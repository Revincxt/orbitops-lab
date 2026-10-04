"use strict";

function timeLabel(seconds) {
  return window.OrbitReplay.utc(state.currentPayload?.scenario.epoch_utc, seconds);
}

function taskState(taskId) {
  const task = state.taskById.get(taskId);
  const scenario = state.currentPayload?.scenario;
  if (scenario && (state.replay.time < scenario.horizon_start_s || state.replay.time >= scenario.horizon_end_s)) {
    return state.assignments.has(taskId) ? (state.replay.time < scenario.horizon_start_s ? "Planned" : "Completed") : "Unassigned";
  }
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
  releaseCameraTracking();
  state.cameraMode = "overview";
  state.orbitEmphasis = false;
  if (!payload.replay?.orbits.some((orbit) => orbit.satellite_id === state.selectedSatelliteId)) state.selectedSatelliteId = null;
  document.getElementById("globe-hover").hidden = true;
  closeSatelliteDetails();
  state.replay.playing = false;
  state.replay.time = payload.scenario.horizon_start_s;
  state.replay.lastFrame = 0;
  state.replay.direction = 1;
  state.replay.windowStart = payload.scenario.horizon_start_s;
  state.replay.windowEnd = payload.scenario.horizon_end_s;
  state.orbitModels = new Map(payload.replay.orbits.map((orbit) => [orbit.satellite_id,
    window.OrbitModel.create(orbit, payload.scenario.satellites.find((satellite) => satellite.satellite_id === orbit.satellite_id).orbital_params)]));
  updateReplayDirection();
  setReplayPickerOpen(false);
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
    option.textContent = satelliteName(satellite.satellite_id);
    option.title = satellite.satellite_id;
    return option;
  });
  selector.replaceChildren(all, ...options);
  if (options.some((option) => option.value === previous)) selector.value = previous;
  selector.hidden = payload.mode !== "reference";
  document.getElementById("target-search").value = "";
  document.getElementById("target-filter").value = "all";
  setPlaybackControl(false);
}

function setReplayTime(time, pause = false) {
  if (!state.currentPayload) return false;
  const value = Number(time);
  if (!validReplayTime(value)) {
    pauseReplay();
    state.replay.timeError = true;
    elements.statusIndicator.classList.add("is-error");
    elements.status.classList.add("error");
    elements.status.textContent = "Enter a valid UTC time (years 0001–9999).";
    return false;
  }
  if (state.replay.timeError) {
    state.replay.timeError = false;
    elements.statusIndicator.classList.remove("is-error");
    elements.status.classList.remove("error");
    elements.status.textContent = `${state.currentPayload.reference_plan.label} · Ready`;
  }
  state.replay.time = value;
  if (pause) pauseReplay();
  updateReplayVisuals();
  return true;
}

function validReplayTime(time) {
  if (!Number.isFinite(time)) return false;
  const date = new Date(Date.parse(state.currentPayload.scenario.epoch_utc) + time * 1000);
  return Number.isFinite(date.getTime()) && date.getUTCFullYear() >= 1 && date.getUTCFullYear() <= 9999;
}

function updateReplayWindow() {
  const replay = state.replay;
  const scenario = state.currentPayload.scenario;
  const width = scenario.horizon_end_s - scenario.horizon_start_s;
  if (replay.time < replay.windowStart || replay.time > replay.windowEnd) {
    replay.windowStart = scenario.horizon_start_s + Math.floor((replay.time - scenario.horizon_start_s) / width) * width;
    replay.windowEnd = replay.windowStart + width;
  }
  const slider = document.getElementById("replay-scrub");
  slider.min = replay.windowStart;
  slider.max = replay.windowEnd;
  slider.value = replay.time;
  slider.setAttribute("aria-valuetext", window.OrbitReplay.utc(scenario.epoch_utc, replay.time, true));
  slider.title = `${window.OrbitReplay.utc(scenario.epoch_utc, replay.windowStart, true)} → ${window.OrbitReplay.utc(scenario.epoch_utc, replay.windowEnd, true)}`;
}

function shiftReplayWindow(direction) {
  if (!state.currentPayload) return;
  const width = state.currentPayload.scenario.horizon_end_s - state.currentPayload.scenario.horizon_start_s;
  const time = state.replay.time + direction * width;
  if (!validReplayTime(time)) return setReplayTime(time, true);
  state.replay.windowStart += direction * width;
  state.replay.windowEnd += direction * width;
  setReplayTime(time, true);
}

function updateReplayDirection() {
  const button = document.getElementById("replay-direction");
  const reversed = state.replay.direction < 0;
  button.setAttribute("aria-pressed", String(reversed));
  button.setAttribute("aria-label", reversed ? "Switch to forward playback" : "Switch to reverse playback");
  button.title = reversed ? "Playing backwards" : "Playing forwards";
}

function setReplayPickerOpen(open) {
  const picker = document.getElementById("replay-time-picker");
  picker.hidden = !open;
  document.getElementById("replay-time-button").setAttribute("aria-expanded", String(open));
  if (open) {
    pauseReplay();
    const input = document.getElementById("replay-utc-input");
    input.value = new Date(Date.parse(state.currentPayload.scenario.epoch_utc) + state.replay.time * 1000).toISOString().slice(0, 19);
    input.focus();
  }
}

function pauseReplay() {
  state.replay.playing = false;
  state.replay.lastFrame = 0;
  setPlaybackControl(false);
}

function setPlaybackControl(playing) {
  const button = document.getElementById("replay-play");
  const icon = svgElement("svg", {"aria-hidden": "true", viewBox: "0 0 24 24"});
  icon.append(svgElement("use", {href: playing ? "#i-pause" : "#i-play"}));
  button.replaceChildren(icon);
  button.setAttribute("aria-pressed", String(playing));
  button.setAttribute("aria-label", playing ? "Pause mission replay" : "Play mission replay");
}

function animateReplay(timestamp) {
  if (!state.replay.playing || !state.currentPayload) return;
  const elapsed = state.replay.lastFrame ? Math.min(0.25, (timestamp - state.replay.lastFrame) / 1000) : 0;
  state.replay.lastFrame = timestamp;
  const next = state.replay.time + elapsed * state.replay.speed * state.replay.direction;
  if (!validReplayTime(next)) { setReplayTime(next, true); return; }
  state.replay.time = next;
  if (timestamp - state.replay.lastPaint > 100) {
    updateReplayVisuals();
    state.replay.lastPaint = timestamp;
  }
  requestAnimationFrame(animateReplay);
}

function updateReplayVisuals() {
  const payload = state.currentPayload;
  if (!payload) return;
  const time = state.replay.time;
  const missionActive = payload.scenario.horizon_start_s <= time && time < payload.scenario.horizon_end_s;
  const active = missionActive ? [...state.assignments.values()].filter((assignment) =>
    time >= assignment.start_s && time < assignment.end_s) : [];
  const extended = time < payload.scenario.horizon_start_s || time > payload.scenario.horizon_end_s;
  document.getElementById("orbit-basis").hidden = !extended;
  elements.globe.dataset.orbitBasis = extended ? "estimated" : "source";
  textField("replay-time", window.OrbitReplay.utc(payload.scenario.epoch_utc, time, true));
  document.getElementById("replay-time").dateTime = new Date(Date.parse(payload.scenario.epoch_utc) + time * 1000).toISOString();
  document.getElementById("replay-time-button").title = extended ? "UTC · estimated two-body orbit · no task execution. Click to jump to a time." : "UTC · source samples. Click to jump to a time.";
  updateReplayWindow();
  if (state.selectedTaskId) {
    const selectedState = taskState(state.selectedTaskId);
    textField("selected-state", selectedState);
    document.getElementById("selected-state").dataset.state = selectedState;
  }
  document.querySelectorAll(".target-row, .map-marker").forEach((node) => {
    const current = taskState(node.dataset.taskId);
    node.dataset.state = current;
    const label = node.querySelector(".target-state");
    if (label) label.textContent = current;
  });
  document.querySelectorAll(".task-bar[data-task-id]").forEach((node) => { node.dataset.state = taskState(node.dataset.taskId); });
  const cursor = document.querySelector(".time-cursor");
  if (cursor) {
    cursor.toggleAttribute("hidden", extended);
    const x = Number(cursor.dataset.left) + (time - payload.scenario.horizon_start_s) / (payload.scenario.horizon_end_s - payload.scenario.horizon_start_s) * Number(cursor.dataset.width);
    if (Number.isFinite(x)) { cursor.setAttribute("x1", x); cursor.setAttribute("x2", x); }
  }
  if (state.globe) updateCesiumReplay(active);
  else if (payload.replay) updateFallbackReplay(active);
  updateOrbitHud();
  if (document.getElementById("target-filter").value === "active") renderTargetCatalog();
}

