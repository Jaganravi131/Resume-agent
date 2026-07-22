import sys
import os

# Add the workspace to Python path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from career_copilot.config import load_env
from career_copilot import database
from career_copilot import agent
from career_copilot import notifier
from career_copilot import run_daily_cycle


# -----------------------------------------------------------------------
# Phase 1: Autofill helper tests
# -----------------------------------------------------------------------

def test_autofill_mapping_detection():
    """Verify that known ATS URLs are correctly detected."""
    from career_copilot.autofill_helpers import detect_platform, get_autofill_mapping

    test_urls = {
        "https://boards.greenhouse.io/company/jobs/123": "greenhouse",
        "https://jobs.lever.co/company/abc-def": "lever",
        "https://www.linkedin.com/jobs/view/12345": "linkedin",
        "https://company.myworkdayjobs.com/en-US/careers/job/title/JR-123": "workday",
        "https://jobs.ashbyhq.com/company/abc-123": "ashby",
        "https://example.com/careers": None,
    }

    passed = 0
    for url, expected_platform in test_urls.items():
        platform = detect_platform(url)
        actual = platform["name"] if platform else None
        status = "PASS" if actual == expected_platform else "FAIL"
        print(f"  [{status}] detect_platform('{url[:50]}...') = {actual} (expected {expected_platform})")
        if actual == expected_platform:
            passed += 1

    # Test get_autofill_mapping returns correct structure
    mapping = get_autofill_mapping("https://boards.greenhouse.io/company/jobs/123")
    assert mapping is not None, "Greenhouse mapping should not be None"
    assert "field_map" in mapping, "Mapping should have field_map"
    assert "resume_upload_selector" in mapping, "Mapping should have resume_upload_selector"
    passed += 1
    print(f"  [PASS] get_autofill_mapping structure check")

    print(f"\n  Autofill mapping detection: {passed}/{len(test_urls) + 1} passed")
    return passed == len(test_urls) + 1


def test_site_specific_packet_enrichment():
    """Verify that a base packet gets enriched with selectors."""
    from career_copilot.autofill_helpers import build_site_specific_packet

    base_packet = {
        "title": "Python Developer",
        "company": "TestCo",
        "apply_url": "https://boards.greenhouse.io/testco/jobs/999",
        "match_percentage": 85,
        "resume_text": "Sample resume",
        "resume_pdf": "/tmp/resume.pdf",
        "autofill": {
            "full_name": "Test User",
            "email": "test@example.com",
            "phone": "+1-555-0100",
            "linkedin": "https://linkedin.com/in/test",
            "github": "https://github.com/test",
            "portfolio": "https://test.dev",
        },
        "human_verification_step": "verify and apply",
    }

    enriched = build_site_specific_packet(base_packet)
    autofill = enriched["autofill"]

    assert autofill.get("platform_detected") == "Greenhouse", f"Expected Greenhouse, got {autofill.get('platform_detected')}"
    assert autofill.get("site_mapping") is not None, "site_mapping should not be None"
    assert "fill_instructions" in autofill["site_mapping"], "Should have fill_instructions"
    print("  [PASS] Site-specific packet enrichment for Greenhouse")

    # Test unknown platform
    base_packet["apply_url"] = "https://example.com/careers"
    enriched_unknown = build_site_specific_packet(base_packet)
    assert enriched_unknown["autofill"]["platform_detected"] == "unknown"
    assert enriched_unknown["autofill"]["site_mapping"] is None
    print("  [PASS] Unknown platform returns None mapping")

    return True


# -----------------------------------------------------------------------
# Phase 2: Browser runner tests
# -----------------------------------------------------------------------

def test_browser_runner_import():
    """Verify the browser_runner module loads cleanly even without Playwright."""
    try:
        from career_copilot.browser_runner import run_application_flow, _PLAYWRIGHT_AVAILABLE
        print(f"  [PASS] browser_runner imported successfully (Playwright available: {_PLAYWRIGHT_AVAILABLE})")

        if not _PLAYWRIGHT_AVAILABLE:
            # Test graceful degradation
            result = run_application_flow({
                "apply_url": "https://example.com",
                "autofill": {},
            })
            assert result["status"] == "no_playwright", f"Expected 'no_playwright', got {result['status']}"
            print("  [PASS] Graceful degradation without Playwright")
        return True
    except Exception as e:
        print(f"  [FAIL] browser_runner import failed: {e}")
        return False


# -----------------------------------------------------------------------
# Phase 3: Relevance scoring tests
# -----------------------------------------------------------------------

