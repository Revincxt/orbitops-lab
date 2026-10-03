"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const state = {
  scenarios: [],
  solvers: [],
  localSolvers: [],
  referenceData: null,
  globe: null,
  imageryFallbackActive: false,
  staticDataset: null,
  runCache: new Map(),
  currentPayload: null,
  selectedTaskId: null,
  busy: false,
  pages: {},
  layers: { targets: true, track: true, rays: true, labels: false, satelliteLabels: true },
  cameraHome: null,
  lastRequest: null,
  assignments: new Map(),
  taskById: new Map(),
  replay: { time: 0, playing: false, speed: 60, lastFrame: 0, lastPaint: 0 },
  orbitPositions: new Map(),
  orbitStyles: new Map(),
  entityTaskStates: new Map(),
  selectedSatelliteId: null,
  geometrySelectionKey: null,
  cameraMode: "overview",
  orbitEmphasis: false,
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
  shell: document.querySelector(".shell"),
  runLabel: document.getElementById("run-label"),
  statusIndicator: document.getElementById("status-indicator"),
  pending: document.getElementById("pending-state"),
  targetList: document.getElementById("target-list"),
  validationBadge: document.getElementById("validation-badge"),
  export: document.getElementById("export-run"),
};

function textField(id, value) {
  const node = document.getElementById(id);
  node.textContent = value;
  node.title = String(value);
}

function pageItems(name, items, size) {
  const pageSize = Math.max(1, size);
  const lastPage = Math.max(0, Math.ceil(items.length / pageSize) - 1);
  const page = Math.min(lastPage, Math.max(0, state.pages[name] || 0));
  state.pages[name] = page;
  const start = page * pageSize;
  textField(`${name}-range`, items.length ? `${start + 1}–${Math.min(start + pageSize, items.length)} / ${items.length}` : "0 items");
  document.getElementById(`${name}-prev`).disabled = page === 0;
  document.getElementById(`${name}-next`).disabled = page === lastPage;
  return items.slice(start, start + pageSize);
}

function bindPager(name, render) {
  for (const [direction, delta] of [["prev", -1], ["next", 1]]) {
    document.getElementById(`${name}-${direction}`).addEventListener("click", () => {
      state.pages[name] = (state.pages[name] || 0) + delta;
      render();
    });
  }
}

function activeRequest() {
  if (isReferenceScenario()) return { scenario_id: elements.scenario.value, solver_name: elements.solver.value };
  return {
    scenario_id: elements.scenario.value,
    solver_name: elements.solver.value,
    seed: Number(elements.seed.value),
    evaluation_budget: Number(elements.budget.value),
  };
}

function markConfigurationChanged() {
  const dirty = Boolean(state.lastRequest && JSON.stringify(activeRequest()) !== JSON.stringify(state.lastRequest));
  elements.pending.hidden = !dirty;
  elements.button.dataset.pending = String(dirty);
  const solver = state.solvers.find((item) => item.solver_name === elements.solver.value);
  if (solver) textField("solver-description", solver.category === "reference" ? "Imported plan · original objectives retained" : `${solver.category} · ${solver.stochastic ? "seeded execution" : "deterministic execution"}`);
}

function setPanel(name, open) {
  const key = name === "config" ? "configOpen" : "inspectorOpen";
  elements.shell.dataset[key] = String(open);
  document.getElementById(`toggle-${name}`).setAttribute("aria-expanded", String(open));
  if (open && window.matchMedia("(max-width: 1000px)").matches) {
    const other = name === "config" ? "inspector" : "config";
    const otherKey = other === "config" ? "configOpen" : "inspectorOpen";
    elements.shell.dataset[otherKey] = "false";
    document.getElementById(`toggle-${other}`).setAttribute("aria-expanded", "false");
  }
}

function activateTab(button) {
  const tabs = [...button.closest('[role="tablist"]').querySelectorAll('[role="tab"]')];
  tabs.forEach((tab) => {
    const selected = tab === button;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    document.getElementById(tab.getAttribute("aria-controls")).hidden = !selected;
  });
  refreshPanels();
}

function bindTabs() {
  document.querySelectorAll('[role="tablist"]').forEach((group) => {
    const tabs = [...group.querySelectorAll('[role="tab"]')];
    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => activateTab(tab));
      tab.addEventListener("keydown", (event) => {
        let next;
        if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
        if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
        if (event.key === "Home") next = 0;
        if (event.key === "End") next = tabs.length - 1;
        if (next === undefined) return;
        event.preventDefault();
        activateTab(tabs[next]);
        tabs[next].focus();
      });
    });
  });
}

function renderTargetCatalog() {
  if (!state.currentPayload) return;
  const { scenario, result } = state.currentPayload;
  const assignments = new Map((result.validation.simulation?.tasks || []).map((task) => [task.task_id, task]));
  const capacity = Math.max(1, Math.floor(elements.targetList.clientHeight / 42));
  const filtered = filteredTasks(scenario);
  const tasks = pageItems("target", filtered, capacity);
  textField("target-count", filtered.length === scenario.tasks.length ? scenario.tasks.length : `${filtered.length}/${scenario.tasks.length}`);
  const rows = tasks.map((task) => {
    const scheduled = assignments.has(task.task_id);
    const currentState = taskState(task.task_id);
    const row = document.createElement("button");
    row.type = "button";
    row.className = `target-row${scheduled ? " is-scheduled" : ""}${task.task_id === state.selectedTaskId ? " is-selected" : ""}`;
    row.setAttribute("aria-pressed", String(task.task_id === state.selectedTaskId));
    row.dataset.taskId = task.task_id;
    row.dataset.state = currentState;
    row.title = `${task.target.name} · priority ${task.priority_value} · ${scheduled ? "scheduled" : "unscheduled"}`;
    const dot = document.createElement("span");
    dot.className = "target-dot";
    const name = document.createElement("span");
    name.className = "target-row-name";
    const title = document.createElement("strong");
    title.textContent = task.target.name;
    const detail = document.createElement("small");
    detail.textContent = `${task.task_id} · P${task.priority_value.toFixed(0)} · ${task.visibility_windows.length} windows`;
    name.append(title, detail);
    const status = document.createElement("span");
    status.className = "target-state";
    status.textContent = currentState;
    row.append(dot, name, status);
    row.addEventListener("click", () => selectTarget(task.task_id));
    return row;
  });
  elements.targetList.replaceChildren(...rows);
}

