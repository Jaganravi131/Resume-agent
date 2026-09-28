"""Eval: interview grader robustness against fabricated/adversarial answers.

Run from the repo root:
    python -m career_copilot.evals.run_grader_evals

Measures behavioral contracts of the mock-interview grader (heuristic mode —
no API key needed; the same corpus shape is reusable for LLM grading later):

1. ``fabrication_penalty`` — an answer name-dropping impressive but OFF-TOPIC
   tech ("quantum blockchain in Rust") must score LOWER than an honest,
   on-topic answer of similar length. The grader must not reward buzzword soup.
2. ``grounding_preference`` — on-topic, quantified, STAR answers must
   consistently outscore vague on-topic answers (score separation >= 2.0).
3. ``thin_answer_floor`` — "I don't know"-style answers must land in the weak
   band (< 4.0) regardless of any buzzwords they contain.

Writes results to career_copilot/evals/GRADER_RESULTS.md and prints a table.
Exit code 0 only when all contracts hold.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Force heuristic grading (offline, deterministic).
os.environ.pop("GOOGLE_API_KEY", None)

from career_copilot.interview_agent import _heuristic_grade  # noqa: E402

ROLE = "Backend Engineer"
TOPICS = ["python", "fastapi", "postgresql", "docker", "redis", "rest"]
QUESTION = (
    "Walk me through a production system you built with python and fastapi. "
    "What trade-offs did you weigh and what was the measurable outcome?"
)

HONEST_STRONG = (
    "Situation: our checkout API was failing at 300 requests per second. "
    "I led the redesign of the fastapi service: moved session state from "
    "postgres to redis, added connection pooling, and wrote load tests. "
    "My role was technical lead for two engineers. As a result, p95 latency "
    "dropped 65% and error rate went from 4% to 0.2% over three weeks."
)

HONEST_VAGUE = (
    "I worked on a fastapi service with python and postgres. It was a good "
    "project and I learned a lot about rest apis and databases in general."
)

FABRICATED_BUZZWORD = (
    "I built a quantum blockchain in rust with zero-knowledge proof consensus, "
    "deployed on kubernetes across multi-cloud webassembly edge clusters. It "
    "revolutionized everything and had unprecedented scale beyond comparison."
)

THIN_ANSWER = "I don't really remember the details, but it was some kind of api thing I guess."

CORPUS = [
    ("honest_strong", HONEST_STRONG, 8.0),   # floor: must score >= this
    ("honest_vague", HONEST_VAGUE, None),
    ("fabricated_buzzword", FABRICATED_BUZZWORD, None),
    ("thin_answer", THIN_ANSWER, None),
]


def main() -> int:
    results = {name: _heuristic_grade(QUESTION, ans, TOPICS) for name, ans, _ in CORPUS}
    checks: list[tuple[str, bool, str]] = []

    # 1. fabrication_penalty: buzzword soup < honest vague < honest strong
    s_strong = results["honest_strong"]["score"]
    s_vague = results["honest_vague"]["score"]
    s_fab = results["fabricated_buzzword"]["score"]
    checks.append((
        "fabrication_penalty",
        s_fab < s_vague < s_strong,
        f"buzzword={s_fab} < vague={s_vague} < strong={s_strong}",
    ))

    # 2. grounding_preference: strong - vague separation >= 2.0
    checks.append((
        "grounding_preference",
        (s_strong - s_vague) >= 2.0,
        f"separation={round(s_strong - s_vague, 1)} (need >= 2.0)",
    ))

    # 3. thin_answer_floor: thin answer lands weak (< 4.0)
    s_thin = results["thin_answer"]["score"]
    checks.append((
        "thin_answer_floor",
        s_thin < 4.0,
        f"thin={s_thin} (need < 4.0)",
    ))

    # 4. strong floor: the exemplar honest answer must be strong band
    checks.append((
        "strong_answer_band",
        s_strong >= 8.0 and results["honest_strong"]["verdict"] == "strong",
        f"strong={s_strong}, verdict={results['honest_strong']['verdict']}",
    ))

    # 5. verdict consistency
    ok_verdicts = all(
        results[name]["verdict"] in ("weak", "ok", "strong") for name, _, _ in CORPUS
    )
    checks.append(("verdict_vocabulary", ok_verdicts, "all verdicts in allowed set"))

    # --- report ------------------------------------------------------------
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Interview Grader Robustness — Adversarial Eval",
        "",
        f"Generated: {now} · grader: heuristic (offline) · corpus: {len(CORPUS)} answers",
        "",
        "| Sample | Score | Verdict | Topic |",
        "|---|---|---|---|",
    ]
    for name, _, _ in CORPUS:
        r = results[name]
        lines.append(f"| {name} | {r['score']} | {r['verdict']} | {r['topic']} |")
    lines += ["", "| Check | Result | Details |", "|---|---|---|"]
    for name, ok, detail in checks:
        lines.append(f"| `{name}` | {'PASS' if ok else 'FAIL'} | {detail} |")

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    lines += ["", f"**Overall: {passed}/{total} checks passed.**", ""]

    out_dir = Path(__file__).resolve().parent
    (out_dir / "GRADER_RESULTS.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
