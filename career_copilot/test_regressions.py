"""Hermetic regression tests for the reliability fixes (no network, no LLM).

Each test pins a bug from PROJECT_REPORT.md §7/§8/§11 that was fixed, so it can
never silently come back. Run directly:

    python career_copilot/test_regressions.py

Also runs the offline unit tests from test_career_copilot (excluding the
network-dependent test_workflow). Exit code 0 only when everything passes.
"""

from __future__ import annotations

import json
import os
import sys
import types
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- Stub google.adk so the package imports without the SDK -----------------
try:
    import google  # noqa: F401
except ImportError:
    google = types.ModuleType("google")
    sys.modules["google"] = google

if not hasattr(google, "adk"):
    adk_mod = types.ModuleType("google.adk")
    adk_mod.agents = types.ModuleType("google.adk.agents")
    adk_mod.agents.llm_agent = types.ModuleType("google.adk.agents.llm_agent")

    class _StubAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    adk_mod.agents.llm_agent.Agent = _StubAgent  # type: ignore
    google.adk = adk_mod  # type: ignore
    sys.modules["google.adk"] = adk_mod
    sys.modules["google.adk.agents"] = adk_mod.agents
    sys.modules["google.adk.agents.llm_agent"] = adk_mod.agents.llm_agent

from career_copilot import database, notifier  # noqa: E402
from career_copilot.config import get_candidate_profile  # noqa: E402


# ---------------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------------

def test_cleanup_date_format() -> bool:
    """Bug #7: cleanup compared local ISO 'T' strings against SQLite UTC
    ' ' strings and deleted cutoff-day rows prematurely."""
    database.init_db()
    now = datetime.utcnow()
    old_id = database.add_job("Old Cleanup Job", "Acme", "Remote",
                              f"https://cleanup-test.example/old-{now.timestamp()}", "desc")
    new_id = database.add_job("New Cleanup Job", "Acme", "Remote",
                              f"https://cleanup-test.example/new-{now.timestamp()}", "desc")
    with database.get_connection() as conn:
        cur = conn.cursor()
        # 200 days old (UTC, SQLite format) — must be deleted
        old_ts = (now - timedelta(days=200)).strftime("%Y-%m-%d %H:%M:%S")
        # 80 days old — must survive (inside the 90-day window)
        new_ts = (now - timedelta(days=80)).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            "UPDATE jobs SET status='applied', created_at=? WHERE title='Old Cleanup Job'",
            (old_ts,),
        )
        cur.execute(
            "UPDATE jobs SET status='applied', created_at=? WHERE title='New Cleanup Job'",
            (new_ts,),
        )
        conn.commit()

    database.cleanup_old_records(days=90)
    with database.get_connection() as conn:
        rows = conn.cursor().execute(
            "SELECT title FROM jobs WHERE title LIKE '%Cleanup Job'"
        ).fetchall()
    titles = {r[0] for r in rows}
    assert "Old Cleanup Job" not in titles, "200-day-old row must be deleted"
    assert "New Cleanup Job" in titles, "80-day-old row must survive (was a date-format bug)"
    print("  [PASS] cleanup cutoff uses matching UTC formats (no premature deletion)")
    return True


def test_invalid_status_rejected() -> bool:
    """Bug #15: job status vocabulary allowed bogus values like 'drafted'."""
    database.init_db()
    database.add_job("Status Test Job", "Acme", "Remote",
                     f"https://cleanup-test.example/status-{os.urandom(4).hex()}", "desc")
    with database.get_connection() as conn:
        job_id = conn.cursor().execute(
            "SELECT id FROM jobs WHERE title='Status Test Job'"
        ).fetchone()[0]

    assert database.update_job_status(job_id, "drafted-not-a-status") is False, \
        "invalid job status must be rejected"
    assert database.update_job_status(job_id, "applied") is True, "valid status must be accepted"
    assert database.update_job_status_by_url("https://nope.example/x", "bogus") == 0
    for status in database.ALLOWED_JOB_STATUSES:
        assert database.update_job_status(job_id, status) is True, f"{status} should be allowed"
    print("  [PASS] job status transitions validated against ALLOWED_JOB_STATUSES")
    return True


