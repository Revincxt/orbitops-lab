"use strict";

function isReferenceScenario() {
  return state.scenarios.find((item) => item.scenario_id === elements.scenario.value)?.mode === "reference";
}

function timeLabel(seconds) {
  return window.OrbitReplay.utc(state.currentPayload?.scenario.epoch_utc, seconds);
}

function taskState(taskId) {
  const task = state.currentPayload?.scenario.tasks.find((item) => item.task_id === taskId);
  return window.OrbitReplay.taskState(state.replay.time, state.assignments.get(taskId), task?.visibility_windows);
}

function filteredTasks(scenario) {
  const search = document.getElementById("target-search").value.toLowerCase().trim();
  const filter = document.getElementById("target-filter").value;
  const satellite = document.getElementById("satellite-filter").value;
  return scenario.tasks.filter((task) => {
    const assignment = state.assignments.get(task.task_id);
    if (search && !`${task.task_id} ${task.target.name}`.toLowerCase().includes(search)) return false;
    if (filter === "planned" && !assignment) return false;
    if (filter === "unassigned" && assignment) return false;
    if (filter === "active" && taskState(task.task_id) !== "Observing") return false;
    if (satellite !== "all" && (assignment ? assignment.satellite_id !== satellite : !task.visibility_windows.some((window) => window.satellite_id === satellite))) return false;
    return true;
  });
}

function configureReplay(payload) {
  state.replay.playing = false;
  state.replay.time = payload.scenario.horizon_start_s;
  state.replay.lastFrame = 0;
  const slider = document.getElementById("replay-scrub");
  slider.min = payload.scenario.horizon_start_s;
  slider.max = payload.scenario.horizon_end_s;
  slider.value = state.replay.time;
  const selector = document.getElementById("satellite-filter");
  const previous = selector.value;
  const all = document.createElement("option");
  all.value = "all";
  all.textContent = "All satellites";
  const options = (payload.scenario.satellites || []).map((satellite) => {
    const option = document.createElement("option");
    option.value = satellite.satellite_id;
    option.textContent = satellite.satellite_id;
    return option;
  });
  selector.replaceChildren(all, ...options);
  if (options.some((option) => option.value === previous)) selector.value = previous;
  selector.hidden = payload.mode !== "reference";
  document.getElementById("target-search").value = "";
  document.getElementById("target-filter").value = "all";
  document.getElementById("replay-play").textContent = "▶";
  document.getElementById("replay-play").setAttribute("aria-pressed", "false");
  document.getElementById("replay-play").setAttribute("aria-label", "Play mission replay");
}

function setReplayTime(time, pause = false) {
  if (!state.currentPayload) return;
  const scenario = state.currentPayload.scenario;
  state.replay.time = Math.max(scenario.horizon_start_s, Math.min(scenario.horizon_end_s, Number(time)));
  if (pause) pauseReplay();
  updateReplayVisuals();
}

function pauseReplay() {
  state.replay.playing = false;
  state.replay.lastFrame = 0;
  const button = document.getElementById("replay-play");
  button.textContent = "▶";
  button.setAttribute("aria-pressed", "false");
  button.setAttribute("aria-label", "Play mission replay");
}

function animateReplay(timestamp) {
  if (!state.replay.playing || !state.currentPayload) return;
  const elapsed = state.replay.lastFrame ? Math.min(0.25, (timestamp - state.replay.lastFrame) / 1000) : 0;
  state.replay.lastFrame = timestamp;
  state.replay.time = Math.min(state.currentPayload.scenario.horizon_end_s, state.replay.time + elapsed * state.replay.speed);
  if (timestamp - state.replay.lastPaint > 100) {
    updateReplayVisuals();
    state.replay.lastPaint = timestamp;
  }
  if (state.replay.time >= state.currentPayload.scenario.horizon_end_s) {
    pauseReplay();
    updateReplayVisuals();
  } else requestAnimationFrame(animateReplay);
}

