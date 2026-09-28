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
