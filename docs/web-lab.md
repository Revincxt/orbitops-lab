# Interactive Web Lab

The demo is a read-only EOS-Bench mission workspace: one pinned 20-satellite,
500-task scenario with four original source plans. It contains no scenario
switcher, local solve controls, seed input or evaluation budget. Synthetic
scenarios and OrbitOps solvers remain available through the Python CLI and API,
but are not part of the demo or its static deployment.

The presentation layer combines an interactive CesiumJS mission-context globe
with framework-free SVG evidence charts. Cesium is responsible only for WGS84
geometry and interaction; it does not solve, simulate, score, or validate a
schedule.

## Launch

From the repository root, with the development environment installed:

```bash
orbitops lab --scenarios scenarios
```

Then open `http://127.0.0.1:8000`. The bind address and port are configurable:

```bash
orbitops lab --scenarios scenarios --host 127.0.0.1 --port 8123
```

The default loopback address keeps the lab on the current machine. Binding to a
non-loopback interface exposes it to that network and should be an explicit
operator decision.

## GitHub Pages deployment

The hosted interface is available at
`https://revincxt.github.io/orbitops-lab/`. GitHub Pages cannot execute the
Python API, so the workflow packages only the pinned EOS-Bench reference archive
and the framework-free interface. `pages-data.json` contains metadata and the
reference archive; no local catalogs, synthetic scenarios, precomputed local
runs or omission manifest are included. Static generation performs no solves.

Every push to `main` runs `scripts/build_pages.py` and deploys through the
repository's GitHub Pages workflow. The local demo fetches only
`/api/reference/data`; both deployments use the same replay and metric code.
If the archive is unavailable, startup reports an error without switching to a
synthetic scenario.

## Interaction model

The fixed-viewport engineering workspace keeps configuration, mission geometry,
and output inspection visible together. The page and its panels do not scroll:
target catalogs, timeline rows, solver comparisons, exclusions, and validator
issues use height-aware pagination. On narrow screens the side panels become
exclusive drawers, opened from the header and dismissed with Escape.

The left panel selects one of the four reference plans and contains the
paginated target catalog. The centre prioritizes the orbit view, with a compact
analysis dock below it. The right panel shows four primary metrics, target
details and satellite workload. Projection controls live in the map toolbar;
layer switches are grouped in a dismissible menu.

Changing a plan marks the current output as pending until Load plan is pressed.
Ctrl+Enter (Cmd+Enter on macOS) loads the selected plan. Comparison rows can also
activate a source plan. Reloading resets playback and camera tracking but
preserves the selected projection; it never calls a local solver. Legacy
`?mode=local` URLs no longer expose other scenarios.

The analysis dock contains:

- **Timeline:** source observation intervals and the selected task's visibility
  windows, paginated across all 20 satellite lanes.
- **Comparison:** TP/TCR/TM/BD, original runtime, check scope and objectives for
  all four plans; different objectives are not collapsed into one ranking.
- **Audit:** unassigned tasks, source consistency checks and verification gaps.
- **Data:** pinned file hashes and source provenance.

The inspector keeps TP, planned task count, TM and full feasibility visible.
N/A remains explicitly labelled Not verified. Additional metrics and the run
record are separate tabs. Runtime explanations, source-model details and
validation caveats do not repeat across the main workspace. Source attribution,
revision and verification scope remain accessible in Run record and Data.
Satellite workload bars support mouse and keyboard selection.

Selecting a target in the catalog, Gantt, or map updates the same inspector and
selection highlight. The inspector exposes coordinates, priority, duration,
satellite assignment, observation interval, data volume and source orbit number.
The layers menu toggles targets, orbit paths, observation links, target IDs and
satellite IDs. Escape, outside clicks and focus leaving the menu dismiss it.
Export downloads the complete reference payload, including scenario, plan,
provenance and verification scope. Load failures remain visible in the status
bar. Targets on the far side of Earth are depth-occluded.

The shared playback clock supports pause, reset, scrubbing and selectable speed.
Reference times use an explicit UTC epoch. Catalog, map, timeline cursor and
task details share half-open interval
semantics: observing at start, completed at end. Planned completion metrics stay
separate from the playback-completed count. Task search, status and satellite
filters keep large scenes reachable without scrollbars.

The orbit display uses a bounded one-period window, shifted inside the source
sample horizon at its ends. Past trajectory is solid; future sampled trajectory
is dashed. Tracks are visible even when paused at the initial epoch. These are
source-replay samples, not a new orbit prediction or a closed ellipse invented
from orbital elements. The 2D fallback splits lines at the date line with
interpolated seam endpoints, rather than connecting them across the map.