function updateReplayVisuals() {
  const payload = state.currentPayload;
  if (!payload) return;
  const time = state.replay.time;
  let completed = 0;
  const active = [];
  for (const assignment of state.assignments.values()) {
    if (time >= assignment.end_s) completed += 1;
    else if (time >= assignment.start_s) active.push(assignment);
  }
  textField("replay-time", window.OrbitReplay.utc(payload.scenario.epoch_utc, time, true));
  textField("replay-progress", `${completed}/${state.assignments.size} completed · ${active.length} observing`);
  document.getElementById("replay-scrub").value = time;
  if (state.selectedTaskId) textField("selected-state", taskState(state.selectedTaskId));
  document.querySelectorAll(".target-row, .map-marker").forEach((node) => {
    const current = taskState(node.dataset.taskId);
    node.dataset.state = current;
    const label = node.querySelector(".target-state");
    if (label) label.textContent = current;
  });
  document.querySelectorAll(".task-bar[data-task-id]").forEach((node) => { node.dataset.state = taskState(node.dataset.taskId); });
  const cursor = document.querySelector(".time-cursor");
  if (cursor) {
    const x = Number(cursor.dataset.left) + (time - payload.scenario.horizon_start_s) / (payload.scenario.horizon_end_s - payload.scenario.horizon_start_s) * Number(cursor.dataset.width);
    if (Number.isFinite(x)) { cursor.setAttribute("x1", x); cursor.setAttribute("x2", x); }
  }
  if (state.globe) updateCesiumReplay(active);
  else if (payload.replay) updateFallbackReplay(active);
  if (document.getElementById("target-filter").value === "active") renderTargetCatalog();
}

function stateColor(taskId) {
  const colors = {Planned: "#59b9e8", Observing: "#f7d074", Completed: "#5ed2a1", Available: "#e1b46a", Unassigned: "#ee7e83"};
  return colors[taskState(taskId)];
}

function configureModeDetails(payload) {
  const reference = payload.mode === "reference";
  textField("workspace-mode", reference ? "20 SATELLITES · REFERENCE" : "SINGLE SATELLITE · LOCAL");
  textField("deployment-mode", reference ? "EOS-Bench · source replay" : staticDeployment ? "GitHub Pages · precomputed runs" : "Local API execution");
  textField("geometry-source", reference ? "Source Orekit · sampled replay" : "Target coordinates · no orbit data");
  document.getElementById("geometry-source").title = reference ? `${payload.replay.model}; retained source samples, interpolated for display. Not telemetry or high-fidelity numerical propagation.` : "No orbital elements exist in this local scenario. Connecting target positions is a plan sequence, not a satellite trajectory.";
  const note = document.getElementById("model-note");
  note.replaceChildren(document.createTextNode(reference ? "EOS-Bench reference snapshot" : "Synthetic scheduling benchmark"));
  const detail = document.createElement("span");
  detail.textContent = reference ? `Pinned ${payload.provenance.revision.slice(0, 8)} · not telemetry` : "Synthetic access windows · no orbital propagation";
  note.append(detail);
  textField("toggle-track", reference ? "Orbit" : "Sequence");
  elements.solver.closest("label").querySelector(".field-label").textContent = reference ? "REFERENCE PLAN" : "SOLVER";
  document.querySelector(".run-hint").textContent = reference ? "Source → consistency check → replay" : "Solve → simulate → validate";
  document.getElementById("toggle-rays").disabled = !reference;
  document.querySelector(".slew-legend").hidden = reference;
  textField("timeline-title", reference ? "Satellite observation lanes · UTC" : "Task windows · relative time");
  textField("resources-title", reference ? "Satellite workload · seconds" : "Resource envelope");
  document.querySelector(".resource-block .count-badge").textContent = reference ? "s" : "%";
  document.querySelector(".resource-block .legend").replaceChildren(...legendItems(reference ? [["observation", "Source observation duration"]] : [["energy", "Energy left"], ["storage", "Storage used"]]));
  document.getElementById("energy-readout").parentElement.firstChild.textContent = reference ? "ACTIVE SATELLITES" : "ENERGY";
  document.getElementById("storage-readout").parentElement.firstChild.textContent = reference ? "OBSERVATION TIME" : "STORAGE";
  if (reference) {
    const loads = Object.values(payload.reference_plan.workloads);
    textField("energy-readout", `${loads.filter((load) => load > 0).length}/${loads.length}`);
    textField("storage-readout", `${loads.reduce((a, b) => a + b, 0).toFixed(0)} s`);
  }
  document.getElementById("issues-title").textContent = reference ? "Source checks and verification scope" : "Validator issues and margins";
}

