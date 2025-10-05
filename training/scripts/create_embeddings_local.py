import argparse
import pathlib
import json
import csv
from datetime import datetime, timezone
from typing import List

from sentence_transformers import SentenceTransformer
from tqdm import tqdm


# utility untuk memastikan folder ada
def ensure_folder_exists(folder_path: pathlib.Path) -> None:
    folder_path.mkdir(parents=True, exist_ok=True)


# fungsi untuk membuat embedding
def create_embeddings_for_processed_doc(
        processed_folder: pathlib.Path,
        embeddings_folder: pathlib.Path,
        embeddings_index_csv: pathlib.Path,
        model_name: str,
        batch_size: int,
        overwrite_existing: bool
) -> None:
    
    # memastikan folder output ada
    ensure_folder_exists(embeddings_folder)
    ensure_folder_exists(embeddings_index_csv.parent)

    # inisialisasi model berdasarkan name model
    model = SentenceTransformer(model_name)

    list_of_processed_files = sorted([p for p in processed_folder.glob("*.json") if p.is_file()])

    if len(list_of_processed_files) == 0:
        print(f"Tidak ada file yang ditemukan di {processed_folder}. Pastikan folder sudah benar.")
        return
    
    embeddings_index_rows = []

    # memastikan membaca isi file agar tidak menimpa
    existing_index = {}
    if embeddings_index_csv.exists():
        try:
            with embeddings_index_csv.open("r", encoding="utf-8") as index_file:
                reader = csv.DictReader(index_file)
                for row in reader:
                    existing_index[row["source_file"]] = row
        except Exception as e:
            print(f"Gagal membaca file index yang ada: {e}")
            existing_index = {}

    # mengumpulkan file batch untuk efisiensi
    text_to_encode : List[str] = []
    corresponding_document_ids: List[str] = []
    corresponding_processed_file_names: List[str] = []
    corresponding_titles: List[str] = []

    # fungsi membantu untuk flush batch dan menyimpan hasil
    def flush_batch_and_save():
        if len(text_to_encode) == 0:
            return
        
        # encode batch vector ke list
        try:
            encoded_batch = model.encode(text_to_encode, show_progress_bar=False)
        except Exception as e:
            print(f"Gagal melakukan encoding batch: {e}")
            text_to_encode.clear()
            corresponding_document_ids.clear()
            corresponding_processed_file_names.clear()
            corresponding_titles.clear()
            return
        
        # memastikan panjang list = jumalh input
        if len(encoded_batch) != len(text_to_encode):
            print("Peringatan: jumlah hasil encoding tidak sesuai dengan jumlah input.")
            text_to_encode.clear()
            corresponding_document_ids.clear()
            corresponding_processed_file_names.clear()
            corresponding_titles.clear()
            return
        
        # menyimpan setiap hasil embedding ke json terpisah
        for index_in_batch, vector in enumerate(encoded_batch):
            document_id = corresponding_document_ids[index_in_batch]
            processed_file_name = corresponding_processed_file_names[index_in_batch]
            document_title = corresponding_titles[index_in_batch]
            embedding_vector = vector.tolist() if hasattr(vector, 'tolist') else list(vector)

            # menentukan nama file output
            safe_document_id = str(document_id).replace("/", "_")
            embedding_file_path = embeddings_folder / f"{safe_document_id}.json"

            # jika file sudah ada dan tidak diizinkan overwrite, lewati
            if embedding_file_path.exists() and not overwrite_existing:
                if document_id in existing_index:
                    embeddings_index_rows.append(existing_index[document_id])
                
                else:
                    embeddings_index_rows.append({
                        "id": document_id,
                        "processed_file": processed_file_name,
                        "embedding_file": str(embedding_file_path.name),
                        "dimensionality": str(len(embedding_vector)),
                        "created_at": existing_index.get(document_id,{}).get("created_at", ""),
                    })
                continue
            
            # susunan objek json yang disimpan
            embedding_output_obj = {
                "id": document_id,
                "title": document_title,
                "embedding": embedding_vector,
            }

            # menulis json embedding 
            try:
                embedding_file_path.write_text(json.dumps(embedding_output_obj,ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                print(f"Gagal menulis file embedding {embedding_file_path}: {e}")
                continue

            # menyiapkan baris untuk index csv(row)
            embeddings_index_rows.append({
                "id": document_id,
                "processed_file": processed_file_name,
                "embedding_file": str(embedding_file_path.name),
                "dimensionality": str(len(embedding_vector)),
                "created_at": datetime.now(timezone.utc()).isoformat() + "Z",
            })

        # mengosongkan batch array agar bisa isi ulang
        text_to_encode.clear()
        corresponding_document_ids.clear()
        corresponding_processed_file_names.clear()
        corresponding_titles.clear()

    total_files = len(list_of_processed_files)
    progress_iterator = tqdm(list_of_processed_files, desc="Memproses file", unit="file")

    for processed_file_path in progress_iterator:
        try:
            processed_obj = json.loads(processed_file_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Gagal membaca atau mengurai {processed_file_path}: {e}")
            continue

        # mengambil id, title, dan menggabungkan title + abstract sebagai text
        document_identifier = processed_obj.get("id", None)
        document_title = processed_obj.get("title", "") or ""
        document_abstract = processed_obj.get("abstract", "") or ""
        processed_file_name = processed_file_path.name

        # jika tidak ada id, id fallback dibuat
        if not document_identifier:
            document_identifier = f"missing-id-{processed_file_name}"

        # memeriksa embedding yang sudah ada dan overwrite false
        embeddings_file_candidate = embeddings_folder / f"{str(document_identifier).replace('/', '_')}.json"
        if embeddings_file_candidate.exists() and not overwrite_existing:
            continue

        # menggabungkan title dan abstract
        document_text_for_embedding = (document_title + "\n\n" + document_abstract).strip()
        if document_text_for_embedding == "":
            document_text_for_embedding = processed_file_name

        # menambahkan ke batch
        text_to_encode.append(document_text_for_embedding)
        corresponding_document_ids.append(document_identifier)
        corresponding_processed_file_names.append(processed_file_name)
        corresponding_titles.append(document_title)

        # jika batch sudah mencapau batch_size
        if len(text_to_encode) >= batch_size:
            flush_batch_and_save()

    # flush sisa batch yang belum diproses
    flush_batch_and_save()

    for existing_id, existing_row in existing_index.items():
        if not any(row["id"] == existing_id for row in embeddings_index_rows):
            embeddings_index_rows.append(existing_row)
    
    # menulis index csv
    csv_header = ["id", "processed_file", "embedding_file", "dimensionality", "created_at"]
    try:
        with open(embeddings_index_csv, "w", encoding="utf-8", newline='') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=csv_header)
            writer.writeheader()
            for row in embeddings_index_rows:
                normalized_row = {
                    "id": row.get("id", ""),
                    "processed_file": row.get("processed_file", ""),
                    "embedding_file": row.get("embedding_file", ""),
                    "dimensionality": row.get("dimensionality", ""),
                    "created_at": row.get("created_at", ""),
                }
                writer.writerow(normalized_row)
    except Exception as e:
        print(f"Gagal menulis file index CSV: {e}")
        
    # menampilkan ringkasan 
    print("selesai membuat embedding.")
    print(f"Total file yang diproses: {total_files}")
    print(f"Total embedding yang dibuat/diupdate: {len(list(embeddings_folder.glob('*.json')))}")
    if len(list(embeddings_folder.glob('*.json'))) > 0:
        example_embedding_file = next(embeddings_folder.glob('*.json'))
        try:
            example_obj = json.loads(example_embedding_file.read_text(encoding="utf-8"))
            example_vector = example_obj.get("embedding", [])
            print(f"Contoh file embedding: {example_embedding_file.name}")
            print(f"Dimensi embedding: {len(example_vector)}")
        except Exception as e:
            print(f"Gagal membaca contoh file embedding: {e}")
    
# entry point utama
def parse_cli_arguments():
    parser = argparse.ArgumentParser(description="Membuat embedding dari dokumen yang sudah diproses secara lokal.")
    parser.add_argument("--processed-folder", type=str, default="data/processed", help="Folder untuk file processed JSON.")
    parser.add_argument("--embeddings-folder", type=str, default="data/processed/embeddings", help="Folder output untuk embeddings JSON.")
    parser.add_argument("--embeddings-index", type=str, default="data/metadata/embeddings_index.csv", help="File CSV index untuk embeddings.")
    parser.add_argument("--model-name", type=str, default="all-MiniLM-L6-v2", help="Nama model sentence-transformers.")
    parser.add_argument("--batch-size", type=int, default=16, help="Batch size untuk encoding.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing embedding files jika diset.")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_cli_arguments()

    # Konversi path relatif ke pathlib.Path yang absolut relatif ke script
    base_script_folder = pathlib.Path(__file__).parents[1]
    processed_folder_path = (base_script_folder / args.processed_folder).resolve()
    embeddings_folder_path = (base_script_folder / args.embeddings_folder).resolve()
    embeddings_index_csv_path = (base_script_folder / args.embeddings_index).resolve()

    # Panggil fungsi utama
    create_embeddings_for_processed_doc(
        processed_folder=processed_folder_path,
        embeddings_folder=embeddings_folder_path,
        embeddings_index_csv=embeddings_index_csv_path,
        model_name=args.model_name,
        batch_size=args.batch_size,
        overwrite_existing=args.overwrite
    )