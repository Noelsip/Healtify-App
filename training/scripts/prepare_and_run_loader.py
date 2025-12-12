import json
import re
import csv
import socket
import argparse
from pathlib import Path
from typing import List, Dict, Any, Set
from datetime import datetime
from tqdm import tqdm

from loader import process_api_result as run_loader

# Configuration
BASE = Path(__file__).parents[1]
RAW_DIR = BASE / "data" / "raw"
META_DIR = BASE / "data" / "metadata"
META_DIR.mkdir(parents=True, exist_ok=True)

ERROR_LOG_PATH = META_DIR / "loader_errors.csv"
SUCCESS_LOG_PATH = META_DIR / "loader_success.csv"
CLEANED_ITEMS_PATH = META_DIR / "api_items_cleaned.json"

def log_error(url: str, reason: str):
    """Simpan log error ke CSV file untuk tracking."""
    header = ["timestamp", "url", "reason"]
    is_new_file = not ERROR_LOG_PATH.exists()
    
    with open(ERROR_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new_file:
            writer.writerow(header)
        writer.writerow([datetime.now().isoformat(), url, reason])

def log_success(url: str, file_path: str):
    """Simpan log success ke CSV file untuk tracking."""
    header = ["timestamp", "url", "file_path"]
    is_new_file = not SUCCESS_LOG_PATH.exists()
    
    with open(SUCCESS_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new_file:
            writer.writerow(header)
        writer.writerow([datetime.now().isoformat(), url, file_path])

def is_private_ip_address(url: str) -> bool:
    """Cek apakah URL mengarah ke IP address privat untuk keamanan."""
    try:
        # Extract hostname from URL
        host = url.split("//")[1].split("/")[0].split(":")[0]
        ip = socket.gethostbyname(host)
        
        # Check if IP is in private ranges
        private_ranges = ("10.", "172.", "192.168.")
        return ip.startswith(private_ranges)
    except Exception:
        return False

def extract_pdf_urls_from_crossref(crossref_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract PDF URLs dan metadata dari data CrossRef."""
    results = []
    items = crossref_data.get("message", {}).get("items", []) or []
    
    for item in items:
        doi = item.get("DOI")
        title_list = item.get("title") or []
        title = title_list[0] if title_list else ""
        
        # Look for PDF links
        pdf_url = None
        links = item.get("link", []) or []
        
        for link in links:
            url = link.get("URL") or link.get("url")
            content_type = (link.get("content-type") or "").lower()
            
            if url and (".pdf" in url.lower() or "application/pdf" in content_type):
                pdf_url = url
                break
        
        # Fallback: check main URL
        if not pdf_url:
            main_url = item.get("URL")
            if main_url and main_url.lower().endswith(".pdf"):
                pdf_url = main_url
        
        if pdf_url:
            # Generate safe identifier
            identifier = (
                doi.replace("/", "_") if doi 
                else re.sub(r"\W+", "_", title)[:50] 
                or "crossref_doc"
            )
            
            results.append({
                "id": identifier,
                "pdf_url": pdf_url,
                "title": title,
                "doi": doi,
                "source": "crossref"
            })
    
    return results

def extract_pdf_urls_from_semantic_scholar(scholar_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract PDF URLs dan metadata dari data Semantic Scholar."""
    results = []
    
    # Handle different response formats
    detailed_results = (
        scholar_data.get("detailed_results") or 
        scholar_data.get("data") or 
        []
    )
    
    for paper in detailed_results:
        paper_id = (
            paper.get("paperId") or 
            paper.get("paper_id") or 
            paper.get("id")
        )
        title = paper.get("title") or ""
        doi = paper.get("doi") or (paper.get("externalIds") or {}).get("DOI")
        
        # Look for PDF URL in different fields
        pdf_url = None
        
        # Check openAccessPdf field
        open_pdf = paper.get("openAccessPdf") or {}
        if isinstance(open_pdf, dict):
            pdf_url = open_pdf.get("url")
        
        # Check other PDF fields
        if not pdf_url:
            pdf_url = paper.get("pdfUrl") or paper.get("pdf_url")
        
        # Check main URL if it's a PDF
        if not pdf_url:
            url = paper.get("url")
            if url and url.lower().endswith(".pdf"):
                pdf_url = url
        
        if pdf_url:
            # Generate safe identifier
            identifier = (
                paper_id or 
                (doi.replace("/", "_") if doi else None) or
                re.sub(r"\W+", "_", title)[:50] or 
                "s2_doc"
            )
            
            results.append({
                "id": identifier,
                "pdf_url": pdf_url,
                "title": title,
                "doi": doi,
                "source": "semantic_scholar"
            })
    
    return results

def extract_pdf_urls_from_sciencedirect(scidir_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract PDF URLs dan metadata dari data ScienceDirect."""
    results = []
    
    search_results = scidir_data.get("search-results", {})
    entries = search_results.get("entry", [])
    
    for entry in entries:
        doi = entry.get("prism:doi", "")
        pii = entry.get("pii", "")
        title = entry.get("dc:title", "")
        
        # Look for PDF URL in links
        pdf_url = None
        links = entry.get("link", [])
        
        for link in links:
            if isinstance(link, dict):
                ref = link.get("@ref", "")
                href = link.get("@href", "")
                
                # Check for PDF or full-text links
                if "pdf" in ref.lower() or "pdfurl" in ref.lower():
                    pdf_url = href
                    break
                elif "full-text" in ref.lower() and href:
                    # Some full-text links may be PDFs
                    if href.lower().endswith(".pdf"):
                        pdf_url = href
                        break
        
        # construct PDF URL from DOI if available
        if not pdf_url and doi:
            # Note: This may not always work without authentication
            pdf_url = f"https://www.sciencedirect.com/science/article/pii/{pii}/pdf" if pii else None
        
        if pdf_url:
            identifier = (
                doi.replace("/", "_") if doi 
                else pii or 
                re.sub(r"\W+", "_", title)[:50] or 
                "scidir_doc"
            )
            
            results.append({
                "id": identifier,
                "pdf_url": pdf_url,
                "title": title,
                "doi": doi,
                "source": "sciencedirect"
            })
    
    return results

def extract_pdf_urls_from_google_books(books_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract PDF URLs dan metadata dari data Google Books."""
    results = []
    
    items = books_data.get("items", [])
    
    for item in items:
        volume_info = item.get("volumeInfo", {})
        access_info = item.get("accessInfo", {})
        
        google_id = item.get("id", "")
        title = volume_info.get("title", "")
        
        # Look for PDF download link
        pdf_url = None
        
        # Check if PDF is available
        if access_info.get("pdf", {}).get("isAvailable"):
            pdf_download_link = access_info.get("pdf", {}).get("downloadLink")
            if pdf_download_link:
                pdf_url = pdf_download_link
        
        # Alternative: check for epub and convert (less common)
        if not pdf_url:
            epub_link = access_info.get("epub", {}).get("downloadLink")
            # We skip epub for now as it requires conversion
            pass
        
        if pdf_url:
            # Extract ISBN if available
            isbn = None
            for identifier in volume_info.get("industryIdentifiers", []):
                if identifier.get("type") in ["ISBN_13", "ISBN_10"]:
                    isbn = identifier.get("identifier")
                    break
            
            identifier = (
                google_id or 
                isbn or 
                re.sub(r"\W+", "_", title)[:50] or 
                "gbook_doc"
            )
            
            results.append({
                "id": identifier,
                "pdf_url": pdf_url,
                "title": title,
                "doi": None,  # Books typically don't have DOIs
                "source": "google_books"
            })
    
    return results

def extract_pdf_urls_from_openlibrary(openlibrary_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract PDF URLs dan metadata dari data Open Library."""
    results = []
    
    docs = openlibrary_data.get("docs", [])
    
    for doc in docs:
        key = doc.get("key", "")
        title = doc.get("title", "")
        
        # Open Library doesn't typically provide direct PDF downloads
        # But we can check if there are any available formats
        pdf_url = None
        
        # Check for Internet Archive lending links
        ia_ids = doc.get("ia", [])
        if ia_ids and isinstance(ia_ids, list) and len(ia_ids) > 0:
            ia_id = ia_ids[0]
            # Construct Internet Archive PDF link
            pdf_url = f"https://archive.org/download/{ia_id}/{ia_id}.pdf"
        
        if pdf_url:
            # Extract ISBN if available
            isbn = None
            isbns = doc.get("isbn", [])
            if isbns:
                isbn = isbns[0]
            
            identifier = (
                key.replace("/", "_") if key 
                else isbn or 
                re.sub(r"\W+", "_", title)[:50] or 
                "openlib_doc"
            )
            
            results.append({
                "id": identifier,
                "pdf_url": pdf_url,
                "title": title,
                "doi": None,  # Books typically don't have DOIs
                "source": "openlibrary"
            })
    
    return results

def build_api_items_from_raw_files() -> List[Dict[str, Any]]:
    """Build daftar API items dari semua file raw yang tersedia."""
    api_items = []
    
    # Process CrossRef files
    for crossref_file in RAW_DIR.glob("crossref_*.json"):
        try:
            data = json.loads(crossref_file.read_text(encoding="utf-8"))
            api_items.extend(extract_pdf_urls_from_crossref(data))
        except Exception as e:
            print(f"[warn] Failed to parse {crossref_file.name}: {e}")
    
    # Process Semantic Scholar files
    for scholar_file in RAW_DIR.glob("semantic_scholar_*.json"):
        try:
            data = json.loads(scholar_file.read_text(encoding="utf-8"))
            api_items.extend(extract_pdf_urls_from_semantic_scholar(data))
        except Exception as e:
            print(f"[warn] Failed to parse {scholar_file.name}: {e}")
    
    # Process ScienceDirect files
    for scidir_file in RAW_DIR.glob("sciencedirect_*.json"):
        try:
            data = json.loads(scidir_file.read_text(encoding="utf-8"))
            api_items.extend(extract_pdf_urls_from_sciencedirect(data))
        except Exception as e:
            print(f"[warn] Failed to parse {scidir_file.name}: {e}")
    
    # Process Google Books files
    for books_file in RAW_DIR.glob("google_books_*.json"):
        try:
            data = json.loads(books_file.read_text(encoding="utf-8"))
            api_items.extend(extract_pdf_urls_from_google_books(data))
        except Exception as e:
            print(f"[warn] Failed to parse {books_file.name}: {e}")
    
    # Process Open Library files
    for openlib_file in RAW_DIR.glob("openlibrary_*.json"):
        try:
            data = json.loads(openlib_file.read_text(encoding="utf-8"))
            api_items.extend(extract_pdf_urls_from_openlibrary(data))
        except Exception as e:
            print(f"[warn] Failed to parse {openlib_file.name}: {e}")
    
    return api_items

def deduplicate_api_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate items berdasarkan PDF URL."""
    seen_urls: Set[str] = set()
    unique_items = []
    
    for item in items:
        pdf_url = item.get("pdf_url")
        if not pdf_url or pdf_url in seen_urls:
            continue
        
        seen_urls.add(pdf_url)
        unique_items.append(item)
    
    return unique_items

def get_previously_failed_urls() -> Set[str]:
    """Get set of URLs yang pernah gagal dari error log sebelumnya."""
    failed_urls: Set[str] = set()
    
    if ERROR_LOG_PATH.exists():
        try:
            with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # Skip header
                
                for row in reader:
                    if len(row) >= 2:
                        failed_urls.add(row[1])
        except Exception as e:
            print(f"Warning: Could not read error log: {e}")
    
    return failed_urls

def clean_and_filter_items(api_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter dan bersihkan API items dari URL tidak valid atau berbahaya."""
    cleaned_items = []
    failed_urls = get_previously_failed_urls()
    
    for item in api_items:
        pdf_url = item.get("pdf_url")
        if not pdf_url:
            continue
        
        # Skip URLs yang pernah gagal
        if pdf_url in failed_urls:
            print(f"[skip] URL sudah pernah gagal sebelumnya: {pdf_url}")
            continue
        
        # Skip private/local IP addresses untuk keamanan
        if is_private_ip_address(pdf_url):
            print(f"[skip] URL mengarah ke IP privat: {pdf_url}")
            log_error(pdf_url, "private/local IP skipped")
            continue
        
        cleaned_items.append(item)
    
    return cleaned_items

def process_documents_safely(api_items: List[Dict[str, Any]]) -> List[str]:
    """Process documents satu per satu dengan error handling yang aman."""
    saved_files = []
    
    for item in tqdm(api_items, desc="Processing documents"):
        url = item["pdf_url"]
        try:
            # Process single item to avoid blocking all processing on one error
            result = run_loader([item])
            if result:
                log_success(url, str(result[0]))
                saved_files.extend(result)
        except Exception as e:
            print(f"[error] Failed to process {url}: {e}")
            log_error(url, str(e))
    
    return saved_files

def save_cleaned_items(api_items: List[Dict[str, Any]]):
    """Simpan daftar API items yang sudah dibersihkan ke file JSON."""
    with open(CLEANED_ITEMS_PATH, "w", encoding="utf-8") as f:
        json.dump(api_items, f, ensure_ascii=False, indent=2)

def main(dry_run: bool = False):
    """Main pipeline untuk prepare dan run loader dengan error handling yang baik."""
    
    print("[1/4] Reading raw files from data/raw ...")
    api_items = build_api_items_from_raw_files()
    print(f"    -> Found {len(api_items)} PDF URL candidates")

    print("[2/4] Cleaning and deduplicating items ...")
    api_items = deduplicate_api_items(api_items)
    print(f"    -> {len(api_items)} unique URLs after deduplication")

    api_items = clean_and_filter_items(api_items)
    print(f"    -> {len(api_items)} valid URLs after filtering")

    if dry_run:
        print("\n=== DRY RUN: Top 20 URLs ===")
        for i, item in enumerate(api_items[:20], 1):
            print(f" {i:2d}. {item['pdf_url']}")
            print(f"     Title: {item.get('title', 'No title')[:80]}...")
        return api_items

    if not api_items:
        print("No valid URLs to process.")
        return []

    print("\n[3/4] Running loader for download + text extraction ...")
    saved_files = process_documents_safely(api_items)

    print(f"\n[4/4] Loader completed. {len(saved_files)} files successfully extracted.")
    save_cleaned_items(api_items)
    print(f"Valid URL list saved to {CLEANED_ITEMS_PATH}")

    print(f"\nPipeline completed without fatal errors.")
    print(f"Extracted results: data/raw_pdf/")
    print(f"Logs: {ERROR_LOG_PATH} and {SUCCESS_LOG_PATH}")

    return saved_files


def create_argument_parser():
    """Create command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Prepare api_items, clean invalid URLs, and run loader safely."
    )
    parser.add_argument("--dry-run", action="store_true", 
                       help="Show URL list without downloading")
    return parser


if __name__ == "__main__":
    parser = create_argument_parser()
    args = parser.parse_args()
    main(dry_run=args.dry_run)