#!/usr/bin/env python3
"""
prompt_and_verify.py (FINAL UPDATED)

Perubahan utama:
- Robust bilingual retrieval + translation fallback
- Output JSON konsisten untuk frontend (dicetak ke stdout)
- Hanya dua label akhir: VALID atau HOAX
- Kesimpulan / synthesis otomatis dari bukti
- Robust handling: None responses dari LLM, rate-limit handling
"""

import os
import re
import json
import time
import uuid
import pathlib
import argparse
import sys
import traceback
from typing import List, Dict, Any, Optional

# third-party
from dotenv import load_dotenv
from google import genai
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector

# project modules (ensure these exist in repo)
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

try:
    client = getattr(cae, "client", None)
except Exception:
    client = None

if client is None:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY tidak ditemukan di environment variables atau .env file.")
    client = genai.Client(api_key=GEMINI_API_KEY)

# Quick DB sanity check
try:
    conn = connect_db()
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {DB_TABLE};")
        cnt = cur.fetchone()
        print(f"[DB] rows in embeddings table: {cnt}")
    conn.close()
except Exception as e:
    print(f"[DB] Warning: tidak dapat melakukan pengecekan awal ke DB: {str(e)}")

# -------------------------
# Utilities: extraction & safe text handling
# -------------------------
def _extract_text_from_model_resp(resp) -> str:
    try:
        if resp is None:
            return ""
        # genai response object variants
        if hasattr(resp, "text"):
            return resp.text or ""
        if hasattr(resp, "candidates") and resp.candidates:
            cand = resp.candidates[0]
            if hasattr(cand, "content"):
                content = cand.content
                if hasattr(content, "parts") and content.parts:
                    # content.parts may be list of objects with .text
                    part = content.parts[0]
                    return getattr(part, "text", "") or ""
                elif hasattr(content, "text"):
                    return content.text or ""
            # fallback candidate properties
            return getattr(cand, "text", "") or ""
        if isinstance(resp, dict):
            # dict form (older clients / debug)
            if "candidates" in resp and resp["candidates"]:
                cand = resp["candidates"][0]
                content = cand.get("content", {})
                if isinstance(content, dict) and "parts" in content and content["parts"]:
                    return content["parts"][0].get("text", "") or ""
                if isinstance(cand, dict) and "output" in cand:
                    return cand["output"]
            # last resort try 'text'
            return str(resp.get("text", "")) if isinstance(resp, dict) else str(resp)
        return str(resp)
    except Exception:
        try:
            return str(resp)
        except Exception:
            return ""

def safe_strip(s):
    try:
        if s is None:
            return ""
        return str(s).strip()
    except Exception:
        return ""

# -------------------------
# Translation & query generation (robust)
# -------------------------
def translate_text_gemini(text: str, target_lang: str = "English") -> str:
    """
    Terjemahkan text ke target_lang menggunakan Gemini.
    Defensive: handle None / non-string responses.
    """
    if not text:
        return ""
    prompt = f"Translate the following text to {target_lang}. Keep it concise and preserve medical terminology when possible.\n\nText:\n\"\"\"\n{text}\n\"\"\"\n\nOutput only the translated text."
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 256}
        )
        txt = _extract_text_from_model_resp(resp)
        txt = safe_strip(txt)
        txt = txt.replace("```", "")
        return txt or text
    except Exception as e:
        # do not crash on translate failure
        print(f"[TRANSLATE] failed: {e}")
        return text

def generate_bilingual_queries(claim: str, langs: List[str] = ["English"]) -> List[str]:
    """
    Hasilkan daftar variasi query:
      - klaim asli
      - terjemahan ke languages
      - (opsional) variasi dari LLM (tolerant terhadap non-JSON)
    """
    out = []
    claim_clean = safe_strip(claim)
    if claim_clean:
        out.append(claim_clean)

    # Add translations
    for L in langs:
        try:
            tr = translate_text_gemini(claim_clean, target_lang=L)
            tr = safe_strip(tr)
            if tr and tr not in out:
                out.append(tr)
        except Exception:
            pass

    # Ask LLM for variations (but tolerant)
    english_example = out[1] if len(out) > 1 else claim_clean
    syn_prompt = f"""You are a medical search query assistant.
Given the topic below, produce 3-5 short, focused search query variations or keyword phrases researchers would use.
Return a JSON array of strings.

Topic (original): {claim_clean}
Topic (english translation): {english_example}
"""
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=syn_prompt,
            config={"temperature":0.2, "max_output_tokens":300}
        )
        txt = _extract_text_from_model_resp(resp)
        txt = safe_strip(txt)
        arr = []
        # Try parse JSON first
        try:
            if txt:
                arr = json.loads(txt)
        except Exception:
            # tolerant fallback: split lines and strip bullets
            for line in (txt or "").splitlines():
                line = line.strip().lstrip("-• ").strip()
                if line:
                    arr.append(line)
        for q in arr:
            qstr = safe_strip(q)
            if qstr and qstr not in out:
                out.append(qstr)
    except Exception as e:
        print(f"[GEN_QUERIES] failed: {e}")

    # dedupe & limit
    unique = []
    for q in out:
        qn = safe_strip(q)
        if qn and qn not in unique:
            unique.append(qn)
    return unique[:6]

# -------------------------
# Retrieval helpers (unchanged core, defensive)
# -------------------------
def _safe_cos_sim(a: List[float], b: List[float]) -> float:
    try:
        import math
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na <= 0 or nb <= 0:
            return 0.0
        return dot / (na * nb)
    except Exception:
        return 0.0

