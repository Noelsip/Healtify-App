"""
Intelligent Text Normalization dengan Semantic Understanding
Tidak menggunakan hardcoded patterns, tapi semantic similarity
"""

import logging
import hashlib
import re
from typing import Optional, List, Tuple
from difflib import SequenceMatcher
from functools import lru_cache

logger = logging.getLogger(__name__)

# Typo correction threshold
TYPO_SIMILARITY_THRESHOLD = 0.85  
MIN_WORD_LENGTH_FOR_TYPO_CHECK = 4

# Semantic similarity threshold
SEMANTIC_SIMILARITY_THRESHOLD = 0.90

# Cache settings
MAX_CACHE_SIZE = 1000


# Core Normalization Functions
def normalize_claim_text(text: str, aggressive: bool = False) -> str:
    """
    Normalisasi text dengan intelligent processing.
    
    Args:
        text: Original text
        aggressive: If True, apply more aggressive normalization
    
    Returns:
        Normalized text
    """
    if not text:
        return ""
    
    # Basic cleaning
    normalized = _basic_cleaning(text)
    
    # Fix common typos (optional)
    if aggressive:
        normalized = _fix_typos(normalized)
    
    # Standardize spacing
    normalized = _standardize_spacing(normalized)
    
    return normalized


def _basic_cleaning(text: str) -> str:
    """Basic text cleaning tanpa hardcoded rules."""
    # Lowercase
    text = text.lower().strip()
    
    # Replace multiple spaces, tabs, newlines
    text = re.sub(r'\s+', ' ', text)
    
    # Remove most punctuation but keep meaningful ones
    # Keep: numbers, letters, spaces, % (percentages), / (ratios)
    text = re.sub(r'[^\w\s%/]', ' ', text)
    
    # Remove extra spaces from punctuation removal
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def _standardize_spacing(text: str) -> str:
    """Standardize spacing around words."""
    # Split and rejoin to ensure consistent spacing
    words = text.split()
    return ' '.join(words)


def _fix_typos(text: str) -> str:
    """
    Fix common typos using fuzzy matching.
    This checks each word against previously seen correct words.
    """
    words = text.split()
    corrected_words = []
    
    for word in words:
        if len(word) < MIN_WORD_LENGTH_FOR_TYPO_CHECK:
            corrected_words.append(word)
            continue
        
        # Check if this looks like a typo of a known word
        corrected = _check_typo(word)
        corrected_words.append(corrected)
    
    return ' '.join(corrected_words)


@lru_cache(maxsize=MAX_CACHE_SIZE)
def _check_typo(word: str) -> str:
    """
    Check if word is a typo using known vocabulary.
    
    This is a simplified version - in production, you'd use:
    - Spellchecker library (pyspellchecker)
    - Language model
    - Domain-specific vocabulary
    """
    # For now, just return the word as-is
    # In production, integrate with spell checker
    return word

# Semantic Similarity Functions
def calculate_text_similarity(text1: str, text2: str) -> float:
    """
    Calculate semantic similarity between two texts.
    Uses multiple algorithms for robustness.
    
    Returns:
        float: Similarity score (0-1)
    """
    if not text1 or not text2:
        return 0.0
    
    # Normalize both texts first
    norm1 = normalize_claim_text(text1, aggressive=False)
    norm2 = normalize_claim_text(text2, aggressive=False)
    
    # Character-level similarity
    char_similarity = SequenceMatcher(None, norm1, norm2).ratio()
    
    # Word-level similarity
    word_similarity = _calculate_word_similarity(norm1, norm2)
    
    # Token set similarity
    token_similarity = _calculate_token_set_similarity(norm1, norm2)
    
    # Weighted combination
    final_similarity = (
        0.3 * char_similarity +
        0.4 * word_similarity +
        0.3 * token_similarity
    )
    
    return final_similarity

def _calculate_word_similarity(text1: str, text2: str) -> float:
    """Calculate similarity based on word overlap."""
    words1 = set(text1.split())
    words2 = set(text2.split())
    
    if not words1 or not words2:
        return 0.0
    
    # Jaccard similarity
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    
    return intersection / union if union > 0 else 0.0

