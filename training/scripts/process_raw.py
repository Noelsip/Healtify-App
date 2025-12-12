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

def parse_google_books_file(file_path: pathlib.Path) -> List[Dict[str, Any]]:
    """Parse file JSON Google Books dan extract informasi buku yang relevan."""
    file_content = file_path.read_text(encoding="utf-8")
    json_object = json.loads(file_content)

    parsed_documents = []
    items = json_object.get("items", [])

    for item in items:
        volume_info = item.get("volumeInfo", {})
        
        # Generate unique identifier
        google_id = item.get("id", "")
        document_identifier = google_id or str(hash(json.dumps(item, sort_keys=True)))

        # Extract title
        title_value = volume_info.get("title")

        # Extract description (abstract)
        abstract_value = volume_info.get("description", "")

        # Extract authors
        authors_list = volume_info.get("authors", [])
        
        # Extract publication year
        year_value = None
        published_date = volume_info.get("publishedDate", "")
        if published_date:
            try:
                year_value = int(published_date.split("-")[0])
            except (ValueError, IndexError):
                pass

        # Extract ISBN as alternative identifier
        isbn_value = None
        industry_identifiers = volume_info.get("industryIdentifiers", [])
        for identifier in industry_identifiers:
            if identifier.get("type") in ["ISBN_13", "ISBN_10"]:
                isbn_value = identifier.get("identifier")
                break

        # Build structured document
        parsed_document = {
            "id": document_identifier,
            "title": title_value,
            "abstract": abstract_value,
            "authors": authors_list,
            "year": year_value,
            "doi": None,  # Books typically don't have DOIs
            "isbn": isbn_value,
            "source": "google_books",
            "raw_file": file_path.name
        }
        parsed_documents.append(parsed_document)
    
    return parsed_documents

def parse_sciencedirect_file(file_path: pathlib.Path) -> List[Dict[str, Any]]:
    """Parse file JSON ScienceDirect dan extract informasi artikel yang relevan."""
    file_content = file_path.read_text(encoding="utf-8")
    json_object = json.loads(file_content)

    parsed_documents = []
    
    # ScienceDirect response structure
    search_results = json_object.get("search-results", {})
    entries = search_results.get("entry", [])

    for entry in entries:
        # Generate unique identifier
        doi = entry.get("prism:doi", "")
        pii = entry.get("pii", "")
        document_identifier = doi or pii or str(hash(json.dumps(entry, sort_keys=True)))

        # Extract title
        title_value = entry.get("dc:title")

        # Extract abstract
        abstract_value = entry.get("dc:description", "")

        # Extract authors
        authors_list = []
        authors_raw = entry.get("authors", {}).get("author", [])
        if isinstance(authors_raw, list):
            for author in authors_raw:
                author_name = author.get("$", "") or author.get("authname", "")
                if author_name:
                    authors_list.append(author_name)
        
        # Extract publication year
        year_value = None
        cover_date = entry.get("prism:coverDate", "")
        if cover_date:
            try:
                year_value = int(cover_date.split("-")[0])
            except (ValueError, IndexError):
                pass

        # Build structured document
        parsed_document = {
            "id": document_identifier,
            "title": title_value,
            "abstract": abstract_value,
            "authors": authors_list,
            "year": year_value,
            "doi": doi,
            "source": "sciencedirect",
            "raw_file": file_path.name
        }
        parsed_documents.append(parsed_document)
    
    return parsed_documents

def parse_openlibrary_file(file_path: pathlib.Path) -> List[Dict[str, Any]]:
    """Parse file JSON Open Library dan extract informasi buku yang relevan."""
    file_content = file_path.read_text(encoding="utf-8")
    json_object = json.loads(file_content)

    parsed_documents = []
    docs = json_object.get("docs", [])

    for doc in docs:
        # Generate unique identifier
        key = doc.get("key", "")
        document_identifier = key or str(hash(json.dumps(doc, sort_keys=True)))

        # Extract title
        title_value = doc.get("title")

        # Extract first sentence or description
        abstract_value = ""
        if doc.get("first_sentence"):
            abstract_value = " ".join(doc["first_sentence"]) if isinstance(doc["first_sentence"], list) else doc["first_sentence"]

        # Extract authors
        authors_list = doc.get("author_name", [])
        
        # Extract publication year
        year_value = None
        publish_year = doc.get("first_publish_year")
        if publish_year:
            try:
                year_value = int(publish_year)
            except (ValueError, TypeError):
                pass

        # Extract ISBN
        isbn_value = None
        isbns = doc.get("isbn", [])
        if isbns:
            isbn_value = isbns[0]

        # Build structured document
        parsed_document = {
            "id": document_identifier,
            "title": title_value,
            "abstract": abstract_value,
            "authors": authors_list,
            "year": year_value,
            "doi": None,
            "isbn": isbn_value,
            "source": "openlibrary",
            "raw_file": file_path.name
        }
        parsed_documents.append(parsed_document)
    
    return parsed_documents

