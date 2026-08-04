# Reproducible benchmarking

The benchmark harness turns a TOML campaign specification into deterministic
scenario fixtures, solver runs, aggregate rankings, convergence traces, and an
integrity manifest. Runtime is measured, but scheduling quality remains the
primary comparison target.

## Campaign specifications

Two committed configurations are available:

- `configs/benchmark-smoke.toml`: 4 scenarios and 32 runs for fast end-to-end
  verification.
- `configs/benchmark-v1.toml`: 360 scenarios and 12,600 runs for the full v1
  campaign. This is intentionally not part of CI.

Each specification fixes the master seed, scenario size and difficulty cells,
instances per cell, solver set, algorithm seeds, evaluation budget, and optional
soft time limit. Duplicate dimensions and unknown solver names are rejected.

Run a campaign with:

```bash
orbitops benchmark configs/benchmark-smoke.toml --output runs/benchmark-smoke
```

Omitting `--output` writes to `runs/<benchmark-id>`. The `runs/` directory is
git-ignored because runtime-bearing reports can be large and machine-specific.

## Synthetic scenario matrix

Scenario seeds are derived with SHA-256 from the generator version, campaign ID,
master seed, size, difficulty, and instance index. Each generated scenario stores
that derived seed and receives a canonical content hash.

| Size | Tasks |
|---|---:|
| `tiny` | 6 |
| `small` | 10 |
| `medium` | 18 |
| `large` | 30 |

Difficulty tiers are operational generator settings, not empirically calibrated
labels. `easy` provides more and wider windows, higher resources, and faster
slewing. `hard` clusters narrow windows while reducing resources and slew rate.
`medium` lies between those profiles. A claim about real mission difficulty
would require external scenario data and separate validation.

## Fair comparison rules

Every configured solver receives the same scenario, algorithm-seed set, and
evaluation budget. Search solvers count unique decoded genomes; deterministic
baselines ignore the budget but are repeated across seeds so every solver has the
same number of comparison rows. A configured time limit is soft and introduces
machine-load sensitivity, so budget-only campaigns are preferred for quality
reproducibility.

Exact solvers may be configured, but their declared task limits still apply. An
unsupported or failed run is retained with its error and counted against the
solver's feasible rate; it does not abort the remaining campaign.

## Aggregation and ranking

For each scenario and algorithm seed, total value is divided by the best value
observed among feasible configured solvers. This produces a value ratio in
`[0, 1]` without mixing raw value scales across scenarios.

Solver ranking is deterministic and uses, in order:

1. feasible-run rate;
2. mean normalized value ratio;
3. rate of matching the best complete lexicographic objective observed;
4. mean completed tasks;
5. mean slew time; and
6. solver name as a final stable tie-breaker.

`mean_seed_value_stddev` averages each scenario's population standard deviation
of total value across algorithm seeds. It is a descriptive stability measure,
not a confidence interval or a significance test.

## Exported artifacts

Each output directory contains:

- `report.json`: complete typed specification, scenario descriptors, runs, and
  summaries, plus Python, platform, package, and generator provenance;
- `report.html`: responsive visual summary with rankings, a difficulty heatmap,
  search convergence, and one replay-verified schedule timeline;
- `runs.csv`: one flat row per scenario, solver, and algorithm seed;
- `summary.csv`: aggregate ranking and stability measures;
- `convergence.csv`: incumbent points for search solvers and a final synthetic
  point for non-search solvers;
- `scenarios/*.json`: exact generated scenario inputs; and
- `manifest.json`: SHA-256 hashes for every other artifact.

The report's `reproducibility_fingerprint` covers the specification, scenario
hashes, deterministic results, errors, evaluation counts, and convergence
traces. Runtime is deliberately excluded: two correct reruns should retain the
same fingerprint even when wall-clock measurements differ.

See [visual reports](visual-reports.md) for report selection and rendering
details.

## Interpretation boundary

The smoke configuration verifies the pipeline and can expose regressions. Its
ranking is not evidence of general algorithm superiority. Full comparative
claims should use the complete campaign or a preregistered alternative, retain
paired scenario-level observations, inspect effect sizes and uncertainty, and
avoid selecting only favorable seeds or difficulty cells.
