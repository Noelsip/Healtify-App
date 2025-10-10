import argparse
import pathlib
import json
import sys
from datetime import datetime, timezone
from tqdm import tqdm
import fitz

# membuat folder otomatis jika belum ada
def ensure_folder_exists(folder_path: pathlib.Path) -> None:
    folder_path.mkdir(parents=True, exist_ok=True)

# mengekstrak teks tiap halaman PDF
def extract_text_pages_from_pdf(pdf_path: pathlib.Path):
    if isinstance(pdf_path, (list, tuple)):
        raise TypeError(
            "extract_text_pages_from_pdf menerima list/tuple. "
            "Pastikan memanggil fungsi per-file, misal: extract_text_pages_from_pdf(pdf_path). "
            f"Contoh isi yang salah: {repr(pdf_path)}"
        )

    # pastikan tipe Path
    if not isinstance(pdf_path, pathlib.Path):
        raise TypeError(f"Argument pdf_path harus pathlib.Path, dapatkan {type(pdf_path)}: {repr(pdf_path)}")

    # pastikan file ada
    if not pdf_path.exists():
        raise FileNotFoundError(f"File PDF tidak ditemukan: {pdf_path}")

    # buka dokumen dan ekstrak tiap halaman
    doc = fitz.open(str(pdf_path))
    pages = []
    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        page_text = page.get_text("text")
        pages.append(page_text)
    doc.close()
    return pages

def parse_cli_arguments():
    parser = argparse.ArgumentParser(description="Ekstrak teks per halaman dari file PDF.")
    parser.add_argument(
        "--input-folder",
        type=str,
        default="data/pdf",
        help="Folder sumber PDF.",
    )
    parser.add_argument(
        "--output-folder",
        type=str,
        default="data/raw_pdf",
        help="Folder tujuan untuk menyimpan hasil ekstraksi.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite file yang sudah ada.",
    )
    parser.add_argument(
        "--min-pages",
        type=int,
        default=0,
        help="Minimum jumlah halaman PDF untuk diproses.",
    )
    return parser.parse_args()

def main():
    args = parse_cli_arguments()

    # menentukan folder
    base_folder = pathlib.Path(__file__).parents[1]
    input_folder = (base_folder / args.input_folder).resolve()
    output_folder = (base_folder / args.output_folder).resolve()

    # memastikan folder output ada
    ensure_folder_exists(output_folder)

    if not input_folder.exists():
        print(f"Folder input '{input_folder}' tidak ditemukan.", file=sys.stderr)
        sys.exit(1)

    # mendapatkan semua file PDF di folder input
    pdf_files = sorted([p for p in input_folder.glob("*.pdf") if p.is_file()])

    if len(pdf_files) == 0:
        print(f"Tidak ada file PDF ditemukan di '{input_folder}'.", file=sys.stderr)
        return
    
    for pdf_path in tqdm(pdf_files, desc="Memproses PDF", unit="file"):
        try:
            # ukuran untuk metadata
            file_size_bytes = pdf_path.stat().st_size

            pages_text = extract_text_pages_from_pdf(pdf_path)

            if len(pages_text) < args.min_pages:
                print(f"Melewati '{pdf_path.name}' karena hanya memiliki {len(pages_text)} halaman.")
                continue

            # menyimpan halaman ke file teks terpisah
            for page_index, pages_text in enumerate(pages_text, start=1):
                out_name = f"{pdf_path.stem}_page_{page_index:03d}.txt"
                out_path = output_folder / out_name

                if out_path.exists() and not args.overwrite:
                    print(f"Melewati '{out_path.name}' karena sudah ada.")
                    continue

                # menulis halaman dengan encoding utf-8
                out_path.write_text(pages_text, encoding="utf-8")

            # menyimpan metadata
            metadata_obj = {
                "pdf_file": pdf_path.name,
                "pdf_stem": pdf_path.stem,
                "n_pages": len(pages_text),
                "file_size_bytes": file_size_bytes,
                "extracted_at": datetime.now(timezone.utc).isoformat() + "Z"
            }

            meta_out_path = output_folder / f"{pdf_path.stem}_meta.json"
            meta_out_path.write_text(json.dumps(metadata_obj, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"Gagal memproses '{pdf_path.name}': {e}", file=sys.stderr)
            continue
    
    total_pages = len(list(output_folder.glob("*.txt")))
    total_meta = len(list(output_folder.glob("*_meta.json")))
    print(f"Selesai! Total halaman diekstrak: {total_pages}, total metadata: {total_meta}")
    print(f"Hasil disimpan di '{output_folder}'")

if __name__ == "__main__":
    main()