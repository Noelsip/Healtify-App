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

# library ketiga
from dotenv import load_dotenv
from google import genai
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector

# project modules
import fetch_sources as fs
import prepare_and_run_loader as pr
import process_raw as praw
import ingest_chunks_to_pg as ic
import chunk_and_embed as cae
from ingest_chunks_to_pg import connect_db, DB_TABLE
from chunk_and_embed import embed_texts_gemini
from fetch_sources import fetch_all_sources

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

# Constants
PROMPT_HEADER = """
Anda adalah sistem verifikasi fakta medis yang teliti. Tugas Anda:
1) Evaluasi relevansi bukti terhadap klaim.
2) Jika ada bukti yang mendukung atau menolak klaim, jelaskan dasar keputusan.
3) Output harus JSON dengan fields: claim, analysis, label (VALID/HOAX), confidence (0-1), evidence (list), summary.
"""

LLM_CONF_THRESHOLD = 0.50
COMBINED_CONF_THRESHOLD = 0.50


def extract_text_from_model_resp(resp) -> str:
    """Ekstrak teks dari berbagai format respons Gemini API."""
    try:
        if resp is None:
            return ""
        
        if hasattr(resp, "text"):
            return resp.text or ""
            
        if hasattr(resp, "candidates") and resp.candidates:
            cand = resp.candidates[0]
            if hasattr(cand, "content"):
                content = cand.content
                if hasattr(content, "parts") and content.parts:
                    part = content.parts[0]
                    return getattr(part, "text", "") or ""
                elif hasattr(content, "text"):
                    return content.text or ""
            return getattr(cand, "text", "") or ""
            
        if isinstance(resp, dict):
            if "candidates" in resp and resp["candidates"]:
                cand = resp["candidates"][0]
                content = cand.get("content", {})
                if isinstance(content, dict) and "parts" in content and content["parts"]:
                    return content["parts"][0].get("text", "") or ""
                if isinstance(cand, dict) and "output" in cand:
                    return cand["output"]
            return str(resp.get("text", "")) if isinstance(resp, dict) else str(resp)
        
        return str(resp)
    except Exception:
        try:
            return str(resp)
        except Exception:
            return ""


def safe_strip(s) -> str:
    """Safely strip dan konversi ke string."""
    try:
        if s is None:
            return ""
        return str(s).strip()
    except Exception:
        return ""


def translate_text_gemini(text: str, target_lang: str = "English") -> str:
    """Terjemahkan teks menggunakan Gemini API."""
    if not text:
        return ""
    
    prompt = (
        f"Translate the following text to {target_lang}. "
        f"Keep it concise and preserve medical terminology when possible.\n\n"
        f"Text:\n\"\"\"\n{text}\n\"\"\"\n\nOutput only the translated text."
    )
    
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 256}
        )
        txt = extract_text_from_model_resp(resp)
        txt = safe_strip(txt).replace("```", "")
        return txt or text
    except Exception as e:
        print(f"[TRANSLATE] failed: {e}")
        return text


def generate_bilingual_queries(claim: str, langs: List[str] = ["English"]) -> List[str]:
    """Generate query variations dalam multiple bahasa dan sinonim."""
    queries = []
    claim_clean = safe_strip(claim)
    
    if claim_clean:
        queries.append(claim_clean)

    # Add translations
    for lang in langs:
        try:
            translated = translate_text_gemini(claim_clean, target_lang=lang)
            translated = safe_strip(translated)
            if translated and translated not in queries:
                queries.append(translated)
        except Exception:
            pass

    # Ask LLM for variations
    english_example = queries[1] if len(queries) > 1 else claim_clean
    syn_prompt = (
        f"You are a medical search query assistant.\n"
        f"Given the topic below, produce 3-5 short, focused search query variations "
        f"or keyword phrases researchers would use.\n"
        f"Return a JSON array of strings.\n\n"
        f"Topic (original): {claim_clean}\n"
        f"Topic (english translation): {english_example}"
    )
    
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=syn_prompt,
            config={"temperature": 0.2, "max_output_tokens": 300}
        )
        txt = extract_text_from_model_resp(resp)
        txt = safe_strip(txt)
        
        variations = []
        try:
            if txt:
                variations = json.loads(txt)
        except Exception:
            # Tolerant fallback: split lines and strip bullets
            for line in (txt or "").splitlines():
                line = line.strip().lstrip("-• ").strip()
                if line:
                    variations.append(line)
        
        for query in variations:
            query_str = safe_strip(query)
            if query_str and query_str not in queries:
                queries.append(query_str)
                
    except Exception as e:
        print(f"[GEN_QUERIES] failed: {e}")

    # Dedupe dan limit
    unique_queries = []
    for q in queries:
        qn = safe_strip(q)
        if qn and qn not in unique_queries:
            unique_queries.append(qn)
    
    return unique_queries[:6]


