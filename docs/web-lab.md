# Interactive Web Lab

The Web Lab turns the existing OrbitOps solvers and shared validator into a
local interactive tool. It is intentionally a thin application layer: the web
interface does not contain a second scheduler, simulator, or scoring model.
Local solver results come from the same Python domain core used by the CLI,
benchmarks, and tests. A separate, explicitly read-only EOS-Bench reference mode
replays imported multi-satellite plans without passing them off as local solves.

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
Python API, so the deployment workflow builds a static reproducibility artifact
instead of pretending that the browser is solving schedules. It includes the
committed 3-task regression cases and deterministic 6, 10, 18, and 30-task
showcases. Seed 42 is fixed, while size-aware search budgets keep the artifact
bounded. Every result reports its actual budget and build provenance; expensive
or unsupported combinations are listed as explicit omissions. Scenario and
solver controls select among recorded results, so seed and budget inputs remain
read-only in hosted mode.

Every push to `main` runs `scripts/build_pages.py`, packages the framework-free
interface and its precomputed result dataset, and deploys the artifact through
the repository's GitHub Pages workflow. Local API execution remains the correct
path for arbitrary seeds, budgets, or additional scenarios.

## Interaction model

The fixed-viewport engineering workspace keeps configuration, mission geometry,
and output inspection visible together. The page and its panels do not scroll:
target catalogs, timeline rows, solver comparisons, exclusions, and validator
issues use height-aware pagination. On narrow screens the side panels become
exclusive drawers, opened from the header and dismissed with Escape.

The configuration surface selects a committed Scenario JSON document, one of
the eleven built-in solver modes, a deterministic seed, and an evaluation budget. The
server solves the selected scenario synchronously, revalidates the schedule with
the shared simulator, and returns one result payload for all views.

When the reference archive is present, the default view opens EOS-Bench's
20-satellite, 500-task, 12-hour scenario with its balanced SA plan. Use
`?mode=local` to open the ten-target resource-frontier showcase with Q-learning,
or choose a local scenario in the existing scenario selector. Timeline,
comparison, constraint audit, and diagnostics share
one tabbed analysis dock. Primary metrics and resource state stay in the output
inspector. The interface renders:

- **Primary metrics:** plan priority yield TP, plan completion TCR, normalized
  start-delay TM (lower is better), and the explicitly scoped validation status.
  Additional metrics report balance BD, solve runtime RT and available slew time.
- **Method comparison:** all precomputed methods for the selected scenario with
  objective, completion, feasibility, runtime, evaluation count, seed, budget,
  and stopping reason.
- **Constraint audit:** scheduled/unscheduled task accounting, resource margins,
  validation issues, search effort, and exact-search proof status.
- **3D mission geometry:** WGS84 targets and selection highlighting. Reference
  mode uses retained source Orekit position samples, moving satellites,
  one-period trailing paths and observation links only during actual task
  intervals. Local synthetic scenarios have no orbit data: only target
  coordinates and an explicitly labelled plan sequence are shown. Invented
  satellite positions and arbitrary coverage circles are not displayed.
- **Mission Gantt:** every target's visibility windows, validated observation
  interval, and the slew immediately preceding a selected observation.
- **Resource trace:** energy remaining and storage used, normalized against the
  satellite capacities after every simulated task.
- **Training curves:** realized exploratory episode-schedule objective, epsilon,
  and normalized mean absolute temporal-difference error for Q-learning runs.
  This diagnostic is not labeled as pure-policy performance; deterministic
  checkpoint replay quality is recorded separately in run metadata.
- **Search convergence:** incumbent objective value by unique evaluation for
  stochastic-search solvers; deterministic solvers receive a terminal point.

Selecting a target in the catalog, Gantt, or map updates the same inspector and
selection highlight. The inspector exposes target coordinates, priority,
duration, observation interval, and resource costs; a second tab contains run
provenance. Globe toolbar controls toggle targets and tracks or fit the mission
to the available viewport. Targets on the far side of Earth are depth-occluded.

Editing configuration marks the visible result as pending until a new run is
evaluated. Ctrl+Enter (Cmd+Enter on macOS) runs the form; controls are disabled
while a solve is in progress and duplicate submissions are ignored. Comparison
rows can reopen previously evaluated results. Export downloads the complete
currently inspected run as JSON, including scenario, schedule, validation,
diagnostics, and available provenance. An unsuccessful request keeps the last
evaluated result available and reports its error in the status bar.

The shared playback clock supports pause, reset, scrubbing and selectable speed.
Reference times have an explicit UTC epoch; local scenarios retain relative
seconds. Catalog, map, timeline cursor and task details share half-open interval
semantics: observing at start, completed at end. Planned completion metrics stay
separate from the playback-completed count. Task search, status and satellite
filters keep large scenes reachable without scrollbars.

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

Disabled exact-solver choices are informative guardrails. The local API enforces
the ten-task brute-force and sixteen-task branch-and-bound implementation limits.
The static build uses stricter eight- and twelve-task caps to bound deployment
time and records each skipped combination in its omission manifest.

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
renders NASA's Blue Marble shaded-relief and bathymetry layer through the public
GIBS Web Mercator service (`GoogleMapsCompatible_Level8`). Cesium's bundled
Natural Earth II tiles remain underneath as a token-free raster fallback.
Scenario coordinates stay in the browser and are
not uploaded to Cesium ion or NASA. If both remote imagery paths or the 3D engine
are unavailable, a selectable two-dimensional coordinate map preserves target
and selection context while the scheduling API and evidence charts continue to
work. Its equirectangular target positions use the supplied WGS84 coordinates;
coastlines are explicitly schematic. The 3D engine loads asynchronously so an
unavailable engine does not block scheduling.

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

Optional browser regression checks run the actual local API while blocking
remote geometry dependencies, verifying the coordinate-map fallback, eight
viewport sizes, complete 30-target pagination, linked selection, keyboard tabs,
layer toggles, JSON downloads, duplicate-submit protection, error recovery,
and recorded budgets and complete comparison pagination in Pages mode:

```bash
python -m pip install -e '.[dev]' playwright
ORBITOPS_BROWSER_TESTS=1 pytest tests/browser
```

Chrome is used by default. Set `ORBITOPS_BROWSER_EXECUTABLE` to test another
Chromium executable. These checks are skipped in the normal Python suite.