function selectTarget(taskId, reveal = true, seek = reveal) {
  const payload = state.currentPayload;
  if (!payload) return;
  const task = payload.scenario.tasks.find((item) => item.task_id === taskId);
  if (!task) return;
  state.selectedTaskId = taskId;
  const assignment = payload.result.validation.simulation?.tasks.find((item) => item.task_id === taskId);
  if (payload.mode === "reference") {
    state.selectedSatelliteId = assignment?.satellite_id || null;
    if (reveal) state.orbitEmphasis = true;
    if (!assignment && state.cameraMode === "follow") {
      releaseCameraTracking();
      state.cameraMode = "focus";
    }
  }
  if (seek && assignment) setReplayTime(assignment.start_s, true);
  textField("selected-name", task.target.name);
  textField("selected-id", task.task_id);
  textField("selected-coordinates", `${task.target.latitude_deg.toFixed(2)}°, ${task.target.longitude_deg.toFixed(2)}°`);
  textField("selected-priority", `P${task.priority_value.toFixed(0)} / ${task.duration_s.toFixed(1)}s`);
  textField("selected-window", assignment ? `${timeLabel(assignment.start_s)}–${timeLabel(assignment.end_s)}` : "Not scheduled");
  textField("selected-assignment", assignment ? (assignment.satellite_id || payload.scenario.satellite.satellite_id) : `${task.visibility_windows.length} candidate windows`);
  document.getElementById("selected-assignment").title = assignment ? `${assignment.satellite_id || payload.scenario.satellite.satellite_id} · ${assignment.window_id}` : "No selected assignment";
  textField("selected-resource-label", payload.mode === "reference" ? "Source data / orbit" : "Energy / storage");
  textField("selected-resources", payload.mode === "reference" ? (assignment ? `${(assignment.data_volume_gb * 1024).toFixed(2)} MB / #${assignment.orbit_number}` : "No source assignment") : `${task.energy_cost_wh.toFixed(1)} Wh / ${task.storage_cost_gb.toFixed(1)} GB`);
  textField("selected-state", taskState(taskId));
  document.getElementById("selected-state").classList.toggle("scheduled", Boolean(assignment));
  textField("globe-coordinate", `${task.target.latitude_deg.toFixed(2)}° LAT / ${task.target.longitude_deg.toFixed(2)}° LON`);
  if (state.globe && window.Cesium) {
    payload.scenario.tasks.forEach((candidate) => {
      const entity = state.globe.entities.getById(`target-${candidate.task_id}`);
      if (entity?.point) {
        const selected = candidate.task_id === taskId;
        entity.point.pixelSize = selected ? 10 : payload.mode === "reference" ? 4 : 6;
        entity.point.outlineWidth = selected ? 2 : .5;
        if (entity.label) {
          entity.label.show = selected || state.layers.labels;
          entity.label.distanceDisplayCondition = new window.Cesium.DistanceDisplayCondition(0, selected || payload.mode !== "reference" ? Infinity : 3500000);
        }
      }
    });
    state.globe.scene.requestRender();
  }
  document.querySelectorAll(".map-marker").forEach((marker) => marker.classList.toggle("is-selected", marker.dataset.taskId === taskId));
  if (reveal) {
    activateTab(document.getElementById("tab-selection"));
    if (window.matchMedia("(max-width: 1000px)").matches) setPanel("inspector", true);
  }
  if (reveal) {
    if (!filteredTasks(payload.scenario).some((candidate) => candidate.task_id === taskId)) {
      document.getElementById("target-search").value = "";
      document.getElementById("target-filter").value = "all";
      document.getElementById("satellite-filter").value = "all";
    }
    const filtered = filteredTasks(payload.scenario);
    const index = filtered.findIndex((candidate) => candidate.task_id === taskId);
    if (index >= 0) state.pages.target = Math.floor(index / Math.max(1, Math.floor(elements.targetList.clientHeight / 42)));
    const capacity = Math.max(1, Math.floor((elements.timeline.clientHeight - 33) / 29));
    if (payload.mode === "reference" && assignment) {
      const selectedSatellite = document.getElementById("satellite-filter").value;
      const satellites = payload.scenario.satellites.filter((satellite) => selectedSatellite === "all" || selectedSatellite === satellite.satellite_id);
      const lane = satellites.findIndex((satellite) => satellite.satellite_id === assignment.satellite_id);
      if (lane >= 0) state.pages.timeline = Math.floor(lane / capacity);
    } else if (index >= 0) state.pages.timeline = Math.floor(index / capacity);
  }
  renderTargetCatalog();
  if (!document.getElementById("pane-timeline").hidden) renderGantt(payload.scenario, payload.result);
  if (payload.mode === "reference") renderWorkloads();
  updateReplayVisuals();
}

