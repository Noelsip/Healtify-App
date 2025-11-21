"""
AI Adapter - Updated untuk menggunakan optimized verification
File: backend/api/ai_adapter.py
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
import logging
import time

logger = logging.getLogger(__name__)

# ===========================
# Path Configuration
# ===========================
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
TRAINING_DIR = PROJECT_ROOT / "training"
TRAINING_SCRIPTS_DIR = TRAINING_DIR / "scripts"

# Gunakan script yang dioptimasi
VERIFY_SCRIPT = TRAINING_SCRIPTS_DIR / "prompt_and_verify_optimized.py"

# Fallback ke script original jika optimized tidak ada
if not VERIFY_SCRIPT.exists():
    VERIFY_SCRIPT = TRAINING_SCRIPTS_DIR / "prompt_and_verify.py"
    logger.warning(f"Optimized script not found, using original: {VERIFY_SCRIPT}")

# ===========================
# Configuration
# ===========================
VERIFICATION_TIMEOUT = 60  # Reduced from 180 to 60 seconds
MAX_RETRIES = 2

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
    Mencari marker [JSON_OUTPUT] untuk hasil yang akurat.
    """
    # Strategy 1: Cari marker [JSON_OUTPUT]
    json_start = output.find("[JSON_OUTPUT]")
    if json_start != -1:
        json_text = output[json_start + len("[JSON_OUTPUT]"):].strip()
    else:
        json_text = output
    
    # Strategy 2: Parse per line untuk menemukan JSON object
    for line in json_text.split("\n"):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict) and "label" in parsed:
                logger.info("Successfully parsed JSON from output")
                return parsed
        except json.JSONDecodeError:
            continue
    
    # Strategy 3: Cari JSON object dalam teks
    import re
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(json_pattern, json_text, re.DOTALL)
    
    for match in matches:
        try:
            parsed = json.loads(match)
            if isinstance(parsed, dict) and "label" in parsed:
                return parsed
        except json.JSONDecodeError:
            continue
    
    # Strategy 4: Parse keseluruhan output
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
    
    # Gabungkan dari evidence dan references
    evidence = result.get("evidence", [])
    references = result.get("references", [])
    
    logger.debug(f"[EXTRACT_SOURCES] Evidence: {len(evidence)}, References: {len(references)}")
    
    # Buat dict untuk deduplikasi
    unique_refs = {}
    
    for ref in evidence + references:
        if not isinstance(ref, dict):
            continue
        
        safe_id = (
            ref.get("safe_id") or 
            ref.get("id") or 
            ref.get("doi") or 
            ref.get("url") or 
            ""
        )
        
        if safe_id and safe_id not in unique_refs:
            unique_refs[safe_id] = ref
    
    # Format ke struktur sources
    for safe_id, ref in unique_refs.items():
        title = (
            ref.get("title") or 
            ref.get("snippet", "")[:100] or 
            f"Reference {safe_id}"
        ).strip()
        
        doi = (ref.get("doi") or "").strip()
        url = (ref.get("url") or "").strip()
        
        # Build URL from DOI if not present
        if doi and not url:
            url = f"https://doi.org/{doi}"
        
        relevance_score = ref.get("relevance_score", 0.0)
        try:
            relevance_score = float(relevance_score)
            relevance_score = max(0.0, min(1.0, relevance_score))
        except (ValueError, TypeError):
            relevance_score = 0.0
        
        source_obj = {
            "title": title,
            "doi": doi,
            "url": url,
            "relevance_score": relevance_score
        }
        
        if source_obj["title"] or source_obj["url"] or source_obj["doi"]:
            sources.append(source_obj)
    
    logger.info(f"[EXTRACT_SOURCES] Extracted {len(sources)} sources")
    return sources

def normalize_label(label: str) -> str:
    """Normalize label ke format yang konsisten."""
    label = label.strip().lower()
    
    label_mapping = {
        "valid": "true",
        "true": "true",
        "benar": "true",
        "hoax": "false",
        "false": "false",
        "salah": "false",
        "partially_valid": "misleading",
        "partial": "misleading",
        "misleading": "misleading",
        "inconclusive": "inconclusive",
        "unsupported": "unsupported"
    }
    
    return label_mapping.get(label, "inconclusive")

# ===========================
# Main Verification Function
# ===========================

