import fitz
import json
import requests
import os
import time
import re
import argparse
from dotenv import load_dotenv
from pathlib import Path
from tqdm import tqdm
from datetime import datetime, timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from process_raw import process_all_raw_files

# configurasi
BASE = Path(__file__).parents[1]
OUT_DIR = BASE / 'data' / 'raw_pdf'
TMP_BASE_DIR = BASE / 'data' / 'tmp_pdf'
OUT_DIR.mkdir(parents=True, exist_ok=True)
TMP_BASE_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE / '.env')
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL")

DEFAULT_HEADERS = {
    "User-Agent": f"healthify-loader/1.0 (mailto:{CONTACT_EMAIL})"
}

# keamanan limit retry untuk requests
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
PDF_CONTENT_TYPES = ("application/pdf", "application/x-pdf")

# melakukan req dengan retry
def requests_session_with_retries(total_retries=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 504)):
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

SESSION = requests_session_with_retries()

# membuat penamaan file dari id/judul
def safe_filename(text: str, fallback: str = 'doc'):
    if not text:
        return fallback
    
    name = re.sub(r'[^\w\-_\. ]', '_', str(text))
    return name[:200]

# mengecek apakah response adalah PDF atau url akhiran .pdf
def is_likely_pdf(headers, url):
    ctype = headers.get("Content-Type", "") if headers else ""

    if any(ct in ctype for ct in PDF_CONTENT_TYPES):
        return True
    if url and url.lower().split("?")[0].endswith(".pdf"):
        return True
    return False


# download file dari url menggunakan session dengan retry
def download_pdf(url: str, dest_path: Path, timeout=30, session=SESSION, headers: dict | None = None, max_bytes: int = MAX_DOWNLOAD_BYTES):
    headers = headers or DEFAULT_HEADERS

    with session.get(url, stream=True, timeout=timeout, headers=headers, allow_redirects=True) as response:
        response.raise_for_status()

        if not is_likely_pdf(response.headers, url):
            print(f"Warning: content-type for {url} is {response.headers.get('Content-Type')}. Continuing download (may not be a PDF).")

        total_written = 0

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    total_written += len(chunk)
                    if max_bytes and total_written > max_bytes:
                        raise ValueError(f"Downloaded data exceeds maximum allowed size {max_bytes} bytes: {url}")
                    f.write(chunk)
        return dest_path
    
# ekstrak teks tiap halaman PDF
def extract_text_from_pdf(pdf_path: Path):
    doc = fitz.open(str(pdf_path))

    try:
        text_pages = []

        for p in doc:
            text = p.get_text("text") or ""
            text_pages.append(text)

        combined_text = "\n".join(text_pages).strip()
        return {
            "file_name": pdf_path.name,
            "n_pages": len(doc),
            "extracted_at": datetime.now(timezone.utc).isoformat() + 'Z',
            "text": combined_text
        }
    finally:
        doc.close()

# memproses daftar dokumen dan disimpan di temp
def process_api_result(api_items, dry_run: bool = False, timeout: int = 30):
    results = []

    for item in tqdm(api_items, desc="Processing documents"):
        url = item.get("pdf_url") or item.get("url")

        if not url:
            print("No URL found for item:", item.get("id", "(no id)"))
            continue

        safe_id = safe_filename(item.get("id") or item.get("doi") or item.get("title") or f"doc_{int(time.time())}")
        temp_pdf = TMP_BASE_DIR / f"{safe_id}.pdf"
        out_json = OUT_DIR / f"{safe_id}.json"

        if dry_run:
            print(f"[Dry Run] candidate: id:{safe_id} url={url}")
            continue
        
        try:
            # menunduh pdf ke tmp
            print(f"Downloading {url} to {temp_pdf.name}...")
            download_pdf(url, temp_pdf, timeout=timeout)

            # validasi dan ekstrak teks
            if not temp_pdf.exists() or temp_pdf.stat().st_size == 0:
                raise IOError(f"Downloaded file is empty or does not exist: {temp_pdf}")
            
            extracted = extract_text_from_pdf(temp_pdf)

            # menambahkan api metadata
            extracted["api_meta"] = {
                k: item.get(k)
                for k in ("id", "title", "doi", "source")
                if k in item
            }

            # menulis json hasil
            with out_json.open("w", encoding="utf-8") as fo:
                json.dump(extracted, fo, ensure_ascii=False, indent=2)

            results.append(out_json)
            print(f"Saved extracted text to {out_json}")
        except Exception as e:
            print(f"Failed to process {url}: {e}")
        finally:
            try:
                if temp_pdf.exists():
                    temp_pdf.unlink()
            except Exception as rmerr:
                print(f"Failed to delete temp file {temp_pdf}: {rmerr}")
    return results
    

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Loader: Download PDFs from api_items and extract text.")
    parser.add_argument("--dry-run", action="store_true", help="Do not download, only list candidates")
    parser.add_argument("--items-file", type=str, default=None, help="Optional JSON file with api_items list to process")
    parser.add_argument("--timeout", type=int, default=30, help="Requests timeout")
    args = parser.parse_args()

    # mengambil daftar item (api_items)
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
    process_api_result(api_items, dry_run=args.dry_run, timeout=args.timeout)