# Stage 9 reinforcement-learning verification

## Material Passport

- Origin Skill: none; direct repository implementation
- Origin Mode: algorithm build / automated validation
- Origin Date: 2026-08-04
- Verification Status: VERIFIED (reproducibility and integration)
- Version Label: stage9-learning-v1

## Verification Result

- Algorithm: dependency-free linear Q-learning with seeded epsilon-greedy exploration
- Training boundary: one policy trained online for one fingerprinted scenario
- Policy contract: committed JSON Schema matches the runtime Pydantic model
- Demo training: 40 episodes, 120 transitions, value 226, three completed tasks
- Demo replay: feasible, value 226, three completed tasks, policy fingerprint accepted
- Demo learned schedule: 44.0 seconds slew versus 48.4 for its greedy initializer
- Learning smoke campaign: two scenarios, two solvers, two seeds, eight runs
- Failed learning smoke runs: zero
- Repeated campaign fingerprint: `17cabf490bc934ad83f2ff10dc2d0d68879681d1f0f56c735c5081ea869dbe30`
- Fixed-scenario feasibility gate: all advanced solvers, including Q-learning,
  returned feasible schedules on 50 seeded scenarios
- Python quality gates: Ruff and strict mypy passed
- Test suite: 124 tests passed; 92.55% branch-aware coverage

The demo improvement is an integration observation, not a performance claim.
Episode count is not the same work unit as unique-genome evaluation, and the
saved policy is deliberately rejected for any changed or different scenario.
Stage 9 does not claim cross-scenario generalization, optimality, or superiority
over the existing hand-written algorithms.