def safe_cosine_similarity(a: List[float], b: List[float]) -> float:
    """Hitung cosine similarity antara dua vektor secara aman."""
    try:
        import math
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        
        if norm_a <= 0 or norm_b <= 0:
            return 0.0
        return dot / (norm_a * norm_b)
    except Exception:
        return 0.0


def distance_to_similarity(dist: Optional[float]) -> float:
    """Convert distance metric ke similarity score."""
    if dist is None:
        return 0.0
    try:
        return 1.0 / (1.0 + float(dist))
    except Exception:
        return 0.0


def retrieve_neighbors_from_db(query_embedding: List[float], k: int = 5, 
                              max_chars_each: int = 1200, 
                              debug_print: bool = False) -> List[Dict[str, Any]]:
    """Retrieve k nearest neighbors dari database menggunakan vector similarity."""
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

    results = []
    for r in rows:
        txt = safe_strip((r.get("text") or "").replace("\n", " "))[:max_chars_each]
        dist_val = None
        try:
            raw_dist = r.get("distance")
            dist_val = float(raw_dist) if raw_dist is not None else None
        except Exception:
            pass

        results.append({
            "doc_id": r.get("doc_id"),
            "safe_id": r.get("safe_id"),
            "source_file": r.get("source_file"),
            "chunk_index": r.get("chunk_index"),
            "n_words": r.get("n_words"),
            "text": txt,
            "doi": r.get("doi", "") or "",
            "distance": dist_val
        })
    
    return results


