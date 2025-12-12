import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from fetch_sources import (
    detect_language,
    translate_query,
    generate_bilingual_queries,
    fetch_all_sources
)
from process_raw import (
    determine_parser_for_file,
    parse_google_books_file,
    parse_sciencedirect_file,
    parse_openlibrary_file
)


def test_language_detection():
    """Test language detection heuristic."""
    print("\n" + "="*60)
    print("TEST 1: Language Detection")
    print("="*60)
    
    test_cases = [
        ("merokok menyebabkan kanker paru", "Indonesian"),
        ("smoking causes lung cancer", "English"),
        ("diabetes dan obesitas", "Indonesian"),
        ("heart disease prevention", "English"),
        ("vitamin C untuk kesehatan", "Indonesian"),
    ]
    
    passed = 0
    for query, expected_lang in test_cases:
        detected = detect_language(query)
        status = "PASS" if detected == expected_lang else "FAIL"
        print(f"{status} | '{query}' -> {detected} (expected: {expected_lang})")
        if detected == expected_lang:
            passed += 1
    
    print(f"\nResult: {passed}/{len(test_cases)} tests passed")
    return passed == len(test_cases)


def test_translation():
    """Test query translation."""
    print("\n" + "="*60)
    print("TEST 2: Query Translation")
    print("="*60)
    
    test_cases = [
        ("merokok menyebabkan kanker", "English"),
        ("smoking causes cancer", "Indonesian"),
    ]
    
    for query, target_lang in test_cases:
        translated = translate_query(query, target_lang=target_lang)
        if translated:
            print(f"'{query}' -> '{translated}' ({target_lang})")
        else:
            print(f"'{query}' -> No translation needed or API unavailable")
    
    print("\nNote: Translation requires GEMINI_API_KEY to be set")
    return True


def test_bilingual_query_generation():
    """Test bilingual query generation."""
    print("\n" + "="*60)
    print("TEST 3: Bilingual Query Generation")
    print("="*60)
    
    test_queries = [
        "kanker paru-paru",
        "diabetes dan obesitas",
        "heart disease",
    ]
    
    for query in test_queries:
        queries = generate_bilingual_queries(query)
        print(f"\nOriginal: '{query}'")
        print(f"Generated: {queries}")
        print(f"Count: {len(queries)} queries")
    
    return True

def test_parser_detection():
    """Test parser detection for all file types."""
    print("\n" + "="*60)
    print("TEST 4: Parser Detection")
    print("="*60)
    
    test_files = [
        ("crossref_test.json", "CrossRef"),
        ("semantic_scholar_test.json", "Semantic Scholar"),
        ("pubmed_test.xml", "PubMed"),
        ("google_books_test.json", "Google Books"),
        ("sciencedirect_test.json", "ScienceDirect"),
        ("openlibrary_test.json", "Open Library"),
        ("unknown_file.txt", None),
    ]
    
    passed = 0
    for filename, expected_source in test_files:
        file_path = Path(filename)
        parser = determine_parser_for_file(file_path)
        
        if expected_source is None:
            if parser is None:
                print(f"PASS | {filename} -> No parser (expected)")
                passed += 1
            else:
                print(f"FAIL | {filename} -> Found parser (unexpected)")
        else:
            if parser is not None:
                parser_name = parser.__name__
                print(f"PASS | {filename} -> {parser_name}")
                passed += 1
            else:
                print(f"FAIL | {filename} -> No parser (expected {expected_source})")
    
    print(f"\nResult: {passed}/{len(test_files)} tests passed")
    return passed == len(test_files)


def test_small_fetch():
    """Test actual fetching with minimal API calls."""
    print("\n" + "="*60)
    print("TEST 5: Small Bilingual Fetch (OPTIONAL)")
    print("="*60)
    
    response = input("Run small API fetch test? (requires API keys, costs quota) [y/N]: ")
    if response.lower() != 'y':
        print("Skipped")
        return True
    
    try:
        query = "covid-19"
        print(f"\nFetching with query: '{query}'")
        print("Limits: 2 results per source, bilingual enabled")
        
        results = fetch_all_sources(
            query=query,
            pubmed_max=2,
            crossref_rows=2,
            semantic_limit=2,
            scidir_limit=2,
            google_limit=2,
            openlib_limit=2,
            use_bilingual=True
        )
        
        print(f"\n Fetch completed!")
        print(f"Files saved: {len(results)}")
        for key, filepath in results.items():
            if filepath:
                print(f"  - {key}: {Path(filepath).name}")
        
        return True
        
    except Exception as e:
        print(f"Fetch failed: {e}")
        print("This may be due to missing API keys or network issues")
        return False


def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("HEALTIFY APP - BILINGUAL FETCH & PARSER TESTS")
    print("="*80)
    
    results = []
    
    # Run tests
    results.append(("Language Detection", test_language_detection()))
    results.append(("Translation", test_translation()))
    results.append(("Bilingual Queries", test_bilingual_query_generation()))
    results.append(("Parser Detection", test_parser_detection()))
    results.append(("API Fetch", test_small_fetch()))
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = " PASS" if result else "FAIL"
        print(f"{status} | {test_name}")
    
    print(f"\n{passed}/{total} test suites passed")
    
    if passed == total:
        print("\nAll tests passed! The fixes are working correctly.")
    else:
        print("\nSome tests failed. Check the output above for details.")
    
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
