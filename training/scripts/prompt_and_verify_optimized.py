"""
Optimized Prompt & Verify - Healthify RAG Pipeline
Versi yang dioptimasi untuk performa <30 detik untuk klaim baru

Optimasi utama:
1. Parallel fetching dari multiple sources
2. Batch embedding (semua teks dalam satu API call)
3. Aggressive caching dengan TTL
4. Lazy translation (hanya untuk LLM prompt)
5. Early exit jika retrieval sudah cukup bagus
6. Simplified relevance scoring (tanpa LLM call)
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
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Third party
from dotenv import load_dotenv, find_dotenv
from google import genai
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector

# Project modules - import dengan error handling
try:
    import fetch_sources as fs
    import process_raw as praw
    import ingest_chunks_to_pg as ic
    import chunk_and_embed as cae
    from ingest_chunks_to_pg import connect_db, DB_TABLE
    from chunk_and_embed import embed_texts_gemini
except ImportError as e:
    print(f"[IMPORT] Warning: {e}", file=sys.stderr)

# ============================================
# CONFIGURATION
# ============================================

BASE = pathlib.Path(__file__).parent
TRAINING_DIR = BASE.parent
PROJECT_ROOT = TRAINING_DIR.parent
DATA_DIR = TRAINING_DIR / "data"
CHUNKS_DIR = DATA_DIR / "chunks"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Performance settings
MAX_WORKERS = 4  # Thread pool size untuk parallel fetch
FETCH_TIMEOUT = 15  # Timeout per source dalam detik
EMBEDDING_BATCH_SIZE = 32
CACHE_TTL = 3600  # 1 jam
MIN_QUALITY_THRESHOLD = 0.35  # Skip dynamic fetch jika quality >= ini
FAST_MODE_THRESHOLD = 0.5  # Skip expensive operations jika quality >= ini

# LLM settings
LLM_MODEL = "gemini-2.5-flash-lite"
LLM_TEMPERATURE = 0.0
LLM_MAX_TOKENS = 1500

# ============================================
# ENVIRONMENT SETUP
# ============================================

def load_environment():
    """Load environment variables."""
    for path in [TRAINING_DIR / ".env", PROJECT_ROOT / ".env", find_dotenv()]:
        if path and pathlib.Path(path).exists():
            load_dotenv(dotenv_path=path, override=True)
            return True
    load_dotenv()
    return False

load_environment()

# Initialize Gemini client
_client = None
def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found")
        _client = genai.Client(api_key=api_key)
    return _client

# ============================================
# CACHING UTILITIES
# ============================================

class SimpleCache:
    """Thread-safe in-memory cache dengan TTL."""
    
    def __init__(self, ttl: int = CACHE_TTL):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self.ttl = ttl
    
    def _hash_key(self, key: str) -> str:
        return hashlib.md5(key.encode()).hexdigest()[:16]
    
    def get(self, key: str) -> Optional[Any]:
        hkey = self._hash_key(key)
        with self._lock:
            if hkey in self._cache:
                value, timestamp = self._cache[hkey]
                if time.time() - timestamp < self.ttl:
                    return value
                del self._cache[hkey]
        return None
    
    def set(self, key: str, value: Any):
        hkey = self._hash_key(key)
        with self._lock:
            self._cache[hkey] = (value, time.time())
    
    def clear_expired(self):
        now = time.time()
        with self._lock:
            expired = [k for k, (_, ts) in self._cache.items() if now - ts >= self.ttl]
            for k in expired:
                del self._cache[k]

# Global caches
_embedding_cache = SimpleCache(ttl=CACHE_TTL)
_query_cache = SimpleCache(ttl=CACHE_TTL)
_fetch_cache = SimpleCache(ttl=CACHE_TTL * 2)  # Longer TTL for fetched data

# ============================================
# UTILITY FUNCTIONS
# ============================================

def safe_strip(s) -> str:
    if s is None:
        return ""
    return str(s).strip()

def extract_text_from_response(resp) -> str:
    """Extract text from Gemini API response."""
    try:
        if hasattr(resp, "text"):
            return resp.text or ""
        if hasattr(resp, "candidates") and resp.candidates:
            cand = resp.candidates[0]
            if hasattr(cand, "content") and hasattr(cand.content, "parts"):
                return cand.content.parts[0].text or ""
        return str(resp) if resp else ""
    except Exception:
        return ""

def compute_text_hash(text: str) -> str:
    """Generate hash untuk caching."""
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()[:32]

# ============================================
# OPTIMIZED EMBEDDING (BATCH + CACHE)
# ============================================

def embed_texts_batch_cached(texts: List[str]) -> List[List[float]]:
    """
    Embed texts dengan caching dan batching.
    Jauh lebih efisien daripada embed satu per satu.
    """
    if not texts:
        return []
    
    results = [None] * len(texts)
    texts_to_embed = []
    indices_to_embed = []
    
    # Check cache first
    for i, text in enumerate(texts):
        text_hash = compute_text_hash(text)
        cached = _embedding_cache.get(text_hash)
        if cached is not None:
            results[i] = cached
        else:
            texts_to_embed.append(text)
            indices_to_embed.append(i)
    
    # Embed uncached texts in batch
    if texts_to_embed:
        try:
            embeddings = embed_texts_gemini(texts_to_embed, batch_size=EMBEDDING_BATCH_SIZE)
            for idx, emb in zip(indices_to_embed, embeddings):
                results[idx] = emb
                # Cache the result
                text_hash = compute_text_hash(texts[idx])
                _embedding_cache.set(text_hash, emb)
        except Exception as e:
            print(f"[EMBED] Error: {e}", file=sys.stderr)
            # Return zero vectors as fallback
            for idx in indices_to_embed:
                results[idx] = [0.0] * 768
    
    return results

# ============================================
# SIMPLIFIED RELEVANCE SCORING (NO LLM)
# ============================================

# Pre-compiled medical keywords untuk fast matching
MEDICAL_KEYWORDS = {
    'id': {'kulit', 'wajah', 'kesehatan', 'penyakit', 'obat', 'terapi', 'dokter', 
           'medis', 'klinis', 'penelitian', 'studi', 'efek', 'manfaat', 'bahaya',
           'vitamin', 'nutrisi', 'diet', 'olahraga', 'tidur', 'stress'},
    'en': {'skin', 'health', 'disease', 'medicine', 'therapy', 'clinical', 
           'study', 'research', 'effect', 'benefit', 'risk', 'treatment',
           'vitamin', 'nutrition', 'diet', 'exercise', 'sleep', 'stress'}
}

def compute_relevance_fast(claim: str, text: str, title: str = "") -> float:
    """
    Fast relevance scoring tanpa LLM call.
    Menggunakan keyword matching dan TF-IDF-like scoring.
    """
    claim_lower = claim.lower()
    text_lower = (text + " " + title).lower()
    
    # Extract significant words dari claim (>3 chars)
    claim_words = set(re.findall(r'[a-zA-Zà-ÿ]{4,}', claim_lower))
    text_words = set(re.findall(r'[a-zA-Zà-ÿ]{4,}', text_lower))
    
    if not claim_words:
        return 0.0
    
    # Direct word overlap
    overlap = claim_words & text_words
    overlap_score = len(overlap) / len(claim_words) if claim_words else 0
    
    # Medical keyword bonus
    all_medical = MEDICAL_KEYWORDS['id'] | MEDICAL_KEYWORDS['en']
    medical_in_claim = claim_words & all_medical
    medical_in_text = text_words & all_medical
    medical_overlap = medical_in_claim & medical_in_text
    medical_score = len(medical_overlap) / max(len(medical_in_claim), 1) if medical_in_claim else 0
    
    # N-gram matching (bigrams)
    claim_bigrams = set(zip(claim_lower.split(), claim_lower.split()[1:]))
    text_bigrams = set(zip(text_lower.split(), text_lower.split()[1:]))
    bigram_overlap = len(claim_bigrams & text_bigrams) / max(len(claim_bigrams), 1)
    
    # Combined score
    score = 0.5 * overlap_score + 0.3 * medical_score + 0.2 * bigram_overlap
    return min(1.0, max(0.0, score))

# ============================================
# OPTIMIZED DATABASE RETRIEVAL
# ============================================

def retrieve_neighbors_fast(query_embedding: List[float], k: int = 10) -> List[Dict[str, Any]]:
    """Retrieve neighbors dengan optimized query."""
    try:
        conn = connect_db()
        register_vector(conn)
        
        emb_str = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"
        
        # Optimized SQL dengan LIMIT dan filter
        sql = f"""
            SELECT doc_id, safe_id, source_file, chunk_index, n_words, 
                   LEFT(text, 2000) as text, doi,
                   embedding <-> %s::vector AS distance
            FROM {DB_TABLE}
            WHERE embedding IS NOT NULL
            ORDER BY distance
            LIMIT %s;
        """
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (emb_str, k))
            rows = cur.fetchall()
        
        conn.close()
        
        results = []
        for r in rows:
            dist = float(r.get("distance", 1.0)) if r.get("distance") else 1.0
            similarity = 1.0 / (1.0 + dist)
            
            results.append({
                "doc_id": r.get("doc_id"),
                "safe_id": r.get("safe_id"),
                "source_file": r.get("source_file"),
                "chunk_index": r.get("chunk_index"),
                "text": safe_strip(r.get("text", "")),
                "doi": r.get("doi", ""),
                "distance": dist,
                "similarity": similarity
            })
        
        return results
    
    except Exception as e:
        print(f"[DB] Error: {e}", file=sys.stderr)
        return []

def retrieve_and_score(claim: str, k: int = 10) -> Tuple[List[Dict], float]:
    """
    Single-pass retrieval dengan scoring.
    Returns: (neighbors, quality_score)
    """
    # Embed claim
    claim_emb = embed_texts_batch_cached([claim])[0]
    
    # Retrieve from DB
    neighbors = retrieve_neighbors_fast(claim_emb, k=k)
    
    if not neighbors:
        return [], 0.0
    
    # Score relevance untuk setiap neighbor
    for nb in neighbors:
        rel_score = compute_relevance_fast(claim, nb.get("text", ""), nb.get("safe_id", ""))
        sim_score = nb.get("similarity", 0)
        nb["relevance_score"] = 0.6 * sim_score + 0.4 * rel_score
    
    # Sort by combined score
    neighbors.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    
    # Calculate quality score
    top_scores = [n.get("relevance_score", 0) for n in neighbors[:5]]
    quality = sum(top_scores) / len(top_scores) if top_scores else 0
    
    return neighbors, quality

# ============================================
# PARALLEL FETCHING
# ============================================

def fetch_source_safe(source_name: str, fetch_func, query: str, limit: int) -> List[Dict]:
    """Fetch dari satu source dengan timeout dan error handling."""
    try:
        result = fetch_func(query, limit)
        if result:
            # Parse hasil fetch
            items = parse_fetch_result(source_name, result)
            return items
    except Exception as e:
        print(f"[FETCH] {source_name} error: {e}", file=sys.stderr)
    return []

def parse_fetch_result(source: str, result) -> List[Dict]:
    """Parse fetch result ke format standar."""
    items = []
    
    if isinstance(result, str):
        path = pathlib.Path(result)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except:
            return []
    elif isinstance(result, dict):
        data = result
    else:
        return []
    
    # Parse berdasarkan source
    if source == "crossref":
        for item in data.get("message", {}).get("items", []):
            title = " ".join(item.get("title", [])) if item.get("title") else ""
            items.append({
                "title": title,
                "abstract": item.get("abstract", ""),
                "doi": item.get("DOI", ""),
                "source": "crossref"
            })
    
    elif source == "semantic_scholar":
        for paper in data.get("detailed_results", []) or data.get("data", []):
            items.append({
                "title": paper.get("title", ""),
                "abstract": paper.get("abstract", ""),
                "doi": paper.get("doi", ""),
                "source": "semantic_scholar"
            })
    
    elif source == "pubmed":
        # Simplified pubmed parsing
        if isinstance(data, list):
            for item in data:
                items.append({
                    "title": item.get("title", ""),
                    "abstract": item.get("abstract", ""),
                    "doi": item.get("doi", ""),
                    "source": "pubmed"
                })
    
    return items

def parallel_fetch(claim: str, max_per_source: int = 8) -> List[Dict]:
    """
    Fetch dari multiple sources secara PARALLEL.
    Jauh lebih cepat daripada sequential.
    """
    # Check cache first
    cache_key = f"fetch:{compute_text_hash(claim)}"
    cached = _fetch_cache.get(cache_key)
    if cached:
        print("[FETCH] Using cached results", file=sys.stderr)
        return cached
    
    all_items = []
    
    # Define fetch tasks
    fetch_tasks = [
        ("crossref", lambda q, l: fs.fetch_crossref(q, rows=l)),
        ("semantic_scholar", lambda q, l: fs.fetch_semantic_scholar(q, limit=l)),
    ]
    
    # Try to add pubmed if available
    try:
        fetch_tasks.append(("pubmed", lambda q, l: fs.fetch_pubmed(q, maximum_results=l)))
    except:
        pass
    
    # Execute in parallel
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for source_name, fetch_func in fetch_tasks:
            future = executor.submit(
                fetch_source_safe, 
                source_name, 
                fetch_func, 
                claim, 
                max_per_source
            )
            futures[future] = source_name
        
        # Collect results with timeout
        for future in as_completed(futures, timeout=FETCH_TIMEOUT):
            try:
                items = future.result(timeout=5)
                if items:
                    all_items.extend(items)
                    print(f"[FETCH] {futures[future]}: {len(items)} items", file=sys.stderr)
            except Exception as e:
                print(f"[FETCH] {futures[future]} timeout/error: {e}", file=sys.stderr)
    
    # Cache results
    if all_items:
        _fetch_cache.set(cache_key, all_items)
    
    return all_items

# ============================================
# FAST INGEST (SIMPLIFIED)
# ============================================

def fast_ingest_items(items: List[Dict], claim: str) -> bool:
    """
    Ingest items ke database dengan cara yang lebih cepat.
    Hanya process items yang paling relevan.
    """
    if not items:
        return False
    
    # Prepare texts
    texts = []
    metas = []
    
    for item in items:
        text = (item.get("title", "") + "\n\n" + (item.get("abstract", "") or "")).strip()
        if len(text) > 50:  # Skip terlalu pendek
            texts.append(text)
            metas.append(item)
    
    if not texts:
        return False
    
    # Batch embed (sudah optimized dengan cache)
    print(f"[INGEST] Embedding {len(texts)} items...", file=sys.stderr)
    embeddings = embed_texts_batch_cached(texts)
    
    # Score dan filter top items
    claim_emb = embed_texts_batch_cached([claim])[0]
    
    scored_items = []
    for i, (text, meta, emb) in enumerate(zip(texts, metas, embeddings)):
        # Cosine similarity
        sim = sum(a*b for a,b in zip(claim_emb, emb))
        norm_a = sum(a*a for a in claim_emb) ** 0.5
        norm_b = sum(b*b for b in emb) ** 0.5
        similarity = sim / (norm_a * norm_b) if norm_a and norm_b else 0
        
        scored_items.append((similarity, text, meta, emb))
    
    # Sort dan ambil top items
    scored_items.sort(reverse=True, key=lambda x: x[0])
    top_items = scored_items[:10]  # Hanya top 10
    
    # Write to JSONL
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CHUNKS_DIR / f"dynamic_{int(time.time())}.jsonl"
    
    with open(out_path, "w", encoding="utf-8") as fo:
        for sim, text, meta, emb in top_items:
            record = {
                "doc_id": meta.get("doi") or str(uuid.uuid4())[:8],
                "safe_id": meta.get("doi") or str(uuid.uuid4())[:8],
                "source_file": "dynamic_fetch",
                "chunk_index": 0,
                "n_words": len(text.split()),
                "text": text[:2000],
                "doi": meta.get("doi", ""),
                "embedding": emb
            }
            fo.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    # Ingest ke DB
    try:
        ic.ingest()
        return True
    except Exception as e:
        print(f"[INGEST] Error: {e}", file=sys.stderr)
        return False

# ============================================
# LLM VERIFICATION (SIMPLIFIED PROMPT)
# ============================================

PROMPT_TEMPLATE = """Anda adalah sistem verifikasi fakta medis. Analisis klaim berikut berdasarkan bukti ilmiah yang diberikan.

