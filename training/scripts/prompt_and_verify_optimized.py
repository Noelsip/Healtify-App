import os
import re
import json
import time
import uuid
import hashlib
import pathlib
import argparse
import sys
import traceback
import logging
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from functools import lru_cache
import threading

from dotenv import load_dotenv, find_dotenv
from google import genai
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
from pgvector.psycopg2 import register_vector

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(asctime)s %(name)s %(message)s'
)
logger = logging.getLogger(__name__)
# ============================================
# CONFIGURATION - TUNED FOR SPEED
# ============================================

BASE = pathlib.Path(__file__).parent
TRAINING_DIR = BASE.parent
PROJECT_ROOT = TRAINING_DIR.parent
DATA_DIR = TRAINING_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Performance settings - AGGRESSIVE
MAX_WORKERS = 6
FETCH_TIMEOUT_PER_SOURCE = 8  # detik per source
TOTAL_FETCH_TIMEOUT = 15      # total timeout untuk semua fetch
EMBEDDING_TIMEOUT = 10
DB_QUERY_TIMEOUT = 5
LLM_TIMEOUT = 15
CACHE_TTL = 7200  # 2 jam

# Quality thresholds
# Dibuat lebih ketat supaya fetching eksternal (CrossRef/Semantic Scholar/PubMed)
# lebih sering dipanggil dan jurnal internasional lebih banyak dipertimbangkan.
MIN_NEIGHBORS_FOR_SKIP_FETCH = 8
MIN_QUALITY_FOR_SKIP_FETCH = 0.80
MAX_NEIGHBORS_TO_PROCESS = 8

# ============================================
# ENVIRONMENT & CLIENT SETUP
# ============================================

def load_env():
    for p in [TRAINING_DIR / ".env", PROJECT_ROOT / ".env", find_dotenv()]:
        if p and pathlib.Path(p).exists():
            load_dotenv(dotenv_path=p, override=True)
            return
    load_dotenv()

load_env()

def translate_to_english_fast(text: str) -> str:
    """Fast translation untuk query expansion."""
    try:
        client = get_gemini_client()
        prompt = f"Translate to English (medical terms): {text}\nOutput translation only."
        
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 100}
        )
        
        return extract_llm_text(resp).strip() or text
    except:
        return text

# Lazy client initialization
_gemini_client = None
def get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found")
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client

# Connection pool untuk database
_db_pool = None
def get_db_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD")
        )
    return _db_pool

DB_TABLE = "embeddings"

# ============================================
# THREAD-SAFE CACHING
# ============================================

class FastCache:
    """High-performance thread-safe cache."""
    
    def __init__(self, max_size: int = 1000, ttl: int = CACHE_TTL):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._lock = threading.RLock()
        self.ttl = ttl
        self.max_size = max_size
        self._hits = 0
        self._misses = 0
    
    def _key(self, s: str) -> str:
        return hashlib.md5(s.encode()).hexdigest()[:20]
    
    def get(self, key: str) -> Optional[Any]:
        k = self._key(key)
        with self._lock:
            if k in self._cache:
                val, ts = self._cache[k]
                if time.time() - ts < self.ttl:
                    self._hits += 1
                    return val
                del self._cache[k]
            self._misses += 1
        return None
    
    def set(self, key: str, value: Any):
        k = self._key(key)
        with self._lock:
            # Evict oldest if full
            if len(self._cache) >= self.max_size:
                oldest = min(self._cache.items(), key=lambda x: x[1][1])
                del self._cache[oldest[0]]
            self._cache[k] = (value, time.time())
    
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0,
            "size": len(self._cache)
        }

# Global caches
embedding_cache = FastCache(max_size=500)
llm_cache = FastCache(max_size=200)
fetch_cache = FastCache(max_size=100, ttl=CACHE_TTL * 2)

# ============================================
# UTILITY FUNCTIONS
# ============================================


def safe_strip(s) -> str:
    """Konversi ke string dan strip dengan aman."""
    try:
        return str(s).strip() if s else ""
    except Exception:
        return ""
    
def text_hash(text: str) -> str:
    """Generate hash untuk text."""
    return hashlib.sha256(text.encode()).hexdigest()[:24]

