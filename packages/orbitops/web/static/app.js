"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const state = { scenarios: [], solvers: [] };

const elements = {
  form: document.getElementById("solve-form"),
  scenario: document.getElementById("scenario-select"),
  solver: document.getElementById("solver-select"),
  seed: document.getElementById("seed-input"),
  budget: document.getElementById("budget-input"),
  button: document.getElementById("run-button"),
  context: document.getElementById("scenario-context"),
  status: document.getElementById("status"),
  results: document.getElementById("results"),
  runtime: document.getElementById("runtime"),
  value: document.getElementById("metric-value"),
  tasks: document.getElementById("metric-tasks"),
  taskContext: document.getElementById("metric-task-context"),
  slew: document.getElementById("metric-slew"),
  timeline: document.getElementById("timeline-chart"),
  resources: document.getElementById("resource-chart"),
  convergence: document.getElementById("convergence-chart"),
};

function svgElement(name, attributes = {}, text = null) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, String(value));
  }
  if (text !== null) element.textContent = text;
  return element;
}

function chart(width, height, title, description) {
  const root = svgElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": `${title}. ${description}`,
  });
  root.append(svgElement("title", {}, title));
  root.append(svgElement("desc", {}, description));
  return root;
}

function emptyChart(host, message) {
  const empty = document.createElement("p");
  empty.className = "chart-empty";
  empty.textContent = message;
  host.replaceChildren(empty);
}

