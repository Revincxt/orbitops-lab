# Stage 8 Web Lab verification

## Material Passport

- Origin Skill: sites:sites-building
- Origin Mode: capability / build and structural validation
- Origin Date: 2026-08-04
- Verification Status: VERIFIED (automated and local API)
- Version Label: stage8-web-lab-v1

## Verification Result

- Launch command: `.venv/bin/orbitops lab --scenarios scenarios --host 127.0.0.1 --port 8765`
- Health response: HTTP 200, status `ok`, three validated scenarios
- Homepage response: HTTP 200, `text/html; charset=utf-8`
- Demo solve response: HTTP 200, feasible, value 226, three completed tasks
- Security headers: CSP, `no-store`, `nosniff`, and `no-referrer` present
- JavaScript syntax check: passed with bundled Node.js
- Wheel build: passed; `index.html`, `app.css`, and `app.js` included
- Python quality gates: Ruff and strict mypy passed
- Test suite: 106 tests passed; 91.92% branch-aware coverage
- Deployment status: local-only; no remote service or hosted data store

Automated checks cover scenario filtering, API validation, baseline and search
solves, exact-solver limits, safe fixed static routes, interface landmarks,
responsive styles, DOM construction, response security headers, server cleanup,
and CLI wiring. The stage does not claim browser screenshot approval because no
browser-based visual review was requested.
