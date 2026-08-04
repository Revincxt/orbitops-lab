# OrbitOps Lab

OrbitOps Lab is a reproducible scheduling laboratory for agile Earth-observation
satellites. It is being built in small, independently verifiable stages: a typed
domain model first, then a discrete-event simulator, constraint validation,
hand-written scheduling algorithms, benchmarks, and an interactive web lab.

> Status: Stage 9 — versioned contracts, deterministic simulation, explainable
> validation, ten solvers, reproducible benchmarks, standalone reports, an
> interactive Web Lab, and a scenario-bound Q-learning pipeline are in place.

## What is implemented from scratch?

The project implements its scheduling model, simulator, constraint validator,
heuristics, local search, genetic algorithm, branch-and-bound solver, synthetic
scenario generator, benchmark harness, and linear Q-learning loop from scratch.
Benchmark reports are rendered without a plotting framework or external assets.
Third-party libraries provide general infrastructure, not the scheduling
answers used in the main results.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
orbitops validate scenarios/examples/demo.json
orbitops check scenarios/examples/demo.json scenarios/examples/feasible-schedule.json
orbitops solve scenarios/examples/demo.json --solver greedy-insertion --seed 42
orbitops solve scenarios/examples/demo.json --solver local-search --seed 42 --evaluation-budget 500
orbitops solve scenarios/examples/demo.json --solver genetic --seed 42 --evaluation-budget 500
orbitops solve scenarios/examples/demo.json --solver q-learning --seed 42 --evaluation-budget 250
orbitops solve scenarios/tiny/tiny-conflict.json --solver branch-and-bound
orbitops benchmark configs/benchmark-smoke.toml --output runs/benchmark-smoke
orbitops report runs/benchmark-smoke/report.json --output runs/custom-report.html
orbitops train scenarios/examples/demo.json --model-output runs/demo-policy.json --episodes 250
orbitops apply-policy scenarios/examples/demo.json runs/demo-policy.json
orbitops lab --scenarios scenarios
pytest
```

Open `http://127.0.0.1:8000` after launching the lab. Choose a scenario and
solver to inspect the validated observation timeline, resource trace, and search
convergence without uploading mission data or depending on a hosted service.

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
- `packages/orbitops/benchmarking/`: deterministic scenario matrix, campaign
  runner, aggregation, reproducibility fingerprint, and artifact export.
- `packages/orbitops/reporting/`: responsive standalone ranking, heatmap,
  convergence, and schedule visualizations.
- `packages/orbitops/learning/`: feasibility-preserving environment, versioned
  linear policy, seeded Q-learning trainer, and fingerprint-checked replay.
- `packages/orbitops/web/`: framework-free local API and responsive Web Lab for
  running solvers and inspecting validated schedules interactively.
- Built-in baselines: random feasible, value, value density, deadline, and global insertion.
- Exact solvers: exhaustive search up to 10 tasks and branch-and-bound up to 16 tasks.
- Advanced solvers: multi-start local search and a genetic algorithm, both with
  seeded randomness, feasible decoding, evaluation budgets, and convergence traces.
- Learning solver: per-scenario linear Q-learning with seeded exploration,
  training traces, portable model JSON, and a greedy-insertion lower bound.
- `scenarios/`: versioned input fixtures.
- `schemas/`: committed Scenario, Schedule, and learned-policy JSON Schema contracts.
- `tests/`: unit, property, integration, and golden tests.
- `docs/`: formulation and architecture decisions.

See [the v0.1 problem formulation](docs/problem-formulation.md) and
[simulation model](docs/simulation-model.md) for the executable assumptions.
[Algorithm documentation](docs/algorithms.md) describes every built-in solver
and the comparison boundary for stochastic search. See
[benchmarking](docs/benchmarking.md) for campaign configuration, ranking rules,
and artifact semantics. [Visual reports](docs/visual-reports.md) documents the
HTML report and representative-schedule replay. [Web Lab](docs/web-lab.md)
documents the local application, API, visual semantics, and safety boundary.
[Reinforcement learning](docs/reinforcement-learning.md) defines the learning
environment, update rule, model artifact, and strict evidence boundary.