def distance_to_similarity(dist: Optional[float]) -> float:
    if dist is None:
        return 0.0
    try:
        return 1.0 / (1.0 + float(dist))
    except Exception:
        return 0.0

def retrieve_neighbors_from_db(query_embedding: List[float], k: int = 5, 
                              max_chars_each: int = 1200, 
                              debug_print: bool = False) -> List[Dict[str, Any]]:
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

    if debug_print and rows:
        print(f"[DEBUG] Retrieved {len(rows)} rows, first DOI: {rows[0].get('doi', 'No DOI')}")

    out = []
    for r in rows:
        txt = safe_strip((r.get("text") or "").replace("\n", " "))[:max_chars_each]
        dist_val = None
        try:
            raw_dist = r.get("distance")
            dist_val = float(raw_dist) if raw_dist is not None else None
        except Exception:
            pass

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

def compute_relevance_score(claim: str, neighbor_text: str, neighbor_title: str = "") -> float:
    claim_lower = safe_strip(claim).lower()
    text_lower = safe_strip(neighbor_text).lower()
    title_lower = safe_strip(neighbor_title).lower()

    patterns = [
        r'asam lambung|gastric acid|stomach acid',
        r'perut kosong|empty stomach|fasting|hungry',
        r'diabetes|diabetic',
        r'hipertensi|hypertension|blood pressure',
        r'kolesterol|cholesterol',
        r'jantung|heart|cardiac',
        r'kanker|cancer|tumor',
        r'obesitas|obesity|overweight'
    ]

    keyword_score = 0.0
    for pattern in patterns:
        if re.search(pattern, claim_lower):
            if re.search(pattern, text_lower) or re.search(pattern, title_lower):
                keyword_score += 1.0

    keyword_score = min(keyword_score / len(patterns), 1.0)
    return keyword_score

def filter_by_relevance(claim: str, neighbors: List[Dict[str, Any]], 
                       min_relevance: float = 0.3, debug: bool = False) -> List[Dict[str, Any]]:
    filtered = []
    for nb in neighbors:
        text = nb.get("text", "")
        title = nb.get("title", "") or nb.get("safe_id", "")

        rel_score = compute_relevance_score(claim, text, title)
        dist = nb.get("distance", 1.0)
        dist_score = 1.0 / (1.0 + float(dist)) if dist is not None else 0.5
        combined_score = 0.6 * dist_score + 0.4 * rel_score
        nb["relevance_score"] = combined_score

        if combined_score >= min_relevance:
            filtered.append(nb)
            if debug:
                print(f"[RELEVANCE] Kept doc {nb.get('safe_id')} (score: {combined_score:.3f})")
        else:
            if debug:
                print(f"[RELEVANCE] Filtered out doc {nb.get('safe_id')} (score: {combined_score:.3f})")

    filtered.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return filtered

# -------------------------
# Bilingual retrieval (ID -> EN variations)
# -------------------------
def retrieve_with_expansion_bilingual(claim: str, k: int = 5, 
                                     expand_queries: bool = True, debug: bool = False) -> List[Dict[str, Any]]:
    if expand_queries:
        queries = generate_bilingual_queries(claim, langs=["English"])
    else:
        queries = [claim]

    if debug:
        print(f"[BILINGUAL_QUERIES] Using queries: {queries}")

    all_neighbors = []
    seen_ids = set()
    for query in queries:
        try:
            emb = embed_texts_gemini([query])[0]
        except Exception as e:
            print(f"[RETRIEVE_BIL] embed failed for query '{query}': {e}")
            continue

        neighbors = retrieve_neighbors_from_db(emb, k=k, debug_print=debug)
        for nb in neighbors:
            nb_id = f"{nb.get('doc_id')}_{nb.get('chunk_index')}"
            if nb_id not in seen_ids:
                seen_ids.add(nb_id)
                nb["_matched_query"] = query
                all_neighbors.append(nb)

    filtered = filter_by_relevance(claim, all_neighbors, min_relevance=0.25, debug=debug)
    filtered.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return filtered[:k*3]

# -------------------------
# Dynamic fetch helpers & ingest (unchanged logic but defensive)
# -------------------------
def _load_fetched_file_to_items(path_or_obj):
    items = []
    if isinstance(path_or_obj, dict):
        title = path_or_obj.get("title") or path_or_obj.get("paperTitle") or ""
        abstract = path_or_obj.get("abstract") or path_or_obj.get("summary") or ""
        url = path_or_obj.get("url") or path_or_obj.get("pdf_url") or ""
        doi = path_or_obj.get("doi") or path_or_obj.get("paperId") or ""
        items.append({"title": title, "abstract": abstract, "url": url, "doi": doi})
        return items

    if isinstance(path_or_obj, (list, tuple)):
        for it in path_or_obj:
            items.extend(_load_fetched_file_to_items(it))
        return items

    if isinstance(path_or_obj, str):
        p = pathlib.Path(path_or_obj)
        if not p.exists():
            try:
                obj = json.loads(path_or_obj)
                return _load_fetched_file_to_items(obj)
            except Exception:
                return []
        name = p.name.lower()
        try:
            if name.startswith("crossref") and p.suffix == ".json":
                parsed = praw.parse_crossref_file(p)
                for d in parsed:
                    items.append({"title": d.get("title",""), "abstract": d.get("abstract",""), "url": d.get("url","") if d.get("url") else "", "doi": d.get("doi","")})
                return items
            elif "semantic" in name and p.suffix == ".json":
                parsed = praw.parse_sematic_scholar_file(p)
                for d in parsed:
                    items.append({"title": d.get("title",""), "abstract": d.get("abstract",""), "url": d.get("url","") if d.get("url") else "", "doi": d.get("doi","")})
                return items
            elif "pubmed" in name and p.suffix in [".xml", ".txt"]:
                parsed = praw.parse_pubmed_xml_file(p)
                for d in parsed:
                    items.append({"title": d.get("title",""), "abstract": d.get("abstract",""), "url": d.get("url","") if d.get("url") else "", "doi": d.get("doi","")})
                return items
            else:
                try:
                    obj = json.loads(p.read_text(encoding="utf-8"))
                    return _load_fetched_file_to_items(obj)
                except Exception:
                    return items
        except Exception as e:
            print(f"[_load_fetched_file_to_items] parse error for {p}: {e}")
        return items

    return items

