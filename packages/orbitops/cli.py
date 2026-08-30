"""Command-line interface for inspecting OrbitOps artifacts."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError

from orbitops.benchmarking import (
    BenchmarkSpec,
    export_benchmark,
    run_benchmark,
    verify_benchmark_artifacts,
)
from orbitops.domain.models import DomainModel, Scenario, Schedule, SolveResult
from orbitops.learning import LinearQPolicy, rollout_policy
from orbitops.reporting import write_benchmark_html_from_json
from orbitops.simulation.validator import validate_schedule
from orbitops.solvers.registry import available_solvers, get_solver
from orbitops.web import serve_lab

app = typer.Typer(
    name="orbitops",
    help="Reproducible satellite scheduling experiments.",
    no_args_is_help=True,
)


class SchemaTarget(StrEnum):
    POLICY = "policy"
    SCENARIO = "scenario"
    SCHEDULE = "schedule"


@app.command("lab")
def launch_lab(
    scenario_dir: Annotated[
        Path,
        typer.Option(
            "--scenarios",
            file_okay=False,
            exists=True,
            readable=True,
            help="Directory containing Scenario JSON files.",
        ),
    ] = Path("scenarios"),
    host: Annotated[
        str,
        typer.Option(help="Interface for the local HTTP server."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(min=1, max=65535, help="Port for the local HTTP server."),
    ] = 8000,
) -> None:
    """Launch the interactive local scheduling laboratory."""

    typer.echo(f"OrbitOps Web Lab: http://{host}:{port}")
    try:
        serve_lab(scenario_dir, host=host, port=port)
    except KeyboardInterrupt:
        typer.echo("\nOrbitOps Web Lab stopped.")
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _result_payload(result: SolveResult) -> dict[str, Any]:
    payload = result.model_dump(mode="json", exclude_none=True)
    validation = payload.get("validation")
    if isinstance(validation, dict):
        validation["is_feasible"] = result.validation.is_feasible
    return payload


@app.command("train")
def train_q_learning_policy(
    scenario_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True),
    ],
    model_output: Annotated[
        Path,
        typer.Option(
            "--model-output",
            "-o",
            dir_okay=False,
            help="Write the trained linear Q policy to this JSON file.",
        ),
    ],
    seed: Annotated[int, typer.Option(help="Deterministic training seed.")] = 0,
    episodes: Annotated[
        int,
        typer.Option(min=1, max=1_000_000, help="Maximum training episodes."),
    ] = 500,
    time_limit_s: Annotated[
        float | None,
        typer.Option("--time-limit", min=0.000001, help="Optional soft time limit."),
    ] = None,
    result_output: Annotated[
        Path | None,
        typer.Option(
            "--result-output",
            dir_okay=False,
            help="Optionally write the validated training result JSON.",
        ),
    ] = None,
) -> None:
    """Train and export a scenario-bound linear Q-learning policy."""

    try:
        scenario = Scenario.from_json(scenario_path)
        result = get_solver(
            "q-learning",
            seed=seed,
            time_limit_s=time_limit_s,
            evaluation_budget=episodes,
        ).solve(scenario)
        raw_model = result.schedule.metadata.get("model")
        if not isinstance(raw_model, dict):
            raise RuntimeError("q-learning result did not contain a policy model")
        policy = LinearQPolicy.model_validate(raw_model)
        if policy.selected_checkpoint_episode is None:
            raise RuntimeError(
                "training ended before any policy checkpoint replay completed; "
                "increase the time limit before exporting a model"
            )
        policy_result = rollout_policy(
            scenario,
            policy,
            solver_name="q-policy-export-check",
        )
        policy.to_json(model_output)
        if result_output is not None:
            result_output.parent.mkdir(parents=True, exist_ok=True)
            result_output.write_text(
                json.dumps(_result_payload(result), indent=2) + "\n",
                encoding="utf-8",
            )
    except (OSError, ValidationError, ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        json.dumps(
            {
                "model_output": str(model_output),
                "scenario_id": scenario.scenario_id,
                "scenario_sha256": policy.scenario_sha256,
                "seed": policy.seed,
                "episodes_completed": policy.episodes_completed,
                "transitions": policy.transitions,
                "selected_checkpoint_episode": policy.selected_checkpoint_episode,
                "policy_checkpoints_evaluated": policy.evaluated_checkpoints,
                "policy_metrics": policy_result.metrics.model_dump(mode="json"),
                "hybrid_metrics": result.metrics.model_dump(mode="json"),
                "hybrid_result_mode": "greedy-incumbent-plus-training",
                "result_output": str(result_output) if result_output is not None else None,
            },
            indent=2,
        )
    )


@app.command("apply-policy")
def apply_q_learning_policy(
    scenario_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True),
    ],
    policy_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write the replay result JSON."),
    ] = None,
) -> None:
    """Replay an exported policy on its fingerprint-matched scenario."""

    try:
        scenario = Scenario.from_json(scenario_path)
        policy = LinearQPolicy.from_json(policy_path)
        result = rollout_policy(scenario, policy)
    except (OSError, ValidationError, ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    rendered = json.dumps(_result_payload(result), indent=2) + "\n"
    if output is None:
        typer.echo(rendered, nl=False)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        typer.echo(f"Wrote {output}")


@app.command("validate")
def validate_scenario(
    scenario_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Validate a scenario against the v0.1 domain contract."""

    try:
        scenario = Scenario.from_json(scenario_path)
    except (OSError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        json.dumps(
            {
                "valid": True,
                "schema_version": scenario.schema_version,
                "scenario_id": scenario.scenario_id,
                "task_count": len(scenario.tasks),
            },
            indent=2,
        )
    )