function renderEvaluation(payload) {
  const evaluation = payload.evaluation || {};
  const reference = payload.mode === "reference";
  textField("metric-slew", evaluation.TM == null ? "—" : evaluation.TM.toFixed(3));
  document.getElementById("metric-slew").title = "TM ↓ = (sum of task start delays + unassigned count × horizon) / (all task count × horizon). This is not an execution-completion statistic.";
  textField("metric-balance", evaluation.BD == null ? "N/A · single satellite" : evaluation.BD.toFixed(3));
  textField("metric-runtime", `${payload.result.runtime_s.toFixed(3)} s${reference ? " · source" : ""}`);
  textField("metric-motion", payload.result.metrics.total_slew_time_s == null ? "Not recorded" : `${payload.result.metrics.total_slew_time_s.toFixed(1)} s`);
  textField("metric-objective", reference ? payload.reference_plan.objective : "TP → task count → −slew");
  textField("metric-basis", reference ? "Recomputed TP/TCR/TM/BD" : "Shared simulator replay");
}

function setComparisonHeadings(labels) {
  document.querySelectorAll(".comparison-table th").forEach((cell, index) => { cell.textContent = labels[index]; cell.title = labels[index]; });
}

function renderReferenceComparison() {
  setComparisonHeadings(["Plan", "TP ↑", "TCR ↑", "TM ↓", "Scope", "RT ↓", "BD ↑", "Objective", "Seed / budget"]);
  const tableHost = document.querySelector(".comparison-table-host");
  const capacity = Math.max(1, Math.floor((tableHost.clientHeight - 25) / 34));
  const plans = pageItems("comparison", state.referenceData.plans, capacity);
  const rows = plans.map((plan) => {
    const row = document.createElement("tr");
    if (plan.plan_id === state.currentPayload.reference_plan.plan_id) row.classList.add("is-focused");
    const cell = appendCell(row, "", "method-name");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = plan.label;
    button.disabled = state.busy;
    button.addEventListener("click", () => {
      elements.solver.value = plan.plan_id;
      renderResult(window.OrbitReplay.referencePayload(state.referenceData, plan));
      elements.status.textContent = `Source plan: ${plan.label}. Objective configuration retained; no local solve performed.`;
    });
    cell.append(button);
    const metrics = plan.recomputed_metrics;
    appendCell(row, metrics.TP.toFixed(0), "numeric");
    appendCell(row, `${(metrics.TCR * 100).toFixed(1)}%`, "numeric");
    appendCell(row, metrics.TM.toFixed(3), "numeric");
    appendCell(row, plan.checks.issues.length ? "ISSUES" : "LIMITED", "numeric");
    appendCell(row, `${plan.source_metrics.RT.toFixed(1)}s`, "numeric");
    appendCell(row, metrics.BD.toFixed(3), "numeric");
    appendCell(row, plan.objective);
    appendCell(row, "Not recorded", "budget-column");
    return row;
  });
  elements.comparisonBody.replaceChildren(...rows);
  textField("comparison-context", "4 imported plans · objectives differ");
  textField("comparison-note", "No overall ranking: objectives differ. RT is source solve time; seeds/budgets are not recorded. All reference checks are limited, not full feasibility certificates.");
}

function renderReferenceAudit() {
  const plan = state.currentPayload.reference_plan;
  textField("audit-summary", `${plan.assignments.length} planned · ${plan.unassigned_tasks.length} unassigned · ${plan.checks.issues.length} discrepancies`);
  const excluded = plan.unassigned_tasks.map((id) => auditItem(id, "source unassigned", "Not selected by the imported plan. A causal exclusion reason was not recorded; no reason is inferred."));
  if (!excluded.length) excluded.push(auditItem("No unassigned tasks", "source partition", "Every source task has an assignment."));
  const capacity = Math.max(1, Math.floor(elements.unscheduledList.clientHeight / 69));
  elements.unscheduledList.replaceChildren(...pageItems("unscheduled", excluded, capacity));
  const checks = [auditItem("Full feasibility not verified", "limited scope", `Not checked: ${plan.checks.not_checked.join(", ")}.`, "audit-warning")];
  plan.checks.issues.forEach((issue) => checks.push(auditItem(issue.task_id || "Source reconciliation", issue.code, issue.message, "audit-error")));
  plan.checks.checked.forEach((check) => checks.push(auditItem(check, "checked", "Checked against pinned source IDs, windows and plan data; not a full physical validation.", "audit-margin")));
  elements.validationList.replaceChildren(...pageItems("validation", checks, Math.max(1, Math.floor(elements.validationList.clientHeight / 69))));
  textField("audit-methodology", "Source hashes and structural consistency checked. No independent certificate of attitude transitions, resource constraints, sensor geometry, battery dynamics or downlink.");
}