def extract_llm_text(resp) -> str:
    """Ekstrak teks dari berbagai format respons Gemini API."""
    try:
        if hasattr(resp, "text") and resp.text:
            return resp.text
        if hasattr(resp, "candidates") and resp.candidates:
            if hasattr(resp.candidates[0], "content"):
                if hasattr(resp.candidates[0].content, "parts"):
                    if resp.candidates[0].content.parts:
                        if hasattr(resp.candidates[0].content.parts[0], "text"):
                            return resp.candidates[0].content.parts[0].text
    except Exception as e:
        logger.warning(f"[EXTRACT_TEXT] Error: {e}")
    
    return str(resp) if resp else ""


# ============================================
# OPTIMIZED EMBEDDING (BATCH + CACHE)
# ============================================

def embed_batch_cached(texts: List[str], timeout: int = EMBEDDING_TIMEOUT) -> List[List[float]]:
    """Batch embed dengan aggressive caching."""
    if not texts:
        return []
    
    results = [None] * len(texts)
    to_embed = []
    to_embed_idx = []
    
    # Check cache
    for i, t in enumerate(texts):
        h = text_hash(t)
        cached = embedding_cache.get(h)
        if cached is not None:
            results[i] = cached
        else:
            to_embed.append(t)
            to_embed_idx.append(i)
    
    # Embed uncached in single batch
    if to_embed:
        try:
            client = get_gemini_client()
            resp = client.models.embed_content(
                model="gemini-embedding-001",
                contents=to_embed
            )
            
            embeddings = []
            if hasattr(resp, "embeddings"):
                for emb in resp.embeddings:
                    if hasattr(emb, "values"):
                        embeddings.append(list(emb.values))
                    else:
                        embeddings.append(list(emb))
            
            for idx, emb in zip(to_embed_idx, embeddings):
                results[idx] = emb
                embedding_cache.set(text_hash(texts[idx]), emb)
                
        except Exception as e:
            print(f"[EMBED] Error: {e}", file=sys.stderr)
            # Fallback: zero vectors
            for idx in to_embed_idx:
                results[idx] = [0.0] * 768
    
    return results

# ============================================
# FAST RELEVANCE SCORING (NO LLM)
# ============================================

# Pre-compiled keyword sets
MEDICAL_KW_ID = frozenset({
    'kulit', 'wajah', 'kesehatan', 'penyakit', 'obat', 'terapi', 
    'medis', 'klinis', 'penelitian', 'studi', 'efek', 'manfaat',
    'vitamin', 'nutrisi', 'diet', 'jantung', 'darah', 'kanker',
    'diabetes', 'kolesterol', 'imun', 'infeksi', 'virus', 'bakteri'
})

MEDICAL_KW_EN = frozenset({
    'skin', 'health', 'disease', 'medicine', 'therapy', 'clinical',
    'study', 'research', 'effect', 'benefit', 'treatment', 'vitamin',
    'heart', 'blood', 'cancer', 'diabetes', 'immune', 'infection'
})

ALL_MEDICAL_KW = MEDICAL_KW_ID | MEDICAL_KW_EN

@lru_cache(maxsize=1000)
def extract_keywords(text: str) -> frozenset:
    """Extract keywords dengan caching."""
    return frozenset(re.findall(r'[a-zA-Zà-ÿ]{4,}', text.lower()))

def compute_relevance_fast(claim: str, text: str, title: str = "") -> float:
    """Ultra-fast relevance scoring."""
    claim_tokens = set(re.findall(r'\w+', claim.lower()))
    text_tokens = set(re.findall(r'\w+', (text + " " + title).lower()))
    
    if not claim_tokens:
        return 0.0
    
    overlap = len(claim_tokens & text_tokens)
    return min(1.0, overlap / len(claim_tokens))

# ============================================
# OPTIMIZED DATABASE RETRIEVAL
# ============================================

