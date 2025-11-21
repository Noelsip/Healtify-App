import os
import re
import json
import time
import uuid
import pathlib
import argparse
import sys
import traceback
import hashlib
import pickle
from typing import List, Dict, Any, Optional
from functools import lru_cache
from functools import lru_cache
from pathlib import Path

# library ketiga
from dotenv import load_dotenv, find_dotenv
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

BASE = pathlib.Path(__file__).parent     
TRAINING_DIR = BASE.parent          
PROJECT_ROOT = TRAINING_DIR.parent       

# Memastikan folder data/chunks exists
DATA_DIR = TRAINING_DIR / "data"
CHUNKS_DIR = DATA_DIR / "chunks"

CACHE_DIR = DATA_DIR / "llm_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# helper untuk menyimpan hasil verifikasi
VERIFICATION_RESULTS_PATH = TRAINING_DIR / "data" / "metadata" / "verification_results.jsonl"
VERIFICATION_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)

# --- Pengaturan environment & client ---
SCRIPT_DIR = str(BASE)
REPO_ROOT = str(PROJECT_ROOT)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, REPO_ROOT)

def load_environment_variables():
    """Load environment variables dengan fallback ke multiple lokasi."""
    dotenv_locations = [
        TRAINING_DIR / ".env",
        PROJECT_ROOT / ".env",
        find_dotenv()
    ]
    
    loaded = False
    for dotenv_path in dotenv_locations:
        if dotenv_path and pathlib.Path(dotenv_path).exists():
            load_dotenv(dotenv_path=dotenv_path, override=True)
            loaded = True
            print(f"[ENV] Loaded environment from: {dotenv_path}", file=sys.stderr)
            break
    
    if not loaded:
        print("[ENV] WARNING: No .env file found in standard locations", file=sys.stderr)
        # Mencoba load dari environment yang sudah ada
        load_dotenv()
    
    return loaded

# Load environment variables
load_environment_variables()

# error handling untuk client initialization
try:
    client = getattr(cae, "client", None)
except Exception as e:
    print(f"[INIT] Warning: Could not get client from cae module: {e}", file=sys.stderr)
    client = None

if client is None:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        error_msg = (
            "GEMINI_API_KEY tidak ditemukan di environment variables.\n"
            f"Lokasi .env yang dicek:\n"
            f"  1. {TRAINING_DIR / '.env'}\n"
            f"  2. {PROJECT_ROOT / '.env'}\n"
            f"  3. Auto-detected location\n"
            f"Pastikan file .env exists dan berisi GEMINI_API_KEY=your_key_here"
        )
        print(f"[ERROR] {error_msg}", file=sys.stderr)
        sys.exit(2)  # Exit code 2 untuk missing configuration
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("[INIT] Gemini client initialized successfully", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] Failed to initialize Gemini client: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(2)

def _get_cache_key(text: str, prefix: str = "") -> str:
    """
        Generate Caache key untuk LLM response.
    """
    content = f"{prefix}:{text}".encode('utf-8')
    return hashlib.md5(content).hexdigest()

def _load_from_cache(cache_key: str) -> Optional[Any]:
    """Load Cache LLM Response."""
    cache_file = CACHE_DIR / f"{cache_key}.pkl"
    if cache_file.exists():
        try:
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
                # Check if cache is still valid (24 jam)
                if time.time() - data['timestamp'] < 86400:
                    return data['result']
        except Exception as e:
            print(f"[CACHE] Error Loading cache: {e}")
    return None

def _save_to_cache(cache_key: str, result: Any):
    """Save LLM response to cache."""
    cache_file = CACHE_DIR / f"{cache_key}.pkl"
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump({'timestamp': time.time(), 'result': result}, f)
    except Exception as e:
        print(f"[CACHE] Error saving cache: {e}")