function refreshPanels() {
  const payload = state.currentPayload;
  if (!payload) return;
  renderTargetCatalog();
  if (!document.getElementById("pane-timeline").hidden) renderGantt(payload.scenario, payload.result);
  if (!document.getElementById("pane-comparison").hidden) renderComparison(payload.scenario.scenario_id, payload.result.schedule.solver_name);
  if (!document.getElementById("pane-audit").hidden) renderConstraintAudit(payload.scenario, payload.result, payload.constraint_audit);
  if (!document.getElementById("pane-learning").hidden) {
    if (payload.mode === "reference") { renderSourceDiagnostics(); }
    else {
    const trace = payload.result.schedule.metadata.training_trace;
    if (Array.isArray(trace) && trace.length) renderTraining(trace);
    else renderConvergence(payload.convergence || []);
    }
  }
  if (elements.resources.clientHeight > 0) renderResources(payload.scenario, payload.result);
  state.globe?.resize();
}

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
  if (path === "/api/reference/data") return dataset.reference || null;
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
  const reference = scenario.mode === "reference";
  const solvers = reference ? state.referenceData.plans.map((plan) => ({solver_name: plan.plan_id, label: plan.label, category: "reference", stochastic: false, max_tasks: null})) : state.localSolvers;
  if (state.solvers !== solvers && (!state.solvers.length || state.solvers[0].category !== solvers[0].category || reference)) {
    const previous = elements.solver.value;
    state.solvers = solvers;
    populateSelect(elements.solver, solvers, "solver_name", (item) => item.label || `${methodLabel(item.solver_name)} · ${item.category}`);
    if (solvers.some((item) => item.solver_name === previous)) elements.solver.value = previous;
    else elements.solver.value = reference ? "eos-sa-balanced" : "q-learning";
  }
  elements.seed.disabled = reference || staticDeployment || state.busy;
  elements.budget.disabled = reference || staticDeployment || state.busy;
  elements.runLabel.textContent = reference ? "Load reference plan" : (staticDeployment ? "Load reference run" : "Run evaluation");
  if (reference) {
    elements.seed.value = "";
    elements.budget.value = "";
    elements.seed.placeholder = "Not recorded";
    elements.budget.placeholder = "Not recorded";
    elements.context.textContent = `${scenario.satellite_count} satellites · ${scenario.task_count} tasks · 12 h UTC. Source benchmark; read-only replay, not a local solve.`;
    elements.context.title = elements.context.textContent;
    return;
  }
  if (!elements.seed.value) elements.seed.value = "42";
  if (!elements.budget.value) elements.budget.value = "250";
  elements.seed.placeholder = "";
  elements.budget.placeholder = "";
  const horizon = scenario.horizon_end_s - scenario.horizon_start_s;
  const studyQuestion = scenario.research_question ? ` · ${scenario.research_question}` : "";
  const geometryNote = scenario.geometry_note ? ` ${scenario.geometry_note}` : "";
  elements.context.textContent = `${scenario.task_count} targets · ${(horizon / 60).toFixed(0)} min planning horizon${studyQuestion}${geometryNote}`;
  elements.context.title = elements.context.textContent;
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
  state.busy = busy;
  elements.button.disabled = busy;
  elements.scenario.disabled = busy;
  elements.solver.disabled = busy;
  elements.seed.disabled = busy || staticDeployment || isReferenceScenario();
  elements.budget.disabled = busy || staticDeployment || isReferenceScenario();
  elements.runLabel.textContent = isReferenceScenario() ? (busy ? "Loading plan…" : "Load reference plan") : staticDeployment
    ? (busy ? "Loading reference…" : "Load reference run")
    : (busy ? "Evaluating…" : "Run evaluation");
  elements.results.setAttribute("aria-busy", String(busy));
  elements.statusIndicator.classList.toggle("is-busy", busy);
  elements.statusIndicator.classList.remove("is-error");
  elements.status.classList.remove("error");
  if (message) elements.status.textContent = message;
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
  cell.title = String(text);
  if (className) cell.className = className;
  row.append(cell);
  return cell;
}

