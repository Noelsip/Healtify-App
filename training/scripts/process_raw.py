import json
import csv
import pathlib
import xml.etree.ElementTree as xml_parser
from typing import List, Dict, Any
from tqdm import tqdm

# Configuration
BASE_DIR = pathlib.Path(__file__).parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

METADATA_CSV_PATH = BASE_DIR / "data" / "metadata" / "processed_metadata.csv"
METADATA_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)


def parse_crossref_file(file_path: pathlib.Path) -> List[Dict[str, Any]]:
    """Parse file JSON CrossRef dan extract informasi dokumen yang relevan."""
    file_content = file_path.read_text(encoding="utf-8")
    json_object = json.loads(file_content)

    # Get items list from CrossRef response
    items_list = json_object.get("message", {}).get("items", [])
    parsed_documents = []

    for item in items_list:
        # Generate unique identifier
        document_identifier = (
            item.get("DOI") or 
            item.get("URL") or 
            str(hash(json.dumps(item, sort_keys=True)))
        )

        # Extract title
        title_value = None
        if item.get("title"):
            title_value = " ".join(item.get("title"))

        # Extract abstract
        abstract_value = item.get("abstract") or ""

        # Extract authors
        authors_list = []
        if item.get("author"):
            for author_entry in item.get("author", []):
                given_name = author_entry.get("given", "").strip()
                family_name = author_entry.get("family", "").strip()
                combined_name = f"{given_name} {family_name}".strip()
                if combined_name:
                    authors_list.append(combined_name)
        
        # Extract publication year
        year_value = None
        issued_object = item.get("issued", {})
        date_parts = issued_object.get("date-parts", [])
        if date_parts and isinstance(date_parts, list) and len(date_parts) > 0:
            if len(date_parts[0]) > 0:
                year_value = date_parts[0][0]

        # Build structured document
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


def parse_semantic_scholar_file(file_path: pathlib.Path) -> List[Dict[str, Any]]:
    """Parse file JSON Semantic Scholar dan extract informasi paper yang relevan."""
    file_content = file_path.read_text(encoding="utf-8")
    json_object = json.loads(file_content)

    parsed_documents = []

    # Handle both search results and detailed results format
    papers_data = json_object.get("data", []) or json_object.get("detailed_results", [])

    for paper in papers_data:
        # Generate unique identifier
        document_identifier = (
            paper.get("paperId") or 
            paper.get("doi") or 
            paper.get("url") or 
            str(hash(json.dumps(paper, sort_keys=True)))
        )

        # Extract title
        title_value = paper.get("title")

        # Extract abstract
        abstract_value = paper.get("abstract") or ""

        # Extract authors
        authors_list = []
        for author_entry in paper.get("authors", []) or []:
            author_name = author_entry.get("name", "")
            if author_name:
                authors_list.append(author_name)
        
        # Extract publication year
        year_value = paper.get("year")

        # Build structured document
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