def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics untuk monitoring."""
    if not CACHE_DIR.exists():
        return {"error": "Cache directory does not exist"}
    
    cache_files = list(CACHE_DIR.glob("*.pkl"))
    total_size = sum(f.stat().st_size for f in cache_files)
    
    return {
        "total_cached_items": len(cache_files),
        "total_size_mb": total_size / (1024 * 1024),
        "cache_dir": str(CACHE_DIR)
    }

# Better database connection check dengan proper error handling
def check_database_connection():
    """Check database connection dengan error handling yang lebih baik."""
    try:
        conn = connect_db()
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {DB_TABLE};")
            cnt = cur.fetchone()
            print(f"[DB] Rows in embeddings table: {cnt[0] if cnt else 0}", file=sys.stderr)
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] WARNING: Database connection check failed: {str(e)}", file=sys.stderr)
        print("[DB] Verification will continue but may fail if database is required", file=sys.stderr)
        return False

# Check database pada startup
db_available = check_database_connection()

# Konstanta konfigurasi
PROMPT_HEADER = """
Anda adalah sistem verifikasi fakta medis yang teliti. Tugas Anda:
1) Nilai apakah klaim ini benar, salah, atau sebagian benar tergantung konteks medis.
2) Jika klaim sebagian benar, jelaskan kondisi atau batasan di mana klaim tersebut bisa benar.
3) Output JSON dengan fields: claim, analysis, label (VALID/HOAX/PARTIALLY_VALID), confidence (0-1), evidence (list), summary.
"""

LLM_CONF_THRESHOLD = 0.75
COMBINED_CONF_THRESHOLD = 0.75

# Konfigurasi untuk ekspansi pola relevansi berbasis LLM
_EXPANSION_CACHE: Dict[str, Dict[str, Any]] = {}
EXPANSION_CACHE_TTL = 60 * 60  # 1 jam TTL
EXPANSION_MAX_TERMS = 12
EXPANSION_MIN_TERMS = 3
EXPANSION_MODEL = "gemini-2.5-flash-lite"
EXPANSION_TIMEOUT = 6.0

# -----------------------
# Fungsi utilitas umum
# -----------------------

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
    """Konversi ke string dan strip dengan aman."""
    try:
        if s is None:
            return ""
        return str(s).strip()
    except Exception:
        return ""

# -----------------------
# Ekspansi pola berbasis LLM
# -----------------------

def _claim_cache_key(claim: str) -> str:
    """Buat kunci cache unik untuk klaim."""
    return str(abs(hash(claim)))[:20]

def _safe_parse_json_array(text: str) -> List[str]:
    """Parser JSON array yang toleran: jika LLM mengembalikan plaintext, coba parsing per baris."""
    text = text.strip()
    if not text:
        return []
    
    # Coba parsing JSON dulu
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [safe_strip(p) for p in parsed if isinstance(p, str)]
    except Exception:
        pass

    # Coba ekstrak array dalam kurung siku dari teks
    m = re.search(r'\[.*\]', text, flags=re.S)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, list):
                return [safe_strip(p) for p in parsed if isinstance(p, str)]
        except Exception:
            pass

    # Fallback: pisah berdasarkan baris dan koma
    candidates = []
    for part in re.split(r'[\n\r,;]+', text):
        part = part.strip().lstrip("-•* ").strip()
        if part:
            candidates.append(part)
    return candidates

def expand_relevance_patterns(claim: str, force_refresh: bool = False) -> List[str]:
    """
    Gunakan LLM (Gemini) untuk menghasilkan kata kunci/istilah relevan untuk klaim.
    Mengembalikan list kata/phrase dalam lowercase dengan caching untuk efisiensi.
    """
    claim_key = _claim_cache_key(claim)
    now = int(time.time())

    # Kembalikan cache jika masih fresh
    cached = _EXPANSION_CACHE.get(claim_key)
    if not force_refresh:
        cache_key = _get_cache_key(claim, "relevance_patterns")
        cached = _load_from_cache(cache_key)
        if cached:
            print(f"[CACHE HIT] Using cached relevance patterns")
            return cached

    # Buat prompt untuk ekspansi pola yang lebih medis dan kontekstual
    prompt = (
        f"Anda adalah research assistant medis. Berikan array JSON berisi {EXPANSION_MAX_TERMS} "
        f"istilah pencarian akademik yang spesifik dan relevan untuk meneliti klaim medis ini secara mendalam.\n\n"
        f"Klaim: \"{claim}\"\n\n"
        f"Persyaratan:\n"
        f"- Sertakan istilah medis/dermatologi yang tepat (contoh: 'facial steaming', 'skin hydration', 'pore dilation')\n"
        f"- Tambahkan mekanisme biologis (contoh: 'vasodilation', 'sebum production', 'collagen synthesis')\n"
        f"- Sertakan konteks klinis (contoh: 'dermatology study', 'skin care efficacy', 'cosmetic dermatology')\n"
        f"- Gunakan variasi bahasa Inggris dan Indonesia untuk coverage maksimal\n"
        f"- Fokus pada aspek yang bisa dibuktikan secara ilmiah\n\n"
        f"Format: [\"term1\", \"term2\", \"term3\", ...]\n"
        f"Contoh untuk klaim uap: [\"facial steaming\", \"steam therapy skin\", \"terapi uap wajah\", \"skin hydration mechanism\", \"pore cleansing\", \"dermatology steam\"]"
    )

    try:
        resp = client.models.generate_content(
            model=EXPANSION_MODEL,
            contents=prompt,
            config={"temperature": 0.3, "max_output_tokens": 2000}
        )
        txt = extract_text_from_model_resp(resp)
        txt = safe_strip(txt)
        patterns = _safe_parse_json_array(txt)
        
        # Normalisasi dan filter
        patterns_norm = []
        for p in patterns:
            p2 = re.sub(r'\s+', ' ', p).strip().lower()
            if p2 and p2 not in patterns_norm and len(p2) > 2:
                patterns_norm.append(p2)
            if len(patterns_norm) >= EXPANSION_MAX_TERMS:
                break

        # Fallback pola yang lebih spesifik medis
        if not patterns_norm:
            fallback = [
                "facial steaming", "steam therapy", "skin hydration", "pore dilation",
                "dermatology steam", "cosmetic dermatology", "skin barrier function",
                "terapi uap wajah", "hidrasi kulit", "perawatan wajah"
            ]
            patterns_norm = [p for p in fallback][:EXPANSION_MIN_TERMS]

        # Cache dan kembalikan
        _save_to_cache(cache_key, patterns_norm)
        return patterns_norm

    except Exception as e:
        print(f"[EXPAND] Peringatan: ekspansi pola gagal untuk klaim '{claim}': {e}")
        # Fallback yang lebih baik untuk klaim medis
        medical_fallback = [
            "medical research", "clinical study", "dermatology", "skin care",
            "health effects", "scientific evidence", "medical journal"
        ]
        patterns_norm = [p for p in medical_fallback][:EXPANSION_MIN_TERMS]
        _EXPANSION_CACHE[claim_key] = {"patterns": patterns_norm, "ts": now}
        return patterns_norm
    

# -----------------------
# Scoring relevansi yang dimodifikasi
# -----------------------

def compute_relevance_score(claim: str, neighbor_text: str, neighbor_title: str = "") -> float:
    """
    Hitung skor relevansi menggunakan pola hasil LLM.
    Score = proporsi pola yang muncul di text/title (dibatasi 0..1).
    Juga kombinasikan sedikit keyword matching tradisional untuk kata-kata domain penting.
    """
    claim_lower = safe_strip(claim).lower()
    text_lower = (safe_strip(neighbor_text) + " " + safe_strip(neighbor_title)).lower()

    # Dapatkan pola yang dihasilkan LLM (dari cache)
    try:
        patterns = expand_relevance_patterns(claim)
    except Exception:
        patterns = []

    # Pastikan pola unik dan pendek
    patterns = [p.strip().lower() for p in patterns if p and len(p) <= 60]
    patterns = list(dict.fromkeys(patterns))  # preserve order, unique

    # Jika daftar pola kosong karena alasan apapun, fallback ke heuristik minimal
    if not patterns:
        patterns = ["kulit", "wajah", "uap", "vapor", "hidrasi"]

    hit_count = 0
    for p in patterns:
        # pemeriksaan word boundary untuk token pendek untuk menghindari kecocokan substring yang tidak disengaja
        if len(p.split()) == 1:
            # token tunggal: gunakan word boundary
            if re.search(r'\b' + re.escape(p) + r'\b', text_lower):
                hit_count += 1
        else:
            if p in text_lower:
                hit_count += 1

    score = hit_count / max(len(patterns), 1)
    
    # Soft cap & smoothing: jika sangat sedikit pola yang cocok tapi teks berisi token klaim, tingkatkan sedikit
    if score < 0.2 and any(tok for tok in re.findall(r"[A-Za-z0-9À-ÿ]{3,}", claim_lower) if tok in text_lower):
        score = min(score + 0.15, 1.0)

    return float(max(0.0, min(1.0, score)))

# -----------------------
# Fungsi retrieval dan filtering
# -----------------------

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
    """Konversi metrik jarak ke skor similaritas."""
    if dist is None:
        return 0.0
    try:
        return 1.0 / (1.0 + float(dist))
    except Exception:
        return 0.0

def retrieve_neighbors_from_db(query_embedding: List[float], k: int = 5, 
                              max_chars_each: int = 2000, 
                              debug_print: bool = False) -> List[Dict[str, Any]]:
    """Ambil k tetangga terdekat dari database menggunakan vektor similaritas."""
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
        print(f"[DEBUG] Berhasil mengambil {len(rows)} baris, DOI pertama: {rows[0].get('doi', 'Tidak ada DOI')}")

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

def filter_by_relevance(claim: str, neighbors: List[Dict[str, Any]], 
                       min_relevance: float = 0.3, debug: bool = False) -> List[Dict[str, Any]]:
    """Filter tetangga berdasarkan skor relevansi dan urutkan berdasarkan skor gabungan."""
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
                print(f"[RELEVANSI] Pertahankan dok {nb.get('safe_id')} (skor: {combined_score:.3f})")
        elif debug:
            print(f"[RELEVANSI] Filter dok {nb.get('safe_id')} (skor: {combined_score:.3f})")

    filtered.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return filtered

# -----------------------
# Fungsi terjemahan dan query expansion
# -----------------------

def translate_text_gemini(text: str, target_lang: str = "English") -> str:
    """Terjemahkan teks menggunakan Gemini API."""
    if not text:
        return ""
    
    prompt = (
        f"Terjemahkan teks berikut ke bahasa {target_lang}. "
        f"Pertahankan keringkasan dan preserve terminologi medis bila memungkinkan.\n\n"
        f"Teks:\n\"\"\"\n{text}\n\"\"\"\n\nOutput hanya teks yang diterjemahkan."
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
        print(f"[TERJEMAH] gagal: {e}")
        return text

def generate_bilingual_queries(claim: str, langs: List[str] = ["English"]) -> List[str]:
    """Generate variasi query dalam multiple bahasa dan sinonim yang lebih komprehensif."""
    # Check cache first
    cache_key = _get_cache_key(claim, "bilingual_queries")
    cached = _load_from_cache(cache_key)
    if cached:
        print(f"[CACHE HIT] Using cached bilingual queries")
        return cached
    
    queries = []
    claim_clean = safe_strip(claim)
    
    if claim_clean:
        queries.append(claim_clean)

    # Tambahkan terjemahan
    for lang in langs:
        try:
            translated = translate_text_gemini(claim_clean, target_lang=lang)
            translated = safe_strip(translated)
            if translated and translated not in queries:
                queries.append(translated)
        except Exception:
            pass

    # Minta variasi yang lebih spesifik dari LLM
    english_example = queries[1] if len(queries) > 1 else claim_clean
    syn_prompt = (
        f"Anda adalah research assistant medis. Berdasarkan klaim kesehatan ini, "
        f"buat 4-6 variasi query pencarian akademik yang akan membantu menemukan "
        f"penelitian ilmiah yang relevan, termasuk:\n"
        f"- Istilah medis yang tepat\n"
        f"- Mekanisme biologis yang terlibat\n"
        f"- Studi klinis terkait\n"
        f"- Efek fisiologis\n\n"
        f"Klaim asli: {claim_clean}\n"
        f"Klaim (English): {english_example}\n\n"
        f"Kembalikan array JSON dengan query yang bervariasi dari umum ke spesifik.\n"
        f"Contoh: [\"facial steaming benefits\", \"steam therapy dermatology\", \"skin hydration mechanisms\", \"pore dilation research\"]"
    )
    
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=syn_prompt,
            config={"temperature": 0.3, "max_output_tokens": 300}
        )
        txt = extract_text_from_model_resp(resp)
        txt = safe_strip(txt)
        
        variations = []
        try:
            if txt:
                variations = json.loads(txt)
        except Exception:
            # Tolerant fallback: pisah baris dan strip bullets
            for line in (txt or "").splitlines():
                line = line.strip().lstrip("-• ").strip()
                if line:
                    variations.append(line)
        
        for query in variations:
            query_str = safe_strip(query)
            if query_str and query_str not in queries:
                queries.append(query_str)
                
    except Exception as e:
        print(f"[GEN_QUERIES] gagal: {e}")

    # Dedupe dan batasi
    unique_queries = []
    for q in queries:
        qn = safe_strip(q)
        if qn and qn not in unique_queries:
            unique_queries.append(qn)
    
    _save_to_cache(cache_key, queries)
    return queries

def retrieve_with_expansion_bilingual(claim: str, k: int = 5, 
                                     expand_queries: bool = True, 
                                     debug: bool = False) -> List[Dict[str, Any]]:
    """Retrieve dokumen dengan query expansion dalam multiple bahasa."""
    if expand_queries:
        queries = generate_bilingual_queries(claim, langs=["English"])
    else:
        queries = [claim]

    if debug:
        print(f"[BILINGUAL_QUERIES] Menggunakan queries: {queries}")

    all_neighbors = []
    seen_ids = set()
    
    for query in queries:
        try:
            emb = embed_texts_gemini([query])[0]
        except Exception as e:
            print(f"[RETRIEVE_BIL] embed gagal untuk query '{query}': {e}")
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

# -----------------------
# Fungsi dynamic fetch dan ingest
# -----------------------

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
            print(f"[LOAD_FETCHED] parse error untuk {p}: {e}")
    
    return items

def save_verification_result(result: Dict[str, Any]) -> None:
    """Simpan single verification payload ke JSONL (append)."""
    try:
        with open(VERIFICATION_RESULTS_PATH, "a", encoding="utf-8") as fo:
            fo.write(json.dumps(result, ensure_ascii=False) + "\n")
    except Exception as e:
        # Jangan hentikan pipeline jika gagal menyimpan; cukup laporkan
        print(f"[SAVE_VERIF] Gagal menyimpan hasil verifikasi: {e}")

def ingest_abstracts_as_chunks(selected_items: List[Dict[str, Any]]) -> bool:
    """Ingest selected abstracts sebagai chunks ke database."""
    if not selected_items:
        return False

    chuncks_dir = TRAINING_DIR / "data" / "chunks"
    chuncks_dir.mkdir(parents=True, exist_ok=True)

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
    out_path = chuncks_dir / out_fname

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

    print(f"[FAST_INGEST] Menulis {len(texts)} abstract chunks ke {out_path}")

    try:
        ic.ingest()
        time.sleep(1.0)
        return True
    except Exception as e:
        print(f"[FAST_INGEST] ingest() gagal: {e}")
        return False

def dynamic_fetch_and_update(claim: str, max_fetch_results: int = 10, 
                            top_k_select: int = 8) -> tuple:
    """Fetch dokumen dari multiple sources dan pilih yang paling relevan."""
    print(f"[DYNAMIC_FETCH] Fetching untuk: {claim[:80]}...")
    fetched_paths = []

    # Fetch dari multiple sources
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
            print(f"[DYNAMIC_FETCH] {source_name} gagal: {e}")

    # Parse semua fetched items
    all_items = []
    for fp in fetched_paths:
        try:
            items = load_fetched_file_to_items(fp)
            if items:
                all_items.extend(items)
        except Exception as e:
            print(f"[DYNAMIC_FETCH] Error loading fetched file {fp}: {e}")

    if not all_items:
        print("[DYNAMIC_FETCH] Tidak ada items yang tersedia setelah parsing fetched files.")
        return False, []

    # Siapkan teks untuk embedding
    candidate_texts = []
    candidate_meta = []
    
    for item in all_items:
        text = (item.get("title", "") + "\n\n" + (item.get("abstract", "") or "")).strip()
        if text:
            candidate_texts.append(text)
            candidate_meta.append(item)

    if not candidate_texts:
        print("[DYNAMIC_FETCH] Tidak ada candidate texts untuk di-embed.")
        return False, []

    # Pilih items paling relevan menggunakan cosine similarity
    try:
        claim_vec = embed_texts_gemini([claim])[0]
        candidate_vecs = embed_texts_gemini(candidate_texts)
    except Exception as e:
        print(f"[DYNAMIC_FETCH] Embedding gagal: {e}")
        return False, []

    similarities = [safe_cosine_similarity(claim_vec, v) for v in candidate_vecs]
    idx_sorted = sorted(range(len(similarities)), key=lambda i: similarities[i], reverse=True)[:top_k_select]
    selected = [candidate_meta[i] for i in idx_sorted]

    print(f"[DYNAMIC_FETCH] Terpilih {len(selected)} items (top sims: {[round(similarities[i], 3) for i in idx_sorted[:5]]})")

    # Normalisasi selected items
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
    """Tentukan apakah perlu dynamic fetch berdasarkan quality metrics."""
    if not neighbors:
        if debug:
            print("[QUALITY_CHECK] Tidak ada neighbors -> perlu dynamic fetch.")
        return True

    relevance_scores = [n.get("relevance_score", 0.0) for n in neighbors if n.get("relevance_score") is not None]
    similarity_scores = [distance_to_similarity(n.get("distance")) for n in neighbors if n.get("distance") is not None]

    relevance_mean = float(sum(relevance_scores) / len(relevance_scores)) if relevance_scores else 0.0
    retriever_mean = float(sum(similarity_scores) / len(similarity_scores)) if similarity_scores else 0.0
    max_relevance = max(relevance_scores) if relevance_scores else 0.0

    # Periksa keyword overlap
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

    # Logika keputusan
    quality_thresholds_met = (
        relevance_mean >= min_relevance_mean and 
        retriever_mean >= min_retriever_mean and 
        max_relevance >= min_max_relevance and 
        any_keyword
    )

    if not quality_thresholds_met:
        if debug:
            print("[QUALITY_CHECK] Quality thresholds tidak tercapai -> dynamic fetch direkomendasikan")
        return True

    return False

def translate_snippets_if_needed(neighbors: List[Dict[str, Any]], target_lang="Indonesian") -> List[Dict[str, Any]]:
    """Terjemahkan snippet text ke target language jika diperlukan berdasarkan heuristic."""
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
                print(f"[TRANSLATE] gagal untuk snippet: {e}")
                nb["_text_translated"] = text
        else:
            nb["_text_translated"] = text
    
    return neighbors

# -----------------------
# Fungsi prompt building dan LLM calling
# -----------------------

def build_prompt(claim: str, neighbors: List[Dict[str, Any]], max_context_chars: int = 3000) -> str:
    """Buat prompt untuk LLM dengan evidence dari neighbors."""
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
        source_info += f" | Relevansi: {relevance_score:.3f}"
        
        part = f"{source_info}\n{text_for_prompt}\n---\n"
        if total_chars + len(part) > max_context_chars:
            break
        
        parts.append(part)
        total_chars += len(part)

    context_block = "\n".join(parts)
    
    return f"""{PROMPT_HEADER}

