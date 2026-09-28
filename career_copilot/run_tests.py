"""Offline-first test entry point.

Default run (``python career_copilot/run_tests.py``) executes ONLY hermetic
suites — no live job APIs, no Gemini calls, no notifications — and finishes
in seconds. This replaced the old behavior of unconditionally running the
legacy ``test_career_copilot.test_workflow`` integration phase, which hit
live DuckDuckGo/Gemini endpoints and took minutes (or hung on flaky networks).

To run the LIVE integration suite (real network + API key required), opt in:

    CAREER_COPILOT_LIVE_TESTS=1 python career_copilot/run_tests.py

Exit code 0 = all executed suites passed; 1 = any failure; 2 = live suite
skipped for missing key (only when opted in).
"""

from __future__ import annotations

import os
import sys
import types

# --- google.adk stub (offline suites never need the real SDK) ---------------
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

# Offline by default: tests must never see an API key unless explicitly opted in.
if not os.environ.get("CAREER_COPILOT_LIVE_TESTS"):
    os.environ.pop("GOOGLE_API_KEY", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_offline() -> int:
    """Hermetic suites: regressions + offline units + portfolio upgrade tests."""
    failed = 0

    print("=" * 60)
    print("SUITE 1/3 — REGRESSIONS + OFFLINE UNITS (hermetic)")
    print("=" * 60)
    from career_copilot import test_regressions

    failed += test_regressions.main()

    print("\n" + "=" * 60)
    print("SUITE 2/3 — EVALUATOR SMOKE (hermetic)")
    print("=" * 60)
    # test_evaluator is a top-level script (asserts at module scope); run it in
    # a subprocess so a failure returns a code instead of aborting this runner.
    import subprocess

    proc = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(__file__), "test_evaluator.py")],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        capture_output=False,
    )
    if proc.returncode:
        failed += 1

    print("\n" + "=" * 60)
    print("SUITE 3/3 — PORTFOLIO UPGRADE (hermetic)")
    print("=" * 60)
    from career_copilot import test_portfolio_upgrade

    failed += test_portfolio_upgrade.main()

    return failed


def run_live() -> int:
    """Legacy integration suite: REAL job APIs + Gemini + full daily cycle."""
    if not os.environ.get("GOOGLE_API_KEY"):
        print("LIVE suite requested but GOOGLE_API_KEY is not set — aborting.")
        return 2
    print("=" * 60)
    print("LIVE INTEGRATION SUITE (real network — opt-in only)")
    print("=" * 60)
    from career_copilot.test_career_copilot import test_workflow

    test_workflow()
    return 0


if __name__ == "__main__":
    want_live = bool(os.environ.get("CAREER_COPILOT_LIVE_TESTS"))
    rc = run_offline()
    if want_live:
        rc = rc or run_live()
    else:
        print(
            "\n(offline mode: live API integration suite skipped — "
            "set CAREER_COPILOT_LIVE_TESTS=1 to include it)"
        )
    print("\nALL OFFLINE SUITES PASSED" if rc == 0 else f"\nFAILURES: {rc}")
    sys.exit(1 if rc else 0)