function addGrid(root, dimensions, xTicks, yTicks, xFormat, yFormat) {
  const { left, top, plotWidth, plotHeight, height } = dimensions;
  for (const tick of yTicks) {
    const y = top + (1 - tick.position) * plotHeight;
    root.append(svgElement("line", { x1: left, y1: y, x2: left + plotWidth, y2: y, class: "chart-grid" }));
    root.append(svgElement("text", { x: left - 10, y: y + 4, "text-anchor": "end", class: "chart-axis" }, yFormat(tick.value)));
  }
  for (const tick of xTicks) {
    const x = left + tick.position * plotWidth;
    root.append(svgElement("text", { x, y: height - 14, "text-anchor": "middle", class: "chart-axis" }, xFormat(tick.value)));
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed with ${response.status}`);
  return payload;
}

function populateSelect(select, items, valueKey, labelFactory) {
  const options = items.map((item) => {
    const option = document.createElement("option");
    option.value = item[valueKey];
    option.textContent = labelFactory(item);
    return option;
  });
  select.replaceChildren(...options);
}

function updateScenarioContext() {
  const scenario = state.scenarios.find((item) => item.scenario_id === elements.scenario.value);
  if (!scenario) return;
  elements.context.textContent = `${scenario.task_count} tasks · ${scenario.horizon_end_s - scenario.horizon_start_s}s horizon`;
  for (const option of elements.solver.options) {
    const solver = state.solvers.find((item) => item.solver_name === option.value);
    option.disabled = Boolean(solver && solver.max_tasks !== null && scenario.task_count > solver.max_tasks);
  }
  if (elements.solver.selectedOptions[0]?.disabled) elements.solver.value = "greedy-insertion";
}

function setBusy(busy, message) {
  elements.button.disabled = busy;
  elements.button.firstChild.textContent = busy ? "Running scheduler " : "Run scheduler ";
  elements.status.classList.remove("error");
  elements.status.textContent = message;
}

function linePoints(points, x, y) {
  return points.map((point) => `${x(point.x).toFixed(2)},${y(point.y).toFixed(2)}`).join(" ");
}

function renderTimeline(scenario, result) {
  const simulation = result.validation.simulation;
  if (!simulation || simulation.tasks.length === 0) {
    emptyChart(elements.timeline, "No observations were scheduled for this run.");
    return;
  }
  const width = 980;
  const left = 150;
  const right = 34;
  const top = 28;
  const rowHeight = 34;
  const height = top + simulation.tasks.length * rowHeight + 52;
  const plotWidth = width - left - right;
  const horizon = scenario.horizon_end_s - scenario.horizon_start_s;
  const x = (value) => left + ((value - scenario.horizon_start_s) / horizon) * plotWidth;
  const root = chart(width, height, "Observation schedule", `${simulation.tasks.length} scheduled tasks on a ${horizon} second horizon.`);

  for (let tick = 0; tick <= 4; tick += 1) {
    const fraction = tick / 4;
    const value = scenario.horizon_start_s + horizon * fraction;
    const tickX = x(value);
    root.append(svgElement("line", { x1: tickX, y1: top - 8, x2: tickX, y2: height - 42, class: "chart-grid" }));
    root.append(svgElement("text", { x: tickX, y: height - 14, "text-anchor": "middle", class: "chart-axis" }, `${Math.round(value)}s`));
  }

  simulation.tasks.forEach((task, index) => {
    const y = top + index * rowHeight;
    root.append(svgElement("text", { x: left - 12, y: y + 20, "text-anchor": "end", class: "task-label" }, task.task_id));
    if (task.slew_time_s > 0) {
      const slewStart = Math.max(scenario.horizon_start_s, task.start_s - task.slew_time_s);
      const slew = svgElement("rect", {
        x: x(slewStart), y: y + 14, width: Math.max(1, x(task.start_s) - x(slewStart)), height: 6,
        rx: 3, class: "slew-bar",
      });
      slew.append(svgElement("title", {}, `Slew ${task.slew_time_s.toFixed(1)} seconds`));
      root.append(slew);
    }
    const observation = svgElement("rect", {
      x: x(task.start_s), y: y + 8, width: Math.max(2, x(task.end_s) - x(task.start_s)), height: 18,
      rx: 5, class: "task-bar",
    });
    observation.append(svgElement("title", {}, `${task.task_id}: ${task.start_s.toFixed(1)}-${task.end_s.toFixed(1)}s · ${task.window_id}`));
    root.append(observation);
  });
  elements.timeline.replaceChildren(root);
}

function renderResources(scenario, result) {
  const simulation = result.validation.simulation;
  if (!simulation) {
    emptyChart(elements.resources, "Resource trace is unavailable.");
    return;
  }
  const satellite = scenario.satellite;
  const energy = [{ x: scenario.horizon_start_s, y: (satellite.initial_energy_wh / satellite.energy_capacity_wh) * 100 }];
  const storage = [{ x: scenario.horizon_start_s, y: (satellite.initial_storage_gb / satellite.storage_capacity_gb) * 100 }];
  simulation.tasks.forEach((task) => {
    energy.push({ x: task.end_s, y: (task.energy_after_wh / satellite.energy_capacity_wh) * 100 });
    storage.push({ x: task.end_s, y: (task.storage_after_gb / satellite.storage_capacity_gb) * 100 });
  });

  const width = 650;
  const height = 300;
  const dimensions = { left: 54, top: 22, plotWidth: 540, plotHeight: 220, height };
  const horizon = scenario.horizon_end_s - scenario.horizon_start_s;
  const x = (value) => dimensions.left + ((value - scenario.horizon_start_s) / horizon) * dimensions.plotWidth;
  const y = (value) => dimensions.top + (1 - value / 100) * dimensions.plotHeight;
  const root = chart(width, height, "Resource trace", "Energy remaining and storage used as percentages of capacity.");
  addGrid(
    root,
    dimensions,
    [0, 0.5, 1].map((position) => ({ position, value: scenario.horizon_start_s + horizon * position })),
    [0, 0.5, 1].map((position) => ({ position, value: position * 100 })),
    (value) => `${Math.round(value)}s`,
    (value) => `${Math.round(value)}%`,
  );
  root.append(svgElement("polyline", { points: linePoints(energy, x, y), class: "energy-line" }));
  root.append(svgElement("polyline", { points: linePoints(storage, x, y), class: "storage-line" }));
  const energyFinal = energy.at(-1);
  const storageFinal = storage.at(-1);
  root.append(svgElement("text", { x: x(energyFinal.x) + 8, y: y(energyFinal.y) + 4, class: "chart-title-label" }, `Energy ${energyFinal.y.toFixed(0)}%`));
  root.append(svgElement("text", { x: x(storageFinal.x) + 8, y: y(storageFinal.y) + 4, class: "chart-title-label" }, `Storage ${storageFinal.y.toFixed(0)}%`));
  elements.resources.replaceChildren(root);
}

function renderConvergence(points) {
  if (!points.length) {
    emptyChart(elements.convergence, "This solver did not publish a convergence trace.");
    return;
  }
  const width = 650;
  const height = 300;
  const dimensions = { left: 58, top: 22, plotWidth: 520, plotHeight: 220, height };
  const maxEvaluation = Math.max(1, ...points.map((point) => point.evaluation));
  const maxValue = Math.max(1, ...points.map((point) => point.total_value));
  const x = (value) => dimensions.left + (value / maxEvaluation) * dimensions.plotWidth;
  const y = (value) => dimensions.top + (1 - value / maxValue) * dimensions.plotHeight;
  const root = chart(width, height, "Search convergence", "Incumbent total value by unique genome evaluation.");
  addGrid(
    root,
    dimensions,
    [0, 0.5, 1].map((position) => ({ position, value: maxEvaluation * position })),
    [0, 0.5, 1].map((position) => ({ position, value: maxValue * position })),
    (value) => `${Math.round(value)}`,
    (value) => `${Math.round(value)}`,
  );
  const series = points.map((point) => ({ x: point.evaluation, y: point.total_value }));
  root.append(svgElement("polyline", { points: linePoints(series, x, y), class: "convergence-line" }));
  series.forEach((point) => root.append(svgElement("circle", { cx: x(point.x), cy: y(point.y), r: 4, class: "chart-point" })));
  const final = series.at(-1);
  root.append(svgElement("text", { x: x(final.x) + 8, y: y(final.y) + 4, class: "chart-title-label" }, `Value ${final.y.toFixed(1)}`));
  elements.convergence.replaceChildren(root);
}

function renderResult(payload) {
  const { scenario, result, convergence } = payload;
  elements.value.textContent = result.metrics.total_value.toFixed(2);
  elements.tasks.textContent = String(result.metrics.completed_tasks);
  elements.taskContext.textContent = `of ${scenario.tasks.length} candidates`;
  elements.slew.textContent = `${result.metrics.total_slew_time_s.toFixed(1)}s`;
  elements.runtime.textContent = `${result.schedule.solver_name} · seed ${result.schedule.seed ?? "—"} · ${(result.runtime_s * 1000).toFixed(1)} ms`;
  renderTimeline(scenario, result);
  renderResources(scenario, result);
  renderConvergence(convergence);
  elements.results.hidden = false;
}

async function runSolve() {
  setBusy(true, "Solving and validating the schedule…");
  try {
    const payload = await api("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        scenario_id: elements.scenario.value,
        solver_name: elements.solver.value,
        seed: Number(elements.seed.value),
        evaluation_budget: Number(elements.budget.value),
      }),
    });
    renderResult(payload);
    elements.status.textContent = "Feasible schedule verified by the shared simulator.";
  } catch (error) {
    elements.status.classList.add("error");
    elements.status.textContent = error instanceof Error ? error.message : "The run failed.";
  } finally {
    elements.button.disabled = false;
    elements.button.firstChild.textContent = "Run scheduler ";
  }
}

async function initialize() {
  try {
    const [scenarioPayload, solverPayload] = await Promise.all([api("/api/scenarios"), api("/api/solvers")]);
    state.scenarios = scenarioPayload.scenarios;
    state.solvers = solverPayload.solvers;
    populateSelect(elements.scenario, state.scenarios, "scenario_id", (item) => item.name);
    populateSelect(elements.solver, state.solvers, "solver_name", (item) => `${item.solver_name} · ${item.category}`);
    elements.solver.value = "greedy-insertion";
    updateScenarioContext();
    await runSolve();
  } catch (error) {
    elements.status.classList.add("error");
    elements.status.textContent = error instanceof Error ? error.message : "The lab could not start.";
  }
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  runSolve();
});
elements.scenario.addEventListener("change", updateScenarioContext);
initialize();
