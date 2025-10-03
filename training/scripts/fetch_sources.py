import os
import time
import json
import pathlib
import csv
import requests
from dotenv import load_dotenv
from tqdm import tqdm
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).parents[1]
load_dotenv(dotenv_path=BASE / ".env")

RAW_DIR = BASE / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = BASE / "data" / "metadata" / "ingestion_log.csv"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

NCBI_API_KEY = os.getenv("NCBI_API_KEY")
S2_API_KEY = os.getenv("S2_API_KEY")
CROSSREF_MAILTO = os.getenv("CROSSREF_MAILTO")

# menambahkan baris ke ingestion
def append_log(row):
    header = ["timestamp","source", "query", "file", "status", "notes"]
    is_new = not LOG_PATH.exists()
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if is_new:
            writer.writeheader()
        writer.writerow(row)

# pengambilan data dari pubmed
def fetch_pubmed(query: str, maximum_results: int = 5) -> str | None:
    try:
        # endpoint esearch
        esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        esearch_params = {
            "db" : "pubmed",
            "retmode" : "json",
            "retmax" : maximum_results,
            "term" : query,
            "api_key" : NCBI_API_KEY
        }

        # melakukan request ke esearch
        esearch_response = requests.get(esearch_url, params=esearch_params, timeout=30)
        esearch_response.raise_for_status()
        
        # mengambil id artikel
        article_ids = esearch_response.json().get("esearchresult", {}).get("idlist", [])

        # jika hasil tidak ada
        if not article_ids:
            append_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "pubmed",
                "query": query,
                "file": "",
                "status": "no results",
                "notes": "No articles found for the given query."
            })
            return None
        
        # endpoint efetch
        efetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        efetch_params = {
            "db" : "pubmed",
            "retmode" : "xml",
            "id" : ",".join(article_ids),
            "api_key" : NCBI_API_KEY
        }

        # melakukan request ke efetch
        efetch_response = requests.get(efetch_url, params=efetch_params, timeout=30)
        efetch_response.raise_for_status()

        safe_query_filename = query.replace(" ", "_").replace("/", "_")
        save_file_path = RAW_DIR / f"pubmed_{safe_query_filename}_{int(time.time())}.xml"

        save_file_path.write_text(efetch_response.text, encoding="utf-8")
        
        # menulis log ingestion
        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "pubmed",
            "query": query,
            "file": str(save_file_path),
            "status": "success",
            "notes": f"{len(article_ids)} articles retrieved."
        })

        return str(save_file_path)
    except Exception as e:
        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "pubmed",
            "query": query,
            "file": "",
            "status": "error",
            "notes": str(e)
        })
        print(f"Error fetching from PubMed: {e}")
        return None
    
# pengambilan data dari crossref
def fetch_crossref(query: str, rows: int = 10):
    try:
        crossreff_url = "https://api.crossref.org/works"
        crossreff_headers = {"User-Agent": CROSSREF_MAILTO}
        crossreff_params = {"query.title": query, "rows": rows}

        crossreff_response = requests.get(crossreff_url, headers=crossreff_headers, params=crossreff_params, timeout=30)
        crossreff_response.raise_for_status()

        crossreff_result = crossreff_response.json()
        file_name = RAW_DIR / f"crossref_{query.replace(' ', '_')}_{int(time.time())}.json"
        file_name.write_text(json.dumps(crossreff_result, ensure_ascii=False, indent=2), encoding="utf-8")

        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "crossref",
            "query": query,
            "file": str(file_name),
            "status": "success",
            "notes": f"{len(crossreff_result.get('message', {}).get('items', []))} articles retrieved."
        })
        return str(file_name)
    except Exception as e:
        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "crossref",
            "query": query,
            "file": "",
            "status": "error",
            "notes": str(e)
        })
        print(f"Error fetching from CrossRef: {e}")
        return None
    