def test_application_resume_column() -> bool:
    """Bug #14: resume text was stuffed into the notes column."""
    database.init_db()
    job_key = os.urandom(4).hex()
    database.add_job("App Schema Job", "Acme", "Remote",
                     f"https://cleanup-test.example/app-{job_key}", "desc")
    with database.get_connection() as conn:
        job_id = conn.cursor().execute(
            "SELECT id FROM jobs WHERE title='App Schema Job'"
        ).fetchone()[0]

    database.save_application(job_id, "https://apply.example/1", "drafted",
                              "first note", resume_text="RESUME-BODY-1")
    first_created = None
    with database.get_connection() as conn:
        row = conn.cursor().execute(
            "SELECT notes, resume_text, created_at FROM applications WHERE job_id=?",
            (job_id,),
        ).fetchone()
        first_created = row[2]
    assert row[0] == "first note" and row[1] == "RESUME-BODY-1", \
        f"notes and resume_text must be stored separately, got {row[:2]}"

    database.save_application(job_id, "https://apply.example/2", "drafted",
                              "second note", resume_text="RESUME-BODY-2")
    with database.get_connection() as conn:
        row = conn.cursor().execute(
            "SELECT notes, resume_text, created_at FROM applications WHERE job_id=?",
            (job_id,),
        ).fetchone()
    assert row[0] == "second note" and row[1] == "RESUME-BODY-2"
    assert row[2] == first_created, "upsert must preserve original created_at"
    print("  [PASS] resume_text has its own column; upsert preserves created_at")
    return True


def test_candidate_profile_placeholders() -> bool:
    """Bug #16: hard-coded personal PII in fallbacks — must be env-only now."""
    saved = {k: os.environ.pop(k, None) for k in (
        "RESUME_NAME", "RESUME_EMAIL", "RESUME_PHONE",
        "RESUME_LINKEDIN", "RESUME_GITHUB", "RESUME_PORTFOLIO",
    )}
    try:
        profile = get_candidate_profile()
        banned = ("jagan", "8124819503", "jaganravi131", "portfolio-ygig")
        blob = json.dumps(profile).lower()
        for token in banned:
            assert token not in blob, f"personal data leak in profile defaults: {token}"
        assert profile["name"] == "Your Name"
        assert "example" in profile["email"] or "your" in profile["email"]
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print("  [PASS] candidate profile uses neutral placeholders (no hard-coded PII)")
    return True


def test_prep_plan_seven_days() -> bool:
    """Bug #12: '7-day prep plan' was a 4-bullet template."""
    from career_copilot.tools import create_preparation_plan
    os.environ.pop("GOOGLE_API_KEY", None)  # deterministic fallback path
    plan = create_preparation_plan("Backend Engineer", "Python, Django, FastAPI, PostgreSQL, Docker")
    for day in range(1, 8):
        assert f"Day {day}" in plan, f"plan missing Day {day}"
    assert "Practice Q&A" in plan and "FINAL CHECKLIST" in plan
    print("  [PASS] create_preparation_plan returns a full 7-day plan with Q&A")
    return True