def retrieve_fast(query_emb: List[float], k: int = 10) -> List[Dict]:
    """Fast retrieval dengan connection pooling."""
    pool = get_db_pool()
    conn = pool.getconn()
    
    try:
        register_vector(conn)
        emb_str = "[" + ",".join(str(float(x)) for x in query_emb) + "]"
        
        sql = f"""
            SELECT doc_id, safe_id, source_file, chunk_index,
                   LEFT(text, 1500) as text, doi,
                   embedding <-> %s::vector AS distance
            FROM {DB_TABLE}
            WHERE embedding IS NOT NULL
            ORDER BY distance
            LIMIT %s;
        """
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (emb_str, k))
            rows = cur.fetchall()
        
        results = []
        for r in rows:
            dist = float(r.get("distance", 1.0) or 1.0)
            results.append({
                "doc_id": r.get("doc_id"),
                "safe_id": r.get("safe_id"),
                "text": safe_strip(r.get("text", "")),
                "doi": r.get("doi", ""),
                "distance": dist,
                "similarity": 1.0 / (1.0 + dist)
            })
        return results
        
    finally:
        pool.putconn(conn)

def retrieve_and_score(claim: str, k: int = 10) -> Tuple[List[Dict], float]:
    """Single-pass retrieval + scoring - WITH PRIORITY FOR UPDATED SOURCES."""
    
    # ✅ STEP 1: Check apakah claim ini sudah pernah di-approve dengan sources baru
    claim_hash = text_hash(claim)
    
    # Query: find VerificationResult yang updated_at RECENT (dalam 24 jam terakhir)
    # dengan label yang BERBEDA dari inference awal
    try:
        from django.utils import timezone
        from datetime import timedelta
        from api.models import Claim, VerificationResult, ClaimSource
        
        recent_claims = Claim.objects.filter(
            text_hash=claim_hash,
            verification_result__updated_at__gte=timezone.now() - timedelta(hours=24)
        ).select_related('verification_result').prefetch_related('sources')
        
        for recent_claim in recent_claims:
            vr = recent_claim.verification_result
            sources = recent_claim.sources.all()
            
            logger.info(f"[RETRIEVE] Found recently updated claim {recent_claim.id}")
            logger.info(f"           Label: {vr.label}, Confidence: {vr.confidence}")
            logger.info(f"           Sources: {sources.count()} (updated at {vr.updated_at})")
            
            # ✅ Use updated sources instead of retrieval!
            if sources.count() > 0:
                updated_neighbors = []
                for source_link in sources.all()[:10]:
                    source = source_link.source
                    updated_neighbors.append({
                        "safe_id": source.doi or source.url or f"src_{source.id}",
                        "title": source.title,
                        "text": source.title,  # Fallback
                        "doi": source.doi,
                        "url": source.url,
                        "source_type": source.source_type,
                        "relevance_score": source_link.relevance_score,
                        "snippet": source_link.excerpt,
                        "_from_update": True,  # Mark as from approved update
                        "similarity": 1.0  # Max similarity since admin approved
                    })
                
                logger.info(f"[RETRIEVE] Using {len(updated_neighbors)} approved sources")
                
                # Compute quality dari updated sources
                rel_scores = [n["relevance_score"] for n in updated_neighbors]
                quality = sum(rel_scores) / len(rel_scores) if rel_scores else 0.5
                
                return updated_neighbors, quality
    
    except Exception as e:
        logger.warning(f"[RETRIEVE] Error checking updates: {e}")
    
    # ✅ STEP 2: Normal retrieval jika tidak ada update
    emb = embed_batch_cached([claim])[0]
    neighbors = retrieve_fast(emb, k=k)
    
    if not neighbors:
        logger.warning("[RETRIEVE] No neighbors found from DB")
        return [], 0.0
    
    # Score neighbors
    for nb in neighbors:
        rel = compute_relevance_fast(claim, nb.get("text", ""), nb.get("safe_id", ""))
        sim = nb.get("similarity", 0)
        nb["relevance_score"] = 0.5 * sim + 0.5 * rel
    
    neighbors.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    
    top_scores = [n["relevance_score"] for n in neighbors[:5]]
    quality = sum(top_scores) / len(top_scores) if top_scores else 0
    
    return neighbors, quality

# ============================================
# PARALLEL FETCHING (CRITICAL OPTIMIZATION)
# ============================================