function renderReferenceGantt() {
  if (!elements.timeline.clientWidth || !elements.timeline.clientHeight) return;
  const {scenario, reference_plan: plan} = state.currentPayload;
  const width = elements.timeline.clientWidth;
  const height = elements.timeline.clientHeight;
  const left = width < 600 ? 100 : 155;
  const top = 8;
  const bottom = 25;
  const plotWidth = width - left - 14;
  const horizon = scenario.horizon_end_s;
  const x = (time) => left + time / horizon * plotWidth;
  const satelliteFilter = document.getElementById("satellite-filter").value;
  const satellites = scenario.satellites.filter((satellite) => satelliteFilter === "all" || satellite.satellite_id === satelliteFilter);
  const lanes = pageItems("timeline", satellites, Math.max(1, Math.floor((height - top - bottom) / 29)));
  const root = chart(width, height, "Satellite observation timeline", "UTC source task intervals; all satellites including zero-workload satellites remain reachable through pagination. Minimum display widths do not change actual durations.");
  root.setAttribute("preserveAspectRatio", "none");
  for (let tick = 0; tick <= 4; tick += 1) {
    const time = horizon * tick / 4;
    root.append(svgElement("line", {x1: x(time), x2: x(time), y1: top, y2: height - bottom, class: "chart-grid"}));
    root.append(svgElement("text", {x: x(time), y: height - 8, "text-anchor": "middle", class: "chart-axis"}, timeLabel(time).slice(0, 5)));
  }
  const selectedTask = scenario.tasks.find((task) => task.task_id === state.selectedTaskId);
  const visibleIds = new Set(filteredTasks(scenario).map((task) => task.task_id));
  lanes.forEach((satellite, index) => {
    const rowY = top + index * 29;
    const row = svgElement("g", {class: "satellite-lane", "data-satellite-id": satellite.satellite_id});
    row.append(svgElement("rect", {x: 0, y: rowY, width, height: 27, class: "row-band", opacity: index % 2 ? 0 : 1}));
    row.append(svgElement("text", {x: 5, y: rowY + 12, class: "task-label"}, satellite.satellite_id.split("_")[0].slice(0, width < 600 ? 12 : 22)));
    const assignments = plan.assignments.filter((assignment) => assignment.satellite_id === satellite.satellite_id);
    row.append(svgElement("text", {x: 5, y: rowY + 23, class: "task-sublabel"}, `${assignments.length} tasks · ${plan.workloads[satellite.satellite_id]}s`));
    selectedTask?.visibility_windows.filter((window) => window.satellite_id === satellite.satellite_id).forEach((window) => {
      const bar = svgElement("rect", {x: x(window.start_s), y: rowY + 5, width: Math.max(1, x(window.end_s) - x(window.start_s)), height: 18, class: "window-bar"});
      bar.append(svgElement("title", {}, `${selectedTask.task_id} · ${window.window_id} · ${timeLabel(window.start_s)}–${timeLabel(window.end_s)} UTC`));
      row.append(bar);
    });
    assignments.filter((assignment) => visibleIds.has(assignment.task_id)).forEach((assignment) => {
      const selected = assignment.task_id === state.selectedTaskId;
      const bar = svgElement("rect", {x: x(assignment.start_s), y: rowY + (selected ? 6 : 9), width: Math.max(selected ? 4 : 2, x(assignment.end_s) - x(assignment.start_s)), height: selected ? 16 : 10,
        rx: 1, class: "task-bar", "data-task-id": assignment.task_id, "data-state": taskState(assignment.task_id), role: "button", tabindex: 0,
        "aria-label": `${assignment.task_id} on ${satellite.satellite_id}, ${timeLabel(assignment.start_s)} UTC, ${(assignment.end_s - assignment.start_s).toFixed(0)} seconds`});
      if (selected) { bar.setAttribute("stroke", "#fff"); bar.setAttribute("stroke-width", "1"); }
      bar.append(svgElement("title", {}, `${assignment.task_id} · ${satellite.satellite_id}\n${timeLabel(assignment.start_s)}–${timeLabel(assignment.end_s)} UTC\nActual duration: ${assignment.end_s - assignment.start_s}s. Display width may be enlarged.`));
      bar.addEventListener("click", () => selectTarget(assignment.task_id));
      bar.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); selectTarget(assignment.task_id); } });
      row.append(bar);
    });
    root.append(row);
  });
  root.append(svgElement("line", {x1: x(state.replay.time), x2: x(state.replay.time), y1: top, y2: height - bottom, class: "time-cursor", "data-left": left, "data-width": plotWidth}));
  elements.timeline.replaceChildren(root);
}

