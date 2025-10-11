import os
import json
import logging
import sys
from pathlib import Path
from typing import Iterable, Tuple, Optional

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values
from pgvector.psycopg2 import register_vector
from tqdm import tqdm

# Configuration
BASE = Path(__file__).parents[1]
DOTENV_PATH = BASE / ".env"

# Load environment variables
load_ok = load_dotenv(dotenv_path=DOTENV_PATH)
if load_ok:
    print(f"Loaded environment variables from {DOTENV_PATH}")
else:
    print(f"No .env file found at {DOTENV_PATH} — using OS environment variables")

# Database configuration
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_TABLE = "embeddings"

# Chunks directory
CHUNKS_DIR = Path(os.getenv("CHUNKS_DIR", BASE / "data" / "chunks"))
if not CHUNKS_DIR.exists():
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

print(f"Using chunks directory: {CHUNKS_DIR}")

# Configuration constants
VECTOR_DIM_ENV = os.getenv("VECTOR_DIM")
VECTOR_DIM = int(VECTOR_DIM_ENV) if VECTOR_DIM_ENV else None
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 500))

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def connect_db():
    """Buat koneksi ke database PostgreSQL dengan pgvector support."""
    connection = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )
    register_vector(connection)
    return connection


def ensure_table(connection, vector_dim: int):
    """Buat tabel embeddings jika belum ada."""
    with connection.cursor() as cursor:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {DB_TABLE} (
                id bigserial PRIMARY KEY,
                doc_id text,
                safe_id text,
                source_file text,
                chunk_index integer,
                n_words integer,
                text text,
                doi text,
                embedding vector({vector_dim}),
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        connection.commit()


def iter_jsonl_records(file_path: Path) -> Iterable[dict]:
    """Generator untuk membaca file JSONL baris per baris."""
    with file_path.open("r", encoding="utf-8") as fh:
        for line_num, raw_line in enumerate(fh, 1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            
            try:
                yield json.loads(raw_line)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to decode JSON at {file_path.name}:{line_num}: {e}")


def detect_vector_dimension(files: Iterable[Path]) -> Optional[int]:
    """Deteksi dimensi vektor dari embedding pertama yang valid."""
    for file_path in files:
        for record in iter_jsonl_records(file_path):
            embedding = record.get("embedding")
            if embedding and isinstance(embedding, list):
                return len(embedding)
    return None


def prepare_record_tuple(record: dict) -> Tuple:
    """Konversi record menjadi tuple untuk database insert."""
    embedding = record.get("embedding")
    embedding_str = _convert_embedding_to_string(embedding)
    
    return (
        record.get("doc_id"),
        record.get("safe_id"),
        record.get("source_file"),
        record.get("chunk_index"),
        record.get("n_words"),
        record.get("text"),
        record.get("doi"),
        embedding_str,
    )


def _convert_embedding_to_string(embedding) -> Optional[str]:
    """Konversi embedding menjadi string format PostgreSQL vector."""
    if embedding is None:
        return None
    
    if not isinstance(embedding, list):
        logger.warning("Embedding bukan list: %r", embedding)
        return None
    
    try:
        return "[" + ",".join(str(float(x)) for x in embedding) + "]"
    except Exception as e:
        logger.warning("Gagal konversi embedding ke float list: %s", e)
        return None


def validate_record(record: dict, expected_vector_dim: int, file_name: str) -> bool:
    """Validasi record sebelum insert ke database."""
    embedding = record.get("embedding")
    
    if not embedding:
        logger.warning(f"Skip record tanpa embedding di {file_name}")
        return False
    
    if not isinstance(embedding, list):
        logger.warning(f"Embedding bukan list (file {file_name} chunk {record.get('chunk_index')})")
        return False
    
    if len(embedding) != expected_vector_dim:
        logger.warning(
            f"Skip chunk karena dimensi tidak cocok (file {file_name} chunk {record.get('chunk_index')} "
            f"len={len(embedding)}): expected {expected_vector_dim}"
        )
        return False
    
    return True


def insert_batch_to_db(cursor, batch_data: list) -> int:
    """Insert batch data ke database."""
    if not batch_data:
        return 0
    
    sql = f"INSERT INTO {DB_TABLE} (doc_id, safe_id, source_file, chunk_index, n_words, text, doi, embedding) VALUES %s"
    template = "(%s,%s,%s,%s,%s,%s,%s,%s::vector)"
    
    execute_values(cursor, sql, batch_data, template=template, page_size=100)
    return len(batch_data)


def process_file(file_path: Path, cursor, vector_dim: int) -> int:
    """Proses satu file JSONL dan insert ke database."""
    logger.info(f"Memproses file: {file_path.name}")
    
    batch_data = []
    total_inserted = 0
    
    for record in tqdm(iter_jsonl_records(file_path), desc=f"Processing {file_path.name}", unit="rec"):
        if not validate_record(record, vector_dim, file_path.name):
            continue
        
        batch_data.append(prepare_record_tuple(record))
        
        # Insert batch ketika mencapai BATCH_SIZE
        if len(batch_data) >= BATCH_SIZE:
            inserted_count = insert_batch_to_db(cursor, batch_data)
            total_inserted += inserted_count
            logger.info(f"Inserted batch of {inserted_count} records. Total: {total_inserted}")
            batch_data = []
    
    # Insert sisa data di akhir file
    if batch_data:
        inserted_count = insert_batch_to_db(cursor, batch_data)
        total_inserted += inserted_count
        logger.info(f"Inserted final batch of {inserted_count} records from {file_path.name}")
    
    return total_inserted


def ingest():
    """Fungsi utama untuk ingest chunks ke PostgreSQL database."""
    # Validasi direktori dan file
    if not CHUNKS_DIR.exists() or not CHUNKS_DIR.is_dir():
        logger.error(f"Direktori chunks tidak ditemukan: {CHUNKS_DIR}")
        sys.exit(1)

    jsonl_files = sorted(list(CHUNKS_DIR.glob("*.jsonl")))
    if not jsonl_files:
        logger.error(f"Tidak ada file .jsonl ditemukan di {CHUNKS_DIR}")
        sys.exit(1)

    logger.info(f"Ditemukan {len(jsonl_files)} file .jsonl di {CHUNKS_DIR}")

    # Tentukan dimensi vektor
    vector_dim = _determine_vector_dimension(jsonl_files)
    
    # Setup database
    try:
        connection = connect_db()
        ensure_table(connection, vector_dim)
    except Exception as e:
        logger.error(f"Gagal setup database: {e}")
        sys.exit(1)

    # Proses files dan insert data
    total_inserted = 0
    try:
        with connection.cursor() as cursor:
            for file_path in jsonl_files:
                inserted_count = process_file(file_path, cursor, vector_dim)
                connection.commit()
                total_inserted += inserted_count

    except KeyboardInterrupt:
        logger.warning("Proses dihentikan oleh user. Data yang sudah diproses tetap tersimpan.")
    except Exception as e:
        logger.error(f"Error during processing: {e}")
    finally:
        connection.close()

    logger.info(f"Proses selesai. Total records inserted: {total_inserted}")


def _determine_vector_dimension(files: list) -> int:
    """Tentukan dimensi vektor dari environment variable atau deteksi otomatis."""
    vector_dim = VECTOR_DIM
    
    if vector_dim is None:
        logger.info("Mendeteksi dimensi vektor dari file...")
        vector_dim = detect_vector_dimension(files)
        
        if vector_dim is None:
            logger.error("Gagal mendeteksi dimensi vektor. Pastikan ada embedding valid.")
            sys.exit(1)
        
        logger.info(f"Terdeteksi dimensi vektor: {vector_dim}")
    else:
        logger.info(f"Menggunakan dimensi vektor dari env: {vector_dim}")
    
    return vector_dim


if __name__ == "__main__":
    ingest()