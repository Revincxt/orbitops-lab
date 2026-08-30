# ruff: noqa: E501
"""Self-contained, dependency-free benchmark report rendering."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from statistics import fmean

from orbitops.benchmarking.generator import generate_scenario
from orbitops.benchmarking.models import (
    BenchmarkReport,
    ScenarioDescriptor,
)
from orbitops.benchmarking.runner import normalized_value_ratios
from orbitops.domain.models import Scenario, SolveResult
from orbitops.solvers.registry import get_solver


@dataclass(frozen=True, slots=True)
class ReportSelection:
    output_path: Path
    scenario_id: str
    solver_name: str
    algorithm_seed: int
    metrics_verified: bool


def _fmt(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _estimate_interval(
    estimate: float | None,
    low: float | None,
    high: float | None,
    *,
    digits: int = 3,
) -> str:
    if estimate is None:
        return "—"
    if low is None or high is None:
        return _fmt(estimate, digits)
    return f"{_fmt(estimate, digits)} [{_fmt(low, digits)}, {_fmt(high, digits)}]"


def _descriptor(report: BenchmarkReport, scenario_id: str | None) -> ScenarioDescriptor:
    if not report.scenarios:
        raise ValueError("benchmark report contains no scenarios")
    if scenario_id is None:
        return report.scenarios[-1]
    for descriptor in report.scenarios:
        if descriptor.scenario_id == scenario_id:
            return descriptor
    raise ValueError(f"unknown report scenario {scenario_id!r}")


def _solver(report: BenchmarkReport, solver_name: str | None) -> str:
    selected = solver_name or report.summaries[0].solver_name
    if selected not in report.spec.solvers:
        raise ValueError(f"solver {selected!r} is not present in this benchmark")
    return selected


def _seed(report: BenchmarkReport, algorithm_seed: int | None) -> int:
    selected = report.spec.algorithm_seeds[0] if algorithm_seed is None else algorithm_seed
    if selected not in report.spec.algorithm_seeds:
        raise ValueError(f"algorithm seed {selected!r} is not present in this benchmark")
    return selected


def _replay(
    report: BenchmarkReport,
    descriptor: ScenarioDescriptor,
    solver_name: str,
    algorithm_seed: int,
) -> tuple[Scenario, SolveResult, bool]:
    scenario, regenerated = generate_scenario(
        report.spec,
        descriptor.size,
        descriptor.difficulty,
        descriptor.instance_index,
    )
    if regenerated.sha256 != descriptor.sha256:
        raise RuntimeError(f"scenario fingerprint mismatch for {descriptor.scenario_id!r}")
    result = get_solver(
        solver_name,
        seed=algorithm_seed,
        time_limit_s=report.spec.time_limit_s,
        evaluation_budget=report.spec.evaluation_budget,
    ).solve(scenario)
    stored = next(
        (
            run
            for run in report.runs
            if run.scenario_id == descriptor.scenario_id
            and run.solver_name == solver_name
            and run.algorithm_seed == algorithm_seed
        ),
        None,
    )
    verified = stored is not None and stored.feasible and stored.metrics == result.metrics
    return scenario, result, verified


def _ranking(report: BenchmarkReport) -> str:
    rows: list[str] = []
    for summary in report.summaries:
        ratio = summary.mean_value_ratio or 0.0
        rows.append(
            "".join(
                (
                    '<div class="rank-row">',
                    f'<span class="rank-index">{summary.rank}</span>',
                    f'<span class="rank-name">{escape(summary.solver_name)}</span>',
                    '<span class="rank-track" aria-hidden="true">',
                    f'<span class="rank-fill" style="width:{ratio * 100:.3f}%"></span>',
                    "</span>",
                    f'<span class="rank-value">{ratio:.3f}</span>',
                    "</div>",
                )
            )
        )
    return (
        '<div class="ranking" role="img" '
        'aria-label="Solver ranking by mean normalized value ratio">' + "".join(rows) + "</div>"
    )


def _difficulty_heatmap(report: BenchmarkReport) -> str:
    ratios = normalized_value_ratios(report.runs)
    header = "".join(
        f"<th>{escape(difficulty.title())}</th>" for difficulty in report.spec.difficulties
    )
    rows: list[str] = []
    for summary in report.summaries:
        cells: list[str] = []
        for difficulty in report.spec.difficulties:
            values = [
                ratios[run.run_id]
                for run in report.runs
                if run.solver_name == summary.solver_name
                and run.difficulty == difficulty
                and run.run_id in ratios
            ]
            value = fmean(values) if values else None
            opacity = 0.08 + 0.42 * (value or 0.0)
            label = _fmt(value)
            cells.append(
                f'<td style="background:color-mix(in srgb,var(--lavender) '
                f'{opacity * 100:.1f}%,transparent)" '
                f'aria-label="{escape(summary.solver_name)}, {difficulty}: {label}">'
                f"{label}</td>"
            )
        rows.append(f"<tr><th>{escape(summary.solver_name)}</th>{''.join(cells)}</tr>")
    return (
        '<div class="table-wrap"><table class="heatmap">'
        f"<thead><tr><th>Solver</th>{header}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _polyline(points: tuple[tuple[float, float], ...]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def _convergence(report: BenchmarkReport, scenario_id: str, seed: int) -> str:
    runs = [
        run
        for run in report.runs
        if run.scenario_id == scenario_id
        and run.algorithm_seed == seed
        and run.evaluations is not None
        and run.convergence
    ]
    if not runs:
        return '<p class="empty">No iterative convergence traces for this selection.</p>'

    width, height = 960.0, 340.0
    left, right, top, bottom = 78.0, 150.0, 24.0, 58.0
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_evaluation = max(point.evaluation for run in runs for point in run.convergence) or 1
    max_value = max(point.total_value for run in runs for point in run.convergence) or 1.0

    def x(value: int) -> float:
        return left + value / max_evaluation * plot_width

    def y(value: float) -> float:
        return top + (1.0 - value / max_value) * plot_height

    grid: list[str] = []
    for fraction in (0.0, 0.5, 1.0):
        y_position = top + (1.0 - fraction) * plot_height
        grid.append(
            f'<line x1="{left}" y1="{y_position:.2f}" x2="{left + plot_width}" '
            f'y2="{y_position:.2f}" class="grid-line" />'
        )
        grid.append(
            f'<text x="{left - 12}" y="{y_position + 4:.2f}" text-anchor="end" '
            f'class="axis-label">{max_value * fraction:.0f}</text>'
        )
    for fraction in (0.0, 0.5, 1.0):
        x_position = left + fraction * plot_width
        grid.append(
            f'<text x="{x_position:.2f}" y="{height - 22}" text-anchor="middle" '
            f'class="axis-label">{round(max_evaluation * fraction)}</text>'
        )

    series: list[str] = []
    table_rows: list[str] = []
    for index, run in enumerate(runs, start=1):
        points = tuple((x(point.evaluation), y(point.total_value)) for point in run.convergence)
        css_class = f"series-{(index - 1) % 6 + 1}"
        series.append(f'<polyline points="{_polyline(points)}" class="curve {css_class}" />')
        for point_x, point_y in points:
            series.append(
                f'<circle cx="{point_x:.2f}" cy="{point_y:.2f}" r="4" '
                f'class="curve-point {css_class}" />'
            )
        final_x, final_y = points[-1]
        series.append(
            f'<text x="{final_x + 10:.2f}" y="{final_y + 4:.2f}" '
            f'class="curve-label">{escape(run.solver_name)}</text>'
        )
        for point in run.convergence:
            table_rows.append(
                f"<tr><th>{escape(run.solver_name)}</th><td>{point.evaluation}</td>"
                f"<td>{point.total_value:.3f}</td>"
                f"<td>{point.completed_tasks}</td></tr>"
            )

    svg = (
        f'<svg class="desktop-chart" viewBox="0 0 {width:.0f} {height:.0f}" '
        'role="img" aria-labelledby="convergence-title convergence-desc">'
        '<title id="convergence-title">Search convergence</title>'
        f'<desc id="convergence-desc">Incumbent total value by evaluation for {escape(scenario_id)}, '
        f"algorithm seed {seed}.</desc>"
        + "".join(grid)
        + f'<text x="{left + plot_width / 2:.2f}" y="{height - 4}" '
        'text-anchor="middle" class="axis-title">Unique genome evaluations</text>'
        + f'<text transform="translate(18 {top + plot_height / 2:.2f}) rotate(-90)" '
        'text-anchor="middle" class="axis-title">Total value</text>' + "".join(series) + "</svg>"
    )
    mobile = (
        '<div class="mobile-data table-wrap"><table><thead><tr><th>Solver</th>'
        "<th>Evaluation</th><th>Value</th><th>Tasks</th></tr></thead>"
        f"<tbody>{''.join(table_rows)}</tbody></table></div>"
    )
    return svg + mobile


def _gantt(scenario: Scenario, result: SolveResult) -> str:
    simulation = result.validation.simulation
    if simulation is None or not simulation.tasks:
        return '<p class="empty">The selected replay produced an empty schedule.</p>'

    tasks = simulation.tasks
    width = 960.0
    left, right, top = 165.0, 38.0, 34.0
    row_height = 34.0
    plot_width = width - left - right
    height = top + len(tasks) * row_height + 58.0
    horizon = scenario.horizon_end_s - scenario.horizon_start_s

    def x(value: float) -> float:
        return left + (value - scenario.horizon_start_s) / horizon * plot_width

    marks: list[str] = []
    table_rows: list[str] = []
    for index, task in enumerate(tasks):
        row_y = top + index * row_height
        task_x = x(task.start_s)
        task_width = max(2.0, x(task.end_s) - task_x)
        slew_start = max(scenario.horizon_start_s, task.start_s - task.slew_time_s)
        marks.append(
            f'<text x="{left - 12}" y="{row_y + 19:.2f}" text-anchor="end" '
            f'class="gantt-label">{escape(task.task_id)}</text>'
        )
        if task.slew_time_s > 0:
            marks.append(
                f'<rect x="{x(slew_start):.2f}" y="{row_y + 13:.2f}" '
                f'width="{max(1.0, task_x - x(slew_start)):.2f}" height="6" '
                'class="gantt-slew"><title>'
                f"Slew {task.slew_time_s:.1f} s</title></rect>"
            )
        marks.append(
            f'<rect x="{task_x:.2f}" y="{row_y + 7:.2f}" width="{task_width:.2f}" '
            'height="18" rx="4" class="gantt-task"><title>'
            f"{escape(task.task_id)} · {task.start_s:.1f}-{task.end_s:.1f} s · "
            f"{escape(task.window_id)}</title></rect>"
        )
        table_rows.append(
            f"<tr><th>{escape(task.task_id)}</th><td>{task.start_s:.1f}</td>"
            f"<td>{task.end_s:.1f}</td><td>{task.slew_time_s:.1f}</td>"
            f"<td>{escape(task.window_id)}</td></tr>"
        )

    ticks: list[str] = []
    axis_y = top + len(tasks) * row_height + 8.0
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        value = scenario.horizon_start_s + fraction * horizon
        tick_x = x(value)
        ticks.append(
            f'<line x1="{tick_x:.2f}" y1="{top - 8}" x2="{tick_x:.2f}" '
            f'y2="{axis_y}" class="grid-line" />'
        )
        ticks.append(
            f'<text x="{tick_x:.2f}" y="{axis_y + 24}" text-anchor="middle" '
            f'class="axis-label">{value:.0f}s</text>'
        )

    svg = (
        f'<svg class="desktop-chart" viewBox="0 0 {width:.0f} {height:.0f}" '
        'role="img" aria-labelledby="gantt-title gantt-desc">'
        '<title id="gantt-title">Representative schedule timeline</title>'
        f'<desc id="gantt-desc">{len(tasks)} scheduled observation tasks. Lavender bars are '
        "observations and peach bars are required slews.</desc>"
        + "".join(ticks)
        + "".join(marks)
        + "</svg>"
    )
    mobile = (
        '<div class="mobile-data table-wrap"><table><thead><tr><th>Task</th>'
        "<th>Start</th><th>End</th><th>Slew</th><th>Window</th></tr></thead>"
        f"<tbody>{''.join(table_rows)}</tbody></table></div>"
    )
    return svg + mobile


def _summary_table(report: BenchmarkReport) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{summary.rank}</td><th>{escape(summary.solver_name)}</th>"
        f"<td>{summary.feasible_rate:.3f}</td>"
        f"<td>{_estimate_interval(summary.mean_value_ratio, summary.value_ratio_ci95_low, summary.value_ratio_ci95_high)}</td>"
        f"<td>{summary.value_ratio_scenario_count if summary.value_ratio_scenario_count is not None else '—'}</td>"
        f"<td>{_fmt(summary.best_observed_rate)}</td>"
        f"<td>{_fmt(summary.mean_total_value)} / {_fmt(summary.median_total_value)}</td>"
        f"<td>{_fmt(summary.mean_completed_tasks, 2)}</td>"
        f"<td>{_fmt(summary.mean_total_slew_time_s, 2)}</td>"
        f"<td>{summary.mean_runtime_s:.5f}</td>"
        "</tr>"
        for summary in report.summaries
    )
    return (
        '<details><summary>Exact solver summary</summary><div class="table-wrap">'
        "<table><thead><tr><th>Rank</th><th>Solver</th><th>Feasible</th>"
        "<th>Value ratio mean [scenario-block 95% CI]</th><th>Ratio scenarios</th>"
        "<th>Best rate</th><th>Raw value mean / median</th>"
        "<th>Tasks</th><th>Slew</th>"
        f"<th>Runtime</th></tr></thead><tbody>{rows}</tbody></table></div></details>"
    )


def _pairwise_table(report: BenchmarkReport) -> str:
    if not report.comparisons:
        return '<p class="empty">At least two solvers are required for paired evidence.</p>'
    rows = "".join(
        "<tr>"
        f"<th>{escape(comparison.solver_a)}</th>"
        f"<th>{escape(comparison.solver_b)}</th>"
        f"<td>{comparison.paired_count}</td>"
        f"<td>{comparison.failed_both_count}</td>"
        f"<td>{comparison.wins_a} / {comparison.ties} / {comparison.losses_a}</td>"
        f"<td>{_fmt(comparison.win_rate_a)}</td>"
        f"<td>{comparison.both_feasible_count}</td>"
        f"<td>{_estimate_interval(comparison.mean_normalized_value_gap, comparison.normalized_value_gap_ci95_low, comparison.normalized_value_gap_ci95_high)}</td>"
        f"<td>{comparison.normalized_value_gap_scenario_count if comparison.normalized_value_gap_scenario_count is not None else '—'}</td>"
        "</tr>"
        for comparison in report.comparisons
    )
    return (
        '<div class="table-wrap"><table><thead><tr><th>Solver A</th><th>Solver B</th>'
        "<th>Shared cells</th><th>Excluded (both failed)</th>"
        "<th>A win / tie / loss</th><th>A win rate</th><th>Both feasible</th>"
        "<th>Normalized value gap [scenario-block 95% CI]</th><th>Gap scenarios</th>"
        f"</tr></thead><tbody>{rows}</tbody></table></div>"
    )


def render_benchmark_html(
    report: BenchmarkReport,
    scenario: Scenario,
    result: SolveResult,
    *,
    metrics_verified: bool,
) -> str:
    """Render one complete standalone benchmark report document."""

    scenario_id = scenario.scenario_id
    solver_name = result.schedule.solver_name
    seed = result.schedule.seed if result.schedule.seed is not None else 0
    verification_text = (
        "Replay matches stored metrics"
        if metrics_verified
        else "Replay differs from stored metrics"
    )
    verification_class = "verified" if metrics_verified else "warning"
    fingerprint = report.reproducibility_fingerprint
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(report.spec.benchmark_id)} · OrbitOps benchmark report</title>
  <style>
    :root {{ color-scheme: light dark; --bg:#fffaf7; --surface:#fffefd; --text:#332a3b;
      --muted:#746b79; --border:#e8dfe8; --lavender:#8d6bb8; --lavender-soft:#eadff4;
      --peach:#d99468; --peach-soft:#f7dfd0; --grid:#ded5df; --good:#437a63;
      --warn:#a15c3d; --shadow:0 18px 50px rgba(93,66,105,.09); }}
    @media (prefers-color-scheme: dark) {{ :root {{ --bg:#17131b; --surface:#211b26;
      --text:#f5edf7; --muted:#b9acbd; --border:#3d3343; --lavender:#b99adb;
      --lavender-soft:#3b2d49; --peach:#e6a57e; --peach-soft:#4a3027; --grid:#433849;
      --good:#82b89d; --warn:#e2a181; --shadow:none; }} }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--text);
      font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      line-height:1.5; }} .page {{ width:min(1180px,100%); margin:0 auto; padding:48px 28px 72px; }}
    .hero {{ padding:34px; background:linear-gradient(135deg,var(--lavender-soft),var(--peach-soft));
      border:1px solid var(--border); border-radius:24px; box-shadow:var(--shadow); }}
    .eyebrow {{ margin:0 0 6px; color:var(--muted); font-size:.82rem; letter-spacing:.12em;
      text-transform:uppercase; }} h1 {{ margin:0; font-size:clamp(2rem,6vw,4.4rem); line-height:1.05;
      font-weight:500; letter-spacing:-.045em; }} .hero-meta {{ display:flex; flex-wrap:wrap;
      gap:8px 18px; margin-top:20px; color:var(--muted); }} .hero-meta strong {{ color:var(--text);
      font-weight:500; }} section {{ padding:42px 4px; border-bottom:1px solid var(--border); }}
    h2 {{ margin:0 0 8px; font-size:clamp(1.35rem,3vw,2rem); font-weight:500; }}
    .section-note {{ margin:0 0 26px; color:var(--muted); max-width:76ch; }}
    .ranking {{ display:grid; gap:12px; }} .rank-row {{ display:grid;
      grid-template-columns:2rem minmax(8rem,12rem) minmax(7rem,1fr) 4rem; gap:12px;
      align-items:center; }} .rank-index,.rank-value {{ font-variant-numeric:tabular-nums;
      color:var(--muted); }} .rank-name {{ font-weight:500; }} .rank-track {{ height:18px;
      background:var(--lavender-soft); border-radius:999px; overflow:hidden; }} .rank-fill {{ display:block;
      height:100%; background:var(--lavender); border-radius:inherit; }} .table-wrap {{ width:100%;
      overflow-x:auto; }} table {{ width:100%; border-collapse:collapse; font-size:.92rem; }}
    th,td {{ padding:11px 12px; border-bottom:1px solid var(--border); text-align:right;
      font-variant-numeric:tabular-nums; }} th:first-child,td:first-child {{ text-align:left; }}
    thead th {{ color:var(--muted); font-weight:500; }} tbody th {{ font-weight:500; }}
    .heatmap td {{ color:var(--text); font-weight:500; text-align:center; }} svg {{ display:block; width:100%; height:auto;
      color:var(--text); }} .grid-line {{ stroke:var(--grid); stroke-width:1; }}
    .axis-label,.axis-title,.gantt-label,.curve-label {{ fill:var(--muted); font-size:13px; }}
    .axis-title,.curve-label {{ fill:var(--text); font-weight:500; }} .curve {{ fill:none;
      stroke-width:3; stroke-linejoin:round; stroke-linecap:round; }} .curve-point {{ stroke:var(--surface);
      stroke-width:2; }} .series-1 {{ stroke:var(--lavender); fill:var(--lavender); }}
    .series-2 {{ stroke:var(--peach); fill:var(--peach); }} .series-3 {{ stroke:var(--good); fill:var(--good); }}
    .series-4 {{ stroke:var(--warn); fill:var(--warn); }} .series-5 {{ stroke:var(--text); fill:var(--text); }}
    .series-6 {{ stroke:var(--muted); fill:var(--muted); }} .gantt-task {{ fill:var(--lavender); }}
    .gantt-slew {{ fill:var(--peach); }} .selection {{ display:flex; flex-wrap:wrap; align-items:center;
      gap:8px 16px; margin:0 0 24px; color:var(--muted); }} .status {{ padding:4px 10px;
      border-radius:999px; font-size:.82rem; font-weight:500; }} .verified {{ color:var(--good);
      background:color-mix(in srgb,var(--good) 12%,transparent); }} .warning {{ color:var(--warn);
      background:color-mix(in srgb,var(--warn) 12%,transparent); }} details {{ margin-top:28px; }}
    .legend {{ display:flex; gap:18px; margin:-10px 0 18px; color:var(--muted); font-size:.86rem; }}
    .swatch {{ display:inline-block; width:18px; height:8px; margin-right:6px; border-radius:999px; }}
    .swatch-task {{ background:var(--lavender); }} .swatch-slew {{ background:var(--peach); }}
    summary {{ cursor:pointer; color:var(--muted); }} .empty {{ color:var(--muted); font-style:italic; }}
    .mobile-data {{ display:none; }} footer {{ padding-top:28px; color:var(--muted); font-size:.86rem;
      overflow-wrap:anywhere; }} code {{ color:var(--text); }}
    @media (max-width:640px) {{ .page {{ padding:22px 16px 48px; }} .hero {{ padding:24px 20px;
      border-radius:18px; }} section {{ padding:34px 0; }} .rank-row {{ grid-template-columns:1.5rem 7.2rem 1fr 3.2rem;
      gap:7px; font-size:.86rem; }} .desktop-chart {{ display:none; }} .mobile-data {{ display:block; }}
      th,td {{ padding:9px 8px; }} }}
  </style>
</head>
<body>
  <main class="page">
    <header class="hero">
      <p class="eyebrow">OrbitOps Lab · Benchmark report</p>
      <h1>{escape(report.spec.benchmark_id)}</h1>
      <div class="hero-meta">
        <span><strong>{len(report.scenarios)}</strong> scenarios</span>
        <span><strong>{len(report.runs)}</strong> solver runs</span>
        <span><strong>{report.spec.evaluation_budget}</strong> evaluation budget</span>
        <span><strong>{escape(report.environment.python_version)}</strong> Python</span>
      </div>
    </header>
    <section aria-labelledby="ranking-heading">
      <h2 id="ranking-heading">Algorithm ranking</h2>
      <p class="section-note">Feasibility is ranked first. Value ratios are normalized against the best feasible solver in each scenario/seed cell, averaged within scenario, and then averaged equally across scenarios; intervals resample scenario blocks.</p>
      {_ranking(report)}
      {_summary_table(report)}
    </section>
    <section aria-labelledby="difficulty-heading">
      <h2 id="difficulty-heading">Performance by difficulty</h2>
      <p class="section-note">Descriptive mean normalized value ratio within each synthetic difficulty tier. Darker cells are closer to the best observed value; inferential intervals are reported only at the scenario-block level above.</p>
      {_difficulty_heatmap(report)}
    </section>
    <section aria-labelledby="pairwise-heading">
      <h2 id="pairwise-heading">Paired comparisons</h2>
      <p class="section-note">Every row compares shared scenario/seed cells. One-sided failures count as feasibility wins or losses; cells where both methods fail are excluded, not ties. Win/tie/loss uses the complete lexicographic objective. Normalized primary-value gaps use jointly feasible cells, average seeds within scenario, and report deterministic scenario-block percentile-bootstrap 95% intervals; a lexicographic win can therefore have a zero value gap.</p>
      {_pairwise_table(report)}
    </section>
    <section aria-labelledby="convergence-heading">
      <h2 id="convergence-heading">Search convergence</h2>
      <p class="section-note"><code>{escape(scenario_id)}</code> · algorithm seed {seed}. Lines show incumbent value, not independent observations.</p>
      {_convergence(report, scenario_id, seed)}
    </section>
    <section aria-labelledby="schedule-heading">
      <h2 id="schedule-heading">Representative schedule</h2>
      <div class="selection"><span><code>{escape(scenario_id)}</code></span><span>{escape(solver_name)}</span><span>seed {seed}</span><span class="status {verification_class}">{verification_text}</span></div>
      <div class="legend" aria-label="Schedule legend"><span><i class="swatch swatch-task"></i>Observation</span><span><i class="swatch swatch-slew"></i>Slew</span></div>
      {_gantt(scenario, result)}
    </section>
    <footer>
      Reproducibility fingerprint: <code>{fingerprint}</code><br>
      Generator: {escape(report.environment.generator_version)} · OrbitOps {escape(report.environment.orbitops_version)} · {escape(report.environment.platform_system)} {escape(report.environment.platform_machine)}
    </footer>
  </main>
</body>
</html>
"""