function renderWorkloads() {
  const {reference_plan: plan, scenario} = state.currentPayload;
  const width = Math.max(180, elements.resources.clientWidth);
  const height = Math.max(65, elements.resources.clientHeight);
  const capacity = Math.max(2, Math.min(8, Math.floor((height - 22) / 19)));
  const selected = state.assignments.get(state.selectedTaskId)?.satellite_id;
  const sorted = scenario.satellites.map((satellite) => ({id: satellite.satellite_id, load: plan.workloads[satellite.satellite_id]})).sort((a, b) => b.load - a.load || a.id.localeCompare(b.id));
  const rows = sorted.slice(0, capacity);
  if (selected && !rows.some((row) => row.id === selected)) rows[rows.length - 1] = sorted.find((row) => row.id === selected);
  const maximum = Math.max(1, ...sorted.map((row) => row.load));
  const root = chart(width, height, "Satellite observation workload", "Highest-workload satellites plus the selected satellite. All satellites are available in the timeline. Source observation durations in seconds, not battery or storage traces.");
  rows.forEach((row, index) => {
    const y = 4 + index * 19;
    root.append(svgElement("text", {x: 0, y: y + 10, class: "chart-axis"}, row.id.split("_")[0].slice(0, 11)));
    root.append(svgElement("rect", {x: 81, y, width: row.load / maximum * (width - 115), height: 11, rx: 1, class: `workload-bar${row.id === selected ? " is-selected" : ""}`}));
    root.append(svgElement("text", {x: width - 1, y: y + 10, "text-anchor": "end", class: "chart-axis"}, `${row.load}s`));
  });
  root.append(svgElement("text", {x: 0, y: height - 3, class: "chart-axis"}, `Top ${capacity}${selected ? " + selection" : ""} · ${sorted.filter((row) => !row.load).length} idle satellites`));
  elements.resources.replaceChildren(root);
}

function renderSourceDiagnostics() {
  const payload = state.currentPayload;
  textField("learning-title", "Reference data provenance");
  textField("learning-kicker", "Source diagnostics");
  elements.learningLegend.replaceChildren();
  const width = Math.max(240, elements.learning.clientWidth);
  const height = Math.max(80, elements.learning.clientHeight);
  const root = chart(width, height, "Reference data provenance", "Pinned source commit and file hashes, retained source orbit samples, original visibility windows and limited verification scope.");
  const records = [
    `EOS-Bench @ ${payload.provenance.revision.slice(0, 12)} · ${payload.provenance.files.length} hash-verified files`,
    `${payload.scenario.satellites.length} satellites · ${payload.scenario.tasks.length} tasks · ${payload.provenance.window_count} source windows`,
    `Source Orekit Keplerian samples · stride ${payload.replay.sample_stride} · WGS84`,
    "UTC epoch explicit · all task intervals half-open · no invented battery traces",
    "Full feasibility not independently verified; see Constraint audit for scope",
  ];
  const lineHeight = Math.min(24, (height - 12) / records.length);
  records.forEach((text, index) => root.append(svgElement("text", {x: 7, y: 12 + index * lineHeight, class: "chart-axis"}, text)));
  elements.learning.replaceChildren(root);
}