function renderComparison(scenarioId, focusedSolver) {
  if (state.currentPayload?.mode === "reference") { renderReferenceComparison(); return; }
  setComparisonHeadings(["Method", "TP ↑", "TCR ↑", "Slew ↓", "Check", "RT ↓", "Evals", "Stop reason", "Seed / budget"]);
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
    if (left.payload.result.validation.is_feasible !== right.payload.result.validation.is_feasible) return left.payload.result.validation.is_feasible ? -1 : 1;
    return right.payload.result.metrics.total_value - left.payload.result.metrics.total_value
      || right.payload.result.metrics.completed_tasks - left.payload.result.metrics.completed_tasks
      || left.payload.result.metrics.total_slew_time_s - right.payload.result.metrics.total_slew_time_s
      || left.solver.solver_name.localeCompare(right.solver.solver_name);
  });

  const tableHost = document.querySelector(".comparison-table-host");
  const capacity = Math.max(1, Math.floor((tableHost.clientHeight - 25) / 34));
  const rows = pageItems("comparison", entries, capacity).map(({ solver, payload, omission }) => {
    const row = document.createElement("tr");
    if (solver.solver_name === focusedSolver) row.classList.add("is-focused");
    const methodCell = appendCell(row, solver.solver_name, "method-name");
    if (payload) {
      const inspect = document.createElement("button");
      inspect.type = "button";
      inspect.textContent = solver.solver_name;
      inspect.title = `Inspect ${methodLabel(solver.solver_name)} · seed ${runMetadata(payload).seed} / budget ${runMetadata(payload).evaluation_budget}`;
      inspect.disabled = state.busy;
      inspect.addEventListener("click", () => {
        elements.solver.value = solver.solver_name;
        applyStaticRunConfiguration();
        renderResult(payload);
        markConfigurationChanged();
        elements.status.textContent = `Inspecting ${methodLabel(solver.solver_name)} · cached validated run`;
      });
      methodCell.replaceChildren(inspect);
    }
    const category = document.createElement("small");
    const variant = methodVariant(solver.solver_name);
    category.textContent = variant ? `${solver.category} · ${variant}` : solver.category;
    methodCell.append(category);
    if (!payload) {
      row.classList.add("is-omitted");
      const reason = document.createElement("td");
      reason.colSpan = 8;
      reason.textContent = omission?.reason || "Not evaluated in this local session.";
      reason.title = reason.textContent;
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
    appendCell(row, `${metadata.seed} / ${metadata.evaluation_budget}`, "numeric budget-column");
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
  elements.comparisonNote.title = elements.comparisonNote.textContent;
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
  item.title = `${title} · ${code}: ${description}`;
  item.append(heading, detail);
  return item;
}

function renderConstraintAudit(scenario, result, auditPayload) {
  if (state.currentPayload?.mode === "reference") { renderReferenceAudit(); return; }
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
  const exclusionCapacity = Math.max(1, Math.floor(elements.unscheduledList.clientHeight / 69));
  elements.unscheduledList.replaceChildren(...pageItems("unscheduled", unscheduledItems, exclusionCapacity));

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
  const validationCapacity = Math.max(1, Math.floor(elements.validationList.clientHeight / 69));
  elements.validationList.replaceChildren(...pageItems("validation", validationItems, validationCapacity));
  elements.auditMethodology.textContent = audit.methodology;
  elements.auditMethodology.title = audit.methodology;
}

function renderProvenance(payload) {
  const metadata = runMetadata(payload);
  const revision = String(metadata.source_revision);
  elements.recordScenario.textContent = payload.scenario.scenario_id;
  elements.recordMethod.textContent = payload.reference_plan?.label || methodLabel(payload.result.schedule.solver_name);
  elements.recordSeed.textContent = String(metadata.seed);
  elements.recordBudget.textContent = `${metadata.evaluation_budget} · ${metadata.budget_profile}`;
  elements.recordRevision.textContent = revision.length > 12 ? revision.slice(0, 12) : revision;
  elements.recordRevision.title = `${revision} · OrbitOps ${metadata.software_version}`;
}

function renderGantt(scenario, result) {
  if (state.currentPayload?.mode === "reference") { renderReferenceGantt(); return; }
  if (!elements.timeline.clientWidth || !elements.timeline.clientHeight) return;
  const simulation = result.validation.simulation;
  const scheduled = new Map((simulation?.tasks || []).map((task) => [task.task_id, task]));
  const width = elements.timeline.clientWidth;
  const height = elements.timeline.clientHeight;
  const left = width < 500 ? 89 : 150;
  const right = 18;
  const top = 8;
  const bottom = 25;
  const rowHeight = 29;
  const capacity = Math.max(1, Math.floor((height - top - bottom) / rowHeight));
  const tasks = pageItems("timeline", filteredTasks(scenario), capacity);
  const plotWidth = width - left - right;
  const horizon = scenario.horizon_end_s - scenario.horizon_start_s;
  const x = (value) => left + ((value - scenario.horizon_start_s) / horizon) * plotWidth;
  const root = chart(width, height, "Mission Gantt chart",
    `${scenario.tasks.length} targets with visibility windows, scheduled observations, and slew intervals. Paginated to fit the workspace.`);
  root.setAttribute("preserveAspectRatio", "none");

  for (let tick = 0; tick <= 4; tick += 1) {
    const value = scenario.horizon_start_s + horizon * tick / 4;
    root.append(svgElement("line", { x1: x(value), y1: top, x2: x(value),
      y2: height - bottom, class: tick === 0 || tick === 4 ? "chart-grid-strong" : "chart-grid" }));
    root.append(svgElement("text", { x: x(value), y: height - 8, "text-anchor": "middle",
      class: "chart-axis" }, `${Math.round(value / 60)}m`));
  }

  tasks.forEach((task, index) => {
    const rowY = top + index * rowHeight;
    const row = svgElement("g", { class: "timeline-row", role: "button", tabindex: "0",
      "aria-label": `Inspect ${task.target.name}, priority ${task.priority_value}`,
      "aria-pressed": String(task.task_id === state.selectedTaskId), "data-task-id": task.task_id });
    row.append(svgElement("rect", { x: 0, y: rowY, width, height: rowHeight - 2,
      class: task.task_id === state.selectedTaskId ? "row-selected" : "row-band",
      opacity: task.task_id === state.selectedTaskId || index % 2 === 0 ? 1 : 0 }));
    const maxLabelLength = width < 500 ? 11 : 22;
    const name = task.target.name.length > maxLabelLength ? `${task.target.name.slice(0, maxLabelLength - 1)}…` : task.target.name;
    row.append(svgElement("text", { x: 6, y: rowY + 12, class: "task-label" }, name));
    row.append(svgElement("text", { x: 6, y: rowY + 23, class: "task-sublabel" },
      width < 500 ? `P${task.priority_value.toFixed(0)}` : `${task.task_id} · P${task.priority_value.toFixed(0)}`));
    task.visibility_windows.forEach((window) => {
      const bar = svgElement("rect", { x: x(window.start_s), y: rowY + 7,
        width: Math.max(2, x(window.end_s) - x(window.start_s)), height: 15, rx: 2, class: "window-bar" });
      bar.append(svgElement("title", {}, `${window.window_id}: ${window.start_s.toFixed(0)}–${window.end_s.toFixed(0)}s visibility`));
      row.append(bar);
    });
    const assignment = scheduled.get(task.task_id);
    if (assignment) {
      if (assignment.slew_time_s > 0) {
        const slewStart = Math.max(scenario.horizon_start_s, assignment.start_s - assignment.slew_time_s);
        const slew = svgElement("rect", { x: x(slewStart), y: rowY + 12,
          width: Math.max(2, x(assignment.start_s) - x(slewStart)), height: 5, rx: 1, class: "slew-bar" });
        slew.append(svgElement("title", {}, `Slew ${assignment.slew_time_s.toFixed(1)} seconds`));
        row.append(slew);
      }
      const observation = svgElement("rect", { x: x(assignment.start_s), y: rowY + 10,
        width: Math.max(3, x(assignment.end_s) - x(assignment.start_s)), height: 9, rx: 1, class: "task-bar", "data-task-id": task.task_id, "data-state": taskState(task.task_id) });
      observation.append(svgElement("title", {}, `${task.target.name}: ${assignment.start_s.toFixed(1)}–${assignment.end_s.toFixed(1)}s · ${assignment.window_id}`));
      row.append(observation);
    } else {
      row.append(svgElement("circle", { cx: width - 6, cy: rowY + 14, r: 2, class: "unscheduled-dot" }));
    }
    row.addEventListener("click", () => selectTarget(task.task_id));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectTarget(task.task_id);
      }
    });
    root.append(row);
  });
  root.append(svgElement("line", {x1: x(state.replay.time), x2: x(state.replay.time), y1: top, y2: height - bottom, class: "time-cursor", "data-left": left, "data-width": plotWidth}));
  elements.timeline.replaceChildren(root);
}

