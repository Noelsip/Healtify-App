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

def is_health_related_claim(claim_text: str, summary: str = "") -> bool:
    """
    Deteksi apakah klaim berkaitan dengan kesehatan.
    Returns True jika health-related, False jika tidak.
    """
    health_keywords_id = {
        'kesehatan', 'penyakit', 'obat', 'vitamin', 'diet', 'nutrisi',
        'medis', 'dokter', 'rumah sakit', 'terapi', 'pengobatan',
        'kanker', 'diabetes', 'jantung', 'darah', 'kulit', 'wajah',
        'imun', 'infeksi', 'virus', 'bakteri', 'gejala', 'diagnosa',
        'vaksin', 'antibiotik', 'herbal', 'suplemen', 'olahraga',
        'tidur', 'stress', 'mental', 'depresi', 'kecemasan'
    }
    
    health_keywords_en = {
        'health', 'disease', 'medicine', 'vitamin', 'diet', 'nutrition',
        'medical', 'doctor', 'hospital', 'therapy', 'treatment',
        'cancer', 'diabetes', 'heart', 'blood', 'skin', 'face',
        'immune', 'infection', 'virus', 'bacteria', 'symptom', 'diagnosis',
        'vaccine', 'antibiotic', 'herbal', 'supplement', 'exercise',
        'sleep', 'stress', 'mental', 'depression', 'anxiety'
    }
    
    all_keywords = health_keywords_id | health_keywords_en
    
    # Check claim text
    text_lower = claim_text.lower()
    summary_lower = summary.lower() if summary else ""
    combined_text = text_lower + " " + summary_lower
    
    # Count keyword matches
    matches = sum(1 for keyword in all_keywords if keyword in combined_text)
    
    # Threshold: at least 1 keyword match untuk dianggap health-related
    return matches >= 1

def determine_verification_label(confidence_score: float, has_sources: bool = True, 
                                has_journal: bool = False, claim_text: str = "", 
                                summary: str = "") -> str:
    """
    Menentukan label verifikasi berdasarkan confidence dan sumber.
    
    Label Rules:
    1. TIDAK TERVERIFIKASI: Jika bukan topik kesehatan atau tidak ada jurnal
    2. FAKTA (valid): confidence >= 0.75 dan ada sumber jurnal
    3. HOAX: confidence <= 0.5 dan ada sumber jurnal
    4. TIDAK PASTI (uncertain): 0.5 < confidence < 0.75 dan ada sumber jurnal
    """
    try:
        c = float(confidence_score)
    except (TypeError, ValueError):
        c = 0.0
    
    # Normalize confidence to 0-1 range
    if c > 1.0 and c <= 100.0:
        c /= 100.0
    c = max(0.0, min(c, 1.0))
    
    # Check if health-related
    is_health = is_health_related_claim(claim_text, summary)
    
    # Rule 1: TIDAK TERVERIFIKASI jika bukan topik kesehatan
    if not is_health:
        logger.info(f"[LABEL] Claim tidak berkaitan dengan kesehatan -> TIDAK TERVERIFIKASI")
        return 'unverified'
    
    # Rule 2: TIDAK TERVERIFIKASI jika tidak ada jurnal
    if not has_journal:
        logger.info(f"[LABEL] Tidak ada sumber jurnal -> TIDAK TERVERIFIKASI")
        return 'unverified'
    
    # Rule 3: FAKTA jika confidence >= 0.75
    if c >= 0.75:
        logger.info(f"[LABEL] Confidence {c:.2f} >= 0.75 -> FAKTA")
        return 'valid'
    
    # Rule 4: HOAX jika confidence <= 0.5
    if c <= 0.5:
        logger.info(f"[LABEL] Confidence {c:.2f} <= 0.5 -> HOAX")
        return 'hoax'
    
    # Rule 5: TIDAK PASTI jika 0.5 < confidence < 0.75
    logger.info(f"[LABEL] Confidence {c:.2f} between 0.5-0.75 -> TIDAK PASTI")
    return 'uncertain'

def map_ai_label_to_backend(ai_label: str) -> str:
    """
    Map label dari AI ke format backend.
    """
    if not ai_label:
        return 'unverified'
    
    label_lower = ai_label.lower().strip()
    
    # Mapping comprehensive
    label_mapping = {
        # VALID variants
        'true': 'valid',
        'valid': 'valid',
        'supported': 'valid',
        'verified': 'valid',
        'benar': 'valid',
        'fakta': 'valid',
        
        # HOAX variants
        'false': 'hoax',
        'hoax': 'hoax',
        'refuted': 'hoax',
        'debunked': 'hoax',
        'salah': 'hoax',
        
        # UNCERTAIN variants
        'uncertain': 'uncertain',
        'partially_valid': 'uncertain',
        'partial': 'uncertain',
        'misleading': 'uncertain',
        'mixed': 'uncertain',
        'tidak_pasti': 'uncertain',
        'sebagian': 'uncertain',
        
        # UNVERIFIED variants
        'unverified': 'unverified',
        'inconclusive': 'unverified',
        'unclear': 'unverified',
        'insufficient': 'unverified',
        'tidak_terverifikasi': 'unverified',
    }
    
    return label_mapping.get(label_lower, 'unverified')