function stateColor(taskId) {
  return TASK_COLORS[taskState(taskId)];
}

function configureModeDetails(payload) {
  document.querySelector(".slew-legend").hidden = true;
  textField("timeline-title", "Observation · UTC");
  const loads = Object.values(payload.reference_plan.workloads);
  textField("energy-readout", `${loads.filter((load) => load > 0).length}/${loads.length}`);
  textField("storage-readout", `${loads.reduce((a, b) => a + b, 0).toFixed(0)} s`);
}

function renderEvaluation(payload) {
  const evaluation = payload.evaluation || {};
  const reference = payload.mode === "reference";
  textField("metric-balance", evaluation.BD == null ? "N/A · single satellite" : evaluation.BD.toFixed(3));
  textField("metric-runtime", `${payload.result.runtime_s.toFixed(3)} s${reference ? " · source" : ""}`);
  textField("metric-motion", payload.result.metrics.total_slew_time_s == null ? "Not recorded" : `${payload.result.metrics.total_slew_time_s.toFixed(1)} s`);
  textField("metric-objective", reference ? objectiveLabel(payload.reference_plan.objective) : "TP → task count → −slew");
  if (reference) document.getElementById("metric-objective").title = payload.reference_plan.objective;
  textField("metric-basis", reference ? "Recomputed TP/TCR/TM/BD" : "Shared simulator replay");
}

function objectiveLabel(objective) {
  // Presentation only: exact source coefficients remain in the title and payload.
  return {
    "profit=.25 completion=.25 timeliness=.25 balance=.25": "Equal weights",
    "profit=1 completion=0 timeliness=0 balance=0": "Profit only",
    "implicit profit-first": "Profit-first",
  }[objective] || objective;
}

const RADAR_AXES = [
  { key: "TP", label: "TP ↑", name: "Total profit", scale: "TP / highest TP across the four source plans", format: (value) => value.toFixed(0) },
  { key: "TCR", label: "TCR ↑", name: "Task completion rate", scale: "Original completion fraction, 0–1", format: (value) => `${(value * 100).toFixed(1)}%` },
  { key: "TM", label: "TM ↓", name: "Timeliness", scale: "1 − TM; lower source TM is better", format: (value) => value.toFixed(3) },
  { key: "RT", label: "RT ↓", name: "Source solver runtime", scale: "Fastest source RT / RT; lower runtime is better", format: (value) => `${value.toFixed(1)}s` },
  { key: "BD", label: "BD ↑", name: "Workload balance", scale: "Original balance score, 0–1", format: (value) => value.toFixed(3) },
];

// Display-only scales, not an aggregate score. Keep natural 0–1 metrics so a
// slightly lower completion rate is not misleadingly drawn as zero completion.
function radarSeries(plans) {
  const values = plans.map((plan) => ({ ...plan.recomputed_metrics, RT: plan.source_metrics.RT }));
  const maxTP = Math.max(0, ...values.map((metrics) => Number.isFinite(metrics.TP) ? metrics.TP : 0));
  const runtimes = values.map((metrics) => metrics.RT).filter((value) => Number.isFinite(value) && value >= 0);
  const minRT = runtimes.length ? Math.min(...runtimes) : 0;
  return plans.map((plan, index) => ({
    plan, metrics: RADAR_AXES.map((axis) => {
      const raw = values[index][axis.key];
      if (!Number.isFinite(raw) || raw < 0) return { ...axis, raw: null, score: null };
      const score = axis.key === "TP" ? (maxTP ? raw / maxTP : 0)
        : axis.key === "TM" ? 1 - raw
        : axis.key === "RT" ? (raw === 0 ? 1 : minRT / raw) : raw;
      return { ...axis, raw, score: Math.max(0, Math.min(1, score)) };
    }),
  }));
}

function renderReferenceComparison() {
  const plans = state.referenceData.plans;
  const selectedId = state.currentPayload.reference_plan.plan_id;
  const series = radarSeries(plans);
  const colors = ["#6ad6ee", "#edc78a", "#75d9b6", "#bca9f5"];
  const dashes = ["", "5 2", "2 2", "7 2 1 2"];
  const selected = series.find((item) => item.plan.plan_id === selectedId);
  const summary = (item) => item.metrics.map((metric) => `${metric.key} ${metric.raw === null ? "N/A" : metric.format(metric.raw)}`).join(" · ");
  const description = "Outward is better on five 0–1 display scales: TP / best TP, TCR, 1 − TM, fastest RT / RT, BD. Different objectives; no overall ranking. Runtime is the recorded source solver runtime.";
  const width = Math.max(160, elements.comparisonChart.clientWidth);
  const height = Math.max(120, elements.comparisonChart.clientHeight);
  const cx = width / 2, cy = height / 2 + 7;
  const radius = Math.max(26, Math.min((width - 62) / 2, (height - 46) / 2));
  const position = (index, distance) => {
    const angle = -Math.PI / 2 + index * Math.PI * 2 / RADAR_AXES.length;
    return [cx + Math.cos(angle) * distance, cy + Math.sin(angle) * distance];
  };
  const points = (scores) => scores.map((score, index) => position(index, radius * score).join(",")).join(" ");
  const root = chart(width, height, "Optimization algorithm comparison", `${description} Selected: ${selected.plan.label}, ${summary(selected)}.`);
  for (const scale of [.25, .5, .75, 1]) {
    root.append(svgElement("polygon", { points: points(RADAR_AXES.map(() => scale)), class: `radar-grid${scale === 1 ? " radar-boundary" : ""}` }));
  }
  RADAR_AXES.forEach((axis, index) => {
    const [x, y] = position(index, radius);
    root.append(svgElement("line", { x1: cx, y1: cy, x2: x, y2: y, class: "radar-grid" }));
    const [labelX, labelY] = position(index, radius + 17);
    const label = svgElement("text", { x: labelX, y: labelY, "text-anchor": "middle", "dominant-baseline": "middle", class: "radar-axis" }, axis.label);
    label.append(svgElement("title", {}, `${axis.name} · ${axis.scale}`));
    root.append(label);
  });
  // Paint the active plan last; all four remain visible, with distinct dashes
  // as well as colours. Polygons and vertices never alter source metric values.
  [...series].sort((a, b) => Number(a.plan.plan_id === selectedId) - Number(b.plan.plan_id === selectedId)).forEach((item) => {
    const index = plans.indexOf(item.plan);
    const active = item.plan.plan_id === selectedId;
    const group = svgElement("g", { class: `radar-series${active ? " is-selected" : ""}`, "data-plan-id": item.plan.plan_id });
    // CSSOM updates are compatible with the local server's strict style CSP.
    group.style.setProperty("--series-color", colors[index % colors.length]);
    group.append(svgElement("title", {}, `${item.plan.label} · ${summary(item)}\nObjective: ${item.plan.objective}\nReference consistency only, not full feasibility.`));
    if (item.metrics.every((metric) => metric.score !== null)) {
      group.append(svgElement("polygon", { points: points(item.metrics.map((metric) => metric.score)), class: "radar-area", "stroke-dasharray": dashes[index % dashes.length] }));
    }
    item.metrics.forEach((metric, axisIndex) => {
      if (metric.score === null) return;
      const [x, y] = position(axisIndex, radius * metric.score);
      const dot = svgElement("circle", { cx: x, cy: y, r: active ? 2.5 : 1.5, class: "radar-point", "data-metric": metric.key, "data-raw": metric.raw, "data-score": metric.score });
      dot.append(svgElement("title", {}, `${item.plan.label} · ${metric.name}: ${metric.format(metric.raw)}\n${metric.scale}`));
      group.append(dot);
    });
    root.append(group);
  });
  elements.comparisonChart.replaceChildren(root);
  if (elements.comparisonLegend.childElementCount !== plans.length) {
    elements.comparisonLegend.replaceChildren(...series.map((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.planId = item.plan.plan_id;
      button.style.setProperty("--series-color", colors[index % colors.length]);
      button.title = `${item.plan.label} · ${summary(item)}\nObjective: ${item.plan.objective}\nReference consistency only; no overall ranking or full feasibility claim.`;
      const swatch = document.createElement("span");
      swatch.className = "radar-swatch";
      swatch.setAttribute("aria-hidden", "true");
      swatch.style.borderTopStyle = index ? "dashed" : "solid";
      const label = document.createElement("span");
      label.textContent = item.plan.label;
      button.append(swatch, label);
      button.addEventListener("click", () => {
        if (elements.solver.value === item.plan.plan_id) return;
        elements.solver.value = item.plan.plan_id;
        loadReferencePlan();
      });
      return button;
    }));
  }
  elements.comparisonLegend.querySelectorAll("button").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.planId === selectedId));
    button.disabled = state.busy;
  });
  elements.comparisonValues.setAttribute("aria-label", `${selected.plan.label} raw metrics`);
  elements.comparisonValues.replaceChildren(...selected.metrics.map((metric) => {
    const field = document.createElement("div");
    field.title = `${metric.name} · ${metric.scale}`;
    const label = document.createElement("dt");
    label.textContent = metric.label;
    const value = document.createElement("dd");
    value.textContent = metric.raw === null ? "N/A" : metric.format(metric.raw);
    field.append(label, value);
    return field;
  }));
}

