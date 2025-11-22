import os
import sys
import json
import subprocess
import hashlib
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# ===========================
# Path Configuration
# ===========================
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
TRAINING_DIR = PROJECT_ROOT / "training"
TRAINING_SCRIPTS_DIR = TRAINING_DIR / "scripts"

VERIFY_SCRIPT = TRAINING_SCRIPTS_DIR / "prompt_and_verify_optimized.py"

if not VERIFY_SCRIPT.exists():
    error_msg = (
        f"CRITICAL: Optimized script not found at {VERIFY_SCRIPT}\n"
        f"   This will cause slow verification (60+ seconds)\n"
        f"   Please ensure prompt_and_verify_optimized.py exists"
    )
    logger.error(error_msg)
    # Try fallback to original
    VERIFY_SCRIPT = TRAINING_SCRIPTS_DIR / "prompt_and_verify.py"
    if not VERIFY_SCRIPT.exists():
        raise FileNotFoundError(error_msg)
    else:
        logger.warning(f"  Using ORIGINAL script (slower): {VERIFY_SCRIPT.name}")
else:
    logger.info(f"✅ Using optimized verification script: {VERIFY_SCRIPT.name}")

# ===========================
# Configuration
# ===========================
VERIFICATION_TIMEOUT = 90  
MAX_RETRIES = 2
SIMPLE_CLAIM_WORD_THRESHOLD = 20  

# Global module cache for direct import
_optimized_module = None
_original_module = None

# ===========================
# Helper Functions
# ===========================

def normalize_claim_text(text: str) -> str:
    """Normalisasi teks klaim untuk konsistensi."""
    if not text:
        return ""
    return text.strip().lower()

