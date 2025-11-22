"""
Optimized Prompt & Verify v2 - Target: <30 detik
Key optimizations:
1. Parallel fetching dengan asyncio/threading
2. Aggressive caching (embedding, LLM responses, fetch results)
3. Early exit strategies
4. Batch embedding
5. Simplified relevance scoring (no LLM call)
6. Connection pooling untuk database
"""

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
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from functools import lru_cache
import threading

from dotenv import load_dotenv, find_dotenv
from google import genai
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
from pgvector.psycopg2 import register_vector

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
MIN_NEIGHBORS_FOR_SKIP_FETCH = 3
MIN_QUALITY_FOR_SKIP_FETCH = 0.35
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
    return str(s).strip() if s else ""

def text_hash(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()[:24]

def extract_llm_text(resp) -> str:
    try:
        if hasattr(resp, "text"):
            return resp.text or ""
        if hasattr(resp, "candidates") and resp.candidates:
            c = resp.candidates[0]
            if hasattr(c, "content") and hasattr(c.content, "parts"):
                return c.content.parts[0].text or ""
        return str(resp) if resp else ""
    except:
        return ""

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
    """Ultra-fast relevance tanpa LLM."""
    claim_kw = extract_keywords(claim)
    text_kw = extract_keywords(text + " " + title)
    
    if not claim_kw:
        return 0.0
    
    # Word overlap
    overlap = len(claim_kw & text_kw)
    overlap_score = overlap / len(claim_kw)
    
    # Medical keyword bonus
    claim_medical = claim_kw & ALL_MEDICAL_KW
    text_medical = text_kw & ALL_MEDICAL_KW
    medical_overlap = len(claim_medical & text_medical)
    medical_score = medical_overlap / max(len(claim_medical), 1) if claim_medical else 0
    
    return min(1.0, 0.6 * overlap_score + 0.4 * medical_score)

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
    """Single-pass retrieval + scoring."""
    emb = embed_batch_cached([claim])[0]
    neighbors = retrieve_fast(emb, k=k)
    
    if not neighbors:
        return [], 0.0
    
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
    """Fetch dari semua source secara PARALLEL."""
    # Check cache
    cache_key = f"fetch:{text_hash(claim)}"
    cached = fetch_cache.get(cache_key)
    if cached:
        print("[FETCH] Cache hit!", file=sys.stderr)
        return cached
    
    all_items = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_crossref_fast, claim, limit_per_source): "crossref",
            executor.submit(fetch_semantic_fast, claim, limit_per_source): "semantic",
            executor.submit(fetch_pubmed_fast, claim, limit_per_source): "pubmed",
        }
        
        for future in futures:
            try:
                result = future.result(timeout=TOTAL_FETCH_TIMEOUT)
                if result:
                    all_items.extend(result)
                    print(f"[FETCH] {futures[future]}: {len(result)} items", file=sys.stderr)
            except FuturesTimeoutError:
                print(f"[FETCH] {futures[future]}: timeout", file=sys.stderr)
            except Exception as e:
                print(f"[FETCH] {futures[future]}: {e}", file=sys.stderr)
    
    # Cache results
    if all_items:
        fetch_cache.set(cache_key, all_items)
    
    return all_items

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
    
    # Prepare texts
    texts = []
    metas = []
    for item in items:
        text = (item.get("title", "") + "\n\n" + (item.get("abstract", "") or "")).strip()
        if len(text) > 30:
            texts.append(text)
            metas.append(item)
    
    if not texts:
        return []
    
    # Batch embed
    all_texts = [claim] + texts
    embeddings = embed_batch_cached(all_texts)
    
    claim_emb = embeddings[0]
    text_embs = embeddings[1:]
    
    # Score dan buat virtual neighbors
    virtual_neighbors = []
    for i, (text, meta, emb) in enumerate(zip(texts, metas, text_embs)):
        # Cosine similarity
        dot = sum(a*b for a, b in zip(claim_emb, emb))
        norm_a = sum(a*a for a in claim_emb) ** 0.5
        norm_b = sum(b*b for b in emb) ** 0.5
        similarity = dot / (norm_a * norm_b) if norm_a and norm_b else 0
        
        rel = compute_relevance_fast(claim, text, meta.get("title", ""))
        
        virtual_neighbors.append({
            "doc_id": meta.get("doi") or f"virtual_{i}",
            "safe_id": meta.get("doi") or f"virtual_{i}",
            "text": text[:1500],
            "doi": meta.get("doi", ""),
            "distance": 1.0 - similarity,
            "similarity": similarity,
            "relevance_score": 0.5 * similarity + 0.5 * rel,
            "_virtual": True
        })
    
    # Sort by score
    virtual_neighbors.sort(key=lambda x: x["relevance_score"], reverse=True)
    return virtual_neighbors

# ============================================
# SIMPLIFIED LLM VERIFICATION
# ============================================

PROMPT_TEMPLATE = """Anda sistem verifikasi fakta medis. Analisis klaim berdasarkan bukti.

KLAIM: "{claim}"

BUKTI:
{evidence}

Output JSON saja:
{{"label": "VALID/HOAX/PARTIALLY_VALID", "confidence": 0.0-1.0, "summary": "penjelasan singkat"}}

VALID = didukung bukti, HOAX = bertentangan, PARTIALLY_VALID = benar dalam kondisi tertentu."""

def build_evidence_text(neighbors: List[Dict], max_chars: int = 2000) -> str:
    parts = []
    total = 0
    for i, nb in enumerate(neighbors[:6], 1):
        text = nb.get("text", "")[:350]
        doi = nb.get("doi", "N/A")
        part = f"[{i}] DOI:{doi}\n{text}\n"
        if total + len(part) > max_chars:
            break
        parts.append(part)
        total += len(part)
    return "\n".join(parts)