def parse_pubmed_xml_file(file_path: pathlib.Path) -> List[Dict[str, Any]]:
    """Parse file XML PubMed dan extract informasi artikel yang relevan."""
    file_content = file_path.read_text(encoding="utf-8")
    xml_root = xml_parser.fromstring(file_content)

    parsed_documents = []

    for article_element in xml_root.findall(".//PubmedArticle"):
        try:
            # Extract title
            title_node = article_element.find(".//ArticleTitle")
            title_value = title_node.text if title_node is not None else ""

            # Extract abstract (can have multiple parts)
            abstract_nodes = article_element.findall(".//AbstractText")
            abstract_parts = [node.text or "" for node in abstract_nodes]
            abstract_value = " ".join(abstract_parts).strip()

            # Extract PMID as identifier
            pmid_node = article_element.find(".//PMID")
            document_identifier = (
                pmid_node.text if pmid_node is not None 
                else str(hash(title_value))
            )

            # Extract authors
            authors_list = []
            author_nodes = article_element.findall(".//Author")
            for author_node in author_nodes:
                first_name_node = author_node.find(".//ForeName")
                last_name_node = author_node.find(".//LastName")
                
                first_name = first_name_node.text if first_name_node is not None else ""
                last_name = last_name_node.text if last_name_node is not None else ""
                
                full_name = f"{first_name} {last_name}".strip()
                if full_name:
                    authors_list.append(full_name)

            # Extract publication year
            year_value = None
            pub_date_node = article_element.find(".//PubDate/Year")
            if pub_date_node is not None:
                try:
                    year_value = int(pub_date_node.text)
                except (ValueError, TypeError):
                    pass

            # Extract DOI if available
            doi_value = None
            doi_nodes = article_element.findall(".//ArticleId[@IdType='doi']")
            if doi_nodes:
                doi_value = doi_nodes[0].text

            # Build structured document
            parsed_document = {
                "id": document_identifier,
                "title": title_value,
                "abstract": abstract_value,
                "authors": authors_list,
                "year": year_value,
                "doi": doi_value,
                "source": "pubmed",
                "raw_file": file_path.name
            }
            parsed_documents.append(parsed_document)

        except Exception as e:
            print(f"Error parsing article in {file_path.name}: {e}")
            continue

    return parsed_documents


def save_document_as_json(document: Dict[str, Any], output_folder: pathlib.Path) -> pathlib.Path:
    """Simpan dokumen sebagai file JSON dengan nama file yang aman."""
    # Create safe filename from document ID
    safe_document_id = str(document.get("id", "")).replace("/", "_")
    if not safe_document_id:
        safe_document_id = "unknown_doc"
    
    output_file_path = output_folder / f"{safe_document_id}.json"

    # Save document as JSON
    output_file_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), 
        encoding="utf-8"
    )
    
    return output_file_path


def determine_parser_for_file(file_path: pathlib.Path):
    """Tentukan parser yang tepat berdasarkan nama file dan ekstensi."""
    lower_case_name = file_path.name.lower()
    
    if lower_case_name.startswith("crossref") and file_path.suffix == ".json":
        return parse_crossref_file
    elif lower_case_name.startswith("semantic_scholar") and file_path.suffix == ".json":
        return parse_semantic_scholar_file
    elif lower_case_name.startswith("pubmed") and file_path.suffix in [".xml"]:
        return parse_pubmed_xml_file
    else:
        return None


def process_all_raw_files() -> List[Dict[str, Any]]:
    """Proses semua file raw dan return list semua dokumen yang telah diparse."""
    metadata_rows = []
    all_documents = []
    
    list_of_raw_files = list(RAW_DIR.glob("*"))

    # Process files with progress bar
    for raw_file_path in tqdm(list_of_raw_files, desc="Processing raw files"):
        try:
            parser_function = determine_parser_for_file(raw_file_path)
            
            if parser_function is None:
                print(f"Skipping unrecognized file format: {raw_file_path.name}")
                continue

            # Parse documents using appropriate parser
            parsed_documents = parser_function(raw_file_path)

            # Save each document to processed folder
            for document in parsed_documents:
                saved_path = save_document_as_json(document, PROCESSED_DIR)
                all_documents.append(document)

                # Prepare metadata row
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

    # Save metadata to CSV
    _save_metadata_to_csv(metadata_rows)
    
    return all_documents


def _save_metadata_to_csv(metadata_rows: List[Dict[str, Any]]):
    """Simpan metadata processing ke CSV file."""
    csv_header = ["id", "title", "source", "raw_file", "processed_file"]
    is_new_csv = not METADATA_CSV_PATH.exists()

    with open(METADATA_CSV_PATH, "a", encoding="utf-8", newline="") as csv_file:
        csv_writer = csv.DictWriter(csv_file, fieldnames=csv_header)

        if is_new_csv:
            csv_writer.writeheader()
        csv_writer.writerows(metadata_rows)


def main():
    """Entry point untuk command line execution."""
    documents = process_all_raw_files()
    print(f"Processing completed. {len(documents)} documents processed.")
    print("Check folders 'data/processed' dan 'data/metadata' for results.")


if __name__ == "__main__":
    main()