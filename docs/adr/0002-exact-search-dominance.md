# ADR-0002: Exact search uses earliest resource-feasible dominance

- Status: Accepted
- Date: 2026-08-04

## Context

Observation start times are continuous. A naive exact solver would need an
arbitrary time grid, making its optimality claim dependent on grid resolution.

## Decision

For each fixed task order and visibility-window selection, exact solvers append
each task at its earliest start satisfying:

1. the selected visibility window;
2. incoming slew and settling time;
3. sufficient charged energy at observation completion; and
4. remaining storage capacity.

The search enumerates task subsets, permutations, and window choices, but does
not enumerate later start times for the same prefix.

## Dominance argument

Under v0.1, charge input is constant, capped only by battery capacity; task costs
are deterministic; storage only increases; and future visibility windows do not
depend on earlier execution times. For the same prefix, moving a feasible task
earlier preserves its storage and final attitude while weakly increasing the
time available before every later deadline. By the delayed schedule's next event
time, the earlier schedule has had at least as much post-consumption charging,
and battery capping cannot make its available energy smaller. Therefore the
earliest feasible prefix weakly dominates any delayed version. Applying this
argument inductively proves that at least one optimal schedule is represented by
the finite order-and-window search.

## Consequences

The exhaustive and branch-and-bound solvers can make an optimality claim only
when search completes without timeout and the scenario respects v0.1. Adding
time-varying eclipse charging, downlink, release times coupled to earlier events,
or stochastic resources invalidates this dominance argument and requires a new
model version and exact-search proof.
