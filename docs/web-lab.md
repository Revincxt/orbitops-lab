# Web Lab Guide

OrbitOps Lab replays one pinned EOS-Bench scenario: **20 satellites, 500 tasks,
12 hours and seven source plans**. The browser never runs a solver. Synthetic
single-satellite experiments remain available through the separate Python
[research CLI](benchmarking.md) and Python API.

## Run locally

Install the project as described in the [README](../README.md#quick-start), then
run from the repository root:

```bash
orbitops lab
```

Open [localhost:8000](http://127.0.0.1:8000). Optional settings:

```bash
orbitops lab --host 127.0.0.1 --port 8123
orbitops lab --reference data/eos-bench/reference.json
```

A custom reference archive needs its matching `.sha256` file and manifest-listed
`orbits/` chunks beside it. Altered archives fail integrity checks. The server
does not load the synthetic `scenarios/` directory.

The default loopback address keeps the service local. A non-loopback bind
exposes it to that network; this development server has no authentication.

## Workspace

The page stays within the viewport. Task List and Timeline scroll internally;
small screens use Map / Tasks / Results navigation.

- The selector beside Repository switches source plans immediately.
- Task List, map targets and Timeline share selection. Plan summary shows the
  selected task's coordinates, priority, duration, observation time, satellite,
  data volume and source orbit number.
- Comparison plots TP, TCR, TM, source RT and BD. Outward means better:
  TP / highest TP, TCR, 1 − TM, fastest RT / RT and BD. Raw values remain
  available; different source objectives are not combined into an overall rank.
- Satellite workload shows source observation durations. Timeline aligns the
  replay scrubber with the UTC scale and all 20 satellite lanes.

## Map and playback

Switch between 3D, unfolded 2.5D and 2D without resetting the replay clock.
Overview releases tracking; Follow tracks the selected satellite. Click a
satellite for its translucent detail popup; double-click to focus. The popup
reports WGS84 altitude and latitude/longitude, orbital period and ECEF X/Y/Z in
kilometres, using the same replay position as the displayed model.

Layers control targets, orbit paths, sensor FOV, IDs and the 3D Sun/day-night
environment. Solar lighting has no drawn boundary or direction marker and is
disabled in unfolded views. The 3D starfield is visual context. Native map
provider credits are retained.

The centred controls are previous 12-hour window, play/pause, next 12-hour
window, reset, direction and speed. Scrub in Timeline or click the UTC clock
below ORBITOPS to jump to a time. Playback extends in both directions beyond the
source horizon; tasks execute only within the original planning interval.

Inside the source interval, positions use original samples. Outside it,
`Estimated orbit` identifies an illustrative two-body extension calibrated at
the source boundaries. It is not an operational ephemeris or a new Orekit/SGP4
solution; perturbations and manoeuvres are not modelled.

The circular sensor cone has a **45° full opening angle**. Scheduled raw Euler
samples are retained, but the display reverses skyward boresights and caps
off-nadir deflection at **29.5°**. Idle gaps use angle-timed eased transitions
(minimum 30 simulation seconds, nominal 0.5°/second when space permits).
Cone and footprint share the same Earth intersection boundary. These are
display assumptions, not verified spacecraft dynamics or certified coverage.

## EOS-Bench reference data

The archive `data/eos-bench/reference.json` derives from nine files at EOS-Bench
revision `ee282656e8b2f6fd0d3cf84677b40966e2780ef3`. It retains original satellite
elements/epochs, 500 task identities and attributes, 4,035 access windows,
scheduled attitude arrays and seven plans:

- Balanced SA and profit SA.
- Profit-first Greedy and profit PPO.
- One profit-objective plan each for MIP, GA and ACO.

The source epoch is `2025-11-18T12:00:00Z`; the horizon is 43,200 seconds.
A 30-second position preview is stored in the main archive. All **864,020**
unique 1-second satellite positions are retained in twelve hourly chunks with
shared boundary samples. The browser checks chunk SHA-256 and caches at most
four chunks. Preview data remains usable while dense samples load; loading
failures pause playback rather than silently claiming full precision.

The importer checks pinned Git blob hashes and records source URLs, byte counts
and SHA-256. Server startup and static builds verify the archive checksum;
chunk content is also checked before serving or publishing.

### Validation scope

TP/TCR/TM/BD are recomputed and reconciled with source metrics. Checks cover
task identities/partition, intervals, required durations, source-window
containment and per-satellite observation overlap. Additional diagnostics cover
attitude sample completeness, angle limits, per-orbit storage/power-cost
budgets, conditional gaps under four agility profiles and WGS84 Earth occlusion.

**This is not a full feasibility certificate.** The source orbit and access
windows disagree for many assignments. Source agility profiles are unrecorded;
the scheduler's power-cost budget is not battery energy. Attitude frame
consistency, full sensor geometry, battery dynamics and downlink remain
unverified. Original assignments and metrics are not rewritten to fit display
corrections. Full feasibility remains `null`; no missing seed, energy trace or
causal exclusion reason is fabricated.

These are simulation benchmark records, not telemetry. BD uses twice the
duration demand of all tasks as its denominator; TM penalizes unassigned tasks
by the full horizon. Source RT is solver runtime, not viewer performance.

### Regenerate and attribution

Download the pinned files and tree metadata using the local names listed in
[the importer](../scripts/import_eos_reference.py), then run:

```bash
python scripts/import_eos_reference.py /path/to/downloaded-source
```

Source: [EOS-Bench](https://github.com/Ethan19YQ/EOS-Bench). The pinned tree has no
license declaration; review third-party redistribution rights separately.
Attribution and hashes establish provenance, not a redistribution license.
OrbitOps-authored code is MIT; bundled Inter retains its SIL Open Font License.
Satellite model attribution is in [the asset guide](../packages/orbitops/web/static/models/README.md).

## Local HTTP service

The service exposes only these read-only data routes, plus fixed browser assets:

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Archive availability and the single loaded scenario count. |
| GET | `/api/reference/data` | Integrity-checked reference archive and display metadata. |
| GET | `/orbit-data/{filename}` | One manifest-listed, hash-verified orbit chunk. |

Missing archives return 503 from health/data routes. Unknown or retired routes
return 404. POST/PUT/PATCH/DELETE return 405 without reading request bodies.
There are no Web solve, scenario-catalog or per-plan endpoints; plan switching
uses the already loaded archive.

The server has no uploads, accounts or persistence. Paths are never mapped to
arbitrary files. Responses retain `no-store`, `nosniff`, `no-referrer` and a
source-restricted CSP. Cesium's browser build needs `unsafe-eval`; permitted
remote origins are the official Cesium CDN and NASA GIBS.

## Static deployment

[GitHub Pages](https://revincxt.github.io/orbitops-lab/) uses the same frontend
without Python endpoints. Build locally:

```bash
python scripts/build_pages.py --output site
```

The artifact includes `pages-data.json`, fixed assets and verified
`orbit-data/` chunks. No solver runs or synthetic scenarios are included.
Non-empty output directories can be replaced only if they carry the builder's
valid artifact marker; source assets and data directories are protected.
The repository's Pages workflow builds and deploys pushes to `main`.

CesiumJS 1.143 loads from the official CDN. NASA GIBS Blue Marble imagery uses
bundled Natural Earth II as a fallback. If the 3D engine is unavailable, the
selectable schematic 2D map keeps tasks, replay and charts accessible. Positions
stay in the browser; they are not uploaded to Cesium ion or NASA.

## Verify changes

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
mypy
pytest
node --test tests/javascript/*.test.cjs
```

Optional browser checks need Playwright and Chrome (or
`ORBITOPS_BROWSER_EXECUTABLE` pointing to Chromium). Native WebGL checks also
need the Cesium CDN:

```bash
ORBITOPS_BROWSER_TESTS=1 pytest tests/browser/test_workbench.py
ORBITOPS_BROWSER_TESTS=1 ORBITOPS_GLOBE_TESTS=1 pytest tests/browser/test_globe.py
```

Tests cover read-only routes, integrity/path safety, Pages builds, source
immutability, bounded replay, plan switching, selection, responsive layout,
circular FOV and the native camera/popup behaviour. They do not certify
real-mission accuracy.