def call_llm_cached(claim: str, neighbors: List[Dict]) -> Dict[str, Any]:
    """LLM call dengan caching."""
    # Build cache key from claim + top neighbor IDs
    neighbor_ids = "_".join(n.get("safe_id", "")[:10] for n in neighbors[:3])
    cache_key = f"llm:{text_hash(claim)}:{neighbor_ids}"
    
    cached = llm_cache.get(cache_key)
    if cached:
        print("[LLM] Cache hit!", file=sys.stderr)
        return cached
    
    evidence_text = build_evidence_text(neighbors)
    prompt = PROMPT_TEMPLATE.format(claim=claim, evidence=evidence_text)
    
    try:
        client = get_gemini_client()
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config={
                "temperature": 0.0,
                "max_output_tokens": 500,
                "response_mime_type": "application/json"
            }
        )
        
        text = extract_llm_text(resp)
        text = text.replace("```json", "").replace("```", "").strip()
        
        result = json.loads(text)
        llm_cache.set(cache_key, result)
        return result
        
    except Exception as e:
        print(f"[LLM] Error: {e}", file=sys.stderr)
        return {"label": "inconclusive", "confidence": 0.0, "summary": str(e)}

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
        raise ValueError("Klaim kosong")
    
    print(f"\n[V2] Verifying: {claim[:60]}...", file=sys.stderr)
    
    # Step 1: Initial DB retrieval
    t1 = time.time()
    print("[1/4] DB retrieval...", file=sys.stderr)
    neighbors, quality = retrieve_and_score(claim, k=k)
    print(f"      {len(neighbors)} neighbors, quality={quality:.3f} ({time.time()-t1:.1f}s)", file=sys.stderr)
    
    # Step 2: Decide if we need fetch
    need_fetch = (
        enable_fetch and 
        (quality < MIN_QUALITY_FOR_SKIP_FETCH or len(neighbors) < MIN_NEIGHBORS_FOR_SKIP_FETCH)
    )
    
    if need_fetch:
        t2 = time.time()
        print("[2/4] Parallel fetch...", file=sys.stderr)
        
        # Parallel fetch
        fetched = parallel_fetch_all(claim, limit_per_source=6)
        print(f"      Fetched {len(fetched)} items ({time.time()-t2:.1f}s)", file=sys.stderr)
        
        if fetched:
            # Create virtual neighbors (NO DB ingest - much faster!)
            t3 = time.time()
            virtual = create_virtual_neighbors(fetched, claim)
            print(f"      Created {len(virtual)} virtual neighbors ({time.time()-t3:.1f}s)", file=sys.stderr)
            
            # Merge with DB neighbors
            if virtual:
                # Combine and re-sort
                all_neighbors = neighbors + virtual
                all_neighbors.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
                neighbors = all_neighbors[:MAX_NEIGHBORS_TO_PROCESS]
                
                # Recalculate quality
                top_scores = [n["relevance_score"] for n in neighbors[:5]]
                quality = sum(top_scores) / len(top_scores) if top_scores else 0
                print(f"      New quality={quality:.3f}", file=sys.stderr)
    else:
        print("[2/4] Skipping fetch (quality OK)", file=sys.stderr)
    
    # Handle no results
    if not neighbors:
        elapsed = time.time() - start
        result = {
            "claim": claim,
            "label": "inconclusive",
            "confidence": 0.0,
            "summary": "Tidak ditemukan bukti ilmiah yang relevan.",
            "evidence": [],
            "references": [],
            "_meta": {"time": elapsed, "quality": 0}
        }
        print(f"\n[V2] No results ({elapsed:.1f}s)", file=sys.stderr)
        print("\n[JSON_OUTPUT]")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    
    # Step 3: LLM verification
    t4 = time.time()
    print("[3/4] LLM verification...", file=sys.stderr)
    llm_result = call_llm_cached(claim, neighbors)
    print(f"      Done ({time.time()-t4:.1f}s)", file=sys.stderr)
    
    # Step 4: Build response
    print("[4/4] Building response...", file=sys.stderr)
    
    evidence = []
    references = []
    
    for nb in neighbors[:6]:
        ev = {
            "safe_id": nb.get("safe_id", ""),
            "snippet": nb.get("text", "")[:300],
            "doi": nb.get("doi", ""),
            "relevance_score": round(nb.get("relevance_score", 0), 3)
        }
        evidence.append(ev)
        
        if nb.get("doi"):
            references.append({
                "safe_id": nb.get("safe_id", ""),
                "doi": nb.get("doi"),
                "url": f"https://doi.org/{nb['doi']}"
            })
    
    # Normalize label
    raw_label = llm_result.get("label", "inconclusive").upper()
    label_map = {
        "VALID": "true", "TRUE": "true", "BENAR": "true",
        "HOAX": "false", "FALSE": "false", "SALAH": "false",
        "PARTIALLY_VALID": "misleading", "PARTIAL": "misleading"
    }
    label = label_map.get(raw_label, "inconclusive")
    
    elapsed = time.time() - start
    
    result = {
        "claim": claim,
        "label": label,
        "confidence": float(llm_result.get("confidence", 0.0)),
        "summary": llm_result.get("summary", ""),
        "evidence": evidence,
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
    
    print(f"\n[V2] Complete: {label} ({result['confidence']:.0%}) in {elapsed:.1f}s", file=sys.stderr)
    print("\n[JSON_OUTPUT]")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    
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


if __name__ == "__main__":
    main()