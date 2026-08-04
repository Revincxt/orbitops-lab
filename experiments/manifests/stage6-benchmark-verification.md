# Stage 6 benchmark-harness verification

## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: run / validate
- Origin Date: 2026-08-04
- Verification Status: VERIFIED
- Version Label: stage6-benchmark-v1

## Experiment Result

- Experiment ID: `stage6-benchmark-smoke-20260804`
- Type: deterministic multi-scenario code benchmark smoke test
- Status: completed
- Command: `.venv/bin/orbitops benchmark configs/benchmark-smoke.toml --output runs/stage6-smoke`
- Independent rerun output: `runs/stage6-smoke-rerun`
- Scenarios: 4 (`tiny` and `medium`; `easy` and `hard`)
- Solvers: `random-feasible`, `greedy-insertion`, `local-search`, `genetic`
- Algorithm seeds: `0`, `1`
- Evaluation budget: 60 unique decoded genomes
- Total solver runs: 32
- Feasible runs: 32
- Failed runs: 0
- Reproducibility fingerprint, both runs:
  `024a34b965ade59c311d398c0f707fc0787ede84894eeb8af34d4c181a9ab6af`

## Descriptive smoke ranking

| Rank | Solver | Feasible rate | Mean value ratio | Best-observed rate |
|---:|---|---:|---:|---:|
| 1 | `genetic` | 1.0 | 0.9996779727452458 | 0.75 |
| 2 | `local-search` | 1.0 | 0.977716648599656 | 0.50 |
| 3 | `greedy-insertion` | 1.0 | 0.9445662450765397 | 0.00 |
| 4 | `random-feasible` | 1.0 | 0.872579127926503 | 0.00 |

The rerun reproduced all scenario hashes, objectives, evaluation counts,
convergence traces, ranking values, and the campaign fingerprint. Wall-clock
means differed slightly as expected and are excluded from the fingerprint.

The full quality suite passed 88 tests with 91.22% branch-aware coverage. This
record verifies pipeline execution and deterministic result reproduction. Four
synthetic scenarios are too few for statistical superiority, real-mission
generalization, or runtime-scaling claims; the table is descriptive only.
