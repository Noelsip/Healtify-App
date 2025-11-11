import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# ===========================
# Path Configuration
# ===========================
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
TRAINING_DIR = PROJECT_ROOT / "training"
TRAINING_SCRIPTS_DIR = TRAINING_DIR / "scripts"
VERIFY_SCRIPT = TRAINING_SCRIPTS_DIR / "prompt_and_verify.py"

# ===========================
# Helper Functions
# ===========================

def normalize_claim_text(text: str) -> str:
    """Normalisasi teks klaim untuk konsistensi."""
    return text.strip().lower()

def load_training_env() -> Dict[str, str]:
    """Load environment variables dari training/.env"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(TRAINING_SCRIPTS_DIR)
    
    dotenv_path = TRAINING_DIR / ".env"
    if dotenv_path.exists():
        try:
            from dotenv import dotenv_values
            env_vars = dotenv_values(dotenv_path)
            env.update({k: v for k, v in env_vars.items() if v is not None})
            logger.info(f"Loaded .env from: {dotenv_path}")
        except ImportError:
            logger.warning("python-dotenv not installed, skipping .env loading")
        except Exception as e:
            logger.error(f"Error loading .env: {e}")
    else:
        logger.warning(f".env not found at: {dotenv_path}")
    
    return env

def parse_json_from_output(output: str) -> Optional[Dict[str, Any]]:
    """
    Parse JSON dari output script training.
    Mencoba berbagai strategi parsing.
    """
    #  1 mencari marker [JSON_OUTPUT]
    json_start = output.find("[JSON_OUTPUT]")
    if json_start != -1:
        json_text = output[json_start + len("[JSON_OUTPUT]"):].strip()
    else:
        json_text = output
    
    # 2  Parse per line
    for line in json_text.split("\n"):
        line = line.strip()
        if not line or not (line.startswith("{") or line.startswith("[")):
            continue
        
        try:
            parsed = json.loads(line)
            logger.info("Successfully parsed JSON from output")
            return parsed
        except json.JSONDecodeError:
            continue
    
    # 3: Mencoba parse keseluruhan output
    try:
        return json.loads(json_text.strip())
    except json.JSONDecodeError:
        pass
    
    return None

def extract_sources(result: Dict[str, Any]) -> list:
    """
    Ekstrak sources dari result dengan format yang konsisten.
    """
    sources = []
    
    # Menggabungkan dari evidence dan references
    references = result.get("references", [])
    evidence = result.get("evidence", [])
    
    logger.debug(f"[EXTRACT_SOURCES] References: {len(references)}, Evidence: {len(evidence)}")
    
    # Membuat dict untuk deduplikasi berdasarkan safe_id
    unique_refs = {}
    
    for ref in references + evidence:
        if not isinstance(ref, dict):
            continue
        
        # Try multiple identifier fields
        safe_id = (
            ref.get("safe_id") or 
            ref.get("id") or 
            ref.get("doi") or 
            ref.get("url") or 
            ref.get("title", "")[:50]
        )
        
        if safe_id and safe_id not in unique_refs:
            unique_refs[safe_id] = ref
    
    logger.debug(f"[EXTRACT_SOURCES] Unique references: {len(unique_refs)}")
    
    # Format ke struktur sources
    for safe_id, ref in unique_refs.items():
        # Extract title dengan fallback
        title = (
            ref.get("title") or 
            ref.get("snippet", "")[:100] or 
            f"Reference {safe_id}"
        ).strip()
        
        # Extract DOI
        doi = (ref.get("doi") or "").strip()
        
        # Extract URL
        url = (ref.get("url") or "").strip()
        
        # Extract relevance score dengan multiple fallbacks
        relevance_score = (
            ref.get("relevance_score") or 
            ref.get("relevance") or 
            ref.get("similarity_score") or 
            0.0
        )
        
        try:
            relevance_score = float(relevance_score)
            relevance_score = max(0.0, min(1.0, relevance_score))
        except (ValueError, TypeError):
            logger.warning(f"[EXTRACT_SOURCES] Invalid relevance for {safe_id}: {relevance_score}")
            relevance_score = 0.0
        
        source_obj = {
            "title": title,
            "doi": doi,
            "url": url,
            "relevance_score": relevance_score
        }
        
        logger.debug(f"[EXTRACT_SOURCES] Source: title={title[:50]}, doi={doi}, relevance={relevance_score}")
        
        # Hanya menambahkan jika minimal ada title atau url atau doi
        if source_obj["title"] or source_obj["url"] or source_obj["doi"]:
            sources.append(source_obj)
    
    logger.info(f"[EXTRACT_SOURCES] Extracted {len(sources)} sources")
    return sources

# ===========================
# Main Verification Function
# ===========================

def verify_claim_with_training_script(
    claim_text: str,
    k: int = 5,
    min_relevance: float = 0.25
) -> Dict[str, Any]:
    """
    Verifikasi klaim menggunakan training script.
    
    Args:
        claim_text: Teks klaim yang akan diverifikasi
        k: Jumlah sumber teratas yang akan diambil
        min_relevance: Skor relevansi minimum
    
    Returns:
        Dict dengan keys: label, summary, confidence, sources
    
    Raises:
        FileNotFoundError: Jika script tidak ditemukan
        RuntimeError: Jika script gagal dijalankan
        TimeoutError: Jika verifikasi timeout
    """
    # Validasi script path
    if not VERIFY_SCRIPT.exists():
        raise FileNotFoundError(f"Script tidak ditemukan: {VERIFY_SCRIPT}")
    
    # Persiapkan command
    cmd = [
        sys.executable,
        str(VERIFY_SCRIPT),
        "--claim", claim_text,
        "--k", str(k),
        "--min-relevance", str(min_relevance),
    ]
    
    logger.info(f"Verifying claim: {claim_text[:50]}...")
    logger.debug(f"Command: {' '.join(cmd)}")
    logger.debug(f"Working dir: {TRAINING_SCRIPTS_DIR}")
    
    try:
        # Load environment
        env = load_training_env()
        
        # Jalankan subprocess
        result = subprocess.run(
            cmd,
            cwd=str(TRAINING_SCRIPTS_DIR),
            capture_output=True,
            text=True,
            timeout=180,
            env=env
        )
        
        logger.info(f"Script completed with return code: {result.returncode}")
        
        # Check return code
        if result.returncode != 0:
            logger.error(f"Script STDERR: {result.stderr}")
            logger.error(f"Script STDOUT: {result.stdout}")
            raise RuntimeError(
                f"Training script failed with code {result.returncode}. "
                f"Error: {result.stderr[:200]}"
            )
        
        # Parse JSON output
        parsed_result = parse_json_from_output(result.stdout)
        
        if not parsed_result:
            logger.error(f"Failed to parse JSON. Output: {result.stdout[:500]}")
            raise ValueError("No valid JSON output from training script")
        
        logger.info(f"Parsed result - Label: {parsed_result.get('label')}")
        
        return parsed_result
        
    except subprocess.TimeoutExpired:
        logger.error("Training script timeout after 180 seconds")
        raise TimeoutError("Verification timeout setelah 3 menit")
    except Exception as e:
        logger.error(f"Error running training script: {e}", exc_info=True)
        raise

# ===========================
# Public API
# ===========================

def call_ai_verify(claim_text: str) -> Dict[str, Any]:
    """
    Main function untuk verifikasi klaim (dipanggil dari views.py).
    
    Args:
        claim_text: Teks klaim yang akan diverifikasi
    
    Returns:
        Dict dengan keys: label, summary, confidence, sources
    """
    try:
        logger.info(f"Starting verification for: {claim_text[:80]}...")
        
        # Panggil training script
        raw_result = verify_claim_with_training_script(claim_text)
        
        # Ekstrak informasi penting
        label = raw_result.get("label", "inconclusive")
        summary = raw_result.get("summary", "Tidak ada ringkasan tersedia")
        confidence = float(raw_result.get("confidence", 0.0))
        
        # Format sources
        sources = extract_sources(raw_result)
        
        logger.info(
            f"Verification complete - Label: {label}, "
            f"Confidence: {confidence:.2f}, Sources: {len(sources)}"
        )
        
        return {
            "label": label,
            "summary": summary,
            "confidence": confidence,
            "sources": sources,
            "_raw_result": raw_result  # Keep raw result for debugging
        }
        
    except TimeoutError as e:
        logger.warning(f"Timeout during verification: {e}")
        return {
            "label": "inconclusive",
            "summary": "Verifikasi timeout. Silakan coba lagi.",
            "confidence": 0.0,
            "sources": [],
        }
    except Exception as e:
        logger.error(f"Error in call_ai_verify: {e}", exc_info=True)
        return {
            "label": "inconclusive",
            "summary": f"Error dalam verifikasi: {str(e)}",
            "confidence": 0.0,
            "sources": [],
        }