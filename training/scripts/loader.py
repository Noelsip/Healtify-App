import os
import re
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

import fitz
import requests
from dotenv import load_dotenv
from tqdm import tqdm
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from process_raw import process_all_raw_files

# Configuration
BASE = Path(__file__).parents[1]
OUT_DIR = BASE / 'data' / 'raw_pdf'
TMP_BASE_DIR = BASE / 'data' / 'tmp_pdf'
OUT_DIR.mkdir(parents=True, exist_ok=True)
TMP_BASE_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE / '.env')
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL")

# Constants
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  
PDF_CONTENT_TYPES = ("application/pdf", "application/x-pdf")
DEFAULT_HEADERS = {
    "User-Agent": f"healthify-loader/1.0 (mailto:{CONTACT_EMAIL})"
}

def create_requests_session(total_retries=3, backoff_factor=0.5, 
                           status_forcelist=(429, 500, 502, 504)):
    """Buat session requests dengan retry mechanism untuk handling network errors."""
    session = requests.Session()
    retries = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset(['GET', 'POST', 'PUT', 'DELETE', 'HEAD', 'OPTIONS'])
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def create_safe_filename(text: str, fallback: str = 'doc', max_length: int = 200) -> str:
    """Konversi text menjadi nama file yang aman dengan menghilangkan karakter tidak valid."""
    if not text:
        return fallback
    
    # Replace invalid characters with underscore
    safe_name = re.sub(r'[^\w\-_\. ]', '_', str(text))
    return safe_name[:max_length]

def is_likely_pdf_content(headers: dict, url: str) -> bool:
    """Cek apakah response kemungkinan berisi PDF berdasarkan headers dan URL."""
    content_type = headers.get("Content-Type", "") if headers else ""

    # Check content type
    if any(ct in content_type for ct in PDF_CONTENT_TYPES):
        return True
        
    # Check URL extension
    if url and url.lower().split("?")[0].endswith(".pdf"):
        return True
        
    return False

def download_pdf_from_url(url: str, dest_path: Path, timeout: int = 30, 
                         session=None, headers: dict = None, 
                         max_bytes: int = MAX_DOWNLOAD_BYTES) -> Path:
    """Download PDF dari URL dengan streaming dan size limit untuk keamanan."""
    if session is None:
        session = create_requests_session()
    
    headers = headers or DEFAULT_HEADERS

    with session.get(url, stream=True, timeout=timeout, 
                    headers=headers, allow_redirects=True) as response:
        response.raise_for_status()

        if not is_likely_pdf_content(response.headers, url):
            print(f"Warning: content-type for {url} is {response.headers.get('Content-Type')}. "
                  f"Continuing download (may not be a PDF).")

        total_written = 0
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    total_written += len(chunk)
                    if max_bytes and total_written > max_bytes:
                        raise ValueError(f"Downloaded data exceeds maximum allowed size "
                                       f"{max_bytes} bytes: {url}")
                    f.write(chunk)
    
    return dest_path

def extract_text_from_pdf_file(pdf_path: Path) -> dict:
    """Ekstrak teks dari semua halaman PDF dan return sebagai structured data."""
    doc = fitz.open(str(pdf_path))

    try:
        text_pages = []
        for page in doc:
            page_text = page.get_text("text") or ""
            text_pages.append(page_text)

        combined_text = "\n".join(text_pages).strip()
        
        return {
            "file_name": pdf_path.name,
            "n_pages": len(doc),
            "extracted_at": datetime.now(timezone.utc).isoformat() + 'Z',
            "text": combined_text
        }
    finally:
        doc.close()

def process_single_document(item: dict, timeout: int = 30, session=None) -> dict:
    """Proses satu dokumen: download PDF, ekstrak teks, dan simpan hasil."""
    url = item.get("pdf_url") or item.get("url")
    
    if not url:
        raise ValueError(f"No URL found for item: {item.get('id', '(no id)')}")

    # Generate safe filenames
    safe_id = create_safe_filename(
        item.get("id") or item.get("doi") or item.get("title") or f"doc_{int(time.time())}"
    )
    temp_pdf = TMP_BASE_DIR / f"{safe_id}.pdf"
    out_json = OUT_DIR / f"{safe_id}.json"

    try:
        # Download PDF to temporary location
        print(f"Downloading {url} to {temp_pdf.name}...")
        download_pdf_from_url(url, temp_pdf, timeout=timeout, session=session)

        # Validate downloaded file
        if not temp_pdf.exists() or temp_pdf.stat().st_size == 0:
            raise IOError(f"Downloaded file is empty or does not exist: {temp_pdf}")
        
        # Extract text from PDF
        extracted_data = extract_text_from_pdf_file(temp_pdf)

        # Add API metadata to extracted data
        extracted_data["api_meta"] = {
            key: item.get(key)
            for key in ("id", "title", "doi", "source")
            if key in item
        }

        # Save extracted data as JSON
        with out_json.open("w", encoding="utf-8") as fo:
            json.dump(extracted_data, fo, ensure_ascii=False, indent=2)

        print(f"Saved extracted text to {out_json}")
        return {"success": True, "file_path": out_json, "url": url}

    finally:
        # Clean up temporary file
        try:
            if temp_pdf.exists():
                temp_pdf.unlink()
        except Exception as cleanup_error:
            print(f"Failed to delete temp file {temp_pdf}: {cleanup_error}")

def process_api_result(api_items: list, dry_run: bool = False, timeout: int = 30) -> list:
    """Proses daftar dokumen dari API results dan return list file paths yang berhasil."""
    if dry_run:
        print("=== DRY RUN MODE ===")
        for item in api_items:
            url = item.get("pdf_url") or item.get("url")
            safe_id = create_safe_filename(
                item.get("id") or item.get("doi") or item.get("title") or f"doc_{int(time.time())}"
            )
            print(f"[Dry Run] candidate: id:{safe_id} url={url}")
        return []

    results = []
    session = create_requests_session()

    for item in tqdm(api_items, desc="Processing documents"):
        try:
            result = process_single_document(item, timeout=timeout, session=session)
            if result.get("success"):
                results.append(result["file_path"])
        except Exception as e:
            url = item.get("pdf_url") or item.get("url", "unknown")
            print(f"Failed to process {url}: {e}")

    return results

def main():
    """Entry point untuk command line interface."""
    parser = argparse.ArgumentParser(
        description="Loader: Download PDFs from api_items and extract text."
    )
    parser.add_argument("--dry-run", action="store_true", 
                       help="Do not download, only list candidates")
    parser.add_argument("--items-file", type=str, default=None, 
                       help="Optional JSON file with api_items list to process")
    parser.add_argument("--timeout", type=int, default=30, 
                       help="Requests timeout in seconds")
    
    args = parser.parse_args()

    # Load API items from file or process raw files
    if args.items_file:
        items_path = Path(args.items_file)
        if not items_path.exists():
            print(f"Items file not found: {items_path}")
            raise SystemExit(1)
        api_items = json.loads(items_path.read_text(encoding="utf-8"))
    else:
        print("Fetching api_items from process_raw.py...")
        api_items = process_all_raw_files()

    print(f"Memulai memproses {len(api_items)} dokumen...")    
    results = process_api_result(api_items, dry_run=args.dry_run, timeout=args.timeout)
    
    if not args.dry_run:
        print(f"Selesai. {len(results)} dokumen berhasil diproses.")

if __name__ == "__main__":
    main()