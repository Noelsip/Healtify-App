import os
import time
import json
import csv
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv
from tqdm import tqdm

# Cache module
try:
    import cache_manager as cache
    CACHE_ENABLED = True
except ImportError:
    CACHE_ENABLED = False

# Configuration
BASE = Path(__file__).parents[1]
load_dotenv(dotenv_path=BASE / ".env")

RAW_DIR = BASE / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

METADATA_DIR = BASE / "data" / "metadata"
METADATA_DIR.mkdir(parents=True, exist_ok=True)

FAILED_REQ_DIR = METADATA_DIR / "failed_requests"
FAILED_REQ_DIR.mkdir(parents=True, exist_ok=True)

LOG_PATH = METADATA_DIR / "ingestion_log.csv"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# API Keys and configuration
NCBI_API_KEY = os.getenv("NCBI_API_KEY")
S2_API_KEY = os.getenv("S2_API_KEY")
CROSSREF_MAILTO = os.getenv("CROSSREF_MAILTO")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Constants
REQUEST_TIMEOUT = 30
RETRY_DELAY = 0.2
MAX_RETRIES = 5
SEMANTIC_FETCH_BATCH_LIMIT = 8  # limit number of detail requests per run to be gentle

# Initialize Gemini client for translation (lazy loading)
_gemini_client = None


def append_ingestion_log(log_entry: dict):
    """Tambahkan entry ke ingestion log CSV file."""
    header = ["timestamp", "source", "query", "file", "status", "notes"]
    is_new_file = not LOG_PATH.exists()
    
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if is_new_file:
            writer.writeheader()
        writer.writerow(log_entry)