@app.command("report")
def render_report(
    report_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Standalone HTML output path."),
    ] = None,
    scenario_id: Annotated[
        str | None,
        typer.Option(help="Representative scenario; defaults to the last matrix scenario."),
    ] = None,
    solver_name: Annotated[
        str | None,
        typer.Option("--solver", help="Representative solver; defaults to rank one."),
    ] = None,
    algorithm_seed: Annotated[
        int | None,
        typer.Option("--seed", help="Representative algorithm seed."),
    ] = None,
) -> None:
    """Render a standalone visual report from an exported benchmark JSON report."""

    destination = output or report_path.with_suffix(".html")
    try:
        selection = write_benchmark_html_from_json(
            report_path,
            destination,
            scenario_id=scenario_id,
            solver_name=solver_name,
            algorithm_seed=algorithm_seed,
        )
    except (OSError, ValidationError, ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        json.dumps(
            {
                "output": str(selection.output_path),
                "scenario_id": selection.scenario_id,
                "solver_name": selection.solver_name,
                "algorithm_seed": selection.algorithm_seed,
                "metrics_verified": selection.metrics_verified,
            },
            indent=2,
        )
    )


@app.command("schema")
def print_schema(
    target: Annotated[
        SchemaTarget,
        typer.Option("--target", "-t", help="Select the contract to export."),
    ] = SchemaTarget.SCENARIO,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write the schema to a file."),
    ] = None,
) -> None:
    """Print or write the authoritative JSON Schema generated by the domain model."""

    models: dict[SchemaTarget, type[DomainModel]] = {
        SchemaTarget.POLICY: LinearQPolicy,
        SchemaTarget.SCENARIO: Scenario,
        SchemaTarget.SCHEDULE: Schedule,
    }
    model = models[target]
    rendered = json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
    if output is None:
        typer.echo(rendered, nl=False)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    typer.echo(f"Wrote {output}")