function setupReferenceGlobe(viewer, Cesium) {
  const payload = state.currentPayload;
  const epoch = Cesium.JulianDate.fromIso8601(payload.scenario.epoch_utc);
  viewer.clock.currentTime = epoch;
  payload.replay.orbits.forEach((orbit, index) => {
    const position = new Cesium.SampledPositionProperty();
    orbit.samples.forEach(([time, lon, lat, altitude]) => position.addSample(Cesium.JulianDate.addSeconds(epoch, time, new Cesium.JulianDate()), Cesium.Cartesian3.fromDegrees(lon, lat, altitude)));
    position.setInterpolationOptions({interpolationDegree: 1, interpolationAlgorithm: Cesium.LinearApproximation});
    state.orbitPositions.set(orbit.satellite_id, position);
    const color = Cesium.Color.fromHsl((index * 0.618) % 1, 0.55, 0.65);
    viewer.entities.add({id: `orbit-${orbit.satellite_id}`, position, path: {show: state.layers.track, leadTime: 0, trailTime: orbit.period_s, resolution: 30, width: 1.25, material: color.withAlpha(0.65)}});
    viewer.entities.add({id: `satellite-${orbit.satellite_id}`, position, point: {pixelSize: 6, color, outlineColor: Cesium.Color.WHITE, outlineWidth: 1}, label: {show: false, text: orbit.satellite_id, font: "10px sans-serif", fillColor: color, pixelOffset: new Cesium.Cartesian2(0, -15)}});
  });
  payload.scenario.tasks.forEach((task) => {
    viewer.entities.add({id: `target-${task.task_id}`, name: task.task_id, position: Cesium.Cartesian3.fromDegrees(task.target.longitude_deg, task.target.latitude_deg, task.target.altitude_m),
      point: {pixelSize: 5, color: Cesium.Color.fromCssColorString(stateColor(task.task_id)), outlineWidth: 0},
      label: {show: state.layers.labels || task.task_id === state.selectedTaskId, text: task.task_id, font: "11px sans-serif", fillColor: Cesium.Color.WHITE, pixelOffset: new Cesium.Cartesian2(8, -10)}});
  });
  state.cameraHome = {missionCenter: new Cesium.BoundingSphere(Cesium.Cartesian3.ZERO, 7100000), global: true, longitudeCenter: 30, latitudeCenter: 10};
  fitMissionView();
  elements.globe.dataset.engine = "cesium";
  document.querySelector(".view-tag").textContent = "3D";
  elements.globeLoading.classList.add("is-hidden");
  updateGlobeLayers();
  updateReplayVisuals();
}

function updateCesiumReplay(active) {
  const viewer = state.globe;
  const Cesium = window.Cesium;
  const payload = state.currentPayload;
  if (payload.scenario.epoch_utc) viewer.clock.currentTime = Cesium.JulianDate.addSeconds(Cesium.JulianDate.fromIso8601(payload.scenario.epoch_utc), state.replay.time, new Cesium.JulianDate());
  payload.scenario.tasks.forEach((task) => {
    const entity = viewer.entities.getById(`target-${task.task_id}`);
    if (entity?.point) entity.point.color = Cesium.Color.fromCssColorString(stateColor(task.task_id));
  });
  const selectedSatellite = state.assignments.get(state.selectedTaskId)?.satellite_id;
  for (const entity of viewer.entities.values) {
    if (entity.id.startsWith("satellite-") && entity.label) entity.label.show = entity.id === `satellite-${selectedSatellite}` || state.layers.labels;
    if (entity.id.startsWith("satellite-") && entity.point) entity.point.pixelSize = entity.id === `satellite-${selectedSatellite}` ? 10 : 6;
    if (entity.id.startsWith("orbit-") && entity.path) entity.path.width = entity.id === `orbit-${selectedSatellite}` ? 2.5 : 1.25;
  }
  const activeIds = new Set(active.map((assignment) => `ray-${assignment.task_id}`));
  viewer.entities.values.filter((entity) => entity.id.startsWith("ray-") && !activeIds.has(entity.id)).forEach((entity) => viewer.entities.remove(entity));
  active.forEach((assignment) => {
    const position = state.orbitPositions.get(assignment.satellite_id);
    const target = viewer.entities.getById(`target-${assignment.task_id}`)?.position;
    if (!position || !target) return;
    const id = `ray-${assignment.task_id}`;
    if (!viewer.entities.getById(id)) viewer.entities.add({id, polyline: {positions: new Cesium.PositionPropertyArray([position, target]), width: 2, arcType: Cesium.ArcType.NONE, material: Cesium.Color.fromCssColorString("#f7d074")}});
    viewer.entities.getById(id).show = state.layers.rays;
  });
  viewer.scene.requestRender();
}