# NEW SOURCE PARSERS
def parse_europepmc_file(file_path: pathlib.Path) -> List[Dict[str, Any]]:
    """Parse file JSON Europe PMC."""
    file_content = file_path.read_text(encoding="utf-8")
    json_object = json.loads(file_content)
    
    results = json_object.get("resultList", {}).get("result", [])
    parsed_documents = []
    
    for item in results:
        doc_id = item.get("id") or item.get("pmid") or item.get("doi")
        
        # Extract authors
        authors_list = []
        for author in item.get("authorList", {}).get("author", []):
            name = author.get("fullName", "")
            if name:
                authors_list.append(name)
        
        parsed_document = {
            "id": doc_id,
            "title": item.get("title", ""),
            "abstract": item.get("abstractText", ""),
            "authors": authors_list,
            "year": item.get("pubYear"),
            "doi": item.get("doi"),
            "url": f"https://europepmc.org/article/{item.get('source', 'MED')}/{item.get('id', '')}",
            "source": "europepmc",
            "source_portal": "europepmc",
            "raw_file": file_path.name
        }
        parsed_documents.append(parsed_document)
    
    return parsed_documents

def parse_openalex_file(file_path: pathlib.Path) -> List[Dict[str, Any]]:
    """Parse file JSON OpenAlex."""
    file_content = file_path.read_text(encoding="utf-8")
    json_object = json.loads(file_content)
    
    results = json_object.get("results", [])
    parsed_documents = []
    
    for work in results:
        # Get DOI
        doi_url = work.get("doi", "")
        doi = doi_url.replace("https://doi.org/", "") if doi_url else ""
        
        # Get authors
        authors_list = []
        for authorship in work.get("authorships", [])[:10]:
            author = authorship.get("author", {})
            name = author.get("display_name", "")
            if name:
                authors_list.append(name)
        
        parsed_document = {
            "id": doi or work.get("id", ""),
            "title": work.get("title", ""),
            "abstract": work.get("abstract", ""),
            "authors": authors_list,
            "year": work.get("publication_year"),
            "doi": doi,
            "url": doi_url or work.get("id", ""),
            "cited_by_count": work.get("cited_by_count", 0),
            "is_oa": work.get("open_access", {}).get("is_oa", False),
            "source": "openalex",
            "source_portal": "openalex",
            "raw_file": file_path.name
        }
        parsed_documents.append(parsed_document)
    
    return parsed_documents

def parse_doaj_file(file_path: pathlib.Path) -> List[Dict[str, Any]]:
    """Parse file JSON DOAJ."""
    file_content = file_path.read_text(encoding="utf-8")
    json_object = json.loads(file_content)
    
    results = json_object.get("results", [])
    parsed_documents = []
    
    for item in results:
        bibjson = item.get("bibjson", {})
        
        # Get DOI
        doi = ""
        for identifier in bibjson.get("identifier", []):
            if identifier.get("type") == "doi":
                doi = identifier.get("id", "")
                break
        
        # Get authors
        authors_list = [a.get("name", "") for a in bibjson.get("author", [])[:10] if a.get("name")]
        
        # Get URL
        url = ""
        for link in bibjson.get("link", []):
            if link.get("type") == "fulltext":
                url = link.get("url", "")
                break
        
        parsed_document = {
            "id": doi or item.get("id", ""),
            "title": bibjson.get("title", ""),
            "abstract": bibjson.get("abstract", ""),
            "authors": authors_list,
            "year": bibjson.get("year"),
            "doi": doi,
            "url": url or (f"https://doi.org/{doi}" if doi else ""),
            "journal": bibjson.get("journal", {}).get("title", ""),
            "source": "doaj",
            "source_portal": "doaj",
            "raw_file": file_path.name
        }
        parsed_documents.append(parsed_document)
    
    return parsed_documents

def parse_arxiv_file(file_path: pathlib.Path) -> List[Dict[str, Any]]:
    """Parse file JSON arXiv."""
    file_content = file_path.read_text(encoding="utf-8")
    json_object = json.loads(file_content)
    
    entries = json_object.get("entries", [])
    parsed_documents = []
    
    for entry in entries:
        url = entry.get("url", "")
        arxiv_id = url.split("/")[-1] if url else ""
        
        parsed_document = {
            "id": arxiv_id or url,
            "title": entry.get("title", ""),
            "abstract": entry.get("abstract", ""),
            "authors": [],
            "year": None,
            "doi": None,
            "url": url,
            "source": "arxiv",
            "source_portal": "arxiv",
            "source_type": "preprint",
            "raw_file": file_path.name
        }
        parsed_documents.append(parsed_document)
    
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
    elif lower_case_name.startswith("google_books") and file_path.suffix == ".json":
        return parse_google_books_file
    elif lower_case_name.startswith("sciencedirect") and file_path.suffix == ".json":
        return parse_sciencedirect_file
    elif lower_case_name.startswith("openlibrary") and file_path.suffix == ".json":
        return parse_openlibrary_file
    # NEW SOURCES
    elif lower_case_name.startswith("europepmc") and file_path.suffix == ".json":
        return parse_europepmc_file
    elif lower_case_name.startswith("openalex") and file_path.suffix == ".json":
        return parse_openalex_file
    elif lower_case_name.startswith("doaj") and file_path.suffix == ".json":
        return parse_doaj_file
    elif lower_case_name.startswith("arxiv") and file_path.suffix == ".json":
        return parse_arxiv_file
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