function renderResources(scenario, result) {
  if (state.currentPayload?.mode === "reference") { renderWorkloads(); return; }
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

  const width = Math.max(180, elements.resources.clientWidth);
  const height = Math.max(70, elements.resources.clientHeight);
  const dimensions = { left: 29, top: 16, plotWidth: width - 43, plotHeight: height - 42 };
  const horizon = scenario.horizon_end_s - scenario.horizon_start_s;
  const x = (value) => dimensions.left + ((value - scenario.horizon_start_s) / horizon) * dimensions.plotWidth;
  const y = (value) => dimensions.top + (1 - value / 100) * dimensions.plotHeight;
  const root = chart(width, height, "Resource envelope", "Energy remaining and storage used as percentages of capacity.");

  const definitions = svgElement("defs");
  const gradient = svgElement("linearGradient", { id: "energy-gradient", x1: "0", y1: "0", x2: "0", y2: "1" });
  gradient.append(
    svgElement("stop", { offset: "0%", "stop-color": "#59b9e8", "stop-opacity": "0.16" }),
    svgElement("stop", { offset: "100%", "stop-color": "#59b9e8", "stop-opacity": "0" }),
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
  root.append(svgElement("circle", { cx: x(energyFinal.x), cy: y(energyFinal.y), r: 2, class: "chart-point" }));
  root.append(svgElement("circle", { cx: x(storageFinal.x), cy: y(storageFinal.y), r: 2, class: "storage-point" }));
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
  const width = Math.max(300, elements.learning.clientWidth);
  const height = Math.max(120, elements.learning.clientHeight);
  const dimensions = { left: 38, top: 20, plotWidth: width - 58, plotHeight: height - 44 };
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
  const width = Math.max(300, elements.learning.clientWidth);
  const height = Math.max(140, elements.learning.clientHeight);
  const left = 38;
  const plotWidth = width - 58;
  const topY = 20;
  const topHeight = (height - 80) * 0.62;
  const lowerY = topY + topHeight + 31;
  const lowerHeight = height - lowerY - 27;
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
    root.append(svgElement("text", { x: x(maxEpisode * fraction), y: height - 10, "text-anchor": fraction === 1 ? "end" : "middle", class: "chart-axis" }, `${Math.round(maxEpisode * fraction)}`));
  });
  root.append(svgElement("text", { x: left, y: 17, class: "chart-panel-label" }, "Episode schedule objective"));
  root.append(svgElement("text", { x: left, y: lowerY - 13, class: "chart-panel-label" }, "Exploration / normalized TD error"));
  root.append(svgElement("text", { x: left + plotWidth - 30, y: height - 10, "text-anchor": "end", class: "chart-panel-label" }, "Episode"));

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
  const project = (longitude, latitude) => [(longitude + 180) / 360 * 1000, (90 - latitude) / 180 * 500];
  const map = chart(1000, 500, "Mission coordinate map",
    "WGS84 target positions in an equirectangular projection. Coastlines are schematic. Source orbit samples are displayed when present.");
  map.classList.add("fallback-map");
  map.append(svgElement("rect", { x: 0, y: 0, width: 1000, height: 500, class: "map-ocean" }));
  for (let lon = -180; lon <= 180; lon += 30) {
    const [x] = project(lon, 0);
    map.append(svgElement("line", { x1: x, y1: 0, x2: x, y2: 500, class: "map-grid" }));
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    const [, y] = project(0, lat);
    map.append(svgElement("line", { x1: 0, y1: y, x2: 1000, y2: y, class: "map-grid" }));
  }
  // Deliberately schematic land outlines; only the target coordinates are authoritative.
  const continents = [
    [[-168,70],[-145,60],[-130,54],[-124,40],[-117,32],[-110,24],[-98,16],[-84,10],[-78,8],[-85,20],[-81,25],[-80,32],[-65,46],[-56,52],[-63,60],[-80,68],[-110,72],[-140,70]],
    [[-81,12],[-67,10],[-51,4],[-35,-8],[-40,-23],[-51,-34],[-67,-55],[-75,-45],[-72,-20],[-80,-5]],
    [[-52,60],[-42,63],[-23,75],[-35,83],[-58,80],[-64,68]],
    [[-10,36],[-10,44],[-5,50],[5,54],[8,62],[22,70],[34,70],[38,60],[60,68],[90,76],[130,70],[170,63],[179,52],[150,47],[135,34],[122,25],[108,18],[104,2],[94,6],[81,8],[72,22],[57,25],[45,12],[34,28],[27,40],[14,42],[5,36]],
    [[-17,36],[0,37],[15,33],[32,31],[44,12],[51,10],[42,-5],[34,-25],[20,-35],[12,-18],[5,-5],[-5,5],[-17,15]],
    [[113,-22],[122,-14],[135,-12],[142,-10],[154,-25],[146,-39],[131,-33],[116,-35]],
    [[130,31],[135,35],[141,41],[144,44],[141,35]],
    [[47,-13],[50,-18],[45,-26],[44,-19]],
    [[166,-35],[174,-40],[170,-47],[166,-44]],
    [[-8,50],[-3,59],[1,52]],
  ];
  continents.forEach((points) => {
    const outline = points.map(([lon, lat]) => project(lon, lat).join(",")).join(" ");
    map.append(svgElement("polygon", { points: outline, class: "map-land" }));
  });
  const taskById = new Map(scenario.tasks.map((task) => [task.task_id, task]));
  const sequence = (state.currentPayload?.result.validation.simulation?.tasks || [])
    .map((assignment) => taskById.get(assignment.task_id)).filter(Boolean);
  const track = svgElement("polyline", {
    points: sequence.map((task) => project(task.target.longitude_deg, task.target.latitude_deg).join(",")).join(" "),
    class: "map-sequence",
  });
  if (state.currentPayload?.mode === "reference") track.setAttribute("points", "");
  track.style.display = state.layers.track ? "" : "none";
  map.append(track);
  scenario.tasks.forEach((task) => {
    const [x, y] = project(task.target.longitude_deg, task.target.latitude_deg);
    const marker = svgElement("g", { class: `map-marker${scheduledIds.has(task.task_id) ? " is-scheduled" : ""}`,
      "data-task-id": task.task_id, role: "button", tabindex: "0",
      "aria-label": `Inspect ${task.target.name}` });
    marker.append(svgElement("circle", { cx: x, cy: y, r: 4 }));
    marker.append(svgElement("title", {}, `${task.target.name}: ${task.target.latitude_deg.toFixed(2)}°, ${task.target.longitude_deg.toFixed(2)}°`));
    if (scenario.tasks.length <= 18) marker.append(svgElement("text", { x: x + 8, y: y - 7 }, task.target.name));
    marker.style.display = state.layers.targets ? "" : "none";
    marker.addEventListener("click", () => selectTarget(task.task_id));
    marker.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectTarget(task.task_id);
      }
    });
    map.append(marker);
  });
  map.append(svgElement("text", { x: 20, y: 485, class: "map-caption" }, "2D FALLBACK · SCHEMATIC COASTLINES · WGS84 TARGET COORDINATES"));
  if (state.currentPayload?.replay) addFallbackOrbits(map);
  elements.globe.replaceChildren(map);
  elements.globe.dataset.engine = "fallback";
  document.querySelector(".view-tag").textContent = "2D";
  elements.globeLoading.classList.add("is-hidden");
  updateReplayVisuals();
}