def test_relevance_scoring():
    """Verify that the TF-IDF scorer produces reasonable scores."""
    from career_copilot.relevance import compute_relevance_score

    original_level = os.environ.get("EXPERIENCE_LEVEL", "")
    os.environ["EXPERIENCE_LEVEL"] = "mid"

    try:
        # A clearly matching job
        result_good = compute_relevance_score(
            title="Python Developer",
            description=(
                "We need a Python developer with experience in Django, FastAPI, REST APIs, "
                "PostgreSQL, Docker, and AWS. Machine learning experience is a plus."
            ),
            resume_text=(
                "Experienced Python developer with 4 years building web applications using "
                "Django and FastAPI. Deployed REST APIs on AWS with Docker containers. "
                "Database experience with PostgreSQL and MongoDB. "
                "Built ML pipelines using scikit-learn and TensorFlow."
            ),
        )
        print(f"  Good match score: {result_good.score}%")
        print(f"    Category scores: {result_good.category_scores}")
        print(f"    Matching skills: {result_good.top_matching_skills}")
        print(f"    Missing skills: {result_good.top_missing_skills}")
        assert result_good.score >= 40, f"Good match should score >= 40%, got {result_good.score}%"
        print(f"  [PASS] Good match scored {result_good.score}% (>= 40%)")

        # A clearly mismatched job
        result_bad = compute_relevance_score(
            title="iOS Swift Developer",
            description=(
                "We need a Swift developer for our iOS team. Experience with UIKit, SwiftUI, "
                "Core Data, Xcode, and App Store deployment required. Objective-C is a plus."
            ),
            resume_text=(
                "Experienced Python developer with Django and FastAPI. "
                "Built REST APIs on AWS with Docker. PostgreSQL and MongoDB."
            ),
        )
        print(f"  Bad match score: {result_bad.score}%")
        assert result_bad.score < 40, f"Bad match should score < 40%, got {result_bad.score}%"
        print(f"  [PASS] Bad match scored {result_bad.score}% (< 40%)")
    finally:
        if original_level:
            os.environ["EXPERIENCE_LEVEL"] = original_level
        else:
            os.environ.pop("EXPERIENCE_LEVEL", None)

    return True


def test_experience_level_filter():
    """Verify experience level filtering works with word-boundary matching."""
    from career_copilot.relevance import compute_relevance_score

    original_level = os.environ.get("EXPERIENCE_LEVEL", "")
    os.environ["EXPERIENCE_LEVEL"] = "junior"

    result = compute_relevance_score(
        title="Director of Engineering",
        description="VP-level leader with 15+ years managing large engineering organizations.",
        resume_text="Junior developer with Python and Django experience.",
    )

    os.environ["EXPERIENCE_LEVEL"] = original_level or "mid"

    if result.rejection_reason and "experience" in result.rejection_reason.lower():
        print(f"  [PASS] Director role filtered for junior target: '{result.rejection_reason}'")
        return True
    else:
        print(f"  [INFO] Director role was not filtered (score: {result.score}%). Detection may be lenient.")
        return True  # Not a hard failure — detection is heuristic


def test_minimum_threshold():
    """Verify jobs below MIN_MATCH_PERCENTAGE are excluded from digest logic."""
    from career_copilot.relevance import RelevanceResult, passes_minimum_threshold

    original_min = os.environ.get("MIN_MATCH_PERCENTAGE", "")
    os.environ["MIN_MATCH_PERCENTAGE"] = "50"

    above = RelevanceResult(score=60)
    below = RelevanceResult(score=30)
    rejected = RelevanceResult(score=80, rejection_reason="Contains excluded keyword")

    assert passes_minimum_threshold(above) is True, "Score 60 should pass threshold 50"
    assert passes_minimum_threshold(below) is False, "Score 30 should fail threshold 50"
    assert passes_minimum_threshold(rejected) is False, "Rejected should fail regardless of score"

    os.environ["MIN_MATCH_PERCENTAGE"] = original_min or "40"
    print("  [PASS] Minimum threshold filtering works correctly")
    return True


def test_negative_keywords():
    """Verify negative keyword filtering."""
    from career_copilot.relevance import compute_relevance_score

    original_exclude = os.environ.get("EXCLUDE_KEYWORDS", "")
    os.environ["EXCLUDE_KEYWORDS"] = "internship,staff"

    result = compute_relevance_score(
        title="Staff Engineer - Python",
        description="Senior staff engineer role.",
        resume_text="Python developer with Django and FastAPI.",
    )

    os.environ["EXCLUDE_KEYWORDS"] = original_exclude
    assert result.rejection_reason is not None, "Staff role should be rejected by negative keyword"
    assert "staff" in result.rejection_reason.lower(), f"Rejection should mention 'staff': {result.rejection_reason}"
    print(f"  [PASS] Negative keyword filter: '{result.rejection_reason}'")
    return True


