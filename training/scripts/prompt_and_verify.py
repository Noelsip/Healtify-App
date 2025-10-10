#!/usr/bin/env python3
"""
prompt_and_verify.py (refactor)

Versi yang diperbaiki:
- Menambahkan seleksi top-k relevan dari hasil fetch (title+abstract embedding)
- Menambahkan fallback cepat: ingest abstract/title sebagai chunk untuk retriever
- Komentar jelas pada fungsi agar mudah dimengerti
- Robust error handling saat memanggil LLM / DB / pipeline
"""

import os
import re
import json
import time
import uuid
import argparse
import sys
import traceback
from typing import List, Dict, Any, Optional

# third-party
from dotenv import load_dotenv
from google import genai
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector

# project modules (pastikan modul-modul ini ada di repo Anda)
import fetch_sources as fs
import prepare_and_run_loader as pr
import process_raw as praw
import ingest_chunks_to_pg as ic
import chunk_and_embed as cae
from ingest_chunks_to_pg import connect_db, DB_TABLE
from chunk_and_embed import embed_texts_gemini

# --- Setup environment & client ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, REPO_ROOT)

load_dotenv(dotenv_path=os.path.join(REPO_ROOT, ".env"))

# Initialize Gemini client (tries to reuse client from chunk_and_embed if exported there)
try:
    client = getattr(cae, "client", None)
except Exception:
    client = None

if client is None:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY tidak ditemukan di environment variables atau .env file.")
    client = genai.Client(api_key=GEMINI_API_KEY)

# Quick DB sanity check (optional; will error early if DB not reachable)
try:
    conn = connect_db()
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {DB_TABLE};")
        cnt = cur.fetchone()
        print("[DB] rows in embeddings table:", cnt)
    conn.close()
except Exception as e:
    print("[DB] Warning: tidak dapat melakukan pengecekan awal ke DB:", str(e))

# --- Prompt header ---
PROMPT_HEADER = """
Anda adalah sistem verifikasi fakta medis berdasarkan literatur ilmiah. Analisis klaim berikut dengan cermat menggunakan bukti-bukti dari jurnal dan dokumen ilmiah yang tersedia.

INSTRUKSI DETAIL:
(terjemahan singkat -- lihat komentar kode untuk detail)
...
FORMAT OUTPUT (HANYA JSON VALID - TANPA KOMENTAR):
{ ... }  # (sama seperti versi Anda sebelumnya)
"""

# ---------------------------
# Utility functions
# ---------------------------

