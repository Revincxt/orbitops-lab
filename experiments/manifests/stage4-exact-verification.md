# Stage 4 exact-solver verification

## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: validate
- Origin Date: 2026-08-04
- Verification Status: VERIFIED
- Version Label: stage4-exact-v1

## Experiment Result

- Experiment ID: `stage4-exact-crosscheck-20260804`
- Type: deterministic golden-case cross-validation
- Status: completed
- Command: `.venv/bin/pytest -q tests/golden/test_exact_solvers.py`
- Solvers: `brute-force`, `branch-and-bound`
- Golden scenarios: `tiny-conflict`, `tiny-resource`
- Repeated runs: targeted suite and full coverage suite
- Anomalies: none detected

| Scenario | Hand-verified value | Completed tasks | Brute force | Branch and bound |
|---|---:|---:|---:|---:|
| `tiny-conflict` | 18.0 | 2 | 18.0 | 18.0 |
| `tiny-resource` | 14.0 | 2 | 14.0 | 14.0 |

Both solvers returned feasible schedules, identical lexicographic objective
values, and `optimality_proven: true`. The proof applies only to the v0.1 model
boundary documented in ADR-0002 and to searches completed without timeout.