def compute_relevance_score(claim: str, neighbor_text: str, neighbor_title: str = "") -> float:
    """Hitung relevance score berdasarkan keyword matching dengan medical patterns."""
    claim_lower = safe_strip(claim).lower()
    text_lower = safe_strip(neighbor_text).lower()
    title_lower = safe_strip(neighbor_title).lower()

    medical_patterns = [
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
    for pattern in medical_patterns:
        if re.search(pattern, claim_lower):
            if re.search(pattern, text_lower) or re.search(pattern, title_lower):
                keyword_score += 1.0

    return min(keyword_score / len(medical_patterns), 1.0)


def filter_by_relevance(claim: str, neighbors: List[Dict[str, Any]], 
                       min_relevance: float = 0.3, debug: bool = False) -> List[Dict[str, Any]]:
    """Filter neighbors berdasarkan relevance score dan sort by combined score."""
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
        elif debug:
            print(f"[RELEVANCE] Filtered out doc {nb.get('safe_id')} (score: {combined_score:.3f})")

    filtered.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return filtered


def retrieve_with_expansion_bilingual(claim: str, k: int = 5, 
                                     expand_queries: bool = True, 
                                     debug: bool = False) -> List[Dict[str, Any]]:
    """Retrieve documents dengan query expansion dalam multiple bahasa."""
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


def load_fetched_file_to_items(path_or_obj):
    """Load dan parse file hasil fetch ke format items yang standardized."""
    items = []
    
    if isinstance(path_or_obj, dict):
        title = path_or_obj.get("title") or path_or_obj.get("paperTitle") or ""
        abstract = path_or_obj.get("abstract") or path_or_obj.get("summary") or ""
        url = path_or_obj.get("url") or path_or_obj.get("pdf_url") or ""
        doi = path_or_obj.get("doi") or path_or_obj.get("paperId") or ""
        items.append({"title": title, "abstract": abstract, "url": url, "doi": doi})
        return items

    if isinstance(path_or_obj, (list, tuple)):
        for item in path_or_obj:
            items.extend(load_fetched_file_to_items(item))
        return items

    if isinstance(path_or_obj, str):
        p = pathlib.Path(path_or_obj)
        if not p.exists():
            try:
                obj = json.loads(path_or_obj)
                return load_fetched_file_to_items(obj)
            except Exception:
                return []
        
        name = p.name.lower()
        try:
            if name.startswith("crossref") and p.suffix == ".json":
                parsed = praw.parse_crossref_file(p)
                for d in parsed:
                    items.append({
                        "title": d.get("title", ""), 
                        "abstract": d.get("abstract", ""), 
                        "url": d.get("url", "") if d.get("url") else "", 
                        "doi": d.get("doi", "")
                    })
            elif "semantic" in name and p.suffix == ".json":
                parsed = praw.parse_sematic_scholar_file(p)
                for d in parsed:
                    items.append({
                        "title": d.get("title", ""), 
                        "abstract": d.get("abstract", ""), 
                        "url": d.get("url", "") if d.get("url") else "", 
                        "doi": d.get("doi", "")
                    })
            elif "pubmed" in name and p.suffix in [".xml", ".txt"]:
                parsed = praw.parse_pubmed_xml_file(p)
                for d in parsed:
                    items.append({
                        "title": d.get("title", ""), 
                        "abstract": d.get("abstract", ""), 
                        "url": d.get("url", "") if d.get("url") else "", 
                        "doi": d.get("doi", "")
                    })
            else:
                try:
                    obj = json.loads(p.read_text(encoding="utf-8"))
                    return load_fetched_file_to_items(obj)
                except Exception:
                    pass
        except Exception as e:
            print(f"[LOAD_FETCHED] parse error for {p}: {e}")
    
    return items


def ingest_abstracts_as_chunks(selected_items: List[Dict[str, Any]]) -> bool:
    """Ingest selected abstracts sebagai chunks ke database."""
    if not selected_items:
        return False

    os.makedirs("data/chunks", exist_ok=True)
    texts = []
    metas = []

    for item in selected_items:
        text = (item.get("title", "") + "\n\n" + item.get("abstract", "")).strip()
        if not text:
            continue
        
        texts.append(text)
        metas.append({
            "safe_id": item.get("doi") or item.get("url") or str(uuid.uuid4()),
            "doi": item.get("doi", ""),
            "source": item.get("url", "") or item.get("source", "") or "",
        })

    if not texts:
        return False

    try:
        vectors = embed_texts_gemini(texts)
    except Exception as e:
        print(f"[FAST_INGEST] Error embedding abstracts: {e}")
        return False

    out_fname = f"abstract_chunks_{int(time.time())}.jsonl"
    out_path = os.path.join("data", "chunks", out_fname)

    with open(out_path, "w", encoding="utf-8") as fo:
        for text, meta, vec in zip(texts, metas, vectors):
            record = {
                "doc_id": meta["safe_id"],
                "safe_id": meta["safe_id"],
                "source_file": "dynamic_fetch",
                "chunk_index": 0,
                "n_words": len(text.split()),
                "text": text,
                "doi": meta["doi"],
                "source_url": meta.get("source", ""),
                "embedding": list(vec) if hasattr(vec, "__iter__") else vec
            }
            fo.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"[FAST_INGEST] Wrote {len(texts)} abstract chunks to {out_path}")

    try:
        ic.ingest()
        time.sleep(1.0)
        return True
    except Exception as e:
        print(f"[FAST_INGEST] ingest() failed: {e}")
        return False


def dynamic_fetch_and_update(claim: str, max_fetch_results: int = 10, 
                            top_k_select: int = 8) -> tuple:
    """Fetch documents dari multiple sources dan select yang paling relevan."""
    print(f"[DYNAMIC_FETCH] Fetching for: {claim[:80]}...")
    fetched_paths = []

    # Fetch from multiple sources
    sources = [
        ("pubmed", lambda: fs.fetch_pubmed(claim, maximum_results=max_fetch_results)),
        ("crossref", lambda: fs.fetch_crossref(claim, rows=max_fetch_results)),
        ("semantic_scholar", lambda: fs.fetch_semantic_scholar(claim, limit=max_fetch_results))
    ]

    for source_name, fetch_func in sources:
        try:
            result = fetch_func()
            if result:
                fetched_paths.append(result)
            time.sleep(0.3)
        except Exception as e:
            print(f"[DYNAMIC_FETCH] {source_name} failed: {e}")

    # Parse all fetched items
    all_items = []
    for fp in fetched_paths:
        try:
            items = load_fetched_file_to_items(fp)
            if items:
                all_items.extend(items)
        except Exception as e:
            print(f"[DYNAMIC_FETCH] Error loading fetched file {fp}: {e}")

    if not all_items:
        print("[DYNAMIC_FETCH] No items available after parsing fetched files.")
        return False, []

    # Prepare texts for embedding
    candidate_texts = []
    candidate_meta = []
    
    for item in all_items:
        text = (item.get("title", "") + "\n\n" + (item.get("abstract", "") or "")).strip()
        if text:
            candidate_texts.append(text)
            candidate_meta.append(item)

    if not candidate_texts:
        print("[DYNAMIC_FETCH] No candidate texts to embed.")
        return False, []

    # Select most relevant items using cosine similarity
    try:
        claim_vec = embed_texts_gemini([claim])[0]
        candidate_vecs = embed_texts_gemini(candidate_texts)
    except Exception as e:
        print(f"[DYNAMIC_FETCH] Embedding failed: {e}")
        return False, []

    similarities = [safe_cosine_similarity(claim_vec, v) for v in candidate_vecs]
    idx_sorted = sorted(range(len(similarities)), key=lambda i: similarities[i], reverse=True)[:top_k_select]
    selected = [candidate_meta[i] for i in idx_sorted]

    print(f"[DYNAMIC_FETCH] Selected {len(selected)} items (top sims: {[round(similarities[i], 3) for i in idx_sorted[:5]]})")

    # Normalize selected items
    normalized_selected = []
    for s in selected:
        normalized_selected.append({
            "title": s.get("title", ""),
            "abstract": s.get("abstract", ""),
            "url": s.get("url", ""),
            "doi": s.get("doi", "")
        })

    did_ingest = ingest_abstracts_as_chunks(normalized_selected)
    return did_ingest, normalized_selected


