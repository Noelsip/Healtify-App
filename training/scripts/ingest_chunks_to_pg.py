import os
import json
import psycopg2
import sys
import logging
from typing import Iterable, Tuple, Optional
from pathlib import Path
from dotenv import load_dotenv
from psycopg2.extras import execute_values
from pgvector.psycopg2 import register_vector
from tqdm import tqdm

BASE = Path(__file__).parents[1]
DOTENV_PATH = BASE / ".env"

load_ok = load_dotenv(dotenv_path=DOTENV_PATH)
if load_ok:
    print(f"Loaded environment variables from {DOTENV_PATH}")
else:
    print(f"No .env file found at {DOTENV_PATH} — relying on OS environment variables (if any)")

# konfigurasi koneksi database
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_TABLE = "embeddings"

CHUNKS_DIR = Path(os.getenv("CHUNKS_DIR",Path(__file__).parents[1] / "data" / "chunks"))

if not os.path.exists(CHUNKS_DIR):
    os.makedirs(CHUNKS_DIR)
print(f"Using chunks directory: {CHUNKS_DIR}")

# mendeteksi vector dim dari embedding pada file pertama
VECTOR_DIM_ENV = os.getenv("VECTOR_DIM")
VECTOR_DIM = int(VECTOR_DIM_ENV) if VECTOR_DIM_ENV else None
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 500))

# logging setup untuk progess, warning, error
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# membuat koneksi ke database PostgreSQL
def connect_db():
    connect = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

    register_vector(connect)
    return connect

# membuat tabel jika belum ada
def ensure_table(connect, vector_dim):
    with connect.cursor() as cursor:
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
        connect.commit()

# generator untuk membaca file JSONL per baris
def iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()

            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError as e:
                logger.warning(f"Gagal decode JSON di {path.name}: {e}, raw: {raw[:200]}...")


# mendeteksi vector dim via env dari embedding pertama valid
def detect_vector_dim_from_files(files: Iterable[Path]) -> Optional[int]:
    for file in files:
        for record in iter_jsonl(file):
            embedding = record.get("embedding")
            if embedding and isinstance(embedding, list):
                return len(embedding)
    return None

# standarisasi tuple data untuk insert
def prepare_tuple_from_record(rec: dict) -> Tuple:
    emb = rec.get("embedding")
    emb_str = None
    if emb is not None:
        if not isinstance(emb, list):
            # jika bukan list, log dan skip nanti
            logger.warning("Embedding bukan list: %r", emb)
        else:
            # pastikan semua elemen numeric (float/int)
            try:
                emb_str = "[" + ",".join(str(float(x)) for x in emb) + "]"
            except Exception as e:
                logger.warning("Gagal konversi embedding ke float list: %s ; emb=%r", e, emb)
                emb_str = None

    return (
        rec.get("doc_id"),
        rec.get("safe_id"),
        rec.get("source_file"),
        rec.get("chunk_index"),
        rec.get("n_words"),
        rec.get("text"),
        rec.get("doi"),
        emb_str,
    )


# fungsi utama untuk membaca file dan memasukkan data ke database
def ingest():
    # menemukan file .jsonl
    if not CHUNKS_DIR.exists() or not CHUNKS_DIR.is_dir():
        logger.error(f"Direktori chunks tidak ditemukan: {CHUNKS_DIR}")
        sys.exit(1)

    files = sorted(list(CHUNKS_DIR.glob("*.jsonl")))
    if not files:
        logger.error(f"Tidak ada file .jsonl ditemukan di {CHUNKS_DIR}")
        sys.exit(1)

    logger.info(f"Ditemukan {len(files)} file .jsonl di {len(files)} {CHUNKS_DIR}")

    # menentukan dimensi vektor
    vector_dim = VECTOR_DIM
    if vector_dim is None:
        logger.info("Mendeteksi dimensi vektor dari file...")
        vector_dim = detect_vector_dim_from_files(files)
        if vector_dim is None:
            logger.error("Gagal mendeteksi dimensi vektor dari file. Pastikan ada embedding valid.")
            sys.exit(1)
        logger.info(f"Terdeteksi dimensi vektor: {vector_dim}")
    else:
        logger.info(f"Menggunakan dimensi vektor dari env: {vector_dim}")

    # mengoneksikan db dan buat table jika perlu
    try:
        connect = connect_db()
    except Exception as e:
        logger.error(f"Gagal koneksi ke database: {e}")
        sys.exit(1)

    try:
        ensure_table(connect, vector_dim)
    except Exception as e:
        logger.error(f"Gagal memastikan tabel di database: {e}")
        connect.close()
        sys.exit(1)

    # melakukan iterasi file dan insert data
    total_inserted = 0
    try:
        with connect.cursor() as cursor:
            for file in files:
                logger.info(f"Memproses file: {file.name}")
                to_insert = []

                for record in tqdm(iter_jsonl(file), desc=f"Memproses {file.name}", unit="rec"):
                    emb = record.get("embedding")

                    if not emb:
                        logger.warning(f"skip record tanpa embedding di {file.name}: {record}")
                        continue
                    if not isinstance(emb, list) :
                        logger.warning("Embedding bukan list (file %s chunk %s). Skip.", file.name, record.get("chunk_index"))
                        continue
                    if len(emb) != vector_dim:
                        logger.warning(
                            "Skip chunk karena dimensi tidak cocok (file %s chunk %s len=%d): expected %d",
                            file.name,
                            record.get("chunk_index"),
                            len(emb),
                            vector_dim
                        )
                        continue
                    
                    to_insert.append(prepare_tuple_from_record(record))

                    if len(to_insert) >= BATCH_SIZE:
                        sql = f"INSERT INTO {DB_TABLE} (doc_id, safe_id, source_file, chunk_index, n_words, text, doi, embedding) VALUES %s"
                        template = "(%s,%s,%s,%s,%s,%s,%s,%s::vector)"

                        logger.debug("Contoh tuple sebelum insert: %r", to_insert[0] if to_insert else None)
                        execute_values(cursor, sql, to_insert, template=template, page_size=100)
                        connect.commit()
                        total_inserted += len(to_insert)
                        logger.info(f"Inserted batch of {len(to_insert)} records. Total inserted: {total_inserted}")
                        to_insert = []

                
                # insert sisa data di akhir file
                if to_insert:
                    sql = f"INSERT INTO {DB_TABLE} (doc_id, safe_id, source_file, chunk_index, n_words, text, doi, embedding) VALUES %s"
                    template = "(%s,%s,%s,%s,%s,%s,%s,%s::vector)"

                    logger.debug("Contoh tuple final sebelum insert: %r", to_insert[0])
                    execute_values(cursor, sql, to_insert, template=template, page_size=100)
                    connect.commit()
                    total_inserted += len(to_insert)
                    logger.info(f"Inserted final batch of {len(to_insert)} records from {file.name}. Total inserted: {total_inserted}")


                logger.info(f"Selesai. Total records inserted: {total_inserted}")

    except KeyboardInterrupt:
        logger.warning("Proses dihentikan oleh user. data tetap tersimpan.")
    except Exception as e:
        logger.error(f"Error selama proses insert: {e}")
    finally:
        connect.close()

    logger.info(f"Proses selesai. Total records inserted: {total_inserted}")


if __name__ == "__main__":
    ingest()