function updateGlobeLayers() {
  if (state.globe) {
    state.globe.entities.values.forEach((entity) => {
      if (entity.id.startsWith("target-")) entity.show = state.layers.targets;
      if (entity.id.startsWith("orbit-") || entity.id.startsWith("sequence-")) entity.show = state.layers.track;
      if (entity.id.startsWith("ray-")) entity.show = state.layers.rays;
      if (entity.label && entity.id.startsWith("target-")) entity.label.show = state.layers.labels || entity.id === `target-${state.selectedTaskId}`;
    });
    state.globe.scene.requestRender();
  } else {
    document.querySelectorAll(".map-marker").forEach((marker) => { marker.style.display = state.layers.targets ? "" : "none"; });
    document.querySelectorAll(".map-sequence").forEach((track) => { track.style.display = state.layers.track ? "" : "none"; });
    document.querySelectorAll(".map-orbit").forEach((track) => { track.style.display = state.layers.track ? "" : "none"; });
    document.querySelectorAll(".map-ray").forEach((ray) => { ray.style.display = state.layers.rays ? "" : "none"; });
  }
}

function fitMissionView(duration = 0) {
  if (!state.globe || !state.cameraHome) return;
  const Cesium = window.Cesium;
  const viewer = state.globe;
  const home = state.cameraHome;
  releaseCameraTracking();
  state.cameraMode = "overview";
  state.orbitEmphasis = false;
  viewer.resize();
  const range = Math.max(1400000, window.OrbitReplay.fitRange(home.missionCenter.radius, viewer.camera.frustum.fovy, viewer.camera.frustum.aspectRatio, home.global ? 1.035 : 1.12));
  if (home.global) {
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(home.longitudeCenter, home.latitudeCenter, range - Cesium.Ellipsoid.WGS84.maximumRadius),
      orientation: { heading: 0, pitch: -Cesium.Math.PI_OVER_TWO, roll: 0 },
      duration,
    });
  } else {
    viewer.camera.flyToBoundingSphere(home.missionCenter, {
      duration,
      offset: new Cesium.HeadingPitchRange(Cesium.Math.toRadians(-18), Cesium.Math.toRadians(-68), range),
    });
  }
  viewer.scene.requestRender();
  updateReplayVisuals();
}

function naturalEarthLayer(Cesium) {
  const provider = new Cesium.UrlTemplateImageryProvider({
    url: `${Cesium.buildModuleUrl("Assets/Textures/NaturalEarthII")}/{z}/{x}/{reverseY}.jpg`,
    tilingScheme: new Cesium.GeographicTilingScheme(),
    maximumLevel: 5,
    credit: new Cesium.Credit("Natural Earth II · CesiumJS"),
  });
  return new Cesium.ImageryLayer(provider, {
    brightness: 1.02,
    contrast: 1.04,
    saturation: .95,
    gamma: 1.02,
  });
}

function nasaBlueMarbleLayer(Cesium) {
  const provider = new Cesium.UrlTemplateImageryProvider({
    url: "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg",
    tilingScheme: new Cesium.WebMercatorTilingScheme(),
    maximumLevel: 8,
    credit: new Cesium.Credit("NASA Earth Observatory · GIBS"),
  });
  return new Cesium.ImageryLayer(provider, {
    brightness: 1.06,
    contrast: 1.06,
    saturation: .98,
    gamma: 1.02,
  });
}