@app.command("check")
def check_schedule(
    scenario_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    schedule_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Simulate a schedule and report every violated hard constraint."""

    try:
        scenario = Scenario.from_json(scenario_path)
        schedule = Schedule.from_json(schedule_path)
    except (OSError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    report = validate_schedule(scenario, schedule)
    payload = report.model_dump(mode="json", exclude_none=True)
    payload["is_feasible"] = report.is_feasible
    typer.echo(json.dumps(payload, indent=2))
    if not report.is_feasible:
        raise typer.Exit(code=1)


@app.command("solvers")
def list_solvers() -> None:
    """List stable names for all built-in scheduling solvers."""

    typer.echo("\n".join(available_solvers()))


@app.command("benchmark")
def benchmark_campaign(
    config_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True),
    ],
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            file_okay=False,
            help="Artifact directory; defaults to runs/<benchmark-id>.",
        ),
    ] = None,
    checkpoint_dir: Annotated[
        Path | None,
        typer.Option(
            "--checkpoint-dir",
            file_okay=False,
            help="Atomic per-run checkpoints; defaults beside the artifact directory.",
        ),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option(help="Reuse matching completed run checkpoints."),
    ] = False,
    workers: Annotated[
        int,
        typer.Option(min=1, max=64, help="Bounded worker threads for independent runs."),
    ] = 1,
    retry_failures: Annotated[
        bool,
        typer.Option(help="When resuming, execute failed checkpoints again."),
    ] = False,
) -> None:
    """Run a reproducible benchmark campaign and export its artifacts."""

    try:
        spec = BenchmarkSpec.from_toml(config_path)
        destination = output_dir or Path("runs") / spec.benchmark_id
        checkpoints = checkpoint_dir or destination.parent / f".{destination.name}.checkpoints"
        report = run_benchmark(
            spec,
            checkpoint_dir=checkpoints,
            resume=resume,
            workers=workers,
            retry_failures=retry_failures,
        )
        files = export_benchmark(report, destination)
    except (OSError, ValidationError, ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        json.dumps(
            {
                "benchmark_id": spec.benchmark_id,
                "scenario_count": len(report.scenarios),
                "run_count": len(report.runs),
                "failed_runs": sum(not run.feasible for run in report.runs),
                "reproducibility_fingerprint": report.reproducibility_fingerprint,
                "output_dir": str(destination),
                "checkpoint_dir": str(checkpoints),
                "resume": resume,
                "workers": workers,
                "artifact_count": len(files),
                "ranking": [
                    {
                        "rank": summary.rank,
                        "solver_name": summary.solver_name,
                        "feasible_rate": summary.feasible_rate,
                        "mean_value_ratio": summary.mean_value_ratio,
                    }
                    for summary in report.summaries
                ],
            },
            indent=2,
        )
    )


@app.command("benchmark-verify")
def verify_benchmark_export(
    artifact_dir: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=False, readable=True),
    ],
) -> None:
    """Verify the complete file set, checksums, and report identity of an export."""

    try:
        files = verify_benchmark_artifacts(artifact_dir)
        manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "valid": True,
                "benchmark_id": manifest["benchmark_id"],
                "reproducibility_fingerprint": manifest["reproducibility_fingerprint"],
                "artifact_count": len(files),
                "artifact_dir": str(artifact_dir),
            },
            indent=2,
        )
    )


@app.command("solve")
def solve_scenario(
    scenario_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    solver_name: Annotated[
        str,
        typer.Option("--solver", "-s", help="Built-in solver name."),
    ] = "greedy-insertion",
    seed: Annotated[int, typer.Option(help="Deterministic random seed.")] = 0,
    time_limit_s: Annotated[
        float | None,
        typer.Option("--time-limit", min=0.000001, help="Optional soft time limit in seconds."),
    ] = None,
    evaluation_budget: Annotated[
        int,
        typer.Option(
            "--evaluation-budget",
            min=1,
            help="Maximum unique decoded candidates for search-based solvers.",
        ),
    ] = 500,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="Write the result JSON to a file."),
    ] = None,
) -> None:
    """Solve a scenario, then validate and score the resulting schedule."""

    try:
        scenario = Scenario.from_json(scenario_path)
        solver = get_solver(
            solver_name,
            seed=seed,
            time_limit_s=time_limit_s,
            evaluation_budget=evaluation_budget,
        )
        result = solver.solve(scenario)
    except (OSError, ValidationError, ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    rendered = json.dumps(_result_payload(result), indent=2) + "\n"
    if output is None:
        typer.echo(rendered, nl=False)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        typer.echo(f"Wrote {output}")