def ingest_abstracts_as_chunks(selected_items: List[Dict[str, Any]]):
    if not selected_items:
        return False

    os.makedirs("data/chunks", exist_ok=True)
    texts = []
    metas = []

    for it in selected_items:
        text = (it.get("title","") + "\n\n" + it.get("abstract","")).strip()
        if not text:
            continue
        texts.append(text)
        metas.append({
            "safe_id": it.get("doi") or it.get("url") or str(uuid.uuid4()),
            "doi": it.get("doi",""),
            # save original fetch URL (if any) so frontend can link back
            "source": it.get("url","") or it.get("source","") or "",
        })

    if not texts:
        return False

    try:
        vecs = embed_texts_gemini(texts)
    except Exception as e:
        print(f"[FAST_INGEST] Error embedding abstracts: {e}")
        return False

    out_fname = f"abstract_chunks_{int(time.time())}.jsonl"
    out_path = os.path.join("data", "chunks", out_fname)

    with open(out_path, "w", encoding="utf-8") as fo:
        for text, meta, vec in zip(texts, metas, vecs):
            rec = {
                "doc_id": meta["safe_id"],
                "safe_id": meta["safe_id"],
                "source_file": "dynamic_fetch",
                "chunk_index": 0,
                "n_words": len(text.split()),
                "text": text,
                "doi": meta["doi"],
                # store original URL in a dedicated field
                "source_url": meta.get("source",""),
                "embedding": list(vec) if hasattr(vec, "__iter__") else vec
            }
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"[FAST_INGEST] Wrote {len(texts)} abstract chunks to {out_path}")

    try:
        ic.ingest()
        time.sleep(1.0)
        return True
    except Exception as e:
        print(f"[FAST_INGEST] ingest() failed: {e}")
        return False


def dynamic_fetch_and_update(claim: str, max_fetch_results: int = 10, 
                            top_k_select: int = 8):
    print(f"[DYNAMIC_FETCH] Fetching for: {claim[:80]}...")
    fetched_paths = []

    try:
        res_pub = fs.fetch_pubmed(claim, maximum_results=max_fetch_results)
        if res_pub:
            fetched_paths.append(res_pub)
        time.sleep(0.3)
    except Exception as e:
        print(f"[DYNAMIC_FETCH] fetch_pubmed failed: {e}")

    try:
        res_x = fs.fetch_crossref(claim, rows=max_fetch_results)
        if res_x:
            fetched_paths.append(res_x)
        time.sleep(0.3)
    except Exception as e:
        print(f"[DYNAMIC_FETCH] fetch_crossref failed: {e}")

    try:
        res_s2 = fs.fetch_semantic_scholar(claim, limit=max_fetch_results)
        if res_s2:
            fetched_paths.append(res_s2)
    except Exception as e:
        print(f"[DYNAMIC_FETCH] fetch_semantic_scholar failed: {e}")

    all_items = []
    for fp in fetched_paths:
        try:
            items = _load_fetched_file_to_items(fp)
            if items:
                all_items.extend(items)
        except Exception as e:
            print(f"[DYNAMIC_FETCH] Error loading fetched file {fp}: {e}")

    if not all_items:
        print("[DYNAMIC_FETCH] No items available after parsing fetched files.")
        return False, []

    cand_texts = []
    cand_meta = []
    for it in all_items:
        t = (it.get("title","") + "\n\n" + (it.get("abstract","") or "")).strip()
        if t:
            cand_texts.append(t)
            cand_meta.append(it)

    if not cand_texts:
        print("[DYNAMIC_FETCH] No candidate texts to embed.")
        return False, []

    try:
        claim_vec = embed_texts_gemini([claim])[0]
        cand_vecs = embed_texts_gemini(cand_texts)
    except Exception as e:
        print(f"[DYNAMIC_FETCH] Embedding failed: {e}")
        return False, []

    sims = [_safe_cos_sim(claim_vec, v) for v in cand_vecs]
    idx_sorted = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)[:top_k_select]
    selected = [cand_meta[i] for i in idx_sorted]

    print(f"[DYNAMIC_FETCH] Selected {len(selected)} items (top sims: {[round(sims[i],3) for i in idx_sorted[:5]]})")

    norm_selected = []
    for s in selected:
        norm_selected.append({
            "title": s.get("title",""),
            "abstract": s.get("abstract",""),
            "url": s.get("url",""),
            "doi": s.get("doi","")
        })

    did_ingest = ingest_abstracts_as_chunks(norm_selected)
    return did_ingest, norm_selected

