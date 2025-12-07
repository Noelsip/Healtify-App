# Healtify App

## AI Health Claim Verification System

Healtify App adalah aplikasi AI Health Detector berbasis web yang memverifikasi klaim kesehatan menggunakan pendekatan **Retrieval Augmented Generation (RAG)** dengan **Large Language Models (LLMs) Gemini**.

### ✨ Fitur Utama

- 🔍 **Bilingual Search**: Pencarian otomatis dalam bahasa Indonesia dan English
- 📚 **Multi-Source Retrieval**: Mengambil paper dari 6 sumber akademik:
  - PubMed (medical journals)
  - CrossRef (scholarly articles)
  - Semantic Scholar (AI/CS papers)
  - ScienceDirect/Elsevier (scientific journals)
  - Google Books (medical textbooks)
  - Open Library (open-access books)
- 🤖 **AI-Powered Verification**: Menggunakan Gemini untuk analisis klaim
- 📊 **Evidence-Based**: Menyediakan sumber jurnal ilmiah sebagai bukti
- 🌐 **REST API**: Backend Django dengan endpoint untuk verifikasi klaim

---

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- PostgreSQL 14+ dengan pgvector extension
- Node.js 18+ (untuk frontend)
- API Keys: Gemini (wajib), NCBI, Semantic Scholar (opsional)

### Installation

#### 1. Backend Setup

```bash
cd backend
pip install -r requirements.txt

# Setup database
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run server
python manage.py runserver
```

#### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

#### 3. Training/RAG Setup

```bash
cd training
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env dengan API keys Anda
```

---

## 📖 Cara Menggunakan

### Fetch Academic Papers (Bilingual)

```bash
cd training/scripts
python fetch_sources.py
```

Atau gunakan kode Python:

```python
from fetch_sources import fetch_all_sources

# Bilingual search (otomatis translate)
fetch_all_sources(
    query="merokok menyebabkan kanker paru",
    pubmed_max=10,
    use_bilingual=True  # Query akan dicari dalam ID dan EN
)
```

### Process & Load to Database

```bash
cd training/scripts

# 1. Parse raw files dari semua sources
python process_raw.py

# 2. Extract PDF URLs dan download
python prepare_and_run_loader.py

# 3. Chunk dan embed documents
python chunk_and_embed.py

# 4. Ingest ke PostgreSQL
python ingest_chunks_to_pg.py
```

### Verify Claim

```bash
cd training/scripts
python prompt_and_verify.py --claim "Merokok menyebabkan kanker paru-paru"
```

---

## 🔧 Recent Fixes (v2.0)

**Masalah yang diperbaiki:**
1. ✅ Parser untuk Google Books, ScienceDirect, dan OpenLibrary (sebelumnya diabaikan)
2. ✅ Ekstraksi PDF URL dari semua 6 sumber (sebelumnya hanya 2)
3. ✅ Bilingual search otomatis untuk query Indonesia/English
4. ✅ Missing dependencies (requests, urllib3)

**Hasil:**
- Peningkatan signifikan jumlah paper yang diambil
- Query Indonesia sekarang menghasilkan 50-200+ paper (vs 0-5 sebelumnya)
- Coverage lengkap jurnal DAN buku akademik

📄 Lihat [FIXES_SUMMARY.md](./FIXES_SUMMARY.md) untuk detail lengkap.

---

## 📁 Project Structure

```
healtify-app/
├── backend/              # Django REST API
│   ├── api/             # Main API app
│   ├── backend_project/ # Django settings
│   └── manage.py
├── frontend/            # React + Vite frontend
│   ├── src/
│   └── package.json
├── training/            # RAG pipeline & scripts
│   ├── scripts/
│   │   ├── fetch_sources.py          # Fetch papers (bilingual)
│   │   ├── process_raw.py            # Parse all sources
│   │   ├── prepare_and_run_loader.py # Extract PDFs
│   │   ├── chunk_and_embed.py        # Create embeddings
│   │   ├── ingest_chunks_to_pg.py    # Load to database
│   │   └── prompt_and_verify.py      # Verify claims
│   ├── data/            # Data storage
│   └── requirements.txt
├── docker-compose.yml   # Docker orchestration
└── README.md

```

---

## 🔑 Environment Variables

Create `training/.env`:

```env
# Required
GEMINI_API_KEY=your_gemini_api_key_here

# Recommended (higher rate limits)
NCBI_API_KEY=your_ncbi_api_key_here
S2_API_KEY=your_semantic_scholar_api_key_here

# Optional
ELSEVIER_API_KEY=your_elsevier_api_key_here
GOOGLE_BOOKS_API_KEY=your_google_books_api_key_here
CROSSREF_MAILTO=your_email@example.com

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=healtify_db
DB_USER=postgres
DB_PASSWORD=your_password
```

---

## 🧪 Testing

Run test suite:

```bash
cd training/scripts
python test_bilingual_fetch.py
```

Tests:
- ✅ Language detection (Indonesian/English)
- ✅ Query translation
- ✅ Bilingual query generation
- ✅ Parser detection for all 6 sources
- ✅ Small API fetch (optional, requires API keys)

---

## 📊 API Endpoints

### POST /api/verify-claim/
Verify health claim dengan RAG.

**Request:**
```json
{
  "claim_text": "Merokok menyebabkan kanker paru-paru"
}
```

**Response:**
```json
{
  "label": "valid",
  "confidence": 0.95,
  "summary": "Terdapat bukti ilmiah kuat...",
  "sources": [
    {
      "title": "Smoking and Lung Cancer Risk",
      "doi": "10.1234/example",
      "relevance_score": 0.92
    }
  ]
}
```

### GET /api/claims/
List semua verified claims.

### GET /api/claims/{id}/
Detail claim tertentu.

---

## 🛠️ Tech Stack

**Backend:**
- Django 4.2
- Django REST Framework
- PostgreSQL + pgvector
- Google Gemini API

**Frontend:**
- React 18
- Vite
- TailwindCSS
- Lucide Icons

**RAG/AI:**
- LangChain
- Sentence Transformers
- FAISS / pgvector
- PyMuPDF

**Data Sources:**
- PubMed/NCBI eUtils
- CrossRef API
- Semantic Scholar API
- ScienceDirect/Elsevier API
- Google Books API
- Open Library API

---

## 📝 License

This project is licensed under the MIT License.

---

## 👥 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

---

## 🐛 Known Issues & Limitations

1. **PDF Access**: Tidak semua paper memiliki PDF open-access
2. **Rate Limits**: Bilingual mode doubles API requests
3. **Translation**: Membutuhkan GEMINI_API_KEY
4. **Database**: Requires PostgreSQL with pgvector extension

---

## 📞 Support

Jika ada masalah, cek log files:
- `training/data/metadata/ingestion_log.csv` - Fetch status
- `training/data/metadata/loader_errors.csv` - Download errors
- `training/data/metadata/verification_results.jsonl` - Verification logs

---

**Built with ❤️ for health misinformation detection** 