import os
import time
import json
import csv
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv
from tqdm import tqdm

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

# Constants
REQUEST_TIMEOUT = 30
RETRY_DELAY = 0.2
MAX_RETRIES = 5
SEMANTIC_FETCH_BATCH_LIMIT = 8  # limit number of detail requests per run to be gentle


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


# -------------------
# PubMed (NCBI) utils
# -------------------

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


# -------------------
# CrossRef
# -------------------

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


# -------------------
# Semantic Scholar
# -------------------

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


# -------------------
# Elsevier / ScienceDirect
# -------------------

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


# -------------------
# Google Books
# -------------------

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


# -------------------
# Open Library
# -------------------

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


# -------------------
# Orchestration
# -------------------

def fetch_all_sources(query: str, pubmed_max: int = 5, crossref_rows: int = 5, 
                     semantic_limit: int = 5, scidir_limit: int = 5, 
                     google_limit: int = 5, openlib_limit: int = 5,
                     delay_between_sources: float = 1.0) -> dict:
    """Fetch dari semua sumber untuk satu query (PubMed, CrossRef, Semantic Scholar,
       ScienceDirect, Google Books, Open Library)."""
    results = {}

    print(f"Fetching from PubMed: {query}")
    results['pubmed'] = fetch_pubmed(query, maximum_results=pubmed_max)
    time.sleep(delay_between_sources)

    print(f"Fetching from CrossRef: {query}")
    results['crossref'] = fetch_crossref(query, rows=crossref_rows)
    time.sleep(delay_between_sources)

    print(f"Fetching from Semantic Scholar: {query}")
    results['semantic_scholar'] = fetch_semantic_scholar(query, limit=semantic_limit)
    time.sleep(delay_between_sources)

    print(f"Fetching from ScienceDirect (Elsevier): {query}")
    results['sciencedirect'] = fetch_sciencedirect(query, limit=scidir_limit)
    time.sleep(delay_between_sources)

    print(f"Fetching from Google Books: {query}")
    results['google_books'] = fetch_google_books(query, limit=google_limit)
    time.sleep(delay_between_sources)

    print(f"Fetching from Open Library: {query}")
    results['openlibrary'] = fetch_openlibrary(query, limit=openlib_limit)
    time.sleep(delay_between_sources)

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
        time.sleep(1)  # Delay antar query