def normalize_ai_response(ai_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize AI response untuk konsistensi dengan backend model.
    
    - Map label ke format backend
    - Normalize confidence (0.0-1.0)
    - Normalize sources structure
    """
    # Map label
    raw_label = ai_result.get('label', 'inconclusive')
    normalized_label = map_training_label_to_backend(raw_label)
    
    # Normalize confidence
    confidence = float(ai_result.get('confidence', 0.0))
    confidence = max(0.0, min(1.0, confidence))  # Clamp to [0, 1]
    
    # Normalize sources
    sources = ai_result.get('sources', [])
    if not isinstance(sources, list):
        sources = []
    
    # Ensure each source has required fields
    normalized_sources = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        
        normalized_sources.append({
            'title': src.get('title', 'Unknown'),
            'doi': src.get('doi', ''),
            'url': src.get('url', ''),
            'relevance_score': float(src.get('relevance', 0) or src.get('relevance_score', 0)),
            'excerpt': src.get('snippet', '')[:500] if src.get('snippet') else src.get('text', '')[:500],
            'source_type': src.get('source_type', 'journal'),
        })
    
    return {
        'label': normalized_label,
        'confidence': confidence,
        'summary': ai_result.get('summary', ''),
        'sources': normalized_sources,
        '_original_label': raw_label,  # Keep for debugging
        '_processing_time': ai_result.get('_processing_time', 0),
        '_method': ai_result.get('_method', 'unknown')
    }

def load_training_env() -> Dict[str, str]:
    """
    Load environment variables dari training/.env dengan validation.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(TRAINING_SCRIPTS_DIR)
    
    dotenv_path = TRAINING_DIR / ".env"
    
    if dotenv_path.exists():
        try:
            from dotenv import dotenv_values
            env_vars = dotenv_values(dotenv_path)
            
            # ✅ Validate critical keys
            critical_keys = ["GEMINI_API_KEY", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"]
            missing_keys = [k for k in critical_keys if not env_vars.get(k)]
            
            if missing_keys:
                logger.warning(f"⚠️  Missing keys in training/.env: {missing_keys}")
            else:
                logger.debug("✅ All critical env keys present")
            
            # Update environment
            env.update({k: v for k, v in env_vars.items() if v is not None})
            
            logger.info(f"✅ Loaded .env from: {dotenv_path}")
            logger.debug(f"   Keys loaded: {list(env_vars.keys())}")
            
        except ImportError:
            logger.error("❌ python-dotenv not installed! Cannot load .env file")
        except Exception as e:
            logger.error(f"❌ Error loading .env: {e}")
    else:
        logger.warning(f"⚠️  .env not found at: {dotenv_path}")
        logger.info("   Using environment variables from system")
    
    return env

def parse_json_from_output(output: str) -> Optional[Dict[str, Any]]:
    """
    Parse JSON dari output dengan multiple fallback strategies.
    """
    if not output or not isinstance(output, str):
        return None
    
    output = output.strip()
    
    # Strategy 1: Direct JSON parse
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        pass
    
    # Strategy 2: Find JSON block in output
    try:
        # Find last JSON object (between { and })
        start_idx = output.rfind('{')
        end_idx = output.rfind('}')
        
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = output[start_idx:end_idx + 1]
            return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        pass
    
    # Strategy 3: Find JSON array
    try:
        start_idx = output.rfind('[')
        end_idx = output.rfind(']')
        
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = output[start_idx:end_idx + 1]
            parsed = json.loads(json_str)
            # If it's a list with one dict, return that dict
            if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
                return parsed[0]
            return {"raw_data": parsed}
    except (json.JSONDecodeError, ValueError):
        pass
    
    logger.warning("Failed to parse JSON from output")
    return None

def map_training_label_to_backend(training_label: str) -> str:
    """
    Map label dari training script ke format backend (4 kategori).
    
    Training labels: 'true', 'false', 'misleading', 'inconclusive', 'supported', 'refuted', etc.
    Backend labels: 'valid', 'hoax', 'uncertain', 'unverified'
    """
    label_lower = training_label.lower().strip()
    
    # Mapping comprehensive
    label_mapping = {
        # TRUE variants → VALID
        'true': 'valid',
        'supported': 'valid',
        'valid': 'valid',
        'verified': 'valid',
        'benar': 'valid',
        
        # FALSE variants → HOAX
        'false': 'hoax',
        'refuted': 'hoax',
        'hoax': 'hoax',
        'debunked': 'hoax',
        'salah': 'hoax',
        
        # PARTIAL/MISLEADING variants → UNCERTAIN
        'partially_supported': 'uncertain',
        'partially_valid': 'uncertain',
        'misleading': 'uncertain',
        'partial': 'uncertain',
        'mixed': 'uncertain',
        'sebagian': 'uncertain',
        'conditional': 'uncertain',
        
        # INCONCLUSIVE variants → UNVERIFIED
        'inconclusive': 'unverified',
        'unverified': 'unverified',
        'unclear': 'unverified',
        'insufficient': 'unverified',
        'no_evidence': 'unverified',
        'tidak_jelas': 'unverified',
    }
    
    return label_mapping.get(label_lower, 'unverified')

def extract_sources(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Ekstrak sources dari result dictionary dengan normalisasi.
    """
    sources = []
    seen_identifiers = set()
    
    # Try different keys
    sources_raw = (
        result.get("sources") or 
        result.get("neighbors") or 
        result.get("evidence") or 
        result.get("references") or
        []
    )
    
    if not isinstance(sources_raw, list):
        logger.warning(f"sources is not a list: {type(sources_raw)}")
        return []
    
    for src in sources_raw:
        if not isinstance(src, dict):
            continue
        
        # Extract identifier
        doi = (src.get("doi") or "").strip()
        url = (src.get("url") or "").strip()
        safe_id = (src.get("safe_id") or "").strip()

        # Create unique key
        identifier = doi if doi else url

        # Skip duplicates
        if not identifier or identifier in seen_identifiers:
            continue

        seen_identifiers.add(identifier)
        
        # Normalize source structure
        source_obj = {
            "title": src.get("title") or src.get("source_file") or src.get("safe_id") or "Unknown",
            "doi": doi,
            "url": url or (f"https://doi.org/{doi}" if doi else ""),
            "relevance_score": float(src.get("relevance_score", 0) or src.get("relevance", 0) or 0),
            "excerpt": (src.get("text") or src.get("snippet") or "")[:500],
            "source_type": src.get("source_type", "journal")
        }
        
        sources.append(source_obj)
    
    # Sort by relevance
    sources.sort(key=lambda x: x.get("relevance", 0), reverse=True)
    
    # Limit to top 10
    return sources[:10]

def normalize_label(label: str) -> str:
    """
    Normalisasi label verifikasi ke format standar.
    """
    if not label:
        return "inconclusive"
    
    label_lower = label.lower().strip()
    
    # Map variations to standard labels
    label_map = {
        "supported": "supported",
        "true": "supported",
        "verified": "supported",
        "benar": "supported",
        
        "refuted": "refuted",
        "false": "refuted",
        "debunked": "refuted",
        "salah": "refuted",
        
        "partially_supported": "partially_supported",
        "partial": "partially_supported",
        "mixed": "partially_supported",
        "sebagian": "partially_supported",
        
        "inconclusive": "inconclusive",
        "unclear": "inconclusive",
        "insufficient": "inconclusive",
        "tidak_jelas": "inconclusive",
    }
    
    return label_map.get(label_lower, "inconclusive")


# ===========================
# Direct Import Methods (FASTEST)
# ===========================

def get_optimized_module():
    """
    Lazy import optimized module untuk direct call (eliminasi subprocess overhead).
    """
    global _optimized_module
    
    if _optimized_module is None:
        # Add to path if not already
        if str(TRAINING_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(TRAINING_SCRIPTS_DIR))
        
        try:
            # Try import optimized
            import prompt_and_verify_optimized as pvo
            _optimized_module = pvo
            logger.info("✅ Loaded optimized module directly (no subprocess)")
        except ImportError as e:
            logger.error(f"❌ Failed to import optimized module: {e}")
            
            # Try fallback to original
            try:
                import prompt_and_verify as pv
                _optimized_module = pv
                logger.warning("⚠️  Using ORIGINAL module (slower)")
            except ImportError as e2:
                logger.error(f"❌ Failed to import original module: {e2}")
                raise ImportError(f"Cannot import verification module: {e}, {e2}")
    
    return _optimized_module

def call_ai_verify_direct_optimized(claim_text: str) -> Dict[str, Any]:
    """
    Args:
        claim_text: Claim text to verify
        
    Returns:
        Verification result dictionary
    """
    start_time = time.time()
    
    try:
        claim_len = len(claim_text.split())
        is_simple = claim_len < SIMPLE_CLAIM_WORD_THRESHOLD
        
        logger.info(
            f"🚀 Direct verification (no subprocess): {claim_text[:80]}... "
            f"(words: {claim_len}, simple: {is_simple})"
        )
        
        # Get optimized module
        pvo = get_optimized_module()
        
        # Check which function is available
        if hasattr(pvo, 'verify_claim_v2'):
            # Optimized script
            logger.debug("Using verify_claim_v2 (optimized)")
            raw_result = pvo.verify_claim_v2(
                claim=claim_text,
                k=10,
                enable_fetch=not is_simple,  # Only fetch for complex claims
                debug=False
            )
        elif hasattr(pvo, 'verify_claim_local'):
            # Original script
            logger.debug("Using verify_claim_local (original)")
            raw_result = pvo.verify_claim_local(
                claim=claim_text,
                k=10,
                enable_expansion=not is_simple,  # Skip expansion for simple claims
                force_dynamic_fetch=False,
                debug_retrieval=False
            )
        else:
            raise AttributeError("No verify function found in module")
        
        # Extract and normalize data
        label = normalize_label(raw_result.get("label", "inconclusive"))
        summary = raw_result.get("summary", "")
        confidence = float(raw_result.get("confidence", 0.0))
        sources = extract_sources(raw_result)
        
        elapsed = time.time() - start_time
        
        # Performance logging
        if elapsed < 15:
            logger.info(f"✅ FAST verification in {elapsed:.1f}s - Label: {label}, Confidence: {confidence:.2f}")
        elif elapsed < 30:
            logger.warning(f"⚠️  MODERATE speed: {elapsed:.1f}s - Label: {label}, Confidence: {confidence:.2f}")
        else:
            logger.error(f"🐌 SLOW verification: {elapsed:.1f}s - Label: {label}, Confidence: {confidence:.2f}")
        
        return {
            "label": label,
            "summary": summary,
            "confidence": confidence,
            "sources": sources,
            "_processing_time": elapsed,
            "_method": "direct_optimized",
            "_module": pvo.__name__
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ Direct call failed after {elapsed:.1f}s: {e}", exc_info=True)
        
        # Fallback to subprocess
        logger.info("⚠️  Falling back to subprocess method")
        return call_ai_verify_subprocess(claim_text)


# ===========================
# Subprocess Method (Fallback)
# ===========================

def verify_claim_with_training_script(
    claim_text: str,
    k: int = 10,
    min_relevance: float = 0.25,
    timeout: int = VERIFICATION_TIMEOUT
) -> Dict[str, Any]:
    """
    Verifikasi klaim menggunakan subprocess (fallback method).
    Lebih lambat dari direct import (3-5s overhead).
    
    Args:
        claim_text: Claim text to verify
        k: Number of neighbors to retrieve
        min_relevance: Minimum relevance threshold
        timeout: Timeout in seconds
        
    Returns:
        Raw result dictionary from script
        
    Raises:
        FileNotFoundError: If verification script not found
        subprocess.TimeoutExpired: If verification exceeds timeout
        RuntimeError: If verification fails
    """
    
    # ✅ Log which script is being used
    logger.info(f"📋 Subprocess verification with: {VERIFY_SCRIPT.name}")
    
    if not VERIFY_SCRIPT.exists():
        raise FileNotFoundError(f"Script tidak ditemukan: {VERIFY_SCRIPT}")
    
    # Determine if simple claim (fast path)
    claim_len = len(claim_text.split())
    is_simple = claim_len < SIMPLE_CLAIM_WORD_THRESHOLD
    
    # Persiapkan command
    cmd = [
        sys.executable,
        str(VERIFY_SCRIPT),
        "--claim", claim_text,
        "--k", str(k),
    ]
    
    # ✅ Add optimization flags for simple claims
    if is_simple:
        if 'optimized' in VERIFY_SCRIPT.name:
            cmd.append("--no-fetch")  # Skip fetch for optimized script
        else:
            cmd.extend(["--no-expansion"])  # Skip expansion for original script
        logger.info(f"🚀 Fast path enabled for simple claim ({claim_len} words)")
    
    logger.info(f"⏱️  Starting subprocess verification (timeout: {timeout}s)")
    logger.debug(f"Command: {' '.join(cmd[:4])}...")
    
    start_time = time.time()
    
    try:
        # Load environment
        env = load_training_env()
        
        # ✅ Validate critical env vars
        if not env.get('GEMINI_API_KEY'):
            logger.error("❌ GEMINI_API_KEY not found in environment!")
        
        logger.debug(f"Environment check:")
        logger.debug(f"  GEMINI_API_KEY: {'SET' if env.get('GEMINI_API_KEY') else 'MISSING'}")
        logger.debug(f"  DB_HOST: {env.get('DB_HOST', 'NOT SET')}")
        logger.debug(f"  DB_NAME: {env.get('DB_NAME', 'NOT SET')}")
        
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
        
        # ✅ Performance logging
        if elapsed < 20:
            logger.info(f"✅ FAST subprocess completed in {elapsed:.1f}s")
        elif elapsed < 40:
            logger.warning(f"⚠️  MODERATE speed: {elapsed:.1f}s (target: <20s)")
        else:
            logger.error(f"🐌 SLOW subprocess: {elapsed:.1f}s (investigate!)")
        
        logger.debug(f"Script exit code: {result.returncode}")
        
        # Check for errors
        if result.returncode != 0:
            logger.error(f"Script exited with code {result.returncode}")
            logger.error(f"STDERR: {result.stderr[:500]}")
            raise RuntimeError(f"Verification script failed: {result.stderr[:200]}")
        
        # Parse stdout
        stdout = result.stdout.strip()
        if not stdout:
            logger.error("Script produced no output")
            logger.error(f"STDERR: {result.stderr[:500]}")
            raise RuntimeError("Verification script produced no output")
        
        # Log output for debugging (truncated)
        logger.debug(f"STDOUT (first 500 chars): {stdout[:500]}")
        
        # Parse JSON
        parsed = parse_json_from_output(stdout)
        if not parsed:
            logger.error(f"Failed to parse JSON from output: {stdout[:200]}")
            raise ValueError("Cannot parse verification result as JSON")
        
        logger.info(f"✅ Subprocess verification successful in {elapsed:.1f}s")
        return parsed
        
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        logger.error(f"⏱️  Verification timeout after {elapsed:.1f}s (limit: {timeout}s)")
        raise
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ Verification failed after {elapsed:.1f}s: {e}")
        raise

def call_ai_verify_subprocess(claim_text: str) -> Dict[str, Any]:
    """
    Subprocess method with retry logic.
    
    Args:
        claim_text: Claim text to verify
        
    Returns:
        Verification result dictionary
    """
    start_time = time.time()
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"🔄 Subprocess verification attempt {attempt}/{MAX_RETRIES}: {claim_text[:80]}...")
            
            raw_result = verify_claim_with_training_script(
                claim_text,
                k=10,
                timeout=VERIFICATION_TIMEOUT
            )
            
            # Extract and normalize
            label = normalize_label(raw_result.get("label", "inconclusive"))
            summary = raw_result.get("summary", "")
            confidence = float(raw_result.get("confidence", 0.0))
            sources = extract_sources(raw_result)
            
            elapsed = time.time() - start_time
            logger.info(f"✅ Subprocess complete in {elapsed:.1f}s - Label: {label}")
            
            return {
                "label": label,
                "summary": summary,
                "confidence": confidence,
                "sources": sources,
                "_processing_time": elapsed,
                "_method": "subprocess",
                "_attempts": attempt
            }
            
        except subprocess.TimeoutExpired:
            logger.error(f"Attempt {attempt} timed out")
            if attempt >= MAX_RETRIES:
                raise RuntimeError("Verification timeout after all retries")
            continue
            
        except Exception as e:
            logger.error(f"Attempt {attempt} failed: {e}")
            if attempt >= MAX_RETRIES:
                raise
            continue
    
    raise RuntimeError("Verification failed after all retries")


# ===========================
# Public API
# ===========================

def call_ai_verify(claim_text: str) -> Dict[str, Any]:
    """
    ✅ MAIN ENTRY POINT: Verifikasi klaim dengan automatic method selection.
    
    ✅ UPDATED: Normalize response untuk konsistensi dengan backend model
    
    Tries methods in order:
    1. Direct import (fastest, 12-18s)
    2. Subprocess (fallback, 20-30s)
    
    Args:
        claim_text: Claim text to verify
        
    Returns:
        Dictionary dengan keys: label, summary, confidence, sources
        Semua label sudah dinormalisasi ke: 'valid', 'hoax', 'uncertain', 'unverified'
        
    Raises:
        ValueError: If claim_text is empty
        RuntimeError: If all verification methods fail
    """
    if not claim_text or not claim_text.strip():
        raise ValueError("Claim text cannot be empty")
    
    claim_text = claim_text.strip()
    
    logger.info("="*80)
    logger.info(f"📥 NEW VERIFICATION REQUEST")
    logger.info(f"   Claim: {claim_text[:100]}{'...' if len(claim_text) > 100 else ''}")
    logger.info(f"   Length: {len(claim_text)} chars, {len(claim_text.split())} words")
    logger.info("="*80)
    
    try:
        # ✅ Method 1: Try direct import first (fastest)
        logger.info("🎯 Attempting direct import method...")
        result = call_ai_verify_direct_optimized(claim_text)
        
        # ✅ NORMALIZE RESPONSE
        normalized = normalize_ai_response(result)
        
        logger.info(f"✅ Verification successful via {result.get('_method', 'unknown')}")
        logger.info(f"   Original label: {result.get('label')} → Normalized: {normalized['label']}")
        logger.info(f"   Confidence: {normalized['confidence']:.2%}")
        
        return normalized
        
    except Exception as e:
        logger.warning(f"⚠️  Direct import failed: {e}")
        logger.info("🔄 Falling back to subprocess method...")
        
        try:
            # ✅ Method 2: Fallback to subprocess
            result = call_ai_verify_subprocess(claim_text)
            
            # ✅ NORMALIZE RESPONSE
            normalized = normalize_ai_response(result)
            
            logger.info(f"✅ Verification successful via subprocess (fallback)")
            logger.info(f"   Original label: {result.get('label')} → Normalized: {normalized['label']}")
            logger.info(f"   Confidence: {normalized['confidence']:.2%}")
            
            return normalized
            
        except Exception as e2:
            logger.error(f"❌ All verification methods failed!")
            logger.error(f"   Direct import error: {e}")
            logger.error(f"   Subprocess error: {e2}")
            
            # Return error response (UNVERIFIED)
            return {
                "label": "unverified",
                "summary": f"Verification failed: {str(e2)[:200]}",
                "confidence": 0.0,
                "sources": [],
                "_error": True,
                "_error_message": str(e2)
            }

# ===========================
# Utility Functions for Testing
# ===========================

def test_verification(claim_text: str = "Minum air hangat di pagi hari baik untuk kesehatan") -> Dict[str, Any]:
    """
    Test function untuk debugging verification.
    
    Args:
        claim_text: Test claim
        
    Returns:
        Test results
    """
    logger.info("🧪 Running verification test...")
    
    results = {
        "claim": claim_text,
        "script_path": str(VERIFY_SCRIPT),
        "script_exists": VERIFY_SCRIPT.exists(),
        "methods": {}
    }
    
    # Test direct import
    try:
        start = time.time()
        result = call_ai_verify_direct_optimized(claim_text)
        elapsed = time.time() - start
        results["methods"]["direct"] = {
            "success": True,
            "time": elapsed,
            "label": result.get("label"),
            "confidence": result.get("confidence")
        }
    except Exception as e:
        results["methods"]["direct"] = {
            "success": False,
            "error": str(e)
        }
    
    # Test subprocess
    try:
        start = time.time()
        result = call_ai_verify_subprocess(claim_text)
        elapsed = time.time() - start
        results["methods"]["subprocess"] = {
            "success": True,
            "time": elapsed,
            "label": result.get("label"),
            "confidence": result.get("confidence")
        }
    except Exception as e:
        results["methods"]["subprocess"] = {
            "success": False,
            "error": str(e)
        }
    
    return results


# ===========================
# Module Initialization
# ===========================

# Log configuration on import
logger.info("="*80)
logger.info("AI Adapter Initialized")
logger.info(f"  Script: {VERIFY_SCRIPT.name}")
logger.info(f"  Path: {VERIFY_SCRIPT}")
logger.info(f"  Exists: {VERIFY_SCRIPT.exists()}")
logger.info(f"  Timeout: {VERIFICATION_TIMEOUT}s")
logger.info(f"  Max Retries: {MAX_RETRIES}")
logger.info("="*80)

# Add or update this function

def determine_verification_label(confidence_score, has_sources=True):
    """
    Menentukan label verifikasi berdasarkan confidence score
    
    Args:
        confidence_score (float): Skor confidence (0.0 - 1.0)
        has_sources (bool): Apakah ada sumber penelitian yang ditemukan
    
    Returns:
        str: Label verifikasi ('valid', 'hoax', 'uncertain', 'unverified')
    """
    if not has_sources:
        return 'unverified'
    
    if confidence_score >= 0.75:
        return 'valid'
    elif confidence_score <= 0.5:
        return 'hoax'
    else:  # 0.5 < confidence < 0.75
        return 'uncertain'

def create_verification_result(claim, confidence, summary, sources_count=0):
    """
    Membuat VerificationResult dengan label otomatis
    """
    from api.models import VerificationResult
    
    has_sources = sources_count > 0
    label = determine_verification_label(confidence, has_sources)
    
    result, created = VerificationResult.objects.update_or_create(
        claim=claim,
        defaults={
            'confidence': confidence,
            'summary': summary,
            'label': label
        }
    )
    
    return result