def write_benchmark_html(
    report: BenchmarkReport,
    output_path: str | Path,
    *,
    scenario_id: str | None = None,
    solver_name: str | None = None,
    algorithm_seed: int | None = None,
) -> ReportSelection:
    descriptor = _descriptor(report, scenario_id)
    selected_solver = _solver(report, solver_name)
    selected_seed = _seed(report, algorithm_seed)
    scenario, result, verified = _replay(
        report,
        descriptor,
        selected_solver,
        selected_seed,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        render_benchmark_html(
            report,
            scenario,
            result,
            metrics_verified=verified,
        ),
        encoding="utf-8",
    )
    return ReportSelection(
        output_path=destination,
        scenario_id=descriptor.scenario_id,
        solver_name=selected_solver,
        algorithm_seed=selected_seed,
        metrics_verified=verified,
    )


def write_benchmark_html_from_json(
    report_path: str | Path,
    output_path: str | Path,
    *,
    scenario_id: str | None = None,
    solver_name: str | None = None,
    algorithm_seed: int | None = None,
) -> ReportSelection:
    report = BenchmarkReport.model_validate_json(Path(report_path).read_text(encoding="utf-8"))
    return write_benchmark_html(
        report,
        output_path,
        scenario_id=scenario_id,
        solver_name=solver_name,
        algorithm_seed=algorithm_seed,
    )