def _safe_cos_sim(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors represented as lists.
       Returns similarity in [-1,1]. Handles zero vectors safely.
    """
    try:
        import math
        dot = 0.0
        na = 0.0
        nb = 0.0
        for x, y in zip(a, b):
            dot += float(x) * float(y)
            na += float(x) * float(x)
            nb += float(y) * float(y)
        if na <= 0 or nb <= 0:
            return 0.0
        return dot / (math.sqrt(na) * math.sqrt(nb))
    except Exception:
        return 0.0

def distance_to_similarity(dist: Optional[float]) -> float:
    """Convert vector distance (Postgres <-> operator) to a similarity-like score in (0,1]."""
    if dist is None:
        return 0.0
    try:
        val = float(dist)
        return 1.0 / (1.0 + val)
    except Exception:
        return 0.0

# ---------------------------
# DB retrieval
# ---------------------------

def retrieve_neighbors_from_db(query_embedding: List[float], k: int = 5, max_chars_each: int = 1200, debug_print: bool = False) -> List[Dict[str, Any]]:
    """
    Ambil k nearest neighbors dari tabel DB dengan metadata lengkap (doi, safe_id, teks).
    Mengembalikan list dict: doc_id, safe_id, source_file, chunk_index, n_words, text, doi, distance
    """
    conn = connect_db()
    try:
        try:
            register_vector(conn)
        except Exception:
            pass

        emb_str = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"

        sql = f"""
            SELECT doc_id, safe_id, source_file, chunk_index, n_words, text, doi,
                   embedding <-> %s::vector AS distance
            FROM {DB_TABLE}
            WHERE embedding IS NOT NULL
            ORDER BY distance
            LIMIT %s;
        """

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (emb_str, k))
            rows = cur.fetchall()

    finally:
        conn.close()

    if debug_print:
        if not rows:
            print("[DEBUG] Query returned 0 rows.")
        else:
            r0 = rows[0]
            print("[DEBUG] rows[0] dengan DOI:", r0.get('doi', 'No DOI'))

    out = []
    for r in rows:
        txt = (r.get("text") or "").replace("\n", " ").strip()[:max_chars_each]
        raw_dist = r.get("distance")
        # distance sometimes returned in DB-specific form: normalize to float if possible
        dist_val = None
        try:
            dist_val = float(raw_dist) if raw_dist is not None else None
        except Exception:
            try:
                dist_val = float(raw_dist[0]) if isinstance(raw_dist, (list, tuple)) and len(raw_dist) > 0 else None
            except Exception:
                dist_val = None

        out.append({
            "doc_id": r.get("doc_id"),
            "safe_id": r.get("safe_id"),
            "source_file": r.get("source_file"),
            "chunk_index": r.get("chunk_index"),
            "n_words": r.get("n_words"),
            "text": txt,
            "doi": r.get("doi", "") or "",
            "distance": dist_val
        })
    return out

# ---------------------------
# Prompt builder & LLM call
# ---------------------------

def build_prompt(claim: str, neighbors: List[Dict[str, Any]], max_context_chars: int = 2500) -> str:
    """
    Membangun prompt RAG: sertakan metadata (safe_id, DOI jika ada, file) dan potongan teks.
    Batasi panjang konteks agar LLM tidak kelebihan token.
    """
    parts = []
    total = 0
    for nb in neighbors:
        doi = nb.get('doi', '') or ''
        safe_id = nb.get('safe_id', '') or nb.get('doc_id', '')
        source_file = nb.get('source_file', '')
        source_info = f"ID: {safe_id}"
        if doi:
            source_info += f" | DOI: {doi}"
        if source_file:
            source_info += f" | File: {source_file}"
        part = f"---\nSumber: {source_info}\nTeks: {nb.get('text', '')}\n"
        if total + len(part) > max_context_chars:
            break
        parts.append(part)
        total += len(part)

    context_block = "\n".join(parts)
    prompt = f"""{PROMPT_HEADER}

KLAIM YANG AKAN DIVERIFIKASI:
"{claim.strip()}"

BUKTI DARI LITERATUR ILMIAH:
{context_block}

ANALISIS DAN RESPOND DALAM FORMAT JSON:"""
    return prompt

def _extract_text_from_model_resp(resp) -> str:
    """Ekstrak teks dari response Gemini SDK (beberapa bentuk)"""
    try:
        if resp is None:
            return ""
        if hasattr(resp, "text"):
            return resp.text
        if hasattr(resp, "candidates") and resp.candidates:
            cand = resp.candidates[0]
            if hasattr(cand, "content"):
                content = cand.content
                if hasattr(content, "parts") and content.parts:
                    return content.parts[0].text
                elif hasattr(content, "text"):
                    return content.text
        if isinstance(resp, dict):
            if "candidates" in resp and resp["candidates"]:
                cand = resp["candidates"][0]
                if "content" in cand:
                    content = cand["content"]
                    if "parts" in content and content["parts"]:
                        return content["parts"][0].get("text", "")
        return str(resp)
    except Exception as e:
        print("[DEBUG] Error extracting text from model response:", e)
        return str(resp)

def call_gemini(prompt: str, model: str = "gemini-2.5-flash", temperature: float = 0.0, max_output_tokens: int = 1200) -> str:
    """
    Panggil Gemini dan pastikan output berupa JSON valid.
    Mencoba beberapa model fallback jika output tidak valid/JSON parsing gagal.
    """
    models_to_try = [model, "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
    for m in models_to_try:
        try:
            resp = client.models.generate_content(
                model=m,
                contents=prompt,
                config={
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens,
                    "response_mime_type": "application/json",
                    "candidate_count": 1
                }
            )
            text = _extract_text_from_model_resp(resp)
            if not text or not text.strip():
                continue
            # try parse JSON quick check
            t = text.strip()
            try:
                json.loads(t)
                return t
            except json.JSONDecodeError:
                # try strip markdown fences and retry
                t2 = t.replace("```json", "").replace("```", "").strip()
                try:
                    json.loads(t2)
                    return t2
                except Exception:
                    print(f"[DEBUG] model {m} returned non-JSON output (len {len(t)}). Trying next model.")
                    continue
        except Exception as e:
            print(f"[DEBUG] call_gemini with model {m} failed:", str(e))
            continue
    raise RuntimeError("Semua model Gemini gagal menghasilkan JSON valid.")

# ---------------------------
# JSON parsing helpers
# ---------------------------

def fix_common_json_issues(json_str: str) -> str:
    """Perbaiki beberapa masalah JSON umum (trailing commas dsb)."""
    s = json_str
    s = re.sub(r',(\s*[}\]])', r'\1', s)  # trailing commas
    # remove control chars
    s = ''.join(ch for ch in s if ord(ch) >= 32 or ch in '\n\r\t')
    return s

def validate_and_normalize_result(result: dict) -> dict:
    """Normalisasi struktur JSON keluaran LLM agar konsisten."""
    if "label" not in result:
        result["label"] = "TIDAK TERDETEKSI"
    label = result["label"].upper().strip()
    if label not in ["VALID", "HOAX", "TIDAK TERDETEKSI"]:
        mapping = {"TIDAK PASTI": "TIDAK TERDETEKSI", "UNCERTAIN": "TIDAK TERDETEKSI",
                   "TRUE": "VALID", "BENAR": "VALID", "FALSE": "HOAX", "SALAH": "HOAX"}
        result["label"] = mapping.get(label, "TIDAK TERDETEKSI")
    result.setdefault("confidence", 0.0)
    result.setdefault("summary", "")
    result.setdefault("evidence", [])
    result.setdefault("references", [])
    result.setdefault("methodology_notes", "")
    result.setdefault("confidence_reasoning", "")
    result["confidence"] = float(result.get("confidence", 0.0))
    # ensure doi fields exist
    for ev in result["evidence"]:
        if isinstance(ev, dict) and "doi" not in ev:
            ev["doi"] = ""
    for ref in result["references"]:
        if isinstance(ref, dict) and "doi" not in ref:
            ref["doi"] = ""
    return result

def extract_json_from_text(text: str) -> Dict[str, Any]:
    """Robust JSON extraction from text produced by LLM."""
    s = text.strip()
    s = s.replace("```json", "").replace("```", "").strip()
    try:
        result = json.loads(s)
        return validate_and_normalize_result(result)
    except json.JSONDecodeError as e1:
        # attempt to extract the first {...} balanced block
        start = -1
        brace = 0
        for i, ch in enumerate(s):
            if ch == "{":
                if start == -1:
                    start = i
                brace += 1
            elif ch == "}":
                brace -= 1
                if brace == 0 and start != -1:
                    candidate = s[start:i+1]
                    try:
                        result = json.loads(candidate)
                        return validate_and_normalize_result(result)
                    except Exception:
                        # try fixes
                        candidate_fixed = fix_common_json_issues(candidate)
                        try:
                            result = json.loads(candidate_fixed)
                            return validate_and_normalize_result(result)
                        except Exception:
                            break
        # all attempts failed -> return default
        print("[WARNING] Tidak dapat parse JSON output LLM. Mengembalikan default response.")
        return {
            "label": "TIDAK TERDETEKSI",
            "confidence": 0.0,
            "summary": "Gagal memproses response dari LLM.",
            "evidence": [],
            "references": [],
            "methodology_notes": "Error parsing LLM response",
            "confidence_reasoning": "Parsing failure",
            "notes": f"Raw response preview: {s[:400]}"
        }

# ---------------------------
# Dynamic fetch + selection + fast ingest
# ---------------------------

def _flatten_fetched_results(fetched_results: List[Any]) -> List[Dict[str, Any]]:
    """
    Flatten results from different fetch_* functions to a unified list of dicts containing:
    { 'title', 'abstract', 'url', 'doi', 'source' }
    Each fetch_* in your repo should ideally return list of dicts or dict; this helper tolerates a few shapes.
    """
    flat = []
    for batch in fetched_results:
        if not batch:
            continue
        # if it's a dict (single result), convert to list
        if isinstance(batch, dict):
            items = [batch]
        else:
            items = list(batch)
        for it in items:
            # try common keys
            title = it.get("title") or it.get("paperTitle") or it.get("name") or ""
            abstract = it.get("abstract") or it.get("summary") or it.get("description") or ""
            url = it.get("url") or it.get("pdf_url") or it.get("pdf") or it.get("link") or ""
            doi = it.get("doi") or it.get("paperId") or it.get("id") or ""
            flat.append({
                "title": str(title).strip(),
                "abstract": str(abstract).strip(),
                "url": str(url).strip(),
                "doi": str(doi).strip(),
                "raw": it
            })
    return flat

def _write_selected_to_raw_selected(selected: List[Dict[str, Any]]):
    """
    Tulis selected items ke folder `data/raw_selected/` sebagai JSON agar prepare_and_run_loader
    dapat memproses hanya dokumen ini.
    """
    os.makedirs("data/raw_selected", exist_ok=True)
    for s in selected:
        key = (s.get("doi") or s.get("url") or s.get("title") or str(uuid.uuid4()))[:120]
        safe_name = re.sub(r"[^\w\-_.]", "_", key)[:80]
        path = os.path.join("data", "raw_selected", safe_name + ".json")
        with open(path, "w", encoding="utf-8") as fo:
            json.dump(s, fo, ensure_ascii=False, indent=2)

def ingest_abstracts_as_chunks(selected_items: List[Dict[str, Any]]):
    """
    FAST FALLBACK:
    - Ambil title + abstract dari selected_items
    - Embed teks tersebut (embed_texts_gemini)
    - Buat file JSONL di data/chunks/ dengan field embedding sehingga ingest() bisa langsung memprosesnya
    - Panggil ic.ingest() untuk memasukkan ke DB
    Catatan: fungsi ini membuat chunk singkat (title+abstract) — berguna untuk respons cepat.
    """
    if not selected_items:
        return False

    os.makedirs("data/chunks", exist_ok=True)
    records = []
    texts = []
    metas = []
    for it in selected_items:
        text = (it.get("title","") + "\n\n" + it.get("abstract","")).strip()
        if not text:
            continue
        texts.append(text)
        metas.append({"safe_id": it.get("doi") or it.get("url") or str(uuid.uuid4()),
                      "doi": it.get("doi",""),
                      "source": it.get("url","") or it.get("raw","")})
    if not texts:
        return False

    # embed in batches using the project's embed function
    try:
        vecs = embed_texts_gemini(texts)
    except Exception as e:
        print("[FAST_INGEST] Error embedding abstracts:", e)
        return False

    # write a single jsonl file with all records
    out_fname = f"abstract_chunks_{int(time.time())}.jsonl"
    out_path = os.path.join("data", "chunks", out_fname)
    with open(out_path, "w", encoding="utf-8") as fo:
        for text, meta, vec in zip(texts, metas, vecs):
            rec = {
                "id": str(uuid.uuid4()),
                "text": text,
                "meta": meta,
                "embedding": list(vec) if hasattr(vec, "__iter__") else vec
            }
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[FAST_INGEST] Wrote {len(texts)} abstract chunks to {out_path}")

    # now call ingest() — it expects data/chunks/*.jsonl
    try:
        ic.ingest()
    except Exception as e:
        print("[FAST_INGEST] ingest() failed:", e)
        return False

    return True

def dynamic_fetch_and_update(claim: str,
                             max_fetch_results: int = 10,
                             top_k_select: int = 8,
                             embed_batch_size: int = 32,
                             do_full_download: bool = False):
    """
    Dynamic fetch pipeline:
    1) fetch from multiple sources (PubMed, CrossRef, Semantic Scholar)
    2) flatten results and compute embeddings for title+abstract (fast)
    3) select top_k most similar to the claim
    4) if do_full_download=True -> write selected to data/raw_selected and call prepare_and_run_loader -> full chunk+embed -> ingest
       else -> FAST fallback: embed title+abstract -> write to data/chunks -> ingest directly
    Returns True jika ada update (chunks ingested), False otherwise.
    """
    print("[DYNAMIC_FETCH] Start dynamic fetch for claim:", claim[:120])
    fetched = []
    # Attempt fetch from each source but tolerate failures
    try:
        try:
            res_pub = fs.fetch_pubmed(claim, maximum_results=max_fetch_results)
            if res_pub:
                fetched.append(res_pub)
        except Exception as e:
            print("[DYNAMIC_FETCH] fetch_pubmed failed:", e)
        time.sleep(0.5)

        try:
            res_x = fs.fetch_crossref(claim, rows=max_fetch_results)
            if res_x:
                fetched.append(res_x)
        except Exception as e:
            print("[DYNAMIC_FETCH] fetch_crossref failed:", e)
        time.sleep(0.5)

        try:
            res_s2 = fs.fetch_semantic_scholar(claim, limit=max_fetch_results)
            if res_s2:
                fetched.append(res_s2)
        except Exception as e:
            print("[DYNAMIC_FETCH] fetch_semantic_scholar failed:", e)
    except Exception as e:
        print("[DYNAMIC_FETCH] Unexpected error during fetch step:", e)

    items = _flatten_fetched_results(fetched)
    if not items:
        print("[DYNAMIC_FETCH] No fetched items found.")
        return False

    # prepare texts for embedding: title + first 250-400 chars of abstract
    cand_texts = []
    cand_meta = []
    for it in items:
        t = (it.get("title","") + "\n\n" + (it.get("abstract","")[:1200] or "")).strip()
        if not t:
            continue
        cand_texts.append(t)
        cand_meta.append(it)

    if not cand_texts:
        print("[DYNAMIC_FETCH] No candidate texts available for embedding.")
        return False

    # embed claim and candidates (batched)
    try:
        claim_vec = embed_texts_gemini([claim])[0]
    except Exception as e:
        print("[DYNAMIC_FETCH] Error embedding claim:", e)
        return False

    try:
        cand_vecs = embed_texts_gemini(cand_texts)
    except Exception as e:
        print("[DYNAMIC_FETCH] Error embedding candidate texts:", e)
        return False

    # compute similarities and select top_k
    sims = [_safe_cos_sim(claim_vec, v) for v in cand_vecs]
    idx_sorted = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)[:top_k_select]
    selected = [cand_meta[i] for i in idx_sorted]
    selected_scores = [sims[i] for i in idx_sorted]
    print(f"[DYNAMIC_FETCH] Selected top {len(selected)} items (example scores): {selected_scores[:5]}")

    # Option A: full pipeline for selected documents (download PDFs, chunk+embed, ingest)
    if do_full_download:
        print("[DYNAMIC_FETCH] Running full pipeline (download PDFs -> chunk+embed -> ingest) for selected items.")
        _write_selected_to_raw_selected(selected)
        try:
            pr.main(dry_run=False)  # prepare & loader will read from data/raw_selected
        except Exception as e:
            print("[DYNAMIC_FETCH] prepare_and_run_loader failed:", e)
        try:
            # run chunk+embed but restrict to processed (prepare_and_run_loader produced processed files)
            cae.process_and_embed_all(
                embed_fn=cae.embed_texts_gemini,
                words_per_chunk=300,
                overlap_words=30,
                save_jsonl=True,
                batch_size=embed_batch_size
            )
        except Exception as e:
            print("[DYNAMIC_FETCH] chunk_and_embed failed:", e)
        try:
            ic.ingest()
            print("[DYNAMIC_FETCH] Full pipeline ingest completed.")
            return True
        except Exception as e:
            print("[DYNAMIC_FETCH] ingest failed after full pipeline:", e)
            return False

    # Option B (recommended default): FAST fallback ingest abstracts as chunks
    print("[DYNAMIC_FETCH] Running FAST fallback: ingest title+abstract as chunks (no PDF download).")
    ok = ingest_abstracts_as_chunks(selected)
    if ok:
        print("[DYNAMIC_FETCH] Fast ingest succeeded.")
        return True
    else:
        print("[DYNAMIC_FETCH] Fast ingest failed; attempting full pipeline as last resort.")
        # try full pipeline as last resort
        try:
            _write_selected_to_raw_selected(selected)
            pr.main(dry_run=False)
            cae.process_and_embed_all(
                embed_fn=cae.embed_texts_gemini,
                words_per_chunk=300,
                overlap_words=30,
                save_jsonl=True,
                batch_size=embed_batch_size
            )
            ic.ingest()
            return True
        except Exception as e:
            print("[DYNAMIC_FETCH] Full pipeline fallback failed:", e)
            return False

# ---------------------------
# Main orchestration: verify_claim_local
# ---------------------------

def verify_claim_local(claim: str, k: int = 5, dry_run: bool = False) -> Dict[str, Any]:
    """
    Main flow:
    - embed claim
    - retrieve neighbors
    - if none or low-quality neighbors: dynamic_fetch_and_update -> retry retrieve
    - build prompt and call LLM, parse JSON response
    - enrich response with DOI & meta from neighbors
    """
    claim = claim.strip()
    if not claim:
        raise ValueError("Klaim kosong.")

    try:
        print("[1/5] Membuat embedding klaim...")
        emb_list = embed_texts_gemini([claim])
        if not emb_list or not isinstance(emb_list[0], (list, tuple)):
            raise RuntimeError("Gagal membuat embedding klaim.")
        query_emb = emb_list[0]

        print(f"[2/5] Mengambil {k} terkait dari database...")
        neighbors = retrieve_neighbors_from_db(query_emb, k=k, debug_print=True)

        # If no neighbors or neighbors have low relevance, attempt dynamic fetch
        need_dynamic = (not neighbors) or (len([n for n in neighbors if n.get("doi")]) == 0)
        if need_dynamic:
            print("[INFO] Tidak cukup neighbors (atau belum ada DOI). Mencoba dynamic fetch & ingest...")
            try:
                did_update = dynamic_fetch_and_update(claim, max_fetch_results=10, top_k_select=8,
                                                     embed_batch_size=32, do_full_download=False)
                if did_update:
                    # small pause to ensure DB commits are visible
                    time.sleep(1.5)
                    neighbors = retrieve_neighbors_from_db(query_emb, k=k, debug_print=True)
                    if neighbors:
                        print("[INFO] Found neighbors after dynamic fetch.")
                    else:
                        print("[INFO] Masih tidak ada neighbors setelah dynamic fetch.")
                else:
                    print("[INFO] dynamic_fetch_and_update returned False (no new data).")
            except Exception as e:
                print("[ERROR] dynamic_fetch_and_update exception:", e)
                traceback.print_exc()

        if not neighbors:
            # fallback response (no evidence)
            return {
                "label": "TIDAK TERDETEKSI",
                "confidence": 0.0,
                "summary": "Tidak ditemukan dokumen relevan di database untuk memverifikasi klaim ini.",
                "evidence": [],
                "references": [],
                "methodology_notes": "Database tidak mengandung dokumen yang relevan",
                "confidence_reasoning": "Tidak ada bukti ilmiah yang tersedia untuk analisis",
            }

        if dry_run:
            print("=== Dry Run: Neighbors list ===")
            for n in neighbors:
                doi_info = f" (DOI: {n.get('doi','')})" if n.get('doi') else ""
                print(f"{n.get('safe_id')} {doi_info} dist={n.get('distance')}")
                print(f"  Preview: {n.get('text','')[:200]}...\n")
            return {"dry_run_neighbors": neighbors}

        print("[3/5] Membangun prompt RAG...")
        prompt = build_prompt(claim, neighbors)
        print(f"[DEBUG] Prompt length: {len(prompt)} chars")

        print("[4/5] Memanggil LLM (Gemini) untuk verifikasi...")
        raw = call_gemini(prompt, temperature=0.0, max_output_tokens=1500)

        print("[5/5] Memparsing hasil...")
        parsed = extract_json_from_text(raw)

        # enrich evidence & references with DOI and snippet from neighbors
        nb_map = {n.get("safe_id") or str(n.get("doc_id")): n for n in neighbors}
        evlist = parsed.get("evidence", []) or []
        references = []
        for ev in evlist:
            sid = ev.get("safe_id")
            nb = nb_map.get(sid)
            if nb:
                ev["source_snippet"] = nb.get("text","")[:400]
                ev["doi"] = nb.get("doi","") or ev.get("doi","")
                ref_entry = {"safe_id": sid, "doi": ev.get("doi",""), "source_type": "journal" if ev.get("doi") else "other"}
                if ref_entry not in references:
                    references.append(ref_entry)

        parsed["references"] = references

        # compute retriever mean & combined confidence
        sim_scores = []
        for n in neighbors:
            sim_scores.append(distance_to_similarity(n.get("distance")))
        retriever_mean = float(sum(sim_scores) / len(sim_scores)) if sim_scores else 0.0
        llm_confidence = float(parsed.get("confidence") or 0.0)
        combined_confidence = 0.7 * llm_confidence + 0.3 * retriever_mean

        parsed["_meta"] = {
            "neighbors_count": len(neighbors),
            "neighbors_with_doi": len([n for n in neighbors if n.get("doi")]),
            "retriever_mean": retriever_mean,
            "combined_confidence": combined_confidence,
            "prompt_len_chars": len(prompt),
            "raw_llm_preview": raw[:500] if raw else ""
        }

        # final confidence normalization: prefer combined_confidence if LLM-old value is low
        parsed["confidence"] = float(parsed.get("confidence") or combined_confidence)
        if parsed.get("label") not in ["VALID", "HOAX", "TIDAK TERDETEKSI"]:
            parsed["label"] = "TIDAK TERDETEKSI"

        return parsed

    except Exception as e:
        print("[ERROR] Exception in verify_claim_local:", str(e))
        traceback.print_exc()
        # raise again so CLI can handle exit code if desired
        raise

# ---------------------------
# CLI entrypoint
# ---------------------------

def main():
    ap = argparse.ArgumentParser(description="Prompt & verify (local) - Healthify RAG helper")
    ap.add_argument("--claim", "-c", type=str, help="Klaim teks yang ingin diverifikasi (atau kosong untuk mode interaktif)")
    ap.add_argument("--k", "-k", type=int, default=5, help="Jumlah neighbor yg diambil dari vector DB")
    ap.add_argument("--dry-run", action="store_true", help="Tampilkan neighbor saja tanpa memanggil LLM")
    ap.add_argument("--save-json", type=str, default=None, help="Simpan hasil JSON ke file (path)")
    ap.add_argument("--full-download", action="store_true", help="Saat dynamic fetch, lakukan full PDF download+processing (lebih lambat)")
    args = ap.parse_args()

    claim = args.claim
    if not claim:
        print("Masukan klaim (akhiri dengan ENTER): ")
        claim = input("> ").strip()

    try:
        # pass do_full_download from CLI flag to dynamic fetch via verify_claim_local path
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
