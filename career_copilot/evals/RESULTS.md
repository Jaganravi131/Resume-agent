# Career Copilot — Evals Results

> Generated 2026-09-25 15:21 UTC · offline-first suite

| Check | Result | Score | Details |
|---|---|---|---|
| `scorer_bounds` | PASS | 1.00 | all scores/categories within 0-100 (incl. duplicate-heavy JD) |
| `discrimination` | PASS | 0.88 | good>bad win rate 3/3 families; Spearman(label, score) = 0.750; scores={'backend': {'good': 84, 'mediocre': 37, 'bad': 31}, 'data': {'good': 76, 'mediocre': 78, 'bad': 19}, 'platform': {'good': 64, 'mediocre': 37, 'bad': 22}} |
| `guardrail_recall` | PASS | 1.00 | sample-level catch 3/3 (100%); skill-level recall 6/6 (100%) |
| `guardrail_false_positives` | PASS | 1.00 | clean 3/3 truthful samples (0 false alarms) |
| `sanitizer_invariants` | PASS | 1.00 | paths/fences/debug/metadata all stripped |
| `quality_gate_separation` | PASS | 1.00 | well-formed=95/100 passed=True; garbage=0/100 passed=False |
| `fallback_grounding` | PASS | 1.00 | fallback never claims unowned skills (incl. adversarial JD) |
| `threshold_safety` | PASS | 1.00 | MIN_MATCH_PERCENTAGE='40%' -> get_min_match()=40 (no crash) |
| `model_failover` | PASS | 1.00 | call order=['primary-x', 'primary-x', 'standby-y'] (expect primary retry then standby); output='standby-ok' |
| `revise_loop_no_progress` | PASS | — | reviser calls=1, attempts=1 (must stay <= 1 with a no-op reviser) |
| `intel_cache_anti_poison` | PASS | — | analyze calls=1, cache row written for unreachable domain: False (must be False); TTL=7d |
| `resume_filename_safety` | PASS | — | well_formed=True, all_unique=True, lengths=[100, 23, 23, 41] |

**Overall: 12/12 checks passed.**

### Metric definitions
- `scorer_bounds` — every score/category stays within 0-100 (regression for the >100% category bug)
- `discrimination` — good-fit jobs outrank bad-fit jobs (win rate + Spearman vs human labels)
- `guardrail_recall` — planted hallucinated skills (kubernetes/rust/terraform/golang) are caught
- `guardrail_false_positives` — truthful resumes (incl. role references & soft-skill prose) raise no alarms
- `sanitizer_invariants` — no paths/fences/debug/metadata survive sanitization
- `quality_gate_separation` — well-formed resume passes, garbage fails
- `fallback_grounding` — the no-LLM fallback generator never claims unowned skills (adversarial JD)
- `threshold_safety` — malformed `MIN_MATCH_PERCENTAGE` never crashes the pipeline
- `model_failover` — primary model retried once, then automatic standby failover
