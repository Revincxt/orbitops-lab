# v0.1 problem formulation

## Decision variables

For each task, a solver chooses whether to execute it and, if selected, one
visibility window and a start time inside that window.

## Hard constraints

1. A task is executed at most once.
2. Its full duration lies inside the selected visibility window.
3. Observation intervals never overlap.
4. Consecutive observations leave enough time for slew and settling.
5. Energy remains within `[0, capacity]` throughout the horizon.
6. Storage remains within `[0, capacity]` throughout the horizon.
7. Every resource state is computed by the shared event simulator.

## Objective

Compare feasible schedules lexicographically:

1. Maximize the sum of task priority values.
2. Then maximize the number of completed tasks.
3. Then minimize total slew time.

Training rewards may be shaped later, but published comparisons use this
objective after the common validator accepts the schedule.

## Time and interval semantics

All v0.1 timestamps are floating-point seconds relative to the scenario epoch.
Visibility and scheduled intervals use half-open semantics: `[start_s, end_s)`.
This permits one event to start exactly when another event ends.

## Solver/simulator trust boundary

A solver returns only task IDs, selected windows, and start times. It cannot
provide trusted end times or resource values. The common simulator derives those
fields and the validator reports stable machine-readable issue codes. See
[`simulation-model.md`](simulation-model.md) for the state-transition rules.
