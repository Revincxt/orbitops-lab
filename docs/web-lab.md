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
and output inspection visible together. The page, map and inspector do not
scroll. Task List and Timeline scroll internally; all 500 source tasks
remain reachable, with a status filter on the Task List heading and no search
field. Timeline shows all 20 satellite lanes without pagination.
Desktop side panels are fixed; there are no collapse controls. On narrow screens
a compact Map / Tasks / Results navigation switches between full-width views.

The top-right algorithm selector, beside Repository, switches
between the four original plans immediately. There is no Load Plan button,
pending-change prompt, visible selector label or separate configuration card. The left column contains
Task List above the algorithm comparison radar. The centre prioritizes the orbit view, with a compact
analysis dock below it. The right panel shows target details and satellite
workload, without the former four primary metric cards. Projection controls live
in the map toolbar. Layer, fit, expand, Overview and Follow share one compact
control rail with matching heights, icon sizes and interaction states;
layer switches are grouped in a dismissible menu. Plan summary has no download
button, and the toolbar has no Past/Future legend. Selection / Metrics share a
compact segmented control at the right of the Plan summary heading, rather than
occupying a separate row.

The brand shows only OrbitOps, without a Mission Control subtitle. The live UTC
replay clock sits below its wordmark without increasing the header height;
clicking it opens the UTC jump picker under the masthead. The replay bar has no
duplicate timestamp, and the clock remains visible in Map / Tasks / Results.
Task List
has no count badge. Satellite workload places `s` after every source duration,
rather than in its section header.

Satellites use an original, locally bundled glTF 3D illustration with a metal
bus, thermal blanket, blue solar wings, optics and communications hardware.
The model is shared by all 20 satellites and retains natural materials rather
than being tinted entirely with orbit colours. Active selection uses a fine
orbit-coloured outline. The nominal velocity-based orientation and minimum
screen size are display assumptions, not real spacecraft attitude, scale or
individual satellite replicas. All source positions and the existing FOV
geometry remain unchanged. The unfolded maps retain models, and the offline
schematic uses a shaded vector counterpart. Clicking, double-click focus,
follow, playback and plan switching remain available. Asset provenance and
reproducible build instructions are in `static/models/README.md`.

The visual treatment refines the orbital command-room reference with layered
graphite surfaces, soft blue ambient light, fine edge highlights and 8px panel
corners. Header bands and alternating rows stay subdued; cyan is concentrated
on active selections and source chart marks rather than filling every panel.
Small status chips, a prominent selected-task ID and stronger numeric hierarchy
separate essential information from secondary labels. This treatment is scoped
to Task List, Comparison, Plan summary, Satellite workload and Timeline; it does
not alter the globe's appearance, control styling or allocated space. The map brackets and header rule
are decorative only and never capture pointer events. No decorative charts,
invented telemetry or aggregate rankings are introduced. Inter typography,
tabular numeric alignment, restrained status colours and keyboard focus remain
consistent across the panels. Desktop keeps the existing column widths and map
height. On phones the radar and algorithm legend sit side by side; tablet Tasks
views place the scrolling Task List on the left and Comparison on the right.

