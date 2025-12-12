import os
import json
import re
import time
from pathlib import Path
from typing import List, Callable, Dict, Any, Optional

from dotenv import load_dotenv
from google import genai
from tqdm import tqdm

# Configuration
BASE = Path(__file__).parents[1]
PROCESSED_DIR = BASE / 'data' / 'processed'
CHUNKS_DIR = BASE / "data" / "chunks"
CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

# Load environment variables
load_dotenv(dotenv_path=BASE / ".env")
_api_key = os.getenv("GEMINI_API_KEY")

# Initialize Gemini client (optional for embeddings)
client = None
if _api_key:
    try:
        client = genai.Client(api_key=_api_key)
        print("[INIT] Gemini client initialized for embeddings")
    except Exception as e:
        print(f"[WARNING] Failed to initialize Gemini client: {e}")
        print("[INFO] Will use fallback embeddings if needed")
else:
    print("[WARNING] GEMINI_API_KEY not found - Gemini embeddings unavailable")
    print("[INFO] Using alternative embedding methods")


def list_processed_documents() -> List[Path]:
    """Dapatkan daftar dokumen yang sudah diproses dari direktori processed."""
    return sorted([p for p in PROCESSED_DIR.glob("*.json")])


def load_processed_doc(path: Path) -> Dict[str, Any]:
    """Load dokumen yang sudah diproses dari file JSON."""
    return json.loads(path.read_text(encoding="utf-8"))


def sanitize_filename(name: str, max_len: int = 200) -> str:
    """Buat nama file aman dari karakter tidak valid."""
    if not name:
        return "doc"
    
    s = str(name)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^A-Za-z0-9._\-]", "_", s)
    if len(s) > max_len:
        s = s[:max_len]
    return s


def get_text_for_chunking(doc: Dict[str, Any]) -> str:
    """Ekstrak dan gabungkan teks dari berbagai field dokumen untuk chunking."""
    parts = []

    # Menambahkan judul
    if doc.get("title"):
        parts.append(doc.get("title"))

    # Menambahkan abstrak 
    if doc.get("abstract"):
        parts.append(doc.get("abstract"))

    # Menambahkan field teks panjang
    if doc.get("text"):
        parts.append(doc.get("text"))

    # Fallback: Menggabungkan semua nilai string dari dokumen
    if not parts:
        for v in doc.values():
            if isinstance(v, str) and len(v) > 10:
                parts.append(v)
    
    return "\n\n".join(parts).strip()


def split_by_words(text: str, words_per_chunk: int = 300, overlap_words: int = 30) -> List[str]:
    """Split teks menjadi chunks berdasarkan jumlah kata dengan overlap."""
    if not text:
        return []
    
    tokens = text.split()
    if len(tokens) <= words_per_chunk:
        return [" ".join(tokens)]
    
    chunks = []
    step = words_per_chunk - overlap_words
    if step <= 0:
        step = words_per_chunk
    
    i = 0
    while i < len(tokens):
        chunk_tokens = tokens[i : i + words_per_chunk]
        chunks.append(" ".join(chunk_tokens))
        i += step
    
    return chunks


def _embed_with_sentence_transformers(texts: List[str]) -> List[List[float]]:
    """Fallback embedding menggunakan sentence-transformers.
    Uses 768-dimensional model to match Gemini embeddings in database."""
    try:
        from sentence_transformers import SentenceTransformer
        
        # Use global cache to avoid reloading model every time
        global _st_model_cache
        if '_st_model_cache' not in globals() or _st_model_cache is None:
            print("[EMBED] Loading sentence-transformers model (768-dim)...")
            # Use 768-dimensional model to match Gemini
            _st_model_cache = SentenceTransformer('sentence-transformers/all-mpnet-base-v2')
            print("[EMBED] Model loaded and cached")
        else:
            print("[EMBED] Using cached model")
        
        print(f"[EMBED] Generating embeddings for {len(texts)} texts...")
        embeddings = _st_model_cache.encode(texts, show_progress_bar=True, convert_to_numpy=True)
        return [emb.tolist() for emb in embeddings]
    except ImportError:
        print("[ERROR] sentence-transformers not installed!")
        print("[INFO] Returning zero vectors as last resort")
        
        # Return zero vectors (768 dimensions to match Gemini)
        return [[0.0] * 768 for _ in texts]
    except Exception as e:
        print(f"[ERROR] Sentence-transformers embedding failed: {e}")
        return [[0.0] * 768 for _ in texts]

# Global model cache
_st_model_cache = None


def embed_texts_gemini(
    texts: List[str],
    model: str = "gemini-embedding-001",
    batch_size: int = 32,
    max_retries: int = 3,
    backoff_seconds: float = 1.0,
) -> List[List[float]]:
    """
    Embed teks menggunakan Gemini Embedding API dengan batching dan retry logic.
    Falls back to sentence-transformers jika Gemini tidak tersedia.
    """
    if not texts:
        return []
    
    # Check if Gemini client is available
    if client is None:
        print("[WARNING] Gemini client not available, using sentence-transformers fallback")
        return _embed_with_sentence_transformers(texts)

    embeddings = []
    try:
        for i in tqdm(range(0, len(texts), batch_size), desc="Embedding batches"):
            batch = texts[i : i + batch_size]
            
            batch_embeddings = _process_embedding_batch(
                batch, model, None, max_retries, backoff_seconds
            )
            
            embeddings.extend(batch_embeddings)
        
        return embeddings
    except Exception as e:
        print(f"[ERROR] Gemini embedding failed: {e}")
        print("[INFO] Falling back to sentence-transformers")
        return _embed_with_sentence_transformers(texts)