def fetch_crossref_fast(query: str, limit: int = 5) -> List[Dict]:
    """Fast CrossRef fetch."""
    import requests
    try:
        url = "https://api.crossref.org/works"
        params = {"query.title": query, "rows": limit}
        headers = {"User-Agent": "healthify/2.0"}
        
        resp = requests.get(url, params=params, headers=headers, timeout=FETCH_TIMEOUT_PER_SOURCE)
        resp.raise_for_status()
        
        items = []
        for item in resp.json().get("message", {}).get("items", []):
            title = " ".join(item.get("title", [])) if item.get("title") else ""
            items.append({
                "title": title,
                "abstract": item.get("abstract", ""),
                "doi": item.get("DOI", ""),
                "source": "crossref"
            })
        return items
    except Exception as e:
        print(f"[FETCH] CrossRef error: {e}", file=sys.stderr)
        return []

def fetch_semantic_fast(query: str, limit: int = 5) -> List[Dict]:
    """Fast Semantic Scholar fetch."""
    import requests
    try:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {"query": query, "limit": limit, "fields": "title,abstract,doi"}
        headers = {"User-Agent": "healthify/2.0"}
        
        api_key = os.getenv("S2_API_KEY")
        if api_key:
            headers["x-api-key"] = api_key
        
        resp = requests.get(url, params=params, headers=headers, timeout=FETCH_TIMEOUT_PER_SOURCE)
        resp.raise_for_status()
        
        items = []
        for paper in resp.json().get("data", []):
            items.append({
                "title": paper.get("title", ""),
                "abstract": paper.get("abstract", ""),
                "doi": paper.get("doi", ""),
                "source": "semantic_scholar"
            })
        return items
    except Exception as e:
        print(f"[FETCH] Semantic Scholar error: {e}", file=sys.stderr)
        return []

def fetch_pubmed_fast(query: str, limit: int = 5) -> List[Dict]:
    """Fast PubMed fetch - simplified."""
    import requests
    try:
        # Search
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        params = {"db": "pubmed", "retmode": "json", "retmax": limit, "term": query}
        api_key = os.getenv("NCBI_API_KEY")
        if api_key:
            params["api_key"] = api_key
        
        resp = requests.get(search_url, params=params, timeout=FETCH_TIMEOUT_PER_SOURCE)
        resp.raise_for_status()
        ids = resp.json().get("esearchresult", {}).get("idlist", [])
        
        if not ids:
            return []
        
        # Fetch summaries (faster than full XML)
        summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        params = {"db": "pubmed", "retmode": "json", "id": ",".join(ids)}
        if api_key:
            params["api_key"] = api_key
        
        resp = requests.get(summary_url, params=params, timeout=FETCH_TIMEOUT_PER_SOURCE)
        resp.raise_for_status()
        
        items = []
        result = resp.json().get("result", {})
        for pid in ids:
            if pid in result:
                doc = result[pid]
                items.append({
                    "title": doc.get("title", ""),
                    "abstract": "",  # Summary doesn't include abstract
                    "doi": "",
                    "source": "pubmed"
                })
        return items
    except Exception as e:
        print(f"[FETCH] PubMed error: {e}", file=sys.stderr)
        return []

def parallel_fetch_all(claim: str, limit_per_source: int = 5) -> List[Dict]:
    """Fetch dengan BILINGUAL queries."""
    
    # ✅ Translate to English
    claim_en = translate_to_english_fast(claim)
    logger.info(f"[FETCH] ID query: {claim[:60]}")
    logger.info(f"[FETCH] EN query: {claim_en[:60]}")
    
    # 🆕 Translate to English for better international results
    logger.info("[FETCH] Translating to English...")
    claim_en = translate_to_english_fast(claim)
    logger.info(f"[FETCH] English query: {claim_en[:60]}")
    
    all_items = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            # Indonesian queries
            executor.submit(fetch_crossref_fast, claim, limit_per_source): "crossref_id",
            executor.submit(fetch_semantic_fast, claim, limit_per_source): "semantic_id",
            
            # ✅ English queries - CRITICAL untuk journal internasional
            executor.submit(fetch_crossref_fast, claim_en, limit_per_source): "crossref_en",
            executor.submit(fetch_semantic_fast, claim_en, limit_per_source): "semantic_en",
            executor.submit(fetch_pubmed_fast, claim_en, limit_per_source): "pubmed_en",
        }
        
        for future in futures:
            try:
                result = future.result(timeout=TOTAL_FETCH_TIMEOUT)
                if result:
                    all_items.extend(result)
                    logger.info(f"[FETCH] {futures[future]}: {len(result)} items")
            except FuturesTimeoutError:
                logger.warning(f"[FETCH] {futures[future]}: timeout")
            except Exception as e:
                logger.warning(f"[FETCH] {futures[future]}: {e}")
    
    # Remove duplicates based on DOI
    seen_dois = set()
    unique_items = []
    for item in all_items:
        doi = item.get("doi", "")
        if doi and doi in seen_dois:
            continue
        if doi:
            seen_dois.add(doi)
        unique_items.append(item)
    
    logger.info(f"[FETCH] Total unique items: {len(unique_items)}")
    
    # Cache results
    if unique_items:
        fetch_cache.set(cache_key, unique_items)
    
    return unique_items