def normalize_ai_response(ai_result: Dict[str, Any], claim_text: str = "") -> Dict[str, Any]:
    """
    Normalisasi response dari AI dengan label yang konsisten.
    """
    raw_label = ai_result.get('label', 'unverified')
    confidence_raw = ai_result.get('confidence', 0)
    
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    
    if confidence > 1.0 and confidence <= 100.0:
        confidence /= 100.0
    confidence = max(0.0, min(confidence, 1.0))
    
    # Extract sources
    sources = extract_sources(ai_result)
    
    # Build enriched summary
    original_summary = (ai_result.get('summary') or "").strip()
    if sources:
        quotes = []
        for s in sources[:5]:
            ex = s.get('excerpt')
            if ex:
                quotes.append(f'• "{ex[:160]}"')
        evidence_block = "Evidence excerpts:\n" + "\n".join(quotes) if quotes else ""
        if not original_summary:
            combined_summary = evidence_block or "Tidak ada ringkasan."
        elif len(original_summary) < 300 and evidence_block:
            combined_summary = original_summary + "\n\n" + evidence_block
        else:
            combined_summary = original_summary
    else:
        combined_summary = original_summary or "Tidak ada sumber pendukung ditemukan."
    
    # Detect journal presence (DOI atau source_type = journal)
    has_journal = any(
        (s.get('doi') or '').strip() or s.get('source_type') == 'journal'
        for s in sources
    )
    
    # Determine final label berdasarkan aturan yang BENAR
    final_label = determine_verification_label(
        confidence_score=confidence,
        has_sources=bool(sources),
        has_journal=has_journal,
        claim_text=claim_text,
        summary=combined_summary
    )
    
    # PENTING: Jika label adalah unverified, set confidence ke None
    final_confidence = confidence if final_label != 'unverified' else None
    
    return {
        'label': final_label,
        'confidence': final_confidence,
        'summary': combined_summary,
        'sources': sources,
        '_original_label': raw_label,
        '_processing_time': ai_result.get('_processing_time', 0),
        '_method': ai_result.get('_method', 'unknown')
    }

