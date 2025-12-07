"""
Cache Manager untuk Healtify
=============================
Menyimpan hasil verifikasi, fetch, dan embedding untuk mempercepat proses.

Features:
- File-based cache (persistent across restarts)
- TTL (Time-To-Live) support
- Automatic cleanup of expired entries
- Thread-safe operations
"""

import os
import json
import time
import hashlib
import threading
from pathlib import Path
from typing import Any, Optional, Dict
from datetime import datetime

# Configuration
CACHE_DIR = Path(__file__).parents[1] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Default TTL values (in seconds)
DEFAULT_TTL = {
    "verification": 7 * 24 * 3600,    # 7 days for verification results
    "fetch": 24 * 3600,                # 24 hours for API fetch results
    "embedding": 30 * 24 * 3600,       # 30 days for embeddings
    "translation": 30 * 24 * 3600,     # 30 days for translations
}

# Lock for thread-safe operations
_cache_lock = threading.Lock()

# In-memory cache for fast access
_memory_cache: Dict[str, Dict[str, Any]] = {}
MAX_MEMORY_ITEMS = 1000  # Limit memory cache size


def _generate_key(prefix: str, data: str) -> str:
    """Generate a unique cache key from prefix and data."""
    hash_obj = hashlib.md5(data.encode('utf-8'))
    return f"{prefix}_{hash_obj.hexdigest()[:16]}"


def _get_cache_path(cache_type: str, key: str) -> Path:
    """Get the file path for a cache entry."""
    type_dir = CACHE_DIR / cache_type
    type_dir.mkdir(parents=True, exist_ok=True)
    return type_dir / f"{key}.json"


def _is_expired(entry: Dict[str, Any]) -> bool:
    """Check if a cache entry has expired."""
    if "expires_at" not in entry:
        return False
    return time.time() > entry["expires_at"]


def get_cache(cache_type: str, key: str) -> Optional[Any]:
    """
    Retrieve a value from cache.
    
    Args:
        cache_type: Type of cache (verification, fetch, embedding, translation)
        key: Cache key (usually generated from input data)
    
    Returns:
        Cached value or None if not found/expired
    """
    full_key = f"{cache_type}:{key}"
    
    # Check memory cache first
    with _cache_lock:
        if full_key in _memory_cache:
            entry = _memory_cache[full_key]
            if not _is_expired(entry):
                return entry.get("value")
            else:
                del _memory_cache[full_key]
    
    # Check file cache
    cache_path = _get_cache_path(cache_type, key)
    if cache_path.exists():
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                entry = json.load(f)
            
            if not _is_expired(entry):
                # Store in memory cache for faster future access
                with _cache_lock:
                    if len(_memory_cache) < MAX_MEMORY_ITEMS:
                        _memory_cache[full_key] = entry
                return entry.get("value")
            else:
                # Remove expired file
                cache_path.unlink(missing_ok=True)
        except (json.JSONDecodeError, IOError):
            pass
    
    return None


def set_cache(cache_type: str, key: str, value: Any, ttl: Optional[int] = None) -> bool:
    """
    Store a value in cache.
    
    Args:
        cache_type: Type of cache
        key: Cache key
        value: Value to cache
        ttl: Time-to-live in seconds (default based on cache_type)
    
    Returns:
        True if successful
    """
    if ttl is None:
        ttl = DEFAULT_TTL.get(cache_type, 3600)
    
    entry = {
        "value": value,
        "created_at": time.time(),
        "expires_at": time.time() + ttl,
        "cache_type": cache_type,
    }
    
    full_key = f"{cache_type}:{key}"
    
    # Store in memory cache
    with _cache_lock:
        if len(_memory_cache) >= MAX_MEMORY_ITEMS:
            # Remove oldest entries
            oldest_keys = sorted(
                _memory_cache.keys(),
                key=lambda k: _memory_cache[k].get("created_at", 0)
            )[:100]
            for old_key in oldest_keys:
                del _memory_cache[old_key]
        
        _memory_cache[full_key] = entry
    
    # Store in file cache
    cache_path = _get_cache_path(cache_type, key)
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        return True
    except IOError as e:
        print(f"[CACHE] Error writing cache: {e}")
        return False


def delete_cache(cache_type: str, key: str) -> bool:
    """Delete a cache entry."""
    full_key = f"{cache_type}:{key}"
    
    with _cache_lock:
        if full_key in _memory_cache:
            del _memory_cache[full_key]
    
    cache_path = _get_cache_path(cache_type, key)
    if cache_path.exists():
        cache_path.unlink()
        return True
    return False