function renderReferenceGantt() {
  if (!elements.timeline.clientWidth || !elements.timeline.clientHeight) return;
  const {scenario, reference_plan: plan} = state.currentPayload;
  const width = elements.timeline.clientWidth;
  const height = elements.timeline.clientHeight;
  const left = width < 600 ? 128 : 155;
  const top = 8;
  const bottom = 25;
  const rowHeight = layoutSize("timeline-row-height");
  const plotWidth = width - left - 14;
  const horizon = scenario.horizon_end_s;
  const x = (time) => left + time / horizon * plotWidth;
  const satelliteFilter = document.getElementById("satellite-filter").value;
  const satellites = scenario.satellites.filter((satellite) => satelliteFilter === "all" || satellite.satellite_id === satelliteFilter);
  const lanes = pageItems("timeline", satellites, Math.max(1, Math.floor((height - top - bottom) / rowHeight)));
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
    const rowY = top + index * rowHeight;
    const row = svgElement("g", {class: "satellite-lane", "data-satellite-id": satellite.satellite_id});
    row.append(svgElement("title", {}, satellite.satellite_id));
    row.append(svgElement("rect", {x: 0, y: rowY, width, height: rowHeight - 2, rx: 3, class: "row-band", opacity: index % 2 ? 0 : 1}));
    row.append(svgElement("text", {x: 5, y: rowY + 13, class: "task-label"}, satelliteName(satellite.satellite_id)));
    const assignments = plan.assignments.filter((assignment) => assignment.satellite_id === satellite.satellite_id);
    row.append(svgElement("text", {x: 5, y: rowY + 27, class: "task-sublabel"}, `${assignments.length} tasks · ${plan.workloads[satellite.satellite_id]} s`));
    selectedTask?.visibility_windows.filter((window) => window.satellite_id === satellite.satellite_id).forEach((window) => {
      const bar = svgElement("rect", {x: x(window.start_s), y: rowY + 6, width: Math.max(1, x(window.end_s) - x(window.start_s)), height: 20, class: "window-bar"});
      bar.append(svgElement("title", {}, `${selectedTask.task_id} · ${window.window_id} · ${timeLabel(window.start_s)}–${timeLabel(window.end_s)} UTC`));
      row.append(bar);
    });
    assignments.filter((assignment) => visibleIds.has(assignment.task_id)).forEach((assignment) => {
      const selected = assignment.task_id === state.selectedTaskId;
      const bar = svgElement("rect", {x: x(assignment.start_s), y: rowY + (selected ? 7 : 10), width: Math.max(selected ? 4 : 2, x(assignment.end_s) - x(assignment.start_s)), height: selected ? 18 : 12,
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
  const rowHeight = layoutSize("workload-row-height");
  const capacity = Math.max(1, Math.min(scenario.satellites.length, Math.floor(height / rowHeight)));
  const labelWidth = Math.min(108, width * .43);
  const barWidth = width - labelWidth - 34;
  const focusedSatellite = elements.resources.contains(document.activeElement) ? document.activeElement.dataset.satelliteId : null;
  const selected = state.selectedSatelliteId;
  const sorted = scenario.satellites.map((satellite) => ({id: satellite.satellite_id, load: plan.workloads[satellite.satellite_id]})).sort((a, b) => b.load - a.load || a.id.localeCompare(b.id));
  const rows = sorted.slice(0, capacity);
  if (selected && !rows.some((row) => row.id === selected)) rows[rows.length - 1] = sorted.find((row) => row.id === selected);
  const maximum = Math.max(1, ...sorted.map((row) => row.load));
  const root = chart(width, height, "Satellite observation workload", "Highest-workload satellites plus the selected satellite. All satellites are available in the timeline. Source observation durations in seconds, not battery or storage traces.");
  rows.forEach((row, index) => {
    const y = 7 + index * rowHeight;
    const group = svgElement("g", {class: "workload-row", role: "button", tabindex: 0, "aria-label": `${row.id}: ${row.load} seconds`, "aria-pressed": String(row.id === selected), "data-satellite-id": row.id});
    group.append(svgElement("title", {}, `${row.id} · ${row.load} s`));
    group.append(svgElement("rect", {x: 0, y: y - 6, width, height: rowHeight, class: "workload-row-band"}));
    group.append(svgElement("text", {x: 0, y: y + 10, class: "chart-axis"}, satelliteName(row.id)));
    group.append(svgElement("rect", {x: labelWidth, y: y + 1, width: barWidth, height: 8, rx: 2, class: "workload-track"}));
    group.append(svgElement("rect", {x: labelWidth, y: y + 1, width: row.load / maximum * barWidth, height: 8, rx: 2, class: `workload-bar${row.id === selected ? " is-selected" : ""}`}));
    group.append(svgElement("text", {x: width - 1, y: y + 10, "text-anchor": "end", class: "chart-axis"}, `${row.load}`));
    group.addEventListener("click", () => selectSatellite(row.id));
    group.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); selectSatellite(row.id); } });
    root.append(group);
  });
  elements.resources.replaceChildren(root);
  if (focusedSatellite) elements.resources.querySelector(`[data-satellite-id="${CSS.escape(focusedSatellite)}"]`)?.focus({preventScroll: true});
}

const ORBIT_PALETTE = ["#79cfff", "#f4c078", "#a6d68b", "#c9a5f4", "#79d8ca", "#f09ea9", "#87acf5", "#e1d286", "#83c6a7", "#e1a3d0", "#abcee6", "#e3ad7d", "#b8bfef", "#8dd3e5", "#d5dc95", "#dc9ea2", "#a8d0c2", "#bea7db", "#a8bdf0", "#e8c59b"];