def verify_claim_with_training_script(
    claim_text: str,
    k: int = 10,
    min_relevance: float = 0.25,
    timeout: int = VERIFICATION_TIMEOUT
) -> Dict[str, Any]:
    """
    Verifikasi klaim menggunakan training script yang dioptimasi.
    
    Args:
        claim_text: Teks klaim yang akan diverifikasi
        k: Jumlah sumber teratas yang akan diambil
        min_relevance: Skor relevansi minimum
        timeout: Timeout dalam detik
    
    Returns:
        Dict dengan keys: label, summary, confidence, sources
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
    ]
    
    logger.info(f"Verifying claim: {claim_text[:50]}...")
    logger.debug(f"Command: {' '.join(cmd)}")
    logger.debug(f"Working dir: {TRAINING_SCRIPTS_DIR}")
    
    start_time = time.time()
    
    try:
        # Load environment
        env = load_training_env()
        
        # Jalankan subprocess
        result = subprocess.run(
            cmd,
            cwd=str(TRAINING_SCRIPTS_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env
        )
        
        elapsed = time.time() - start_time
        logger.info(f"Script completed in {elapsed:.1f}s with return code: {result.returncode}")
        
        # Log stderr untuk debugging (tapi jangan fail)
        if result.stderr:
            logger.debug(f"Script STDERR: {result.stderr[:500]}")
        
        # Parse JSON output
        parsed_result = parse_json_from_output(result.stdout)
        
        if not parsed_result:
            logger.error(f"Failed to parse JSON. Output: {result.stdout[:500]}")
            raise ValueError("No valid JSON output from training script")
        
        logger.info(f"Parsed result - Label: {parsed_result.get('label')}, "
                   f"Confidence: {parsed_result.get('confidence')}")
        
        return parsed_result
        
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        logger.error(f"Training script timeout after {elapsed:.1f} seconds")
        raise TimeoutError(f"Verification timeout setelah {timeout} detik")
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
    start_time = time.time()
    
    try:
        logger.info(f"Starting verification for: {claim_text[:80]}...")
        
        # Panggil training script
        raw_result = verify_claim_with_training_script(
            claim_text,
            k=10,  # Increased from 5 for better coverage
            timeout=VERIFICATION_TIMEOUT
        )
        
        # Ekstrak informasi penting
        raw_label = raw_result.get("label", "inconclusive")
        label = normalize_label(raw_label)
        summary = raw_result.get("summary", "Tidak ada ringkasan tersedia")
        confidence = float(raw_result.get("confidence", 0.0))
        
        # Clamp confidence
        confidence = max(0.0, min(1.0, confidence))
        
        # Format sources
        sources = extract_sources(raw_result)
        
        elapsed = time.time() - start_time
        logger.info(
            f"Verification complete in {elapsed:.1f}s - "
            f"Label: {label}, Confidence: {confidence:.2f}, Sources: {len(sources)}"
        )
        
        return {
            "label": label,
            "summary": summary,
            "confidence": confidence,
            "sources": sources,
            "_processing_time": elapsed,
            "_raw_label": raw_label  # Keep original for debugging
        }
        
    except TimeoutError as e:
        elapsed = time.time() - start_time
        logger.warning(f"Timeout during verification after {elapsed:.1f}s: {e}")
        return {
            "label": "inconclusive",
            "summary": "Verifikasi timeout. Silakan coba lagi dengan klaim yang lebih spesifik.",
            "confidence": 0.0,
            "sources": [],
            "_error": "timeout"
        }
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"Error in call_ai_verify after {elapsed:.1f}s: {e}", exc_info=True)
        return {
            "label": "inconclusive",
            "summary": f"Error dalam verifikasi: {str(e)}",
            "confidence": 0.0,
            "sources": [],
            "_error": str(e)
        }


# ===========================
# Direct Python Call (Alternative)
# ===========================

def call_ai_verify_direct(claim_text: str) -> Dict[str, Any]:
    """
    Alternative: Panggil verification langsung tanpa subprocess.
    Lebih cepat tapi requires proper Python path setup.
    """
    try:
        # Add training scripts to path
        if str(TRAINING_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(TRAINING_SCRIPTS_DIR))
        
        # Import and call directly
        from prompt_and_verify_optimized import verify_claim_optimized
        
        result = verify_claim_optimized(
            claim=claim_text,
            k=10,
            enable_dynamic_fetch=True,
            debug=False
        )
        
        # Normalize result
        label = normalize_label(result.get("label", "inconclusive"))
        
        return {
            "label": label,
            "summary": result.get("summary", ""),
            "confidence": float(result.get("confidence", 0.0)),
            "sources": extract_sources(result)
        }
        
    except ImportError:
        logger.warning("Direct import failed, falling back to subprocess")
        return call_ai_verify(claim_text)
    except Exception as e:
        logger.error(f"Direct call failed: {e}", exc_info=True)
        return call_ai_verify(claim_text)