# ============================================
# FAST INGEST (IN-MEMORY ONLY FOR SPEED)
# ============================================

def create_virtual_neighbors(items: List[Dict], claim: str) -> List[Dict]:
    """
    Alih-alih ingest ke DB (lambat), buat virtual neighbors di memory.
    Ini JAUH lebih cepat untuk real-time verification.
    """
    if not items:
        return []
    
    logger.info(f"[VIRTUAL_NEIGHBORS] Creating from {len(items)} items")
    
    # Prepare texts
    texts = []
    metas = []
    for item in items:
        text = (item.get("title", "") + "\n\n" + (item.get("abstract", "") or "")).strip()
        if len(text) > 30:
            texts.append(text)
            metas.append(item)
    
    if not texts:
        logger.warning("[VIRTUAL_NEIGHBORS] No valid texts found")
        return []
    
    # Batch embed
    try:
        all_texts = [claim] + texts
        embeddings = embed_batch_cached(all_texts)
        
        claim_emb = embeddings[0]
        text_embs = embeddings[1:]
    except Exception as e:
        logger.error(f"[VIRTUAL_NEIGHBORS] Embedding error: {e}")
        return []
    
    # Score dan buat virtual neighbors
    virtual_neighbors = []
    for i, (text, meta, emb) in enumerate(zip(texts, metas, text_embs)):
        # Cosine similarity
        dot = sum(a*b for a, b in zip(claim_emb, emb))
        norm_a = (sum(a*a for a in claim_emb) ** 0.5) or 1.0
        norm_b = (sum(b*b for b in emb) ** 0.5) or 1.0
        
        similarity = dot / (norm_a * norm_b) if norm_a and norm_b else 0.0
        similarity = max(0.0, min(similarity, 1.0))
        
        # Compute relevance
        relevance = compute_relevance_fast(claim, text, meta.get("title", ""))
        
        virtual_neighbors.append({
            "safe_id": meta.get("doi", f"virtual_{i}"),
            "title": meta.get("title", "Unknown"),
            "text": text[:500],
            "excerpt": text[:200],
            "doi": meta.get("doi", ""),
            "url": meta.get("url", ""),
            "similarity": similarity,
            "relevance_score": 0.6 * similarity + 0.4 * relevance,
            "_from_update": False
        })
    
    # Sort by relevance descending
    virtual_neighbors.sort(key=lambda x: x["relevance_score"], reverse=True)
    logger.info(f"[VIRTUAL_NEIGHBORS] Created {len(virtual_neighbors)} neighbors")
    
    return virtual_neighbors

# ============================================
# SIMPLIFIED LLM VERIFICATION
# ============================================

