# Interactive Web Lab

The Web Lab turns the existing OrbitOps solvers and shared validator into a
local interactive tool. It is intentionally a thin application layer: the web
interface does not contain a second scheduler, simulator, or scoring model.
Every displayed result comes from the same Python domain core used by the CLI,
benchmarks, and tests.

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

## Interaction model

The configuration surface selects a committed Scenario JSON document, one of
the nine built-in solvers, a deterministic seed, and an evaluation budget. The
server solves the selected scenario synchronously, revalidates the schedule with
the shared simulator, and returns one result payload for all views.

The interface renders:

- **Primary metrics:** total value, completed observations, and total slew time.
- **Observation schedule:** validated observation intervals plus the slew time
  immediately preceding each observation.
- **Resource trace:** energy remaining and storage used, normalized against the
  satellite capacities after every simulated task.
- **Convergence:** incumbent objective value by unique evaluation for stochastic
  search; deterministic solvers receive a single terminal point.

Disabled exact-solver choices are informative guardrails. The API independently
enforces the same ten-task brute-force and sixteen-task branch-and-bound limits,
so bypassing the interface cannot start an unsupported search.

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

## Architecture and safety boundary

`LabApplication` owns scenario discovery and fixed-route dispatch without any
network dependency. A small standard-library threaded HTTP adapter adds response
framing and security headers. Static assets are served only through the three
declared routes; URL paths are never translated into filesystem paths.

The server is stateless and has no uploads, accounts, cookies, remote calls, or
persistence. Responses use `no-store`, `nosniff`, a same-origin Content Security
Policy, and a no-referrer policy. These controls make the lab appropriate for
local experimentation; they do not turn it into an authenticated production
service.

## Verification

Automated tests cover catalog filtering, solver capability metadata, baseline
and stochastic solve responses, exact-solver limits, invalid inputs, fixed
static routes, accessible interface structure, safe DOM construction, security
headers, CLI wiring, and server cleanup. JavaScript is syntax-checked separately,
and wheel inspection confirms that all three static assets ship with the Python
package.