KLAIM:
"{claim.strip()}"

BUKTI ILMIAH:
{context_block}

INSTRUKSI ANALISIS:
- Evaluasi bukti secara menyeluruh dan objektif
- Pertimbangkan mekanisme biologis yang mendasari klaim
- Identifikasi kondisi atau batasan di mana klaim mungkin benar
- Jika ada konflik dalam bukti, jelaskan nuansanya
- Berikan analisis berdasarkan evidence-based medicine

OUTPUT FORMAT:
{{
  "claim": "klaim asli",
  "analysis": "analisis mendalam tentang mekanisme dan bukti",
  "label": "VALID/HOAX/PARTIALLY_VALID",
  "confidence": 0.0-1.0,
  "conditions": "kondisi di mana klaim benar (jika PARTIALLY_VALID)",
  "evidence": [
    {{"safe_id": "id_dokumen", "snippet": "kutipan yang mendukung/menolak", "relevance": "mengapa relevan"}}
  ],
  "summary": "ringkasan kesimpulan yang seimbang"
}}
"""

def call_gemini(prompt: str, model: str = "gemini-2.5-flash-lite", 
               temperature: float = 0.0, max_output_tokens: int = 2000,
               use_cache: bool = True) -> str:
    """Panggil Gemini API dengan caching untuk prompt yang sama."""
    
    # Generate cache key from prompt + config
    if use_cache:
        cache_key = _get_cache_key(
            f"{prompt}|model={model}|temp={temperature}|max_tokens={max_output_tokens}",
            prefix="gemini_verify"
        )
        cached = _load_from_cache(cache_key)
        if cached:
            print("[CACHE HIT] Using cached Gemini verification result", file=sys.stderr)
            return cached
    
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
            
            # Save to cache before returning
            if use_cache:
                _save_to_cache(cache_key, text)
            
            return text
            
        except Exception as e:
            print(f"[DEBUG] call_gemini dengan model {m} gagal: {str(e)}")
            continue
    
    raise RuntimeError("Semua panggilan model Gemini gagal atau mengembalikan kosong.")

def fix_common_json_issues(json_str: str) -> str:
    """Perbaiki masalah sintaks JSON yang umum."""
    s = json_str
    # Hapus trailing commas
    s = re.sub(r',(\s*[}\]])', r'\1', s)
    # Hapus karakter non-printable kecuali newlines, returns, tabs
    s = ''.join(ch for ch in s if ord(ch) >= 32 or ch in '\n\r\t')
    return s

def extract_json_from_text(text: str) -> Dict[str, Any]:
    """Ekstrak dan parse JSON dari response text LLM."""
    s = safe_strip(text)
    if not s:
        return validate_and_normalize_result({})
    
    # Coba parsing JSON biasa dulu
    try:
        parsed = json.loads(s)
        return validate_and_normalize_result(parsed)
    except Exception:
        pass
    
    # Coba cari JSON object dalam teks
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
                    # Coba perbaiki masalah umum
                    candidate_fixed = fix_common_json_issues(candidate)
                    try:
                        parsed = json.loads(candidate_fixed)
                        return validate_and_normalize_result(parsed)
                    except Exception:
                        pass
    
    # Fallback: kembalikan response HOAX default
    print("[PERINGATAN] Tidak dapat mem-parse JSON dari LLM. Mengembalikan response HOAX default.")
    return validate_and_normalize_result({})

def validate_and_normalize_result(result: dict) -> dict:
    """Validasi dan normalisasi result dari LLM ke format yang konsisten."""
    result = result or {}
    
    # Normalisasi label - tambah support untuk PARTIALLY_VALID
    if "label" not in result:
        result["label"] = "HOAX"
    
    label = safe_strip(result.get("label", "")).upper()
    if label not in ["VALID", "HOAX", "PARTIALLY_VALID"]:
        label_mapping = {
            "TRUE": "VALID", "BENAR": "VALID",
            "FALSE": "HOAX", "SALAH": "HOAX",
            "PARTIAL": "PARTIALLY_VALID", "SEBAGIAN": "PARTIALLY_VALID",
            "PARTIALLY_TRUE": "PARTIALLY_VALID", "SEBAGIAN_BENAR": "PARTIALLY_VALID",
            "CONDITIONAL": "PARTIALLY_VALID", "KONDISIONAL": "PARTIALLY_VALID",
            "CONTEXT_DEPENDENT": "PARTIALLY_VALID",
            "UNCERTAIN": "PARTIALLY_VALID", "TIDAK_PASTI": "PARTIALLY_VALID"
        }
        result["label"] = label_mapping.get(label, "HOAX")
    else:
        result["label"] = label
    
    # Normalisasi confidence
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
    result.setdefault("conditions", "")  # Untuk PARTIALLY_VALID
    
    return result

def decide_final_label_and_confidence(parsed: Dict[str, Any], neighbors: List[Dict[str, Any]], 
                                    combined_confidence: float) -> Dict[str, Any]:
    """Tentukan label dan confidence akhir berdasarkan output LLM dan heuristics."""
    llm_label = parsed.get("label", "").upper()
    llm_confidence = float(parsed.get("confidence", 0.0))
    
    # Logika keputusan akhir - include PARTIALLY_VALID
    if llm_label in ["VALID", "HOAX", "PARTIALLY_VALID"] and llm_confidence >= LLM_CONF_THRESHOLD:
        final_label = llm_label
        final_confidence = llm_confidence
        decision_reason = f"Menggunakan vonis LLM (label={llm_label}, confidence={llm_confidence:.2f})"
    else:
        # Untuk fallback, gunakan combined confidence dengan threshold yang berbeda
        if combined_confidence >= 0.7:
            final_label = "VALID"
        elif combined_confidence >= 0.4:
            final_label = "PARTIALLY_VALID"
        else:
            final_label = "HOAX"
        
        final_confidence = combined_confidence
        decision_reason = f"Menggunakan fallback retriever+LLM gabungan (combined_confidence={combined_confidence:.2f})"
    
    return {
        "final_label": final_label,
        "final_confidence": float(final_confidence),
        "decision_reason": decision_reason
    }
def build_frontend_payload(claim: str, parsed: Dict[str, Any], neighbors: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Buat payload untuk frontend dari parsed result dan neighbors."""
    # Map neighbors berdasarkan ID untuk referensi
    neighbor_map = {n.get("safe_id") or str(n.get("doc_id")): n for n in neighbors}
    
    # Proses evidence list
    evidence_list = parsed.get("evidence", []) or []
    references = []
    frontend_evidence = []
    
    for ev in evidence_list:
        safe_id = ev.get("safe_id") or ev.get("id") or ev.get("doc_id") or ""
        nb = neighbor_map.get(safe_id) or {}
        
        # Buat evidence item
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
        
        # Buat reference
        ref_entry = {
            "safe_id": safe_id,
            "doi": doi_val,
            "url": url_val,
            "source_type": "journal" if doi_val else "other",
            "relevance": evidence_item["relevance_score"]
        }
        
        # Tambahkan ke references jika tidak duplikat
        if not any(r.get("safe_id") == ref_entry["safe_id"] and r.get("url") == ref_entry["url"] 
                  for r in references):
            references.append(ref_entry)
    
    # Fallback: gunakan top neighbors sebagai evidence jika kosong
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