function orbitColor(id) {
  const index = state.currentPayload?.replay?.orbits.findIndex((orbit) => orbit.satellite_id === id) ?? -1;
  return ORBIT_PALETTE[Math.max(0, index) % ORBIT_PALETTE.length];
}

function satelliteName(id) {
  return id.replace(/_\d+$/, "").replaceAll("_", " ");
}

function satelliteAltitude(orbit) {
  const position = state.globe && state.orbitPositions.get(orbit.satellite_id)?.getValue(state.globe.clock.currentTime);
  return position ? window.Cesium.Cartographic.fromCartesian(position).height : state.orbitModels.get(orbit.satellite_id).point(state.replay.time)[2];
}

function satelliteGlyph() {
  // A screen-space engineering symbol, not a physical spacecraft/attitude model.
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 40;
  const context = canvas.getContext("2d");
  context.translate(20, 20);
  context.rotate(-Math.PI / 7);
  context.strokeStyle = "#08111a";
  context.lineWidth = 2;
  context.fillStyle = "#fff";
  for (const x of [-17, 7]) {
    context.fillRect(x, -7, 10, 14);
    context.strokeRect(x, -7, 10, 14);
    context.beginPath();
    context.moveTo(x + 5, -7); context.lineTo(x + 5, 7);
    context.moveTo(x, 0); context.lineTo(x + 10, 0);
    context.stroke();
  }
  context.fillRect(-5, -10, 10, 20);
  context.strokeRect(-5, -10, 10, 20);
  return canvas;
}

function updateSolarEnvironment() {
  const viewer = state.globe;
  if (!viewer) return;
  const Cesium = window.Cesium;
  const visible = state.layers.illumination && !state.viewTransition && viewer.scene.mode === Cesium.SceneMode.SCENE3D;
  viewer.scene.globe.enableLighting = visible;
  viewer.scene.sun.show = visible;
}

function clearSensorFovs() {
  if (state.globe && state.fovPrimitives) state.globe.scene.primitives.remove(state.fovPrimitives);
  state.fovPrimitives = null;
  state.sensorFovs.clear();
}

function addSensorFov(viewer, Cesium, orbit, color) {
  if (!state.fovPrimitives) state.fovPrimitives = viewer.scene.primitives.add(new Cesium.PrimitiveCollection());
  const instance = (geometry, alpha) => new Cesium.GeometryInstance({geometry, id: `sensor-${orbit.satellite_id}`,
    attributes: {color: Cesium.ColorGeometryInstanceAttribute.fromColor(color.withAlpha(alpha))}});
  const options = {length: 1, topRadius: 0, bottomRadius: 1, slices: 48};
  const solid = state.fovPrimitives.add(new Cesium.Primitive({
    geometryInstances: instance(new Cesium.CylinderGeometry({...options,
      vertexFormat: Cesium.PerInstanceColorAppearance.FLAT_VERTEX_FORMAT}), .035),
    appearance: new Cesium.PerInstanceColorAppearance({flat: true, translucent: true, closed: false}),
    asynchronous: false, allowPicking: false, show: false,
  }));
  const wire = state.fovPrimitives.add(new Cesium.Primitive({
    geometryInstances: instance(new Cesium.CylinderOutlineGeometry({...options, numberOfVerticalLines: 4}), .16),
    appearance: new Cesium.PerInstanceColorAppearance({flat: true, translucent: true}),
    asynchronous: false, allowPicking: false, show: false,
  }));
  const sensor = {solid, wire, frame: null, time: null};
  sensor.footprint = viewer.entities.add({id: `fov-${orbit.satellite_id}`, show: false,
    polygon: {
      hierarchy: new Cesium.ConstantProperty(),
      height: 15, material: color.withAlpha(.02), outline: true,
      outlineColor: color.withAlpha(.22), arcType: Cesium.ArcType.GEODESIC,
    }});
  state.sensorFovs.set(orbit.satellite_id, sensor);
}

function updateSensorFovs() {
  if (!state.globe || !state.fovPrimitives) return;
  const viewer = state.globe, Cesium = window.Cesium;
  const visible = state.layers.fov && !state.viewTransition;
  // A transformed local cone is meaningful only on the native 3D globe.
  // Unfolded views retain the georeferenced footprint instead of a distorted cone.
  state.fovPrimitives.show = visible && viewer.scene.mode === Cesium.SceneMode.SCENE3D;
  if (!visible) {
    for (const sensor of state.sensorFovs.values()) sensor.footprint.show = false;
    return;
  }
  for (const [id, sensor] of state.sensorFovs) {
    if (sensor.time && Cesium.JulianDate.equals(sensor.time, viewer.clock.currentTime)) {
      sensor.footprint.show = Boolean(sensor.frame);
      continue;
    }
    const position = state.orbitPositions.get(id)?.getValue(viewer.clock.currentTime);
    const frame = position && window.SensorFov.frame([position.x, position.y, position.z]);
    sensor.time = Cesium.JulianDate.clone(viewer.clock.currentTime, sensor.time || new Cesium.JulianDate());
    sensor.frame = frame;
    sensor.footprint.show = visible && Boolean(frame);
    sensor.solid.show = sensor.wire.show = Boolean(frame);
    if (!frame) { sensor.footprint.polygon.hierarchy.setValue(undefined); continue; }
    const rotation = Cesium.Matrix3.fromArray([...frame.right, ...frame.north, ...frame.up]);
    const matrix = Cesium.Matrix4.fromRotationTranslation(rotation, Cesium.Cartesian3.fromArray(frame.center));
    Cesium.Matrix4.multiplyByScale(matrix, new Cesium.Cartesian3(frame.radius, frame.radius, frame.length), matrix);
    Cesium.Matrix4.clone(matrix, sensor.solid.modelMatrix);
    Cesium.Matrix4.clone(matrix, sensor.wire.modelMatrix);
    sensor.footprint.polygon.hierarchy.setValue(new Cesium.PolygonHierarchy(
      frame.footprint.map((point) => Cesium.Cartesian3.fromArray(point))));
  }
}

