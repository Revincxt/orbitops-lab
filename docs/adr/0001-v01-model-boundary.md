# ADR-0001: Freeze the v0.1 scheduling boundary

- Status: Accepted
- Date: 2026-08-04

## Context

Orbit scheduling can expand into orbit propagation, communications, multi-agent
coordination, weather uncertainty, and many other concerns. Implementing them at
once would make correctness hard to isolate.

## Decision

v0.1 models one satellite, precomputed observation windows, constant task
resource costs, a one-dimensional signed attitude, constant slew rate, and a
deterministic offline horizon. The JSON contract is versioned as `0.1` and
rejects unknown fields.

## Consequences

The simulator and solvers can be tested against small hand-computed cases. Real
orbit propagation, downlink, stochastic cloud cover, and multiple satellites
require new versioned contracts instead of silent changes to v0.1.