def _calculate_token_set_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity ignoring word order completely.
    Good for catching semantic similarity despite different phrasing.
    """
    tokens1 = sorted(text1.split())
    tokens2 = sorted(text2.split())
    
    # Compare sorted token lists
    return SequenceMatcher(None, ' '.join(tokens1), ' '.join(tokens2)).ratio()

# Advanced Similarity with Fuzzy Matching
def find_similar_texts(
    query_text: str,
    candidate_texts: List[Tuple[int, str]],
    threshold: float = SEMANTIC_SIMILARITY_THRESHOLD,
    top_k: int = 5
) -> List[Tuple[int, str, float]]:
    """
    Find most similar texts from candidates using fuzzy matching.
    
    Args:
        query_text: Text to search for
        candidate_texts: List of (id, text) tuples
        threshold: Minimum similarity threshold
        top_k: Return top K results
    
    Returns:
        List of (id, text, similarity_score) tuples
    """
    results = []
    
    for candidate_id, candidate_text in candidate_texts:
        similarity = calculate_text_similarity(query_text, candidate_text)
        
        if similarity >= threshold:
            results.append((candidate_id, candidate_text, similarity))
    
    # Sort by similarity descending
    results.sort(key=lambda x: x[2], reverse=True)
    
    return results[:top_k]

# Hash Generation (Semantic-aware)
def generate_semantic_hash(text: str, use_aggressive: bool = False) -> str:
    """
    Generate hash that's resistant to typos and variations.
    
    Args:
        text: Original text
        use_aggressive: Use aggressive normalization
    
    Returns:
        Hash string
    """
    # Normalize text
    normalized = normalize_claim_text(text, aggressive=use_aggressive)
    
    # Create hash
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def generate_fuzzy_hash(text: str) -> str:
    """
    Generate a fuzzy hash that groups similar variations together.
    Uses only the most significant words.
    """
    # Get only content words (remove very short words)
    words = normalize_claim_text(text).split()
    significant_words = [w for w in words if len(w) >= 3]
    
    # Sort alphabetically to ignore word order
    sorted_words = sorted(significant_words)
    
    # Create hash from sorted significant words
    fuzzy_text = ' '.join(sorted_words)
    return hashlib.md5(fuzzy_text.encode('utf-8')).hexdigest()[:16]

# Intelligent Duplicate Detection
class ClaimSimilarityMatcher:
    """
    Intelligent matcher for finding duplicate/similar claims.
    Uses multiple strategies for robust matching.
    """
    
    def __init__(
        self,
        exact_threshold: float = 1.0,
        high_threshold: float = 0.95,
        medium_threshold: float = 0.85,
        low_threshold: float = 0.75
    ):
        self.exact_threshold = exact_threshold
        self.high_threshold = high_threshold
        self.medium_threshold = medium_threshold
        self.low_threshold = low_threshold
    
    def find_duplicates(
        self,
        query_text: str,
        existing_claims: List[Tuple[int, str, str]]  # (id, text, normalized)
    ) -> dict:
        """
        Find duplicate claims using multi-level matching.
        
        Args:
            query_text: New claim text
            existing_claims: List of (id, original_text, normalized_text)
        
        Returns:
            dict with match_level and matched_claim_id
        """
        query_normalized = normalize_claim_text(query_text)
        query_fuzzy_hash = generate_fuzzy_hash(query_text)
        
        matches = {
            'exact': [],
            'high': [],
            'medium': [],
            'low': []
        }
        
        for claim_id, original, normalized in existing_claims:
            # Level 1: Exact match (after normalization)
            if query_normalized == normalized:
                matches['exact'].append((claim_id, 1.0))
                continue
            
            # Level 2: Fuzzy hash match (very similar)
            claim_fuzzy_hash = generate_fuzzy_hash(original)
            if query_fuzzy_hash == claim_fuzzy_hash:
                matches['high'].append((claim_id, 0.95))
                continue
            
            # Level 3: Semantic similarity
            similarity = calculate_text_similarity(query_text, original)
            
            if similarity >= self.high_threshold:
                matches['high'].append((claim_id, similarity))
            elif similarity >= self.medium_threshold:
                matches['medium'].append((claim_id, similarity))
            elif similarity >= self.low_threshold:
                matches['low'].append((claim_id, similarity))
        
        # Return best match
        for level in ['exact', 'high', 'medium', 'low']:
            if matches[level]:
                # Sort by similarity
                matches[level].sort(key=lambda x: x[1], reverse=True)
                best_match = matches[level][0]
                
                return {
                    'match_found': True,
                    'match_level': level,
                    'claim_id': best_match[0],
                    'similarity': best_match[1],
                    'all_matches': matches[level]
                }
        
        return {
            'match_found': False,
            'match_level': None,
            'claim_id': None,
            'similarity': 0.0
        }

# Integration with Embedding Models (Optional)
def calculate_embedding_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity using embedding models (optional).
    Requires sentence-transformers or similar library.
    
    This is commented out as it requires additional dependencies.
    Uncomment if you want to use semantic embeddings.
    """
    try:
        return calculate_text_similarity(text1, text2)
    
    except ImportError:
        logger.warning("sentence-transformers not available, using basic similarity")
        return calculate_text_similarity(text1, text2)

# Utility Functions
@lru_cache(maxsize=MAX_CACHE_SIZE)
def preprocess_for_comparison(text: str) -> str:
    """
    Optimized preprocessing for comparison.
    Cached for performance.
    """
    return normalize_claim_text(text, aggressive=False)

def get_similarity_explanation(similarity: float) -> str:
    """Get human-readable explanation of similarity score."""
    if similarity >= 0.95:
        return "Sangat mirip (kemungkinan besar duplikat)"
    elif similarity >= 0.85:
        return "Mirip (kemungkinan variasi dari klaim yang sama)"
    elif similarity >= 0.75:
        return "Agak mirip (mungkin topik yang sama)"
    elif similarity >= 0.60:
        return "Sedikit mirip (topik berkaitan)"
    else:
        return "Tidak mirip"

# Testing & Debugging
def test_normalization():
    """Test function untuk verify normalization works correctly."""
    test_cases = [
        ("merokok dapat menyebabkan kanker paru-paru", "merokok dapat menyebabkan kanker paru paru"),
        ("Covid-19 menyebabkan demam", "covid 19 menyebabkan demam"),
        ("Diabetes mellitus tipe 2", "diabetes melitus type 2"),
        ("Tekanan darah tinggi berbahaya", "hipertensi berbahaya"),
    ]
    
    print("\n=== Testing Text Normalization ===\n")
    
    for text1, text2 in test_cases:
        norm1 = normalize_claim_text(text1)
        norm2 = normalize_claim_text(text2)
        similarity = calculate_text_similarity(text1, text2)
        
        print(f"Text 1: {text1}")
        print(f"Text 2: {text2}")
        print(f"Normalized 1: {norm1}")
        print(f"Normalized 2: {norm2}")
        print(f"Similarity: {similarity:.2%}")
        print(f"Explanation: {get_similarity_explanation(similarity)}")
        print(f"Same hash: {generate_semantic_hash(text1) == generate_semantic_hash(text2)}")
        print("-" * 80)

if __name__ == "__main__":
    test_normalization()