# -------------------------
# Decide whether dynamic fetch needed
# -------------------------
def needs_dynamic_fetch(neighbors: List[Dict[str, Any]],
                        claim: str,
                        min_relevance_mean: float = 0.30,
                        min_retriever_mean: float = 0.30,
                        min_max_relevance: float = 0.45,
                        debug: bool = False) -> bool:
    if not neighbors:
        if debug:
            print("[QUALITY_CHECK] No neighbors -> need dynamic fetch.")
        return True

    rels = [n.get("relevance_score", 0.0) for n in neighbors if n.get("relevance_score") is not None]
    sims = [distance_to_similarity(n.get("distance")) for n in neighbors if n.get("distance") is not None]

    relevance_mean = float(sum(rels) / len(rels)) if rels else 0.0
    retriever_mean = float(sum(sims) / len(sims)) if sims else 0.0
    max_rel = max(rels) if rels else 0.0

    claim_tokens = set(re.findall(r"[A-Za-zÀ-ÿ0-9]+", safe_strip(claim).lower()))
    def has_keyword_match(text: str) -> bool:
        txt_tokens = set(re.findall(r"[A-Za-zÀ-ÿ0-9]+", safe_strip(text).lower()))
        overlap = [t for t in (claim_tokens & txt_tokens) if len(t) > 2]
        return len(overlap) > 0

    any_keyword = any(has_keyword_match(n.get("text","")) or has_keyword_match(n.get("safe_id","") or "") for n in neighbors)

    if debug:
        print(f"[QUALITY_CHECK] relevance_mean={relevance_mean:.3f}, retriever_mean={retriever_mean:.3f}, max_rel={max_rel:.3f}, any_keyword={any_keyword}")

    if relevance_mean < min_relevance_mean or retriever_mean < min_retriever_mean:
        if debug:
            print("[QUALITY_CHECK] mean scores below threshold -> dynamic fetch recommended")
        return True

    if max_rel < min_max_relevance:
        if debug:
            print("[QUALITY_CHECK] max relevance below threshold -> dynamic fetch recommended")
        return True

    if not any_keyword:
        if debug:
            print("[QUALITY_CHECK] no keyword overlap between claim and neighbors -> dynamic fetch recommended")
        return True

    return False

# -------------------------
# Translate snippets to Indonesian if needed (heuristic)
# -------------------------
def translate_snippets_if_needed(neighbors: List[Dict[str,Any]], target_lang="Indonesian") -> List[Dict[str,Any]]:
    for nb in neighbors:
        txt = nb.get("text","")
        if not txt:
            nb["_text_translated"] = ""
            continue
        eng_words = len(re.findall(r"[a-zA-Z]{4,}", txt))
        id_connectives = len(re.findall(r"\b(dan|yang|dengan|atau|untuk|di)\b", txt.lower()))
        if eng_words > max(5, id_connectives * 3):
            try:
                nb["_text_translated"] = translate_text_gemini(txt, target_lang=target_lang)
            except Exception as e:
                print(f"[TRANSLATE] failed for snippet: {e}")
                nb["_text_translated"] = txt
        else:
            nb["_text_translated"] = txt
    return neighbors

# -------------------------
# Prompt building (user-facing in Indonesian)
# -------------------------
PROMPT_HEADER = """
Anda adalah sistem verifikasi fakta medis yang teliti. Tugas Anda:
1) Evaluasi relevansi bukti terhadap klaim.
2) Jika ada bukti yang mendukung atau menolak klaim, jelaskan dasar keputusan.
3) Output harus JSON dengan fields: claim, analysis, label (VALID/HOAX), confidence (0-1), evidence (list), summary.
"""

def build_prompt(claim: str, neighbors: List[Dict[str, Any]], 
                max_context_chars: int = 3000) -> str:
    parts = []
    total = 0
    for idx, nb in enumerate(neighbors, 1):
        doi = nb.get('doi', '') or ''
        safe_id = nb.get('safe_id', '') or nb.get('doc_id', '')
        source_file = nb.get('source_file', '')
        rel_score = nb.get('relevance_score', 0.0)
        text_for_prompt = nb.get("_text_translated") or nb.get("text","")
        source_info = f"[Bukti #{idx}] ID: {safe_id}"
        if doi:
            source_info += f" | DOI: {doi}"
        if source_file:
            source_info += f" | File: {source_file}"
        source_info += f" | Relevance: {rel_score:.3f}"
        part = f"{source_info}\n{text_for_prompt}\n---\n"
        if total + len(part) > max_context_chars:
            break
        parts.append(part)
        total += len(part)

    context_block = "\n".join(parts)
    prompt = f"""{PROMPT_HEADER}

CLAIM:
"{claim.strip()}"

BUKTI:
{context_block}

Instruksi:
- Evaluasi bukti dan tentukan apakah klaim tersebut didukung (VALID) atau dibantah (HOAX).
- Jelaskan analisis singkat dan sertakan evidence list (id, snippet).
- Kembalikan hanya JSON yang valid dengan fields: claim, analysis, label, confidence, evidence (array of objects with safe_id & snippet), summary.
"""
    return prompt

# -------------------------
# LLM call with fallback
# -------------------------
def call_gemini(prompt: str, model: str = "gemini-2.5-flash-lite", 
               temperature: float = 0.0, max_output_tokens: int = 1200) -> str:
    # try list of models but prefer lite first to reduce quota pressure
    models_to_try = [model, "gemini-2.5-flash", "gemini-2.0-flash"]
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
            text = safe_strip(text)
            if not text:
                continue
            # try to return JSON-like text (strip fences)
            t = text.replace("```json", "").replace("```", "").strip()
            return t
        except Exception as e:
            print(f"[DEBUG] call_gemini with model {m} failed: {str(e)}")
            continue
    raise RuntimeError("All Gemini model calls failed or returned empty.")