NASA and Natural Earth imagery share a darker, reduced-saturation presentation
with a subtle blue atmospheric rim. This affects appearance only, not geometry,
source coordinates, orbital samples, tasks or scores. Native starfield, map
projections, double-click focus, follow and extended playback remain available.
A faint, transparent geographic tile grid is generated locally with Cesium's
[GridImageryProvider](https://cesium.com/learn/cesiumjs/ref-doc/GridImageryProvider.html).
It is a map guide, not a sensor footprint, observation window or orbit. It adds
no external requests or mission entities and works in all three projections.

Only the 3D view adds solar illumination with a natural day/night transition.
There is no yellow boundary line, outline or extra terminator geometry. The
native Sun uses Cesium's
[Simon 1994 ephemeris](https://cesium.com/learn/cesiumjs/ref-doc/Simon1994PlanetaryPositions.html)
and the same Earth-fixed transformation as the scene's SunLight, evaluated at
the replay UTC rather than the wall clock. The boundary follows WGS84 surface
normals perpendicular to that direction, not an equatorial circle or a camera
shadow. It represents the Sun-centre geometric horizon, not atmospheric
refraction, civil/nautical/astronomical twilight or satellite eclipse predictions.
Source tasks, access windows, orbit samples and scores remain unchanged.

The Sun stays at its physical ephemeris distance; it is not moved near Earth
to fit the viewport. Looking towards an unobscured Sun displays the native disc
and restrained glow. It can naturally be outside the camera's view or occulted
by Earth; there is no extra solar direction marker or indicator.
`Sun & day/night` in Layers toggles the 3D
environment. The switch is unavailable in 2D, 2.5D and the offline schematic;
those maps retain their previous unshaded appearance without a boundary or
solar marker. Returning to 3D restores the stored setting and replay time.

Cesium updates the solar position and lighting from the shared replay clock,
including times before and after the original planning horizon. The environment
adds no mission entities, extra geometry or render listeners. Plan reloads reuse
the existing scene and Sun. The native ICRF transform can load
Cesium's existing IAU XYS assets; no new service, custom texture or dependency
is introduced. Day/night lighting remains enabled at satellite-follow altitudes
instead of fading to a fully lit Earth when zooming in.

Changing the top selector or activating a radar legend item loads the original
source plan automatically. Reloading resets playback and camera tracking but
preserves the selected projection and mobile workspace view; it never calls a
local solver. Legacy
`?mode=local` URLs no longer expose other scenarios.

The analysis dock contains only the Timeline: source observation intervals and
the selected task's visibility windows across all 20 satellite lanes. The
Visibility/Observation legend sits directly left of the satellite filter at
the right of the Timeline heading, without a separate Observation · UTC title.
The plot scrolls internally, with a sticky UTC scale and replay scrubber
and no previous/next page controls. Playback, resize and plan changes preserve
its scroll position; selecting a task or satellite reveals the corresponding
lane without scrolling the page or map. The inspector retains its observation
time field.

Comparison uses a five-axis SVG radar for all four source algorithms. Each axis
uses a 0–1 display scale with outward meaning better: TP / highest source TP,
original TCR, 1 − TM, fastest source RT / RT, and original BD. This preserves
natural completion and balance fractions rather than mapping the worst plan to
zero completion. Runtime is source solver runtime, not viewer performance.
Colours and line patterns distinguish the plans; the active series is drawn
last and has a subtle fill. The footer shows its raw TP/TCR/TM/RT/BD values;
axis and series tooltips preserve metric scales, exact source objectives and
limited reference-consistency scope. There is no separate information button
or explanatory popover. No overall score or full-feasibility claim is inferred.

The instrument panels share their own corner radii, header surfaces, inset
control rails and active-state gradients, independent of the unchanged map
shell. Restrained shadows separate the graphite instrument surfaces;
readable Inter labels and tabular figures retain the fixed-height engineering
layout. Charts use local SVG gradients and lightweight
depth filters, not a new chart library or image assets. The radar has a decorative
plinth, a faint decorative reference ring, transparent selected-plan surface
and vertex halos; metric polygons stay untransformed on their original axes.
Workload bars have slim recessed tracks, restrained horizontal shading, separated
numeric/unit typography and an explicit selected-row marker, with unchanged value-to-length ratios, including
zero-length bars for zero workload. Timeline bars share the same material and
state colours, with a coordinated selected-satellite lane. These presentation
effects do not alter the archive, source times, plans or evaluation metrics.
Algorithm changes use a short opacity transition only; there is no continuous
decorative animation, perspective distortion or minimum fake bar width. Reduced
motion disables the transition, and keyboard focus remains visible.

Task rows retain their DOM nodes across selection, resize and playback so the
scroll position and keyboard focus do not jump. A task selected elsewhere is
revealed by scrolling only the list, never the page or map.

The inspector has only Selection and Metrics tabs. Audit, Data and Run record
views have been removed. The top scenario-summary strip and the live
completed/observing text are also absent; playback retains its timestamp,
scrubber, speed and play/reset controls. Source attribution, revision, hashes and
verification scope remain in the reference archive and payload. Removing their panels
does not change the archive, recomputed metrics or limited validation scope.
Satellite workload bars support mouse and keyboard selection.
The panel contains only the per-satellite bars, without active-satellite or
total-observation-time footer readouts. Source workload totals remain unchanged.

Previous/next 12-hour window, play/pause, reset, playback direction and speed
form one centered control group below the map. A fine divider separates the speed
selector from the transport buttons; active playback and reverse direction have
distinct states. The replay bar is now 46px
high, returning 24px to the map. UTC stays under the brand rather than in this group.
The scrubber lives under Timeline's UTC tick labels and shares the exact plot
coordinates, including the native thumb's half-width. The scale and scrubber stay
fixed while satellite lanes scroll; refreshes keep the input node and keyboard
focus intact. Tick labels, task intervals and playback position share the same
12-hour window, including orbit-only periods before and after the scenario.
Source tasks are clipped to that window, not duplicated into extended periods.

Every satellite has an illustrative, geocentric circular field of view with a
30° **full** cone angle (15° half-angle). Its tip follows the exact displayed
satellite position, including estimated orbit extensions; its axis points at
Earth's centre. Cone surfaces use 3.5% opacity with subtle satellite-coloured
edges. Earth intersections are computed against the WGS84 ellipsoid, not by
guessing a flat ground-disc radius. A slightly buried primitive cap avoids a
floating base, and the georeferenced surface boundary is displayed separately.
These are display assumptions, not source sensor attitudes, verified coverage,
terrain visibility, access windows or task executions; the reference archive,
schedules and scores remain unchanged.

The existing Layers menu toggles `Sensor FOV · 30°`. 3D shows the translucent
volume and ground boundary. The unfolded 2D/2.5D views and offline schematic
show the ground boundary only, rather than a distorted 3D cone. This follows
Cesium's [3D-only primitive model-matrix support](https://cesium.com/learn/cesiumjs/ref-doc/Primitive.html#modelMatrix).
Cone geometry is built once and moved with model transforms, not rebuilt on
each playback tick. Cone primitives are non-pickable; ground-boundary hits pass
through to mission objects. Plan reloads dispose of the previous FOV primitives.
Ground-boundary geometry is updated only when the replay clock changes; camera
movement and paused frames reuse the same hierarchy instead of rebuilding it.

The interface bundles the unmodified Inter variable font and its SIL Open Font
License locally; no font CDN request is needed in either the API or Pages build.
Labels use proportional type, numeric values use tabular figures, and only the
UTC playback timestamp uses monospace. CSS density tokens are shared by the
catalog and timeline rows, workload capacity and comparison layout, so larger readable type
does not crop rows or alter any source data. Satellite names are human-readable
throughout the interface, with full source IDs retained in titles and the payload.

Selecting a target in the catalog, Gantt, or map updates the same inspector and
selection highlight. The inspector exposes coordinates, priority, duration,
satellite assignment, observation interval, data volume and source orbit number.
The layers menu toggles targets, orbit paths, observation links, target IDs and
satellite IDs. Escape, outside clicks and focus leaving the menu dismiss it.
The browser no longer offers a JSON download action. Scenario, plan, provenance
and verification scope remain unchanged in the reference payload. Load failures
remain visible in the status bar. Targets on the far side of Earth are depth-occluded.

The shared playback clock supports pause, reset, scrubbing, selectable speed and
forward/reverse playback. It is not bounded by the task-planning horizon. Previous
and next buttons shift the scrubber's 12-hour viewing window; clicking the UTC
timestamp opens a direct date/time jump. Dates use UTC regardless of the browser's
local time zone. Crossing either source boundary does not stop, loop or freeze the
satellites. Date input is limited to calendar years 0001–9999, not to the source
scenario's 12-hour horizon.

Inside the original closed sample interval, the native globe retains the exact
source Cartesian linear interpolation and the fallback retains its geodetic
interpolation. Outside it, a browser-only elliptic two-body model uses the source
six orbital elements and their UTC epoch. Its orientation is calibrated against
two nearby source samples at each boundary, with WGS84 conversion and constant
Earth rotation, to avoid a position discontinuity. This is not a new Orekit/IERS
propagation, SGP4 calculation or operational ephemeris: J2, drag, manoeuvres,
changing Earth orientation and other perturbations are not modelled. Long-range
prediction accuracy is not certified. An `Estimated orbit` badge distinguishes
these times from source replay.

Observation activity is disabled outside the original half-open task interval.
There are no new observation links, windows, resource events, assignments or
evaluation metrics. Assigned tasks remain Planned before the scenario and
Completed after it. The timeline retains the original schedule and hides its
playhead outside the sample interval. The reference payload remains unchanged;
generated extension samples are display-only.

Catalog, map, timeline cursor and task details share half-open interval
semantics: observing at start, completed at end. Planned completion metrics stay
separate from the playback-completed count. Status and satellite filters,
together with internal catalog and timeline scrolling, keep large scenes
reachable without scrolling the page or map.

The orbit display uses a one-period window centred on the current time: half a
period of solid past trajectory and half a period of dashed future trajectory.
Either side can include the estimated extension outside the source interval.
The native position property combines source samples with before/after model
callbacks; the 2D fallback computes only its current one-period track, without
accumulating an unbounded sample cache. Tracks are visible even when paused at
the initial epoch. The 2D fallback splits lines at the date line with
interpolated seam endpoints, rather than connecting them across the map.

Satellites have screen-space engineering symbols and colour-matched names,
tracks and selection halos. Symbols do not represent physical scale or attitude.
Click a satellite/track to select it; double-click to focus the camera on it.
There is no separate Focus button or Past/Future key. Overview/Follow are
integrated to the right of the map toolbar's layer, fit and expand buttons in
one shared control rail, with icon-only camera controls in compact panes.
There is no extra row below the map; solid/dashed orbit geometry is unchanged.
Satellite details are closed by default: selecting a satellite opens a small
translucent popup beside its symbol, showing display-interpolated WGS84 ellipsoid
altitude and the source orbital period. It follows the selected symbol during
playback and camera changes, stays within the map bounds, and hides while the
satellite is offscreen or occluded. Close, Escape, clicking empty map space or
loading a plan dismisses it, without changing the replay clock or map dimensions.
Overview and Follow are explicit camera modes; selecting a task links the
associated satellite without automatically flying the camera. Overview and the fit button release
tracking. Target IDs are distance-limited to avoid labelling all 500 targets at
global scale; the selected target stays labelled. Depth testing stays enabled
for targets, satellite symbols and labels, so the far side is occluded.

The map can temporarily expand within the centre workspace while the two side
panels remain available; restore returns the analysis dock. Camera framing
accounts for both viewport axes and all retained orbital altitudes, and refits
when an overview viewport is resized. A fine-tick north-reset compass projects
geographic north onto the rendered camera's screen axes, accounting for tilt,
roll and tracked transforms rather than using heading alone. It synchronizes
after each rendered frame, including small turns below the camera event threshold
while replay is paused, without an extra render loop. Unfolded views use map north;
morphs and degenerate north projections retain the last valid bearing. There is
no numeric readout, and its N label stays upright. Clicking it preserves position
and pitch while releasing tracking and resetting heading and roll.
The map has no attribution information icon or toggle. Only that control is
hidden; native credit content, provider credit metadata and the Cesium logo are
retained. Small/short
map panes compact the toolbar and separate the task legend from the compass.

The map toolbar's projection controls switch between the native Cesium 3D
globe, tilted 2.5D unfolded map (Columbus View), and 2D geographic map. All views
share the same source positions, task selection, layers and replay clock; a
projection change does not restart or pause playback. 2.5D retains orbital
height above the projected map; 2D flattens that height spatially while the
source altitude remains available in the satellite readout. Switching releases
camera tracking and fits an overview. Follow works in every view;
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
downlink are not independently verified. The reference payload therefore reports
full feasibility as null, never PASS; comparison rows explicitly report limited
scope. Unrecorded seeds, budgets and causal exclusion
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

The archive includes source URLs, hashes and verification scope. The pinned source
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
The 3D globe uses Cesium's native star-map skybox behind the Earth and orbital
paths. It fades out when switching to 2D or Columbus View (2.5D), keeping unfolded
maps clean. It uses the same official Cesium asset origin, without a new API key
or additional star catalog; stars are visual context, not observation evidence.
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
scripts, orbit extension model, deployment configuration, Cesium configuration,
local font and its license, and social preview asset ship with the Python package.

Pure JavaScript tests check all 20 orbits against the unchanged source samples,
boundary continuity, WGS84 conversion, finite multi-year propagation and bounded
track sampling. Withheld source segments provide forward/backward prediction
regression checks; these do not certify long-range ephemeris accuracy.

Optional browser regression checks run against the actual reference archive
while blocking remote geometry dependencies. They verify eight viewport sizes,
all 500 reachable targets, all 20 satellite lanes, linked selection, keyboard
tabs, layer-menu dismissal, removed download/legend controls, unified map actions,
single-scenario enforcement, missing
archive errors, plan switching and API-free static loading. Playback checks cover
both horizon crossings, reverse playback, UTC jumps, source immutability and the
absence of out-of-horizon task activity:

```bash
python -m pip install -e '.[dev]' playwright
ORBITOPS_BROWSER_TESTS=1 pytest tests/browser
```

Chrome is used by default. Set `ORBITOPS_BROWSER_EXECUTABLE` to test another
Chromium executable. These checks are skipped in the normal Python suite.

Real WebGL checks run against the official Cesium engine rather than a mocked
renderer. They verify initial-epoch tracks, exact source-sample positions,
canvas picking, double-click focus, follow, centred one-period tracks, responsive
framing, map expansion and retaining source geometry when changing reference
plans. They also check extended positions, paths and follow in all three native
projections, plus the built-in starfield. NASA
imagery is deliberately blocked to check the Natural Earth fallback. The
official Cesium CDN must be reachable. First requests use Chrome's network path
and system proxy; completed official responses are cached byte-for-byte across
tests, avoiding a separate API client's proxy configuration:

```bash
ORBITOPS_GLOBE_TESTS=1 pytest tests/browser/test_globe.py
```
