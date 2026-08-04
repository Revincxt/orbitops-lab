# Baseline algorithms

Every solver returns only a candidate `Schedule`. The shared validator then
simulates, rejects, and scores it. Solvers cannot publish self-reported resource
states or objective values.

## Feasible insertion primitive

For each task window and chronological gap, the insertion engine calculates the
earliest and latest starts allowed by observation duration and the incoming and
outgoing attitude transitions. Both boundary starts are sent through the full
constraint validator. Testing the latest boundary allows extra charging time
without introducing an arbitrary time grid.

The primitive returns only schedules accepted by the common validator.

## Included solvers

- `random-feasible`: seeded shuffle of tasks and seeded choice among feasible insertions.
- `greedy-value`: descending task priority value.
- `greedy-density`: descending priority value per observation second.
- `greedy-deadline`: ascending earliest visibility-window deadline.
- `greedy-insertion`: repeatedly chooses the globally best feasible insertion
  under the v0.1 lexicographic objective.

Task IDs, starts, windows, and total slew provide deterministic tie-breaking.
The optional time limit is soft and checked between insertion evaluations.

## Exact tiny-instance search

- `brute-force` enumerates every feasible task order and window selection for
  scenarios containing at most 10 tasks.
- `branch-and-bound` supports at most 16 tasks, starts from a value-greedy lower
  bound, and prunes using an optimistic lexicographic bound that assumes every
  remaining task can be completed with no additional slew.

For a fixed task order and chosen windows, both solvers schedule each task at its
earliest resource-feasible start. This remains exact under v0.1 because charging
is constant, storage never decreases, and all resource costs are deterministic:
executing a task earlier leaves no less time or energy for subsequent work.
Consequently, enumerating order and window choices is sufficient without a time
grid. [ADR-0002](adr/0002-exact-search-dominance.md) records the proof boundary.

Search metadata reports expanded nodes, feasible extensions, pruned branches,
timeout state, and whether optimality was proven. A time-limited result remains
feasible but is not labeled optimal.

## Shared stochastic-search representation

Local search and the genetic algorithm represent a candidate as:

- a permutation containing every scenario task exactly once; and
- an active set describing which tasks the decoder may schedule.

The deterministic decoder visits active tasks in permutation order and applies
the same feasible-insertion primitive as the baselines. Every decoded schedule
is checked by the shared validator before it can be ranked. This intentionally
trades some representational freedom for a strong invariant: stochastic search
never returns a schedule that bypassed the production constraints.

`--evaluation-budget` counts unique decoded genomes. Re-evaluating a cached
genome does not consume the budget. The deterministic greedy initializer is
constructed first, then its genome is decoded as evaluation one. A soft time
limit can stop either algorithm between candidate evaluations.

## Multi-start local search

`local-search` begins from the global greedy-insertion schedule and performs
strict-improvement hill climbing. Its neighborhood contains four moves:

- activate one excluded task;
- deactivate one included task;
- swap two positions in the priority order; and
- relocate one task to another position.

After a stagnation threshold, the solver starts another seeded random genome,
up to four starts in total. Metadata includes attempted, evaluated, accepted,
and globally improving move counts per operator, plus the incumbent convergence
trace. The algorithm is reproducible for fixed scenario, seed, budget, and code
version, but it does not prove optimality.

## Genetic algorithm

`genetic` seeds its population with greedy insertion, value order, and random
genomes. Each generation uses tournament selection, one-cut order-preserving
crossover, active-set inheritance, swap/relocate/toggle mutations, and two-elite
survival. Default constants are committed in the solver:

- maximum population size: 24;
- tournament size: 3;
- crossover probability: 0.9; and
- per-mutation probability: 0.2.

Population size scales up to twice the task count within the cap. Metadata
records the effective population, generations, parameters, stopping reason, and
every incumbent improvement.

## Comparing stochastic algorithms

A single seed is a reproducibility check, not evidence that one algorithm is
better. Comparative benchmarks should hold scenarios and evaluation budgets
fixed, use multiple algorithm seeds, report the distribution of the complete
lexicographic objective, and include runtime only as a separately measured
quantity. The Stage 5 verification manifest is a smoke gate; the benchmark
harness documented in [benchmarking](benchmarking.md) provides the broader,
multi-scenario comparison path.
