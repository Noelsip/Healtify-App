import os
import sys
import json
import subprocess
import hashlib
import time
import logging
import requests
import re
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
    logger.warning(f"Optimized script not found, using original")
    VERIFY_SCRIPT = TRAINING_SCRIPTS_DIR / "prompt_and_verify.py"

# ===========================
# Configuration
# ===========================
VERIFICATION_TIMEOUT = 90  
MAX_RETRIES = 2
SIMPLE_CLAIM_WORD_THRESHOLD = 20

# Global module cache for direct import
_optimized_module = None
_original_module = None

def safe_float(value, default: float = 0.0) -> float:
    """Konversi ke float dengan aman; fallback ke default jika gagal."""
    try:
        if value is None:
            return float(default)
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        return float(s)
    except Exception:
        try:
            return float(default)
        except Exception:
            return 0.0

def validate_url(url: str, timeout: float = 3.0) -> str:
    """Cek cepat apakah URL sumber tampak valid. Jika 404/5xx, kembalikan string kosong."""
    if not url:
        return ""
    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout)
        status = resp.status_code

        if status in (404, 410) or status >= 500:
            logger.info(f"Dropping unreachable source URL {url} (status={status})")
            return ""

        return resp.url or url
    except Exception as e:
        logger.debug(f"validate_url HEAD failed for {url}: {e}")
        return url

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
    IMPROVED: Deteksi health-related dengan support BILINGUAL.
    """
    # Expanded keywords - lebih comprehensive
    health_keywords_id = {
        'kesehatan', 'penyakit', 'obat', 'vitamin', 'diet', 'nutrisi',
        'medis', 'dokter', 'rumah sakit', 'terapi', 'pengobatan',
        'kanker', 'diabetes', 'jantung', 'darah', 'kulit', 'wajah',
        'imun', 'infeksi', 'virus', 'bakteri', 'gejala', 'diagnosa',
        'vaksin', 'antibiotik', 'herbal', 'suplemen', 'olahraga',
        'tidur', 'stress', 'mental', 'depresi', 'kecemasan',
        'merokok', 'rokok', 'tembakau', 'paru', 'asap'  # TAMBAHAN
    }
    
    health_keywords_en = {
        'health', 'disease', 'medicine', 'vitamin', 'diet', 'nutrition',
        'medical', 'doctor', 'hospital', 'therapy', 'treatment',
        'cancer', 'diabetes', 'heart', 'blood', 'skin', 'immune',
        'infection', 'virus', 'bacteria', 'symptom', 'diagnosis',
        'vaccine', 'antibiotic', 'supplement', 'exercise',
        'sleep', 'stress', 'mental', 'depression', 'anxiety',
        'smoking', 'cigarette', 'tobacco', 'lung', 'smoke'  # TAMBAHAN
    }
    
    # Medical patterns untuk deteksi lebih luas
    medical_patterns = [
        r'\b(cause[s]?|menyebabkan)\s+(cancer|kanker|disease|penyakit)',
        r'\b(prevent[s]?|mencegah)\s+(disease|penyakit|infection|infeksi)',
        r'\b(risk|risiko)\s+(of|dari)\s+(cancer|kanker|disease|penyakit)',
        r'\b(smoking|merokok)\b.*\b(lung|paru|cancer|kanker)',
        r'\b(treatment|pengobatan|terapi)\s+(for|untuk)',
    ]
    
    combined_text = (claim_text + " " + summary).lower()
    all_keywords = health_keywords_id | health_keywords_en
    
    # Method 1: Keyword matching
    keyword_matches = sum(1 for kw in all_keywords if kw in combined_text)
    
    # Method 2: Pattern matching
    pattern_matches = sum(1 for pattern in medical_patterns 
                         if re.search(pattern, combined_text, re.I))
    
    total_matches = keyword_matches + pattern_matches
    
    # LOWER threshold - lebih permissive
    is_health = total_matches >= 1  # Changed from 2 to 1
    
    logger.info(f"[HEALTH_CHECK] Keywords: {keyword_matches}, Patterns: {pattern_matches}, Is Health: {is_health}")
    
    return is_health

def determine_verification_label(confidence_score: float, has_sources: bool = True, 
                                has_journal: bool = False, claim_text: str = "", 
                                summary: str = "") -> str:
    """
    FIXED: Label determination dengan threshold yang lebih reasonable.

    New Rules (RELAXED):
    - Jika BUKAN klaim kesehatan DAN tidak ada sumber -> unverified
    """
    try:
        c = float(confidence_score)
    except (TypeError, ValueError):
        c = 0.0

    # Normalize confidence to 0.0–1.0
    if c > 1.0 and c <= 100.0:
        c /= 100.0
    c = max(0.0, min(c, 1.0))

    # Gabungkan teks klaim + ringkasan untuk heuristic sederhana
    combined_text = f"{claim_text} {summary}".lower()

    # Heuristic konsensus kuat: merokok/smoking menyebabkan kanker paru/lung cancer
    if (
        ("merokok" in combined_text or "smoking" in combined_text)
        and ("kanker paru" in combined_text or "lung cancer" in combined_text)
    ):
        logger.info("[LABEL] -> VALID (strong-consensus heuristic: smoking causes lung cancer)")
        return "valid"

    # Check if health-related
    is_health = is_health_related_claim(claim_text, summary)

    logger.info(
        f"[LABEL] Confidence: {c:.2f}, Has sources: {has_sources}, Has journal: {has_journal}, Is health: {is_health}"
    )

    # RULE A: Jika BUKAN klaim kesehatan ATAU tidak ada jurnal/sumber -> TIDAK TERVERIFIKASI
    if (not is_health) or (not has_sources):
        logger.info("[LABEL] -> UNVERIFIED (non-health or no journal sources)")
        return "unverified"

    # RULE B: Klaim kesehatan dengan jurnal/sumber
    #  - c >= 0.75  -> FAKTA (valid)
    #  - c <= 0.55  -> HOAX
    #  - 0.55 < c < 0.75 -> TIDAK PASTI (uncertain)
    if c >= 0.75:
        logger.info(f"[LABEL] -> VALID (confidence {c:.2f} >= 0.75)")
        return "valid"
    if c <= 0.55:
        logger.info(f"[LABEL] -> HOAX (confidence {c:.2f} <= 0.55)")
        return "hoax"

    logger.info(f"[LABEL] -> UNCERTAIN (0.55 < {c:.2f} < 0.75)")
    return "uncertain"

def map_ai_label_to_backend(ai_label: str) -> str:
    """Map label dari AI ke format backend."""
    if not ai_label:
        return 'unverified'
    
    label_lower = ai_label.lower().strip()
    
    label_mapping = {
        'true': 'valid', 'valid': 'valid', 'supported': 'valid', 
        'verified': 'valid', 'benar': 'valid', 'fakta': 'valid',
        
        'false': 'hoax', 'hoax': 'hoax', 'refuted': 'hoax',
        'debunked': 'hoax', 'salah': 'hoax',
        
        'uncertain': 'uncertain', 'partially_valid': 'uncertain',
        'partial': 'uncertain', 'misleading': 'uncertain',
        'mixed': 'uncertain', 'tidak_pasti': 'uncertain',
        
        'unverified': 'unverified', 'inconclusive': 'unverified',
        'unclear': 'unverified', 'insufficient': 'unverified',
    }
    
    return label_mapping.get(label_lower, 'unverified')

def normalize_ai_response(ai_result: Dict[str, Any], claim_text: str = "") -> Dict[str, Any]:
    """
    FIXED: Normalisasi response dengan logging detail.
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
    
    # Map raw label dari AI ke skema backend (valid/hoax/uncertain/unverified)
    mapped_label = map_ai_label_to_backend(raw_label)

    # Extract sources
    sources = extract_sources(ai_result)
    
    # Build summary
    original_summary = (ai_result.get('summary') or "").strip()
    combined_summary = original_summary or "Tidak ada ringkasan tersedia."
    
    # Detect journal presence
    has_journal = any(
        (s.get('doi') or '').strip() or s.get('source_type') == 'journal'
        for s in sources
    )
    
    logger.info(f"[NORMALIZE] Raw label: {raw_label} (mapped: {mapped_label}), Confidence: {confidence:.2f}")
    logger.info(f"[NORMALIZE] Has journal: {has_journal}, Total sources: {len(sources)}")
    
    # Jika AI sudah sangat yakin bahwa klaim adalah HOAX, jangan dibalik menjadi VALID
    if mapped_label == 'hoax':
        final_label = 'hoax'
        final_confidence = confidence
        logger.info("[NORMALIZE] Final label forced to HOAX based on AI raw label")
    else:
        # Determine final label dengan improved logic (termasuk heuristic merokok-kanker)
        final_label = determine_verification_label(
            confidence_score=confidence,
            has_sources=bool(sources),
            has_journal=has_journal,
            claim_text=claim_text,
            summary=combined_summary
        )

        # IMPORTANT: Jika label unverified, set confidence ke None
        final_confidence = confidence if final_label != 'unverified' else None
    
    logger.info(f"[NORMALIZE] Final: label={final_label}, confidence={final_confidence}")
    
    return {
        'label': final_label,
        'confidence': final_confidence,
        'summary': combined_summary,
        'sources': sources,
        '_original_label': raw_label,
        '_debug': {
            'claim_text': claim_text[:100],
            'has_journal': has_journal,
            'source_count': len(sources)
        }
    }