function setupReferenceGlobe(viewer, Cesium) {
  const payload = state.currentPayload;
  const epoch = Cesium.JulianDate.fromIso8601(payload.scenario.epoch_utc);
  viewer.clock.startTime = Cesium.JulianDate.clone(epoch);
  viewer.clock.stopTime = Cesium.JulianDate.addSeconds(epoch, payload.scenario.horizon_end_s, new Cesium.JulianDate());
  viewer.clock.currentTime = Cesium.JulianDate.addSeconds(epoch, state.replay.time, new Cesium.JulianDate());
  viewer.clock.clockRange = Cesium.ClockRange.UNBOUNDED;
  viewer.clock.shouldAnimate = false;
  const symbol = satelliteGlyph();
  payload.replay.orbits.forEach((orbit, index) => {
    const sampled = new Cesium.SampledPositionProperty();
    orbit.samples.forEach(([time, lon, lat, altitude]) => sampled.addSample(Cesium.JulianDate.addSeconds(epoch, time, new Cesium.JulianDate()), Cesium.Cartesian3.fromDegrees(lon, lat, altitude)));
    sampled.setInterpolationOptions({interpolationDegree: 1, interpolationAlgorithm: Cesium.LinearApproximation});
    const model = state.orbitModels.get(orbit.satellite_id);
    const extension = new Cesium.CallbackPositionProperty((time, result) => {
      const seconds = Cesium.JulianDate.secondsDifference(time, epoch);
      return Cesium.Cartesian3.fromArray(model.cartesian(seconds), 0, result);
    }, false, Cesium.ReferenceFrame.FIXED);
    const start = Cesium.JulianDate.addSeconds(epoch, model.sourceStart, new Cesium.JulianDate());
    const stop = Cesium.JulianDate.addSeconds(epoch, model.sourceEnd, new Cesium.JulianDate());
    const position = new Cesium.CompositePositionProperty(Cesium.ReferenceFrame.FIXED);
    position.intervals.addInterval(new Cesium.TimeInterval({start: Cesium.Iso8601.MINIMUM_VALUE, stop: start, isStopIncluded: false, data: extension}));
    position.intervals.addInterval(new Cesium.TimeInterval({start, stop, data: sampled}));
    position.intervals.addInterval(new Cesium.TimeInterval({start: stop, stop: Cesium.Iso8601.MAXIMUM_VALUE, isStartIncluded: false, data: extension}));
    state.orbitPositions.set(orbit.satellite_id, position);
    const color = Cesium.Color.fromCssColorString(ORBIT_PALETTE[index % ORBIT_PALETTE.length]);
    const styles = {};
    for (const [name, alpha] of [["normal", .65], ["selected", .95], ["dimmed", .28]]) {
      styles[name] = {
        past: new Cesium.PolylineGlowMaterialProperty({color: color.withAlpha(alpha), glowPower: .08}),
        future: new Cesium.PolylineDashMaterialProperty({color: color.withAlpha(alpha * .75), dashLength: 14}),
      };
    }
    state.orbitStyles.set(orbit.satellite_id, styles);
    addSensorFov(viewer, Cesium, orbit, color);
    const bounds = windowForOrbit(orbit);
    viewer.entities.add({id: `orbit-${orbit.satellite_id}`, position,
      path: {show: state.layers.track && bounds.past > 0, leadTime: 0, trailTime: bounds.past, resolution: 15, width: 1.4, material: styles.normal.past}});
    viewer.entities.add({id: `orbit-preview-${orbit.satellite_id}`, position,
      path: {show: state.layers.track && bounds.future > 0, leadTime: bounds.future, trailTime: 0, resolution: 15, width: 1.4, material: styles.normal.future}});
    viewer.entities.add({id: `satellite-${orbit.satellite_id}`, name: orbit.satellite_id, position,
      viewFrom: new Cesium.Cartesian3(-1800000, -1800000, 1600000),
      billboard: {image: symbol, width: 22, height: 22, color, disableDepthTestDistance: 0,
        scaleByDistance: new Cesium.NearFarScalar(500000, 1.3, 50000000, .75)},
      point: {show: false, pixelSize: 23, color: color.withAlpha(.15), outlineColor: color, outlineWidth: 1, disableDepthTestDistance: 0},
      label: {show: state.layers.satelliteLabels, text: satelliteName(orbit.satellite_id), font: '500 12px "Inter", sans-serif', fillColor: color,
        showBackground: true, backgroundColor: Cesium.Color.fromCssColorString("#0a1420").withAlpha(.8),
        backgroundPadding: new Cesium.Cartesian2(5, 3), horizontalOrigin: Cesium.HorizontalOrigin.LEFT,
        pixelOffset: new Cesium.Cartesian2(14, -10), disableDepthTestDistance: 0,
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 55000000)}});
  });
  payload.scenario.tasks.forEach((task) => {
    viewer.entities.add({id: `target-${task.task_id}`, name: task.task_id, position: Cesium.Cartesian3.fromDegrees(task.target.longitude_deg, task.target.latitude_deg, task.target.altitude_m),
      point: {pixelSize: 4, color: Cesium.Color.fromCssColorString(stateColor(task.task_id)).withAlpha(.85), outlineColor: Cesium.Color.fromCssColorString("#102333"), outlineWidth: .5, disableDepthTestDistance: 0},
      label: {show: state.layers.labels || task.task_id === state.selectedTaskId, text: task.task_id, font: '600 12px "Inter", sans-serif', fillColor: Cesium.Color.WHITE,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE, outlineColor: Cesium.Color.fromCssColorString("#08111a"), outlineWidth: 3,
        pixelOffset: new Cesium.Cartesian2(9, -13), disableDepthTestDistance: 0,
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, task.task_id === state.selectedTaskId ? Infinity : 3500000)}});
  });
  const altitude = Math.max(...payload.replay.orbits.map((orbit) => Math.max(...orbit.samples.map((sample) => sample[3]))));
  state.cameraHome = {missionCenter: new Cesium.BoundingSphere(Cesium.Cartesian3.ZERO, Cesium.Ellipsoid.WGS84.maximumRadius + altitude), global: true, longitudeCenter: 105, latitudeCenter: 20};
  fitMissionView();
  elements.globe.dataset.engine = "cesium";
  updateMapViewControls();
  elements.globeLoading.classList.add("is-hidden");
  updateGlobeLayers();
  updateReplayVisuals();
}

function windowForOrbit(orbit) {
  const half = orbit.period_s / 2;
  return {start: state.replay.time - half, end: state.replay.time + half, past: half, future: half};
}

function updateCesiumReplay(active) {
  const viewer = state.globe;
  const Cesium = window.Cesium;
  const payload = state.currentPayload;
  if (payload.scenario.epoch_utc) viewer.clock.currentTime = Cesium.JulianDate.addSeconds(Cesium.JulianDate.fromIso8601(payload.scenario.epoch_utc), state.replay.time, new Cesium.JulianDate());
  payload.scenario.tasks.forEach((task) => {
    const entity = viewer.entities.getById(`target-${task.task_id}`);
    const current = taskState(task.task_id);
    if (entity?.point && state.entityTaskStates.get(task.task_id) !== current) {
      entity.point.color = Cesium.Color.fromCssColorString(stateColor(task.task_id)).withAlpha(.85);
      state.entityTaskStates.set(task.task_id, current);
    }
  });
  if (payload.replay) {
    const selectionKey = `${state.selectedSatelliteId}:${state.selectedTaskId}:${state.layers.labels}:${state.layers.satelliteLabels}:${state.orbitEmphasis}`;
    const changed = selectionKey !== state.geometrySelectionKey;
    payload.replay.orbits.forEach((orbit) => {
      const bounds = windowForOrbit(orbit);
      const selected = orbit.satellite_id === state.selectedSatelliteId;
      const past = viewer.entities.getById(`orbit-${orbit.satellite_id}`)?.path;
      const future = viewer.entities.getById(`orbit-preview-${orbit.satellite_id}`)?.path;
      if (!past || !future) return;
      past.trailTime = bounds.past;
      future.leadTime = bounds.future;
      past.show = state.layers.track && bounds.past > 0;
      future.show = state.layers.track && bounds.future > 0;
      if (changed) {
        const styles = state.orbitStyles.get(orbit.satellite_id)[selected ? "selected" : state.selectedSatelliteId && state.orbitEmphasis ? "dimmed" : "normal"];
        past.material = styles.past;
        future.material = styles.future;
        past.width = future.width = selected ? 2.5 : 1.4;
        const entity = viewer.entities.getById(`satellite-${orbit.satellite_id}`);
        entity.billboard.width = entity.billboard.height = selected ? 30 : 22;
        entity.point.show = selected;
        entity.label.show = selected || state.layers.satelliteLabels;
        entity.label.distanceDisplayCondition = new Cesium.DistanceDisplayCondition(0, selected ? Infinity : 55000000);
      }
    });
    if (changed) {
      payload.scenario.tasks.forEach((task) => {
        const entity = viewer.entities.getById(`target-${task.task_id}`);
        const selected = task.task_id === state.selectedTaskId;
        entity.point.pixelSize = selected ? 10 : 4;
        entity.point.outlineWidth = selected ? 2 : .5;
        entity.label.show = selected || state.layers.labels;
        entity.label.distanceDisplayCondition = new Cesium.DistanceDisplayCondition(0, selected ? Infinity : 3500000);
      });
      state.geometrySelectionKey = selectionKey;
      if (state.cameraMode === "follow") followSelectedSatellite();
    }
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
  updateSensorFovs();
  updateSolarEnvironment();
  updatePlanarFollow();
  viewer.scene.requestRender();
}

function addFallbackOrbits(map) {
  const group = svgElement("g", {class: "fallback-orbits"});
  const footprints = svgElement("g", {class: "fallback-fovs"});
  state.currentPayload.replay.orbits.forEach((orbit) => {
    const footprint = svgElement("g", {class: "map-fov", "data-satellite-id": orbit.satellite_id});
    footprint.style.stroke = orbitColor(orbit.satellite_id);
    footprints.append(footprint);
  });
  map.append(footprints);
  state.currentPayload.replay.orbits.forEach((orbit) => {
    const track = svgElement("g", {class: "map-orbit", "data-satellite-id": orbit.satellite_id});
    track.style.stroke = orbitColor(orbit.satellite_id);
    group.append(track);
    const marker = svgElement("g", {class: "map-satellite", "data-satellite-id": orbit.satellite_id, role: "button", tabindex: "0", "aria-label": `Inspect satellite ${orbit.satellite_id}`});
    marker.style.color = orbitColor(orbit.satellite_id);
    marker.append(svgElement("path", {d: "M-8-3H-3V-5H3V-3H8V3H3V5H-3V3H-8Z"}));
    marker.append(svgElement("title", {}, orbit.satellite_id));
    marker.append(svgElement("text", {x: 11, y: -7, class: "satellite-label"}, satelliteName(orbit.satellite_id)));
    marker.addEventListener("click", () => selectSatellite(orbit.satellite_id));
    marker.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectSatellite(orbit.satellite_id); }
    });
    group.append(marker);
  });
  map.append(group);
  map.append(svgElement("g", {class: "fallback-rays"}));
}