def clear_cache(cache_type: Optional[str] = None) -> int:
    """
    Clear cache entries.
    
    Args:
        cache_type: Specific type to clear, or None for all
    
    Returns:
        Number of entries cleared
    """
    count = 0
    
    with _cache_lock:
        if cache_type:
            keys_to_delete = [k for k in _memory_cache if k.startswith(f"{cache_type}:")]
        else:
            keys_to_delete = list(_memory_cache.keys())
        
        for key in keys_to_delete:
            del _memory_cache[key]
            count += 1
    
    # Clear file cache
    if cache_type:
        type_dir = CACHE_DIR / cache_type
        if type_dir.exists():
            for f in type_dir.glob("*.json"):
                f.unlink()
                count += 1
    else:
        for type_dir in CACHE_DIR.iterdir():
            if type_dir.is_dir():
                for f in type_dir.glob("*.json"):
                    f.unlink()
                    count += 1
    
    return count


def cleanup_expired() -> int:
    """Remove all expired cache entries. Returns count of removed entries."""
    count = 0
    
    # Clean memory cache
    with _cache_lock:
        expired_keys = [k for k, v in _memory_cache.items() if _is_expired(v)]
        for key in expired_keys:
            del _memory_cache[key]
            count += 1
    
    # Clean file cache
    for type_dir in CACHE_DIR.iterdir():
        if type_dir.is_dir():
            for cache_file in type_dir.glob("*.json"):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        entry = json.load(f)
                    if _is_expired(entry):
                        cache_file.unlink()
                        count += 1
                except (json.JSONDecodeError, IOError):
                    cache_file.unlink()
                    count += 1
    
    return count


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    stats = {
        "memory_entries": len(_memory_cache),
        "memory_limit": MAX_MEMORY_ITEMS,
        "cache_dir": str(CACHE_DIR),
        "types": {}
    }
    
    for type_dir in CACHE_DIR.iterdir():
        if type_dir.is_dir():
            cache_type = type_dir.name
            files = list(type_dir.glob("*.json"))
            total_size = sum(f.stat().st_size for f in files)
            stats["types"][cache_type] = {
                "file_count": len(files),
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "ttl_days": DEFAULT_TTL.get(cache_type, 3600) / 86400
            }
    
    return stats


# =========================
# Convenience Functions
# =========================

def cache_verification(claim: str, result: Dict[str, Any], ttl: Optional[int] = None) -> bool:
    """Cache a verification result."""
    key = _generate_key("v", claim.lower().strip())
    return set_cache("verification", key, result, ttl)


def get_cached_verification(claim: str) -> Optional[Dict[str, Any]]:
    """Get cached verification result."""
    key = _generate_key("v", claim.lower().strip())
    result = get_cache("verification", key)
    if result:
        print(f"[CACHE] ✅ HIT: Verification cache for claim")
    return result


def cache_fetch(query: str, source: str, results: Any, ttl: Optional[int] = None) -> bool:
    """Cache fetch results from an API source."""
    key = _generate_key("f", f"{source}:{query.lower().strip()}")
    return set_cache("fetch", key, results, ttl)


def get_cached_fetch(query: str, source: str) -> Optional[Any]:
    """Get cached fetch results."""
    key = _generate_key("f", f"{source}:{query.lower().strip()}")
    result = get_cache("fetch", key)
    if result:
        print(f"[CACHE] ✅ HIT: Fetch cache for {source}")
    return result


def cache_embedding(text: str, embedding: list, ttl: Optional[int] = None) -> bool:
    """Cache an embedding vector."""
    key = _generate_key("e", text[:500])  # Limit text length for key
    return set_cache("embedding", key, embedding, ttl)


def get_cached_embedding(text: str) -> Optional[list]:
    """Get cached embedding."""
    key = _generate_key("e", text[:500])
    return get_cache("embedding", key)


def cache_translation(text: str, target_lang: str, translated: str, ttl: Optional[int] = None) -> bool:
    """Cache a translation."""
    key = _generate_key("t", f"{target_lang}:{text[:500]}")
    return set_cache("translation", key, translated, ttl)


def get_cached_translation(text: str, target_lang: str) -> Optional[str]:
    """Get cached translation."""
    key = _generate_key("t", f"{target_lang}:{text[:500]}")
    return get_cache("translation", key)


# =========================
# Initialization
# =========================

def init_cache():
    """Initialize cache system and cleanup expired entries."""
    print(f"[CACHE] Initializing cache at: {CACHE_DIR}")
    expired = cleanup_expired()
    if expired > 0:
        print(f"[CACHE] Cleaned up {expired} expired entries")
    
    stats = get_cache_stats()
    for cache_type, info in stats["types"].items():
        print(f"[CACHE] {cache_type}: {info['file_count']} entries ({info['total_size_mb']} MB)")


# Run cleanup on import
if __name__ != "__main__":
    # Only run on import, not when executed directly
    try:
        init_cache()
    except Exception as e:
        print(f"[CACHE] Warning: Cache init failed: {e}")


if __name__ == "__main__":
    # Test cache functionality
    print("Testing cache manager...")
    
    # Test verification cache
    test_claim = "Test claim for caching"
    test_result = {"label": "valid", "confidence": 0.9}
    
    cache_verification(test_claim, test_result)
    cached = get_cached_verification(test_claim)
    print(f"Verification cache: {cached}")
    
    # Print stats
    print("\nCache stats:")
    print(json.dumps(get_cache_stats(), indent=2))
