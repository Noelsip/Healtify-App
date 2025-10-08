import os
import json
import time
import argparse
import sys
import chunk_and_embed as cae
from google import genai
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector
from typing import List, Dict, Any, Optional
from chunk_and_embed import embed_texts_gemini
from ingest_chunks_to_pg import connect_db, DB_TABLE

# konfigurasi
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, REPO_ROOT)

load_dotenv(dotenv_path=os.path.join(REPO_ROOT, ".env"))

try:
    client = getattr(cae, 'client', None)
except Exception as e:
    client = None

if client is None:
    try:
        load_dotenv(os.path.join(REPO_ROOT, ".env"))
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY tidak ditemukan di environment variables atau .env file.")
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        raise RuntimeError("Gagal menginisialisasi Gemini client. Pastikan GEMINI_API_KEY benar.") from e
    
# prompting untuk instruksi llm
PROMPT_HEADER = """
Konteks: di bawah ini ada potongan teks dari jurnal atau dokumen ilmiah yang relevan.

Tugas Anda:
1. Ringkas setiap bukti (1–2 kalimat).
2. Tentukan posisi setiap bukti terhadap klaim: gunakan hanya salah satu dari: "support", "contradict", atau "neutral".
3. Berdasarkan semua bukti, tentukan:
   - label akhir klaim: "Valid", "Hoax", atau "Tidak Pasti".
   - nilai confidence (0–1), di mana 1 berarti sangat yakin.
4. Cantumkan sumber (safe_id) dari setiap bukti.

Format keluaran yang WAJIB Anda berikan hanya berupa JSON valid seperti ini:
{
  "label": "Valid|Hoax|Tidak Pasti",
  "confidence": 0.0,
  "summary": "Ringkasan keseluruhan (maks 120 kata)",
  "evidence": [
    {"safe_id": "...", "summary": "...", "stance": "support|contradict|neutral"}
  ],
  "notes": "Alasan singkat (opsional)"
}

Jangan menambahkan teks lain di luar JSON.
"""

# ---------------- fungsi retrieval yang lebih defensif + debug ----------------
def retrieve_neighbors_from_db(query_embedding: List[float], k: int = 5, max_chars_each: int = 1000, debug_print: bool = False) -> List[Dict[str, Any]]:
    """
    Ambil k nearest neighbors dari tabel DB (pgvector) - versi defensif.
    - Jika kolom 'distance' datang sebagai tuple/list/obj, kita ekstrak numeric pertama.
    - Jika debug_print True, print rows[0] untuk membantu diagnosis.
    """
    conn = connect_db()
    try:
        # pastikan pgvector ter-registered pada koneksi ini
        try:
            register_vector(conn)
        except Exception:
            pass

        # format embedding sebagai string seperti "[0.1,0.2,...]" (cara yang sebelumnya bekerja)
        emb_str = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"

        sql = f"""
            SELECT doc_id, safe_id, source_file, chunk_index, n_words, text,
                   embedding <-> %s::vector AS distance
            FROM {DB_TABLE}
            ORDER BY distance
            LIMIT %s;
        """

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (emb_str, k))
            rows = cur.fetchall()
    finally:
        conn.close()

    # Debug: tunjukkan bentuk baris pertama jika diminta
    if debug_print:
        if not rows:
            print("[DEBUG] Tidak ada row dikembalikan oleh query.")
        else:
            print("[DEBUG] bentuk rows[0]:")
            # print full repr and types of each value
            r0 = rows[0]
            print(repr(r0))
            for key, val in r0.items():
                print(f"  - {key}: type={type(val)}, repr={repr(val)[:200]}")

    out = []
    for r in rows:
        txt = (r.get("text") or "").replace("\n", " ").strip()[:max_chars_each]
        raw_dist = r.get("distance")

        # Normalisasi raw_dist ke float bila memungkinkan
        dist_val = None
        try:
            # if it's numeric already
            if isinstance(raw_dist, (float, int)):
                dist_val = float(raw_dist)
            # if it's a tuple/list like (x,) or [x], extract first numeric element
            elif isinstance(raw_dist, (tuple, list)) and len(raw_dist) > 0 and isinstance(raw_dist[0], (float, int)):
                dist_val = float(raw_dist[0])
            # if it's some object exposing a[0] or .value (try common patterns)
            else:
                # try indexing
                try:
                    maybe0 = raw_dist[0]
                    if isinstance(maybe0, (float, int)):
                        dist_val = float(maybe0)
                except Exception:
                    # try attribute .value or .item
                    try:
                        if hasattr(raw_dist, "value"):
                            dist_val = float(raw_dist.value)
                        elif hasattr(raw_dist, "item"):
                            v = raw_dist.item()
                            if isinstance(v, (float, int)):
                                dist_val = float(v)
                    except Exception:
                        dist_val = None
        except Exception:
            dist_val = None

        out.append({
            "doc_id": r.get("doc_id"),
            "safe_id": r.get("safe_id"),
            "source_file": r.get("source_file"),
            "chunk_index": r.get("chunk_index"),
            "n_words": r.get("n_words"),
            "text": txt,
            "distance": dist_val
        })
    return out


# menggabungkan prompt, klaim, dan potongan konteks
def build_prompt(claim: str, neighbors: List[Dict[str, Any]], max_context_chars: int = 2000) -> str:
    parts = []
    total = 0

    for nb in neighbors:
        part = f"---\nSumber: {nb.get('safe_id')}\nTeks: {nb.get('text')}\n"
        if total + len(part) > max_context_chars:
            break
        parts.append(part)
        total += len(part)
    context_block = "\n".join(parts)
    prompt = PROMPT_HEADER + "\nKlaim: " + claim.strip() + "\n\nKonteks yang diambil:\n" + context_block + "\n\nJawab sekarang:"
    return prompt