Satellites have screen-space engineering symbols and colour-matched names,
tracks and selection halos. Symbols do not represent physical scale or attitude.
Click a satellite/track to select it, or double-click to focus. The map readout
shows display-interpolated WGS84 ellipsoid altitude and the source orbital period.
Overview, Focus and Follow are explicit camera modes; selecting a task links the
associated satellite without automatically flying the camera. Overview and the fit button release
tracking. Target IDs are distance-limited to avoid labelling all 500 targets at
global scale; the selected target stays labelled. Depth testing stays enabled
for targets, satellite symbols and labels, so the far side is occluded.

The map can temporarily expand within the centre workspace while the two side
panels remain available; restore returns the analysis dock. Camera framing
accounts for both viewport axes and all retained orbital altitudes, and refits
when an overview viewport is resized. A north-reset compass reflects the current
camera heading instead of showing a static orientation indicator. Small/short
map viewports compact the satellite readout to keep the globe accessible.

The map toolbar's projection controls switch between the native Cesium 3D
globe, tilted 2.5D unfolded map (Columbus View), and 2D geographic map. All views
share the same source positions, task selection, layers and replay clock; a
projection change does not restart or pause playback. 2.5D retains orbital
height above the projected map; 2D flattens that height spatially while the
source altitude remains available in the satellite readout. Switching releases
camera tracking and fits an overview. Focus and follow work in every view;
2D follow centres on the source sub-satellite position without a 3D camera
transform. World-map framing accounts for both viewport axes and source
altitudes, including after pane expansion or resize. Controls are disabled
during the short transition and when only the offline 2D schematic is available.
Reduced-motion preferences use instantaneous view changes.

## EOS-Bench reference data

`data/eos-bench/reference.json` is a pinned derivative of six public source files
from revision `ee282656e8b2f6fd0d3cf84677b40966e2780ef3`. It retains 20 satellites,
500 original mission IDs/coordinates/priorities/durations, 4,035 original access
windows and four source plans: balanced SA, profit SA, profit-first Greedy and
profit PPO. Original orbital elements and UTC epochs are retained. Position
samples come directly from the source CZML, not a new invented trajectory.

The importer checks every downloaded file against its pinned Git blob hash and
records SHA-256, source URL and byte count. The generated archive has a separate
SHA-256 integrity record, checked at server startup and before static builds;
modified snapshots are rejected. It retains every thirtieth original orbit
sample plus the final sample, reducing the display archive to about 3 MB.
Cesium uses linear Cartesian interpolation; the 2D fallback uses date-line-aware
geodetic interpolation. Neither is a new high-fidelity propagator. Original
window boundaries and assignment times are not resampled or altered.

TP/TCR/TM/BD are recomputed from the imported tasks and assignments and reconciled
against source metrics. ID validity, uniqueness, horizon, required duration,
containing source windows, per-satellite observation overlap and task partition
are also checked. **These checks are not full feasibility validation.** Attitude
transitions, per-orbit resource budgets, sensor geometry, battery dynamics and
downlink are not independently verified. The UI therefore reports full
feasibility as N/A, never PASS. Unrecorded seeds, budgets and causal exclusion
reasons remain unrecorded; no energy/storage trace is fabricated.

The EOS figures are simulation benchmarks, not operational telemetry. The source
model uses Keplerian propagation. BD's denominator is twice the demand duration
of all tasks, including unassigned ones; TM penalizes an unassigned task by the
entire horizon. Single-satellite BD is N/A locally. Descriptive metrics do not
change the local lexicographic optimization objective. Reference plans with
different objectives are shown without an overall ranking.

To regenerate the archive, download the fixed revision's source files and tree
metadata using the local names documented in `scripts/import_eos_reference.py`,
then run:

```bash
python scripts/import_eos_reference.py /path/to/downloaded-source
```

The export includes source URLs, hashes and verification scope. The pinned source
tree contains no license declaration; the reference snapshot is kept distinct
from OrbitOps-authored code and should be reviewed before external redistribution.
Pushing this archive to `main` makes the reference snapshot public in the
repository and includes it in the automatic GitHub Pages deployment. Source
attribution and hashes document provenance, not a redistribution license.

The retained Python API independently enforces the ten-task brute-force and
sixteen-task branch-and-bound implementation limits. Those controls are not
exposed in the EOS-Bench demo.