def fix_common_json_issues(json_str: str) -> str:
    s = json_str
    s = re.sub(r',(\s*[}\]])', r'\1', s)
    s = ''.join(ch for ch in s if ord(ch) >= 32 or ch in '\n\r\t')
    return s

def validate_and_normalize_result(result: dict) -> dict:
    # normalize keys and map ANY unknown->HOAX (no TIDAK TERDETEKSI)
    result = result or {}
    if "label" not in result:
        result["label"] = "HOAX"
    label = safe_strip(result.get("label", "")).upper()
    if label not in ["VALID", "HOAX"]:
        # map plausible synonyms
        mapping = {
            "TRUE": "VALID",
            "BENAR": "VALID",
            "FALSE": "HOAX",
            "SALAH": "HOAX",
            "UNCERTAIN": "HOAX",
            "TIDAK TERDETEKSI": "HOAX",
            "TIDAK PASTI": "HOAX"
        }
        result["label"] = mapping.get(label, "HOAX")
    result.setdefault("confidence", 0.0)
    # clip/normalize confidence between 0..1
    try:
        cf = float(result.get("confidence", 0.0))
        cf = max(0.0, min(1.0, cf))
    except Exception:
        cf = 0.0
    result["confidence"] = cf
    result.setdefault("analysis", "")
    result.setdefault("evidence", [])
    result.setdefault("summary", "")
    result.setdefault("references", [])
    return result

def extract_json_from_text(text: str) -> Dict[str, Any]:
    s = safe_strip(text)
    if not s:
        return validate_and_normalize_result({})
    # attempt plain json parse
    try:
        parsed = json.loads(s)
        return validate_and_normalize_result(parsed)
    except Exception:
        # try to find first JSON-like object
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
                        parsed = json.loads(candidate)
                        return validate_and_normalize_result(parsed)
                    except Exception:
                        candidate_fixed = fix_common_json_issues(candidate)
                        try:
                            parsed = json.loads(candidate_fixed)
                            return validate_and_normalize_result(parsed)
                        except Exception:
                            pass
        # fallback: return minimal HOAX response
        print("[WARNING] Cannot parse JSON from LLM. Returning default HOAX response.")
        return validate_and_normalize_result({})

# -------------------------
# Synthesis / final decision logic (only VALID/HOAX)
# -------------------------
def decide_final_label_and_summary(parsed: Dict[str,Any], neighbors: List[Dict[str,Any]], combined_confidence: float) -> Dict[str,Any]:
    analysis_text = safe_strip(parsed.get("analysis") or parsed.get("summary") or "")
    analysis_lower = analysis_text.lower()

    # cues (simple)
    support_cues = ["mendukung", "support", "supports", "increases", "associated with", "lebih berisiko", "lebih berbahaya"]
    contradict_cues = ["tidak", "no evidence", "not supported", "insufficient", "does not", "no association", "lack of evidence", "not associated"]

    supports = any(c in analysis_lower for c in support_cues)
    contradicts = any(c in analysis_lower for c in contradict_cues)

    # simple evidence tally (keywords)
    cnt_vape = 0
    cnt_smoke = 0
    for n in neighbors:
        t = safe_strip(n.get("_text_translated") or n.get("text") or "").lower()
        if not t:
            continue
        if re.search(r"\b(vape|e-cigarette|electronic cigarette|e-cig)\b", t):
            if re.search(r"\b(risk|harm|disease|damage|adverse|mortality|injury|tox)\b", t):
                cnt_vape += 1
        if re.search(r"\b(smok|cigarette|tobacco|cigarettes|tobacco smoke)\b", t):
            if re.search(r"\b(risk|harm|disease|damage|adverse|mortality|injury|tox)\b", t):
                cnt_smoke += 1

    parsed_label = safe_strip(parsed.get("label","")).upper()
    # default conservative decision: HOAX
    final_label = "HOAX"
    # if LLM gave VALID or support signals, flip to VALID
    if parsed_label == "VALID" or supports:
        final_label = "VALID"
    else:
        # heuristics using counts + confidence
        if cnt_vape > cnt_smoke and combined_confidence >= 0.45:
            final_label = "VALID"
        elif cnt_smoke > cnt_vape and combined_confidence >= 0.45:
            final_label = "VALID"
        else:
            final_label = "HOAX"

    # final confidence blending
    llm_conf = float(parsed.get("confidence") or 0.0)
    final_conf = max(llm_conf, combined_confidence)
    final_conf = max(0.0, min(1.0, float(final_conf)))

    # build conclusion text
    parts = []
    parts.append(f"{len(neighbors)} dokumen dianalisis.")
    if cnt_vape or cnt_smoke:
        parts.append(f"Bukti terkait vape: {cnt_vape}, bukti terkait rokok: {cnt_smoke}.")
    if supports and not contradicts:
        parts.append("Analisis LLM cenderung mendukung klaim.")
    elif contradicts and not supports:
        parts.append("Analisis LLM cenderung menolak klaim.")
    else:
        parts.append("Tidak ada bukti mayoritas yang jelas; keputusan dibuat berdasarkan gabungan sinyal LLM dan retriever.")
    parts.append("Ringkasan LLM: " + (analysis_text or "").strip()[:600])
    conclusion = " ".join([p for p in parts if p])

    return {"final_label": final_label, "final_confidence": final_conf, "conclusion": conclusion}