function renderMissionGlobe(scenario, result) {
  const scheduledTasks = result.validation.simulation?.tasks || [];
  const scheduledIds = new Set(scheduledTasks.map((task) => task.task_id));
  elements.globeTargets.textContent = `${scenario.tasks.length} targets`;
  elements.globeSequence.textContent = state.currentPayload?.mode === "reference" ? `${scheduledIds.size} planned · ${scenario.satellites.length} satellites` : `${scheduledIds.size} selected · ${scenario.satellite.satellite_id}`;
  elements.globe.setAttribute("aria-label", `Interactive WGS84 globe with ${scenario.tasks.length} mission targets, ${scheduledIds.size} scheduled.`);

  const Cesium = window.Cesium;
  if (!Cesium) {
    renderGlobeFallback(scenario, scheduledIds);
    return;
  }
  try {
    if (!state.globe) {
      elements.globe.replaceChildren();
      document.getElementById("cesium-styles").rel = "stylesheet";
      const primaryImagery = nasaBlueMarbleLayer(Cesium);
      state.globe = new Cesium.Viewer("mission-globe", {
        animation: false,
        baseLayer: naturalEarthLayer(Cesium),
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
        maximumRenderTimeChange: Infinity,
      });
      state.globe.imageryLayers.add(primaryImagery);
      bindGlobePicking(state.globe, Cesium);
      primaryImagery.imageryProvider.errorEvent.addEventListener(() => {
        if (!state.imageryFallbackActive && state.globe) {
          primaryImagery.show = false;
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
      state.globe.scene.backgroundColor = Cesium.Color.fromCssColorString("#080d14");
      state.globe.scene.globe.baseColor = Cesium.Color.fromCssColorString("#263a49");
      state.globe.scene.globe.enableLighting = false;
      state.globe.scene.globe.showGroundAtmosphere = true;
      state.globe.scene.skyBox.show = false;
      state.globe.scene.sun.show = false;
      state.globe.scene.moon.show = false;
      state.globe.useBrowserRecommendedResolution = false;
      state.globe.resolutionScale = Math.min(2, window.devicePixelRatio || 1) / (window.devicePixelRatio || 1);
      state.globe.scene.screenSpaceCameraController.minimumZoomDistance = 15000;
    }

    const viewer = state.globe;
    releaseCameraTracking();
    viewer.entities.removeAll();
    state.orbitPositions.clear();
    state.orbitStyles.clear();
    state.entityTaskStates.clear();
    state.geometrySelectionKey = null;
    if (state.currentPayload.mode === "reference") {
      setupReferenceGlobe(viewer, Cesium);
      return;
    }
    const longitudeCenter = circularLongitudeCenter(scenario.tasks);
    const latitudeCenter = scenario.tasks.length
      ? scenario.tasks.reduce((sum, task) => sum + task.target.latitude_deg, 0) / scenario.tasks.length
      : 0;
    const scheduledColor = Cesium.Color.fromCssColorString("#59b9e8");
    const candidateColor = Cesium.Color.fromCssColorString("#e1b46a");
    const targetPositions = [];

    scenario.tasks.forEach((task, index) => {
      const selected = scheduledIds.has(task.task_id);
      const color = selected ? scheduledColor : candidateColor;
      const position = Cesium.Cartesian3.fromDegrees(task.target.longitude_deg, task.target.latitude_deg, task.target.altitude_m || 0);
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
          disableDepthTestDistance: 0,
        },
        label: {
          show: state.layers.labels || task.task_id === state.selectedTaskId,
          text: task.target.name.toUpperCase(),
          font: "600 11px sans-serif",
          fillColor: Cesium.Color.WHITE.withAlpha(0.88),
          outlineColor: Cesium.Color.fromCssColorString("#211b2a"),
          outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(((index % 3) - 1) * 18, -22 - (index % 4) * 10),
          disableDepthTestDistance: 0,
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
        id: "sequence-local",
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

    let missionCenter = targetPositions.length
      ? Cesium.BoundingSphere.fromPoints(targetPositions)
      : new Cesium.BoundingSphere(Cesium.Cartesian3.fromDegrees(longitudeCenter, latitudeCenter, 0), 250000);
    const global = missionCenter.radius > 2800000;
    if (global) missionCenter = new Cesium.BoundingSphere(Cesium.Cartesian3.ZERO, 7100000);
    state.cameraHome = { missionCenter, global, longitudeCenter, latitudeCenter };
    fitMissionView();
    viewer.scene.requestRender();
    elements.globe.dataset.engine = "cesium";
    document.querySelector(".view-tag").textContent = "3D";
    updateGlobeLayers();
    elements.globeLoading.classList.add("is-hidden");
  } catch (error) {
    console.warn("Cesium mission view unavailable", error);
    if (state.globe && !state.globe.isDestroyed()) state.globe.destroy();
    state.globe = null;
    state.imageryFallbackActive = false;
    renderGlobeFallback(scenario, scheduledIds);
  }
}

function renderResult(payload) {
  const { scenario, result, convergence } = payload;
  const previousScenarioId = state.currentPayload?.scenario.scenario_id;
  state.currentPayload = payload;
  state.taskById = new Map(scenario.tasks.map((task) => [task.task_id, task]));
  state.assignments = new Map((result.validation.simulation?.tasks || []).map((task) => [task.task_id, task]));
  configureReplay(payload);
  if (previousScenarioId !== scenario.scenario_id) {
    state.pages = {};
    state.selectedTaskId = result.validation.simulation?.tasks[0]?.task_id || scenario.tasks[0]?.task_id;
  }
  const metadata = runMetadata(payload);
  state.lastRequest = payload.mode === "reference" ? {scenario_id: scenario.scenario_id, solver_name: result.schedule.solver_name} : {
    scenario_id: scenario.scenario_id,
    solver_name: result.schedule.solver_name,
    seed: metadata.seed,
    evaluation_budget: metadata.evaluation_budget,
  };
  const trainingTrace = result.schedule.metadata.training_trace;
  state.runCache.set(runKey(scenario.scenario_id, result.schedule.solver_name), payload);
  elements.value.textContent = result.metrics.total_value.toFixed(1);
  elements.tasks.textContent = `${result.metrics.completed_tasks}/${scenario.tasks.length}`;
  elements.taskContext.textContent = `${((result.metrics.completed_tasks / Math.max(1, scenario.tasks.length)) * 100).toFixed(0)}% of candidate targets`;
  renderEvaluation(payload);
  const reference = payload.mode === "reference";
  elements.feasible.textContent = reference ? "N/A" : result.validation.is_feasible ? "PASS" : "FAIL";
  elements.feasible.classList.toggle("is-fail", !reference && !result.validation.is_feasible);
  elements.feasible.classList.toggle("is-reference", reference);
  textField("check-label", reference ? "Full feasibility" : "Feasibility");
  textField("check-context", reference ? "Not independently verified" : "Shared simulator verdict");
  elements.validationBadge.textContent = reference ? (result.validation.reference_consistent ? "REFERENCE CONSISTENCY CHECKED" : "REFERENCE DISCREPANCIES") : result.validation.is_feasible ? "SCHEDULE VALIDATED" : "VALIDATION FAILED";
  elements.validationBadge.className = `validation-badge ${reference ? "is-reference" : result.validation.is_feasible ? "is-pass" : "is-fail"}`;
  textField("mission-name", scenarioDisplayName(scenario));
  textField("mission-id", scenario.scenario_id);
  textField("mission-horizon", `${((scenario.horizon_end_s - scenario.horizon_start_s) / 60).toFixed(0)} min`);
  const finalState = result.validation.simulation?.final_state;
  if (!reference) {
    textField("energy-readout", `${(finalState?.energy_wh ?? scenario.satellite.initial_energy_wh).toFixed(1)} / ${scenario.satellite.energy_capacity_wh.toFixed(0)} Wh`);
    textField("storage-readout", `${(finalState?.storage_gb ?? scenario.satellite.initial_storage_gb).toFixed(1)} / ${scenario.satellite.storage_capacity_gb.toFixed(1)} GB`);
  }
  configureModeDetails(payload);
  elements.export.disabled = false;
  const timingNote = reference ? " · source runtime" : staticDeployment ? " · recorded at build" : "";
  elements.runtime.textContent = `${payload.reference_plan?.label || result.schedule.solver_name} · ${reference ? `${result.runtime_s.toFixed(3)} s` : `${(result.runtime_s * 1000).toFixed(1)} ms`}${timingNote}`;
  renderProvenance(payload);
  renderComparison(scenario.scenario_id, result.schedule.solver_name);
  renderConstraintAudit(scenario, result, payload.constraint_audit);
  renderMissionGlobe(scenario, result);
  renderGantt(scenario, result);
  renderResources(scenario, result);
  if (reference) renderSourceDiagnostics();
  else if (Array.isArray(trainingTrace) && trainingTrace.length) renderTraining(trainingTrace);
  else renderConvergence(convergence);
  elements.results.hidden = false;
  selectTarget(state.selectedTaskId, false);
  markConfigurationChanged();
}

async function runSolve() {
  if (state.busy || !elements.form.reportValidity() || !elements.scenario.value) return;
  const progressMessage = staticDeployment
    ? "Loading the precomputed reproducibility artifact…"
    : "Evaluating the solver and replaying the resulting schedule…";
  setBusy(true, progressMessage);
  try {
    const request = activeRequest();
    const payload = isReferenceScenario() ? window.OrbitReplay.referencePayload(state.referenceData, state.referenceData.plans.find((plan) => plan.plan_id === request.solver_name)) : await api("/api/solve", {
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
    if (window.matchMedia("(max-width: 1000px)").matches) setPanel("config", false);
    elements.status.textContent = payload.mode === "reference" ? "EOS-Bench reference loaded · source files hash-verified; limited consistency checks, not a full feasibility certificate." : staticDeployment
      ? "Precomputed run loaded · feasibility and diagnostic artifacts were generated by the shared simulator."
      : "Schedule replay completed · the shared simulator produced the feasibility verdict and diagnostics.";
  } catch (error) {
    setBusy(false);
    elements.statusIndicator.classList.add("is-error");
    elements.status.classList.add("error");
    elements.status.textContent = error instanceof Error ? error.message : "The run failed.";
  } finally {
    if (state.busy) setBusy(false);
    refreshPanels();
  }
}

function scenarioDisplayName(scenario) {
  const names = {
    "showcase-resources-10": "Resource-constrained observation pass",
    "showcase-temporal-06": "Overlapping access windows",
    "showcase-slew-18": "Angularly dispersed target corridor",
    "showcase-global-30": "Dense global observation campaign",
  };
  return names[scenario.scenario_id] || scenario.name;
}

async function initialize() {
  try {
    const [scenarioPayload, solverPayload, referenceData] = await Promise.all([api("/api/scenarios"), api("/api/solvers"), api("/api/reference/data")]);
    state.scenarios = [...scenarioPayload.scenarios];
    state.solvers = solverPayload.solvers;
    state.localSolvers = solverPayload.solvers;
    state.referenceData = referenceData;
    if (referenceData) {
      const source = referenceData.scenario;
      state.scenarios.unshift({scenario_id: source.scenario_id, name: source.name, task_count: source.tasks.length, satellite_count: source.satellites.length, horizon_start_s: source.horizon_start_s, horizon_end_s: source.horizon_end_s, mode: "reference"});
    }
    populateSelect(elements.scenario, state.scenarios, "scenario_id", (item) => `${scenarioDisplayName(item)} · ${item.task_count}`);
    if (state.scenarios.some((item) => item.scenario_id === "showcase-resources-10")) elements.scenario.value = "showcase-resources-10";
    populateSelect(
      elements.solver,
      state.solvers,
      "solver_name",
      (item) => `${methodLabel(item.solver_name)} · ${item.category}`,
    );
    elements.solver.value = "q-learning";
    if (referenceData && new URLSearchParams(location.search).get("mode") !== "local") elements.scenario.value = referenceData.scenario.scenario_id;
    if (staticDeployment) {
      const dataset = await loadStaticDataset();
      elements.seed.value = dataset.metadata.seed;
      elements.budget.value = dataset.metadata.evaluation_budget;
      elements.seed.disabled = true;
      elements.budget.disabled = true;
      elements.deploymentMode.textContent = "GitHub Pages · precomputed runs";
      elements.runLabel.textContent = "Load reference run";
    }
    updateScenarioContext();
    markConfigurationChanged();
    await runSolve();
  } catch (error) {
    setBusy(false);
    elements.button.disabled = true;
    elements.statusIndicator.classList.add("is-error");
    elements.status.classList.add("error");
    elements.status.textContent = error instanceof Error ? error.message : "The lab could not start.";
  }
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  runSolve();
});
elements.scenario.addEventListener("change", () => {
  updateScenarioContext();
  markConfigurationChanged();
});
elements.solver.addEventListener("change", () => {
  applyStaticRunConfiguration();
  markConfigurationChanged();
});
elements.seed.addEventListener("input", markConfigurationChanged);
elements.budget.addEventListener("input", markConfigurationChanged);
elements.export.addEventListener("click", () => {
  if (!state.currentPayload) return;
  const payload = state.currentPayload;
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${payload.scenario.scenario_id}-${payload.result.schedule.solver_name}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
for (const name of ["config", "inspector"]) {
  document.getElementById(`toggle-${name}`).addEventListener("click", () => {
    const key = name === "config" ? "configOpen" : "inspectorOpen";
    setPanel(name, elements.shell.dataset[key] !== "true");
  });
}
for (const name of ["targets", "track", "rays", "labels"]) {
  document.getElementById(`toggle-${name}`).addEventListener("click", (event) => {
    state.layers[name] = !state.layers[name];
    event.currentTarget.setAttribute("aria-pressed", String(state.layers[name]));
    updateGlobeLayers();
    updateReplayVisuals();
  });
}
document.getElementById("reset-view").addEventListener("click", () => {
  if (state.globe && state.cameraHome) {
    fitMissionView(window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 0.6);
  } else if (state.currentPayload) {
    renderMissionGlobe(state.currentPayload.scenario, state.currentPayload.result);
  }
});
bindTabs();
bindMissionControls();
bindPager("target", renderTargetCatalog);
for (const name of ["timeline", "comparison", "unscheduled", "validation"]) bindPager(name, refreshPanels);
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    runSolve();
  }
  if (event.key === "Escape" && window.matchMedia("(max-width: 1000px)").matches) {
    const openPanel = elements.shell.dataset.configOpen === "true" ? "config" : "inspector";
    setPanel("config", false);
    setPanel("inspector", false);
    document.getElementById(`toggle-${openPanel}`).focus();
  }
});
const narrowLayout = window.matchMedia("(max-width: 1000px)");
function updateWorkspaceLayout() {
  setPanel("config", !narrowLayout.matches);
  setPanel("inspector", !narrowLayout.matches);
}
narrowLayout.addEventListener("change", updateWorkspaceLayout);
updateWorkspaceLayout();
let resizeFrame;
const resizeObserver = new ResizeObserver(() => {
  cancelAnimationFrame(resizeFrame);
  resizeFrame = requestAnimationFrame(refreshPanels);
});
for (const host of [elements.timeline, elements.resources, elements.learning, elements.targetList, elements.unscheduledList, elements.validationList, document.querySelector(".comparison-table-host")]) resizeObserver.observe(host);
let globeResizeFrame;
const globeResizeObserver = new ResizeObserver(() => {
  cancelAnimationFrame(globeResizeFrame);
  globeResizeFrame = requestAnimationFrame(() => {
    state.globe?.resize();
    if (state.cameraMode === "overview") fitMissionView();
  });
});
globeResizeObserver.observe(elements.globe);
document.getElementById("cesium-engine").addEventListener("load", () => {
  if (state.currentPayload && !state.globe) {
    renderMissionGlobe(state.currentPayload.scenario, state.currentPayload.result);
    selectTarget(state.selectedTaskId, false);
  }
});
initialize();
