"""Pure application layer for the local OrbitOps Web Lab."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

from pydantic import Field, ValidationError

from orbitops.domain.models import DomainModel, Scenario, SolveResult
from orbitops.solvers import advanced_solvers, available_solvers, baseline_solvers, exact_solvers
from orbitops.solvers.branch_and_bound import BranchAndBoundSolver
from orbitops.solvers.brute_force import BruteForceSolver
from orbitops.solvers.registry import get_solver
from orbitops.web.evaluation import evaluation_metrics
from orbitops.web.reference import ReferenceArchive

STATIC_DIR = Path(__file__).with_name("static")
MAX_REQUEST_BYTES = 64 * 1024


class SolveRequest(DomainModel):
    scenario_id: str = Field(min_length=1)
    solver_name: str = Field(min_length=1)
    seed: int = 0
    evaluation_budget: int = Field(default=250, ge=1, le=5000)
    time_limit_s: float | None = Field(default=None, gt=0, le=300)


@dataclass(frozen=True, slots=True)
class WebResponse:
    status: int
    content_type: str
    body: bytes

    @classmethod
    def json(cls, status: int, payload: Any) -> WebResponse:
        return cls(
            status=status,
            content_type="application/json; charset=utf-8",
            body=(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(),
        )


class LabApplication:
    """Route API and static requests without depending on an HTTP framework."""

    def __init__(self, scenario_dir: str | Path, static_dir: str | Path = STATIC_DIR) -> None:
        self.scenario_dir = Path(scenario_dir)
        self.static_dir = Path(static_dir)
        self._scenarios = self._load_scenarios()
        self.reference = ReferenceArchive(
            self.scenario_dir.parent / "data" / "eos-bench" / "reference.json"
        )

    def _load_scenarios(self) -> dict[str, Scenario]:
        if not self.scenario_dir.is_dir():
            raise ValueError(f"scenario directory does not exist: {self.scenario_dir}")
        scenarios: dict[str, Scenario] = {}
        for path in sorted(self.scenario_dir.rglob("*.json")):
            try:
                scenario = Scenario.from_json(path)
            except (OSError, ValidationError):
                continue
            if scenario.scenario_id in scenarios:
                raise ValueError(f"duplicate scenario_id {scenario.scenario_id!r}")
            scenarios[scenario.scenario_id] = scenario
        if not scenarios:
            raise ValueError(f"no valid scenarios found in {self.scenario_dir}")
        return scenarios

    def _scenario_summaries(self) -> list[dict[str, Any]]:
        return [
            {
                "scenario_id": scenario.scenario_id,
                "name": scenario.name,
                "task_count": len(scenario.tasks),
                "horizon_start_s": scenario.horizon_start_s,
                "horizon_end_s": scenario.horizon_end_s,
                "research_question": scenario.metadata.get("research_question"),
                "geometry_note": scenario.metadata.get("geometry_note"),
            }
            for scenario in self._scenarios.values()
        ]

    @staticmethod
    def _solver_summaries() -> list[dict[str, Any]]:
        categories = {
            **dict.fromkeys(baseline_solvers(), "baseline"),
            **dict.fromkeys(exact_solvers(), "exact"),
            **dict.fromkeys(advanced_solvers(), "advanced"),
        }
        limits = {
            BruteForceSolver.name: BruteForceSolver.max_tasks,
            BranchAndBoundSolver.name: BranchAndBoundSolver.max_tasks,
        }
        return [
            {
                "solver_name": name,
                "category": categories[name],
                "stochastic": name in {"random-feasible", *advanced_solvers()},
                "max_tasks": limits.get(name),
            }
            for name in available_solvers()
        ]

    @staticmethod
    def _result_payload(scenario: Scenario, result: SolveResult) -> dict[str, Any]:
        payload = result.model_dump(mode="json", exclude_none=True)
        validation = payload["validation"]
        validation["is_feasible"] = result.validation.is_feasible
        raw_convergence = result.schedule.metadata.get("convergence")
        if isinstance(raw_convergence, list):
            convergence = raw_convergence
        else:
            evaluations = result.schedule.metadata.get("evaluations", 0)
            convergence = [
                {
                    "evaluation": evaluations if isinstance(evaluations, int) else 0,
                    "total_value": result.metrics.total_value,
                    "completed_tasks": result.metrics.completed_tasks,
                    "total_slew_time_s": result.metrics.total_slew_time_s,
                }
            ]
        return {
            "scenario": scenario.model_dump(mode="json"),
            "result": payload,
            "convergence": convergence,
            "evaluation": evaluation_metrics(scenario, result),
        }

    def _solve(self, body: bytes) -> WebResponse:
        if len(body) > MAX_REQUEST_BYTES:
            return WebResponse.json(413, {"error": "request body exceeds 64 KiB"})
        try:
            request = SolveRequest.model_validate_json(body)
            scenario = self._scenarios.get(request.scenario_id)
            if scenario is None:
                raise ValueError(f"unknown scenario {request.scenario_id!r}")
            solver = get_solver(
                request.solver_name,
                seed=request.seed,
                evaluation_budget=request.evaluation_budget,
                time_limit_s=request.time_limit_s,
            )
            result = solver.solve(scenario)
        except ValidationError as exc:
            return WebResponse.json(
                422,
                {
                    "error": "invalid solve request",
                    "details": json.loads(exc.json(include_url=False)),
                },
            )
        except ValueError as exc:
            return WebResponse.json(400, {"error": str(exc)})
        except RuntimeError as exc:
            return WebResponse.json(500, {"error": str(exc)})
        return WebResponse.json(200, self._result_payload(scenario, result))

    def _static(self, filename: str, content_type: str) -> WebResponse:
        path = self.static_dir / filename
        try:
            body = path.read_bytes()
        except OSError:
            return WebResponse.json(404, {"error": "static asset not found"})
        return WebResponse(status=200, content_type=content_type, body=body)

    def dispatch(
        self,
        method: Literal["GET", "POST"],
        path: str,
        body: bytes = b"",
    ) -> WebResponse:
        route = path.split("?", 1)[0]
        if method == "GET" and route == "/api/reference":
            return WebResponse.json(200, self.reference.catalog())
        if method == "GET" and route == "/api/reference/data":
            return WebResponse.json(200, self.reference.export())
        if method == "GET" and route.startswith("/api/reference/runs/"):
            try:
                return WebResponse.json(200, self.reference.payload(unquote(route.split("/")[-1])))
            except ValueError as exc:
                return WebResponse.json(404, {"error": str(exc)})
        if method == "GET" and route == "/api/health":
            return WebResponse.json(
                200,
                {"status": "ok", "scenario_count": len(self._scenarios)},
            )
        if method == "GET" and route == "/api/scenarios":
            return WebResponse.json(200, {"scenarios": self._scenario_summaries()})
        if method == "GET" and route.startswith("/api/scenarios/"):
            scenario_id = unquote(route.removeprefix("/api/scenarios/"))
            scenario = self._scenarios.get(scenario_id)
            if scenario is None:
                return WebResponse.json(404, {"error": "scenario not found"})
            return WebResponse.json(200, scenario.model_dump(mode="json"))
        if method == "GET" and route == "/api/solvers":
            return WebResponse.json(200, {"solvers": self._solver_summaries()})
        if method == "POST" and route == "/api/solve":
            return self._solve(body)
        static_routes = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.css": ("app.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/replay.js": ("replay.js", "text/javascript; charset=utf-8"),
            "/mission.js": ("mission.js", "text/javascript; charset=utf-8"),
            "/favicon.svg": ("favicon.svg", "image/svg+xml"),
            "/cesium-config.js": ("cesium-config.js", "text/javascript; charset=utf-8"),
            "/deployment-config.js": (
                "deployment-config.js",
                "text/javascript; charset=utf-8",
            ),
            "/orbitops-social-card.jpg": ("orbitops-social-card.jpg", "image/jpeg"),
        }
        if method == "GET" and route in static_routes:
            return self._static(*static_routes[route])
        return WebResponse.json(404, {"error": "route not found"})