# pengambilan data dari semantic scholar
def fetch_semantic_scholar(query: str, limit: int = 5) -> str | None:
    base_search_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    base_paper_url = "https://api.semanticscholar.org/graph/v1/paper/"
    s2_headers = { "User-Agent": CROSSREF_MAILTO or "healthify/1.0" }
    if S2_API_KEY:
        s2_headers["x-api-key"] = S2_API_KEY

    # melakukan pencarian tanpa fields
    search_params = { "query": query, "limit": limit }
    try:
        search_response = requests.get(base_search_url, headers=s2_headers, params=search_params, timeout=30)
    except requests.RequestException as rexc:
        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "semantic_scholar",
            "query": query,
            "file": "",
            "status": "error",
            "notes": f"Search request error: {str(rexc)}"
        })
        print(f"Error fetching from Semantic Scholar (search): {rexc}")
        return None
    
    # jika status bukan 200
    if search_response.status_code != 200:
        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "semantic_scholar",
            "query": query,
            "file": "",
            "status": f"search_error_{search_response.status_code}",
            "notes": (search_response.text[:2000] or "")
        })
        print(f"Error fetching from Semantic Scholar (search): Status {search_response.status_code}")
        return None
    
    # mengambil id paper
    try:
        search_json = search_response.json()
        paper_items = search_json.get("data", [])
        paper_ids = [item.get("paperId") for item in paper_items if item.get("paperId")]
    except Exception as jexc:
        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "semantic_scholar",
            "query": query,
            "file": "",
            "status": "parse_error_search",
            "notes": f"Search JSON parse error: {str(jexc)}"
        })
        print(f"Error parsing Semantic Scholar search response: {jexc}")
        return None
    
    # jika tidak ada id paper
    if not paper_ids:
        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "semantic_scholar",
            "query": query,
            "file": "",
            "status": "no results",
            "notes": "No articles found for the given query."
        })
        return None
    
    # mengambil detail paper dengan fields lengkap
    detail_fields = "title,abstract,authors,year,doi,url,venue"
    detailed_results = []

    def fetch_with_backoff(url, headers, params=None, max_retries=5):
        backoff = 1.0
        for attempt in range(1, max_retries + 1):
            try:
                r = requests.get(url, headers=headers, params=params, timeout=30)
            except requests.RequestException as e:
                # connection/timeout error — treat as retryable
                last_exc = e
                r = None
            else:
                last_exc = None

            if r is not None and r.status_code == 200:
                return r
            # handle rate limit or 5xx -> retry
            status = r.status_code if r is not None else None
            if status == 429 or (status is not None and 500 <= status < 600) or last_exc:
                # wait then retry
                time.sleep(backoff)
                backoff *= 2  # exponential backoff
                continue
            # non-retryable or other status -> return r for caller to inspect
            return r
        # if exhausted retries, return last response or raise last exception info
        return r if r is not None else None

    # iterate paper ids and fetch details (be polite with short sleeps)
    for pid in paper_ids:
        detail_url = base_paper_url + pid
        params = {"fields": detail_fields}
        resp = fetch_with_backoff(detail_url, headers=s2_headers, params=params, max_retries=5)
        if resp is None:
            # worst-case network error after retries
            append_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "semantic_scholar",
                "query": query,
                "file": "",
                "status": "detail_exception",
                "notes": f"Failed to fetch detail for {pid} after retries"
            })
            continue
        if resp.status_code == 200:
            try:
                detail_json = resp.json()
                detailed_results.append(detail_json)
            except Exception as jexc:
                append_log({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "semantic_scholar",
                    "query": query,
                    "file": "",
                    "status": "parse_error_detail",
                    "notes": str(jexc)
                })
                continue
        else:
            # log non-200 detail response (including 403/404/429)
            append_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "semantic_scholar",
                "query": query,
                "file": "",
                "status": f"detail_error_{resp.status_code}",
                "notes": (resp.text[:1000] or "")
            })
        # small polite delay to avoid hitting rate limits
        time.sleep(0.2)

    # --- Step C: save combined raw result ---
    combined = {
        "query": query,
        "search_meta": {"total": search_json.get("total"), "offset": search_json.get("offset")},
        "paper_ids": paper_ids,
        "detailed_results": detailed_results
    }
    safe_query_filename = query.replace("/", "_").replace(" ", "_")
    saved_file_path = RAW_DIR / f"semantic_scholar_{safe_query_filename}_{int(time.time())}.json"
    saved_file_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

    # log success (note: may have partial details if some detail calls failed)
    append_log({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "semantic_scholar",
        "query": query,
        "file": str(saved_file_path),
        "status": "success",
        "notes": f"search_returned:{len(paper_ids)}, details_returned:{len(detailed_results)}"
    })

    return str(saved_file_path)
 
    
if __name__ == "__main__":
    # contoh query yang ingin diambil
    list_of_queries = [
        "covid-19",
        "machine learning in healthcare",
        "causes of diabetes",
        "mental health and exercise",
    ]

    # query dengan progress bar
    for query in tqdm(list_of_queries):
        fetch_pubmed(query, maximum_results=5)
        time.sleep(1)
        fetch_crossref(query, rows=5)
        time.sleep(1)
        fetch_semantic_scholar(query, limit=5)
        time.sleep(1)