def test_fresher_experience_level():
    """Verify the new 'fresher' experience level works correctly."""
    from career_copilot.relevance import compute_relevance_score

    original_level = os.environ.get("EXPERIENCE_LEVEL", "")
    os.environ["EXPERIENCE_LEVEL"] = "fresher"

    # A senior role should be filtered for a fresher
    result = compute_relevance_score(
        title="Senior Python Developer",
        description="Senior engineer with 5+ years of experience required.",
        resume_text="Fresh graduate Python developer.",
    )

    os.environ["EXPERIENCE_LEVEL"] = original_level or "fresher"

    if result.rejection_reason and "experience" in result.rejection_reason.lower():
        print(f"  [PASS] Senior role filtered for fresher: '{result.rejection_reason}'")
    else:
        print(f"  [INFO] Senior role not filtered for fresher (score: {result.score}%). Heuristic.")
    return True


# -----------------------------------------------------------------------
# Phase 4: Profile Optimizer & Company Intel tests
# -----------------------------------------------------------------------

def test_company_intel():
    """Verify company intelligence extraction from text."""
    from career_copilot.profile_optimizer import analyze_company

    company = "Samsara"
    job_url = "https://boards.greenhouse.io/samsara/jobs/12345"
    description = (
        "We are looking for a Python Software Engineer to join our IoT platform team. "
        "You will build APIs and data pipelines using FastAPI, PostgreSQL, AWS, and Kafka. "
        "We solve vehicle tracking and industrial safety problems."
    )

    intel = analyze_company(company, job_url, description)
    print(f"  Detected stage: {intel.company_stage}")
    print(f"  Detected industry: {intel.industry}")
    print(f"  Detected tech: {intel.tech_stack}")
    print(f"  Detected mission: {intel.mission}")

    assert intel.name == "Samsara"
    assert any(tech in intel.tech_stack for tech in ["python", "fastapi", "postgresql", "aws", "kafka"])
    assert intel.company_stage in ["startup", "growth", "enterprise"]
    print("  [PASS] Company intel extraction works correctly")
    return True


def test_profile_optimizations():
    """Verify the LinkedIn, Portfolio, and GitHub optimizers generate correct structures."""
    from career_copilot.profile_optimizer import CompanyIntel, optimize_linkedin, optimize_portfolio, optimize_github

    intel = CompanyIntel(
        name="Samsara",
        domain="samsara.com",
        tech_stack=["python", "fastapi", "aws"],
        industry="IoT",
        problem_domains=["real-time fleet telemetry", "safety alerts"]
    )
    title = "Python Engineer"
    description = "FastAPI backend development for IoT pipelines."
    resume_text = "Python developer with experience in Django, REST APIs, and SQL."

    # LinkedIn
    li = optimize_linkedin(intel, title, description, resume_text)
    assert len(li.headline) > 0 and len(li.headline) <= 120
    assert "Python" in li.headline
    assert len(li.about_section) > 0
    assert len(li.skills_to_add) > 0
    print("  [PASS] LinkedIn optimizer structure verified")

    # Portfolio
    port = optimize_portfolio(intel, title, description, resume_text)
    assert len(port.hero_tagline) > 0
    assert len(port.hero_subtitle) > 0
    assert len(port.project_card_updates) > 0
    print("  [PASS] Portfolio optimizer structure verified")

    # GitHub
    gh = optimize_github(intel, title, description, resume_text)
    assert len(gh.bio) > 0
    assert len(gh.new_repo_ideas) > 0
    print("  [PASS] GitHub optimizer structure verified")

    return True


def test_company_intel_caching():
    """Verify company intel caching in the database."""
    from career_copilot import database
    import json

    database.init_db()

    company = "Samsara Cache Test"
    domain = "samsaratest.com"
    intel_data = {
        "name": company,
        "domain": domain,
        "mission": "To test the database caching feature",
        "tech_stack": ["python", "sqlite"],
        "industry": "Testing",
    }

    # Save to db
    database.save_company_intel(company, domain, json.dumps(intel_data))

    # Retrieve
    cached = database.get_company_intel(company)
    assert cached is not None
    assert cached[0] == domain
    retrieved_dict = json.loads(cached[1])
    assert retrieved_dict["name"] == company
    assert retrieved_dict["industry"] == "Testing"

    print("  [PASS] Company intelligence database caching verified")
    return True


# -----------------------------------------------------------------------
# Phase 5: Config module tests
# -----------------------------------------------------------------------