# -------------------------
# Main verification flow
# -------------------------
def verify_claim_local(claim: str, k: int = 5, dry_run: bool = False, 
                      enable_expansion: bool = True,
                      min_relevance: float = 0.25,
                      force_dynamic_fetch: bool = False,
                      debug_retrieval: bool = False) -> Dict[str, Any]:
    """
    Main verification flow. Returns dict with key '_frontend_payload' containing
    the JSON-ready payload for frontend display.
    """
    claim = safe_strip(claim)
    if not claim:
        raise ValueError("Klaim kosong.")

    try:
        print("[1/6] Retrieving with bilingual query expansion...")
        if enable_expansion:
            neighbors = retrieve_with_expansion_bilingual(claim, k=k, expand_queries=True, debug=debug_retrieval)
        else:
            emb = embed_texts_gemini([claim])[0]
            neighbors = retrieve_neighbors_from_db(emb, k=k, debug_print=debug_retrieval)
            neighbors = filter_by_relevance(claim, neighbors, min_relevance=min_relevance, debug=debug_retrieval)

        # Decide whether to dynamic fetch
        if force_dynamic_fetch:
            print("[QUALITY_CHECK] Force dynamic fetch requested.")
            quality_need_fetch = True
        else:
            quality_need_fetch = needs_dynamic_fetch(neighbors, claim, min_relevance_mean=min_relevance, min_retriever_mean=0.25, debug=debug_retrieval)

        dyn_selected = None
        if quality_need_fetch:
            print("[2/6] Retrieval quality low or insufficient. Attempting dynamic fetch...")
            try:
                did_update, dyn_selected = dynamic_fetch_and_update(claim, max_fetch_results=30, top_k_select=12)
                if did_update:
                    print("[DYNAMIC_FETCH] Ingest performed. Waiting for DB to be ready...")
                    time.sleep(2.0)
                    # Retry retrieval after ingest
                    if enable_expansion:
                        neighbors = retrieve_with_expansion_bilingual(claim, k=k, expand_queries=True, debug=debug_retrieval)
                    else:
                        emb = embed_texts_gemini([claim])[0]
                        neighbors = retrieve_neighbors_from_db(emb, k=k*2, debug_print=debug_retrieval)
                        neighbors = filter_by_relevance(claim, neighbors, min_relevance=min_relevance, debug=debug_retrieval)

                    if debug_retrieval:
                        print("\n[DEBUG] Neighbors after retry (top 6):")
                        for i, n in enumerate(neighbors[:6], 1):
                            print(f"  [{i}] {n.get('safe_id')} rel={n.get('relevance_score',0):.3f} doi={n.get('doi','')}")
                            print(f"        snippet: {n.get('text','')[:200]}...\n")

                    # If still insufficient, use fetched items as fallback
                    if needs_dynamic_fetch(neighbors, claim, min_relevance_mean=min_relevance, min_retriever_mean=0.25, debug=debug_retrieval):
                        print("[DYNAMIC_FETCH] Retry retrieval after dynamic fetch still low quality.")
                        if dyn_selected:
                            print("[DYNAMIC_FETCH] Using fetched items as fallback context for LLM.")
                            fallback_neighbors = []
                            for idx, s in enumerate(dyn_selected, 1):
                                txt = (s.get("title","") + "\n\n" + s.get("abstract","")).strip()
                                if not txt:
                                    continue
                                fallback_neighbors.append({
                                    "doc_id": s.get("doi") or s.get("url") or f"dyn_{idx}",
                                    "safe_id": s.get("doi") or s.get("url") or f"dyn_{idx}",
                                    "source_file": "dynamic_fetch_fallback",
                                    "chunk_index": 0,
                                    "n_words": len(txt.split()),
                                    "text": txt,
                                    "doi": s.get("doi",""),
                                    "distance": None,
                                    "relevance_score": 0.8
                                })
                            neighbors = fallback_neighbors
                        else:
                            # no fallback items -> treat as empty
                            neighbors = []
                else:
                    print("[DYNAMIC_FETCH] No new items fetched or ingest failed.")
            except Exception as e:
                print(f"[ERROR] Dynamic fetch failed: {e}")

        if not neighbors:
            # No docs found: still return HOAX by design plus empty evidence
            frontend = {
                "claim": claim,
                "label": "HOAX",
                "confidence": 0.0,
                "summary": "Tidak ditemukan dokumen relevan untuk klaim ini setelah pencarian dan fetch otomatis.",
                "conclusion": "Tidak ada bukti yang ditemukan.",
                "evidence": [],
                "references": [],
                "metadata": {}
            }
            print("\n[JSON_OUTPUT]")
            print(json.dumps(frontend, ensure_ascii=False, indent=2))
            return {"_frontend_payload": frontend}

        # Translate snippets if needed for LLM prompt
        neighbors = translate_snippets_if_needed(neighbors, target_lang="Indonesian")

        if dry_run:
            print("\n=== DRY RUN: Neighbors ===")
            for i, n in enumerate(neighbors, 1):
                rel = n.get('relevance_score', 0)
                print(f"\n[{i}] {n.get('safe_id')} (relevance: {rel:.3f})")
                print(f"DOI: {n.get('doi', 'N/A')}")
                print(f"Text: {n.get('_text_translated', n.get('text',''))[:400]}...")
            return {"dry_run_neighbors": neighbors}

        print(f"[3/6] Building prompt with {len(neighbors)} relevant neighbors...")
        prompt = build_prompt(claim, neighbors, max_context_chars=3500)

        print("[4/6] Calling LLM for verification...")
        raw = ""
        try:
            raw = call_gemini(prompt, temperature=0.0, max_output_tokens=1600)
        except Exception as e:
            print(f"[ERROR] call_gemini failed: {e}")
            raw = ""

        if raw:
            print("[5/6] Parsing result from LLM...")
            parsed = extract_json_from_text(raw)
        else:
            parsed = validate_and_normalize_result({})

        # ----------------- Enrichment (A2/A3 already applied upstream) -----------------
        print("[6/6] Enriching with metadata and building frontend payload...")
        nb_map = {n.get("safe_id") or str(n.get("doc_id")): n for n in neighbors}

        evlist = parsed.get("evidence", []) or []
        references = []
        for ev in evlist:
            sid = ev.get("safe_id") or ev.get("id") or ev.get("doc_id") or ""
            nb = nb_map.get(sid)
            if nb:
                ev["source_snippet"] = safe_strip(nb.get("_text_translated", nb.get("text", "")))[:400]
                doi_val = safe_strip(nb.get("doi", "") or ev.get("doi", "") or "")
                ev["doi"] = doi_val
                ev["relevance_score"] = float(nb.get("relevance_score", 0.0))
                url_val = ""
                if doi_val:
                    doi_norm = re.sub(r'^(urn:doi:|doi:)\s*', '', doi_val, flags=re.I)
                    url_val = f"https://doi.org/{doi_norm}"
                else:
                    url_val = safe_strip(nb.get("source_url") or nb.get("source") or nb.get("source_file") or "")
                ev["url"] = url_val
                ref_entry = {
                    "safe_id": sid,
                    "doi": doi_val,
                    "url": url_val,
                    "source_type": "journal" if doi_val else "other",
                    "relevance": ev.get("relevance_score", 0.0)
                }
                if not any(r.get("safe_id") == ref_entry["safe_id"] and r.get("url") == ref_entry["url"] for r in references):
                    references.append(ref_entry)
            else:
                ev["source_snippet"] = ev.get("snippet", "")[:400]
                ev["doi"] = safe_strip(ev.get("doi", ""))
                ev["relevance_score"] = float(ev.get("relevance_score", 0.0))
                if ev.get("doi"):
                    doi_norm = re.sub(r'^(urn:doi:|doi:)\s*', '', ev.get("doi"), flags=re.I)
                    ev["url"] = f"https://doi.org/{doi_norm}"
                else:
                    ev["url"] = ""
                ref_entry = {
                    "safe_id": ev.get("safe_id") or ev.get("doi") or "",
                    "doi": ev.get("doi", ""),
                    "url": ev.get("url", ""),
                    "source_type": "journal" if ev.get("doi") else "other",
                    "relevance": ev.get("relevance_score", 0.0)
                }
                if ref_entry["safe_id"] and not any(r.get("safe_id") == ref_entry["safe_id"] for r in references):
                    references.append(ref_entry)

        parsed["references"] = references

        # Compute retriever/relevance metrics
        sim_scores = []
        rel_scores = []
        for n in neighbors:
            sim_scores.append(distance_to_similarity(n.get("distance")))
            rel_scores.append(n.get("relevance_score", 0.0))

        retriever_mean = float(sum(sim_scores) / len(sim_scores)) if sim_scores else 0.0
        relevance_mean = float(sum(rel_scores) / len(rel_scores)) if rel_scores else 0.0
        llm_confidence = float(parsed.get("confidence") or 0.0)

        combined_confidence = (
            0.5 * llm_confidence +
            0.3 * relevance_mean +
            0.2 * retriever_mean
        )

        parsed["_meta"] = {
            "neighbors_count": len(neighbors),
            "neighbors_with_doi": len([n for n in neighbors if n.get("doi")]),
            "retriever_mean_similarity": retriever_mean,
            "relevance_mean": relevance_mean,
            "combined_confidence": combined_confidence,
            "prompt_len_chars": len(prompt),
            "query_expansion_used": enable_expansion,
            "raw_llm_preview": safe_strip(raw)[:500] if raw else ""
        }

        # Adjust confidence & label
        if llm_confidence < 0.3:
            parsed["confidence"] = combined_confidence
        else:
            parsed["confidence"] = llm_confidence

        parsed = validate_and_normalize_result(parsed)
        final_dec = decide_final_label_and_summary(parsed, neighbors, combined_confidence)
        parsed["final_label"] = final_dec["final_label"]
        parsed["final_confidence"] = final_dec["final_confidence"]
        parsed["conclusion"] = final_dec["conclusion"]
        parsed["label"] = parsed["final_label"]
        parsed["confidence"] = parsed["final_confidence"]

        # Normalize evidence list for frontend
        frontend_evidence = []
        for ev in parsed.get("evidence", []):
            sid = ev.get("safe_id") or ev.get("id") or ev.get("doc_id") or ""
            nb = nb_map.get(sid) or {}
            item = {
                "safe_id": sid,
                "snippet": safe_strip(ev.get("snippet") or ev.get("text") or nb.get("text", "") )[:400],
                "source_snippet": safe_strip(ev.get("source_snippet") or nb.get("_text_translated") or nb.get("text",""))[:400],
                "doi": safe_strip(ev.get("doi","") or nb.get("doi","") or ""),
                "url": safe_strip(ev.get("url","") or (f"https://doi.org/{ev.get('doi')}" if ev.get("doi") else nb.get("source_url") or nb.get("source") or nb.get("source_file") or "")),
                "relevance_score": float(ev.get("relevance_score", 0.0))
            }
            frontend_evidence.append(item)

        if not frontend_evidence:
            for n in neighbors[:6]:
                sid = n.get("safe_id") or n.get("doc_id") or ""
                doi_val = safe_strip(n.get("doi","") or "")
                url_val = f"https://doi.org/{doi_val}" if doi_val else safe_strip(n.get("source_url") or n.get("source") or n.get("source_file") or "")
                frontend_evidence.append({
                    "safe_id": sid,
                    "snippet": safe_strip(n.get("_text_translated") or n.get("text",""))[:400],
                    "source_snippet": safe_strip(n.get("_text_translated") or n.get("text",""))[:400],
                    "doi": doi_val,
                    "url": url_val,
                    "relevance_score": float(n.get("relevance_score", 0.0))
                })

        parsed["evidence"] = frontend_evidence
        parsed["references"] = references

        # Build frontend payload
        frontend = {
            "claim": claim,
            "label": parsed.get("label", "HOAX"),
            "confidence": float(parsed.get("confidence", 0.0)),
            "summary": parsed.get("summary", "") or parsed.get("analysis", "") or "",
            "conclusion": parsed.get("conclusion", ""),
            "evidence": parsed.get("evidence", []),
            "references": parsed.get("references", []),
            "metadata": parsed.get("_meta", {})
        }

        # Print JSON_OUTPUT for frontend and return payload
        print("\n[JSON_OUTPUT]")
        print(json.dumps(frontend, ensure_ascii=False, indent=2))

        return {"_frontend_payload": frontend}

    except Exception as e:
        print(f"[ERROR] Exception in verify_claim_local: {str(e)}")
        traceback.print_exc()
        raise