function addFallbackOrbits(map) {
  const group = svgElement("g", {class: "fallback-orbits"});
  state.currentPayload.replay.orbits.forEach((orbit) => {
    group.append(svgElement("g", {class: "map-orbit", "data-satellite-id": orbit.satellite_id}));
    group.append(svgElement("circle", {class: "map-satellite", "data-satellite-id": orbit.satellite_id, r: 3}));
  });
  map.append(group);
  map.append(svgElement("g", {class: "fallback-rays"}));
}

function updateFallbackReplay(active) {
  const payload = state.currentPayload;
  const project = (lon, lat) => [(lon + 180) / 360 * 1000, (90 - lat) / 180 * 500];
  const positions = new Map();
  payload.replay.orbits.forEach((orbit) => {
    const point = window.OrbitReplay.point(orbit.samples, state.replay.time);
    const [x, y] = project(point[0], point[1]);
    positions.set(orbit.satellite_id, [x, y]);
    const marker = document.querySelector(`.map-satellite[data-satellite-id="${CSS.escape(orbit.satellite_id)}"]`);
    marker?.setAttribute("cx", x);
    marker?.setAttribute("cy", y);
    const group = document.querySelector(`.map-orbit[data-satellite-id="${CSS.escape(orbit.satellite_id)}"]`);
    if (!group) return;
    group.style.display = state.layers.track ? "" : "none";
    const end = window.OrbitReplay.sampleIndex(orbit.samples, state.replay.time);
    const start = window.OrbitReplay.sampleIndex(orbit.samples, Math.max(0, state.replay.time - orbit.period_s));
    const segments = [[]];
    orbit.samples.slice(start, end + 1).forEach((sample, index, samples) => {
      if (index && Math.abs(sample[1] - samples[index - 1][1]) > 180) segments.push([]);
      segments.at(-1).push(project(sample[1], sample[2]).join(","));
    });
    group.replaceChildren(...segments.map((points) => svgElement("polyline", {points: points.join(" ")})));
  });
  const rays = document.querySelector(".fallback-rays");
  if (!rays) return;
  rays.replaceChildren(...active.flatMap((assignment) => {
    const origin = positions.get(assignment.satellite_id);
    const target = payload.scenario.tasks.find((task) => task.task_id === assignment.task_id)?.target;
    if (!origin || !target) return [];
    const [x, y] = project(target.longitude_deg, target.latitude_deg);
    // Avoid a misleading line across the date-line seam in this projection.
    if (Math.abs(origin[0] - x) > 500) return [];
    const ray = svgElement("line", {x1: origin[0], y1: origin[1], x2: x, y2: y, class: "map-ray", "data-task-id": assignment.task_id});
    ray.style.display = state.layers.rays ? "" : "none";
    return [ray];
  }));
}

function bindMissionControls() {
  document.getElementById("replay-play").addEventListener("click", () => {
    if (!state.currentPayload) return;
    if (state.replay.playing) { pauseReplay(); return; }
    if (state.replay.time >= state.currentPayload.scenario.horizon_end_s) setReplayTime(state.currentPayload.scenario.horizon_start_s);
    state.replay.playing = true;
    state.replay.lastFrame = 0;
    const button = document.getElementById("replay-play");
    button.textContent = "Ⅱ";
    button.setAttribute("aria-pressed", "true");
    button.setAttribute("aria-label", "Pause mission replay");
    requestAnimationFrame(animateReplay);
  });
  document.getElementById("replay-reset").addEventListener("click", () => setReplayTime(state.currentPayload?.scenario.horizon_start_s || 0, true));
  document.getElementById("replay-scrub").addEventListener("input", (event) => setReplayTime(event.target.value, true));
  document.getElementById("replay-speed").addEventListener("change", (event) => { state.replay.speed = Number(event.target.value); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) pauseReplay(); });
  for (const id of ["target-search", "target-filter", "satellite-filter"]) {
    document.getElementById(id).addEventListener(id === "target-search" ? "input" : "change", () => {
      state.pages.target = 0;
      state.pages.timeline = 0;
      refreshPanels();
    });
  }
}
