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
orbitops benchmark configs/benchmark-smoke.toml \
  --output runs/benchmark-smoke \
  --workers 4
```

Omitting `--output` writes to `runs/<benchmark-id>`. The `runs/` directory is
git-ignored because runtime-bearing reports can be large and machine-specific.

Every run receives a content-addressed `run_key` and is written to an atomic
checkpoint as soon as it finishes. By default checkpoints live beside the output
directory in `.<output-name>.checkpoints`; select another location with
`--checkpoint-dir`. Resume an interrupted campaign without rerunning completed
cells with:

```bash
orbitops benchmark configs/benchmark-v1.toml \
  --output runs/benchmark-v1 \
  --workers 4 \
  --resume
```

Checkpoint identity covers the exact scenario content, solver, algorithm seed,
evaluation budget, time limit, and the explicit benchmark-run contract version.
That contract is bumped whenever solver, objective, simulator, or result
semantics can change, so an upgrade cannot silently mix old and new records in
one resumed report. Corrupt or mismatched checkpoints fail closed. Use
`--retry-failures` to rerun checkpoints that recorded an exception. Worker
completion order does not affect report ordering or the reproducibility
fingerprint.

If the campaign is interrupted, work that has not started is cancelled instead
of draining the entire pending matrix. Already committed checkpoints remain
valid; an in-flight thread may finish internally but is intentionally rerun on
the next `--resume` unless its record had already been atomically committed.

Parallel workers are available only for budget-bounded campaigns. A campaign
with a wall-clock `time_limit_s` must use `--workers 1`, because thread
contention changes how much search fits inside a soft deadline and would make
cross-worker checkpoint reuse scientifically ambiguous.

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
`[0, 1]` without mixing raw value scales across scenarios. If every feasible
solver has zero value in a cell, each receives ratio `1`.

Algorithm seeds are repeated measurements inside one scenario, not independent
scenario samples. A solver's seed-level ratios are therefore averaged within
each scenario and the reported `mean_value_ratio` gives every scenario equal
weight. Its deterministic percentile-bootstrap 95% interval resamples whole
scenario blocks while retaining all seed observations inside each block.
`value_ratio_scenario_count` records the number of scenarios that contributed
at least one feasible run. Value-ratio evidence is conditional on feasibility;
the feasible-run rate remains a separate, higher-priority ranking measure.

Solver ranking is deterministic and uses, in order:

1. feasible-run rate;
2. mean normalized value ratio;
3. rate of matching the best complete lexicographic objective observed;
4. mean completed tasks;
5. mean slew time; and
6. solver name as a final stable tie-breaker.

`mean_seed_value_stddev` averages each scenario's population standard deviation
of total value across algorithm seeds. Raw total-value means and medians are
descriptive only because their scales differ across scenarios. The deprecated
raw-value confidence-interval fields remain readable for report-schema v1 but
are left empty in newly generated v2 reports.

`comparisons.csv` reports paired outcomes on shared scenario/seed cells.
Feasibility is compared first and the complete lexicographic objective second.
A one-sided failure is a win or loss; a cell where both solvers fail increments
`failed_both_count` and is excluded rather than counted as a tie. Consequently,
`win_rate_a` uses `paired_count - failed_both_count` as its denominator and is
empty when every shared cell is excluded. Ties require both runs to be feasible
and equal under the complete objective.

For jointly feasible cells, the primary-value effect is the difference between
the two normalized value ratios. Seed-level gaps are averaged within scenario,
scenarios receive equal weight, and the 95% interval resamples scenario blocks.
Win/tie/loss can disagree with the sign of this primary-value gap when completed
tasks or slew break a value tie. These intervals describe the generated
campaign; they do not establish general mission performance.

Benchmark report schema v2 carries these aggregation semantics. The reader also
accepts schema v1 reports; legacy raw confidence intervals and legacy failure
accounting are preserved as recorded rather than silently reinterpreted.

## Exported artifacts

Each output directory contains:

- `report.json`: complete typed specification, scenario descriptors, runs, and
  summaries, plus Python, platform, package, and generator provenance;
- `report.html`: responsive visual summary with rankings, a difficulty heatmap,
  search convergence, and one replay-verified schedule timeline;
- `runs.csv`: one flat row per scenario, solver, and algorithm seed;
- `summary.csv`: aggregate ranking, stability measures, scenario-block
  normalized-ratio intervals, and the report schema version;
- `comparisons.csv`: paired solver evidence on common scenario/seed cells,
  including joint-failure exclusions and scenario-block normalized-gap
  intervals;
- `convergence.csv`: incumbent points for search solvers and a final synthetic
  point for non-search solvers;
- `scenarios/*.json`: exact generated scenario inputs; and
- `manifest.json`: the dedicated `orbitops-benchmark` artifact type and SHA-256
  hashes for every other artifact.

Exports are first written to a sibling staging directory, verified, and then
swapped into place. This prevents interrupted exports from leaving mixed old and
new artifacts. Before replacing an existing directory, it verifies every
manifest-listed checksum and the typed report identity; extra stale files may be
removed only after that verification succeeds. The exporter refuses to replace a
non-empty directory that is not a verified OrbitOps benchmark artifact. Fully
verified legacy manifests remain replaceable. Verify a completed export later
with:

```bash
orbitops benchmark-verify runs/benchmark-smoke
```

Verification rejects missing, modified, and stale files and cross-checks the
report identity against the manifest.

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