# -----------------------
# Main verification function
# -----------------------

def verify_claim_local(claim: str, k: int = 5, dry_run: bool = False, 
                      enable_expansion: bool = True, min_relevance: float = 0.25,
                      force_dynamic_fetch: bool = False, 
                      debug_retrieval: bool = False) -> Dict[str, Any]:
    """Main verification flow - verifikasi klaim medis menggunakan RAG pipeline."""
    print(f"[CACHE_STATS] {json.dumps(get_cache_stats())}", file=sys.stderr)
    claim = safe_strip(claim)
    if not claim:
        raise ValueError("Klaim kosong.")

    # ✅ Check database availability
    if not db_available:
        print("[WARNING] Database not available, verification may be limited", file=sys.stderr)

    try:
        print("[1/6] Mengambil dengan bilingual query expansion...", file=sys.stderr)
        if enable_expansion:
            neighbors = retrieve_with_expansion_bilingual(claim, k=k, expand_queries=True, debug=debug_retrieval)
        else:
            emb = embed_texts_gemini([claim])[0]
            neighbors = retrieve_neighbors_from_db(emb, k=k, debug_print=debug_retrieval)
            neighbors = filter_by_relevance(claim, neighbors, min_relevance=min_relevance, debug=debug_retrieval)

        # Memeriksa apakah perlu dynamic fetch
        quality_need_fetch = force_dynamic_fetch or needs_dynamic_fetch(
            neighbors, claim, min_relevance_mean=min_relevance, min_retriever_mean=0.25, debug=debug_retrieval
        )

        dynamic_selected = None
        if quality_need_fetch:
            print("[2/6] Kualitas retrieval rendah atau tidak cukup. Mencoba dynamic fetch...", file=sys.stderr)
            try:
                did_update, dynamic_selected = dynamic_fetch_and_update(claim, max_fetch_results=30, top_k_select=12)
                if did_update:
                    print("[DYNAMIC_FETCH] Ingest dilakukan. Menunggu DB siap...", file=sys.stderr)
                    time.sleep(2.0)
                    
                    # Retry retrieval setelah ingest
                    if enable_expansion:
                        neighbors = retrieve_with_expansion_bilingual(claim, k=k, expand_queries=True, debug=debug_retrieval)
                    else:
                        emb = embed_texts_gemini([claim])[0]
                        neighbors = retrieve_neighbors_from_db(emb, k=k*2, debug_print=debug_retrieval)
                        neighbors = filter_by_relevance(claim, neighbors, min_relevance=min_relevance, debug=debug_retrieval)

                    if debug_retrieval:
                        print("\n[DEBUG] Neighbors setelah retry (top 6):", file=sys.stderr)
                        for i, n in enumerate(neighbors[:6], 1):
                            print(f"  [{i}] {n.get('safe_id')} rel={n.get('relevance_score',0):.3f} doi={n.get('doi','')}", file=sys.stderr)
                            print(f"        snippet: {n.get('text','')[:200]}...\n", file=sys.stderr)

                    # Menggunakan fetched items sebagai fallback jika masih tidak cukup
                    if needs_dynamic_fetch(neighbors, claim, min_relevance_mean=min_relevance, 
                                         min_retriever_mean=0.25, debug=debug_retrieval):
                        print("[DYNAMIC_FETCH] Retry retrieval setelah dynamic fetch masih berkualitas rendah.", file=sys.stderr)
                        if dynamic_selected:
                            print("[DYNAMIC_FETCH] Menggunakan fetched items sebagai fallback context untuk LLM.", file=sys.stderr)
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
                    print("[DYNAMIC_FETCH] Tidak ada items baru yang di-fetch atau ingest gagal.", file=sys.stderr)
            except Exception as e:
                print(f"[ERROR] Dynamic fetch gagal: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)

        # Handle kasus tidak ada neighbors
        if not neighbors:
            frontend = {
                "claim": claim,
                "label": "inconclusive",
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

        # Menerjemahkan snippets untuk LLM
        neighbors = translate_snippets_if_needed(neighbors, target_lang="Indonesian")

        if dry_run:
            print("\n=== DRY RUN: Neighbors ===", file=sys.stderr)
            for i, n in enumerate(neighbors, 1):
                relevance = n.get('relevance_score', 0)
                print(f"\n[{i}] {n.get('safe_id')} (relevansi: {relevance:.3f})", file=sys.stderr)
                print(f"DOI: {n.get('doi', 'N/A')}", file=sys.stderr)
                print(f"Text: {n.get('_text_translated', n.get('text',''))[:400]}...", file=sys.stderr)
            return {"dry_run_neighbors": neighbors}

        print(f"[3/6] Membuat prompt dengan {len(neighbors)} neighbors yang relevan...", file=sys.stderr)
        prompt = build_prompt(claim, neighbors, max_context_chars=3500)

        print("[4/6] Memanggil LLM untuk verifikasi...", file=sys.stderr)
        try:
            raw_response = call_gemini(prompt, temperature=0.0, max_output_tokens=1600)
        except Exception as e:
            print(f"[ERROR] call_gemini gagal: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            raw_response = ""

        print("[5/6] Parsing hasil dari LLM...", file=sys.stderr)
        parsed = extract_json_from_text(raw_response) if raw_response else validate_and_normalize_result({})

        print("[6/6] Memperkaya dengan metadata dan membuat frontend payload...", file=sys.stderr)
        
        # Menghitung metrics
        similarity_scores = [distance_to_similarity(n.get("distance")) for n in neighbors if n.get("distance") is not None]
        relevance_scores = [n.get("relevance_score", 0.0) for n in neighbors]
        
        retriever_mean = float(sum(similarity_scores) / len(similarity_scores)) if similarity_scores else 0.0
        relevance_mean = float(sum(relevance_scores) / len(relevance_scores)) if relevance_scores else 0.0
        llm_confidence = float(parsed.get("confidence") or 0.0)
        
        combined_confidence = (0.5 * llm_confidence + 0.3 * relevance_mean + 0.2 * retriever_mean)

        # Menambahkan metadata
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

        # Logika keputusan akhir
        final_decision = decide_final_label_and_confidence(parsed, neighbors, combined_confidence)
        parsed.update(final_decision)
        
        # Memaksa label akhir (hanya VALID/HOAX)
        parsed["label"] = parsed["final_label"]
        parsed["confidence"] = parsed["final_confidence"]

        # Buat frontend payload
        frontend = build_frontend_payload(claim, parsed, neighbors)

        # Menyimpan hasil verifikasi agar bisa di-ingest oleh backend / pipeline lain
        try:
            payload_to_save = {
                "timestamp": int(time.time()),
                "claim": frontend.get("claim"),
                "frontend": frontend,
                "_parsed_meta": parsed.get("_meta", {}),
            }
            save_verification_result(payload_to_save)
        except Exception as e:
            print(f"[SAVE_VERIF] Warning: gagal menyimpan payload: {e}", file=sys.stderr)

        # Print JSON output dan return
        print("\n[JSON_OUTPUT]")
        print(json.dumps(frontend, ensure_ascii=False, indent=2))
        
        return {"_frontend_payload": frontend}

    except Exception as e:
        error_msg = f"Exception dalam verify_claim_local: {str(e)}"
        print(f"[ERROR] {error_msg}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        
        # Return error response instead of raising
        error_frontend = {
            "claim": claim,
            "label": "inconclusive",
            "confidence": 0.0,
            "summary": f"Error dalam verifikasi: {str(e)}",
            "conclusion": "Terjadi kesalahan teknis saat memproses klaim.",
            "evidence": [],
            "references": [],
            "metadata": {"error": error_msg}
        }
        print("\n[JSON_OUTPUT]")
        print(json.dumps(error_frontend, ensure_ascii=False, indent=2))
        return {"_frontend_payload": error_frontend}

# -----------------------
# CLI main function
# -----------------------

def main():
    """CLI entry point untuk menjalankan fact-checking system."""
    parser = argparse.ArgumentParser(
        description="Improved Prompt & Verify - Healthify RAG dengan bilingual retrieval dan LLM-based pattern expansion"
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
        print("Masukkan klaim (akhiri dengan ENTER): ", file=sys.stderr)
        claim = input("> ").strip()

    if not claim:
        print("Error: Klaim tidak boleh kosong", file=sys.stderr)
        sys.exit(1)

    if args.enable_prefetch:
        queries = generate_bilingual_queries(claim, langs=["English"])
        print(f"[MAIN] Generated queries untuk fetch: {queries}", file=sys.stderr)

        for q in queries:
            try:
                print(f"[MAIN] Fetching untuk expanded query: {q}", file=sys.stderr)
                fetch_all_sources(q, pubmed_max=5, crossref_rows=5, semantic_limit=5, delay_between_sources=0.3)
            except Exception as e:
                print(f"[MAIN] fetch_all_sources gagal untuk '{q}': {e}", file=sys.stderr)

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
        print(f"\n❌ Gagal verifikasi klaim: {str(e)}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

    # Print ringkasan yang user-friendly
    print("\n" + "="*60, file=sys.stderr)
    print("HASIL VERIFIKASI (ringkasan untuk pengguna)", file=sys.stderr)
    print("="*60, file=sys.stderr)

    frontend = result.get("_frontend_payload") if isinstance(result, dict) else None
    if frontend:
        print(f"\n📋 KLAIM: {frontend.get('claim')}", file=sys.stderr)
        print(f"\n🏷️  LABEL: {frontend.get('label')}", file=sys.stderr)
        print(f"📊 CONFIDENCE: {frontend.get('confidence'):.2%}", file=sys.stderr)
        print(f"\n💡 RINGKASAN:\n{frontend.get('summary','')}", file=sys.stderr)
        print(f"\n🔍 KESIMPULAN:\n{frontend.get('conclusion','')}", file=sys.stderr)
        
        metadata = frontend.get("metadata", {})
        if metadata:
            print(f"\n📈 METADATA:", file=sys.stderr)
            print(f"   - Neighbors yang diambil: {metadata.get('neighbors_count', 0)}", file=sys.stderr)
            print(f"   - Neighbors dengan DOI: {metadata.get('neighbors_with_doi', 0)}", file=sys.stderr)
            print(f"   - Mean relevance score: {metadata.get('relevance_mean', 0):.3f}", file=sys.stderr)
            print(f"   - Mean similarity score: {metadata.get('retriever_mean_similarity', 0):.3f}", file=sys.stderr)
            print(f"   - Combined confidence: {metadata.get('combined_confidence', 0):.2%}", file=sys.stderr)

    if args.save_json and frontend:
        with open(args.save_json, "w", encoding="utf-8") as fo:
            json.dump(frontend, fo, ensure_ascii=False, indent=2)
        print(f"\n💾 Hasil disimpan ke: {args.save_json}", file=sys.stderr)

    print("\n" + "="*60, file=sys.stderr)
    print("✅ Selesai.", file=sys.stderr)
    print("="*60, file=sys.stderr)


if __name__ == "__main__":
    main()