def test_coarse_pass_never_calls_llm() -> bool:
    """Bug #20: cost inversion — the cheap pass must never touch the LLM."""
    from career_copilot import relevance

    calls = {"n": 0}

    def _sentinel(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("LLM must not be called in the coarse pass")

    original = relevance._llm_semantic_score
    relevance._llm_semantic_score = _sentinel
    saved_key = os.environ.pop("GOOGLE_API_KEY", None)
    try:
        os.environ["GOOGLE_API_KEY"] = "fake-key-present"  # key exists — must still not call
        from career_copilot.tools import compute_match_detailed
        result = compute_match_detailed(
            "Backend Engineer", "Python Django FastAPI", None, use_llm=False
        )
        assert result["score"] >= 0 and calls["n"] == 0, \
            f"use_llm=False must not call the LLM (calls={calls['n']})"
    finally:
        relevance._llm_semantic_score = original
        os.environ.pop("GOOGLE_API_KEY", None)
        if saved_key is not None:
            os.environ["GOOGLE_API_KEY"] = saved_key
    print("  [PASS] coarse scoring pass is LLM-free (coarse-to-fine cost control)")
    return True


def test_email_url_escaping() -> bool:
    """Bug #8: job URLs were injected unescaped into the email href attribute."""
    evil_url = "https://evil.example/'><script>alert(1)</script><a href='"
    jobs = [(1, "Title & Co", "Acme <b>", "Loc \"x\"", evil_url, "desc", "found", "now")]
    html_body = notifier.build_match_report_email(jobs)
    assert "<script>" not in html_body, "raw script tag must not survive escaping"
    assert "href='https://evil.example/&#x27;&gt;" in html_body or "&gt;" in html_body, \
        "quote and angle brackets must be escaped inside the URL attribute"
    assert "&amp;" in html_body and "&lt;b&gt;" in html_body
    print("  [PASS] notification email escapes URL + all job-controlled strings")
    return True


def test_matches_keys_semantics() -> bool:
    """Bug #10: 'matched_jobs' returned total fetched instead of matched count."""
    import inspect
    from career_copilot import workflow
    src = inspect.getsource(workflow.run_daily_cycle)
    assert '"jobs_fetched": len(digest["jobs"])' in src
    assert '"matched_jobs": len(digest["digest"])' in src
    print("  [PASS] run_daily_cycle reports jobs_fetched and matched_jobs separately")
    return True


def test_ddg_parser_attribute_order_tolerant() -> bool:
    """§8.9: DDG scraping regexes required href-before-class and class as the
    first attribute — any markup shuffle silently returned zero results."""
    from career_copilot import tools
    html = (
        '<a class="result__url js-extra" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fboards.greenhouse.io%2Facme%2Fjobs%2F123">url</a>'
        '<a href="#ignored" class="unrelated">x</a>'
        "<a target=\"_blank\" class='result__a js-title' href='https://x'><b>Senior</b> Python Dev</a>"
        '<a class="result__snippet result__snippet--news">Build <b>APIs</b> with Django.</a>'
    )
    links, titles, snippets = tools._extract_ddg_results(html)
    assert len(links) == 1 and "uddg=" in links[0], \
        "result__url link must be captured regardless of attribute order"
    assert len(titles) == 1 and "Senior" in titles[0]
    assert len(snippets) == 1 and "Django" in snippets[0]
    print("  [PASS] DDG parser is attribute-order tolerant (no silent empty results)")
    return True


def test_jobicy_full_query_first() -> bool:
    """§8.10: Jobicy reduced 'Machine Learning Engineer' to just tag='machine'."""
    from career_copilot import tools
    urls: list[str] = []
    original = tools.fetch_json

    def _fake(url, *args, **kwargs):
        urls.append(url)
        return {"jobs": []}

    tools.fetch_json = _fake
    try:
        assert tools._search_jobicy("Machine Learning Engineer") == []
    finally:
        tools.fetch_json = original
    assert urls and urls[0].lower().endswith("tag=machine+learning+engineer"), \
        f"full query phrase must be tried first, got {urls}"
    assert len(urls) >= 2 and urls[1].lower().endswith("tag=machine"), \
        "primary keyword must be the fallback (legacy recall preserved)"
    print("  [PASS] Jobicy tries the full query phrase before falling back to first keyword")
    return True


def test_filter_api_is_digest_gate() -> bool:
    """§8.4: filter_jobs_by_relevance was dead code while the digest hand-rolled
    the same threshold loop — the digest must route Phase 1 through it."""
    import inspect
    from career_copilot import relevance, tools
    src = inspect.getsource(tools.build_daily_digest)
    assert "filter_jobs_by_relevance" in src, "digest Phase 1 must use the public filter API"

    calls = {"n": 0}

    def _sentinel(*a, **k):
        calls["n"] += 1
        raise AssertionError("LLM must not run in the coarse filter")

    original = relevance._llm_semantic_score
    relevance._llm_semantic_score = _sentinel
    saved_key = os.environ.pop("GOOGLE_API_KEY", None)
    saved_min = os.environ.pop("MIN_MATCH_PERCENTAGE", None)
    try:
        os.environ["GOOGLE_API_KEY"] = "fake-key-present"
        jobs = [
            {"title": "Python Backend Engineer", "company": "A", "location": "R",
             "url": "https://a.example/1",
             "description": "python django fastapi backend api engineer"},
            {"title": "Executive Chef", "company": "B", "location": "R",
             "url": "https://b.example/2",
             "description": "kitchen menu recipes cooking cuisine tasting plating"},
        ]
        passed, filtered = relevance.filter_jobs_by_relevance(
            jobs, "python django fastapi backend engineer", use_llm=False
        )
    finally:
        relevance._llm_semantic_score = original
        os.environ.pop("GOOGLE_API_KEY", None)
        if saved_key is not None:
            os.environ["GOOGLE_API_KEY"] = saved_key
        if saved_min is not None:
            os.environ["MIN_MATCH_PERCENTAGE"] = saved_min
    assert calls["n"] == 0, "coarse filter must never call the LLM"
    assert [j["title"] for j in passed] == ["Python Backend Engineer"], \
        f"only the matching job may pass, got {[j['title'] for j in passed]}"
    assert len(filtered) == 1 and "relevance" in passed[0]
    assert isinstance(passed[0]["match_percentage"], (int, float))
    print("  [PASS] digest routes Phase 1 through filter_jobs_by_relevance (LLM-free)")
    return True


def test_scheduler_once_mode() -> bool:
    """§8.7: scheduler was a keep-alive loop only — no cron-friendly single run."""
    from career_copilot import scheduler
    calls: list[str] = []
    original = scheduler.workflow.run_daily_cycle
    saved_q = os.environ.pop("JOB_SEARCH_QUERY", None)
    try:
        scheduler.workflow.run_daily_cycle = lambda q: (calls.append(q), {"notification_status": "mock-ok"})[1]
        assert scheduler.run_once("Data Engineer") == 0, "success must return exit code 0"

        def _boom(q):
            raise RuntimeError("boom")

        scheduler.workflow.run_daily_cycle = _boom
        assert scheduler.run_once("Data Engineer") == 1, "failure must return exit code 1"
    finally:
        scheduler.workflow.run_daily_cycle = original
        if saved_q is not None:
            os.environ["JOB_SEARCH_QUERY"] = saved_q
    assert calls == ["Data Engineer"], "exactly one cycle must run"
    print("  [PASS] scheduler --once runs exactly one cycle and reports exit status")
    return True


def test_application_status_machine() -> bool:
    """§8.11: application status accepted any string and never advanced past
    'drafted'. (Also pins: add_job returns a bool, NOT an id — callers must
    re-SELECT; this test previously passed by accident via True→1 collision.)"""
    database.init_db()
    url = f"https://cleanup-test.example/appstatus-{os.urandom(4).hex()}"
    database.add_job("App Status Machine Job", "Acme", "Remote", url, "desc")
    with database.get_connection() as conn:
        job_id = conn.cursor().execute(
            "SELECT id FROM jobs WHERE url=?", (url,)
        ).fetchone()[0]
    database.save_application(job_id, "https://apply.example/x", "not-a-real-status", "notes")
    with database.get_connection() as conn:
        row = conn.cursor().execute(
            "SELECT status FROM applications WHERE job_id=?", (job_id,)
        ).fetchone()
    assert row and row[0] == "drafted", \
        f"invalid status must be coerced to 'drafted', got {row and row[0]!r}"

    assert database.update_application_status(job_id, "hired-nope") is False, \
        "invalid transitions vocabulary must be rejected"
    assert database.update_application_status(job_id, "ready_to_submit") is True
    assert database.update_application_status(job_id, "submitted") is True
    with database.get_connection() as conn:
        status = conn.cursor().execute(
            "SELECT status FROM applications WHERE job_id=?", (job_id,)
        ).fetchone()[0]
    assert status == "submitted"
    for s in database.ALLOWED_APPLICATION_STATUSES:
        assert database.update_application_status(job_id, s) is True, f"{s} must be allowed"
    print("  [PASS] application status machine: validated lifecycle advancement")
    return True


def test_smtp_connection_timeout() -> bool:
    """CRITICAL (post-audit sweep): smtplib.SMTP had NO timeout — a hung SMTP
    server froze the daily scheduler thread forever (silent total automation
    failure). Must connect with a bounded timeout."""
    import smtplib
    from career_copilot import notifier
    captured: dict = {}

    class _FakeSMTP:
        def __init__(self, host, port, timeout=None, **kwargs):
            captured["timeout"] = timeout
            raise OSError("connection refused (fake)")

    original_smtp = smtplib.SMTP
    notifier.smtplib.SMTP = _FakeSMTP
    keys = ("SMTP_SERVER", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "RECEIVER_EMAIL")
    saved = {k: os.environ.get(k) for k in keys}
    os.environ.update({
        "SMTP_SERVER": "smtp.example", "SMTP_PORT": "587",
        "SMTP_USERNAME": "u", "SMTP_PASSWORD": "p", "RECEIVER_EMAIL": "r@example.com",
    })
    try:
        assert notifier.send_email("subj", "<b>body</b>") is False, \
            "failed connection must return False, not raise"
    finally:
        notifier.smtplib.SMTP = original_smtp
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    assert captured.get("timeout") is not None and captured["timeout"] <= 30, \
        f"SMTP must connect with a bounded timeout, got {captured.get('timeout')!r}"
    print("  [PASS] SMTP connection uses a bounded timeout (no infinite pipeline hang)")
    return True


def test_resume_filename_collision_proof() -> bool:
    """CRITICAL (post-audit sweep): external job titles flow into filenames —
    non-ASCII titles sanitized to an empty string (every such job overwrote
    resume_.pdf) and very long titles could exceed filesystem limits and crash
    the digest."""
    from career_copilot import tools
    f1 = tools._build_resume_filename("データエンジニア", "株式会社")
    f2 = tools._build_resume_filename("机器学习工程师", "某公司")
    assert f1 != f2, "distinct non-ASCII jobs must not collide onto one filename"
    assert f1.startswith("resume_") and f1.endswith(".pdf") and "/" not in f1
    long_name = tools._build_resume_filename("Senior " * 60 + "Engineer", "Acme " * 40 + "Corp")
    assert len(long_name) <= 120, f"filename must respect filesystem limits, got {len(long_name)}"
    ascii_name = tools._build_resume_filename("Python Developer", "Acme")
    assert "python_developer" in ascii_name
    print("  [PASS] resume filenames are collision-proof and filesystem-safe")
    return True


def test_company_analyzer_dead_domain_shortcircuit() -> bool:
    """Post-audit: analyze_company tried 4 about-page URLs even when the
    homepage fetch failed — dead domains cost ~2.5 min each in a digest."""
    from career_copilot import profile_optimizer as profopt
    calls: list[str] = []
    original = profopt._fetch_page_text

    def _dead(url, *a, **k):
        calls.append(url)
        return ""

    profopt._fetch_page_text = _dead
    try:
        intel = profopt.analyze_company("DeadCo", "https://boards.greenhouse.io/deadco/jobs/1", "desc")
    finally:
        profopt._fetch_page_text = original
    assert len(calls) == 1, \
        f"dead domain must fetch homepage only, got {len(calls)} fetches: {calls}"
    assert intel.raw_homepage_text == ""

    calls.clear()
    pages = {"https://liveco.example": "x" * 500, "https://liveco.example/about": "y" * 400}

    def _live(url, *a, **k):
        calls.append(url)
        return pages.get(url, "")

    profopt._fetch_page_text = _live
    try:
        intel = profopt.analyze_company("LiveCo", "https://liveco.example/jobs/1", "desc")
    finally:
        profopt._fetch_page_text = original
    assert len(calls) >= 2 and intel.raw_about_text, \
        "live domain must still attempt about pages"
    print("  [PASS] company analyzer short-circuits dead domains (1 fetch, not 5)")
    return True


def test_company_intel_cache_ttl_and_poison() -> bool:
    """Post-audit: intel cache had NO TTL (one outage-day fetch poisoned intel
    forever) and cached even unreachable-domain results."""
    from career_copilot import profile_optimizer as profopt
    from career_copilot import tools
    database.init_db()
    suffix = os.urandom(4).hex()
    fresh_co, stale_co, dead_co = (f"FreshCo-{suffix}", f"StaleCo-{suffix}", f"DeadCacheCo-{suffix}")

    calls: list[str] = []
    original = profopt.analyze_company

    def _fake_analyze(company, job_url, description):
        calls.append(company)
        return profopt.CompanyIntel(name=company, domain=f"{company.lower()}.com",
                                    mission="m", raw_homepage_text="fetched ok")

    # 1) fresh cache -> served from cache, no re-analysis
    database.save_company_intel(fresh_co, "fresh.example", json.dumps({"name": fresh_co, "mission": "cached mission"}))
    profopt.analyze_company = _fake_analyze
    try:
        out = tools.analyze_target_company(fresh_co, "https://jobs.example/1", "desc")
    finally:
        profopt.analyze_company = original
    assert out.startswith("[Cached]") and calls == [], \
        f"fresh intel must come from cache, got analyze calls {calls}"

    # 2) stale cache (30 days) -> re-analyzed and refreshed
    database.save_company_intel(stale_co, "stale.example", json.dumps({"name": stale_co}))
    with database.get_connection() as conn:
        conn.cursor().execute(
            "UPDATE company_intel SET created_at='2000-01-01 00:00:00' WHERE company=?",
            (stale_co,),
        )
        conn.commit()
    profopt.analyze_company = _fake_analyze
    try:
        out = tools.analyze_target_company(stale_co, "https://jobs.example/2", "desc")
    finally:
        profopt.analyze_company = original
    assert not out.startswith("[Cached]") and calls == [stale_co], \
        f"stale intel (>{tools.INTEL_CACHE_TTL_DAYS}d) must re-analyze, got {out[:30]!r} calls={calls}"

    # 3) unreachable-domain result must NOT be cached (no poison)
    def _dead_analyze(company, job_url, description):
        calls.append(company)
        return profopt.CompanyIntel(name=company, raw_homepage_text="")

    profopt.analyze_company = _dead_analyze
    try:
        tools.analyze_target_company(dead_co, "https://jobs.example/3", "desc")
    finally:
        profopt.analyze_company = original
    assert database.get_company_intel(dead_co) is None, \
        "unreachable-domain intel must not be written to cache"
    print("  [PASS] intel cache: TTL-bounded, stale refresh, no unreachable-domain poisoning")
    return True


def test_legacy_db_migration() -> bool:
    """Pass 3: the resume_text ALTER must upgrade a legacy (pre-fix) applications
    table, preserve existing rows, and init_db must be idempotent."""
    import sqlite3
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    original_path = database.DB_PATH
    try:
        # Build a legacy schema WITHOUT resume_text (as the pre-fix init_db made),
        # including a legacy row with the resume stuffed into notes (bug #14 era).
        conn = sqlite3.connect(tmp.name)
        conn.executescript("""
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, company TEXT,
                location TEXT, url TEXT UNIQUE, description TEXT,
                status TEXT DEFAULT 'found',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER UNIQUE,
                apply_url TEXT, status TEXT, notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT, report_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE company_intel (
                id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT UNIQUE,
                domain TEXT, intel_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute(
            "INSERT INTO applications (job_id, apply_url, status, notes) VALUES (1,'https://a.example','drafted','OLD-RESUME-AS-NOTES')"
        )
        conn.commit()
        conn.close()

        database.DB_PATH = tmp.name
        database.init_db()  # must ALTER TABLE — must not crash on legacy schema
        database.init_db()  # idempotent second run

        with database.get_connection() as c:
            cols = {r[1] for r in c.cursor().execute("PRAGMA table_info(applications)").fetchall()}
        assert "resume_text" in cols and "notes" in cols, \
            f"migration must add resume_text while preserving notes, cols={cols}"

        # Legacy row preserved + writable through the new API
        database.save_application(1, "https://a.example", "submitted", "new note", resume_text="NEW-BODY")
        with database.get_connection() as c:
            row = c.cursor().execute(
                "SELECT notes, resume_text FROM applications WHERE job_id=1"
            ).fetchone()
        assert tuple(row) == ("new note", "NEW-BODY"), f"legacy row must upsert cleanly, got {row}"
    finally:
        database.DB_PATH = original_path
        os.unlink(tmp.name)
    print("  [PASS] legacy DB migrates cleanly (resume_text added, idempotent, rows preserved)")
    return True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

REGRESSION_TESTS = [
    test_cleanup_date_format,
    test_invalid_status_rejected,
    test_application_resume_column,
    test_candidate_profile_placeholders,
    test_prep_plan_seven_days,
    test_coarse_pass_never_calls_llm,
    test_email_url_escaping,
    test_matches_keys_semantics,
    test_ddg_parser_attribute_order_tolerant,
    test_jobicy_full_query_first,
    test_filter_api_is_digest_gate,
    test_scheduler_once_mode,
    test_application_status_machine,
    test_smtp_connection_timeout,
    test_resume_filename_collision_proof,
    test_company_analyzer_dead_domain_shortcircuit,
    test_company_intel_cache_ttl_and_poison,
    test_legacy_db_migration,
]

OFFLINE_UNIT_TESTS = [
    "test_autofill_mapping_detection",
    "test_site_specific_packet_enrichment",
    "test_browser_runner_import",
    "test_relevance_scoring",
    "test_experience_level_filter",
    "test_minimum_threshold",
    "test_negative_keywords",
    "test_fresher_experience_level",
    "test_config_module",
    "test_database_cleanup",
    "test_resume_caching",
]


def main() -> int:
    print("=" * 60)
    print("CAREER COPILOT — REGRESSION SUITE (hermetic)")
    print("=" * 60)

    results: dict[str, bool] = {}

    print("\n--- Reliability regression tests ---")
    for test in REGRESSION_TESTS:
        try:
            results[test.__name__] = bool(test())
        except Exception as exc:
            results[test.__name__] = False
            print(f"  [FAIL] {test.__name__}: {type(exc).__name__}: {exc}")

    print("\n--- Offline unit tests (from test_career_copilot) ---")
    try:
        import career_copilot.test_career_copilot as tc
        for name in OFFLINE_UNIT_TESTS:
            try:
                results[name] = bool(getattr(tc, name)())
            except Exception as exc:
                results[name] = False
                print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")
    except Exception as exc:
        print(f"  [FAIL] could not import unit tests: {exc}")

    print("\n" + "=" * 60)
    failed = [k for k, v in results.items() if not v]
    print(f"Total: {len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", ", ".join(failed))
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
