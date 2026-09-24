"""Evaluation harness — offline-first metrics for Career Copilot.

Each check returns a dict: {name, passed, score, details}. run_all() aggregates
them into a report consumed by run_evals (markdown + JSON output).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Allow running without google-adk (package __init__ already tolerates it)
_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from career_copilot.evals import fixtures as fx
from career_copilot.relevance import (
    compute_relevance_score,
    get_min_match,
    _score_categories,
    _tokenize,
)
from career_copilot.resume_evaluator import (
    evaluate_resume_quality,
    find_unverified_skills,
    sanitize_resume_text,
)
from career_copilot.tools import _generate_fallback_resume

_LABEL_ORDER = {"bad": 0, "mediocre": 1, "good": 2}


def _env_sandbox():
    """Save env and force deterministic offline scoring conditions."""
    saved = dict(os.environ)
    os.environ["EXPERIENCE_LEVEL"] = "mid"
    os.environ["MIN_MATCH_PERCENTAGE"] = "40"
    os.environ.pop("EXCLUDE_KEYWORDS", None)
    os.environ.pop("GOOGLE_API_KEY", None)  # offline baseline unless --llm adds it back
    return saved


def _env_restore(saved: dict) -> None:
    os.environ.clear()
    os.environ.update(saved)


# ---------------------------------------------------------------------------
# 1. Scorer bounds (regression for the >100% category-score bug)
# ---------------------------------------------------------------------------

def check_scorer_bounds() -> dict:
    violations = []
    for pair in fx.GOLDEN_PAIRS:
        r = compute_relevance_score(pair["title"], pair["description"], fx.BASE_RESUME)
        if not (0 <= r.score <= 100):
            violations.append(f"{pair['family']}/{pair['fit']}: score={r.score}")
        for cat, v in r.category_scores.items():
            if not (0 <= v <= 100):
                violations.append(f"{pair['family']}/{pair['fit']}: {cat}={v}")

    # Duplicate-heavy JD regression (previously produced 400%)
    dup_cats = _score_categories(_tokenize(fx.DUPLICATE_HEAVY_JD), _tokenize(fx.BASE_RESUME))
    for cat, v in dup_cats.items():
        if not (0 <= v <= 100):
            violations.append(f"duplicate-heavy: {cat}={v}")

    return {
        "name": "scorer_bounds",
        "passed": not violations,
        "score": 1.0 if not violations else 0.0,
        "details": "all scores/categories within 0-100 (incl. duplicate-heavy JD)"
        if not violations else f"violations: {violations}",
    }


# ---------------------------------------------------------------------------
# 2. Discrimination: good fits must outrank bad fits
# ---------------------------------------------------------------------------

def _spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        rank = [0.0] * len(vals)
        for pos, i in enumerate(order):
            rank[i] = pos
        return rank
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    if n < 2:
        return 0.0
    mean_x, mean_y = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mean_x) * (ry[i] - mean_y) for i in range(n))
    den_x = sum((v - mean_x) ** 2 for v in rx) ** 0.5
    den_y = sum((v - mean_y) ** 2 for v in ry) ** 0.5
    return num / (den_x * den_y) if den_x and den_y else 0.0


def check_discrimination() -> dict:
    scores = []
    labels = []
    by_family: dict[str, dict[str, int]] = {}
    for pair in fx.GOLDEN_PAIRS:
        r = compute_relevance_score(pair["title"], pair["description"], fx.BASE_RESUME)
        scores.append(r.score)
        labels.append(_LABEL_ORDER[pair["fit"]])
        by_family.setdefault(pair["family"], {})[pair["fit"]] = r.score

    wins = 0
    total = 0
    for family, fits in by_family.items():
        if "good" in fits and "bad" in fits:
            total += 1
            wins += 1 if fits["good"] > fits["bad"] else 0

    rho = _spearman([float(x) for x in labels], [float(s) for s in scores])
    win_rate = wins / total if total else 0.0
    passed = win_rate == 1.0 and rho >= 0.6
    return {
        "name": "discrimination",
        "passed": passed,
        "score": round((win_rate + max(rho, 0)) / 2, 3),
        "details": (
            f"good>bad win rate {wins}/{total} families; "
            f"Spearman(label, score) = {rho:.3f}; "
            f"scores={ {f: d for f, d in by_family.items()} }"
        ),
    }


# ---------------------------------------------------------------------------
# 3 & 4. Anti-hallucination guardrail: recall + false-positive rate
# ---------------------------------------------------------------------------

def check_guardrail_recall() -> dict:
    total_planted = 0
    caught_planted = 0
    sample_hits = 0
    misses = []
    for sample in fx.HALLUCINATED_SAMPLES:
        found = set(find_unverified_skills(sample["text"], fx.BASE_RESUME))
        planted = set(sample["planted_skills"])
        total_planted += len(planted)
        caught = planted & found
        caught_planted += len(caught)
        if found:
            sample_hits += 1
        for skill in planted - found:
            misses.append(f"{sample['id']}:{skill}")

    sample_rate = sample_hits / len(fx.HALLUCINATED_SAMPLES)
    skill_rate = caught_planted / total_planted if total_planted else 0.0
    passed = sample_rate >= 0.95 and skill_rate >= 0.90
    return {
        "name": "guardrail_recall",
        "passed": passed,
        "score": round(skill_rate, 3),
        "details": (
            f"sample-level catch {sample_hits}/{len(fx.HALLUCINATED_SAMPLES)} "
            f"({sample_rate:.0%}); skill-level recall {caught_planted}/{total_planted} "
            f"({skill_rate:.0%})"
            + (f"; misses={misses}" if misses else "")
        ),
    }


def check_guardrail_false_positives() -> dict:
    false_alarms = []
    for sample in fx.TRUTHFUL_SAMPLES:
        found = find_unverified_skills(sample["text"], fx.BASE_RESUME)
        if found:
            false_alarms.append(f"{sample['id']}:{found}")

    clean = len(fx.TRUTHFUL_SAMPLES) - len(false_alarms)
    fpr = len(false_alarms) / len(fx.TRUTHFUL_SAMPLES)
    return {
        "name": "guardrail_false_positives",
        "passed": fpr <= 0.05,
        "score": round(1.0 - fpr, 3),
        "details": f"clean {clean}/{len(fx.TRUTHFUL_SAMPLES)} truthful samples"
        + (f"; false alarms={false_alarms}" if false_alarms else " (0 false alarms)"),
    }


# ---------------------------------------------------------------------------
# 5. Sanitizer invariants
# ---------------------------------------------------------------------------

def check_sanitizer() -> dict:
    cleaned = sanitize_resume_text(fx.DIRTY_SAMPLE)
    leaks = [tok for tok in fx.SANITIZER_FORBIDDEN if tok in cleaned]
    return {
        "name": "sanitizer_invariants",
        "passed": not leaks,
        "score": 1.0 if not leaks else 0.0,
        "details": "paths/fences/debug/metadata all stripped" if not leaks else f"leaked tokens: {leaks}",
    }


# ---------------------------------------------------------------------------
# 6. Quality gate separation (good resume passes, garbage fails)
# ---------------------------------------------------------------------------

def check_quality_gate() -> dict:
    good = evaluate_resume_quality(fx.BASE_RESUME, "Test Candidate")
    bad = evaluate_resume_quality(fx.GARBAGE_SAMPLE, "Test Candidate")
    passed = good["passed"] is True and bad["passed"] is False
    return {
        "name": "quality_gate_separation",
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "details": f"well-formed={good['score']}/100 passed={good['passed']}; "
                   f"garbage={bad['score']}/100 passed={bad['passed']}",
    }


# ---------------------------------------------------------------------------
# 7. Grounded fallback generator (must pass the guardrail by construction)
# ---------------------------------------------------------------------------

def check_fallback_grounding() -> dict:
    leaks_all: list[str] = []
    for pair in fx.GOLDEN_PAIRS:
        text = _generate_fallback_resume(
            pair["title"], "TargetCo", pair["description"], fx.BASE_RESUME
        )
        leaks_all += find_unverified_skills(text, fx.BASE_RESUME)

    adversarial = _generate_fallback_resume(
        "Platform Engineer", "CloudCo", fx.ADVERSARIAL_JD, fx.BASE_RESUME
    )
    adv_leaks = find_unverified_skills(adversarial, fx.BASE_RESUME)
    adv_word_leak = [
        w for w in ("kubernetes", "terraform", "golang", "rust", "kafka", "redis")
        if re.search(rf"\b{w}\b", adversarial.lower())
    ]
    passed = not leaks_all and not adv_leaks and not adv_word_leak
    return {
        "name": "fallback_grounding",
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "details": (
            "fallback never claims unowned skills (incl. adversarial JD)"
            if passed else f"leaks={leaks_all + adv_leaks + adv_word_leak}"
        ),
    }


# ---------------------------------------------------------------------------
# 8. Config/threshold safety (malformed env must not crash the pipeline)
# ---------------------------------------------------------------------------

def check_threshold_safety() -> dict:
    saved = os.environ.get("MIN_MATCH_PERCENTAGE")
    os.environ["MIN_MATCH_PERCENTAGE"] = "40%"
    value = get_min_match()
    if saved is None:
        os.environ.pop("MIN_MATCH_PERCENTAGE", None)
    else:
        os.environ["MIN_MATCH_PERCENTAGE"] = saved
    passed = value == 40
    return {
        "name": "threshold_safety",
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "details": f"MIN_MATCH_PERCENTAGE='40%' -> get_min_match()={value} (no crash)",
    }


# ---------------------------------------------------------------------------
# 9. Standby model failover (retry primary -> fail over to standby)
# ---------------------------------------------------------------------------

def check_model_failover() -> dict:
    import career_copilot.config as cfg

    calls: list[str] = []

    class _FakeModels:
        def generate_content(self, model=None, contents=None, config=None):
            calls.append(model)
            if model == "primary-x":
                raise RuntimeError("429 quota exceeded (simulated)")
            class _R:
                text = "standby-ok"
            return _R()

    class _FakeClient:
        models = _FakeModels()

    saved_env = {
        "GEMINI_MODEL": os.environ.get("GEMINI_MODEL"),
        "GEMINI_STANDBY_MODEL": os.environ.get("GEMINI_STANDBY_MODEL"),
    }
    saved_client = cfg._GENAI_CLIENT
    os.environ["GEMINI_MODEL"] = "primary-x"
    os.environ["GEMINI_STANDBY_MODEL"] = "standby-y"
    cfg._GENAI_CLIENT = _FakeClient()

    try:
        out = cfg.call_gemini("ping")
    finally:
        cfg._GENAI_CLIENT = saved_client
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    expected = ["primary-x", "primary-x", "standby-y"]
    passed = calls == expected and out == "standby-ok"
    return {
        "name": "model_failover",
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "details": f"call order={calls} (expect primary retry then standby); output={out!r}",
    }


# ---------------------------------------------------------------------------
# 10. Optional live-LLM tailoring eval (--llm)
# ---------------------------------------------------------------------------

def check_llm_tailoring() -> dict:
    """Requires GOOGLE_API_KEY + network. Measures hallucination rate of real tailoring."""
    if not os.environ.get("GOOGLE_API_KEY"):
        return {
            "name": "llm_tailoring",
            "passed": True,
            "score": None,
            "details": "SKIPPED (no GOOGLE_API_KEY)",
        }

    from career_copilot.tools import generate_tailored_resume_with_audit

    halluc_free = 0
    attempts = []
    scores = []
    results = []
    sample = fx.GOLDEN_PAIRS[:3]  # 3 pairs to cap cost
    for pair in sample:
        audited = generate_tailored_resume_with_audit(
            pair["title"], "TargetCo", pair["description"]
        )
        clean = not audited["hallucinated_skills"]
        halluc_free += 1 if clean else 0
        attempts.append(audited["optimization_attempts"])
        scores.append(audited["evaluation"].get("score", 0))
        results.append(f"{pair['family']}/{pair['fit']}: halluc={audited['hallucinated_skills']}")

    rate = halluc_free / len(sample)
    avg_ats = sum(scores) / len(scores) if scores else 0
    return {
        "name": "llm_tailoring",
        "passed": rate >= 0.95,
        "score": round(rate, 3),
        "details": (
            f"hallucination-free {halluc_free}/{len(sample)} ({rate:.0%}); "
            f"avg ATS score {avg_ats:.0f}/100; revise attempts={attempts}; {results}"
        ),
    }


def check_revise_loop_no_progress_break() -> dict:
    """When the reviser is a no-op (LLM down), the critique loop must stop after
    ONE attempt — re-evaluating an identical resume cannot make progress and
    burned duplicate LLM calls per tailored resume."""
    from career_copilot import resume_evaluator as re_

    calls = {"n": 0}

    def _noop_reviser(text, *args, **kwargs):
        calls["n"] += 1
        return text  # unchanged — simulates the unavailable-LLM fallback

    original = re_.optimize_resume_for_role
    re_.optimize_resume_for_role = _noop_reviser
    try:
        # A <50-char resume always fails the quality gate, so the loop MUST enter.
        _, final_eval = re_.evaluate_and_optimize(
            "Too short", "Backend Engineer", "Acme", "python django backend apis",
            base_resume_text="python django backend experience with apis and databases",
        )
    finally:
        re_.optimize_resume_for_role = original

    attempts = final_eval.get("optimization_attempts", -1)
    passed = 0 <= attempts <= 1 and calls["n"] <= 1
    return {
        "name": "revise_loop_no_progress",
        "passed": passed,
        "score": None,
        "details": f"reviser calls={calls['n']}, attempts={attempts} (must stay <= 1 with a no-op reviser)",
    }


def check_intel_cache_anti_poison() -> dict:
    """Unreachable-domain company intel must never be cached (anti-poison), and
    the cache write path must leave the database untouched in that case."""
    from career_copilot import database, profile_optimizer as profopt, tools

    database.init_db()
    company = f"EvalCacheCo-{os.urandom(4).hex()}"
    calls: list[str] = []
    original = profopt.analyze_company

    def _dead(c, job_url, description):
        calls.append(c)
        return profopt.CompanyIntel(name=c, raw_homepage_text="")  # site unreachable

    profopt.analyze_company = _dead
    try:
        tools.analyze_target_company(company, "https://jobs.example/eval", "desc")
        poisoned = database.get_company_intel(company) is not None
    finally:
        profopt.analyze_company = original

    passed = (not poisoned) and len(calls) == 1
    return {
        "name": "intel_cache_anti_poison",
        "passed": passed,
        "score": None,
        "details": (
            f"analyze calls={len(calls)}, cache row written for unreachable domain: {poisoned} "
            f"(must be False); TTL={tools.INTEL_CACHE_TTL_DAYS}d"
        ),
    }


def check_resume_filename_safety() -> dict:
    """External job titles flow into filenames: allowlist charset, length cap,
    and uniqueness for non-ASCII titles must all hold."""
    from career_copilot import tools

    names = [
        tools._build_resume_filename("a" * 300, "b" * 300),
        tools._build_resume_filename("データエンジニア", "株式会社"),
        tools._build_resume_filename("机器学习工程师", "某公司"),
        tools._build_resume_filename("Python Developer", "Acme"),
    ]
    well_formed = all(
        n.startswith("resume_") and n.endswith(".pdf") and "/" not in n and ".." not in n and len(n) <= 120
        for n in names
    )
    unique = len(set(names)) == len(names)
    passed = well_formed and unique
    return {
        "name": "resume_filename_safety",
        "passed": passed,
        "score": None,
        "details": f"well_formed={well_formed}, all_unique={unique}, lengths={[len(n) for n in names]}",
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

OFFLINE_CHECKS = [
    check_scorer_bounds,
    check_discrimination,
    check_guardrail_recall,
    check_guardrail_false_positives,
    check_sanitizer,
    check_quality_gate,
    check_fallback_grounding,
    check_threshold_safety,
    check_model_failover,
    check_revise_loop_no_progress_break,
    check_intel_cache_anti_poison,
    check_resume_filename_safety,
]


def run_all(include_llm: bool = False) -> dict:
    saved = _env_sandbox()
    try:
        checks = [fn() for fn in OFFLINE_CHECKS]
        if include_llm:
            os.environ.update({k: v for k, v in saved.items() if k == "GOOGLE_API_KEY"})
            checks.append(check_llm_tailoring())
    finally:
        _env_restore(saved)

    passed = sum(1 for c in checks if c["passed"])
    return {
        "checks": checks,
        "total": len(checks),
        "passed": passed,
        "all_passed": passed == len(checks),
    }


def to_markdown(report: dict) -> str:
    lines = [
        "| Check | Result | Score | Details |",
        "|---|---|---|---|",
    ]
    for c in report["checks"]:
        status = "PASS" if c["passed"] else "FAIL"
        score = "—" if c["score"] is None else f"{c['score']:.2f}"
        lines.append(f"| `{c['name']}` | {status} | {score} | {c['details']} |")
    lines.append("")
    lines.append(f"**Overall: {report['passed']}/{report['total']} checks passed.**")
    return "\n".join(lines)
