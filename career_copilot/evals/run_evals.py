"""CLI entry point for the Career Copilot eval suite.

Usage:
    python -m career_copilot.evals.run_evals            # offline evals
    python -m career_copilot.evals.run_evals --llm      # + live tailoring eval (needs GOOGLE_API_KEY)

Writes a JSON report and regenerates RESULTS.md next to this module.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from career_copilot.evals.harness import run_all, to_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Career Copilot evaluation suite")
    parser.add_argument("--llm", action="store_true", help="Include the live-LLM tailoring eval (needs GOOGLE_API_KEY + network)")
    parser.add_argument("--json", action="store_true", help="Print the raw JSON report")
    args = parser.parse_args(argv)

    report = run_all(include_llm=args.llm)

    out_dir = Path(__file__).resolve().parent
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    md = (
        "# Career Copilot — Evals Results\n\n"
        f"> Generated {stamp} · offline-first suite\n\n"
        + to_markdown(report)
        + "\n\n### Metric definitions\n"
        "- `scorer_bounds` — every score/category stays within 0-100 (regression for the >100% category bug)\n"
        "- `discrimination` — good-fit jobs outrank bad-fit jobs (win rate + Spearman vs human labels)\n"
        "- `guardrail_recall` — planted hallucinated skills (kubernetes/rust/terraform/golang) are caught\n"
        "- `guardrail_false_positives` — truthful resumes (incl. role references & soft-skill prose) raise no alarms\n"
        "- `sanitizer_invariants` — no paths/fences/debug/metadata survive sanitization\n"
        "- `quality_gate_separation` — well-formed resume passes, garbage fails\n"
        "- `fallback_grounding` — the no-LLM fallback generator never claims unowned skills (adversarial JD)\n"
        "- `threshold_safety` — malformed `MIN_MATCH_PERCENTAGE` never crashes the pipeline\n"
        "- `model_failover` — primary model retried once, then automatic standby failover\n"
    )

    (out_dir / "RESULTS.md").write_text(md, encoding="utf-8")
    (out_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(to_markdown(report))
    print(f"\nWrote {out_dir / 'RESULTS.md'} and {out_dir / 'results.json'}")

    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