PROMPT_TEMPLATE = """Anda adalah sistem verifikasi fakta medis yang teliti dan objektif.

KLAIM YANG DIVERIFIKASI:
"{claim}"

BUKTI ILMIAH YANG TERSEDIA:
{evidence}

INSTRUKSI:
1. Evaluasi bukti secara menyeluruh dan objektif
2. Tentukan apakah klaim didukung, ditolak, atau sebagian benar berdasarkan bukti
3. Pertimbangkan mekanisme biologis yang mendasari klaim
4. Jika ada konflik dalam bukti, jelaskan nuansanya
5. Berikan confidence score 0.0-1.0 yang realistis
6. Fokuskan analisis hanya pada klaim di atas. 
   Jangan mengalihkan pembahasan ke topik lain (misalnya kehamilan) jika tidak secara langsung menjawab klaim tersebut.
7. Jika bukti tidak spesifik untuk klaim (misalnya hanya membahas risiko kehamilan), jelaskan bahwa bukti TIDAK LANGSUNG mendukung klaim dan simpulkan secara jujur (uncertain/unverified).
OUTPUT FORMAT (JSON ONLY):
{{
    "label": "VALID atau HOAX atau UNCERTAIN",
    "confidence": 0.0-1.0,
    "summary": "Ringkasan singkat (2-3 kalimat) yang secara langsung menjawab klaim di atas, jelaskan apakah klaim benar/salah/tidak pasti dan SEBUTKAN kalau bukti hanya terkait topik lain."
}}

CATATAN:
- VALID: Klaim didukung oleh bukti ilmiah yang kuat
- HOAX: Klaim bertentangan dengan bukti yang ada
- UNCERTAIN: Klaim sebagian benar atau terbatas pada kondisi tertentu
- Output HANYA JSON, jangan ada teks tambahan
"""

def build_evidence_text(neighbors: List[Dict], max_chars: int = 2000) -> str:
    """Build evidence string dari neighbors dengan smart truncation."""
    if not neighbors:
        return "No evidence found."
    
    parts = []
    total = 0
    
    for i, nb in enumerate(neighbors[:6], 1):
        title = nb.get("title", "Unknown")[:100]
        relevance = nb.get("relevance_score", 0)
        
        # Build entry tanpa menambahkan potongan teks jurnal
        # Hanya sertakan judul singkat dan skor relevansi agar LLM menyimpulkan sendiri
        entry = f"{i}. {title} (relevance: {relevance:.1%})"
        
        # Check if we have space
        if total + len(entry) <= max_chars:
            parts.append(entry)
            total += len(entry)
        else:
            break
    
    return "\n".join(parts) if parts else "No evidence excerpts available."

def call_llm_cached(claim: str, neighbors: List[Dict]) -> Dict[str, Any]:
    """LLM call dengan caching yang smart."""
    
    # Build cache key
    neighbor_ids = "_".join(
        n.get("doi", n.get("safe_id", "")[:10]) 
        for n in neighbors[:5]
    )
    has_approved_sources = any(n.get("_from_update") for n in neighbors)
    cache_key = f"llm:{text_hash(claim)}:{hashlib.md5(neighbor_ids.encode()).hexdigest()[:12]}"
    if has_approved_sources:
        cache_key += ":approved"
    
    # Check cache
    cached = llm_cache.get(cache_key)
    if cached and not has_approved_sources:  
        logger.info("[LLM] Cache hit (non-approved sources)")
        return cached
    
    # Build evidence
    evidence_text = build_evidence_text(neighbors)
    prompt = PROMPT_TEMPLATE.format(claim=claim, evidence=evidence_text)
    
    try:
        logger.info(f"[LLM] Calling Gemini with {len(neighbors)} sources")
        logger.debug(f"      Cache key: {cache_key}")
        
        client = get_gemini_client()
        
        # ✅ FIX: Gunakan response_schema BUKAN generation_config
        # atau gunakan parameter yang correct
        try:
            # Method 1: Newer API version (try first)
            resp = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
                config={
                    "temperature": 0.0,
                    "max_output_tokens": 2000,
                }
            )
        except TypeError:
            # Method 2: Older API version fallback
            logger.warning("[LLM] Using fallback API format")
            import google.generativeai as genai
            
            model = genai.GenerativeModel(
                "gemini-2.5-flash-lite",
                generation_config=genai.types.GenerationConfig(
                    temperature=0.0,
                    max_output_tokens=2000
                )
            )
            resp = model.generate_content(prompt)
        
        result_text = extract_llm_text(resp)
        
        # Parse JSON dengan error handling
        try:
            if result_text.startswith('{'):
                parsed = json.loads(result_text)
            else:
                # Find JSON block
                json_start = result_text.find('{')
                json_end = result_text.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    parsed = json.loads(result_text[json_start:json_end])
                else:
                    raise ValueError("No JSON found in response")
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[LLM] JSON parse error: {e}")
            parsed = {
                "label": "inconclusive",
                "confidence": 0.5,
                "summary": result_text[:500] if result_text else "Verification inconclusive"
            }
        
        # Cache result
        if not has_approved_sources:
            llm_cache.set(cache_key, parsed)
        
        logger.info(f"[LLM] Result: label={parsed.get('label')}, conf={parsed.get('confidence')}")
        return parsed
    
    except Exception as e:
        logger.error(f"[LLM] Error: {e}", exc_info=True)
        return {
            "label": "inconclusive",
            "confidence": 0.0,
            "summary": f"Verification failed: {str(e)[:200]}"
        }
        
