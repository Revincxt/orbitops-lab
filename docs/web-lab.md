# Interactive Web Lab

The Web Lab turns the existing OrbitOps solvers and shared validator into a
local interactive tool. It is intentionally a thin application layer: the web
interface does not contain a second scheduler, simulator, or scoring model.
Every displayed result comes from the same Python domain core used by the CLI,
benchmarks, and tests.

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

The configuration surface selects a committed Scenario JSON document, one of
the eleven built-in solver modes, a deterministic seed, and an evaluation budget. The
server solves the selected scenario synchronously, revalidates the schedule with
the shared simulator, and returns one result payload for all views.

The default view runs the committed demonstration scenario with the seeded
Q-learning solver and a 250-episode budget. This makes the complete learning
and validation story visible on first load. The interface renders:

- **Primary metrics:** total value, completed observations, and total slew time.
- **Method comparison:** all precomputed methods for the selected scenario with
  objective, completion, feasibility, runtime, evaluation count, seed, budget,
  and stopping reason.
- **Constraint audit:** scheduled/unscheduled task accounting, resource margins,
  validation issues, search effort, and exact-search proof status.
- **3D mission geometry:** all scenario targets on a WGS84 globe, selected-target
  highlighting, scheduled observation sequence, an elevated satellite marker,
  and an explicitly notional orbit-context track.
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

The globe is deliberately labeled as mission context rather than orbit
propagation. v0.1 scenarios contain target coordinates and visibility windows,
but no orbital elements, epoch, or propagator state. The interface therefore
does not claim that the displayed context track predicts spacecraft position.

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
are unavailable, a static mission-geometry fallback preserves target and
selection context while the scheduling API and evidence charts continue to work.

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
