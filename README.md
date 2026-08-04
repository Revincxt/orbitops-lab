# OrbitOps Lab

OrbitOps Lab is a reproducible scheduling laboratory for agile Earth-observation
satellites. It is being built in small, independently verifiable stages: a typed
domain model first, then a discrete-event simulator, constraint validation,
hand-written scheduling algorithms, benchmarks, and an interactive web lab.

> Status: Stage 4 — versioned contracts, deterministic simulation, explainable
> validation, five baselines, and two exact tiny-instance solvers are in place.

## What is implemented from scratch?

The project will implement its scheduling model, simulator, constraint validator,
heuristics, local search, genetic algorithm, branch-and-bound solver, benchmark
harness, and reinforcement-learning training loop. Third-party libraries provide
general infrastructure, not the scheduling answers used in the main results.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
orbitops validate scenarios/examples/demo.json
orbitops check scenarios/examples/demo.json scenarios/examples/feasible-schedule.json
orbitops solve scenarios/examples/demo.json --solver greedy-insertion --seed 42
orbitops solve scenarios/tiny/tiny-conflict.json --solver branch-and-bound
pytest
```

## v0.1 scope

- One agile satellite and multiple observation tasks.
- Offline scheduling with precomputed visibility windows.
- Time-window, non-overlap, slew, energy, and storage constraints.
- Lexicographic objective: total value, completed task count, then slew time.

High-fidelity orbit propagation, downlink planning, and multi-satellite
coordination are deliberately deferred.

## Repository map

- `packages/orbitops/domain/`: immutable domain models and objective definition.
- `packages/orbitops/simulation/`: shared state transitions, event simulation, and validation.
- `packages/orbitops/solvers/`: common solver contract and later implementations.
- Built-in baselines: random feasible, value, value density, deadline, and global insertion.
- Exact solvers: exhaustive search up to 10 tasks and branch-and-bound up to 16 tasks.
- `scenarios/`: versioned input fixtures.
- `schemas/`: committed JSON Schema contracts.
- `tests/`: unit, property, integration, and golden tests.
- `docs/`: formulation and architecture decisions.

See [the v0.1 problem formulation](docs/problem-formulation.md) and
[simulation model](docs/simulation-model.md) for the executable assumptions.