def needs_dynamic_fetch(neighbors: List[Dict[str, Any]], claim: str,
                        min_relevance_mean: float = 0.30,
                        min_retriever_mean: float = 0.30,
                        min_max_relevance: float = 0.45,
                        debug: bool = False) -> bool:
    """Determine apakah perlu dynamic fetch berdasarkan quality metrics."""
    if not neighbors:
        if debug:
            print("[QUALITY_CHECK] No neighbors -> need dynamic fetch.")
        return True

    relevance_scores = [n.get("relevance_score", 0.0) for n in neighbors if n.get("relevance_score") is not None]
    similarity_scores = [distance_to_similarity(n.get("distance")) for n in neighbors if n.get("distance") is not None]

    relevance_mean = float(sum(relevance_scores) / len(relevance_scores)) if relevance_scores else 0.0
    retriever_mean = float(sum(similarity_scores) / len(similarity_scores)) if similarity_scores else 0.0
    max_relevance = max(relevance_scores) if relevance_scores else 0.0

    # Check keyword overlap
    claim_tokens = set(re.findall(r"[A-Za-zÀ-ÿ0-9]+", safe_strip(claim).lower()))
    
    def has_keyword_match(text: str) -> bool:
        txt_tokens = set(re.findall(r"[A-Za-zÀ-ÿ0-9]+", safe_strip(text).lower()))
        overlap = [t for t in (claim_tokens & txt_tokens) if len(t) > 2]
        return len(overlap) > 0

    any_keyword = any(
        has_keyword_match(n.get("text", "")) or has_keyword_match(n.get("safe_id", "") or "") 
        for n in neighbors
    )

    if debug:
        print(f"[QUALITY_CHECK] relevance_mean={relevance_mean:.3f}, "
              f"retriever_mean={retriever_mean:.3f}, max_rel={max_relevance:.3f}, "
              f"any_keyword={any_keyword}")

    # Decision logic
    quality_thresholds_met = (
        relevance_mean >= min_relevance_mean and 
        retriever_mean >= min_retriever_mean and 
        max_relevance >= min_max_relevance and 
        any_keyword
    )

    if not quality_thresholds_met:
        if debug:
            print("[QUALITY_CHECK] Quality thresholds not met -> dynamic fetch recommended")
        return True

    return False


def translate_snippets_if_needed(neighbors: List[Dict[str, Any]], target_lang="Indonesian") -> List[Dict[str, Any]]:
    """Translate snippet text ke target language jika diperlukan berdasarkan heuristic."""
    for nb in neighbors:
        text = nb.get("text", "")
        if not text:
            nb["_text_translated"] = ""
            continue
        
        # Heuristic: jika banyak English words, translate ke Indonesian
        english_words = len(re.findall(r"[a-zA-Z]{4,}", text))
        indonesian_connectives = len(re.findall(r"\b(dan|yang|dengan|atau|untuk|di)\b", text.lower()))
        
        if english_words > max(5, indonesian_connectives * 3):
            try:
                nb["_text_translated"] = translate_text_gemini(text, target_lang=target_lang)
            except Exception as e:
                print(f"[TRANSLATE] failed for snippet: {e}")
                nb["_text_translated"] = text
        else:
            nb["_text_translated"] = text
    
    return neighbors


