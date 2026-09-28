# Interview Grader Robustness — Adversarial Eval

Generated: 2026-09-28 19:03 UTC · grader: heuristic (offline) · corpus: 4 answers

| Sample | Score | Verdict | Topic |
|---|---|---|---|
| honest_strong | 9.0 | strong | python |
| honest_vague | 2.5 | weak | python |
| fabricated_buzzword | 0.0 | weak | python |
| thin_answer | 0.0 | weak | python |

| Check | Result | Details |
|---|---|---|
| `fabrication_penalty` | PASS | buzzword=0.0 < vague=2.5 < strong=9.0 |
| `grounding_preference` | PASS | separation=6.5 (need >= 2.0) |
| `thin_answer_floor` | PASS | thin=0.0 (need < 4.0) |
| `strong_answer_band` | PASS | strong=9.0, verdict=strong |
| `verdict_vocabulary` | PASS | all verdicts in allowed set |

**Overall: 5/5 checks passed.**