function updateFallbackReplay(active) {
  const payload = state.currentPayload;
  const project = (lon, lat) => [(lon + 180) / 360 * 1000, (90 - lat) / 180 * 500];
  const positions = new Map();
  payload.replay.orbits.forEach((orbit) => {
    const model = state.orbitModels.get(orbit.satellite_id);
    const point = model.point(state.replay.time);
    const footprint = document.querySelector(`.map-fov[data-satellite-id="${CSS.escape(orbit.satellite_id)}"]`);
    if (footprint) {
      const frame = window.SensorFov.frame(window.OrbitModel.toCartesian(point));
      footprint.style.display = state.layers.fov && frame ? "" : "none";
      const samples = frame ? [...frame.footprint, frame.footprint[0]].map((sample, i) => [i, ...window.OrbitModel.toGeodetic(sample)]) : [];
      const paths = samples.length ? window.OrbitReplay.trackSegments(samples, 0, samples.length - 1).map((segment) =>
        svgElement("polyline", {points: segment.map((sample) => project(sample[1], sample[2]).join(",")).join(" ")})) : [];
      footprint.replaceChildren(...paths);
    }
    const [x, y] = project(point[0], point[1]);
    positions.set(orbit.satellite_id, [x, y]);
    const marker = document.querySelector(`.map-satellite[data-satellite-id="${CSS.escape(orbit.satellite_id)}"]`);
    marker?.setAttribute("transform", `translate(${x},${y})`);
    const selected = orbit.satellite_id === state.selectedSatelliteId;
    marker?.classList.toggle("is-selected", selected);
    marker?.setAttribute("aria-pressed", String(selected));
    if (marker) marker.querySelector("text").style.display = selected || state.layers.satelliteLabels ? "" : "none";
    const group = document.querySelector(`.map-orbit[data-satellite-id="${CSS.escape(orbit.satellite_id)}"]`);
    if (!group) return;
    group.style.display = state.layers.track ? "" : "none";
    group.classList.toggle("is-selected", selected);
    group.classList.toggle("is-dimmed", Boolean(state.selectedSatelliteId && state.orbitEmphasis && !selected));
    const bounds = windowForOrbit(orbit);
    const samples = model.trackSamples(bounds.start, bounds.end);
    const paths = [["past", bounds.start, state.replay.time], ["future", state.replay.time, bounds.end]].flatMap(([kind, start, end]) =>
      window.OrbitReplay.trackSegments(samples, start, end).map((segment) => svgElement("polyline", {class: `map-track-${kind}`, points: segment.map((sample) => project(sample[1], sample[2]).join(",")).join(" ")})));
    group.replaceChildren(...paths);
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

function releaseCameraTracking() {
  if (!state.globe || !window.Cesium) return;
  state.globe.trackedEntity = undefined;
  if (!state.viewTransition) state.globe.camera.lookAtTransform(window.Cesium.Matrix4.IDENTITY);
}

function selectSatellite(id) {
  if (!state.currentPayload?.replay?.orbits.some((orbit) => orbit.satellite_id === id)) return;
  state.selectedSatelliteId = id;
  state.satelliteDetailsOpen = true;
  state.orbitEmphasis = true;
  updateReplayVisuals();
  renderWorkloads();
  if (!document.getElementById("pane-timeline").hidden) renderGantt(state.currentPayload.scenario, state.currentPayload.result);
}

function updateOrbitHud() {
  const reference = state.currentPayload?.mode === "reference";
  const orbit = state.currentPayload?.replay?.orbits.find((item) => item.satellite_id === state.selectedSatelliteId);
  document.getElementById("orbit-hud").hidden = !reference || !orbit || !state.satelliteDetailsOpen || state.viewTransition;
  const available = Boolean(!state.viewTransition && orbit && state.globe?.entities.getById(`satellite-${orbit.satellite_id}`));
  document.getElementById("camera-follow").disabled = !available;
  document.getElementById("north-view").disabled = !state.globe || state.viewTransition;
  updateCameraCompass();
  document.getElementById("camera-overview").disabled = !state.globe || state.viewTransition;
  document.getElementById("reset-view").disabled = state.viewTransition;
  for (const mode of ["overview", "follow"]) document.getElementById(`camera-${mode}`).setAttribute("aria-pressed", String(state.cameraMode === mode));
  document.getElementById("camera-follow").title = state.cameraMode === "follow" ? "Stop following satellite" : "Follow selected satellite";
  if (!reference) return;
  textField("satellite-name", orbit ? satelliteName(orbit.satellite_id) : "Select a satellite");
  document.getElementById("satellite-name").title = orbit?.satellite_id || "Pick a satellite symbol or select an assigned task";
  document.getElementById("satellite-swatch").style.backgroundColor = orbit ? orbitColor(orbit.satellite_id) : "#596777";
  if (orbit) {
    textField("satellite-altitude", `${(satelliteAltitude(orbit) / 1000).toFixed(1)} km`);
    textField("satellite-period", `${(orbit.period_s / 60).toFixed(1)} min`);
  } else {
    textField("satellite-altitude", "— km");
    textField("satellite-period", "— min");
  }
  positionSatelliteDetails();
}

function closeSatelliteDetails() {
  state.satelliteDetailsOpen = false;
  document.getElementById("orbit-hud").hidden = true;
}

function positionSatelliteDetails() {
  const hud = document.getElementById("orbit-hud");
  if (!state.satelliteDetailsOpen || state.viewTransition) { hud.hidden = true; return; }
  let point;
  if (state.globe) {
    const Cesium = window.Cesium, viewer = state.globe;
    const position = state.orbitPositions.get(state.selectedSatelliteId)?.getValue(viewer.clock.currentTime);
    const visible = position && (state.viewMode !== "3d" || new Cesium.EllipsoidalOccluder(
      Cesium.Ellipsoid.WGS84, viewer.camera.positionWC).isPointVisible(position));
    if (visible) point = Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene, position);
  } else {
    const marker = document.querySelector(`.map-satellite[data-satellite-id="${CSS.escape(state.selectedSatelliteId || "")}"]`);
    const matrix = marker?.getScreenCTM(), rect = elements.globe.getBoundingClientRect();
    if (matrix) point = {x: matrix.e - rect.left, y: matrix.f - rect.top};
  }
  const width = elements.globe.clientWidth, height = elements.globe.clientHeight;
  if (!point || point.x < 0 || point.x > width || point.y < 0 || point.y > height) { hud.hidden = true; return; }
  hud.hidden = false;
  // Leave the symbol unobstructed so the second click of a double-click still
  // reaches Cesium. The popup's responsive max-width guarantees side clearance.
  const preferredX = point.x + hud.offsetWidth + 12 <= width - 12 ? point.x + 12 : point.x - hud.offsetWidth - 12;
  hud.style.left = `${Math.max(12, Math.min(width - hud.offsetWidth - 12, preferredX))}px`;
  hud.style.top = `${Math.max(12, Math.min(height - hud.offsetHeight - 12, point.y + 16))}px`;
}

function cameraMotionDuration() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : .65;
}

function focusSelectedSatellite() {
  const viewer = state.globe;
  const Cesium = window.Cesium;
  if (!viewer || !Cesium || state.viewTransition) return;
  const position = state.orbitPositions.get(state.selectedSatelliteId)?.getValue(viewer.clock.currentTime);
  if (!position) return;
  releaseCameraTracking();
  state.cameraMode = "manual";
  state.orbitEmphasis = true;
  const range = window.OrbitReplay.fitRange(1000000, viewer.camera.frustum.fovy || Cesium.Math.PI_OVER_THREE, elements.globe.clientWidth / Math.max(1, elements.globe.clientHeight), 1.1);
  viewer.camera.flyToBoundingSphere(new Cesium.BoundingSphere(position, 1000000), {
    duration: cameraMotionDuration(), offset: new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(state.viewMode === "2d" ? -90 : -65), range),
  });
  viewer.scene.requestRender();
  updateOrbitHud();
  updateReplayVisuals();
}