def extract_sources(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Ekstrak sources dari result dictionary dengan normalisasi.
    """
    sources = []
    
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

        # Jika tidak ada DOI, lakukan cek ringan untuk menghindari link yang jelas-jelas 404/5xx
        if not doi and url:
            url = validate_url(url)
        
        # Minimal identifier supaya bisa dilacak di frontend / database
        identifier = doi or url or safe_id
        if not identifier:
            continue
        
        raw_title = src.get("title") or safe_id or "Unknown"
        snippet = (src.get("snippet") or src.get("text") or "").strip()
        if raw_title == "Unknown" and snippet:
            raw_title = snippet[:80] + ("..." if len(snippet) > 80 else "")
        
        excerpt = snippet[:500]
        
        source_obj = {
            "title": raw_title,
            "doi": doi,
            "url": (f"https://doi.org/{doi}" if doi else url),
            "relevance_score": safe_float(
                src.get("relevance_score", src.get("relevance", 0.0)),
                default=0.0,
            ),
            "excerpt": excerpt,
            "source_type": src.get("source_type", "journal"),
        }
        
        sources.append(source_obj)
    
    # Urutkan dari yang paling relevan dan ambil maksimal 5 untuk ditampilkan di frontend
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
            
            critical_keys = ["DEEPSEEK_API_KEY", "GEMINI_API_KEY", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"]
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
    """Lazy import optimized module."""
    global _optimized_module
    
    if _optimized_module is None:
        if str(TRAINING_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(TRAINING_SCRIPTS_DIR))
        
        try:
            import prompt_and_verify as pv
            _optimized_module = pv
            logger.info("✅ Loaded verification module (DeepSeek)")
        except ImportError as e:
            raise ImportError(f"Cannot import verification module: {e}")
    
    return _optimized_module

def call_ai_verify_direct_optimized(claim_text: str) -> Dict[str, Any]:
    """Call AI verification directly."""
    start_time = time.time()
    
    try:
        logger.info(f"🚀 Verifying: {claim_text[:80]}...")
        
        pvo = get_optimized_module()
        
        # Use verify_claim_local (main verification function)
        if hasattr(pvo, 'verify_claim_local'):
            raw_result = pvo.verify_claim_local(
                claim=claim_text,
                k=10,
                dry_run=False,
                enable_expansion=True,
                min_relevance=0.25,
                force_dynamic_fetch=False,
                debug_retrieval=False
            )
        else:
            raise AttributeError("verify_claim_local not found in module")
        
        elapsed = time.time() - start_time
        
        logger.info(f"✅ Verification completed in {elapsed:.1f}s")
        
        # Extract from _frontend_payload if present (new format)
        if "_frontend_payload" in raw_result:
            payload = raw_result["_frontend_payload"]
            logger.debug(f"[PARSE] Extracted from _frontend_payload: label={payload.get('label')}")
        else:
            payload = raw_result
        
        # Get label and map it
        raw_label = payload.get("label", "unverified")
        mapped_label = map_ai_label_to_backend(raw_label)
        
        # Get confidence
        raw_confidence = payload.get("confidence")
        confidence = float(raw_confidence) if raw_confidence is not None else 0.0
        
        # Get summary
        summary = payload.get("summary", "") or payload.get("conclusion", "") or ""
        
        # Get sources from evidence or references
        sources = extract_sources(payload)
        
        logger.info(f"[PARSE] Label: {raw_label} -> {mapped_label}, Confidence: {confidence}, Sources: {len(sources)}")
        
        return {
            "label": mapped_label,
            "summary": summary,
            "confidence": confidence,
            "sources": sources,
            "_processing_time": elapsed,
            "_method": "direct_optimized",
            "_claim_text": claim_text,
            "_raw_label": raw_label
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ Verification failed: {e}", exc_info=True)
        
        return {
            "label": "unverified",
            "summary": f"Verification error: {str(e)[:100]}",
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
# Public API
# ===========================

def call_ai_verify(claim_text: str, additional_evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    MAIN ENTRY POINT dengan improved logic.
    
    Args:
        claim_text: Teks klaim yang akan diverifikasi
        additional_evidence: Optional dict berisi evidence tambahan dari user dispute:
            - doi: DOI jurnal dari user
            - url: URL sumber dari user  
            - abstract: Abstract/konten yang sudah di-fetch
            - title: Judul jurnal
    """
    if not claim_text or not claim_text.strip():
        raise ValueError("Claim text cannot be empty")
    
    claim_text = claim_text.strip()
    
    logger.info("="*80)
    logger.info(f" NEW VERIFICATION REQUEST")
    logger.info(f"   Claim: {claim_text[:100]}")
    if additional_evidence:
        logger.info(f"   Additional Evidence: DOI={additional_evidence.get('doi', 'N/A')}")
    logger.info("="*80)
    
    try:
        # Jika ada additional evidence, include dalam verification
        if additional_evidence and additional_evidence.get('abstract'):
            result = call_ai_verify_with_evidence(claim_text, additional_evidence)
        else:
            result = call_ai_verify_direct_optimized(claim_text)
            
        normalized = normalize_ai_response(result, claim_text=claim_text)
        
        logger.info(f" Final Result:")
        logger.info(f"   Label: {normalized['label']}")
        logger.info(f"   Confidence: {normalized.get('confidence', 'N/A')}")
        logger.info(f"   Sources: {len(normalized.get('sources', []))}")
        
        return normalized
        
    except Exception as e:
        logger.error(f" Verification failed: {e}")
        
        return {
            "label": "unverified",
            "summary": f"Verification failed: {str(e)[:200]}",
            "confidence": None,
            "sources": [],
            "_error": True,
            "_error_message": str(e)
        }


def call_ai_verify_with_evidence(claim_text: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
    """
    Verifikasi klaim dengan evidence tambahan dari user dispute.
    Evidence akan di-inject ke dalam prompt sebagai bukti prioritas.
    """
    start_time = time.time()
    
    try:
        module = get_optimized_module()
        if module is None:
            raise ImportError("Could not import verification module")
        
        # Build custom evidence context
        evidence_context = f"""
=== BUKTI TAMBAHAN DARI USER ===
Judul: {evidence.get('title', 'N/A')}
DOI: {evidence.get('doi', 'N/A')}
URL: {evidence.get('url', 'N/A')}

Abstrak/Konten:
{evidence.get('abstract', 'Tidak tersedia')}
================================
"""
        
        # Gabungkan claim dengan evidence untuk verification
        enhanced_claim = f"{claim_text}\n\n[KONTEKS TAMBAHAN - BUKTI DARI PELAPOR]\n{evidence_context}"
        
        logger.info(f"[VERIFY_WITH_EVIDENCE] Running verification with user evidence...")
        
        # Call verify function dengan enhanced claim
        raw_result = module.verify_claim_local(
            enhanced_claim,
            k=8,  # Lebih banyak neighbors
            dry_run=False,
            enable_expansion=True,
            min_relevance=0.2,  # Lower threshold untuk include evidence
            force_dynamic_fetch=False,
            debug_retrieval=False
        )
        
        elapsed = time.time() - start_time
        logger.info(f"[VERIFY_WITH_EVIDENCE] Completed in {elapsed:.2f}s")
        
        # Add user evidence to sources
        if raw_result.get('sources') is None:
            raw_result['sources'] = []
        
        # Tambahkan evidence user sebagai source pertama
        user_source = {
            'title': evidence.get('title', 'User Provided Evidence'),
            'doi': evidence.get('doi', ''),
            'url': evidence.get('url', ''),
            'relevance_score': 0.95,  # High relevance karena dari user
            '_from_dispute': True
        }
        raw_result['sources'].insert(0, user_source)
        
        return raw_result
        
    except Exception as e:
        logger.error(f"[VERIFY_WITH_EVIDENCE] Error: {e}")
        raise
logger.info(f"  Exists: {VERIFY_SCRIPT.exists()}")
logger.info(f"  Timeout: {VERIFICATION_TIMEOUT}s")
logger.info(f"  Max Retries: {MAX_RETRIES}")
logger.info("="*80)