def extract_sources(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Ekstrak sources dari result dictionary dengan normalisasi.
    """
    sources = []
    seen_identifiers = set()
    
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
        
        doi = (src.get("doi") or "").strip()
        url = (src.get("url") or "").strip()
        safe_id = (src.get("safe_id") or "").strip()
        
        identifier = doi or url or safe_id
        
        if not identifier or identifier in seen_identifiers:
            continue
        seen_identifiers.add(identifier)
        
        raw_title = src.get("title") or safe_id or "Unknown"
        snippet = (src.get("snippet") or src.get("text") or "").strip()
        if raw_title == "Unknown" and snippet:
            raw_title = snippet[:80] + ("..." if len(snippet) > 80 else "")
        
        excerpt = snippet[:500]
        
        source_obj = {
            "title": raw_title,
            "doi": doi,
            "url": url or (f"https://doi.org/{doi}" if doi else ""),
            "relevance_score": float(
                src.get("relevance_score", 0)
                or src.get("relevance", 0) 
                or 0
            ),
            "excerpt": excerpt,
            "source_type": src.get("source_type", "journal"),
        }
        
        sources.append(source_obj)
    
    sources.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return sources[:5]

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
            
            critical_keys = ["GEMINI_API_KEY", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"]
            missing_keys = [k for k in critical_keys if not env_vars.get(k)]
            
            if missing_keys:
                logger.warning(f"⚠️  Missing keys in training/.env: {missing_keys}")
            else:
                logger.debug("✅ All critical env keys present")
            
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
            if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
                return parsed[0]
            return {"raw_data": parsed}
    except (json.JSONDecodeError, ValueError):
        pass
    
    logger.warning("Failed to parse JSON from output")
    return None

# ===========================
# Direct Import Methods (FASTEST)
# ===========================

def get_optimized_module():
    """
    Lazy import optimized module untuk direct call.
    """
    global _optimized_module
    
    if _optimized_module is None:
        if str(TRAINING_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(TRAINING_SCRIPTS_DIR))
        
        try:
            import prompt_and_verify_optimized as pvo
            _optimized_module = pvo
            logger.info("✅ Loaded optimized module directly (no subprocess)")
        except ImportError as e:
            logger.error(f"❌ Failed to import optimized module: {e}")
            
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
    Call AI verification directly (no subprocess).
    """
    start_time = time.time()
    
    try:
        claim_len = len(claim_text.split())
        is_simple = claim_len < SIMPLE_CLAIM_WORD_THRESHOLD
        
        logger.info(
            f"🚀 Direct verification: {claim_text[:80]}... "
            f"(words: {claim_len}, simple: {is_simple})"
        )
        
        pvo = get_optimized_module()
        
        if hasattr(pvo, 'verify_claim_v2'):
            logger.debug("Using verify_claim_v2 (optimized)")
            raw_result = pvo.verify_claim_v2(
                claim=claim_text,
                k=10,
                enable_fetch=not is_simple,
                debug=False
            )
        else:
            raise AttributeError("verify_claim_v2 function not found")
        
        # Extract results dengan safe defaults
        label = map_ai_label_to_backend(raw_result.get("label", "unverified"))
        summary = raw_result.get("summary", "")
        confidence = float(raw_result.get("confidence") or 0.0)
        sources = extract_sources(raw_result)
        
        elapsed = time.time() - start_time
        
        if elapsed < 15:
            logger.info(f"✅ FAST verification in {elapsed:.1f}s")
        elif elapsed < 30:
            logger.warning(f"⚠️  MODERATE speed: {elapsed:.1f}s")
        else:
            logger.error(f"🐌 SLOW verification: {elapsed:.1f}s")
        
        return {
            "label": label,
            "summary": summary,
            "confidence": confidence,
            "sources": sources,
            "_processing_time": elapsed,
            "_method": "direct_optimized",
            "_module": pvo.__name__,
            "_claim_text": claim_text
        }
        
    except (NameError, AttributeError, ModuleNotFoundError) as e:
        elapsed = time.time() - start_time
        logger.error(
            f"❌ Module/Attribute error after {elapsed:.1f}s: {e}",
            exc_info=True
        )
        # Fallback: return unverified result
        return {
            "label": "unverified",
            "summary": f"Verification system error: {str(e)[:100]}",
            "confidence": None,
            "sources": [],
            "_error": True,
            "_processing_time": elapsed
        }
    
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ Direct call failed after {elapsed:.1f}s: {e}", exc_info=True)
        
        return {
            "label": "unverified",
            "summary": f"Verification failed: {str(e)[:100]}",
            "confidence": None,
            "sources": [],
            "_error": True,
            "_processing_time": elapsed
        }
        
def call_ai_verify_subprocess(claim_text: str) -> Dict[str, Any]:
    """
    Subprocess fallback method - fallback implementation.
    """
    raise NotImplementedError("Subprocess method not fully implemented - use direct method")

# ===========================
# Public API
# ===========================

def call_ai_verify(claim_text: str) -> Dict[str, Any]:
    """
    MAIN ENTRY POINT: Verifikasi klaim dengan automatic method selection.
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
        logger.info("🎯 Attempting direct import method...")
        result = call_ai_verify_direct_optimized(claim_text)
        
        # Normalize response dengan aturan label yang BENAR
        normalized = normalize_ai_response(result, claim_text=claim_text)
        
        logger.info(f"✅ Verification successful via {result.get('_method', 'unknown')}")
        logger.info(f"   Label: {normalized['label']}")
        logger.info(f"   Confidence: {normalized.get('confidence', 'N/A')}")
        
        return normalized
        
    except Exception as e:
        logger.warning(f"⚠️  Direct import failed: {e}")
        logger.info("🔄 Falling back to subprocess method...")
        
        try:
            result = call_ai_verify_subprocess(claim_text)
            normalized = normalize_ai_response(result, claim_text=claim_text)
            
            logger.info(f"✅ Verification successful via subprocess")
            logger.info(f"   Label: {normalized['label']}")
            logger.info(f"   Confidence: {normalized.get('confidence', 'N/A')}")
            
            return normalized
            
        except Exception as e2:
            logger.error(f"❌ All verification methods failed!")
            logger.error(f"   Direct import error: {e}")
            logger.error(f"   Subprocess error: {e2}")
            
            return {
                "label": "unverified",
                "summary": f"Verification failed: {str(e2)[:200]}",
                "confidence": None,
                "sources": [],
                "_error": True,
                "_error_message": str(e2)
            }

# Module initialization
logger.info("="*80)
logger.info("AI Adapter Initialized")
logger.info(f"  Script: {VERIFY_SCRIPT.name}")
logger.info(f"  Path: {VERIFY_SCRIPT}")
logger.info(f"  Exists: {VERIFY_SCRIPT.exists()}")
logger.info(f"  Timeout: {VERIFICATION_TIMEOUT}s")
logger.info(f"  Max Retries: {MAX_RETRIES}")
logger.info("="*80)