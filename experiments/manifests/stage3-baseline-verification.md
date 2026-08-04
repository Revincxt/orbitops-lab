# Stage 3 baseline feasibility verification

## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: validate
- Origin Date: 2026-08-04
- Verification Status: VERIFIED
- Version Label: stage3-baseline-v1

## Experiment Result

- Experiment ID: `stage3-baseline-feasibility-20260804`
- Type: deterministic code smoke test
- Status: completed
- Command: `.venv/bin/pytest -q tests/integration/test_baseline_feasibility.py`
- Inputs: scenario seeds `0..99`, 8 tasks per scenario, solver seed `20260804`
- Solvers: `random-feasible`, `greedy-value`, `greedy-density`,
  `greedy-deadline`, `greedy-insertion`
- Total solver runs: 500
- Feasible schedules: 500
- Infeasible schedules: 0
- Feasibility rate: 100%
- Anomalies: none detected

The same gate passed in its targeted invocation and again as part of the full
coverage run. This verifies deterministic construction and validator acceptance;
it does not compare objective quality, scaling, or runtime performance.