def build_prompt(claim: str, neighbors: List[Dict[str, Any]], max_context_chars: int = 3000) -> str:
    """Build prompt untuk LLM dengan evidence dari neighbors."""
    parts = []
    total_chars = 0
    
    for idx, nb in enumerate(neighbors, 1):
        doi = nb.get('doi', '') or ''
        safe_id = nb.get('safe_id', '') or nb.get('doc_id', '')
        source_file = nb.get('source_file', '')
        relevance_score = nb.get('relevance_score', 0.0)
        text_for_prompt = nb.get("_text_translated") or nb.get("text", "")
        
        source_info = f"[Bukti #{idx}] ID: {safe_id}"
        if doi:
            source_info += f" | DOI: {doi}"
        if source_file:
            source_info += f" | File: {source_file}"
        source_info += f" | Relevance: {relevance_score:.3f}"
        
        part = f"{source_info}\n{text_for_prompt}\n---\n"
        if total_chars + len(part) > max_context_chars:
            break
        
        parts.append(part)
        total_chars += len(part)

    context_block = "\n".join(parts)
    
    return f"""{PROMPT_HEADER}

CLAIM:
"{claim.strip()}"

BUKTI:
{context_block}

Instruksi:
- Evaluasi bukti dan tentukan apakah klaim tersebut didukung (VALID) atau dibantah (HOAX).
- Jelaskan analisis singkat dan sertakan evidence list (id, snippet).
- Kembalikan hanya JSON yang valid dengan fields: claim, analysis, label, confidence, evidence (array of objects with safe_id & snippet), summary.
"""


def call_gemini(prompt: str, model: str = "gemini-2.5-flash-lite", 
               temperature: float = 0.0, max_output_tokens: int = 1200) -> str:
    """Call Gemini API dengan fallback ke multiple models."""
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
            text = extract_text_from_model_resp(resp)
            text = safe_strip(text)
            
            if not text:
                continue
            
            # Clean JSON fences
            text = text.replace("```json", "").replace("```", "").strip()
            return text
            
        except Exception as e:
            print(f"[DEBUG] call_gemini with model {m} failed: {str(e)}")
            continue
    
    raise RuntimeError("All Gemini model calls failed or returned empty.")


def fix_common_json_issues(json_str: str) -> str:
    """Fix common JSON syntax issues."""
    s = json_str
    # Remove trailing commas
    s = re.sub(r',(\s*[}\]])', r'\1', s)
    # Remove non-printable characters except newlines, returns, tabs
    s = ''.join(ch for ch in s if ord(ch) >= 32 or ch in '\n\r\t')
    return s