# -------------------------
# CLI entrypoint
# -------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Improved Prompt & Verify - Healthify RAG with bilingual retrieval"
    )
    ap.add_argument("--claim", "-c", type=str,
                   help="Klaim yang akan diverifikasi (kosong untuk mode interaktif)")
    ap.add_argument("--k", "-k", type=int, default=5,
                   help="Jumlah neighbor yang diambil (default: 5)")
    ap.add_argument("--dry-run", action="store_true",
                   help="Tampilkan neighbors saja tanpa LLM call")
    ap.add_argument("--no-expansion", action="store_true",
                   help="Disable query expansion (gunakan single query)")
    ap.add_argument("--min-relevance", type=float, default=0.25,
                   help="Minimum relevance score untuk filter (default: 0.25)")
    ap.add_argument("--save-json", type=str, default=None,
                   help="Simpan hasil ke file JSON")
    ap.add_argument("--force-dynamic-fetch", action="store_true",
                   help="Memaksa dynamic fetch meskipun retrieval awal tampak cukup")
    ap.add_argument("--debug-retrieval", action="store_true",
                   help="Cetak debug retrieval/relevance lebih detail")
    args = ap.parse_args()

    claim = args.claim
    if not claim:
        print("Masukan klaim (akhiri dengan ENTER): ")
        claim = input("> ").strip()

    if not claim:
        print("Error: Klaim tidak boleh kosong")
        sys.exit(1)

    try:
        result = verify_claim_local(
            claim,
            k=args.k,
            dry_run=args.dry_run,
            enable_expansion=not args.no_expansion,
            min_relevance=args.min_relevance,
            force_dynamic_fetch=args.force_dynamic_fetch,
            debug_retrieval=args.debug_retrieval
        )
    except Exception as e:
        print(f"\n❌ Gagal verifikasi klaim: {str(e)}")
        sys.exit(1)

    # Human-friendly summary (kept) and JSON already printed
    print("\n" + "="*60)
    print("HASIL VERIFIKASI (ringkasan human-readable)")
    print("="*60)

    frontend = result.get("_frontend_payload") if isinstance(result, dict) else None
    if frontend:
        print(f"\n📋 KLAIM: {frontend.get('claim')}")
        print(f"\n🏷️  LABEL: {frontend.get('label')}")
        print(f"📊 CONFIDENCE: {frontend.get('confidence'):.2%}")
        print(f"\n💡 SUMMARY:\n{frontend.get('summary','')}")
        print(f"\n🔍 CONCLUSION:\n{frontend.get('conclusion','')}")
        meta = frontend.get("metadata", {})
        if meta:
            print(f"\n📈 METADATA:")
            print(f"   - Neighbors retrieved: {meta.get('neighbors_count', 0)}")
            print(f"   - Neighbors with DOI: {meta.get('neighbors_with_doi', 0)}")
            print(f"   - Mean relevance score: {meta.get('relevance_mean', 0):.3f}")
            print(f"   - Mean similarity score: {meta.get('retriever_mean_similarity', 0):.3f}")
            print(f"   - Combined confidence: {meta.get('combined_confidence', 0):.2%}")

    if args.save_json and frontend:
        with open(args.save_json, "w", encoding="utf-8") as fo:
            json.dump(frontend, fo, ensure_ascii=False, indent=2)
        print(f"\n💾 Hasil disimpan ke: {args.save_json}")

    print("\n" + "="*60)
    print("✅ Selesai.")
    print("="*60)

if __name__ == "__main__":
    main()