## JSON API

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Process health and loaded scenario count. |
| `GET` | `/api/scenarios` | Scenario names, identifiers, horizons, and task counts. |
| `GET` | `/api/scenarios/{id}` | Full validated scenario contract. |
| `GET` | `/api/solvers` | Stable solver names, categories, stochastic flags, and exact limits. |
| `POST` | `/api/solve` | Run, simulate, score, and return one schedule. |
| `GET` | `/api/reference` | Available read-only reference scenario and plans. |
| `GET` | `/api/reference/data` | Pinned display archive, or null if unavailable. |
| `GET` | `/api/reference/runs/{id}` | Reference plan with explicitly limited check scope. |

Example solve request:

```json
{
  "scenario_id": "demo-001",
  "solver_name": "genetic",
  "seed": 42,
  "evaluation_budget": 250
}
```

The request contract rejects unknown fields, evaluation budgets outside
`1..5000`, non-positive time limits, and request bodies larger than 64 KiB.
Scenario files are discovered only at startup and must pass the authoritative
Pydantic contract; other JSON artifacts are ignored.

## Cesium integration

The lab loads the official CesiumJS 1.143 browser build from `cesium.com` and
renders NASA's Blue Marble shaded-relief layer through the public
GIBS Web Mercator service (`GoogleMapsCompatible_Level8`). Cesium's bundled
Natural Earth II tiles remain underneath as a token-free raster fallback.
Scenario coordinates stay in the browser and are
not uploaded to Cesium ion or NASA. If both remote imagery paths or the 3D engine
are unavailable, a selectable two-dimensional coordinate map preserves target
and selection context while playback and evidence charts continue to work. Its equirectangular target positions use the supplied WGS84 coordinates;
coastlines are explicitly schematic. The 3D engine loads asynchronously so an
unavailable engine does not block reference replay.

Cesium's official browser build uses workers, WebAssembly, and runtime code
compilation. The Content Security Policy therefore permits `unsafe-eval` only
inside a script policy whose executable sources remain restricted to the local
application and `https://cesium.com`. Workers, images, fonts, and connections
are similarly source-restricted; imagery and connection policies additionally
allow only NASA GIBS. Deployments with stricter requirements can vendor and
bundle the ESM build and raster tiles instead.

## Architecture and safety boundary

`LabApplication` owns scenario discovery and fixed-route dispatch without any
network dependency. A small standard-library threaded HTTP adapter adds response
framing and security headers. Static assets are served only through explicitly
declared local routes plus the page route; URL paths are never translated into
filesystem paths.

The server is stateless and has no uploads, accounts, cookies, or persistence.
Scheduling and validation are local-only. Responses use `no-store`, `nosniff`,
a source-restricted Content Security Policy, and a no-referrer policy. The sole
browser-network dependencies are the official CesiumJS and NASA GIBS origins
described above. These controls make the lab appropriate for local
experimentation; they do not turn it into an authenticated production service.

## Verification

Automated tests cover catalog filtering, solver capability metadata, baseline
and stochastic solve responses, exact-solver limits, invalid inputs, fixed
static routes, accessible interface structure, Cesium/Gantt/training-view
contracts, the GitHub Pages reproducibility build, safe DOM construction,
security headers, CLI wiring, and server cleanup. JavaScript is syntax-checked
separately, and wheel inspection confirms that the HTML, stylesheet, application
script, deployment configuration, Cesium configuration, and social preview
asset ship with the Python package.

Optional browser regression checks run against the actual reference archive
while blocking remote geometry dependencies. They verify eight viewport sizes,
all 500 reachable targets, all 20 satellite lanes, linked selection, keyboard
tabs, layer-menu dismissal, JSON export, single-scenario enforcement, missing
archive errors, plan switching and API-free static loading:

```bash
python -m pip install -e '.[dev]' playwright
ORBITOPS_BROWSER_TESTS=1 pytest tests/browser
```

Chrome is used by default. Set `ORBITOPS_BROWSER_EXECUTABLE` to test another
Chromium executable. These checks are skipped in the normal Python suite.

Real WebGL checks run against the official Cesium engine rather than a mocked
renderer. They verify initial-epoch tracks, exact source-sample positions,
canvas picking, focus/follow, end-of-horizon bounds, responsive framing, map
expansion and retaining source geometry when changing reference plans. NASA
imagery is deliberately blocked to check the Natural Earth fallback. The
official Cesium CDN must be reachable:

```bash
ORBITOPS_GLOBE_TESTS=1 pytest tests/browser/test_globe.py
```
