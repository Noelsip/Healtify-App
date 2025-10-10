from pathlib import Path
from typing import List, Callable, Dict, Any, Optional
from tqdm import tqdm
from dotenv import load_dotenv
from google import genai
import  time
import os
import json
import re

# konfigurasi
BASE = Path(__file__).parents[1]
PROCESSED_DIR = BASE / 'data' / 'processed'
CHUNKS_DIR = BASE / "data" / "chunks"
CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(dotenv_path=BASE / ".env")
_api_key = os.getenv("GEMINI_API_KEY")

if _api_key:
    client = genai.Client(api_key=_api_key)
else:
    raise ValueError(
        "Tidak menemukan GEMINI_API_KEY atau GOOGLE_API_KEY. "
        "Set environment variable atau konfigurasi Vertex/ADC."
    )

# membaca dokumen proses
def list_processed_documents() -> List[Path]:
    return sorted([p for p in PROCESSED_DIR.glob("*.json")])

def load_processed_doc(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

# membuat nama file aman dari karakter
def _sanitize_filename(name: str, max_len: int = 200) -> str:
    if not name:
        return "doc"
    
    s = str(name)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^A-Za-z0-9._\-]", "_", s)
    if len(s) > max_len:
        s = s[:max_len]
    return s


# teks aggregator chunking
def get_text_for_chunking(doc: Dict[str, Any]) -> str:
    parts = []

    # judul(jika ada)
    if doc.get("title"):
        parts.append(doc.get("title"))

    # abstrak (jika ada)
    if doc.get("abstract"):
        parts.append(doc.get("abstract"))

    # teks field panjang(jika)
    if doc.get("text"):
        parts.append(doc.get("text"))

    # gabungan semua nilai string dari doc
    if not parts:
        for v in doc.values():
            if isinstance(v, str) and len(v) > 10:
                parts.append(v)
    return "\n\n".join(parts).strip()

# spliter berdasarkan kata
def split_by_words(text: str, words_per_chunk: int = 300, overlap_words: int = 30) -> List[str]:

    if not text:
        return []
    
    # tokenisasi
    tokens = text.split()
    if len(tokens) <= words_per_chunk:
        return [" ".join(tokens)]
    
    chunks = []
    
    i = 0
    step = words_per_chunk - overlap_words
    if step <= 0:
        step = words_per_chunk
    
    while i < len(tokens):
        chunk_tokens = tokens[i : i + words_per_chunk]
        chunks.append(" ".join(chunk_tokens))
        i += step
    return chunks

def embed_texts_gemini(
    texts: List[str],
    model: str = "gemini-embedding-001",
    batch_size: int = 32,
    output_dimensionality: Optional[int] = None,
    max_retries: int = 3,
    backoff_seconds: float = 1.0) -> List[List[float]]:
    # validasi
    if not texts:
        return []

    if batch_size < 1:
        batch_size = 1

    embeddings: List[List[float]] = []

    # proses teks per-batch agar req tidak terlalu besar
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]

        # rate limits
        for attempt in range(max_retries):
            try:
                kwargs = {"model": model, "contents": batch}
                if output_dimensionality is not None:
                    kwargs["output_dimensionality"] = int(output_dimensionality)

                response = client.models.embed_content(**kwargs)

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

                # normalisasi tiap embedding menjadi list of float
                for emb in emb_list:
                    # Handle berbagai format embedding
                    if hasattr(emb, 'values'):
                        # Format objek dengan atribut values
                        embedding_values = list(emb.values)
                    elif isinstance(emb, dict) and 'values' in emb:
                        # Format dictionary dengan key 'values'
                        embedding_values = list(emb['values'])
                    elif isinstance(emb, tuple) and len(emb) == 2 and emb[0] == 'values':
                        # Format tuple ('values', [embedding_list])
                        embedding_values = list(emb[1])
                    elif isinstance(emb, list):
                        # Sudah berupa list
                        embedding_values = list(emb)
                    else:
                        # Fallback - coba konversi langsung
                        embedding_values = list(emb)
                    
                    embeddings.append(embedding_values)

                break

            except Exception as e:
                is_last = (attempt == max_retries - 1)
                print(f"[gemini-embed] batch {i}-{i+len(batch)-1}, attempt {attempt+1} failed: {e}")

                if is_last:
                    raise
                else:
                    time.sleep(backoff_seconds * (2 ** attempt))

    # memastikan jumlah embed dan input sama
    if len(embeddings) != len(texts):
        raise RuntimeError(f"Jumlah Embedding mismatch: got {len(embeddings)} embeddings for {len(texts)} inputs")
    
    return embeddings


# membuat chunk, embed dan menyimpannya
def process_and_embed_all(
    embed_fn: Callable[[List[str]], List[List[float]]],
    words_per_chunk: int = 300,
    overlap_words: int = 30,
    save_jsonl: bool = True,
    batch_size: int = 32
):
    processed_files = list_processed_documents()
    print(f"Menemukan {len(processed_files)} dokumen processed di {PROCESSED_DIR}")

    for p in tqdm(processed_files, desc="Docs"):
        doc = load_processed_doc(p)
        doc_id = doc.get("id") or p.stem
        full_text = get_text_for_chunking(doc)
        chunks = split_by_words(full_text, words_per_chunk=words_per_chunk, overlap_words=overlap_words)

        if not chunks:
            print(f"[skip] dokumen {doc_id} kosong -> lewati")
            continue

        # batched embedding supaya tidak diminta 1/1
        embedings_all: List[List[float]] = []

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            emb_batch = embed_fn(batch)

            if not isinstance(emb_batch, list) or len(emb_batch) != len(batch):
                raise ValueError ("embed_fn harus mengembalikan List[List[float]] sesuai input barch size")
            embedings_all.extend(emb_batch)

        # menyimpan hasil ke JSONL
        safe_id = _sanitize_filename(doc_id)
        out_path = CHUNKS_DIR / f"{safe_id}.jsonl"
        if save_jsonl:
            with out_path.open("w", encoding="utf-8") as fo:
                for idx, (txt, emb) in enumerate(zip(chunks, embedings_all)):
                    record = {
                        "doc_id": doc_id,
                        "safe_id": safe_id,
                        "source_file": p.name,
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