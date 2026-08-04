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