# ============================================
# MAIN VERIFICATION (OPTIMIZED FLOW)
# ============================================

def verify_claim_v2(
    claim: str,
    k: int = 10,
    enable_fetch: bool = True,
    debug: bool = False
) -> Dict[str, Any]:
    """
    Optimized verification - target <30 detik.
    
    Flow:
    1. Retrieve dari DB (2-3s)
    2. Jika quality cukup -> skip ke LLM
    3. Jika quality rendah -> parallel fetch + virtual neighbors (8-15s)
    4. LLM verification (3-8s)
    5. Build response
    """
    start = time.time()
    claim = safe_strip(claim)
    
    if not claim:
        raise ValueError("Claim cannot be empty")
    
    logger.info(f"\n[V2] Verifying: {claim[:60]}...")
    
    # Step 1: Initial DB retrieval
    t1 = time.time()
    logger.info("[1/4] DB retrieval...")
    try:
        neighbors, quality = retrieve_and_score(claim, k=k)
        logger.info(
            f"      {len(neighbors)} neighbors, quality={quality:.3f} ({time.time()-t1:.1f}s)"
        )
    except Exception as e:
        logger.error(f"[RETRIEVE] Error: {e}")
        neighbors, quality = [], 0.0
    
    # Step 2: Decide if we need fetch
    need_fetch = (
        enable_fetch and 
        (quality < MIN_QUALITY_FOR_SKIP_FETCH or len(neighbors) < MIN_NEIGHBORS_FOR_SKIP_FETCH)
    )
    
    if need_fetch:
        logger.info(f"[2/4] Fetching from external sources (quality={quality:.3f})...")
        t2 = time.time()
        try:
            fetch_items = parallel_fetch_all(claim, limit_per_source=5)
            virtual_neighbors = create_virtual_neighbors(fetch_items, claim)
            neighbors.extend(virtual_neighbors)
            logger.info(f"      Fetched {len(fetch_items)} items, created {len(virtual_neighbors)} neighbors ({time.time()-t2:.1f}s)")
        except Exception as e:
            logger.warning(f"[FETCH] Error: {e}, continuing with DB results")
    else:
        logger.info(f"[2/4] Skipping fetch (quality OK)")
    
    # Handle no results
    if not neighbors:
        logger.warning("[VERIFY] No neighbors found, returning unverified")
        return {
            "claim": claim,
            "label": "unverified",
            "confidence": None,
            "summary": "Tidak ada sumber pendukung ditemukan untuk klaim ini.",
            "sources": [],
            "_processing_time": time.time() - start,
            "_method": "empty_result"
        }
    
    # Step 3: LLM verification
    t4 = time.time()
    logger.info("[3/4] LLM verification...")
    llm_result = call_llm_cached(claim, neighbors)
    logger.info(f"      Done ({time.time()-t4:.1f}s)")
    
    # Step 4: Build response
    logger.info("[4/4] Building response...")
    
    evidence = []
    references = []
    
    for nb in neighbors[:6]:
        # Build evidence entry
        evidence_entry = {
            "safe_id": nb.get("safe_id", "unknown"),
            "snippet": nb.get("excerpt", nb.get("text", ""))[:300],
            "doi": nb.get("doi", ""),
            "relevance_score": nb.get("relevance_score", 0)
        }
        evidence.append(evidence_entry)
        
        # Build reference entry
        reference_entry = {
            "safe_id": nb.get("safe_id", "unknown"),
            "doi": nb.get("doi", ""),
            "url": nb.get("url", f"https://doi.org/{nb.get('doi')}" if nb.get("doi") else "")
        }
        references.append(reference_entry)
    
    # Extract final label
    raw_label = llm_result.get("label", "unverified").lower().strip()
    label_mapping = {
        "valid": "valid",
        "true": "valid",
        "hoax": "hoax",
        "false": "hoax",
        "uncertain": "uncertain",
        "partially_valid": "uncertain",
        "unverified": "unverified",
        "inconclusive": "unverified"
    }
    final_label = label_mapping.get(raw_label, "unverified")
    
    # Extract confidence
    try:
        confidence = float(llm_result.get("confidence", 0.0))
        if confidence > 1.0:
            confidence /= 100.0
        confidence = max(0.0, min(confidence, 1.0))
        if final_label == "unverified":
            confidence = None
    except (TypeError, ValueError):
        confidence = None if final_label == "unverified" else 0.5
    
    elapsed = time.time() - start
    
    result = {
        "claim": claim,
        "label": final_label,
        "confidence": confidence,
        "summary": llm_result.get("summary", ""),
        "sources": evidence,
        "references": references,
        "_meta": {
            "time": round(elapsed, 2),
            "quality": round(quality, 3),
            "neighbors_count": len(neighbors),
            "cache_stats": {
                "embedding": embedding_cache.stats(),
                "llm": llm_cache.stats(),
                "fetch": fetch_cache.stats()
            }
        }
    }
    
    logger.info(
        f"\n[V2] Complete: {final_label} "
        f"(conf={f'{confidence*100:.0f}%' if confidence else 'N/A'}) "
        f"in {elapsed:.1f}s\n"
    )
    
    return result

