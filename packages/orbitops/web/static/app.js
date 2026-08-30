"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const state = {
  scenarios: [],
  solvers: [],
  globe: null,
  imageryFallbackActive: false,
  staticDataset: null,
  runCache: new Map(),
};
const deployment = window.ORBITOPS_DEPLOYMENT || { mode: "api" };
const staticDeployment = deployment.mode === "static";
let staticDatasetPromise = null;

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
  feasible: document.getElementById("metric-feasible"),
  timeline: document.getElementById("timeline-chart"),
  resources: document.getElementById("resource-chart"),
  learning: document.getElementById("learning-chart"),
  learningTitle: document.getElementById("learning-title"),
  learningKicker: document.getElementById("learning-kicker"),
  learningLegend: document.getElementById("learning-legend"),
  globe: document.getElementById("mission-globe"),
  globeLoading: document.getElementById("globe-loading"),
  globeTargets: document.getElementById("globe-targets"),
  globeSequence: document.getElementById("globe-sequence"),
  deploymentMode: document.getElementById("deployment-mode"),
  comparisonBody: document.getElementById("comparison-body"),
  comparisonContext: document.getElementById("comparison-context"),
  comparisonNote: document.getElementById("comparison-note"),
  auditSummary: document.getElementById("audit-summary"),
  auditMethodology: document.getElementById("audit-methodology"),
  unscheduledList: document.getElementById("unscheduled-list"),
  validationList: document.getElementById("validation-list"),
  recordScenario: document.getElementById("record-scenario"),
  recordMethod: document.getElementById("record-method"),
  recordSeed: document.getElementById("record-seed"),
  recordBudget: document.getElementById("record-budget"),
  recordRevision: document.getElementById("record-revision"),
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

function seriesPoints(points, x, y) {
  return points.map((point) => `${x(point.x).toFixed(2)},${y(point.y).toFixed(2)}`).join(" ");
}

function sampleSeries(points, limit = 100) {
  if (points.length <= limit) return points;
  const sampled = [];
  for (let index = 0; index < limit; index += 1) {
    sampled.push(points[Math.round((index / (limit - 1)) * (points.length - 1))]);
  }
  return sampled;
}

function legendItems(items) {
  return items.map(([className, text]) => {
    const item = document.createElement("span");
    const swatch = document.createElement("i");
    swatch.className = `swatch ${className}`;
    item.append(swatch, document.createTextNode(text));
    return item;
  });
}

async function loadStaticDataset() {
  if (!staticDatasetPromise) {
    staticDatasetPromise = fetch("./pages-data.json").then(async (response) => {
      if (!response.ok) throw new Error("Static experiment dataset is unavailable.");
      const dataset = await response.json();
      state.staticDataset = dataset;
      return dataset;
    });
  }
  return staticDatasetPromise;
}

async function staticApi(path, options = {}) {
  const dataset = await loadStaticDataset();
  if (path === "/api/scenarios") return dataset.scenarios;
  if (path === "/api/solvers") return dataset.solvers;
  if (path === "/api/solve" && options.method === "POST") {
    const request = JSON.parse(options.body);
    const key = `${request.scenario_id}::${request.solver_name}`;
    const result = dataset.runs[key];
    if (!result) {
      const omission = (dataset.omissions || {})[key];
      throw new Error(omission?.reason || "No precomputed result is available for this method and scenario.");
    }
    return result;
  }
  throw new Error(`Static deployment does not implement ${path}.`);
}