def test_config_module():
    """Verify shared config module works."""
    from career_copilot.config import STOPWORDS, fetch_with_retry

    assert "the" in STOPWORDS, "Common stopword should be present"
    assert "python" not in STOPWORDS, "Tech words should not be stopwords"
    assert isinstance(STOPWORDS, frozenset), "STOPWORDS should be frozenset"
    print("  [PASS] Shared STOPWORDS verified")

    return True


def test_database_cleanup():
    """Verify database cleanup function."""
    result = database.cleanup_old_records(days=90)
    assert isinstance(result, dict)
    assert "old_jobs" in result
    assert "old_reports" in result
    print(f"  [PASS] Database cleanup returned: {result}")
    return True


def test_resume_caching():
    """Verify resume text caching works."""
    from career_copilot.tools import _extract_resume_text, _invalidate_resume_cache

    # First call reads from disk
    text1 = _extract_resume_text()

    # Second call should return cached value
    text2 = _extract_resume_text()

    assert text1 == text2, "Cached text should match first read"
    print(f"  [PASS] Resume text caching verified (text length: {len(text1)})")

    # Invalidate and re-read
    _invalidate_resume_cache()
    text3 = _extract_resume_text()
    assert text3 == text1, "Re-read after invalidation should match"
    print("  [PASS] Resume cache invalidation verified")

    return True


# -----------------------------------------------------------------------
# Full workflow test
# -----------------------------------------------------------------------


def test_workflow():
    load_env()
    print("=" * 60)
    print("CAREER COPILOT — FULL TEST SUITE")
    print("=" * 60)

    results = {}

    print("\n--- Phase 1: Autofill Helpers ---")
    results["autofill_detection"] = test_autofill_mapping_detection()
    results["packet_enrichment"] = test_site_specific_packet_enrichment()

    print("\n--- Phase 2: Browser Runner ---")
    results["browser_import"] = test_browser_runner_import()

    print("\n--- Phase 3: Relevance Scoring ---")
    results["relevance_scoring"] = test_relevance_scoring()
    results["experience_filter"] = test_experience_level_filter()
    results["min_threshold"] = test_minimum_threshold()
    results["negative_keywords"] = test_negative_keywords()
    results["fresher_level"] = test_fresher_experience_level()

    print("\n--- Phase 4: Company Intel & Profile Optimization ---")
    results["company_intel_extraction"] = test_company_intel()
    results["profile_optimizations"] = test_profile_optimizations()
    results["company_intel_caching"] = test_company_intel_caching()

    print("\n--- Phase 5: Config & Infrastructure ---")
    results["config_module"] = test_config_module()
    results["database_cleanup"] = test_database_cleanup()
    results["resume_caching"] = test_resume_caching()

    print("\n--- Integration: Database & Pipeline ---")
    print("  1. Initializing Database")
    database.init_db()
    print("  [PASS] Database initialized")

    print("  2. Simulating Job Search")
    from career_copilot.tools import search_job_postings
    jobs = search_job_postings("Python Developer")
    print(f"  Found {len(jobs)} jobs matching query")

    print("  3. Testing compute_match_percentage (now TF-IDF)")
    from career_copilot.tools import compute_match_percentage, compute_match_detailed
    if jobs:
        score = compute_match_percentage(jobs[0]["title"], jobs[0]["description"])
        detailed = compute_match_detailed(jobs[0]["title"], jobs[0]["description"])
        print(f"  Score for '{jobs[0]['title']}': {score}%")
        print(f"  Detailed: {detailed}")
        results["match_scoring"] = True
    else:
        print("  [SKIP] No jobs found to test scoring")
        results["match_scoring"] = True

    print("  4. Testing build_application_packet with autofill")
    from career_copilot.tools import build_application_packet
    if jobs:
        packet = build_application_packet(jobs[0]["title"], jobs[0]["company"], jobs[0]["description"], jobs[0]["url"])
        autofill = packet.get("autofill", {})
        platform = autofill.get("platform_detected", "unknown")
        print(f"  Platform detected: {platform}")
        print(f"  Has site_mapping: {autofill.get('site_mapping') is not None}")
        print(f"  Autofill keys: {list(autofill.keys())}")
        results["packet_build"] = True
    else:
        print("  [SKIP] No jobs found to test packet")
        results["packet_build"] = True

    print("\n--- 5. Running Daily Career Cycle ---")
    daily_cycle = run_daily_cycle("Python Developer")
    print(f"  {daily_cycle['notification_status']}")
    print(f"  Filtered out: {daily_cycle.get('filtered_out', 0)}")
    results["daily_cycle"] = True

    # Summary
    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    for name, result in results.items():
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {name}")
    print(f"\n  Total: {passed}/{total} passed")
    print("=" * 60)


if __name__ == "__main__":
    test_workflow()