def validate_and_normalize_result(result: dict) -> dict:
    """Validate dan normalize result dari LLM ke format yang konsisten."""
    result = result or {}
    
    # Normalize label
    if "label" not in result:
        result["label"] = "HOAX"
    
    label = safe_strip(result.get("label", "")).upper()
    if label not in ["VALID", "HOAX"]:
        label_mapping = {
            "TRUE": "VALID", "BENAR": "VALID",
            "FALSE": "HOAX", "SALAH": "HOAX",
            "UNCERTAIN": "HOAX", "TIDAK TERDETEKSI": "HOAX", "TIDAK PASTI": "HOAX"
        }
        result["label"] = label_mapping.get(label, "HOAX")
    
    # Normalize confidence
    try:
        confidence = float(result.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
    except Exception:
        confidence = 0.0
    result["confidence"] = confidence
    
    # Set defaults
    result.setdefault("analysis", "")
    result.setdefault("evidence", [])
    result.setdefault("summary", "")
    result.setdefault("references", [])
    
    return result


def extract_json_from_text(text: str) -> Dict[str, Any]:
    """Extract dan parse JSON dari response text LLM."""
    s = safe_strip(text)
    if not s:
        return validate_and_normalize_result({})
    
    # Try plain JSON parse first
    try:
        parsed = json.loads(s)
        return validate_and_normalize_result(parsed)
    except Exception:
        pass
    
    # Try to find JSON object in text
    start = -1
    brace_count = 0
    
    for i, ch in enumerate(s):
        if ch == "{":
            if start == -1:
                start = i
            brace_count += 1
        elif ch == "}":
            brace_count -= 1
            if brace_count == 0 and start != -1:
                candidate = s[start:i+1]
                try:
                    parsed = json.loads(candidate)
                    return validate_and_normalize_result(parsed)
                except Exception:
                    # Try fixing common issues
                    candidate_fixed = fix_common_json_issues(candidate)
                    try:
                        parsed = json.loads(candidate_fixed)
                        return validate_and_normalize_result(parsed)
                    except Exception:
                        pass
    
    # Fallback: return default HOAX response
    print("[WARNING] Cannot parse JSON from LLM. Returning default HOAX response.")
    return validate_and_normalize_result({})


def decide_final_label_and_confidence(parsed: Dict[str, Any], neighbors: List[Dict[str, Any]], 
                                    combined_confidence: float) -> Dict[str, Any]:
    """Decide final label dan confidence berdasarkan LLM output dan heuristics."""
    llm_label = parsed.get("label", "").upper()
    llm_confidence = float(parsed.get("confidence", 0.0))
    
    # Final decision logic
    if llm_label in ["VALID", "HOAX"] and llm_confidence >= LLM_CONF_THRESHOLD:
        final_label = llm_label
        final_confidence = llm_confidence
        decision_reason = f"Used LLM verdict (label={llm_label}, confidence={llm_confidence:.2f})"
    else:
        final_label = "VALID" if combined_confidence >= COMBINED_CONF_THRESHOLD else "HOAX"
        final_confidence = combined_confidence
        decision_reason = f"Used combined retriever+LLM fallback (combined_confidence={combined_confidence:.2f})"
    
    return {
        "final_label": final_label,
        "final_confidence": float(final_confidence),
        "decision_reason": decision_reason
    }


def build_frontend_payload(claim: str, parsed: Dict[str, Any], neighbors: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build payload untuk frontend dari parsed result dan neighbors."""
    # Map neighbors by ID for reference
    neighbor_map = {n.get("safe_id") or str(n.get("doc_id")): n for n in neighbors}
    
    # Process evidence list
    evidence_list = parsed.get("evidence", []) or []
    references = []
    frontend_evidence = []
    
    for ev in evidence_list:
        safe_id = ev.get("safe_id") or ev.get("id") or ev.get("doc_id") or ""
        nb = neighbor_map.get(safe_id) or {}
        
        # Build evidence item
        doi_val = safe_strip(ev.get("doi", "") or nb.get("doi", "") or "")
        url_val = ""
        if doi_val:
            doi_normalized = re.sub(r'^(urn:doi:|doi:)\s*', '', doi_val, flags=re.I)
            url_val = f"https://doi.org/{doi_normalized}"
        else:
            url_val = safe_strip(nb.get("source_url") or nb.get("source") or nb.get("source_file") or "")
        
        evidence_item = {
            "safe_id": safe_id,
            "snippet": safe_strip(ev.get("snippet") or ev.get("text") or nb.get("text", ""))[:400],
            "source_snippet": safe_strip(nb.get("_text_translated") or nb.get("text", ""))[:400],
            "doi": doi_val,
            "url": url_val,
            "relevance_score": float(ev.get("relevance_score", nb.get("relevance_score", 0.0)))
        }
        frontend_evidence.append(evidence_item)
        
        # Build reference
        ref_entry = {
            "safe_id": safe_id,
            "doi": doi_val,
            "url": url_val,
            "source_type": "journal" if doi_val else "other",
            "relevance": evidence_item["relevance_score"]
        }
        
        # Add to references if not duplicate
        if not any(r.get("safe_id") == ref_entry["safe_id"] and r.get("url") == ref_entry["url"] 
                  for r in references):
            references.append(ref_entry)
    
    # Fallback: use top neighbors as evidence if empty
    if not frontend_evidence:
        for n in neighbors[:6]:
            safe_id = n.get("safe_id") or n.get("doc_id") or ""
            doi_val = safe_strip(n.get("doi", "") or "")
            url_val = f"https://doi.org/{doi_val}" if doi_val else safe_strip(
                n.get("source_url") or n.get("source") or n.get("source_file") or ""
            )
            
            frontend_evidence.append({
                "safe_id": safe_id,
                "snippet": safe_strip(n.get("_text_translated") or n.get("text", ""))[:400],
                "source_snippet": safe_strip(n.get("_text_translated") or n.get("text", ""))[:400],
                "doi": doi_val,
                "url": url_val,
                "relevance_score": float(n.get("relevance_score", 0.0))
            })
    
    return {
        "claim": claim,
        "label": parsed.get("label", "HOAX"),
        "confidence": float(parsed.get("confidence", 0.0)),
        "summary": parsed.get("summary", "") or parsed.get("analysis", "") or "",
        "conclusion": parsed.get("conclusion", ""),
        "evidence": frontend_evidence,
        "references": references,
        "metadata": parsed.get("_meta", {})
    }


def verify_claim_local(claim: str, k: int = 5, dry_run: bool = False, 
                      enable_expansion: bool = True, min_relevance: float = 0.25,
                      force_dynamic_fetch: bool = False, 
                      debug_retrieval: bool = False) -> Dict[str, Any]:
    """Main verification flow - verifikasi klaim medis menggunakan RAG pipeline."""
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

        # Check if dynamic fetch needed
        quality_need_fetch = force_dynamic_fetch or needs_dynamic_fetch(
            neighbors, claim, min_relevance_mean=min_relevance, min_retriever_mean=0.25, debug=debug_retrieval
        )

        dynamic_selected = None
        if quality_need_fetch:
            print("[2/6] Retrieval quality low or insufficient. Attempting dynamic fetch...")
            try:
                did_update, dynamic_selected = dynamic_fetch_and_update(claim, max_fetch_results=30, top_k_select=12)
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

                    # Use fetched items as fallback if still insufficient
                    if needs_dynamic_fetch(neighbors, claim, min_relevance_mean=min_relevance, 
                                         min_retriever_mean=0.25, debug=debug_retrieval):
                        print("[DYNAMIC_FETCH] Retry retrieval after dynamic fetch still low quality.")
                        if dynamic_selected:
                            print("[DYNAMIC_FETCH] Using fetched items as fallback context for LLM.")
                            fallback_neighbors = []
                            for idx, s in enumerate(dynamic_selected, 1):
                                text = (s.get("title", "") + "\n\n" + s.get("abstract", "")).strip()
                                if text:
                                    fallback_neighbors.append({
                                        "doc_id": s.get("doi") or s.get("url") or f"dyn_{idx}",
                                        "safe_id": s.get("doi") or s.get("url") or f"dyn_{idx}",
                                        "source_file": "dynamic_fetch_fallback",
                                        "chunk_index": 0,
                                        "n_words": len(text.split()),
                                        "text": text,
                                        "doi": s.get("doi", ""),
                                        "distance": None,
                                        "relevance_score": 0.8
                                    })
                            neighbors = fallback_neighbors
                        else:
                            neighbors = []
                else:
                    print("[DYNAMIC_FETCH] No new items fetched or ingest failed.")
            except Exception as e:
                print(f"[ERROR] Dynamic fetch failed: {e}")

        # Handle no neighbors case
        if not neighbors:
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

        # Translate snippets for LLM
        neighbors = translate_snippets_if_needed(neighbors, target_lang="Indonesian")

        if dry_run:
            print("\n=== DRY RUN: Neighbors ===")
            for i, n in enumerate(neighbors, 1):
                relevance = n.get('relevance_score', 0)
                print(f"\n[{i}] {n.get('safe_id')} (relevance: {relevance:.3f})")
                print(f"DOI: {n.get('doi', 'N/A')}")
                print(f"Text: {n.get('_text_translated', n.get('text',''))[:400]}...")
            return {"dry_run_neighbors": neighbors}

        print(f"[3/6] Building prompt with {len(neighbors)} relevant neighbors...")
        prompt = build_prompt(claim, neighbors, max_context_chars=3500)

        print("[4/6] Calling LLM for verification...")
        try:
            raw_response = call_gemini(prompt, temperature=0.0, max_output_tokens=1600)
        except Exception as e:
            print(f"[ERROR] call_gemini failed: {e}")
            raw_response = ""

        print("[5/6] Parsing result from LLM...")
        parsed = extract_json_from_text(raw_response) if raw_response else validate_and_normalize_result({})

        print("[6/6] Enriching with metadata and building frontend payload...")
        
        # Calculate metrics
        similarity_scores = [distance_to_similarity(n.get("distance")) for n in neighbors if n.get("distance") is not None]
        relevance_scores = [n.get("relevance_score", 0.0) for n in neighbors]
        
        retriever_mean = float(sum(similarity_scores) / len(similarity_scores)) if similarity_scores else 0.0
        relevance_mean = float(sum(relevance_scores) / len(relevance_scores)) if relevance_scores else 0.0
        llm_confidence = float(parsed.get("confidence") or 0.0)
        
        combined_confidence = (0.5 * llm_confidence + 0.3 * relevance_mean + 0.2 * retriever_mean)

        # Add metadata
        parsed["_meta"] = {
            "neighbors_count": len(neighbors),
            "neighbors_with_doi": len([n for n in neighbors if n.get("doi")]),
            "retriever_mean_similarity": retriever_mean,
            "relevance_mean": relevance_mean,
            "combined_confidence": combined_confidence,
            "prompt_len_chars": len(prompt),
            "query_expansion_used": enable_expansion,
            "raw_llm_preview": safe_strip(raw_response)[:500] if raw_response else ""
        }

        # Final decision logic
        final_decision = decide_final_label_and_confidence(parsed, neighbors, combined_confidence)
        parsed.update(final_decision)
        
        # Force final labels (only VALID/HOAX)
        parsed["label"] = parsed["final_label"]
        parsed["confidence"] = parsed["final_confidence"]

        # Build frontend payload
        frontend = build_frontend_payload(claim, parsed, neighbors)
        
        # Print JSON output and return
        print("\n[JSON_OUTPUT]")
        print(json.dumps(frontend, ensure_ascii=False, indent=2))
        
        return {"_frontend_payload": frontend}

    except Exception as e:
        print(f"[ERROR] Exception in verify_claim_local: {str(e)}")
        traceback.print_exc()
        raise


def main():
    """CLI entry point untuk menjalankan fact-checking system."""
    parser = argparse.ArgumentParser(
        description="Improved Prompt & Verify - Healthify RAG with bilingual retrieval"
    )
    parser.add_argument("--claim", "-c", type=str,
                       help="Klaim yang akan diverifikasi (kosong untuk mode interaktif)")
    parser.add_argument("--k", "-k", type=int, default=5,
                       help="Jumlah neighbor yang diambil (default: 5)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Tampilkan neighbors saja tanpa LLM call")
    parser.add_argument("--no-expansion", action="store_true",
                       help="Disable query expansion (gunakan single query)")
    parser.add_argument("--min-relevance", type=float, default=0.25,
                       help="Minimum relevance score untuk filter (default: 0.25)")
    parser.add_argument("--save-json", type=str, default=None,
                       help="Simpan hasil ke file JSON")
    parser.add_argument("--force-dynamic-fetch", action="store_true",
                       help="Memaksa dynamic fetch meskipun retrieval awal tampak cukup")
    parser.add_argument("--enable-prefetch", action="store_true",
                       help="Jalankan pre-fetch dengan query expansion sebelum verifikasi")
    parser.add_argument("--debug-retrieval", action="store_true",
                       help="Tampilkan debug info untuk retrieval")
    
    args = parser.parse_args()

    claim = args.claim
    if not claim:
        print("Masukan klaim (akhiri dengan ENTER): ")
        claim = input("> ").strip()

    if not claim:
        print("Error: Klaim tidak boleh kosong")
        sys.exit(1)

    if args.enable_prefetch:
        # Generate query variations and optionally fetch
        queries = generate_bilingual_queries(claim, langs=["English"])
        print(f"[MAIN] Generated queries for fetch: {queries}")

        for q in queries:
            try:
                print(f"[MAIN] Fetching for expanded query: {q}")
                fetch_all_sources(q, pubmed_max=5, crossref_rows=5, semantic_limit=5, delay_between_sources=0.3)
            except Exception as e:
                print(f"[MAIN] fetch_all_sources failed for '{q}': {e}")

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

    # Print human-friendly summary
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
        
        metadata = frontend.get("metadata", {})
        if metadata:
            print(f"\n📈 METADATA:")
            print(f"   - Neighbors retrieved: {metadata.get('neighbors_count', 0)}")
            print(f"   - Neighbors with DOI: {metadata.get('neighbors_with_doi', 0)}")
            print(f"   - Mean relevance score: {metadata.get('relevance_mean', 0):.3f}")
            print(f"   - Mean similarity score: {metadata.get('retriever_mean_similarity', 0):.3f}")
            print(f"   - Combined confidence: {metadata.get('combined_confidence', 0):.2%}")

    if args.save_json and frontend:
        with open(args.save_json, "w", encoding="utf-8") as fo:
            json.dump(frontend, fo, ensure_ascii=False, indent=2)
        print(f"\n💾 Hasil disimpan ke: {args.save_json}")

    print("\n" + "="*60)
    print("✅ Selesai.")
    print("="*60)


if __name__ == "__main__":
    main()