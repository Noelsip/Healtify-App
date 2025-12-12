import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

# Load environment
BASE = Path(__file__).parents[1]
load_dotenv(dotenv_path=BASE / ".env")

# Connect to database
try:
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )
    
    cur = conn.cursor()
    
    # Check dimensions
    print("=" * 60)
    print("DATABASE EMBEDDING DIMENSIONS CHECK")
    print("=" * 60)
    
    cur.execute("""
        SELECT 
            vector_dims(embedding) as dimension_count,
            COUNT(*) as num_vectors
        FROM embeddings 
        WHERE embedding IS NOT NULL
        GROUP BY vector_dims(embedding)
        ORDER BY dimension_count;
    """)
    
    results = cur.fetchall()
    
    if not results:
        print("\nNo embeddings found in database!")
    else:
        print("\nEmbedding Dimensions in Database:")
        print("-" * 60)
        total_vectors = 0
        for dims, count in results:
            print(f"  {dims} dimensions: {count:,} vectors")
            total_vectors += count
        
        print("-" * 60)
        print(f"  TOTAL: {total_vectors:,} vectors")
        
        # Check if we have mismatched dimensions
        if len(results) > 1:
            print("\n⚠️  WARNING: Multiple dimension sizes detected!")
            print("   This can cause query errors.")
        
        # Sample some embeddings
        print("\n" + "=" * 60)
        print("SAMPLE EMBEDDINGS")
        print("=" * 60)
        
        cur.execute("""
            SELECT 
                doc_id,
                safe_id,
                vector_dims(embedding) as dims,
                LEFT(text, 80) as sample_text
            FROM embeddings
            WHERE embedding IS NOT NULL
            ORDER BY RANDOM()
            LIMIT 3;
        """)
        
        samples = cur.fetchall()
        for doc_id, safe_id, dims, text in samples:
            print(f"\nDoc ID: {doc_id}")
            print(f"  Dimensions: {dims}")
            print(f"  Text: {text}...")
    
    # Recommendations
    print("\n" + "=" * 60)
    print("RECOMMENDATIONS")
    print("=" * 60)
    
    if not results:
        print("\nNo embeddings yet - you can use any embedding model")
        print("Recommended: Add GEMINI_API_KEY for best results")
    elif len(results) == 1:
        dims = results[0][0]
        if dims == 768:
            print(f"\nDatabase has {dims}-dim vectors (Gemini gemini-embedding-001)")
            print("   → Add GEMINI_API_KEY to .env")
            print("   → OR use sentence-transformers: all-mpnet-base-v2 (768-dim)")
        elif dims == 384:
            print(f"\nDatabase has {dims}-dim vectors (sentence-transformers)")
            print("   → Use model: all-MiniLM-L6-v2 (384-dim)")
        elif dims == 3072:
            print(f"\nDatabase has {dims}-dim vectors (Unusual!)")
            print("   This might be from:")
            print("   - Gemini 2.0 batch embeddings")
            print("   - Multiple embeddings concatenated")
            print("   - Custom embedding configuration")
            print("\n   BEST FIX:")
            print("   → Add GEMINI_API_KEY with same model used for initial embedding")
            print("   → OR truncate table and re-embed with standard 768-dim model")
        else:
            print(f"\nDatabase has {dims}-dim vectors (Custom)")
            print(f"You need a model that outputs {dims} dimensions")
            print("OR re-embed database with standard model")
    
    cur.close()
    conn.close()
    
    print("\n" + "=" * 60)
    
except Exception as e:
    print(f"Error: {e}")
    print("\nMake sure:")
    print("  1. Database is running")
    print("  2. .env has correct DB credentials")
    print("  3. pgvector extension is installed")
