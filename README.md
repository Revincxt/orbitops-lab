<div align="center">

# OrbitOps Lab

**Earth-observation mission replay and scheduling research.**

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-6ad6ee?style=flat-square)](pyproject.toml)
[![CI](https://github.com/Revincxt/orbitops-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/Revincxt/orbitops-lab/actions/workflows/ci.yml)
[![Code: MIT](https://img.shields.io/badge/Code-MIT-8fa5bc?style=flat-square)](LICENSE)

[Live Demo](https://revincxt.github.io/orbitops-lab/) · [Quick Start](#quick-start) · [Data & Scope](#credits--scope)

</div>

![OrbitOps Lab workspace with satellite orbits, task list, algorithm comparison, observation timeline and satellite workloads](docs/assets/orbitops-workspace.jpg)

## Overview

A fixed-viewport engineering workspace for exploring satellite orbits, observation
tasks and scheduling results.

- **Orbit views** — 3D, 2.5D and 2D maps with satellite models, focus and follow.
- **Mission replay** — forward/reverse playback, UTC navigation and a synchronized satellite timeline.
- **Task inspection** — observation windows, task status, plan details and satellite workloads.
- **Plan comparison** — switch between reference plans and compare performance with radar charts.

The Python research core separately supports scheduling algorithms, independent
validation and reproducible benchmarks for synthetic single-satellite scenarios.
The hosted demo replays reference results; it does not run those solvers.

## Quick Start

Requires **Python 3.12+**. From a terminal:

```bash
git clone https://github.com/Revincxt/orbitops-lab.git
cd orbitops-lab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
orbitops lab
```

Open [localhost:8000](http://127.0.0.1:8000), or try the
[hosted demo](https://revincxt.github.io/orbitops-lab/) without installation.

## Credits & Scope

Demo records come from [EOS-Bench](https://github.com/Ethan19YQ/EOS-Bench), with
source revision, file hashes and validation results retained in the
[reference archive](data/eos-bench/reference.json). The checks cover source
consistency and selected constraints, not full operational feasibility.
Orbit extensions and sensor fields of view are illustrative, not operational telemetry.

[MIT](LICENSE) applies to OrbitOps-authored code; third-party data is separate.