async function api(path, options = {}) {
  if (staticDeployment) return staticApi(path, options);
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed with ${response.status}`);
  return payload;
}

function populateSelect(select, items, valueKey, labelFactory) {
  select.replaceChildren(...items.map((item) => {
    const option = document.createElement("option");
    option.value = item[valueKey];
    option.textContent = labelFactory(item);
    return option;
  }));
}

function runKey(scenarioId, solverName) {
  return `${scenarioId}::${solverName}`;
}

function selectedStaticRun() {
  return state.staticDataset?.runs[runKey(elements.scenario.value, elements.solver.value)] || null;
}

function applyStaticRunConfiguration() {
  if (!staticDeployment) return;
  const selected = selectedStaticRun();
  if (!selected) return;
  const metadata = selected.run_metadata || {};
  elements.seed.value = metadata.seed ?? state.staticDataset.metadata.seed;
  elements.budget.value = metadata.evaluation_budget ?? state.staticDataset.metadata.evaluation_budget;
}

function updateScenarioContext() {
  const scenario = state.scenarios.find((item) => item.scenario_id === elements.scenario.value);
  if (!scenario) return;
  const horizon = scenario.horizon_end_s - scenario.horizon_start_s;
  const studyQuestion = scenario.research_question ? ` · ${scenario.research_question}` : "";
  const geometryNote = scenario.geometry_note ? ` ${scenario.geometry_note}` : "";
  elements.context.textContent = `${scenario.task_count} targets · ${(horizon / 60).toFixed(0)} min planning horizon${studyQuestion}${geometryNote}`;
  for (const option of elements.solver.options) {
    const solver = state.solvers.find((item) => item.solver_name === option.value);
    const exceedsCapability = Boolean(solver && solver.max_tasks !== null && scenario.task_count > solver.max_tasks);
    const missingStaticRun = Boolean(
      staticDeployment && state.staticDataset && !state.staticDataset.runs[runKey(scenario.scenario_id, option.value)],
    );
    option.disabled = exceedsCapability || missingStaticRun;
    const omission = state.staticDataset?.omissions?.[runKey(scenario.scenario_id, option.value)];
    option.title = omission?.reason || "";
  }
  if (elements.solver.selectedOptions[0]?.disabled) {
    const preferred = [...elements.solver.options].find((option) => option.value === "greedy-insertion" && !option.disabled);
    const available = preferred || [...elements.solver.options].find((option) => !option.disabled);
    if (available) elements.solver.value = available.value;
  }
  applyStaticRunConfiguration();
}

function setBusy(busy, message) {
  elements.button.disabled = busy;
  if (staticDeployment) {
    elements.button.firstChild.textContent = busy ? "Loading reference run " : "Load reference run ";
  } else {
    elements.button.firstChild.textContent = busy ? "Evaluating solver " : "Evaluate solver ";
  }
  elements.status.classList.remove("error");
  elements.status.textContent = message;
}

function displayReason(value) {
  return String(value || "not reported").replaceAll("_", " ");
}

function methodVariant(solverName) {
  if (solverName === "q-learning") return "hybrid";
  if (solverName === "q-policy-only") return "pure policy";
  return "";
}

function methodLabel(solverName) {
  const variant = methodVariant(solverName);
  return variant ? `${solverName} (${variant})` : solverName;
}

function runMetadata(payload) {
  const scheduleMetadata = payload.result.schedule.metadata || {};
  return {
    seed: payload.run_metadata?.seed ?? payload.result.schedule.seed ?? Number(elements.seed.value),
    evaluation_budget: payload.run_metadata?.evaluation_budget
      ?? scheduleMetadata.evaluation_budget
      ?? Number(elements.budget.value),
    evaluations: payload.run_metadata?.evaluations
      ?? scheduleMetadata.evaluations
      ?? scheduleMetadata.nodes_expanded
      ?? null,
    stop_reason: payload.run_metadata?.stop_reason
      ?? scheduleMetadata.stop_reason
      ?? (scheduleMetadata.optimality_proven ? "optimality_proven" : "method_completed"),
    source_revision: payload.run_metadata?.source_revision
      ?? state.staticDataset?.metadata?.source_revision
      ?? "local working tree",
    software_version: payload.run_metadata?.software_version
      ?? state.staticDataset?.metadata?.software_version
      ?? "local",
    budget_profile: payload.run_metadata?.budget_profile ?? "requested",
  };
}

function appendCell(row, text, className = "") {
  const cell = document.createElement("td");
  cell.textContent = text;
  if (className) cell.className = className;
  row.append(cell);
  return cell;
}

function renderComparison(scenarioId, focusedSolver) {
  const entries = [];
  if (staticDeployment && state.staticDataset) {
    state.solvers.forEach((solver) => {
      const key = runKey(scenarioId, solver.solver_name);
      entries.push({
        solver,
        payload: state.staticDataset.runs[key] || null,
        omission: state.staticDataset.omissions?.[key] || null,
      });
    });
  } else {
    state.solvers.forEach((solver) => {
      const payload = state.runCache.get(runKey(scenarioId, solver.solver_name));
      if (payload) entries.push({ solver, payload, omission: null });
    });
  }

  entries.sort((left, right) => {
    if (!left.payload) return right.payload ? 1 : 0;
    if (!right.payload) return -1;
    return right.payload.result.metrics.total_value - left.payload.result.metrics.total_value
      || left.solver.solver_name.localeCompare(right.solver.solver_name);
  });

  const rows = entries.map(({ solver, payload, omission }) => {
    const row = document.createElement("tr");
    if (solver.solver_name === focusedSolver) row.classList.add("is-focused");
    const methodCell = appendCell(row, solver.solver_name, "method-name");
    const category = document.createElement("small");
    const variant = methodVariant(solver.solver_name);
    category.textContent = variant ? `${solver.category} · ${variant}` : solver.category;
    methodCell.append(category);
    if (!payload) {
      row.classList.add("is-omitted");
      const reason = document.createElement("td");
      reason.colSpan = 8;
      reason.textContent = omission?.reason || "Not evaluated in this local session.";
      row.append(reason);
      return row;
    }

    const { result, scenario } = payload;
    const metadata = runMetadata(payload);
    const completion = `${result.metrics.completed_tasks}/${scenario.tasks.length}`;
    appendCell(row, result.metrics.total_value.toFixed(1), "numeric");
    appendCell(row, completion, "numeric");
    appendCell(row, `${result.metrics.total_slew_time_s.toFixed(1)} s`, "numeric");
    appendCell(row, result.validation.is_feasible ? "PASS" : "FAIL", result.validation.is_feasible ? "pass" : "fail");
    appendCell(row, `${(result.runtime_s * 1000).toFixed(1)} ms`, "numeric");
    appendCell(row, metadata.evaluations === null ? "—" : String(metadata.evaluations), "numeric");
    appendCell(row, displayReason(metadata.stop_reason));
    appendCell(row, `${metadata.seed} / ${metadata.evaluation_budget}`, "numeric");
    return row;
  });
  elements.comparisonBody.replaceChildren(...rows);

  const availableCount = entries.filter((entry) => entry.payload).length;
  const omittedCount = entries.length - availableCount;
  elements.comparisonContext.textContent = staticDeployment
    ? `${availableCount} reference methods · ${omittedCount} documented omissions`
    : `${availableCount} method${availableCount === 1 ? "" : "s"} evaluated in this session`;
  elements.comparisonNote.textContent = staticDeployment
    ? "Runtime is descriptive. Large stochastic cases use the recorded reduced Pages budget; omissions and every actual seed/budget remain explicit. Evaluation units differ by method family."
    : "Evaluate additional methods to extend this within-session comparison. Evaluation units differ by method family and do not imply equal computational work.";
}

function fallbackAudit(scenario, result) {
  const simulation = result.validation.simulation;
  const scheduledIds = new Set((simulation?.tasks || []).map((task) => task.task_id));
  const minimumEnergy = Math.min(
    scenario.satellite.initial_energy_wh,
    ...(simulation?.tasks || []).map((task) => task.energy_after_wh),
  );
  const finalStorage = simulation?.final_state?.storage_gb ?? scenario.satellite.initial_storage_gb;
  return {
    methodology: "Local-session fallback: exclusions report solver termination, while validator issues and resource margins come from deterministic replay.",
    summary: {
      scheduled_tasks: scheduledIds.size,
      unscheduled_tasks: scenario.tasks.length - scheduledIds.size,
      validation_issues: result.validation.issues.length,
      minimum_energy_wh: minimumEnergy,
      storage_remaining_gb: Math.max(0, scenario.satellite.storage_capacity_gb - finalStorage),
    },
    issues: result.validation.issues,
    unscheduled: scenario.tasks
      .filter((task) => !scheduledIds.has(task.task_id))
      .map((task) => ({
        task_id: task.task_id,
        target_name: task.target.name,
        reason_code: "solver_termination",
        reason: `Not selected before ${displayReason(result.schedule.metadata.stop_reason || "method completion")}.`,
      })),
  };
}

function auditItem(title, code, description, itemClass = "") {
  const item = document.createElement("li");
  if (itemClass) item.className = itemClass;
  const heading = document.createElement("p");
  const strong = document.createElement("strong");
  strong.textContent = title;
  const tag = document.createElement("code");
  tag.textContent = code;
  heading.append(strong, tag);
  const detail = document.createElement("span");
  detail.textContent = description;
  item.append(heading, detail);
  return item;
}

function renderConstraintAudit(scenario, result, auditPayload) {
  const audit = auditPayload || fallbackAudit(scenario, result);
  const summary = audit.summary;
  elements.auditSummary.textContent = `${summary.scheduled_tasks} scheduled · ${summary.unscheduled_tasks} unscheduled · ${summary.validation_issues} validator issues`;

  const unscheduledItems = audit.unscheduled.map((item) => auditItem(
    `${item.target_name} · ${item.task_id}`,
    displayReason(item.reason_code),
    item.reason,
  ));
  if (!unscheduledItems.length) {
    unscheduledItems.push(auditItem(
      "All candidate targets scheduled",
      "complete",
      "No target requires an exclusion diagnosis for this incumbent.",
      "audit-pass",
    ));
  }
  elements.unscheduledList.replaceChildren(...unscheduledItems);

  const validationItems = [
    auditItem(
      "Minimum post-task energy",
      "energy margin",
      `${summary.minimum_energy_wh.toFixed(2)} Wh remained at the tightest recorded point.`,
      "audit-margin",
    ),
    auditItem(
      "Final storage headroom",
      "storage margin",
      `${summary.storage_remaining_gb.toFixed(2)} GB remained after replay.`,
      "audit-margin",
    ),
  ];
  audit.issues.forEach((issue) => {
    validationItems.push(auditItem(
      issue.task_id ? `${issue.task_id} · ${issue.severity}` : issue.severity,
      issue.code,
      issue.message,
      issue.severity === "error" ? "audit-error" : "audit-warning",
    ));
  });
  if (!audit.issues.length) {
    validationItems.push(auditItem(
      "Independent replay passed",
      "no issues",
      "The shared simulator reported no validation warnings or errors.",
      "audit-pass",
    ));
  }
  elements.validationList.replaceChildren(...validationItems);
  elements.auditMethodology.textContent = audit.methodology;
}

function renderProvenance(payload) {
  const metadata = runMetadata(payload);
  const revision = String(metadata.source_revision);
  elements.recordScenario.textContent = payload.scenario.scenario_id;
  elements.recordMethod.textContent = methodLabel(payload.result.schedule.solver_name);
  elements.recordSeed.textContent = String(metadata.seed);
  elements.recordBudget.textContent = `${metadata.evaluation_budget} · ${metadata.budget_profile}`;
  elements.recordRevision.textContent = revision.length > 12 ? revision.slice(0, 12) : revision;
  elements.recordRevision.title = `${revision} · OrbitOps ${metadata.software_version}`;
}

function renderGantt(scenario, result) {
  const simulation = result.validation.simulation;
  const scheduled = new Map((simulation?.tasks || []).map((task) => [task.task_id, task]));
  const width = 1180;
  const left = 212;
  const right = 42;
  const top = 36;
  const rowHeight = 58;
  const bottom = 40;
  const height = top + scenario.tasks.length * rowHeight + bottom;
  const plotWidth = width - left - right;
  const horizon = scenario.horizon_end_s - scenario.horizon_start_s;
  const x = (value) => left + ((value - scenario.horizon_start_s) / horizon) * plotWidth;
  const root = chart(
    width,
    height,
    "Mission Gantt chart",
    `${scenario.tasks.length} targets with visibility windows, scheduled observations, and slew intervals.`,
  );

  for (let tick = 0; tick <= 6; tick += 1) {
    const fraction = tick / 6;
    const value = scenario.horizon_start_s + horizon * fraction;
    const tickX = x(value);
    root.append(svgElement("line", {
      x1: tickX,
      y1: top - 12,
      x2: tickX,
      y2: height - bottom + 2,
      class: tick === 0 || tick === 6 ? "chart-grid-strong" : "chart-grid",
    }));
    root.append(svgElement("text", {
      x: tickX,
      y: height - 12,
      "text-anchor": "middle",
      class: "chart-axis",
    }, `${Math.round(value / 60)}m`));
  }

  scenario.tasks.forEach((task, index) => {
    const rowY = top + index * rowHeight;
    if (index % 2 === 0) {
      root.append(svgElement("rect", {
        x: 0,
        y: rowY,
        width,
        height: rowHeight,
        rx: 9,
        class: "row-band",
      }));
    }
    root.append(svgElement("text", {
      x: left - 16,
      y: rowY + 23,
      "text-anchor": "end",
      class: "task-label",
    }, task.target.name));
    root.append(svgElement("text", {
      x: left - 16,
      y: rowY + 40,
      "text-anchor": "end",
      class: "task-sublabel",
    }, `${task.task_id} · P${task.priority_value.toFixed(0)}`));

    task.visibility_windows.forEach((window) => {
      const bar = svgElement("rect", {
        x: x(window.start_s),
        y: rowY + 17,
        width: Math.max(2, x(window.end_s) - x(window.start_s)),
        height: 24,
        rx: 7,
        class: "window-bar",
      });
      bar.append(svgElement("title", {}, `${window.window_id}: ${window.start_s.toFixed(0)}–${window.end_s.toFixed(0)}s visibility`));
      root.append(bar);
    });

    const assignment = scheduled.get(task.task_id);
    if (!assignment) {
      root.append(svgElement("circle", {
        cx: width - right + 15,
        cy: rowY + 29,
        r: 3,
        class: "unscheduled-dot",
      }));
      return;
    }
    if (assignment.slew_time_s > 0) {
      const slewStart = Math.max(scenario.horizon_start_s, assignment.start_s - assignment.slew_time_s);
      const slew = svgElement("rect", {
        x: x(slewStart),
        y: rowY + 26,
        width: Math.max(2, x(assignment.start_s) - x(slewStart)),
        height: 7,
        rx: 3.5,
        class: "slew-bar",
      });
      slew.append(svgElement("title", {}, `Slew ${assignment.slew_time_s.toFixed(1)} seconds`));
      root.append(slew);
    }
    const observation = svgElement("rect", {
      x: x(assignment.start_s),
      y: rowY + 20,
      width: Math.max(3, x(assignment.end_s) - x(assignment.start_s)),
      height: 18,
      rx: 5,
      class: "task-bar",
    });
    observation.append(svgElement("title", {}, `${task.target.name}: ${assignment.start_s.toFixed(1)}–${assignment.end_s.toFixed(1)}s · ${assignment.window_id}`));
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
  const height = 320;
  const dimensions = { left: 54, top: 28, plotWidth: 548, plotHeight: 225 };
  const horizon = scenario.horizon_end_s - scenario.horizon_start_s;
  const x = (value) => dimensions.left + ((value - scenario.horizon_start_s) / horizon) * dimensions.plotWidth;
  const y = (value) => dimensions.top + (1 - value / 100) * dimensions.plotHeight;
  const root = chart(width, height, "Resource envelope", "Energy remaining and storage used as percentages of capacity.");

  const definitions = svgElement("defs");
  const gradient = svgElement("linearGradient", { id: "energy-gradient", x1: "0", y1: "0", x2: "0", y2: "1" });
  gradient.append(
    svgElement("stop", { offset: "0%", "stop-color": "#8d6bb8", "stop-opacity": "0.22" }),
    svgElement("stop", { offset: "100%", "stop-color": "#8d6bb8", "stop-opacity": "0" }),
  );
  definitions.append(gradient);
  root.append(definitions);

  [0, 0.5, 1].forEach((fraction) => {
    const gridY = y(fraction * 100);
    root.append(svgElement("line", { x1: dimensions.left, y1: gridY, x2: dimensions.left + dimensions.plotWidth, y2: gridY, class: "chart-grid" }));
    root.append(svgElement("text", { x: dimensions.left - 10, y: gridY + 4, "text-anchor": "end", class: "chart-axis" }, `${fraction * 100}%`));
  });
  [0, 0.5, 1].forEach((fraction) => {
    const value = scenario.horizon_start_s + horizon * fraction;
    root.append(svgElement("text", { x: x(value), y: height - 18, "text-anchor": "middle", class: "chart-axis" }, `${Math.round(value / 60)}m`));
  });

  const area = [
    `${x(energy[0].x)},${y(0)}`,
    ...energy.map((point) => `${x(point.x)},${y(point.y)}`),
    `${x(energy.at(-1).x)},${y(0)}`,
  ].join(" ");
  root.append(svgElement("polygon", { points: area, class: "energy-area" }));
  root.append(svgElement("polyline", { points: seriesPoints(energy, x, y), class: "energy-line" }));
  root.append(svgElement("polyline", { points: seriesPoints(storage, x, y), class: "storage-line" }));
  const energyFinal = energy.at(-1);
  const storageFinal = storage.at(-1);
  root.append(svgElement("text", { x: dimensions.left, y: 17, class: "chart-panel-label" }, "Capacity utilization"));
  root.append(svgElement("text", { x: x(energyFinal.x) - 6, y: y(energyFinal.y) - 10, "text-anchor": "end", class: "chart-title-label" }, `Energy ${energyFinal.y.toFixed(0)}%`));
  root.append(svgElement("text", { x: x(storageFinal.x) - 6, y: y(storageFinal.y) - 10, "text-anchor": "end", class: "chart-title-label" }, `Storage ${storageFinal.y.toFixed(0)}%`));
  elements.resources.replaceChildren(root);
}

function renderConvergence(points) {
  elements.learningKicker.textContent = "Search diagnostics";
  elements.learningTitle.textContent = "Convergence trace";
  elements.learningLegend.replaceChildren(...legendItems([["objective", "Incumbent objective"]]));
  if (!points.length) {
    emptyChart(elements.learning, "This solver did not publish a convergence trace.");
    return;
  }
  const width = 650;
  const height = 320;
  const dimensions = { left: 56, top: 28, plotWidth: 544, plotHeight: 225 };
  const maxEvaluation = Math.max(1, ...points.map((point) => point.evaluation));
  const maxValue = Math.max(1, ...points.map((point) => point.total_value));
  const x = (value) => dimensions.left + (value / maxEvaluation) * dimensions.plotWidth;
  const y = (value) => dimensions.top + (1 - value / maxValue) * dimensions.plotHeight;
  const root = chart(width, height, "Search convergence", "Incumbent objective value by unique solution evaluation.");
  [0, 0.5, 1].forEach((fraction) => {
    const gridY = y(maxValue * fraction);
    root.append(svgElement("line", { x1: dimensions.left, y1: gridY, x2: dimensions.left + dimensions.plotWidth, y2: gridY, class: "chart-grid" }));
    root.append(svgElement("text", { x: dimensions.left - 10, y: gridY + 4, "text-anchor": "end", class: "chart-axis" }, `${Math.round(maxValue * fraction)}`));
    root.append(svgElement("text", { x: x(maxEvaluation * fraction), y: height - 18, "text-anchor": "middle", class: "chart-axis" }, `${Math.round(maxEvaluation * fraction)}`));
  });
  const series = points.map((point) => ({ x: point.evaluation, y: point.total_value }));
  root.append(svgElement("polyline", { points: seriesPoints(series, x, y), class: "convergence-line" }));
  series.forEach((point) => root.append(svgElement("circle", { cx: x(point.x), cy: y(point.y), r: 4, class: "chart-point" })));
  root.append(svgElement("text", { x: dimensions.left, y: 17, class: "chart-panel-label" }, "Objective by evaluation"));
  elements.learning.replaceChildren(root);
}

function renderTraining(trace) {
  elements.learningKicker.textContent = "Learning diagnostics";
  elements.learningTitle.textContent = "Training curves";
  elements.learningLegend.replaceChildren(...legendItems([
    ["objective", "Episode schedule objective"],
    ["epsilon", "Epsilon"],
    ["td-error", "Mean |TD|"],
  ]));
  if (!trace.length) {
    emptyChart(elements.learning, "Training trace is unavailable for this run.");
    return;
  }
  const points = sampleSeries(trace);
  const width = 650;
  const height = 340;
  const left = 56;
  const plotWidth = 544;
  const topY = 29;
  const topHeight = 128;
  const lowerY = 207;
  const lowerHeight = 72;
  const maxEpisode = Math.max(1, ...points.map((point) => point.episode));
  const maxValue = Math.max(1, ...points.map((point) => point.total_value));
  const maxTd = Math.max(1e-12, ...points.map((point) => point.mean_abs_td_error));
  const x = (value) => left + (value / maxEpisode) * plotWidth;
  const yValue = (value) => topY + (1 - value / maxValue) * topHeight;
  const yDiagnostic = (value) => lowerY + (1 - value) * lowerHeight;
  const root = chart(width, height, "Q-learning training curves", "Realized exploratory episode schedule objective, epsilon exploration schedule, and normalized mean absolute temporal-difference error by episode.");

  [0, 0.5, 1].forEach((fraction) => {
    const objectiveY = yValue(maxValue * fraction);
    const diagnosticY = yDiagnostic(fraction);
    root.append(svgElement("line", { x1: left, y1: objectiveY, x2: left + plotWidth, y2: objectiveY, class: "chart-grid" }));
    root.append(svgElement("text", { x: left - 10, y: objectiveY + 4, "text-anchor": "end", class: "chart-axis" }, `${Math.round(maxValue * fraction)}`));
    root.append(svgElement("line", { x1: left, y1: diagnosticY, x2: left + plotWidth, y2: diagnosticY, class: "chart-grid" }));
    root.append(svgElement("text", { x: left - 10, y: diagnosticY + 4, "text-anchor": "end", class: "chart-axis" }, fraction.toFixed(1)));
    root.append(svgElement("text", { x: x(maxEpisode * fraction), y: height - 17, "text-anchor": "middle", class: "chart-axis" }, `${Math.round(maxEpisode * fraction)}`));
  });
  root.append(svgElement("text", { x: left, y: 17, class: "chart-panel-label" }, "Episode schedule objective"));
  root.append(svgElement("text", { x: left, y: lowerY - 13, class: "chart-panel-label" }, "Exploration / normalized TD error"));
  root.append(svgElement("text", { x: left + plotWidth, y: height - 17, "text-anchor": "end", class: "chart-panel-label" }, "Episode"));

  const objective = points.map((point) => ({ x: point.episode, y: point.total_value }));
  const epsilon = points.map((point) => ({ x: point.episode, y: point.epsilon }));
  const td = points.map((point) => ({ x: point.episode, y: point.mean_abs_td_error / maxTd }));
  root.append(svgElement("polyline", { points: seriesPoints(objective, x, yValue), class: "objective-line" }));
  root.append(svgElement("polyline", { points: seriesPoints(epsilon, x, yDiagnostic), class: "epsilon-line" }));
  root.append(svgElement("polyline", { points: seriesPoints(td, x, yDiagnostic), class: "td-line" }));
  elements.learning.replaceChildren(root);
}

function wrapLongitude(value) {
  return ((value + 540) % 360) - 180;
}

function circularLongitudeCenter(tasks) {
  if (!tasks.length) return 0;
  const vector = tasks.reduce((total, task) => {
    const radians = (task.target.longitude_deg * Math.PI) / 180;
    return {
      x: total.x + Math.cos(radians),
      y: total.y + Math.sin(radians),
    };
  }, { x: 0, y: 0 });
  if (Math.abs(vector.x) < 1e-12 && Math.abs(vector.y) < 1e-12) return 0;
  return (Math.atan2(vector.y, vector.x) * 180) / Math.PI;
}

function renderGlobeFallback(scenario, scheduledIds) {
  const globe = document.createElement("div");
  globe.className = "fallback-globe";
  const core = document.createElement("span");
  core.className = "fallback-globe-core";
  globe.append(core);
  const longitudeCenter = circularLongitudeCenter(scenario.tasks);
  const longitudeSpan = Math.max(
    24,
    ...scenario.tasks.map((task) => Math.abs(wrapLongitude(task.target.longitude_deg - longitudeCenter))),
  );
  scenario.tasks.forEach((task) => {
    const marker = document.createElement("span");
    marker.className = scheduledIds.has(task.task_id) ? "fallback-marker is-scheduled" : "fallback-marker";
    const longitudeOffset = wrapLongitude(task.target.longitude_deg - longitudeCenter);
    marker.style.setProperty("--marker-x", `${50 + (longitudeOffset / longitudeSpan) * 34}%`);
    marker.style.setProperty("--marker-y", `${50 - (task.target.latitude_deg / 90) * 34}%`);
    marker.title = task.target.name;
    globe.append(marker);
  });
  elements.globe.replaceChildren(globe);
  elements.globeLoading.firstElementChild?.remove();
  elements.globeLoading.lastElementChild.textContent = "Static mission geometry · 3D engine unavailable";
}

function notionalGroundTrack(Cesium, longitudeCenter) {
  const coordinates = [];
  for (let index = 0; index <= 180; index += 1) {
    const phase = (index / 180) * Math.PI * 2;
    const longitude = ((longitudeCenter - 160 + index * 2 + 540) % 360) - 180;
    const latitude = 68 * Math.sin(phase);
    coordinates.push(longitude, latitude, 560000);
  }
  return Cesium.Cartesian3.fromDegreesArrayHeights(coordinates);
}

function naturalEarthLayer(Cesium) {
  const provider = new Cesium.UrlTemplateImageryProvider({
    url: `${Cesium.buildModuleUrl("Assets/Textures/NaturalEarthII")}/{z}/{x}/{reverseY}.jpg`,
    tilingScheme: new Cesium.GeographicTilingScheme(),
    maximumLevel: 5,
    credit: new Cesium.Credit("Natural Earth II · CesiumJS"),
  });
  return new Cesium.ImageryLayer(provider, {
    brightness: 1.08,
    contrast: 1.08,
    saturation: 1.08,
    gamma: 1.04,
  });
}

function nasaBlueMarbleLayer(Cesium) {
  const provider = new Cesium.UrlTemplateImageryProvider({
    url: "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg",
    tilingScheme: new Cesium.WebMercatorTilingScheme(),
    maximumLevel: 8,
    credit: new Cesium.Credit("NASA Earth Observatory · GIBS"),
  });
  return new Cesium.ImageryLayer(provider, {
    brightness: 1.18,
    contrast: 1.08,
    saturation: 1.12,
    gamma: 1.08,
  });
}

function renderMissionGlobe(scenario, result) {
  const scheduledTasks = result.validation.simulation?.tasks || [];
  const scheduledIds = new Set(scheduledTasks.map((task) => task.task_id));
  elements.globeTargets.textContent = `${scenario.tasks.length} targets`;
  elements.globeSequence.textContent = `${scheduledIds.size} selected · ${scenario.satellite.satellite_id}`;
  elements.globe.setAttribute("aria-label", `Interactive WGS84 globe with ${scenario.tasks.length} mission targets, ${scheduledIds.size} scheduled.`);

  const Cesium = window.Cesium;
  if (!Cesium) {
    renderGlobeFallback(scenario, scheduledIds);
    return;
  }
  try {
    if (!state.globe) {
      const primaryImagery = nasaBlueMarbleLayer(Cesium);
      state.globe = new Cesium.Viewer("mission-globe", {
        animation: false,
        baseLayer: primaryImagery,
        baseLayerPicker: false,
        fullscreenButton: false,
        geocoder: false,
        homeButton: false,
        infoBox: false,
        navigationHelpButton: false,
        scene3DOnly: true,
        sceneModePicker: false,
        selectionIndicator: false,
        timeline: false,
        shouldAnimate: false,
        requestRenderMode: true,
      });
      primaryImagery.imageryProvider.errorEvent.addEventListener(() => {
        if (!state.imageryFallbackActive && state.globe) {
          state.globe.imageryLayers.add(naturalEarthLayer(Cesium), 0);
          state.imageryFallbackActive = true;
          elements.globe.dataset.imagerySource = "natural-earth-fallback";
        }
      });
      elements.globe.dataset.imagerySource = "nasa-blue-marble";
      let imageryRequestsObserved = false;
      state.globe.scene.globe.tileLoadProgressEvent.addEventListener((pendingRequests) => {
        if (pendingRequests > 0) imageryRequestsObserved = true;
        if (imageryRequestsObserved && pendingRequests === 0) {
          elements.globe.dataset.imageryReady = "true";
        }
      });
      state.globe.scene.backgroundColor = Cesium.Color.fromCssColorString("#211b2a");
      state.globe.scene.globe.baseColor = Cesium.Color.fromCssColorString("#263a49");
      state.globe.scene.globe.enableLighting = false;
      state.globe.scene.globe.showGroundAtmosphere = true;
      state.globe.scene.skyBox.show = false;
      state.globe.scene.sun.show = false;
      state.globe.scene.moon.show = false;
      state.globe.resolutionScale = Math.min(1.25, window.devicePixelRatio || 1);
    }

    const viewer = state.globe;
    viewer.entities.removeAll();
    const longitudeCenter = circularLongitudeCenter(scenario.tasks);
    const latitudeCenter = scenario.tasks.length
      ? scenario.tasks.reduce((sum, task) => sum + task.target.latitude_deg, 0) / scenario.tasks.length
      : 0;
    const scheduledColor = Cesium.Color.fromCssColorString("#d6a9e9");
    const candidateColor = Cesium.Color.fromCssColorString("#d99066");
    const targetPositions = [];

    viewer.entities.add({
      polyline: {
        positions: notionalGroundTrack(Cesium, longitudeCenter),
        width: 1.5,
        material: new Cesium.PolylineDashMaterialProperty({
          color: Cesium.Color.fromCssColorString("#b9a3c8").withAlpha(0.48),
          dashLength: 14,
        }),
      },
    });

    scenario.tasks.forEach((task, index) => {
      const selected = scheduledIds.has(task.task_id);
      const color = selected ? scheduledColor : candidateColor;
      const position = Cesium.Cartesian3.fromDegrees(task.target.longitude_deg, task.target.latitude_deg, 18000);
      targetPositions.push(position);
      viewer.entities.add({
        id: `target-${task.task_id}`,
        name: task.target.name,
        position,
        point: {
          pixelSize: selected ? 11 : 8,
          color,
          outlineColor: Cesium.Color.WHITE.withAlpha(0.76),
          outlineWidth: 1,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        label: {
          show: selected || scenario.tasks.length <= 12,
          text: task.target.name.toUpperCase(),
          font: "600 11px sans-serif",
          fillColor: Cesium.Color.WHITE.withAlpha(0.88),
          outlineColor: Cesium.Color.fromCssColorString("#211b2a"),
          outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(((index % 3) - 1) * 18, -22 - (index % 4) * 10),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        ellipse: {
          semiMajorAxis: selected ? 68000 : 44000,
          semiMinorAxis: selected ? 68000 : 44000,
          material: color.withAlpha(selected ? 0.16 : 0.08),
          outline: true,
          outlineColor: color.withAlpha(0.5),
          height: 0,
        },
      });
    });

    const taskById = new Map(scenario.tasks.map((task) => [task.task_id, task]));
    const sequenceCoordinates = [];
    scheduledTasks.forEach((assignment) => {
      const task = taskById.get(assignment.task_id);
      if (task) sequenceCoordinates.push(task.target.longitude_deg, task.target.latitude_deg, 70000);
    });
    if (sequenceCoordinates.length >= 6) {
      viewer.entities.add({
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArrayHeights(sequenceCoordinates),
          width: 3,
          material: new Cesium.PolylineGlowMaterialProperty({
            color: scheduledColor.withAlpha(0.78),
            glowPower: 0.16,
          }),
          arcType: Cesium.ArcType.GEODESIC,
        },
      });
    }

    const satelliteLongitude = wrapLongitude(longitudeCenter - 8);
    const satelliteLatitude = Math.min(72, latitudeCenter + 23);
    const satellitePosition = Cesium.Cartesian3.fromDegrees(satelliteLongitude, satelliteLatitude, 680000);
    viewer.entities.add({
      id: "mission-satellite",
      position: satellitePosition,
      point: {
        pixelSize: 10,
        color: Cesium.Color.fromCssColorString("#fff3e9"),
        outlineColor: scheduledColor,
        outlineWidth: 3,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: scenario.satellite.satellite_id.toUpperCase(),
        font: "700 11px sans-serif",
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.fromCssColorString("#211b2a"),
        outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -23),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });

    const firstScheduled = taskById.get(scheduledTasks[0]?.task_id);
    if (firstScheduled) {
      viewer.entities.add({
        polyline: {
          positions: [
            satellitePosition,
            Cesium.Cartesian3.fromDegrees(firstScheduled.target.longitude_deg, firstScheduled.target.latitude_deg, 0),
          ],
          width: 1.5,
          material: new Cesium.PolylineDashMaterialProperty({ color: candidateColor.withAlpha(0.72), dashLength: 10 }),
        },
      });
    }

    const missionCenter = targetPositions.length
      ? Cesium.BoundingSphere.fromPoints(targetPositions)
      : new Cesium.BoundingSphere(Cesium.Cartesian3.fromDegrees(longitudeCenter, latitudeCenter, 0), 250000);
    const cameraRange = Math.min(18000000, Math.max(1400000, missionCenter.radius * 2.75));
    viewer.camera.flyToBoundingSphere(missionCenter, {
      duration: 0,
      offset: new Cesium.HeadingPitchRange(
        Cesium.Math.toRadians(-18),
        Cesium.Math.toRadians(-68),
        cameraRange,
      ),
    });
    viewer.scene.requestRender();
    elements.globeLoading.classList.add("is-hidden");
  } catch (error) {
    console.warn("Cesium mission view unavailable", error);
    state.globe = null;
    state.imageryFallbackActive = false;
    renderGlobeFallback(scenario, scheduledIds);
  }
}

function renderResult(payload) {
  const { scenario, result, convergence } = payload;
  const trainingTrace = result.schedule.metadata.training_trace;
  state.runCache.set(runKey(scenario.scenario_id, result.schedule.solver_name), payload);
  elements.value.textContent = result.metrics.total_value.toFixed(1);
  elements.tasks.textContent = `${result.metrics.completed_tasks}/${scenario.tasks.length}`;
  elements.taskContext.textContent = `${((result.metrics.completed_tasks / Math.max(1, scenario.tasks.length)) * 100).toFixed(0)}% of candidate targets`;
  elements.slew.textContent = `${result.metrics.total_slew_time_s.toFixed(1)}s`;
  elements.feasible.textContent = result.validation.is_feasible ? "PASS" : "FAIL";
  const timingNote = staticDeployment ? " · recorded at build" : "";
  elements.runtime.textContent = `${result.schedule.solver_name} · ${(result.runtime_s * 1000).toFixed(1)} ms${timingNote}`;
  renderProvenance(payload);
  renderComparison(scenario.scenario_id, result.schedule.solver_name);
  renderConstraintAudit(scenario, result, payload.constraint_audit);
  renderMissionGlobe(scenario, result);
  renderGantt(scenario, result);
  renderResources(scenario, result);
  if (Array.isArray(trainingTrace) && trainingTrace.length) renderTraining(trainingTrace);
  else renderConvergence(convergence);
  elements.results.hidden = false;
}

async function runSolve() {
  const progressMessage = staticDeployment
    ? "Loading the precomputed reproducibility artifact…"
    : "Evaluating the solver and replaying the resulting schedule…";
  setBusy(true, progressMessage);
  try {
    const request = {
      scenario_id: elements.scenario.value,
      solver_name: elements.solver.value,
      seed: Number(elements.seed.value),
      evaluation_budget: Number(elements.budget.value),
    };
    const payload = await api("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    if (!payload.run_metadata) {
      payload.run_metadata = {
        seed: request.seed,
        evaluation_budget: request.evaluation_budget,
        budget_profile: "requested",
        source_revision: "local working tree",
        software_version: "local",
      };
    }
    renderResult(payload);
    elements.status.textContent = staticDeployment
      ? "Precomputed run loaded · feasibility and diagnostic artifacts were generated by the shared simulator."
      : "Schedule replay completed · the shared simulator produced the feasibility verdict and diagnostics.";
  } catch (error) {
    elements.status.classList.add("error");
    elements.status.textContent = error instanceof Error ? error.message : "The run failed.";
  } finally {
    elements.button.disabled = false;
    elements.button.firstChild.textContent = staticDeployment ? "Load reference run " : "Evaluate solver ";
  }
}

async function initialize() {
  try {
    const [scenarioPayload, solverPayload] = await Promise.all([api("/api/scenarios"), api("/api/solvers")]);
    state.scenarios = scenarioPayload.scenarios;
    state.solvers = solverPayload.solvers;
    populateSelect(elements.scenario, state.scenarios, "scenario_id", (item) => item.name);
    populateSelect(
      elements.solver,
      state.solvers,
      "solver_name",
      (item) => `${methodLabel(item.solver_name)} · ${item.category}`,
    );
    elements.solver.value = "q-learning";
    if (staticDeployment) {
      const dataset = await loadStaticDataset();
      elements.seed.value = dataset.metadata.seed;
      elements.budget.value = dataset.metadata.evaluation_budget;
      elements.seed.disabled = true;
      elements.budget.disabled = true;
      elements.deploymentMode.textContent = "GitHub Pages · precomputed runs";
      elements.button.firstChild.textContent = "Load reference run ";
    }
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
elements.solver.addEventListener("change", applyStaticRunConfiguration);
initialize();