# memanggil llm dengan prompt
def call_gemini(prompt: str, model: str = "gemini-1.0", temperature: float = 0.0, max_output_tokens: int = 800) -> str:
    response = client.responses.create(
        model=model,
        input=prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    if hasattr(response, "output_text"):
        return response.output_text
    if hasattr(response, "output") and isinstance(response.output, str):
        return response.output
    if isinstance(response, dict) and "output" in response:
        return response["output"]
    
    # try candidates
    try:
        candidates = getattr(response, "candidates", None) or response.get("candidates", [])
        texts = []
        for c in candidates:
            if isinstance(c, dict) and "content" in c:
                texts.append(c["content"])
        if texts:
            return "\n".join(texts)
    except Exception:
        pass
    # fallback
    return str(response)

# parsing output llm menjadi json
def extract_json_from_text(text: str) -> Dict[str, Any]:
    s = text.strip()
    try:
        return json.loads(s)
    except Exception as e:
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = s[start:end+1]
            try:
                return json.loads(candidate)
            except Exception as e2:
                raise ValueError("Gagal parse JSON dari LLM: " + str(e2) + "\nCandidate preview: " + candidate[:300])
    raise ValueError("Tidak menemukan JSON valid di output LLM.")


# small utility 
def distance_to_similarity(dist: Optional[float]) -> float:
    if dist is None:
        return 0.0
    return 1.0 / (1.0 + dist)

# orchestration utama
def verify_claim_local (claim: str, k: int = 5, dry_run: bool = False) -> Dict[str, Any]:
    claim = claim.strip()
    if not claim:
        raise ValueError("Klaim kosong.")
    
    # embed klaim
    print("[1/5] Membuat embedding klaim...")
    emb_list = embed_texts_gemini([claim])

    if not emb_list or not isinstance(emb_list[0], list):
        raise RuntimeError("Gagal membuat embedding klaim.")
    query_emb = emb_list[0]

    # retrieve neighbors dari db
    print(f"[2/5] Mengambil {k} terkait dari database...")
    neighbors = retrieve_neighbors_from_db(query_emb, k=k)
    if dry_run:
        print("=== Dry Run: Neighbors list ===")
        for n in neighbors:
            print(f"{n['safe_id']}  (dist: {n['distance']} preview: {n['text'][:200]})")
        return {"dry_run_neighbors": neighbors}

    # build prompt
    print("[3/5] Membangun prompt RAG...")
    prompt = build_prompt(claim, neighbors)

    # call llm
    print("[4/5] Memanggil LLM(Gemini) untuk verifikasi...")
    raw = call_gemini(prompt, temperature=0.0, max_output_tokens=800)

    # parse JSON
    print("[5/5] Memparsing hasil...")
    parsed = extract_json_from_text(raw)

    # memperbanyak bukti dengan similarity
    sim_scores = []
    nb_map = {n["safe_id"]: n for n in neighbors}
    evlist = parsed.get("evidence") or []
    for ev in evlist:
        sid = ev.get("safe_id")
        if sid and sid in nb_map:
            ev["source_snippet"] = nb_map[sid]["text"][:400]
            sim_scores.append(distance_to_similarity(nb_map[sid].get("distance")))
    
    # fallback jika tidak ada bukti dari llm
    if not sim_scores and neighbors:
        sim_scores = [distance_to_similarity(n.get("distance")) for n in neighbors]


    retriever_mean = float(sum(sim_scores) / len(sim_scores)) if sim_scores else 0.0
    llm_confidence = float(parsed.get("confidence") or 0.0)
    combined_confidence = 0.7 * llm_confidence + 0.3 * retriever_mean

    parsed["_meta"] = {
        "neighbors_count": len(neighbors),
        "retriever_mean": retriever_mean,
        "combined_confidence": combined_confidence,
        "prompt_len_chars": len(prompt),
        "raw_llm_preview": raw[:2000]
    }

    # normalisasi label
    parsed['confidence'] = float(parsed.get('confidence') or combined_confidence)
    parsed['label'] = parsed.get('label') or "Tidak Pasti"

    return parsed

def main():
    ap = argparse.ArgumentParser(description="Prompt & verify (local) - Healthify RAG helper")
    ap.add_argument("--claim", "-c", type=str, help="Klaim teks yang ingin diverifikasi (atau kosong untuk mode interaktif)")
    ap.add_argument("--k", "-k", type=int, default=5, help="Jumlah neighbor yg diambil dari vector DB")
    ap.add_argument("--dry-run", action="store_true", help="Tampilkan neighbor saja tanpa memanggil LLM")
    ap.add_argument("--save-json", type=str, default=None, help="Simpan hasil JSON ke file (path)")
    args = ap.parse_args()

    claim = args.claim
    if not claim:
        print("Masukan klaim (akhiri dengan ENTER): ")
        claim = input("> ").strip()

    try:
        result = verify_claim_local(claim, k=args.k, dry_run=args.dry_run)
    except Exception as e:
        print("Gagal verifikasi klaim:", str(e))
        sys.exit(1)

    pretty = json.dumps(result, indent=2, ensure_ascii=False)
    print("=== Hasil Verifikasi ===")
    print(pretty)

    if args.save_json:
        with open(args.save_json, "w", encoding="utf-8") as fo:
            json.dump(result, fo, ensure_ascii=False, indent=2)
        print(f"Hasil disimpan di {args.save_json}")
    print("Selesai.")

if __name__ == "__main__":
    main()