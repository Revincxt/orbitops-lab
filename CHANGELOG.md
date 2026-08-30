# Changelog

All notable changes to OrbitOps Lab are recorded here. The project follows
[Semantic Versioning](https://semver.org/).

## 0.2.0 — 2026-08-30

### Added

- A comparative-methods research interface with per-scenario solver tables,
  constraint audits, run provenance, and explicit precomputation omissions.
- Four deterministic showcase scenarios spanning 6, 10, 18, and 30 tasks.
- A replayable `q-policy-only` solver alongside the backward-compatible hybrid
  `q-learning` solver.
- Per-episode deterministic policy-checkpoint replay, selected-checkpoint
  provenance, and separate pure-policy convergence evidence.
- Atomic run checkpoints, bounded parallel benchmark workers, `--resume`, and
  `--retry-failures` for long campaigns.
- Scenario-block bootstrap intervals for normalized solver ratios and paired
  normalized value gaps, with jointly failed cells excluded rather than tied.
- Transactional benchmark exports and `orbitops benchmark-verify` integrity
  checking.

### Changed

- Objective value aggregation is stable for every ordering of the same task
  set.
- Learning resource headroom is measured after the current plan rather than
  after recharge to the scenario horizon.
- Linear Q policies use the explicit v2 feature contract; v1 policy artifacts
  are rejected instead of being replayed under changed resource semantics. v1
  artifacts must be retrained; there is no safe weight-only migration to v2.
- `orbitops train` reports exported-policy and hybrid-result metrics separately,
  removing the previous ambiguous training summary.
- Search deadlines now cover greedy initialization and candidate decoding;
  Q-learning uses the same absolute deadline for action enumeration, training,
  and policy-checkpoint replay.
- Web learning curves identify their objective as the realized exploratory
  episode schedule rather than pure-policy performance.
- Static Pages builds use size-aware budgets and publish the actual run
  settings and provenance.

### Security

- Pages output replacement now uses a marked staging directory and rejects
  source, symlink, and unknown non-empty destinations.
- Benchmark artifact replacement verifies the dedicated artifact type, typed
  report identity, complete file set, and every recorded checksum.

## 0.1.0 — 2026-08-04

- Initial reproducible scheduling core, simulator, validators, solver
  portfolio, benchmark harness, Web Lab, and GitHub Pages artifact.