function followSelectedSatellite() {
  if (state.viewTransition) return;
  const viewer = state.globe;
  const entity = viewer?.entities.getById(`satellite-${state.selectedSatelliteId}`);
  if (!entity || !entity.position.getValue(viewer.clock.currentTime)) return;
  state.cameraMode = "follow";
  state.orbitEmphasis = true;
  viewer.camera.cancelFlight();
  if (state.viewMode === "2d") {
    // In 2D, track the source sub-satellite position without an ENU camera transform.
    // Native EntityView retains a 3D local offset that can move the whole map offscreen.
    releaseCameraTracking();
    updatePlanarFollow();
  } else if (viewer.trackedEntity !== entity) viewer.trackedEntity = entity;
  viewer.scene.requestRender();
  updateOrbitHud();
}

function updatePlanarFollow() {
  const viewer = state.globe;
  if (!viewer || state.viewTransition || state.viewMode !== "2d" || state.cameraMode !== "follow") return;
  const Cesium = window.Cesium;
  const position = state.orbitPositions.get(state.selectedSatelliteId)?.getValue(viewer.clock.currentTime);
  if (!position) return;
  const target = Cesium.Cartographic.fromCartesian(position);
  const height = Math.max(15000, viewer.camera.positionCartographic.height);
  viewer.camera.setView({destination: Cesium.Cartesian3.fromRadians(target.longitude, target.latitude, height),
    orientation: {heading: 0, pitch: -Cesium.Math.PI_OVER_TWO, roll: 0}});
}

function pickedMissionObject(viewer, point) {
  let first = viewer.scene.pick(point)?.id;
  if (first?.id?.startsWith("fov-")) {
    first = viewer.scene.drillPick(point, 10).find((hit) => !hit.id?.id?.startsWith("fov-"))?.id;
  }
  // Observation links/paths can share a pixel with their satellite symbol.
  // Prefer the actual symbol there, without disabling depth testing.
  const satellite = typeof first?.id === "string" && !first.billboard && (first.id.startsWith("orbit-") || first.id.startsWith("ray-"))
    ? viewer.scene.drillPick(point, 5).find((hit) => hit.id?.billboard)?.id : null;
  const id = (satellite || first)?.id;
  if (typeof id !== "string") return null;
  for (const prefix of ["target-", "ray-"]) if (id.startsWith(prefix)) return {kind: "task", id: id.slice(prefix.length)};
  for (const prefix of ["satellite-", "orbit-preview-", "orbit-"]) if (id.startsWith(prefix)) return {kind: "satellite", id: id.slice(prefix.length)};
  return null;
}