KLAIM: "{claim}"

BUKTI:
{evidence}

Berikan output JSON dengan format:
{{
  "label": "VALID" atau "HOAX" atau "PARTIALLY_VALID",
  "confidence": 0.0-1.0,
  "summary": "penjelasan singkat hasil verifikasi",
  "evidence_used": ["id bukti yang digunakan"]
}}

Catatan:
- VALID = klaim didukung bukti ilmiah
- HOAX = klaim bertentangan dengan bukti ilmiah
- PARTIALLY_VALID = klaim benar dalam kondisi tertentu

Output HANYA JSON, tanpa teks lain."""

def build_evidence_text(neighbors: List[Dict], max_chars: int = 2500) -> str:
    """Build evidence text untuk prompt."""
    parts = []
    total = 0
    
    for i, nb in enumerate(neighbors[:8], 1):
        text = nb.get("text", "")[:400]
        doi = nb.get("doi", "")
        rel = nb.get("relevance_score", 0)
        
        part = f"[{i}] (relevance: {rel:.2f}) {doi}\n{text}\n"
        
        if total + len(part) > max_chars:
            break
        
        parts.append(part)
        total += len(part)
    
    return "\n".join(parts)

def call_llm_verify(claim: str, neighbors: List[Dict]) -> Dict[str, Any]:
    """Call LLM untuk verifikasi dengan prompt yang simplified."""
    evidence_text = build_evidence_text(neighbors)
    prompt = PROMPT_TEMPLATE.format(claim=claim, evidence=evidence_text)
    
    try:
        client = get_client()
        resp = client.models.generate_content(
            model=LLM_MODEL,
            contents=prompt,
            config={
                "temperature": LLM_TEMPERATURE,
                "max_output_tokens": LLM_MAX_TOKENS,
                "response_mime_type": "application/json"
            }
        )
        
        text = extract_text_from_response(resp)
        text = text.replace("```json", "").replace("```", "").strip()
        
        result = json.loads(text)
        return result
    
    except Exception as e:
        print(f"[LLM] Error: {e}", file=sys.stderr)
        return {
            "label": "inconclusive",
            "confidence": 0.0,
            "summary": f"Error dalam verifikasi: {str(e)}"
        }

# ============================================
# MAIN VERIFICATION FUNCTION (OPTIMIZED)
# ============================================

def verify_claim_optimized(
    claim: str,
    k: int = 10,
    enable_dynamic_fetch: bool = True,
    debug: bool = False
) -> Dict[str, Any]:
    """
    Optimized verification flow.
    Target: <30 detik untuk klaim baru.
    """
    start_time = time.time()
    claim = safe_strip(claim)
    
    if not claim:
        raise ValueError("Klaim kosong")
    
    print(f"\n[VERIFY] Starting: {claim[:60]}...", file=sys.stderr)
    
    # Step 1: Initial retrieval (~2-3 detik)
    print("[1/4] Retrieving from database...", file=sys.stderr)
    t1 = time.time()
    neighbors, quality = retrieve_and_score(claim, k=k)
    print(f"      Found {len(neighbors)} neighbors, quality={quality:.3f} ({time.time()-t1:.1f}s)", file=sys.stderr)
    
    # Step 2: Dynamic fetch jika quality rendah (~5-15 detik)
    if enable_dynamic_fetch and quality < MIN_QUALITY_THRESHOLD and len(neighbors) < 3:
        print("[2/4] Quality low, fetching from sources...", file=sys.stderr)
        t2 = time.time()
        
        # Parallel fetch
        fetched_items = parallel_fetch(claim, max_per_source=8)
        
        if fetched_items:
            print(f"      Fetched {len(fetched_items)} items ({time.time()-t2:.1f}s)", file=sys.stderr)
            
            # Fast ingest
            t3 = time.time()
            did_ingest = fast_ingest_items(fetched_items, claim)
            
            if did_ingest:
                print(f"      Ingested to DB ({time.time()-t3:.1f}s)", file=sys.stderr)
                time.sleep(0.5)  # Brief wait
                
                # Retry retrieval
                neighbors, quality = retrieve_and_score(claim, k=k)
                print(f"      Re-retrieved: {len(neighbors)} neighbors, quality={quality:.3f}", file=sys.stderr)
    else:
        print("[2/4] Skipping dynamic fetch (quality sufficient)", file=sys.stderr)
    
    # Handle no results
    if not neighbors:
        elapsed = time.time() - start_time
        print(f"\n[VERIFY] No results found ({elapsed:.1f}s total)", file=sys.stderr)
        
        result = {
            "claim": claim,
            "label": "inconclusive",
            "confidence": 0.0,
            "summary": "Tidak ditemukan bukti ilmiah yang relevan.",
            "evidence": [],
            "references": []
        }
        print("\n[JSON_OUTPUT]")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    
    # Step 3: LLM Verification (~3-5 detik)
    print("[3/4] Calling LLM for verification...", file=sys.stderr)
    t4 = time.time()
    llm_result = call_llm_verify(claim, neighbors)
    print(f"      LLM done ({time.time()-t4:.1f}s)", file=sys.stderr)
    
    # Step 4: Build response
    print("[4/4] Building response...", file=sys.stderr)
    
    # Prepare evidence list
    evidence = []
    references = []
    
    for i, nb in enumerate(neighbors[:6]):
        ev = {
            "safe_id": nb.get("safe_id", ""),
            "snippet": nb.get("text", "")[:300],
            "doi": nb.get("doi", ""),
            "relevance_score": nb.get("relevance_score", 0)
        }
        evidence.append(ev)
        
        if nb.get("doi"):
            references.append({
                "safe_id": nb.get("safe_id", ""),
                "doi": nb.get("doi"),
                "url": f"https://doi.org/{nb.get('doi')}"
            })
    
    # Final result
    result = {
        "claim": claim,
        "label": llm_result.get("label", "inconclusive").lower(),
        "confidence": float(llm_result.get("confidence", 0.0)),
        "summary": llm_result.get("summary", ""),
        "evidence": evidence,
        "references": references,
        "metadata": {
            "neighbors_count": len(neighbors),
            "quality_score": quality,
            "processing_time": time.time() - start_time
        }
    }
    
    elapsed = time.time() - start_time
    print(f"\n[VERIFY] Complete in {elapsed:.1f}s", file=sys.stderr)
    print(f"         Label: {result['label']}, Confidence: {result['confidence']:.2f}", file=sys.stderr)
    
    # Output JSON
    print("\n[JSON_OUTPUT]")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    
    return result

# ============================================
# CLI
# ============================================

def main():
    parser = argparse.ArgumentParser(description="Optimized Claim Verification")
    parser.add_argument("--claim", "-c", type=str, help="Claim to verify")
    parser.add_argument("--k", type=int, default=10, help="Number of neighbors")
    parser.add_argument("--no-fetch", action="store_true", help="Disable dynamic fetch")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    
    args = parser.parse_args()
    
    claim = args.claim
    if not claim:
        print("Masukkan klaim: ", file=sys.stderr)
        claim = input("> ").strip()
    
    if not claim:
        print("Error: Klaim tidak boleh kosong", file=sys.stderr)
        sys.exit(1)
    
    try:
        result = verify_claim_optimized(
            claim=claim,
            k=args.k,
            enable_dynamic_fetch=not args.no_fetch,
            debug=args.debug
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()