# ============================================
# CLI ENTRY POINT
# ============================================

def main():
    parser = argparse.ArgumentParser(description="Optimized Claim Verification v2")
    parser.add_argument("--claim", "-c", type=str, help="Claim to verify")
    parser.add_argument("--k", type=int, default=10, help="Number of neighbors")
    parser.add_argument("--no-fetch", action="store_true", help="Disable dynamic fetch")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    
    args = parser.parse_args()
    
    claim = args.claim
    if not claim:
        print("Masukkan klaim: ", file=sys.stderr)
        claim = input("> ").strip()
    
    if not claim:
        print("Error: Klaim kosong", file=sys.stderr)
        sys.exit(1)
    
    try:
        result = verify_claim_v2(
            claim=claim,
            k=args.k,
            enable_fetch=not args.no_fetch,
            debug=args.debug
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

def translate_to_english_fast(text: str) -> str:
    """Fast translation untuk query expansion."""
    try:
        client = get_gemini_client()
        prompt = f"Translate to English (medical terms): {text}\nOutput translation only."
        
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 100}
        )
        
        return extract_llm_text(resp).strip() or text
    except:
        return text

# Update parallel_fetch_all to use English queries
def parallel_fetch_all(claim: str, limit_per_source: int = 5) -> List[Dict]:
    """Fetch dengan bilingual queries untuk hasil internasional."""
    cache_key = f"fetch:{text_hash(claim)}"
    cached = fetch_cache.get(cache_key)
    if cached:
        return cached
    
    # Translate to English for better international results
    claim_en = translate_to_english_fast(claim)
    
    all_items = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Use BOTH Indonesian and English queries
        futures = {
            # Indonesian query
            executor.submit(fetch_crossref_fast, claim, limit_per_source): "crossref_id",
            executor.submit(fetch_semantic_fast, claim, limit_per_source): "semantic_id",
            executor.submit(fetch_pubmed_fast, claim, limit_per_source): "pubmed_id",
            # English query for international journals
            executor.submit(fetch_crossref_fast, claim_en, limit_per_source): "crossref_en",
            executor.submit(fetch_semantic_fast, claim_en, limit_per_source): "semantic_en",
            executor.submit(fetch_pubmed_fast, claim_en, limit_per_source): "pubmed_en",
        }
        
        for future in futures:
            try:
                result = future.result(timeout=TOTAL_FETCH_TIMEOUT)
                if result:
                    all_items.extend(result)
            except:
                pass
    
    if all_items:
        fetch_cache.set(cache_key, all_items)
    
    return all_items

if __name__ == "__main__":
    main()