function bindGlobePicking(viewer, Cesium) {
  const tooltip = document.getElementById("globe-hover");
  const inspect = (point, focus = false) => {
    if (state.viewTransition) return;
    const picked = pickedMissionObject(viewer, point);
    if (!picked) { closeSatelliteDetails(); return; }
    tooltip.hidden = true;
    if (picked.kind === "task") selectTarget(picked.id);
    else selectSatellite(picked.id);
    if (focus) focusSelectedSatellite();
  };
  viewer.screenSpaceEventHandler.setInputAction((event) => inspect(event.position), Cesium.ScreenSpaceEventType.LEFT_CLICK);
  viewer.screenSpaceEventHandler.setInputAction((event) => inspect(event.position, true), Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
  let lastPick = 0;
  let hoverTimer;
  const hover = (point) => {
    if (viewer.isDestroyed() || state.viewTransition) return;
    lastPick = performance.now();
    const picked = pickedMissionObject(viewer, point);
    tooltip.hidden = !picked;
    viewer.canvas.style.cursor = picked ? "pointer" : "grab";
    if (!picked) return;
    if (picked.kind === "task") tooltip.textContent = `${picked.id} · ${taskState(picked.id)}`;
    else {
      if (state.satelliteDetailsOpen && picked.id === state.selectedSatelliteId) { tooltip.hidden = true; return; }
      const orbit = state.currentPayload?.replay?.orbits.find((item) => item.satellite_id === picked.id);
      if (!orbit) { tooltip.hidden = true; return; }
      tooltip.textContent = `${satelliteName(picked.id)} · ${(satelliteAltitude(orbit) / 1000).toFixed(1)} km`;
    }
    tooltip.style.left = `${Math.max(8, Math.min(elements.globe.clientWidth - 288, point.x + 15))}px`;
    tooltip.style.top = `${Math.max(8, Math.min(elements.globe.clientHeight - 36, point.y + 15))}px`;
  };
  viewer.screenSpaceEventHandler.setInputAction((event) => {
    clearTimeout(hoverTimer);
    const point = Cesium.Cartesian2.clone(event.endPosition);
    hoverTimer = setTimeout(() => hover(point), Math.max(0, 80 - (performance.now() - lastPick)));
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
  viewer.canvas.addEventListener("mouseleave", () => { clearTimeout(hoverTimer); tooltip.hidden = true; });
  viewer.camera.percentageChanged = .01;
  viewer.camera.changed.addEventListener(() => {
    updateCameraCompass();
    positionSatelliteDetails();
    clearTimeout(hoverTimer);
    tooltip.hidden = true;
  });
  // Camera.changed is thresholded; small turns can leave overlays stale while
  // playback is paused. Read the final rendered camera in every camera mode,
  // without requesting another frame or changing the replay clock.
  viewer.scene.postRender.addEventListener(() => {
    updateCameraCompass();
    if (state.satelliteDetailsOpen) positionSatelliteDetails();
  });
}

function updateCameraCompass() {
  if (state.viewTransition) return;
  const compass = document.getElementById("north-view");
  let bearing = 0;
  if (state.globe) {
    const Cesium = window.Cesium, {camera, scene} = state.globe;
    if (scene.mode === Cesium.SceneMode.MORPHING) return;
    // Heading alone misses screen roll in tilted views. Project geographic north
    // onto the rendered camera's right/up axes, including tracked transforms.
    // In unfolded scenes world +Z is map north, not an Earth-fixed ENU tangent.
    let north = Cesium.Cartesian3.UNIT_Z;
    if (scene.mode === Cesium.SceneMode.SCENE3D) {
      const {latitude, longitude} = camera.positionCartographic;
      north = {x: -Math.sin(latitude) * Math.cos(longitude),
        y: -Math.sin(latitude) * Math.sin(longitude), z: Math.cos(latitude)};
    }
    const right = Cesium.Cartesian3.dot(north, camera.rightWC);
    const up = Cesium.Cartesian3.dot(north, camera.upWC);
    // North can be parallel to the view ray. Retain the last valid bearing
    // instead of flashing an arbitrary angle or writing NaN into the SVG.
    if (!Number.isFinite(right) || !Number.isFinite(up) || Math.hypot(right, up) < 1e-7) return;
    bearing = (Cesium.Math.toDegrees(Math.atan2(-right, up)) + 360) % 360;
  }
  const angle = (Math.round(bearing * 100) / 100 % 360).toFixed(2);
  if (compass.dataset.heading === angle) return;
  compass.dataset.heading = angle;
  // Rotate the rose toward geographic north; counter-rotate N to keep it legible.
  compass.querySelector(".compass-rose").setAttribute("transform", `rotate(${-angle} 24 24)`);
  compass.querySelector(".compass-north-label").setAttribute("transform", `rotate(${angle} 24 9)`);
  const display = `${Math.round(bearing) % 360}°`;
  compass.setAttribute("aria-label", `Face north, current heading ${display}`);
}

const MAP_VIEWS = {"3d": {label: "3D", method: "morphTo3D"}, "2.5d": {label: "2.5D", method: "morphToColumbusView"}, "2d": {label: "2D", method: "morphTo2D"}};

function updateMapViewControls() {
  const viewer = state.globe;
  if (viewer && !state.viewTransition) {
    state.viewMode = viewer.scene.mode === window.Cesium.SceneMode.SCENE2D ? "2d" : viewer.scene.mode === window.Cesium.SceneMode.COLUMBUS_VIEW ? "2.5d" : "3d";
  } else if (!viewer) {
    state.viewMode = "2d";
    state.viewTransition = false;
  }
  elements.globe.dataset.viewMode = state.viewTransition ? "morphing" : state.viewMode;
  elements.globe.setAttribute("aria-busy", String(state.viewTransition));
  for (const button of document.querySelectorAll(".map-projections button")) {
    button.setAttribute("aria-pressed", String(button.dataset.view === state.viewMode));
    button.disabled = !viewer || state.viewTransition;
  }
  document.getElementById("map-projections").title = viewer ? "Native Cesium scene views · same source data and replay clock" : "2D schematic fallback · 3D engine unavailable";
  document.getElementById("toggle-illumination").disabled = !viewer || state.viewTransition || state.viewMode !== "3d";
  updateSolarEnvironment();
}

function bindMapViewEvents(viewer) {
  viewer.scene.morphStart.addEventListener(() => {
    state.viewTransition = true;
    updateSensorFovs();
    updateSolarEnvironment();
    document.getElementById("globe-hover").hidden = true;
    updateMapViewControls();
    updateOrbitHud();
  });
  viewer.scene.morphComplete.addEventListener(() => {
    state.viewTransition = false;
    updateMapViewControls();
    fitMissionView();
  });
  updateMapViewControls();
}

function setMapViewMode(mode) {
  const viewer = state.globe;
  if (!viewer || state.viewTransition || !MAP_VIEWS[mode] || mode === state.viewMode) return;
  viewer.camera.cancelFlight();
  releaseCameraTracking();
  state.cameraMode = "overview";
  state.orbitEmphasis = false;
  viewer.scene[MAP_VIEWS[mode].method](cameraMotionDuration());
  viewer.scene.requestRender();
}

function bindOrbitControls() {
  document.getElementById("close-satellite-details").addEventListener("click", closeSatelliteDetails);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.satelliteDetailsOpen) closeSatelliteDetails();
  });
  for (const button of document.querySelectorAll(".map-projections button")) button.addEventListener("click", () => setMapViewMode(button.dataset.view));
  document.getElementById("camera-overview").addEventListener("click", () => fitMissionView(cameraMotionDuration()));
  document.getElementById("camera-follow").addEventListener("click", () => {
    if (state.cameraMode === "follow") {
      releaseCameraTracking();
      state.cameraMode = "manual";
      updateOrbitHud();
    } else {
      followSelectedSatellite();
      updateReplayVisuals();
    }
  });
  document.getElementById("toggle-sat-labels").addEventListener("click", (event) => {
    state.layers.satelliteLabels = !state.layers.satelliteLabels;
    event.currentTarget.setAttribute("aria-pressed", String(state.layers.satelliteLabels));
    updateReplayVisuals();
  });
  document.getElementById("north-view").addEventListener("click", () => {
    if (!state.globe) return;
    const viewer = state.globe;
    viewer.camera.cancelFlight();
    releaseCameraTracking();
    if (state.cameraMode === "follow") state.cameraMode = "manual";
    viewer.camera.setView({orientation: {heading: 0, pitch: viewer.camera.pitch, roll: 0}});
    viewer.scene.requestRender();
    updateOrbitHud();
  });
  document.getElementById("expand-map").addEventListener("click", (event) => {
    const expanded = event.currentTarget.getAttribute("aria-expanded") !== "true";
    event.currentTarget.setAttribute("aria-expanded", String(expanded));
    event.currentTarget.setAttribute("aria-label", expanded ? "Restore analysis dock" : "Expand map pane");
    event.currentTarget.title = expanded ? "Restore analysis dock" : "Expand map pane";
    elements.shell.dataset.mapExpanded = String(expanded);
    requestAnimationFrame(() => {
      state.globe?.resize();
      if (state.cameraMode === "overview") fitMissionView();
      refreshPanels();
    });
  });
}

function bindMissionControls() {
  document.getElementById("replay-play").addEventListener("click", () => {
    if (!state.currentPayload) return;
    if (state.replay.playing) { pauseReplay(); return; }
    state.replay.playing = true;
    state.replay.lastFrame = 0;
    setPlaybackControl(true);
    requestAnimationFrame(animateReplay);
  });
  document.getElementById("replay-reset").addEventListener("click", () => {
    if (!state.currentPayload) return;
    state.replay.windowStart = state.currentPayload.scenario.horizon_start_s;
    state.replay.windowEnd = state.currentPayload.scenario.horizon_end_s;
    setReplayTime(state.currentPayload.scenario.horizon_start_s, true);
  });
  document.getElementById("replay-direction").addEventListener("click", () => {
    state.replay.direction *= -1;
    state.replay.lastFrame = 0;
    updateReplayDirection();
  });
  document.getElementById("replay-window-prev").addEventListener("click", () => shiftReplayWindow(-1));
  document.getElementById("replay-window-next").addEventListener("click", () => shiftReplayWindow(1));
  document.getElementById("replay-time-button").addEventListener("click", () => {
    if (state.currentPayload) setReplayPickerOpen(document.getElementById("replay-time-picker").hidden);
  });
  document.getElementById("replay-time-picker").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = document.getElementById("replay-utc-input");
    const time = (Date.parse(input.value + "Z") - Date.parse(state.currentPayload.scenario.epoch_utc)) / 1000;
    if (input.reportValidity() && setReplayTime(time, true)) {
      setReplayPickerOpen(false);
      document.getElementById("replay-time-button").focus();
    }
  });
  document.addEventListener("click", (event) => {
    if (!document.getElementById("replay-time-picker").contains(event.target) && !document.getElementById("replay-time-button").contains(event.target)) setReplayPickerOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !document.getElementById("replay-time-picker").hidden) {
      setReplayPickerOpen(false);
      document.getElementById("replay-time-button").focus();
    }
  });
  document.getElementById("replay-scrub").addEventListener("input", (event) => setReplayTime(event.target.value, true));
  document.getElementById("replay-speed").addEventListener("change", (event) => { state.replay.speed = Number(event.target.value); });
  bindOrbitControls();
  document.addEventListener("visibilitychange", () => { if (document.hidden) pauseReplay(); });
  for (const id of ["target-search", "target-filter", "satellite-filter"]) {
    document.getElementById(id).addEventListener(id === "target-search" ? "input" : "change", () => {
      elements.targetList.scrollTop = 0;
      state.pages.timeline = 0;
      if (id === "satellite-filter" && document.getElementById(id).value !== "all") selectSatellite(document.getElementById(id).value);
      refreshPanels();
    });
  }
}
