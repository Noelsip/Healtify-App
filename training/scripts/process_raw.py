import pathlib
import json
import xml.etree.ElementTree as xml_parser
import csv
from tqdm import tqdm

BASE_DIR = pathlib.Path(__file__).parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
RAW_DIR.mkdir(parents=True, exist_ok=True)
METADATA_CSV_PATH = BASE_DIR / "data" / "metadata" / "processed_metadata.csv"
METADATA_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

# Parsing file CrossRef json
def parse_crossref_file (file_path: pathlib.Path):
    # membaca file json CrossRef
    file_content = file_path.read_text(encoding="utf-8")
    json_object = json.loads(file_content)

    # mengambol daftar item
    items_list = json_object.get("message", {}).get("items", [])
    parsed_documents = []

    for item in items_list:
        document_identifier = item.get("DOI") or item.get("URL") or str(hash(json.dumps(item)))

        # mengambil judul
        title_value = None
        if item.get("title"):
            title_value = " ".join(item.get("title")) #menggabungkan judul jika ada

        abstract_value = item.get("abstract") or ""

        # mengambil penulis
        authors_list = []
        if item.get("author"):
            for author_entry in item.get("author", []):
                given_name = author_entry.get("given", "").strip()
                family_name = author_entry.get("family", "").strip()
                combined_name = f"{given_name} {family_name}".strip()
                if combined_name:
                    authors_list.append(combined_name)
        
        # mengambil tahun publikasi
        year_value = None
        issued_object = item.get("issued", {})
        date_parts = issued_object.get("date-parts", [])
        if date_parts and isinstance(date_parts, list) and len(date_parts) > 0:
            year_value = date_parts[0][0] if len(date_parts[0]) > 0 else None

        # susunan dokumen terstruktur
        parsed_document = {
            "id": document_identifier,
            "title": title_value,
            "abstract": abstract_value,
            "authors": authors_list,
            "year": year_value,
            "doi": item.get("DOI"),
            "source": "crossref",
            "raw_file": file_path.name
        }
        parsed_documents.append(parsed_document)
    return parsed_documents

# Parsing semantic scholar json endpoint /paper/search
def parse_sematic_scholar_file (file_path: pathlib.Path):
    # membaca file json Semantic Scholar
    file_content = file_path.read_text(encoding="utf-8")
    json_object = json.loads(file_content)

    parsed_documents = []

    for paper in json_object.get("data", []):
        document_identifier = paper.get("paperId") or paper.get("doi") or paper.get("url") or str(hash(json.dumps(paper)))

        # mengambil judul
        title_value = paper.get("title")

        abstract_value = paper.get("abstract") or ""

        # mengambil penulis
        authors_list = []
        for author_entry in paper.get("authors", []) or []:
            author_name = author_entry.get("name", "")
            if author_name:
                authors_list.append(author_name)
        
        # mengambil tahun publikasi
        year_value = paper.get("year")

        # susunan dokumen terstruktur
        parsed_document = {
            "id": document_identifier,
            "title": title_value,
            "abstract": abstract_value,
            "authors": authors_list,
            "year": year_value,
            "doi": paper.get("doi"),
            "source": "semantic_scholar",
            "raw_file": file_path.name
        }
        parsed_documents.append(parsed_document)
    return parsed_documents

# Parsing PubMed XML file
def parse_pubmed_xml_file(file_path: pathlib.Path):
    file_content = file_path.read_text(encoding="utf-8")
    xml_root = xml_parser.fromstring(file_content)

    parsed_documents = []  # list kosong untuk menampung semua artikel

    for article_element in xml_root.findall(".//PubmedArticle"):
        try:
            # Ambil title
            title_node = article_element.find(".//ArticleTitle")
            title_value = title_node.text if title_node is not None else ""

            # Ambil abstract (bisa beberapa bagian)
            abstract_nodes = article_element.findall(".//AbstractText")
            abstract_parts = [node.text or "" for node in abstract_nodes]
            abstract_value = " ".join(abstract_parts).strip()

            # Ambil PMID
            pmid_node = article_element.find(".//PMID")
            document_identifier = pmid_node.text if pmid_node is not None else str(hash(title_value))

            # Susun dokumen satu artikel
            parsed_document = {
                "id": document_identifier,
                "title": title_value,
                "abstract": abstract_value,
                "authors": [],
                "year": None,
                "doi": None,
                "source": "pubmed",
                "raw_file": file_path.name
            }

            # Masukkan ke list
            parsed_documents.append(parsed_document)

        except Exception as e:
            print(f"Error parsing article in {file_path.name}: {e}")
            continue

    return parsed_documents


# utilitas menyimpan dokumen standar (json) ke folder output
def save_document_as_json(document: dict, output_folder: pathlib.Path):
    safe_document_id = str(document.get("id", "")).replace("/", "_")
    output_file_path = output_folder / f"{safe_document_id}.json"

    output_file_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_file_path

def process_all_raw_files():
    metadata_rows = []

    list_of_raw_files = list(RAW_DIR.glob("*"))

    # looping dengan progress bar
    for raw_file_path in tqdm(list_of_raw_files, desc="Processing raw files"):
        try:
            # menentukan parser berdasarkan nama file
            lower_case_name = raw_file_path.name.lower()

            if lower_case_name.startswith("crossref") and raw_file_path.suffix == ".json":
                parsed_documents = parse_crossref_file(raw_file_path)
            elif lower_case_name.startswith("semantic_scholar") and raw_file_path.suffix == ".json":
                parsed_documents = parse_sematic_scholar_file(raw_file_path)
            elif lower_case_name.startswith("pubmed") and raw_file_path.suffix in [".xml", ".xml"]:
                parsed_documents = parse_pubmed_xml_file(raw_file_path)
            else:
                print(f"Skipping unrecognized file format: {raw_file_path.name}")
                parsed_documents = []

            # menyimpan dokumen yg telah diparse ke folder processed
            for document in parsed_documents:
                saved_path = save_document_as_json(document, PROCESSED_DIR)

                # menyiapkan baris metadata
                metadata_rows.append({
                    "id": document.get("id", ""),
                    "title": document.get("title", "") or "",
                    "source": document.get("source", ""),
                    "raw_file": document.get("raw_file", ""),
                    "processed_file": saved_path.name
                })
            
        except Exception as e:
            print(f"Error processing file {raw_file_path.name}: {e}")
            continue

    # menyimpan metadata ke CSV
    csv_header = ["id", "title", "source", "raw_file", "processed_file"]
    is_new_csv = not METADATA_CSV_PATH.exists()

    with open(METADATA_CSV_PATH, "a", encoding="utf-8", newline="") as csv_file:
        csv_writer = csv.DictWriter(csv_file, fieldnames=csv_header)

        if is_new_csv:
            csv_writer.writeheader()
        csv_writer.writerows(metadata_rows)

if __name__ == "__main__":
    process_all_raw_files()

    print("Processing raw files completed. cek folder 'data/processed' dan 'metadata'.")