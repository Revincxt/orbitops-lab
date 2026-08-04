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