def _process_embedding_batch(
    batch: List[str], 
    model: str, 
    output_dimensionality: Optional[int],
    max_retries: int, 
    backoff_seconds: float
) -> List[List[float]]:
    """Proses satu batch embedding dengan retry mechanism."""
    for attempt in range(max_retries):
        try:
            kwargs = {"model": model, "contents": batch}
            if output_dimensionality is not None:
                kwargs["output_dimensionality"] = int(output_dimensionality)

            response = client.models.embed_content(**kwargs)
            return _extract_embeddings_from_response(response)

        except Exception as e:
            is_last_attempt = (attempt == max_retries - 1)
            print(f"[gemini-embed] batch failed, attempt {attempt+1}: {e}")

            if is_last_attempt:
                raise
            else:
                time.sleep(backoff_seconds * (2 ** attempt))


def _extract_embeddings_from_response(response) -> List[List[float]]:
    """Ekstrak embeddings dari berbagai format response Gemini API."""
    if hasattr(response, "embeddings"):
        emb_list = response.embeddings
    elif isinstance(response, dict) and "embeddings" in response:
        emb_list = response["embeddings"]
    elif hasattr(response, "data"):
        emb_list = []
        for item in response.data:
            if hasattr(item, "embedding"):
                emb_list.append(item.embedding)
            elif isinstance(item, dict) and "embedding" in item:
                emb_list.append(item["embedding"])
            else:
                raise RuntimeError("Tidak menemukan embedding pada response.data item")
    else:
        raise RuntimeError("Bentuk response embeddings tidak dikenal: " + str(type(response)))

    # Normalisasi setiap embedding menjadi list of float
    normalized_embeddings = []
    for emb in emb_list:
        embedding_values = _normalize_embedding_format(emb)
        normalized_embeddings.append(embedding_values)
    
    return normalized_embeddings


def _normalize_embedding_format(emb) -> List[float]:
    """Normalisasi berbagai format embedding menjadi list of float."""
    if hasattr(emb, 'values'):
        return list(emb.values)
    elif isinstance(emb, dict) and 'values' in emb:
        return list(emb['values'])
    elif isinstance(emb, tuple) and len(emb) == 2 and emb[0] == 'values':
        return list(emb[1])
    elif isinstance(emb, list):
        return list(emb)
    else:
        return list(emb)


def process_and_embed_all(
    embed_fn: Callable[[List[str]], List[List[float]]],
    words_per_chunk: int = 300,
    overlap_words: int = 30,
    save_jsonl: bool = True,
    batch_size: int = 32
):
    """Proses semua dokumen: chunking, embedding, dan simpan ke JSONL files."""
    processed_files = list_processed_documents()
    print(f"Menemukan {len(processed_files)} dokumen processed di {PROCESSED_DIR}")

    for file_path in tqdm(processed_files, desc="Processing docs"):
        _process_single_document(
            file_path, embed_fn, words_per_chunk, 
            overlap_words, save_jsonl, batch_size
        )

def _process_single_document(
    file_path: Path,
    embed_fn: Callable[[List[str]], List[List[float]]],
    words_per_chunk: int,
    overlap_words: int,
    save_jsonl: bool,
    batch_size: int
):
    """Proses satu dokumen: load, chunk, embed, dan save."""
    doc = load_processed_doc(file_path)
    doc_id = doc.get("id") or file_path.stem
    full_text = get_text_for_chunking(doc)
    chunks = split_by_words(full_text, words_per_chunk=words_per_chunk, overlap_words=overlap_words)

    if not chunks:
        print(f"[SKIP] dokumen {doc_id} kosong -> lewati")
        return

    # Generate embeddings dalam batch
    embeddings_all: List[List[float]] = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        emb_batch = embed_fn(batch)

        if not isinstance(emb_batch, list) or len(emb_batch) != len(batch):
            raise ValueError("embed_fn harus mengembalikan List[List[float]] sesuai input batch size")
        embeddings_all.extend(emb_batch)

    # Simpan hasil ke JSONL
    if save_jsonl:
        _save_chunks_to_jsonl(doc, doc_id, file_path, chunks, embeddings_all)


def _save_chunks_to_jsonl(
    doc: Dict[str, Any], 
    doc_id: str, 
    file_path: Path, 
    chunks: List[str], 
    embeddings: List[List[float]]
):
    """Simpan chunks dan embeddings ke file JSONL."""
    safe_id = sanitize_filename(doc_id)
    out_path = CHUNKS_DIR / f"{safe_id}.jsonl"
    
    with out_path.open("w", encoding="utf-8") as fo:
        for idx, (txt, emb) in enumerate(zip(chunks, embeddings)):
            record = {
                "doc_id": doc_id,
                "safe_id": safe_id,
                "source_file": file_path.name,
                "chunk_index": idx,
                "text": txt,
                "n_words": len(txt.split()),
                "doi": doc.get("doi") or doc.get("metadata", {}).get("doi") or None,
                "embedding": emb
            }
            fo.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    print(f"SAVED: {out_path} ({len(chunks)} chunks)")


if __name__ == "__main__":
    process_and_embed_all(
        embed_fn=embed_texts_gemini,
        words_per_chunk=300,
        overlap_words=30,
        save_jsonl=True,
        batch_size=32
    )