"""Export resume-tailoring training pairs (JSONL) from the local database.

Pairs are built from the immutable resume version history: every recorded
`resume_versions` row joins its job to produce one instruction-tuning example:
the base resume + job description as input, the stored tailored resume as target.

Usage:
    python training/export_training_data.py [--out training/data/tailoring_pairs.jsonl]

Notes / honest limitations:
- The base resume is the CURRENT file at career_copilot/resume/ (older base
  versions are not versioned), so pairs from history all share today's base.
- Only examples whose version text is non-empty are exported.
- This is a data-prep utility: no model weights are downloaded or trained here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

INSTRUCTION = (
    "You are a truthful ATS resume optimizer. Rewrite the candidate's base resume "
    "for the target job. Use ONLY skills and experience evidenced in the base resume. "
    "Format: candidate name on line 1, contact line, ALL-CAPS section headings "
    "(PROFESSIONAL SUMMARY, CORE SKILLS, EXPERIENCE, PROJECTS, EDUCATION), '- ' bullets."
)


def export_pairs(db_module) -> list[dict]:
    """Build training pairs from resume_versions joined with jobs. Injectable db for tests."""
    db_module.init_db()
    with db_module.get_connection() as conn:
        rows = conn.cursor().execute(
            """
            SELECT v.job_id, v.title, v.company, v.resume_text, j.description
            FROM resume_versions v
            LEFT JOIN jobs j ON j.id = v.job_id
            WHERE LENGTH(COALESCE(v.resume_text, '')) > 200
            ORDER BY v.job_id, v.version
            """
        ).fetchall()

    from career_copilot.tools import _extract_resume_text

    base_resume = _extract_resume_text()
    pairs: list[dict] = []
    for job_id, title, company, tailored_text, description in rows:
        pairs.append({
            "instruction": INSTRUCTION,
            "input": (
                f"TARGET ROLE: {title} at {company}\n\n"
                f"JOB DESCRIPTION:\n{description or ''}\n\n"
                f"BASE RESUME:\n{base_resume}"
            ),
            "output": tailored_text,
        })
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="training/data/tailoring_pairs.jsonl")
    args = parser.parse_args()

    from career_copilot import database

    pairs = export_pairs(database)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        for pair in pairs:
            fh.write(json.dumps(pair, ensure_ascii=False) + "\n")
    print(f"Wrote {len(pairs)} training pairs -> {args.out}")
    if not pairs:
        print("No resume versions recorded yet — generate tailored resumes first "
              "(their versions are stored automatically), then re-run this export.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
