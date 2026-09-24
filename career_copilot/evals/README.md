# Career Copilot — Evals

Offline-first evaluation suite for the scoring engine, anti-hallucination
guardrail, sanitizer, quality gate, grounded fallback generator, and model
failover. Designed to run in CI with **no network and no API key**.

## Run

```bash
# offline suite (9 checks) — CI-safe
python -m career_copilot.evals.run_evals

# include the live-LLM tailoring eval (needs GOOGLE_API_KEY + network)
python -m career_copilot.evals.run_evals --llm

# raw JSON report
python -m career_copilot.evals.run_evals --json
```

Exit code is `0` only when every check passes (CI-gateable).

## Checks

| Check | What it protects against |
|---|---|
| `scorer_bounds` | Category/score values escaping 0-100 (duplicate-token double-count regression) |
| `discrimination` | Scorer losing the ability to rank good fits above bad fits (win rate + Spearman) |
| `guardrail_recall` | Invented skills (kubernetes/rust/terraform/golang) slipping into tailored resumes |
| `guardrail_false_positives` | Guardrail crying wolf on truthful prose, soft skills, and role references |
| `sanitizer_invariants` | Paths / code fences / `[Tool]` debug / JSON metadata leaking into PDFs |
| `quality_gate_separation` | Garbage input passing the 70/100 ATS gate (or good input failing it) |
| `fallback_grounding` | The no-LLM fallback fabricating JD skills (its historical bug) |
| `threshold_safety` | Malformed `MIN_MATCH_PERCENTAGE` crashing the daily cycle |
| `model_failover` | Primary model outages: retry once → automatic standby model |

## Files

- `fixtures.py` — synthetic base resume, 9 labeled golden JD pairs, seeded hallucination/truthful/dirty samples
- `harness.py` — metric implementations (`run_all`, `to_markdown`)
- `run_evals.py` — CLI, writes `RESULTS.md` + `results.json`
- `RESULTS.md` — latest baseline results (regenerated on every run)

## Notes

- The base resume is **synthetic** (no real PII). Planted skills are chosen from
  `relevance.verified_skill_universe()` but deliberately absent from the base.
- Golden labels (`good`/`mediocre`/`bad`) are hand-labeled; treat `discrimination`'s
  Spearman as a coarse calibration signal (n=9), not a statistical claim.
- With `--llm`, `llm_tailoring` measures real-generation hallucination rate and
  avg ATS score over 3 pairs (cost-capped).
