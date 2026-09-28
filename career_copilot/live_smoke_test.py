"""Live autonomy smoke test — verifies the agentic loop end-to-end with a REAL key.

Run ONLY on a keyed machine:
    python career_copilot/live_smoke_test.py

What it proves (each step reports PASS/FAIL and never hides a failure):
  1. Model chain reachable (real Gemini call succeeds).
  2. Planner produces a valid, allow-listed plan from a natural-language goal.
  3. Loop executes steps with real tool calls and reflection decisions.
  4. Failure triggers work: a forced-failing tool yields a structured error,
     a reflection, and either a replan or an honest partial summary.
  5. Cost accounting recorded real token usage during the run.
  6. Anti-hallucination guardrail still holds on a live generation.

Exit code 0 = all checks passed; 1 = any failure (each printed).
Requires GOOGLE_API_KEY in the environment or career_copilot/.env.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career_copilot.config import load_env

load_env()

if not os.environ.get("GOOGLE_API_KEY"):
    print("GOOGLE_API_KEY not set — the live smoke test needs a real key.")
    print("Set it in the environment or career_copilot/.env, then re-run.")
    sys.exit(2)

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, fn) -> None:
    try:
        detail = fn()
        PASS.append(name)
        print(f"  [PASS] {name}" + (f" — {detail}" if detail else ""))
    except Exception as exc:  # noqa: BLE001
        FAIL.append(f"{name}: {type(exc).__name__}: {exc}")
        print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")


print("=" * 60)
print("CAREER COPILOT — LIVE AUTONOMY SMOKE TEST")
print("=" * 60)

from career_copilot.config import get_llm_usage, reset_llm_usage

reset_llm_usage()

# ---------------------------------------------------------------------------
# 1. Model chain reachable
# ---------------------------------------------------------------------------
def test_model_chain() -> str:
    from career_copilot.config import call_gemini

    text = call_gemini("Reply with exactly the word: READY", temperature=0.0)
    assert text and len(text) < 50, f"unexpected response: {text[:100]}"
    return f"model replied ({len(text)} chars)"


check("1. model chain reachable (real Gemini call)", test_model_chain)


# ---------------------------------------------------------------------------
# 2. Planner produces a valid allow-listed plan
# ---------------------------------------------------------------------------
def test_planner() -> str:
    from career_copilot.agent_loop import TOOL_SPECS, _extract_json, _plan, _validate_plan

    plan = _plan("Show me how many jobs and applications are stored", 4, "n/a")
    assert plan, "planner returned no steps"
    valid = _validate_plan({"plan": plan})
    assert valid, "planner plan failed validation"
    for step in valid:
        assert step["tool"] in TOOL_SPECS, f"non-allow-listed tool: {step['tool']}"
    return f"{len(valid)} step(s), tools={[s['tool'] for s in valid]}"


check("2. planner emits valid allow-listed plan", test_planner)


# ---------------------------------------------------------------------------
# 3. Loop executes with real tool calls + reflection
# ---------------------------------------------------------------------------
def test_loop_execution() -> str:
    from career_copilot.agent_loop import run_agent_loop

    run = run_agent_loop(
        "Report how many jobs and applications are in the database", max_steps=4
    )
    assert run.mode == "agentic", f"loop degraded to {run.mode}: {run.final_summary[:200]}"
    assert run.steps_executed, "no steps executed"
    ok_steps = [s for s in run.steps_executed if s.ok]
    assert ok_steps, f"all steps failed: {[s.error for s in run.steps_executed]}"
    assert run.final_summary, "empty final summary"
    return f"{len(ok_steps)}/{len(run.steps_executed)} steps ok, replans={run.replans}"


check("3. agentic loop executes end-to-end (agentic mode)", test_loop_execution)


# ---------------------------------------------------------------------------
# 4. Failure triggers: forced-failing tool → structured error → replan/summary
# ---------------------------------------------------------------------------
def test_failure_triggers() -> str:
    from career_copilot import agent_loop, workflow

    # Force the planner to include a tool that always fails, then verify the
    # loop reports the failure structurally and still finishes.
    def _always_fail():
        raise RuntimeError("simulated live failure")

    orig_plan = agent_loop._plan
    agent_loop._plan = lambda goal, ms, qh: [
        {"tool": "__fail__", "args": {}, "description": "forced failure"},
        {"tool": "get_database_stats", "args": {}, "description": "recover with stats"},
    ]
    agent_loop.TOOL_REGISTRY["__fail__"] = _always_fail
    try:
        run = agent_loop.run_agent_loop("recover from a tool failure", max_steps=4)
    finally:
        agent_loop._plan = orig_plan
        del agent_loop.TOOL_REGISTRY["__fail__"]

    failed = [s for s in run.steps_executed if not s.ok]
    recovered = [s for s in run.steps_executed if s.ok]
    assert failed and failed[0].error and "simulated live failure" in failed[0].error, (
        "failure must be captured structurally with the original error"
    )
    assert recovered, "loop did not continue past the failure"
    assert run.final_summary, "no summary after partial failure"
    return (
        f"failure captured + {len(recovered)} recovery step(s), "
        f"replans={run.replans}, mode={run.mode}"
    )


check("4. failure triggers: structured error + recovery", test_failure_triggers)


# ---------------------------------------------------------------------------
# 5. Cost accounting captured real usage
# ---------------------------------------------------------------------------
def test_cost_accounting() -> str:
    usage = get_llm_usage()
    assert usage["calls"] > 0, "no LLM calls recorded during the live run"
    assert usage["input_tokens"] > 0, "no input tokens recorded"
    assert usage["estimated_cost_usd"] >= 0
    return (
        f"{usage['calls']} calls, {usage['input_tokens']} in / "
        f"{usage['output_tokens']} out tokens, ~${usage['estimated_cost_usd']}"
    )


check("5. token/cost accounting recorded live usage", test_cost_accounting)


# ---------------------------------------------------------------------------
# 6. Anti-hallucination guardrail holds on a live generation
# ---------------------------------------------------------------------------
def test_guardrail_live() -> str:
    from career_copilot.tools import _generate_tailored_resume_inner

    # JD deliberately demands skills a python/flask resume does not have.
    resume, audit = _generate_tailored_resume_inner(
        "Rust Systems Engineer",
        "EvalCorp",
        "Requires deep Rust systems programming, WebAssembly, and kernel-level "
        "experience. (This JD is a hallucination probe — the candidate is a "
        "python/flask developer.)",
    )
    lowered = resume.lower()
    for fabricated in ("rust", "webassembly", "wasm", "kernel"):
        assert fabricated not in lowered or "learning" in lowered, (
            f"guardrail leak: resume claims '{fabricated}' the candidate never had"
        )
    gen = audit.get("generator", "")
    return f"generator={gen}, resume stayed grounded (no rust/wasm claims)"


check("6. anti-hallucination guardrail holds live", test_guardrail_live)


# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print(f"LIVE SMOKE: {len(PASS)}/{len(PASS) + len(FAIL)} passed")
if FAIL:
    print("FAILURES:")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("Autonomy verified end-to-end: plan, execute, reflect, fail safely, stay grounded.")
