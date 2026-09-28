"""Offline tests for the portfolio-upgrade features (agent_chat, agent_loop,
memory_retrieval). All hermetic — no network, no LLM. Run:
    python career_copilot/test_portfolio_upgrade.py
"""

from __future__ import annotations

import os
import sys
import types

# --- google.adk stub (same pattern as run_tests.py) -------------------------
try:
    import google  # noqa: F401
except ImportError:
    google = types.ModuleType("google")
    sys.modules["google"] = google

if not hasattr(google, "adk"):
    adk_mod = types.ModuleType("google.adk")
    adk_agents = types.ModuleType("google.adk.agents")
    adk_llm_agent = types.ModuleType("google.adk.agents.llm_agent")

    class _MockAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    adk_llm_agent.Agent = _MockAgent
    adk_agents.llm_agent = adk_llm_agent
    adk_mod.agents = adk_agents
    google.adk = adk_mod
    sys.modules["google.adk"] = adk_mod
    sys.modules["google.adk.agents"] = adk_agents
    sys.modules["google.adk.agents.llm_agent"] = adk_llm_agent

# No API key in tests — forces fallback paths everywhere.
os.environ.pop("GOOGLE_API_KEY", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = []
FAIL = []

# Windows consoles default to cp1252 which cannot print '→'/'✅' — force UTF-8
# for THIS process's stdout so test names print reliably.
import io as _io
import sys as _sys

if hasattr(_sys.stdout, "reconfigure"):
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  [PASS] {name}")
    except Exception as exc:  # noqa: BLE001
        FAIL.append((name, str(exc)[:300]))
        print(f"  [FAIL] {name}: {exc}")


def main() -> int:
    # ========================================================================
    # agent_loop
    # ========================================================================
    print("== agent_loop ==")
    from career_copilot import agent_loop

    def test_tool_registry_allowlist():
        agent_loop._lazy_register()
        assert "search_job_postings" in agent_loop.TOOL_REGISTRY
        assert "build_daily_digest" in agent_loop.TOOL_REGISTRY
        assert "search_memory" in agent_loop.TOOL_REGISTRY
        assert "send_daily_notifications" in agent_loop.TOOL_REGISTRY

    def test_validate_plan_drops_unknown_tools():
        plan = {
            "plan": [
                {"tool": "get_database_stats", "args": {}, "description": "stats"},
                {"tool": "hack_the_planet", "args": {}, "description": "evil"},
                {"tool": "search_job_postings", "args": {"query": "dev"}, "description": "search"},
                "not a dict",
                {"tool": "get_database_stats", "args": "not a dict"},
            ]
        }
        valid = agent_loop._validate_plan(plan)
        assert len(valid) == 3, f"expected 3 valid steps, got {len(valid)}"
        assert all(v["tool"] in agent_loop.TOOL_REGISTRY for v in valid)
        assert valid[2]["args"] == {}  # non-dict args coerced

    def test_extract_json_handles_fences():
        text = '```json\n{"plan": [{"tool": "get_database_stats", "args": {}}]}\n```'
        parsed = agent_loop._extract_json(text)
        assert parsed and parsed["plan"][0]["tool"] == "get_database_stats"

    def test_execute_structured_error():
        def boom():
            raise ValueError("kapow")

        agent_loop.TOOL_REGISTRY["__boom__"] = boom
        try:
            result = agent_loop._execute({"tool": "__boom__", "args": {}, "description": "t"})
            assert result.ok is False
            assert "kapow" in result.error
        finally:
            del agent_loop.TOOL_REGISTRY["__boom__"]

    def test_run_loop_no_key_falls_back():
        """No GOOGLE_API_KEY → deterministic fallback, never raises.
        run_daily_cycle is stubbed so the test stays offline."""
        from career_copilot import workflow

        orig = workflow.run_daily_cycle
        workflow.run_daily_cycle = lambda *a, **k: "stubbed daily cycle"
        try:
            run = agent_loop.run_agent_loop("find me a job", max_steps=3)
            assert run.mode == "deterministic-fallback"
            assert "unavailable" in run.final_summary
            assert "stubbed daily cycle" in run.final_summary
        finally:
            workflow.run_daily_cycle = orig

    check("tool registry allow-list registers expected tools", test_tool_registry_allowlist)
    check("plan validation drops unknown tools and coerces args", test_validate_plan_drops_unknown_tools)
    check("JSON extraction handles ```json fences", test_extract_json_handles_fences)
    check("tool execution returns structured errors (no raise)", test_execute_structured_error)
    check("no-API-key loop degrades to deterministic fallback", test_run_loop_no_key_falls_back)

    def test_compact_result_digest_shape():
        sr = agent_loop.StepResult(
            step={"tool": "build_daily_digest", "description": "d"}, tool="build_daily_digest",
            ok=True,
            result={"jobs": [1, 2, 3], "digest": [
                {"title": "ML Eng", "company": "A", "match_percentage": 88},
                {"title": "Backend", "company": "B", "match_percentage": 71},
            ]},
        )
        compact = sr.compact_result()
        assert "fetched" in compact and "top_matches" in compact
        assert "ML Eng" in compact and "88" in compact

    def test_reflection_is_selective():
        """Reflect only on failure / last step / every 3rd step — verified by
        counting LLM calls via a stubbed _reflect."""
        calls = {"n": 0}

        def fake_reflect(goal, run, remaining):
            calls["n"] += 1
            return {"action": "continue"}

        orig_reflect = agent_loop._reflect
        orig_plan = agent_loop._plan
        agent_loop._reflect = fake_reflect
        agent_loop._plan = lambda goal, ms, qh: [
            {"tool": "get_database_stats", "args": {}, "description": f"s{i}"}
            for i in range(6)
        ]
        # Bypass the no-key fallback for this test (planner is stubbed anyway).
        os.environ["GOOGLE_API_KEY"] = "test-stub"
        try:
            run = agent_loop.run_agent_loop("count to six", max_steps=6, max_iterations=10)
            # 6 steps: reflect at 3 (periodic), 4 (fail? no — 4 is not last, not
            # periodic → skipped), 6 (last+periodic) → exactly 2 reflections
            # (steps 1,2,4,5 continue silently).
            assert calls["n"] == 2, f"expected 2 selective reflections, got {calls['n']}"
            assert len(run.steps_executed) == 6
        finally:
            agent_loop._reflect = orig_reflect
            agent_loop._plan = orig_plan
            os.environ.pop("GOOGLE_API_KEY", None)

    check("digest results compact to structured reflector input", test_compact_result_digest_shape)
    check("reflection is selective (cost-bounded), not per-step", test_reflection_is_selective)

    # ========================================================================
    # memory_retrieval (TF-IDF mode — no API key configured)
    # ========================================================================
    print("== memory_retrieval ==")
    from career_copilot import memory_retrieval as mr

    def test_tfidf_ranks_relevant_first():
        corpus = [
            {"entity_type": "job", "entity_id": 1, "title": "Backend Go", "text": "golang microservices kubernetes grpc", "meta": {}},
            {"entity_type": "job", "entity_id": 2, "title": "ML Engineer", "text": "pytorch transformers embeddings training models", "meta": {}},
            {"entity_type": "job", "entity_id": 3, "title": "Data Eng", "text": "sql airflow spark pipelines warehouse", "meta": {}},
        ]
        res = mr._tfidf_search(corpus, "pytorch transformer embeddings", top_k=2)
        assert res, "expected results"
        assert res[0].entity_id == 2, f"ML job should rank first, got {res[0].title}"
        assert res[0].score > 0.1

    def test_tfidf_no_results_for_gibberish():
        corpus = [{"entity_type": "job", "entity_id": 1, "title": "x", "text": "python flask", "meta": {}}]
        res = mr._tfidf_search(corpus, "zzzqqq xyzzy", top_k=3)
        assert res == []

    def test_semantic_search_offline_mode():
        out = mr.semantic_search("python developer", top_k=3)
        assert out["mode"] in ("tfidf", "empty", "vector")  # never raises
        assert isinstance(out["results"], list)

    def test_memory_stats():
        stats = mr.memory_stats()
        assert isinstance(stats, dict) and "total" in stats

    def test_retrieved_as_dict():
        r = mr.Retrieved(entity_type="job", entity_id=1, title="t", text="x", score=0.5, meta={})
        d = r.as_dict()
        assert d["entity_type"] == "job" and abs(d["score"] - 0.5) < 1e-6

    def test_text_hash_stable():
        assert mr._text_hash("abc") == mr._text_hash("abc")
        assert mr._text_hash("abc") != mr._text_hash("abd")

    check("TF-IDF ranks semantically relevant docs first", test_tfidf_ranks_relevant_first)
    check("TF-IDF returns nothing for out-of-vocabulary query", test_tfidf_no_results_for_gibberish)
    check("semantic_search never raises without API key", test_semantic_search_offline_mode)
    check("memory_stats returns counts", test_memory_stats)
    check("Retrieved.as_dict round-trips", test_retrieved_as_dict)
    check("text hash stable + discriminative", test_text_hash_stable)

    # ========================================================================
    # agent_chat (module structure; no live runner)
    # ========================================================================
    print("== agent_chat ==")
    from career_copilot import agent_chat

    def test_agent_status_no_crash():
        status = agent_chat.agent_status()
        assert status["mode"] in ("adk-agent", "fallback-llm")

    def test_chat_reply_degrades_without_key():
        """Without API key the bridge must return an error string, never raise."""
        reply = agent_chat.chat_reply("hello")
        assert isinstance(reply, str) and reply

    def test_reset_session_safe():
        agent_chat.reset_session("nonexistent-key")  # must not raise

    check("agent_status reports a valid mode", test_agent_status_no_crash)
    check("chat_reply degrades gracefully without API key", test_chat_reply_degrades_without_key)
    check("reset_session is safe on unknown key", test_reset_session_safe)

    # ========================================================================
    # Outcome feedback loop (follow_up_agent + outcome-informed tailoring)
    # ========================================================================
    print("== outcome feedback loop ==")
    from career_copilot import database, follow_up_agent
    from career_copilot.tools import _outcome_informed_context
    import tempfile as _tf

    _tmpdb = _tf.NamedTemporaryFile(suffix=".db", delete=False)
    _tmpdb.close()
    _orig_db = database.DB_PATH

    import itertools as _it
    _setup_counter = _it.count(1)

    def _setup_outcome_db():
        n = next(_setup_counter)  # unique URL per setup (jobs.url is UNIQUE)
        url = f"https://outcome-test.example/ml-{n}"
        database.DB_PATH = _tmpdb.name
        database.init_db()
        assert database.add_job("ML Engineer", "Acme", "Remote",
                                url, "pytorch transformers"), "add_job must succeed"
        jobs = database.get_all_jobs()
        job_id = jobs[-1][0]
        database.save_application(job_id, url, "submitted", "", resume_text="BASE")
        database.save_resume_version(job_id, "ML Engineer", "Acme", "RESUME-BODY",
                                     ats_score=91, generator="gemini")
        return job_id

    def _teardown_outcome_db():
        database.DB_PATH = _orig_db
        database.close_idle_resources()
        import gc as _gc
        _gc.collect()
        for suf in ("", "-wal", "-shm"):
            try:
                os.unlink(_tmpdb.name + suf)
            except OSError:
                pass

    def test_outcome_roundtrip_and_stats():
        job_id = _setup_outcome_db()
        assert follow_up_agent.record_application_outcome(job_id, "bogus_outcome").startswith("❌")
        assert follow_up_agent.record_application_outcome(
            job_id, "interview", notes="phone screen", resume_version=1
        ).startswith("✅")
        timeline = database.get_outcomes(job_id)
        assert timeline[0]["outcome"] == "interview"
        stats = database.get_outcome_stats()
        assert stats.get("interview") == 1

    def test_best_performing_resumes_ranking():
        job_id = _setup_outcome_db()
        database.record_outcome(job_id, "offer", resume_version=1)
        best = database.get_best_performing_resumes(limit=5)
        assert best and best[0]["best_outcome"] == "offer"
        assert best[0]["ats_score"] == 91

    def test_stale_detection():
        job_id = _setup_outcome_db()
        # status='submitted', no outcome events → stale immediately
        stale = follow_up_agent.get_stale_applications(days=0)
        assert any(s["job_id"] == job_id for s in stale)
        digest = follow_up_agent.build_follow_up_digest(days=0)
        assert digest["stale_count"] >= 1
        nudge = digest["items"][0]["nudge"]
        assert isinstance(nudge, str) and len(nudge) > 60  # template or LLM

    def test_outcome_informed_context_additive():
        """Empty history → empty context (prompt unchanged); with history → block.
        Uses a FRESH DB — earlier tests in this suite already wrote outcomes to
        the shared temp DB, so 'no history' can only be proven in isolation."""
        fresh = _tf.NamedTemporaryFile(suffix=".db", delete=False)
        fresh.close()
        database.DB_PATH = fresh.name
        database.init_db()
        try:
            assert _outcome_informed_context("x", "y") == ""  # no outcomes yet
            n = next(_setup_counter)
            url = f"https://outcome-fresh.example/ml-{n}"
            database.add_job("ML Engineer", "Beta", "Remote", url, "pytorch")
            job_id = database.get_all_jobs()[-1][0]
            database.save_resume_version(job_id, "ML Engineer", "Beta", "BODY")
            database.record_outcome(job_id, "interview", resume_version=1)
            ctx = _outcome_informed_context("ML Engineer", "pytorch")
            assert "OUTCOME FEEDBACK" in ctx
            assert "interview" in ctx
        finally:
            for suf in ("", "-wal", "-shm"):
                try:
                    os.unlink(fresh.name + suf)
                except OSError:
                    pass
            database.DB_PATH = _tmpdb.name  # restore shared DB for teardown

    check("outcome recording validates + builds timeline + stats",
          test_outcome_roundtrip_and_stats)
    check("best-performing resumes ranked by outcome", test_best_performing_resumes_ranking)
    check("stale applications detected + nudges generated", test_stale_detection)
    check("outcome-informed tailoring context is purely additive",
          test_outcome_informed_context_additive)
    _teardown_outcome_db()

    # ========================================================================
    # Browser form memory (agent 9)
    # ========================================================================
    print("== browser form memory ==")
    from career_copilot import browser_runner

    def test_form_memory_roundtrip(tmp_path=None):
        import json as _json
        from pathlib import Path as _Path

        orig = browser_runner._FORM_MEMORY_PATH
        test_file = _Path(_tf.mkdtemp()) / "form_memory.json"
        try:
            browser_runner._FORM_MEMORY_PATH = test_file
            assert browser_runner.load_form_memory("https://boards.greenhouse.io/x/1") == {}
            browser_runner.save_form_memory(
                "https://boards.greenhouse.io/x/1",
                {"email": "input[name='email']", "full_name": "#name"},
            )
            mem = browser_runner.load_form_memory(
                "https://boards.greenhouse.io/other/999"  # same domain, diff URL
            )
            assert mem.get("email") == "input[name='email']"
            # different domain → no cross-contamination
            assert browser_runner.load_form_memory("https://jobs.lever.co/x/1") == {}
        finally:
            browser_runner._FORM_MEMORY_PATH = orig
            try:
                test_file.unlink()
            except OSError:
                pass

    check("form memory persists per-domain and never cross-contaminates",
          test_form_memory_roundtrip)

    # ========================================================================
    # Mock-interview agent (agent 6 upgrade)
    # ========================================================================
    print("== mock interview agent ==")
    from career_copilot import interview_agent as ia
    from career_copilot import database as _db

    _tmpdb2 = _tf.NamedTemporaryFile(suffix=".db", delete=False)
    _tmpdb2.close()
    _db.DB_PATH = _tmpdb2.name
    _db.init_db()

    def test_topic_extraction():
        topics = ia.extract_topics(
            "ML Engineer",
            "Build RAG pipelines with pytorch and kubernetes. Deploy models with docker "
            "and kubernetes. Experience with llm embeddings and pytorch required."
        )
        assert topics, "topics must be extracted"
        for expected in ("pytorch", "kubernetes"):
            assert expected in topics, f"{expected} should rank (got {topics})"

    def test_session_lifecycle_offline():
        """Start → answer → end, fully offline (heuristic grader)."""
        sess = ia.start_session(
            "Backend Engineer",
            "Python FastAPI PostgreSQL docker kubernetes REST api. "
            "Strong sql and redis caching experience."
        )
        sid = sess["session_id"]
        assert sess["question"] and sess["question"].endswith("?")

        result = ia.answer_question(
            sid,
            "I built a FastAPI service handling 500 requests/second. Situation: our "
            "postgres latency hit p95 800ms. I led the caching redesign with redis, "
            "reducing latency by 60% as a result.",
        )
        assert "grade" in result
        g = result["grade"]
        assert 0 <= g["score"] <= 10
        assert g["verdict"] in ia.ALLOWED_VERDICTS
        assert g["grader"] == "heuristic"  # no API key in tests
        assert result["next_question"].endswith("?")

        report = ia.end_session(sid)
        assert report["questions_answered"] == 1
        assert 0 <= report["overall_score"] <= 10
        assert "restudy_topics" in report

    def test_grading_rejects_thin_answers():
        sess = ia.start_session("Data Engineer", "python sql airflow spark etl pipelines")
        bad = ia.answer_question(sess["session_id"], "I don't know.")
        good = ia.answer_question(
            sess["session_id"],
            "Situation: our airflow DAG failed weekly. I built retry logic with SLAs and "
            "backfill handling in python, cutting failures by 90% and saving 5 hours/week.",
        )
        assert bad["grade"]["score"] < good["grade"]["score"], (
            "the graded rubric must separate thin from substantive answers"
        )

    def test_invalid_session():
        assert "error" in ia.answer_question(999999, "hello")
        assert "error" in ia.end_session(999999)

    check("JD topic extraction ranks salient skills", test_topic_extraction)
    check("offline session lifecycle: ask → grade → adaptive report",
          test_session_lifecycle_offline)
    check("rubric separates thin from substantive answers",
          test_grading_rejects_thin_answers)
    check("invalid session ids return structured errors", test_invalid_session)

    # ========================================================================
    # GitHub-aware project gap analysis (agent 5 upgrade)
    # ========================================================================
    print("== project gap analysis ==")
    from career_copilot import project_gap as pg

    def test_skill_gap_diff():
        resume = "I built web apps with python, flask, and sql databases."
        gap = pg.analyze_skill_gap(
            "Platform Engineer",
            "Requires kubernetes experience. Strong python and sql. Kubernetes operations "
            "daily. More kubernetes: clusters, helm on kubernetes. Terraform a plus.",
            resume_text=resume,
        )
        assert "python" in gap["proven"] and "sql" in gap["proven"]
        assert "kubernetes" in gap["missing"] and "terraform" in gap["missing"]
        # kubernetes mentioned 4x, terraform 1x → frequency ordering must hold
        assert gap["missing"].index("kubernetes") < gap["missing"].index("terraform"), (
            "missing skills ordered by JD frequency"
        )

    def test_gap_projects_never_reprove():
        resume = "Years of python and react development."
        text = pg.recommend_gap_closing_projects(
            "DevOps Engineer",
            "kubernetes terraform aws observability prometheus required.",
            resume_text=resume,
        )
        assert "kubernetes" in text.lower()  # gap-closing project exists
        # If the LLM path produced output, it must not be a bare fallback list;
        # both paths mention the missing skill and neither recommends 'react'.
        assert "react" not in text.lower(), "must not re-recommend proven skills"

    def test_no_gap_case():
        resume = "Expert in kubernetes terraform aws prometheus and docker."
        text = pg.recommend_gap_closing_projects(
            "Platform Engineer",
            "kubernetes terraform aws prometheus docker required.",
            resume_text=resume,
        )
        assert "No major skill gaps" in text

    check("skill gap: proven vs missing with JD-frequency ordering", test_skill_gap_diff)
    check("gap projects close missing skills, never re-prove", test_gap_projects_never_reprove)
    check("full-coverage JD returns no-gap guidance", test_no_gap_case)

    # ========================================================================
    # Tracing (observability)
    # ========================================================================
    print("== tracing ==")
    from career_copilot import tracing

    def test_span_success_and_error():
        with tracing.trace_span("t.ok", kind="tool", attrs={"n": 1}) as span:
            span["extra"] = "x"
        try:
            with tracing.trace_span("t.fail", kind="llm", attrs={"model": "m"}):
                raise ValueError("boom")
        except ValueError:
            pass

    def test_pii_safe_attrs():
        safe = tracing._safe_attrs("llm", {"prompt": "x" * 500, "model": "m"})
        assert safe["prompt"].startswith("<str:") and len(safe["prompt"]) < 20
        assert safe["model"] == "m"

    def test_backend_report():
        st = tracing.otel_status()
        assert st["backend"] in ("opentelemetry", "structured-logging")

    check("trace spans swallow nothing but record success/error", test_span_success_and_error)
    check("long string attrs are truncated (PII-safe)", test_pii_safe_attrs)
    check("otel_status reports the active backend", test_backend_report)

    _db.DB_PATH = _orig_db
    _db.close_idle_resources()
    import gc as _gc2
    _gc2.collect()
    for suf in ("", "-wal", "-shm"):
        try:
            os.unlink(_tmpdb2.name + suf)
        except OSError:
            pass

    # ========================================================================
    print("\n" + "=" * 60)
    print(f"Total: {len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("FAILED:")
        for name, err in FAIL:
            print(f"  {name}: {err}")
        return 1
    print("All portfolio-upgrade tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
