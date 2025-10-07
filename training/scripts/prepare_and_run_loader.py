import json
import re
import csv
import socket
from pathlib import Path
from tqdm import tqdm
from datetime import datetime
from loader import process_api_result as run_loader

# === Konfigurasi utama ===
BASE = Path(__file__).parents[1]
RAW_DIR = BASE / "data" / "raw"
META_DIR = BASE / "data" / "metadata"
META_DIR.mkdir(parents=True, exist_ok=True)

ERROR_LOG_PATH = META_DIR / "loader_errors.csv"
SUCCESS_LOG_PATH = META_DIR / "loader_success.csv"
CLEANED_ITEMS_PATH = META_DIR / "api_items_cleaned.json"

# === Utilitas log dan validasi ===
def log_error(url: str, reason: str):
    """Simpan log error ke CSV"""
    header = ["timestamp", "url", "reason"]
    new_file = not ERROR_LOG_PATH.exists()
    with open(ERROR_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(header)
        writer.writerow([datetime.now().isoformat(), url, reason])

def log_success(url: str, file_path: str):
    """Simpan log sukses ke CSV"""
    header = ["timestamp", "url", "file_path"]
    new_file = not SUCCESS_LOG_PATH.exists()
    with open(SUCCESS_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(header)
        writer.writerow([datetime.now().isoformat(), url, file_path])

def is_private_ip(url: str) -> bool:
    """Cek apakah URL mengarah ke IP privat"""
    try:
        host = url.split("//")[1].split("/")[0].split(":")[0]
        ip = socket.gethostbyname(host)
        return ip.startswith(("10.", "172.", "192.168."))
    except Exception:
        return False

def extract_pdf_urls_from_crossref(obj):
    """Ambil PDF URL dari file CrossRef"""
    results = []
    items = obj.get("message", {}).get("items", []) or []
    for it in items:
        doi = it.get("DOI")
        title_list = it.get("title") or []
        title = title_list[0] if title_list else ""
        links = it.get("link", []) or []
        pdf_url = None
        for l in links:
            url = l.get("URL") or l.get("url")
            ctype = (l.get("content-type") or "").lower()
            if url and (".pdf" in url.lower() or "application/pdf" in ctype):
                pdf_url = url
                break
        if not pdf_url:
            maybe = it.get("URL")
            if maybe and maybe.lower().endswith(".pdf"):
                pdf_url = maybe
        if pdf_url:
            identifier = doi.replace("/", "_") if doi else re.sub(r"\W+", "_", title)[:50] or "crossref_doc"
            results.append({
                "id": identifier,
                "pdf_url": pdf_url,
                "title": title,
                "doi": doi,
                "source": "crossref"
            })
    return results

def extract_pdf_from_semantic_scholar(obj):
    """Ambil PDF URL dari Semantic Scholar"""
    results = []
    detailed = obj.get("detailed_results") or obj.get("data") or []
    for det in detailed:
        pid = det.get("paperId") or det.get("paper_id") or det.get("paperId")
        title = det.get("title") or ""
        doi = det.get("doi") or (det.get("externalIds") or {}).get("DOI")
        pdf_url = None
        open_pdf = det.get("openAccessPdf") or {}
        if isinstance(open_pdf, dict):
            pdf_url = open_pdf.get("url")
        if not pdf_url:
            pdf_url = det.get("pdfUrl") or det.get("pdf_url")
        if not pdf_url:
            url = det.get("url")
            if url and url.lower().endswith(".pdf"):
                pdf_url = url
        if pdf_url:
            identifier = pid or (doi.replace("/", "_") if doi else re.sub(r"\W+", "_", title)[:50] or "s2_doc")
            results.append({
                "id": identifier,
                "pdf_url": pdf_url,
                "title": title,
                "doi": doi,
                "source": "semantic_scholar"
            })
    return results

def build_api_items_from_raw():
    """Bangun daftar api_items dari file raw di data/raw"""
    api_items = []
    for p in RAW_DIR.glob("crossref_*.json"):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            api_items.extend(extract_pdf_urls_from_crossref(obj))
        except Exception as e:
            print(f"[warn] gagal parse {p.name}: {e}")
    for p in RAW_DIR.glob("semantic_scholar_*.json"):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            api_items.extend(extract_pdf_from_semantic_scholar(obj))
        except Exception as e:
            print(f"[warn] gagal parse {p.name}: {e}")
    return api_items

def deduplicate_items(items):
    """Hapus duplikat berdasarkan pdf_url"""
    seen = set()
    out = []
    for it in items:
        url = it.get("pdf_url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(it)
    return out

def clean_api_items(api_items):
    """Buang URL yang tidak valid, IP privat, atau yang sudah error di log sebelumnya"""
    cleaned = []
    seen_error = set()
    if ERROR_LOG_PATH.exists():
        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            next(f)  # skip header
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    seen_error.add(parts[1])
    for item in api_items:
        url = item.get("pdf_url")
        if not url:
            continue
        if url in seen_error:
            print(f"[skip] URL sudah pernah gagal sebelumnya: {url}")
            continue
        if is_private_ip(url):
            print(f"[skip] URL mengarah ke IP privat: {url}")
            log_error(url, "private/local IP skipped")
            continue
        cleaned.append(item)
    return cleaned

# === MAIN PIPELINE ===
def main(dry_run=False):
    print("[1/4] Membaca file mentah dari data/raw ...")
    api_items = build_api_items_from_raw()
    print(f"    -> Ditemukan {len(api_items)} kandidat URL PDF")

    api_items = deduplicate_items(api_items)
    print(f"    -> {len(api_items)} URL unik setelah deduplikasi")

    api_items = clean_api_items(api_items)
    print(f"    -> {len(api_items)} URL valid setelah dibersihkan dari IP lokal & error sebelumnya")

    if dry_run:
        for i, it in enumerate(api_items[:20], 1):
            print(f" {i}. {it['pdf_url']}")
        return api_items

    if not api_items:
        print("❌ Tidak ada URL yang valid untuk diproses.")
        return []

    print("\n[2/4] Menjalankan loader untuk download + ekstraksi teks ...")
    saved_files = []
    for item in tqdm(api_items, desc="Processing documents"):
        url = item["pdf_url"]
        try:
            result = run_loader([item])  # kirim satu per satu agar error tidak memblokir semuanya
            if result:
                log_success(url, str(result[0]))
                saved_files.extend(result)
        except Exception as e:
            print(f"[error] Gagal memproses {url}: {e}")
            log_error(url, str(e))

    print(f"\n[3/4] Loader selesai. {len(saved_files)} file berhasil diekstrak.")
    with open(CLEANED_ITEMS_PATH, "w", encoding="utf-8") as f:
        json.dump(api_items, f, ensure_ascii=False, indent=2)
    print(f"[4/4] Daftar URL yang valid disimpan di {CLEANED_ITEMS_PATH}")

    print("\n✅ Pipeline selesai tanpa error fatal.\nHasil ekstraksi: data/raw_pdf/\nLog: data/metadata/loader_errors.csv dan loader_success.csv")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Prepare api_items, clean invalid URLs, and run loader safely.")
    parser.add_argument("--dry-run", action="store_true", help="Lihat daftar URL tanpa mendownload.")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