def create_log_entry(source: str, query: str, file_path: str = "", 
                    status: str = "", notes: str = "") -> dict:
    """Buat log entry dengan timestamp."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "query": query,
        "file": file_path,
        "status": status,
        "notes": notes
    }


def safe_filename(text: str) -> str:
    """Konversi teks menjadi nama file yang aman."""
    # replace spaces and slashes, remove other non-filename chars
    text = text.strip()
    text = text.replace(" ", "_").replace("/", "_")
    text = re.sub(r"[^A-Za-z0-9_.\-()]+", "", text)
    return text[:200]  # limit length


def _save_failed_response(source: str, identifier: str, status_code, text_preview: str):
    """Simpan informasi request gagal untuk analisa."""
    now = int(time.time())
    fname = FAILED_REQ_DIR / f"failed_{source}_{safe_filename(identifier)}_{now}.json"
    payload = {"source": source, "identifier": identifier, "status_code": status_code, "preview": text_preview}
    try:
        fname.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # best-effort, do not break pipeline
        pass

# Translation utils
def get_gemini_client():
    """Lazy load Gemini client untuk translation."""
    global _gemini_client
    if _gemini_client is None and GEMINI_API_KEY:
        try:
            from google import genai
            _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        except ImportError:
            print("[translation] Warning: google-genai not installed, translation disabled")
        except Exception as e:
            print(f"[translation] Warning: Failed to initialize Gemini client: {e}")
    return _gemini_client


def detect_language(text: str) -> str:
    """Deteksi bahasa dari teks (simple heuristic)."""
    indonesian_words = ["dan", "yang", "dengan", "untuk", "atau", "dari", "pada", "di", "ke", "ini", "itu"]
    english_words = ["and", "the", "with", "for", "or", "from", "on", "in", "to", "this", "that"]
    
    text_lower = text.lower()
    id_count = sum(1 for word in indonesian_words if f" {word} " in f" {text_lower} ")
    en_count = sum(1 for word in english_words if f" {word} " in f" {text_lower} ")
    
    return "Indonesian" if id_count > en_count else "English"


def translate_query(query: str, target_lang: str = "English") -> Optional[str]:
    """Translate query ke target language menggunakan Gemini."""
    client = get_gemini_client()
    if not client:
        print("[translation] Gemini client not available, skipping translation")
        return None
    
    # Deteksi bahasa source
    source_lang = detect_language(query)
    
    if source_lang == target_lang:
        return None
    
    prompt = (
        f"Translate the following health/medical query from {source_lang} to {target_lang}. "
        f"Preserve medical terminology and keep it concise.\n\n"
        f"Query: \"{query}\"\n\n"
        f"Output only the translated query, nothing else."
    )
    
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 128}
        )
        
        # Extract text from response
        if hasattr(response, 'text'):
            translated = response.text.strip()
        elif hasattr(response, 'candidates') and len(response.candidates) > 0:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                parts = candidate.content.parts
                if len(parts) > 0 and hasattr(parts[0], 'text'):
                    translated = parts[0].text.strip()
                else:
                    translated = None
            else:
                translated = None
        else:
            translated = None
        
        if translated and translated != query:
            print(f"[translation] {source_lang} -> {target_lang}: '{query}' -> '{translated}'")
            return translated
        
        return None
        
    except Exception as e:
        print(f"[translation] Error translating '{query}': {e}")
        return None


def generate_bilingual_queries(query: str) -> List[str]:
    """Generate query list dalam bahasa Indonesia dan English."""
    queries = [query]
    
    # Translate to English
    english_query = translate_query(query, target_lang="English")
    if english_query and english_query not in queries:
        queries.append(english_query)
    
    # Translate to Indonesian
    indonesian_query = translate_query(query, target_lang="Indonesian")
    if indonesian_query and indonesian_query not in queries:
        queries.append(indonesian_query)
    
    return queries

# PubMed (NCBI) utils
def fetch_pubmed(query: str, maximum_results: int = 5) -> Optional[str]:
    """Ambil artikel dari PubMed menggunakan eUtils API."""
    try:
        article_ids = _search_pubmed_articles(query, maximum_results)
        
        if not article_ids:
            append_ingestion_log(create_log_entry(
                "pubmed", query, "", "no results", 
                "No articles found for the given query."
            ))
            return None
        
        articles_xml = _fetch_pubmed_articles(article_ids)
        
        safe_query = safe_filename(query)
        file_path = RAW_DIR / f"pubmed_{safe_query}_{int(time.time())}.xml"
        file_path.write_text(articles_xml, encoding="utf-8")
        
        append_ingestion_log(create_log_entry(
            "pubmed", query, str(file_path), "success",
            f"{len(article_ids)} articles retrieved."
        ))
        
        return str(file_path)
        
    except Exception as e:
        append_ingestion_log(create_log_entry(
            "pubmed", query, "", "error", str(e)
        ))
        print(f"[pubmed] Error fetching from PubMed: {e}")
        return None


def _search_pubmed_articles(query: str, max_results: int) -> list:
    """Search artikel di PubMed dan return list article IDs."""
    esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        "db": "pubmed",
        "retmode": "json",
        "retmax": max_results,
        "term": query,
        "api_key": NCBI_API_KEY
    }
    
    response = requests.get(esearch_url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    
    return response.json().get("esearchresult", {}).get("idlist", [])


def _fetch_pubmed_articles(article_ids: list) -> str:
    """Fetch artikel details dari PubMed menggunakan article IDs."""
    efetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {
        "db": "pubmed",
        "retmode": "xml",
        "id": ",".join(article_ids),
        "api_key": NCBI_API_KEY
    }
    
    response = requests.get(efetch_url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    
    return response.text

# CrossRef
def fetch_crossref(query: str, rows: int = 10) -> Optional[str]:
    """Ambil artikel dari CrossRef API."""
    try:
        url = "https://api.crossref.org/works"
        headers = {"User-Agent": CROSSREF_MAILTO or "healthify/1.0"}
        params = {"query.title": query, "rows": rows}
        
        response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        safe_query = safe_filename(query)
        file_path = RAW_DIR / f"crossref_{safe_query}_{int(time.time())}.json"
        
        result = response.json()
        file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        
        items_count = len(result.get('message', {}).get('items', []))
        append_ingestion_log(create_log_entry(
            "crossref", query, str(file_path), "success",
            f"{items_count} articles retrieved."
        ))
        
        return str(file_path)
        
    except Exception as e:
        append_ingestion_log(create_log_entry(
            "crossref", query, "", "error", str(e)
        ))
        print(f"[crossref] Error fetching from CrossRef: {e}")
        return None

# Semantic Scholar
def fetch_semantic_scholar(query: str, limit: int = 5) -> Optional[str]:
    """Ambil artikel dari Semantic Scholar API."""
    try:
        paper_ids = _search_semantic_scholar_papers(query, limit)
        
        if not paper_ids:
            append_ingestion_log(create_log_entry(
                "semantic_scholar", query, "", "no results",
                "No articles found for the given query."
            ))
            return None
        
        # limit detail fetch to a safe small batch to avoid hitting rate limits
        limited_ids = paper_ids[:SEMANTIC_FETCH_BATCH_LIMIT]
        detailed_results = _fetch_semantic_scholar_details(limited_ids)
        
        file_path = _save_semantic_scholar_results(query, paper_ids, detailed_results)
        
        append_ingestion_log(create_log_entry(
            "semantic_scholar", query, str(file_path), "success",
            f"search_returned:{len(paper_ids)}, details_returned:{len(detailed_results)}"
        ))
        
        return str(file_path)
        
    except Exception as e:
        append_ingestion_log(create_log_entry(
            "semantic_scholar", query, "", "error", str(e)
        ))
        print(f"[semantic_scholar] Error fetching from Semantic Scholar: {e}")
        return None


def _search_semantic_scholar_papers(query: str, limit: int) -> list:
    """Search papers di Semantic Scholar dan return paper IDs."""
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    headers = {"User-Agent": CROSSREF_MAILTO or "healthify/1.0"}
    
    if S2_API_KEY:
        headers["x-api-key"] = S2_API_KEY
    
    params = {"query": query, "limit": limit}
    response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    
    if response.status_code != 200:
        # save failed preview
        _save_failed_response("semantic_scholar_search", query, response.status_code, response.text[:1000])
        raise Exception(f"Search failed with status {response.status_code}")
    
    search_result = response.json()
    paper_items = search_result.get("data", [])
    
    return [item.get("paperId") for item in paper_items if item.get("paperId")]


def _fetch_semantic_scholar_details(paper_ids: list) -> list:
    """Fetch detail papers dari Semantic Scholar. Improved error handling & logging."""
    base_url = "https://api.semanticscholar.org/graph/v1/paper/"
    headers = {"User-Agent": CROSSREF_MAILTO or "healthify/1.0"}

    if S2_API_KEY:
        headers["x-api-key"] = S2_API_KEY

    fields = "title,abstract,authors,year,doi,url,venue"
    detailed_results = []

    for paper_id in paper_ids:
        detail_url = base_url + paper_id
        params = {"fields": fields}

        try:
            response = _fetch_with_backoff(detail_url, headers, params)
            if not response:
                print(f"[semantic_scholar] No response object for {paper_id} (treated as network_error)")
                _save_failed_response("semantic_scholar_detail", paper_id, "network_error", "no_response")
                continue

            if response.status_code != 200:
                preview = response.text[:1000].replace("\n", " ")
                print(f"[semantic_scholar] Failed to fetch {paper_id}: status={response.status_code}; preview={preview[:400]}")
                _save_failed_response("semantic_scholar_detail", paper_id, response.status_code, preview)
                # If rate-limited, back off a bit longer
                if response.status_code == 429:
                    time.sleep(2.0)
                continue

            try:
                detail_json = response.json()
                detailed_results.append(detail_json)
            except json.JSONDecodeError as e:
                print(f"[semantic_scholar] JSON parse error for {paper_id}: {e}; response preview: {response.text[:400]}")
                _save_failed_response("semantic_scholar_detail", paper_id, "json_error", response.text[:400])
                continue

        except Exception as e:
            print(f"[semantic_scholar] Exception fetching {paper_id}: {e}")
            _save_failed_response("semantic_scholar_detail", paper_id, "exception", str(e)[:1000])
            continue

        # courteous small delay to avoid rate limiting
        time.sleep(RETRY_DELAY)

    return detailed_results


def _fetch_with_backoff(url: str, headers: dict, params: dict = None):
    """Fetch URL dengan exponential backoff untuk handle rate limiting."""
    backoff = 1.0

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)

            # Success case
            if response.status_code == 200:
                return response

            # Rate limit or server error - retry with logs
            if response.status_code in (429, 500, 502, 503, 504):
                print(f"[backoff] attempt {attempt} received {response.status_code} for {url}; retrying after {backoff}s")
                if attempt < MAX_RETRIES:
                    time.sleep(backoff)
                    backoff *= 2
                    continue

            # Other errors - return for caller to handle
            return response

        except requests.RequestException as e:
            print(f"[backoff] network exception attempt {attempt} for {url}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2
                continue
            # final failure: return None so caller treats as network error
            print(f"[backoff] final failure for {url}: {e}")
            return None

    return None


def _save_semantic_scholar_results(query: str, paper_ids: list, detailed_results: list) -> Path:
    """Save combined Semantic Scholar results ke file."""
    combined = {
        "query": query,
        "search_meta": {"total": len(paper_ids)},
        "paper_ids": paper_ids,
        "detailed_results": detailed_results
    }
    
    safe_query = safe_filename(query)
    file_path = RAW_DIR / f"semantic_scholar_{safe_query}_{int(time.time())}.json"
    
    file_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return file_path

# Elsevier / ScienceDirect
def fetch_sciencedirect(query: str, limit: int = 5) -> Optional[str]:
    """Ambil hasil pencarian dari ScienceDirect (Elsevier) API.
    Requires ELSEVIER_API_KEY in env.
    Saves JSON hasil ke RAW_DIR."""
    try:
        api_key = os.getenv("ELSEVIER_API_KEY")
        if not api_key:
            raise Exception("ELSEVIER_API_KEY not set in environment")

        url = "https://api.elsevier.com/content/search/sciencedirect"
        headers = {"X-ELS-APIKey": api_key, "Accept": "application/json", "User-Agent": "healthify/1.0"}
        params = {"query": query, "count": limit}

        response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        result = response.json()
        safe_query = safe_filename(query)
        file_path = RAW_DIR / f"sciencedirect_{safe_query}_{int(time.time())}.json"
        file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        entries = len(result.get("search-results", {}).get("entry", []))
        append_ingestion_log(create_log_entry(
            "sciencedirect", query, str(file_path), "success",
            f"{entries} entries retrieved."
        ))
        return str(file_path)

    except Exception as e:
        append_ingestion_log(create_log_entry("sciencedirect", query, "", "error", str(e)))
        print(f"[sciencedirect] Error fetching from ScienceDirect: {e}")
        return None


def fetch_elsevier_books(query: str, limit: int = 5) -> Optional[str]:
    """Optional: fetch metadata of books via Elsevier APIs (if available)."""
    try:
        return fetch_sciencedirect(query, limit=limit)
    except Exception as e:
        append_ingestion_log(create_log_entry("elsevier_books", query, "", "error", str(e)))
        print(f"[elsevier_books] Error fetching Elsevier books: {e}")
        return None

# Google Books
def fetch_google_books(query: str, limit: int = 5) -> Optional[str]:
    """Ambil buku (metadata) dari Google Books API.
    GOOGLE_BOOKS_API_KEY optional — but recommended for higher quota."""
    try:
        api_key = os.getenv("GOOGLE_BOOKS_API_KEY")
        url = "https://www.googleapis.com/books/v1/volumes"
        params = {"q": query, "maxResults": min(limit, 40)}  # Google Books max 40 per request
        if api_key:
            params["key"] = api_key

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        result = response.json()
        safe_query = safe_filename(query)
        file_path = RAW_DIR / f"google_books_{safe_query}_{int(time.time())}.json"
        file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        items = len(result.get("items", []))
        append_ingestion_log(create_log_entry(
            "google_books", query, str(file_path), "success",
            f"{items} items retrieved."
        ))
        return str(file_path)

    except Exception as e:
        append_ingestion_log(create_log_entry("google_books", query, "", "error", str(e)))
        print(f"[google_books] Error fetching from Google Books: {e}")
        return None

# Open Library
def fetch_openlibrary(query: str, limit: int = 5) -> Optional[str]:
    """Ambil buku dari Open Library (no API key required)."""
    try:
        url = "https://openlibrary.org/search.json"
        params = {"q": query, "limit": limit}
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        result = response.json()
        safe_query = safe_filename(query)
        file_path = RAW_DIR / f"openlibrary_{safe_query}_{int(time.time())}.json"
        file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        docs = len(result.get("docs", []))
        append_ingestion_log(create_log_entry(
            "openlibrary", query, str(file_path), "success",
            f"{docs} docs retrieved."
        ))
        return str(file_path)

    except Exception as e:
        append_ingestion_log(create_log_entry("openlibrary", query, "", "error", str(e)))
        print(f"[openlibrary] Error fetching from Open Library: {e}")
        return None

# NEW SOURCES (No API Key Required)
def fetch_europe_pmc(query: str, limit: int = 10) -> Optional[str]:
    """Fetch dari Europe PMC (PubMed + PMC + Preprints) - GRATIS."""
    try:
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        params = {
            "query": query,
            "format": "json",
            "pageSize": min(limit, 25),
            "resultType": "core"
        }
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        
        result = response.json()
        safe_query = safe_filename(query)
        file_path = RAW_DIR / f"europepmc_{safe_query}_{int(time.time())}.json"
        file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        
        hits = result.get("hitCount", 0)
        append_ingestion_log(create_log_entry("europepmc", query, str(file_path), "success", f"{hits} hits"))
        return str(file_path)
        
    except Exception as e:
        append_ingestion_log(create_log_entry("europepmc", query, "", "error", str(e)))
        print(f"[europepmc] Error: {e}")
        return None


def fetch_openalex(query: str, limit: int = 10) -> Optional[str]:
    """Fetch dari OpenAlex (pengganti Microsoft Academic) - GRATIS."""
    try:
        url = "https://api.openalex.org/works"
        params = {
            "search": query,
            "filter": "type:journal-article,has_abstract:true",
            "per_page": min(limit, 25),
            "select": "id,doi,title,abstract_inverted_index,authorships,publication_year,cited_by_count,open_access"
        }
        headers = {"User-Agent": "Healthify/1.0 (mailto:admin@healthify.cloud)"}
        
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        
        result = response.json()
        
        # Convert inverted index abstract to normal text
        for work in result.get("results", []):
            if work.get("abstract_inverted_index"):
                work["abstract"] = _reconstruct_openalex_abstract(work["abstract_inverted_index"])
                del work["abstract_inverted_index"]
        
        safe_query = safe_filename(query)
        file_path = RAW_DIR / f"openalex_{safe_query}_{int(time.time())}.json"
        file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        
        count = len(result.get("results", []))
        append_ingestion_log(create_log_entry("openalex", query, str(file_path), "success", f"{count} works"))
        return str(file_path)
        
    except Exception as e:
        append_ingestion_log(create_log_entry("openalex", query, "", "error", str(e)))
        print(f"[openalex] Error: {e}")
        return None


def _reconstruct_openalex_abstract(inverted_index: dict) -> str:
    """Reconstruct abstract dari OpenAlex inverted index format."""
    if not inverted_index:
        return ""
    
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    
    word_positions.sort(key=lambda x: x[0])
    return " ".join([word for _, word in word_positions])


def fetch_doaj(query: str, limit: int = 10) -> Optional[str]:
    """Fetch dari DOAJ (Directory of Open Access Journals) - GRATIS."""
    try:
        url = f"https://doaj.org/api/search/articles/{query}"
        params = {"page": 1, "pageSize": min(limit, 50)}
        
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        
        result = response.json()
        safe_query = safe_filename(query)
        file_path = RAW_DIR / f"doaj_{safe_query}_{int(time.time())}.json"
        file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        
        count = len(result.get("results", []))
        append_ingestion_log(create_log_entry("doaj", query, str(file_path), "success", f"{count} articles"))
        return str(file_path)
        
    except Exception as e:
        append_ingestion_log(create_log_entry("doaj", query, "", "error", str(e)))
        print(f"[doaj] Error: {e}")
        return None


def fetch_arxiv(query: str, limit: int = 5) -> Optional[str]:
    """Fetch dari arXiv (preprints) - GRATIS. Gunakan hati-hati untuk medical claims."""
    try:
        import xml.etree.ElementTree as ET
        
        url = "http://export.arxiv.org/api/query"
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": min(limit, 20),
            "sortBy": "relevance"
        }
        
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        
        # Parse XML response
        root = ET.fromstring(response.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        
        entries = []
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns)
            summary = entry.find("atom:summary", ns)
            link = entry.find("atom:id", ns)
            
            entries.append({
                "title": title.text.strip() if title is not None else "",
                "abstract": summary.text.strip() if summary is not None else "",
                "url": link.text.strip() if link is not None else "",
                "source": "arxiv"
            })
        
        result = {"entries": entries, "query": query}
        safe_query = safe_filename(query)
        file_path = RAW_DIR / f"arxiv_{safe_query}_{int(time.time())}.json"
        file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        
        append_ingestion_log(create_log_entry("arxiv", query, str(file_path), "success", f"{len(entries)} entries"))
        return str(file_path)
        
    except Exception as e:
        append_ingestion_log(create_log_entry("arxiv", query, "", "error", str(e)))
        print(f"[arxiv] Error: {e}")
        return None


def resolve_unpaywall(doi: str) -> Optional[Dict[str, Any]]:
    """Resolve DOI ke Open Access PDF via Unpaywall - GRATIS dengan email."""
    email = os.getenv("UNPAYWALL_EMAIL", "admin@healthify.cloud")
    
    if not doi:
        return None
    
    doi = doi.strip()
    if doi.startswith("https://doi.org/"):
        doi = doi.replace("https://doi.org/", "")
    elif doi.startswith("http://doi.org/"):
        doi = doi.replace("http://doi.org/", "")
    
    try:
        url = f"https://api.unpaywall.org/v2/{doi}"
        params = {"email": email}
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            best_oa = data.get("best_oa_location")
            
            if best_oa and best_oa.get("url_for_pdf"):
                return {
                    "doi": doi,
                    "title": data.get("title", ""),
                    "pdf_url": best_oa.get("url_for_pdf"),
                    "is_oa": data.get("is_oa", False)
                }
        return None
        
    except Exception as e:
        print(f"[unpaywall] Error resolving DOI {doi}: {e}")
        return None

# FAST PARALLEL FETCH
def fetch_sources_parallel(query: str, sources: List[str] = None, limit: int = 5, timeout: int = 20) -> Dict[str, Any]:
    """
    Fetch dari multiple sources secara PARALLEL untuk kecepatan maksimal.
    
    Args:
        query: Search query
        sources: List sources to fetch. Default: sumber cepat tanpa API key
        limit: Max results per source
        timeout: Max time keseluruhan
    
    Returns:
        Dict dengan hasil per source
    """
    # Default: ALL 7 sources for maximum coverage
    if sources is None:
        sources = [
            "pubmed",           
            "europepmc",        
            "openalex",         
            "crossref",         
            "semantic_scholar", 
            "doaj",             
            "arxiv",            
        ]
    
    fetch_funcs = {
        "pubmed": lambda q: fetch_pubmed(q, maximum_results=limit),
        "europepmc": lambda q: fetch_europe_pmc(q, limit),
        "openalex": lambda q: fetch_openalex(q, limit),
        "crossref": lambda q: fetch_crossref(q, rows=limit),
        "semantic_scholar": lambda q: fetch_semantic_scholar(q, limit=limit),
        "doaj": lambda q: fetch_doaj(q, limit),
        "arxiv": lambda q: fetch_arxiv(q, limit),
    }
    
    results = {}
    sources_to_fetch = []
    
    # Check cache first for each source
    for source in sources:
        if source in fetch_funcs:
            if CACHE_ENABLED:
                cached = cache.get_cached_fetch(query, source)
                if cached:
                    results[source] = cached
                    print(f"  ✓ {source}: cached")
                    continue
            sources_to_fetch.append(source)
    
    # Fetch only non-cached sources
    if sources_to_fetch:
        with ThreadPoolExecutor(max_workers=7) as executor:
            future_to_source = {}
            
            for source in sources_to_fetch:
                future = executor.submit(fetch_funcs[source], query)
                future_to_source[future] = source
            
            for future in as_completed(future_to_source, timeout=timeout):
                source = future_to_source[future]
                try:
                    result = future.result(timeout=5)
                    if result:
                        results[source] = result
                        # Cache the result
                        if CACHE_ENABLED:
                            cache.cache_fetch(query, source, result)
                        print(f"  ✓ {source}: fetched")
                except Exception as e:
                    print(f"  ✗ {source}: {str(e)[:50]}")
    
    return results



# Orchestration
def fetch_all_sources(query: str, pubmed_max: int = 5, crossref_rows: int = 5, 
                     semantic_limit: int = 5, scidir_limit: int = 5, 
                     google_limit: int = 5, openlib_limit: int = 5,
                     delay_between_sources: float = 0.5, use_bilingual: bool = True,
                     use_parallel: bool = True) -> dict:
    """Fetch dari semua sumber untuk satu query.
    
    Sumber yang digunakan:
    - PubMed, CrossRef, Semantic Scholar (existing)
    - Europe PMC, OpenAlex, DOAJ (NEW - gratis, tanpa API key)
    - ScienceDirect, Google Books, Open Library (existing)
       
    Args:
        query: Query utama dalam bahasa apapun
        use_bilingual: Jika True, generate query dalam bahasa Indonesia dan English
        use_parallel: Jika True, fetch secara parallel (LEBIH CEPAT)
    """
    results = {}
    
    # Generate bilingual queries jika diminta
    queries_to_fetch = [query]
    if use_bilingual:
        print(f"\n[BILINGUAL] Generating bilingual queries for: {query}")
        bilingual_queries = generate_bilingual_queries(query)
        queries_to_fetch = bilingual_queries
        print(f"[BILINGUAL] Will search with {len(queries_to_fetch)} queries: {queries_to_fetch}")
    
    # Fetch dari semua sources untuk setiap query
    for idx, q in enumerate(queries_to_fetch):
        print(f"\n{'='*60}")
        print(f"Query {idx+1}/{len(queries_to_fetch)}: {q}")
        print(f"{'='*60}")
        
        if use_parallel:
            # ===== FAST PARALLEL MODE =====
            print("[PARALLEL] Fetching from 5 sources simultaneously...")
            parallel_results = fetch_sources_parallel(
                q, 
                sources=["europepmc", "openalex", "doaj", "crossref", "pubmed"],
                limit=5,
                timeout=20
            )
            for source, result in parallel_results.items():
                results[f'{source}_{idx}'] = result
            
            time.sleep(delay_between_sources)
            
            # Fetch additional sources sequentially
            print(f"Fetching from Semantic Scholar: {q}")
            scholar_result = fetch_semantic_scholar(q, limit=semantic_limit)
            if scholar_result:
                results[f'semantic_scholar_{idx}'] = scholar_result
            
        else:
            # SEQUENTIAL MODE 
            print(f"Fetching from PubMed: {q}")
            pubmed_result = fetch_pubmed(q, maximum_results=pubmed_max)
            if pubmed_result:
                results[f'pubmed_{idx}'] = pubmed_result
            time.sleep(delay_between_sources)

            print(f"Fetching from CrossRef: {q}")
            crossref_result = fetch_crossref(q, rows=crossref_rows)
            if crossref_result:
                results[f'crossref_{idx}'] = crossref_result
            time.sleep(delay_between_sources)
            
            print(f"Fetching from Europe PMC: {q}")
            epmc_result = fetch_europe_pmc(q, limit=pubmed_max)
            if epmc_result:
                results[f'europepmc_{idx}'] = epmc_result
            time.sleep(delay_between_sources)
            
            print(f"Fetching from OpenAlex: {q}")
            openalex_result = fetch_openalex(q, limit=crossref_rows)
            if openalex_result:
                results[f'openalex_{idx}'] = openalex_result
            time.sleep(delay_between_sources)
            
            print(f"Fetching from DOAJ: {q}")
            doaj_result = fetch_doaj(q, limit=crossref_rows)
            if doaj_result:
                results[f'doaj_{idx}'] = doaj_result
            time.sleep(delay_between_sources)

            print(f"Fetching from Semantic Scholar: {q}")
            scholar_result = fetch_semantic_scholar(q, limit=semantic_limit)
            if scholar_result:
                results[f'semantic_scholar_{idx}'] = scholar_result
            time.sleep(delay_between_sources)

            print(f"Fetching from ScienceDirect (Elsevier): {q}")
            scidir_result = fetch_sciencedirect(q, limit=scidir_limit)
            if scidir_result:
                results[f'sciencedirect_{idx}'] = scidir_result
            time.sleep(delay_between_sources)

            print(f"Fetching from Google Books: {q}")
            books_result = fetch_google_books(q, limit=google_limit)
            if books_result:
                results[f'google_books_{idx}'] = books_result
            time.sleep(delay_between_sources)

            print(f"Fetching from Open Library: {q}")
            openlib_result = fetch_openlibrary(q, limit=openlib_limit)
            if openlib_result:
                results[f'openlibrary_{idx}'] = openlib_result
            time.sleep(delay_between_sources)

    print(f"\n{'='*60}")
    print(f"Fetching completed for all {len(queries_to_fetch)} queries")
    print(f"Total results: {len(results)} files")
    print(f"Sources used: {list(set([k.rsplit('_', 1)[0] for k in results.keys()]))}")
    print(f"{'='*60}\n")

    return results


if __name__ == "__main__":
    # Sample queries untuk testing
    sample_queries = [
        "covid-19",
        "machine learning in healthcare",
        "causes of diabetes",
        "mental health and exercise",
        "advancements in cancer treatment"
    ]

    # Fetch semua queries dengan progress bar
    for query in tqdm(sample_queries, desc="Fetching queries"):
        fetch_all_sources(query)
        time.sleep(1)  
