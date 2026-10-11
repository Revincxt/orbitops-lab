"use strict";

function timeLabel(seconds) {
  return window.OrbitReplay.utc(state.currentPayload?.scenario.epoch_utc, seconds);
}

function taskState(taskId) {
  state.taskStates.update(state.replay.time);
  return state.taskStates.get(taskId);
}

function filteredTasks(scenario) {
  const filter = document.getElementById("target-filter").value;
  const satellite = document.getElementById("satellite-filter").value;
  return scenario.tasks.filter((task) => {
    const assignment = state.assignments.get(task.task_id);
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
  if (!state.ephemeris) state.ephemeris = window.OrbitEphemeris.create(payload.replay.ephemeris,
    payload.scenario.epoch_utc, payload.replay.orbits.map(o => o.satellite_id), undefined,
    () => updateReplayVisuals());
  state.orbitModels = new Map(payload.replay.orbits.map((orbit) => [orbit.satellite_id,
    window.OrbitModel.create(orbit, payload.scenario.satellites.find((satellite) => satellite.satellite_id === orbit.satellite_id).orbital_params,
      (id, time) => state.ephemeris.samples(id, time))]));
  state.satelliteSchedules = new Map(payload.scenario.satellites.map(s => [s.satellite_id,
    payload.reference_plan.assignments.filter(a => a.satellite_id === s.satellite_id).sort((a,b) => a.start_s - b.start_s)]));
  state.attitudeFrames.clear();
  state.ephemerisReady = ensureEphemeris();
  updateReplayDirection();
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
  document.getElementById("target-filter").value = "all";
  setPlaybackControl(false);
}

function satelliteFrame(id, time = state.replay.time) {
  const cached = state.attitudeFrames.get(id), revision = state.ephemeris.revision;
  if (cached && cached.time === time && cached.revision === revision) return cached.frame;
  const model = state.orbitModels.get(id);
  const frame = window.SatelliteAttitude.replay(state.satelliteSchedules.get(id) || [], time, model,
    state.currentPayload.replay.attitude?.sample_step_s ?? 1, revision);
  state.attitudeFrames.set(id, {time, revision, frame});
  return frame;
}

function ensureEphemeris() {
  const loader = state.ephemeris;
  if (!loader) return Promise.resolve();
  const radius = Math.max(...[...state.orbitModels.values()].map(m => m.period / 2));
  return loader.ensure(state.replay.time, radius).then(() => {
    if (loader !== state.ephemeris || loader.revision === state.ephemerisRevision) return;
    state.ephemerisRevision = loader.revision;
    if (state.replay.ephemerisError) {
      state.replay.ephemerisError = false;
      elements.statusIndicator.classList.remove("is-error");
      elements.status.classList.remove("error");
      elements.status.textContent = `${state.currentPayload.reference_plan.label} · Ready`;
    }
    updateReplayVisuals();
  });
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
  setAttributeIfChanged(slider, "min", replay.windowStart);
  setAttributeIfChanged(slider, "max", replay.windowEnd);
  slider.value = replay.time;
  const progress = `${(replay.time - replay.windowStart) / width * 100}%`;
  if (slider.parentElement.style.getPropertyValue("--replay-progress") !== progress) slider.parentElement.style.setProperty("--replay-progress", progress);
  setAttributeIfChanged(slider, "aria-valuetext", window.OrbitReplay.utc(scenario.epoch_utc, replay.time, true));
  setAttributeIfChanged(slider, "title", `${window.OrbitReplay.utc(scenario.epoch_utc, replay.windowStart, true)} → ${window.OrbitReplay.utc(scenario.epoch_utc, replay.windowEnd, true)}`);
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
  if (state.globe) {
    // Native EntityView and model callbacks must see every playback frame, not
    // the 10 Hz UI clock. Otherwise idle and observing intervals have different
    // camera cadences even when the renderer itself keeps running at 60 Hz.
    updateCesiumClock();
    // All cone apexes and ground rims share that exact frame, including nearby
    // spacecraft visible in Follow. A second UI refresh reuses their geometry.
    updateSensorFovs();
    state.globe.scene.requestRender();
  }
  // Task states, telemetry and the offline SVG have their own bounded cadence.
  if (timestamp - state.replay.lastPaint >= 100) {
    updateReplayVisuals();
    state.replay.lastPaint = timestamp;
  }
  requestAnimationFrame(animateReplay);
}

function updateTaskNodes(changed) {
  if (!state.taskNodes) {
    state.taskNodes = new Map();
    document.querySelectorAll(".target-row, .map-marker, .task-bar[data-task-id]").forEach(node => {
      const id = node.dataset.taskId;
      if (!state.taskNodes.has(id)) state.taskNodes.set(id, []);
      state.taskNodes.get(id).push({node, label: node.querySelector(".target-state")});
    });
    changed = state.taskById.keys();
  }
  for (const id of changed) {
    const current = state.taskStates.get(id);
    for (const {node, label} of state.taskNodes.get(id) || []) {
      if (node.dataset.state !== current) node.dataset.state = current;
      if (label && label.textContent !== current) label.textContent = current;
    }
  }
}

function updateReplayVisuals() {
  const payload = state.currentPayload;
  if (!payload) return;
  const time = state.replay.time;
  const changedTasks = state.taskStates.update(time);
  const extended = time < payload.scenario.horizon_start_s || time > payload.scenario.horizon_end_s;
  const precise = Boolean(state.ephemeris?.samples(payload.replay.orbits[0].satellite_id, time));
  const precision = extended ? "estimated" : precise ? "1s" : "preview-30s";
  if (elements.globe.dataset.orbitPrecision !== precision) elements.globe.dataset.orbitPrecision = precision;
  ensureEphemeris().catch(error => {
    if (error.name === "AbortError" || state.replay.ephemerisError) return;
    state.replay.ephemerisError = true;
    pauseReplay();
    elements.statusIndicator.classList.add("is-error");
    elements.status.classList.add("error");
    elements.status.textContent = "Orbit data unavailable · 30 s preview";
  });
  document.getElementById("orbit-basis").hidden = !extended;
  const basis = extended ? "estimated" : "source";
  if (elements.globe.dataset.orbitBasis !== basis) elements.globe.dataset.orbitBasis = basis;
  textField("replay-time", window.OrbitReplay.utc(payload.scenario.epoch_utc, time, true));
  setAttributeIfChanged(document.getElementById("replay-time"), "datetime", new Date(Date.parse(payload.scenario.epoch_utc) + time * 1000).toISOString());
  setAttributeIfChanged(document.getElementById("replay-time"), "title", extended ? "UTC · estimated two-body orbit · no task execution" : precise ? "UTC · 1 s source ephemeris" : "UTC · 30 s preview while source ephemeris loads");
  updateReplayWindow();
  const timeline = elements.timeline.querySelector(".timeline-lanes");
  if (timeline && (Number(timeline.dataset.windowStart) !== state.replay.windowStart || Number(timeline.dataset.windowEnd) !== state.replay.windowEnd)) renderReferenceGantt();
  if (state.selectedTaskId) {
    const selectedState = taskState(state.selectedTaskId);
    textField("selected-state", selectedState);
    const node = document.getElementById("selected-state");
    if (node.dataset.state !== selectedState) node.dataset.state = selectedState;
  }
  updateTaskNodes(changedTasks);
  const cursor = document.querySelector(".time-cursor");
  if (cursor) {
    cursor.toggleAttribute("hidden", extended);
    const x = Number(cursor.dataset.left) + (time - state.replay.windowStart) / (state.replay.windowEnd - state.replay.windowStart) * Number(cursor.dataset.width);
    if (Number.isFinite(x)) { setAttributeIfChanged(cursor, "x1", x); setAttributeIfChanged(cursor, "x2", x); }
  }
  if (state.globe) updateCesiumReplay();
  else if (payload.replay) updateFallbackReplay();
  updateOrbitHud();
  if (document.getElementById("target-filter").value === "active" && changedTasks.length) renderTargetCatalog();
}

function stateColor(taskId) {
  return TASK_COLORS[taskState(taskId)];
}

function renderEvaluation(payload) {
  const evaluation = payload.evaluation || {};
  textField("metric-balance", evaluation.BD == null ? "N/A · single satellite" : evaluation.BD.toFixed(3));
  textField("metric-runtime", `${payload.result.runtime_s.toFixed(3)} s · source`);
  textField("metric-motion", payload.result.metrics.total_slew_time_s == null ? "Not recorded" : `${payload.result.metrics.total_slew_time_s.toFixed(1)} s`);
  textField("metric-objective", objectiveLabel(payload.reference_plan.objective));
  document.getElementById("metric-objective").title = payload.reference_plan.objective;
  textField("metric-basis", "Recomputed TP/TCR/TM/BD");
  const constraints = payload.result.validation.constraints;
  const budget = document.getElementById("metric-budget");
  budget.textContent = constraints?.per_orbit_resources.status || "Not checked";
  budget.title = constraints?.per_orbit_resources.power_basis || "";
  const transition = document.getElementById("metric-transitions");
  const profiles = Object.entries(constraints?.transitions.profiles || {});
  const counts = profiles.map(([, value]) => value.violations.length);
  transition.textContent = counts.length ? `${Math.min(...counts)}–${Math.max(...counts)} gaps` : "Not checked";
  transition.title = `Conditional EOS transition checks; source agility profile not recorded. ${profiles.map(([name, value]) => `${name}: ${value.violations.length} insufficient gaps`).join("; ")}. Not a full feasibility certificate.`;
  const visibility = constraints?.ellipsoid_visibility;
  textField("metric-occlusion", visibility ? `${visibility.issues.length} / ${visibility.checked_tasks}` : "Not checked");
  document.getElementById("metric-occlusion").title = "Source assignments with Earth-occluded geometry at one or more original 1 s samples. Published orbit/window mismatch; original plans are not rewritten.";
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
  { key: "TP", label: "TP ↑", name: "Total profit", scale: "TP / highest TP across the selected source plans", format: (value) => value.toFixed(0) },
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

function appendChartGradient(defs, id, stops, radial = false, horizontal = false) {
  const gradient = svgElement(radial ? "radialGradient" : "linearGradient", radial
    ? {id, cx: "45%", cy: "24%", r: "85%"}
    : {id, x1: "0%", y1: "0%", x2: horizontal ? "100%" : "0%", y2: horizontal ? "0%" : "100%"});
  stops.forEach(([offset, color, opacity = 1]) => {
    gradient.append(svgElement("stop", {offset, "stop-color": color, "stop-opacity": opacity}));
  });
  defs.append(gradient);
  return `url(#${id})`;
}

function appendChartDepth(defs, id) {
  const filter = svgElement("filter", {id, x: "-30%", y: "-50%", width: "160%", height: "200%", "color-interpolation-filters": "sRGB"});
  filter.append(svgElement("feDropShadow", {dx: 0, dy: 1.5, stdDeviation: 1.2, "flood-color": "#01060c", "flood-opacity": .65}));
  defs.append(filter);
}

function renderReferenceComparison() {
  const plans = state.referenceData.plans;
  const selectedId = state.currentPayload.reference_plan.plan_id;
  const series = radarSeries(plans);
  const colors = ["#6ad6ee", "#edc78a", "#75d9b6", "#bca9f5", "#f28e9b", "#8daeee", "#cadb78"];
  const dashes = ["", "5 2", "2 2", "7 2 1 2", "9 3", "3 2 1 2", "6 2 2 2"];
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
  const defs = svgElement("defs");
  appendChartGradient(defs, "radar-surface", [["0%", "#24374e"], ["55%", "#132235"], ["100%", "#091321"]], true);
  appendChartDepth(defs, "radar-depth");
  colors.forEach((color, index) => appendChartGradient(defs, `radar-fill-${index}`, [["0%", color, .26], ["100%", color, .025]]));
  root.append(defs);
  const boundary = points(RADAR_AXES.map(() => 1));
  root.append(svgElement("ellipse", {cx, cy, rx: radius + 7, ry: radius + 7, class: "radar-reference-ring", "aria-hidden": "true"}));
  // A decorative plinth adds depth; measured polygons keep their exact axes.
  root.append(svgElement("polygon", {points: boundary, transform: "translate(0 3)", class: "radar-plinth", "aria-hidden": "true"}));
  root.append(svgElement("polygon", {points: boundary, class: "radar-surface", "aria-hidden": "true"}));
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
  // Paint the active plan last; all selected plans use distinct dashes
  // as well as colours. Polygons and vertices never alter source metric values.
  [...series].sort((a, b) => Number(a.plan.plan_id === selectedId) - Number(b.plan.plan_id === selectedId)).forEach((item) => {
    const index = plans.indexOf(item.plan);
    const active = item.plan.plan_id === selectedId;
    const group = svgElement("g", { class: `radar-series${active ? " is-selected" : ""}`, "data-plan-id": item.plan.plan_id });
    // CSSOM updates are compatible with the local server's strict style CSP.
    group.style.setProperty("--series-color", colors[index % colors.length]);
    group.style.setProperty("--series-fill", `url(#radar-fill-${index})`);
    group.append(svgElement("title", {}, `${item.plan.label} · ${summary(item)}\nObjective: ${item.plan.objective}\nReference consistency only, not full feasibility.`));
    if (item.metrics.every((metric) => metric.score !== null)) {
      group.append(svgElement("polygon", { points: points(item.metrics.map((metric) => metric.score)), class: "radar-area", "stroke-dasharray": dashes[index % dashes.length] }));
    }
    item.metrics.forEach((metric, axisIndex) => {
      if (metric.score === null) return;
      const [x, y] = position(axisIndex, radius * metric.score);
      if (active) group.append(svgElement("ellipse", {cx: x, cy: y, rx: 4.8, ry: 4.8, class: "radar-point-halo", "aria-hidden": "true"}));
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
      label.textContent = item.plan.plan_id === "eos-sa-balanced" ? "SA · B" : item.plan.plan_id === "eos-sa-profit" ? "SA · P" : item.plan.label.split(" · ")[0];
      button.setAttribute("aria-label", item.plan.label);
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
  const left = width < 600 ? 128 : 155;
  const top = 6;
  const bottom = 6;
  const rowHeight = layoutSize("timeline-row-height");
  const plotWidth = width - left - 14;
  const {windowStart, windowEnd} = state.replay;
  const duration = windowEnd - windowStart;
  const x = (time) => left + (time - windowStart) / duration * plotWidth;
  const overlaps = (start, end) => end > windowStart && start < windowEnd;
  const satelliteFilter = document.getElementById("satellite-filter").value;
  const satellites = scenario.satellites.filter((satellite) => satelliteFilter === "all" || satellite.satellite_id === satelliteFilter);
  const height = top + satellites.length * rowHeight + bottom;
  const scrollTop = elements.timeline.scrollTop;
  const focusedTaskId = elements.timeline.contains(document.activeElement) ? document.activeElement.dataset.taskId : null;
  elements.timeline.style.setProperty("--timeline-label-width", `${left}px`);
  const axis = chart(width, 24, "Schedule time axis", `${window.OrbitReplay.utc(scenario.epoch_utc, windowStart, true)} → ${window.OrbitReplay.utc(scenario.epoch_utc, windowEnd, true)}`);
  axis.setAttribute("preserveAspectRatio", "none");
  const root = chart(width, height, "Satellite observation timeline", "UTC source task intervals; all satellites including zero-workload satellites remain reachable through internal scrolling. Minimum display widths do not change actual durations.");
  root.setAttribute("preserveAspectRatio", "none");
  root.classList.add("timeline-lanes");
  root.dataset.windowStart = windowStart;
  root.dataset.windowEnd = windowEnd;
  root.style.height = `${height}px`;
  const defs = svgElement("defs");
  appendChartGradient(defs, "timeline-lane-surface", [["0%", "#182535"], ["100%", "#101b2a"]]);
  appendChartGradient(defs, "timeline-lane-active", [["0%", "#21384a"], ["100%", "#15283b"]]);
  appendChartGradient(defs, "timeline-planned", [["0%", "#d4f7ff"], ["35%", "#70d7ed"], ["100%", "#3f8da9"]]);
  appendChartGradient(defs, "timeline-observing", [["0%", "#fff0c5"], ["35%", "#edc78a"], ["100%", "#ae7e43"]]);
  appendChartGradient(defs, "timeline-completed", [["0%", "#d7ffed"], ["35%", "#75d9b6"], ["100%", "#398f77"]]);
  const clip = svgElement("clipPath", {id: "timeline-plot-clip"});
  clip.append(svgElement("rect", {x: left, y: 0, width: plotWidth, height}));
  defs.append(clip);
  root.append(defs);
  for (let tick = 0; tick <= 4; tick += 1) {
    const time = windowStart + duration * tick / 4;
    root.append(svgElement("line", {x1: x(time), x2: x(time), y1: top, y2: height - bottom, class: "chart-grid"}));
    axis.append(svgElement("text", {x: x(time), y: 15, "text-anchor": tick === 0 ? "start" : tick === 4 ? "end" : "middle", class: "chart-axis"}, timeLabel(time).slice(0, 5)));
  }
  document.getElementById("timeline-axis").replaceChildren(axis);
  const selectedTask = scenario.tasks.find((task) => task.task_id === state.selectedTaskId);
  const visibleIds = new Set(filteredTasks(scenario).map((task) => task.task_id));
  satellites.forEach((satellite, index) => {
    const rowY = top + index * rowHeight;
    const row = svgElement("g", {class: `satellite-lane${satellite.satellite_id === state.selectedSatelliteId ? " is-selected" : ""}`, "data-satellite-id": satellite.satellite_id});
    row.append(svgElement("title", {}, satellite.satellite_id));
    row.append(svgElement("rect", {x: 0, y: rowY, width, height: rowHeight - 2, rx: 3, class: "row-band", opacity: index % 2 ? 0 : 1}));
    row.append(svgElement("text", {x: 5, y: rowY + 13, class: "task-label"}, satelliteName(satellite.satellite_id)));
    const assignments = plan.assignments.filter((assignment) => assignment.satellite_id === satellite.satellite_id);
    row.append(svgElement("text", {x: 5, y: rowY + 27, class: "task-sublabel"}, `${assignments.length} tasks · ${plan.workloads[satellite.satellite_id]} s`));
    selectedTask?.visibility_windows.filter((window) => window.satellite_id === satellite.satellite_id && overlaps(window.start_s, window.end_s)).forEach((window) => {
      const bar = svgElement("rect", {x: x(window.start_s), y: rowY + 6, width: Math.max(1, x(window.end_s) - x(window.start_s)), height: 20, class: "window-bar", "clip-path": "url(#timeline-plot-clip)"});
      bar.append(svgElement("title", {}, `${selectedTask.task_id} · ${window.window_id} · ${timeLabel(window.start_s)}–${timeLabel(window.end_s)} UTC`));
      row.append(bar);
    });
    assignments.filter((assignment) => visibleIds.has(assignment.task_id)).forEach((assignment) => {
      const selected = assignment.task_id === state.selectedTaskId;
      const inWindow = overlaps(assignment.start_s, assignment.end_s);
      const bar = svgElement("rect", {x: x(assignment.start_s), y: rowY + (selected ? 7 : 10), width: Math.max(selected ? 4 : 2, x(assignment.end_s) - x(assignment.start_s)), height: selected ? 18 : 12,
        rx: 1, class: "task-bar", "clip-path": "url(#timeline-plot-clip)", "data-task-id": assignment.task_id, "data-state": taskState(assignment.task_id), role: "button", tabindex: inWindow ? 0 : -1,
        "aria-label": `${assignment.task_id} on ${satellite.satellite_id}, ${timeLabel(assignment.start_s)} UTC, ${(assignment.end_s - assignment.start_s).toFixed(0)} seconds`});
      bar.toggleAttribute("hidden", !inWindow);
      if (selected) { bar.setAttribute("stroke", "#fff"); bar.setAttribute("stroke-width", "1"); }
      bar.append(svgElement("title", {}, `${assignment.task_id} · ${satellite.satellite_id}\n${timeLabel(assignment.start_s)}–${timeLabel(assignment.end_s)} UTC\nActual duration: ${assignment.end_s - assignment.start_s}s. Display width may be enlarged.`));
      bar.addEventListener("click", () => selectTarget(assignment.task_id));
      bar.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); selectTarget(assignment.task_id); } });
      row.append(bar);
    });
    root.append(row);
  });
  const cursor = svgElement("line", {x1: x(state.replay.time), x2: x(state.replay.time), y1: top, y2: height - bottom, class: "time-cursor", "data-left": left, "data-width": plotWidth});
  cursor.toggleAttribute("hidden", state.replay.time < scenario.horizon_start_s || state.replay.time > scenario.horizon_end_s);
  root.append(cursor);
  const previous = elements.timeline.querySelector(".timeline-lanes");
  if (previous) previous.replaceWith(root);
  else {
    elements.timeline.querySelector(".chart-empty")?.remove();
    elements.timeline.append(root);
  }
  state.taskNodes = null;
  elements.timeline.scrollTop = scrollTop;
  if (focusedTaskId) root.querySelector(`[data-task-id="${CSS.escape(focusedTaskId)}"]`)?.focus({preventScroll: true});
}

function renderWorkloads() {
  const {reference_plan: plan, scenario} = state.currentPayload;
  const width = Math.max(180, elements.resources.clientWidth);
  const rowHeight = layoutSize("workload-row-height");
  const height = Math.max(65, scenario.satellites.length * rowHeight + 4);
  const scrollTop = elements.resources.scrollTop;
  const labelWidth = Math.min(108, width * .43);
  const barWidth = Math.max(12, width - labelWidth - 46);
  const focusedSatellite = elements.resources.contains(document.activeElement) ? document.activeElement.dataset.satelliteId : null;
  const selected = state.selectedSatelliteId;
  const rows = scenario.satellites.map((satellite) => ({id: satellite.satellite_id, load: plan.workloads[satellite.satellite_id]})).sort((a, b) => b.load - a.load || a.id.localeCompare(b.id));
  const maximum = Math.max(1, ...rows.map((row) => row.load));
  const root = chart(width, height, "Satellite observation workload", "All satellites, including zero-workload satellites, are reachable through internal scrolling. Source observation durations in seconds, not battery or storage traces.");
  root.setAttribute("preserveAspectRatio", "none");
  root.style.height = `${height}px`;
  const defs = svgElement("defs");
  appendChartGradient(defs, "workload-fill", [["0%", "#38677f"], ["60%", "#639eb7"], ["100%", "#9acedd"]], false, true);
  appendChartGradient(defs, "workload-selected", [["0%", "#86714e"], ["60%", "#b29a72"], ["100%", "#e1c99f"]], false, true);
  appendChartGradient(defs, "workload-recess", [["0%", "#080f1a"], ["100%", "#142133"]]);
  appendChartDepth(defs, "workload-depth");
  const labelClip = svgElement("clipPath", {id: "workload-label-clip"});
  labelClip.append(svgElement("rect", {x: 6, y: 0, width: labelWidth - 12, height}));
  defs.append(labelClip);
  root.append(defs);
  rows.forEach((row, index) => {
    const y = 7 + index * rowHeight;
    const group = svgElement("g", {class: "workload-row", role: "button", tabindex: 0, "aria-label": `${row.id}: ${row.load} seconds`, "aria-pressed": String(row.id === selected), "data-satellite-id": row.id});
    group.append(svgElement("title", {}, `${row.id} · ${row.load} s`));
    group.append(svgElement("rect", {x: 0, y: y - 6, width, height: rowHeight, class: "workload-row-band"}));
    if (row.id === selected) group.append(svgElement("rect", {x: 0, y: y + 2, width: 2, height: 8, rx: 1, class: "workload-selection-marker", "aria-hidden": "true"}));
    group.append(svgElement("text", {x: 6, y: y + 10, class: "chart-axis workload-label", "clip-path": "url(#workload-label-clip)"}, satelliteName(row.id)));
    group.append(svgElement("rect", {x: labelWidth, y: y + 2, width: barWidth, height: 8, rx: 2, class: "workload-track"}));
    for (const tick of [.25, .5, .75]) {
      group.append(svgElement("line", {x1: labelWidth + tick * barWidth, x2: labelWidth + tick * barWidth, y1: y + 3, y2: y + 9, class: "workload-tick", "aria-hidden": "true"}));
    }
    const filledWidth = row.load / maximum * barWidth;
    group.append(svgElement("rect", {x: labelWidth, y: y + 2, width: filledWidth, height: 8, rx: 2, class: `workload-bar${row.id === selected ? " is-selected" : ""}`}));
    if (filledWidth > 5) group.append(svgElement("line", {x1: labelWidth + 2.5, x2: labelWidth + filledWidth - 2.5, y1: y + 3, y2: y + 3, class: "workload-highlight", "aria-hidden": "true"}));
    const value = svgElement("text", {x: width - 1, y: y + 10, "text-anchor": "end", class: "chart-axis workload-value"});
    value.append(svgElement("tspan", {}, String(row.load)), svgElement("tspan", {class: "workload-unit"}, " s"));
    group.append(value);
    group.addEventListener("click", () => selectSatellite(row.id, true));
    group.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); selectSatellite(row.id, true); } });
    root.append(group);
  });
  elements.resources.replaceChildren(root);
  elements.resources.scrollTop = scrollTop;
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
  if (state.globe && state.footprintPrimitives) state.globe.scene.primitives.remove(state.footprintPrimitives);
  state.fovPrimitives = null;
  state.footprintPrimitives = null;
  state.sensorFovs.clear();
}

function addSensorFov(viewer, Cesium, orbit, color) {
  if (!state.fovPrimitives) state.fovPrimitives = viewer.scene.primitives.add(new Cesium.PrimitiveCollection());
  if (!state.footprintPrimitives) state.footprintPrimitives = viewer.scene.primitives.add(new Cesium.PrimitiveCollection());
  const sensor = {solid: null, volumeFrame: null, mesh: null, frame: null, time: null, color, id: orbit.satellite_id,
    footprintPositions: [], footprintFrame: null, fill: null};
  sensor.footprint = viewer.entities.add({id: `fov-${orbit.satellite_id}`, show: false,
    polyline: {
      positions: new Cesium.CallbackProperty(() => sensor.footprintPositions, false),
      width: 1, material: color.withAlpha(.22), arcType: Cesium.ArcType.NONE,
    }});
  state.sensorFovs.set(orbit.satellite_id, sensor);
}

function updateSensorVolume(sensor, visible) {
  const frame = sensor.frame;
  if (!visible || !frame) {
    if (sensor.solid) state.fovPrimitives.remove(sensor.solid);
    sensor.solid = null;
    sensor.volumeFrame = null;
    sensor.mesh = null;
    return;
  }
  if (sensor.volumeFrame === frame) return;
  const Cesium = window.Cesium, mesh = window.SensorFov.mesh(frame);
  // Replace synchronously, like the ground fill. A fixed CylinderGeometry can
  // only scale its flat base; this open fan ends at the current curved rim.
  if (sensor.solid) state.fovPrimitives.remove(sensor.solid);
  const rotation = Cesium.Matrix3.fromArray([...frame.right, ...frame.north, ...frame.up]);
  const matrix = Cesium.Matrix4.fromRotationTranslation(rotation, Cesium.Cartesian3.fromArray(frame.center));
  Cesium.Matrix4.multiplyByScale(matrix, new Cesium.Cartesian3(frame.radius, frame.radius, frame.length), matrix);
  sensor.solid = state.fovPrimitives.add(new Cesium.Primitive({
    geometryInstances: new Cesium.GeometryInstance({id: `sensor-${sensor.id}`,
      geometry: new Cesium.Geometry({attributes: {position: new Cesium.GeometryAttribute({
        componentDatatype: Cesium.ComponentDatatype.DOUBLE, componentsPerAttribute: 3, values: mesh.positions,
      })}, indices: mesh.indices, primitiveType: Cesium.PrimitiveType.TRIANGLES,
        boundingSphere: Cesium.BoundingSphere.fromVertices(mesh.positions)}),
      attributes: {color: Cesium.ColorGeometryInstanceAttribute.fromColor(sensor.color.withAlpha(.035))},
    }),
    modelMatrix: matrix,
    appearance: new Cesium.PerInstanceColorAppearance({flat: true, translucent: true, closed: false}),
    asynchronous: false, allowPicking: false,
  }));
  sensor.mesh = mesh;
  sensor.volumeFrame = frame;
}

function updateSensorFootprint(sensor, visible) {
  const frame = sensor.frame;
  const show = visible && Boolean(frame?.footprint.length);
  sensor.footprint.show = show;
  if (!show) {
    if (sensor.footprintPositions.length) sensor.footprintPositions = [];
    sensor.footprintFrame = null;
    if (sensor.fill) state.footprintPrimitives.remove(sensor.fill);
    sensor.fill = null;
    return;
  }
  if (sensor.footprintFrame === frame) return;
  const Cesium = window.Cesium;
  // Static Entity polygons rebuild asynchronously and retain their old batch
  // until the replacement is ready. Own the current fill instead: destroy the
  // previous geometry immediately and build synchronously once per replay tick.
  if (sensor.fill) state.footprintPrimitives.remove(sensor.fill);
  sensor.fill = null;
  const hierarchy = new Cesium.PolygonHierarchy(frame.footprint.map(point => Cesium.Cartesian3.fromArray(point)));
  sensor.fill = state.footprintPrimitives.add(new Cesium.Primitive({
    geometryInstances: new Cesium.GeometryInstance({id: `coverage-${sensor.id}`,
      geometry: new Cesium.PolygonGeometry({polygonHierarchy: hierarchy, height: 15,
        arcType: Cesium.ArcType.GEODESIC, vertexFormat: Cesium.PerInstanceColorAppearance.FLAT_VERTEX_FORMAT}),
      attributes: {color: Cesium.ColorGeometryInstanceAttribute.fromColor(sensor.color.withAlpha(.02))},
    }),
    appearance: new Cesium.PerInstanceColorAppearance({flat: true, translucent: true, closed: false}),
    asynchronous: false, allowPicking: false,
  }));
  sensor.footprintPositions = frame.surfaceBoundary.map(point => Cesium.Cartesian3.fromArray(point));
  sensor.footprintPositions.push(sensor.footprintPositions[0]);
  sensor.footprintFrame = frame;
}

function updateSensorFovs() {
  if (!state.globe || !state.fovPrimitives) return;
  const viewer = state.globe, Cesium = window.Cesium;
  const visible = state.layers.fov && !state.viewTransition;
  // A transformed local cone is meaningful only on the native 3D globe.
  // Unfolded views retain the current footprint instead of a distorted cone.
  const volumeVisible = visible && viewer.scene.mode === Cesium.SceneMode.SCENE3D;
  state.fovPrimitives.show = volumeVisible;
  state.footprintPrimitives.show = visible;
  if (!visible) {
    for (const sensor of state.sensorFovs.values()) {
      updateSensorVolume(sensor, false);
      updateSensorFootprint(sensor, false);
    }
    return;
  }
  const seconds = Cesium.JulianDate.secondsDifference(viewer.clock.currentTime, viewer.clock.startTime);
  for (const [id, sensor] of state.sensorFovs) {
    if (sensor.time && sensor.revision === state.ephemeris.revision && Cesium.JulianDate.equals(sensor.time, viewer.clock.currentTime)) {
      updateSensorVolume(sensor, volumeVisible);
      updateSensorFootprint(sensor, visible);
      continue;
    }
    const position = state.orbitPositions.get(id)?.getValue(viewer.clock.currentTime);
    const attitude = satelliteFrame(id, seconds);
    const frame = position && window.SensorFov.frame([position.x, position.y, position.z], attitude?.direction, attitude?.x);
    sensor.revision = state.ephemeris.revision;
    sensor.time = Cesium.JulianDate.clone(viewer.clock.currentTime, sensor.time || new Cesium.JulianDate());
    sensor.frame = frame;
    sensor.attitude = attitude;
    updateSensorVolume(sensor, volumeVisible);
    updateSensorFootprint(sensor, visible);
  }
}

function setupReferenceGlobe(viewer, Cesium) {
  state.fallbackSatellites.clear();
  state.taskNodes = null;
  const payload = state.currentPayload;
  const epoch = Cesium.JulianDate.fromIso8601(payload.scenario.epoch_utc);
  viewer.clock.startTime = Cesium.JulianDate.clone(epoch);
  viewer.clock.stopTime = Cesium.JulianDate.addSeconds(epoch, payload.scenario.horizon_end_s, new Cesium.JulianDate());
  viewer.clock.currentTime = Cesium.JulianDate.addSeconds(epoch, state.replay.time, new Cesium.JulianDate());
  viewer.clock.clockRange = Cesium.ClockRange.UNBOUNDED;
  viewer.clock.shouldAnimate = false;
  payload.replay.orbits.forEach((orbit, index) => {
    const model = state.orbitModels.get(orbit.satellite_id);
    const position = new Cesium.CallbackPositionProperty((time, result) => {
      const seconds = Cesium.JulianDate.secondsDifference(time, epoch);
      return Cesium.Cartesian3.fromArray(model.cartesian(seconds), 0, result);
    }, false, Cesium.ReferenceFrame.FIXED);
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
      orientation: new Cesium.CallbackProperty((time, result) => {
        const attitude = satelliteFrame(orbit.satellite_id, Cesium.JulianDate.secondsDifference(time, epoch));
        return attitude && Cesium.Quaternion.fromRotationMatrix(Cesium.Matrix3.fromArray(attitude.modelAxes), result);
      }, false),
      viewFrom: new Cesium.Cartesian3(-1800000, -1800000, 1600000),
      // A fixed velocity frame follows the orbit, not the task's body attitude.
      // Do not let AUTO choose a different frame when source precision changes.
      trackingReferenceFrame: Cesium.TrackingReferenceFrame.VELOCITY,
      model: {uri: "./models/earth-observer.glb?v=0.15.0", scale: 1, minimumPixelSize: 28,
        maximumScale: 120000, runAnimations: false, shadows: Cesium.ShadowMode.DISABLED,
        silhouetteColor: color, silhouetteSize: 0, environmentMapOptions: {enabled: false}},
      point: {show: false, pixelSize: 23, color: color.withAlpha(.15), outlineColor: color, outlineWidth: 1, disableDepthTestDistance: 0},
      label: {show: state.layers.satelliteLabels, text: satelliteName(orbit.satellite_id), font: '500 12px "Inter", sans-serif', fillColor: color,
        showBackground: true, backgroundColor: Cesium.Color.fromCssColorString("#0a1420").withAlpha(.8),
        backgroundPadding: new Cesium.Cartesian2(5, 3), horizontalOrigin: Cesium.HorizontalOrigin.LEFT,
        pixelOffset: new Cesium.Cartesian2(20, -14), disableDepthTestDistance: 0,
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
  state.cameraHome = {missionCenter: new Cesium.BoundingSphere(Cesium.Cartesian3.ZERO, Cesium.Ellipsoid.WGS84.maximumRadius + altitude), longitudeCenter: 105, latitudeCenter: 20};
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

function updateCesiumClock() {
  const viewer = state.globe, Cesium = window.Cesium;
  if (!viewer || !state.currentPayload?.scenario.epoch_utc) return;
  // setupReferenceGlobe stores the source epoch once. Avoid reparsing UTC on
  // each frame, and retain a distinct date for Cesium's change detection.
  viewer.clock.currentTime = Cesium.JulianDate.addSeconds(viewer.clock.startTime,
    state.replay.time, new Cesium.JulianDate());
}

function updateCesiumReplay() {
  const viewer = state.globe;
  const Cesium = window.Cesium;
  const payload = state.currentPayload;
  updateCesiumClock();
  payload.scenario.tasks.forEach((task) => {
    const entity = viewer.entities.getById(`target-${task.task_id}`);
    const current = taskState(task.task_id);
    if (entity?.point && state.entityTaskStates.get(task.task_id) !== current) {
      entity.point.color = Cesium.Color.fromCssColorString(stateColor(task.task_id)).withAlpha(.85);
      state.entityTaskStates.set(task.task_id, current);
    }
  });
  if (payload.replay) {
    const selectionKey = `${state.selectedSatelliteId}:${state.selectedTaskId}:${state.layers.labels}:${state.layers.satelliteLabels}:${state.layers.track}:${state.orbitEmphasis}`;
    const changed = selectionKey !== state.geometrySelectionKey;
    payload.replay.orbits.forEach((orbit) => {
      const selected = orbit.satellite_id === state.selectedSatelliteId;
      const past = viewer.entities.getById(`orbit-${orbit.satellite_id}`)?.path;
      const future = viewer.entities.getById(`orbit-preview-${orbit.satellite_id}`)?.path;
      if (!past || !future) return;
      if (changed) {
        // Lead/trail durations are fixed at setup. Replacing ConstantProperty
        // values on every UI tick needlessly invalidates both path visualizers.
        past.show = future.show = state.layers.track;
        const styles = state.orbitStyles.get(orbit.satellite_id)[selected ? "selected" : state.selectedSatelliteId && state.orbitEmphasis ? "dimmed" : "normal"];
        past.material = styles.past;
        future.material = styles.future;
        past.width = future.width = selected ? 2.5 : 1.4;
        const entity = viewer.entities.getById(`satellite-${orbit.satellite_id}`);
        entity.model.minimumPixelSize = selected ? 40 : 28;
        entity.model.silhouetteSize = selected ? 1 : 0;
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
  updateSensorFovs();
  updateSolarEnvironment();
  viewer.scene.requestRender();
}

function addFallbackOrbits(map) {
  const group = svgElement("g", {class: "fallback-orbits"});
  const footprints = svgElement("g", {class: "fallback-fovs"});
  state.fallbackSatellites.clear();
  map.append(footprints);
  state.currentPayload.replay.orbits.forEach((orbit) => {
    const color = orbitColor(orbit.satellite_id);
    const footprint = svgElement("g", {class: "map-fov", "data-satellite-id": orbit.satellite_id});
    footprint.style.stroke = color;
    footprints.append(footprint);
    const track = svgElement("g", {class: "map-orbit", "data-satellite-id": orbit.satellite_id});
    track.style.stroke = color;
    group.append(track);
    const marker = svgElement("g", {class: "map-satellite", "data-satellite-id": orbit.satellite_id, role: "button", tabindex: "0", "aria-label": `Inspect satellite ${orbit.satellite_id}`});
    marker.style.color = color;
    // A shaded vector counterpart when the native 3D renderer is unavailable.
    marker.append(svgElement("path", {class: "satellite-panel", d: "M-16-3-6-6-6 4-16 7Z M6-6 16-3 16 7 6 4Z"}));
    marker.append(svgElement("path", {class: "satellite-cells", d: "M-13-4V6M-10-5V5M-16 2-6-1M10-5V5M13-4V6M6-1 16 2"}));
    marker.append(svgElement("path", {class: "satellite-bus", d: "M-5-5 0-8 5-5V6L0 9-5 6Z"}));
    marker.append(svgElement("path", {class: "satellite-metal", d: "M-5-5 0-8 5-5 0-2Z M0-2V9L5 6V-5Z"}));
    marker.append(svgElement("path", {class: "satellite-antenna", d: "M-3-8Q0-12 3-8Q0-6-3-8Z M0-9V-13"}));
    marker.append(svgElement("title", {}, orbit.satellite_id));
    marker.append(svgElement("text", {x: 20, y: -9, class: "satellite-label"}, satelliteName(orbit.satellite_id)));
    marker.addEventListener("click", () => selectSatellite(orbit.satellite_id));
    marker.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectSatellite(orbit.satellite_id); }
    });
    group.append(marker);
    state.fallbackSatellites.set(orbit.satellite_id, {footprint, track, marker});
  });
  map.append(group);
}

function updateFallbackReplay() {
  const payload = state.currentPayload;
  const time = state.replay.time, revision = state.ephemeris.revision;
  const project = (lon, lat) => [(lon + 180) / 360 * 1000, (90 - lat) / 180 * 500];
  payload.replay.orbits.forEach((orbit) => {
    const model = state.orbitModels.get(orbit.satellite_id);
    const cached = state.fallbackSatellites.get(orbit.satellite_id);
    if (!cached) return;
    const {footprint, track: group, marker} = cached;
    if (state.layers.fov && (cached.footprintTime !== time || cached.footprintRevision !== revision)) {
      const attitude = satelliteFrame(orbit.satellite_id);
      const frame = window.SensorFov.frame(model.cartesian(time), attitude?.direction, attitude?.x);
      const show = Boolean(frame?.footprint.length);
      const samples = show ? [...frame.footprint, frame.footprint[0]].map((sample, i) => [i, ...window.OrbitModel.toGeodetic(sample)]) : [];
      const paths = samples.length ? window.OrbitReplay.trackSegments(samples, 0, samples.length - 1).map((segment) =>
        svgElement("polyline", {points: segment.map((sample) => project(sample[1], sample[2]).join(",")).join(" ")})) : [];
      footprint.replaceChildren(...paths);
      cached.footprintTime = time;
      cached.footprintRevision = revision;
      cached.footprintVisible = show;
    }
    if (!state.layers.fov) {
      if (footprint.childElementCount) footprint.replaceChildren();
      cached.footprintTime = null;
    }
    const footprintDisplay = state.layers.fov && cached.footprintVisible ? "" : "none";
    if (footprint.style.display !== footprintDisplay) footprint.style.display = footprintDisplay;
    if (cached.positionTime !== time || cached.positionRevision !== revision) {
      const point = model.point(time), [x, y] = project(point[0], point[1]);
      setAttributeIfChanged(marker, "transform", `translate(${x},${y})`);
      cached.positionTime = time;
      cached.positionRevision = revision;
    }
    const selected = orbit.satellite_id === state.selectedSatelliteId;
    if (marker.classList.contains("is-selected") !== selected) marker.classList.toggle("is-selected", selected);
    setAttributeIfChanged(marker, "aria-pressed", String(selected));
    const label = marker.querySelector("text"), labelDisplay = selected || state.layers.satelliteLabels ? "" : "none";
    if (label.style.display !== labelDisplay) label.style.display = labelDisplay;
    const trackDisplay = state.layers.track ? "" : "none";
    if (group.style.display !== trackDisplay) group.style.display = trackDisplay;
    if (group.classList.contains("is-selected") !== selected) group.classList.toggle("is-selected", selected);
    const dimmed = Boolean(state.selectedSatelliteId && state.orbitEmphasis && !selected);
    if (group.classList.contains("is-dimmed") !== dimmed) group.classList.toggle("is-dimmed", dimmed);
    if (cached.trackTime === time && cached.trackRevision === revision) return;
    const bounds = windowForOrbit(orbit);
    const samples = model.trackSamples(bounds.start, bounds.end);
    const paths = [["past", bounds.start, state.replay.time], ["future", state.replay.time, bounds.end]].flatMap(([kind, start, end]) =>
      window.OrbitReplay.trackSegments(samples, start, end).map((segment) => svgElement("polyline", {class: `map-track-${kind}`, points: segment.map((sample) => project(sample[1], sample[2]).join(",")).join(" ")})));
    group.replaceChildren(...paths);
    cached.trackTime = time;
    cached.trackRevision = revision;
  });
}

function releaseCameraTracking() {
  cancelSelectionFlight();
  if (!state.globe || !window.Cesium) return;
  state.globe.trackedEntity = undefined;
  if (!state.viewTransition && state.viewMode === "3d") state.globe.camera.lookAtTransform(window.Cesium.Matrix4.IDENTITY);
}

function selectSatellite(id, reorient = false) {
  if (!state.currentPayload?.replay?.orbits.some((orbit) => orbit.satellite_id === id)) return;
  cancelSelectionFlight();
  if (reorient && state.globe && !state.viewTransition) {
    state.globe.camera.cancelFlight();
    releaseCameraTracking();
    state.cameraMode = "manual";
  }
  if (state.selectedSatelliteId !== id) delete document.getElementById("orbit-hud").dataset.anchorSide;
  state.selectedSatelliteId = id;
  state.satelliteDetailsOpen = true;
  state.orbitEmphasis = true;
  updateReplayVisuals();
  renderWorkloads();
  revealWorkloadSatellite(id);
  if (!document.getElementById("pane-timeline").hidden) {
    renderReferenceGantt();
    revealTimelineSatellite(id);
  }
  if (reorient) orientToMissionSelection("satellite", id);
}

function updateOrbitHud() {
  const reference = state.currentPayload?.mode === "reference";
  const orbit = state.currentPayload?.replay?.orbits.find((item) => item.satellite_id === state.selectedSatelliteId);
  const hud = document.getElementById("orbit-hud");
  if (!reference || !orbit || !state.satelliteDetailsOpen || state.viewTransition) hud.hidden = true;
  const followId = followSatelliteId();
  const available = Boolean(!state.viewTransition && reference && followId
    && (!state.globe || state.globe.entities.getById(`satellite-${followId}`)));
  document.getElementById("camera-follow").disabled = !available;
  document.getElementById("north-view").disabled = !state.globe || state.viewTransition;
  updateCameraCompass();
  document.getElementById("camera-overview").disabled = !state.globe || state.viewTransition;
  document.getElementById("reset-view").disabled = state.viewTransition;
  for (const mode of ["overview", "follow"]) document.getElementById(`camera-${mode}`).setAttribute("aria-pressed", String(state.cameraMode === mode));
  document.getElementById("camera-follow").title = state.cameraMode === "follow" ? "Stop following satellite" : "Follow selected satellite";
  if (!reference) return;
  satelliteDetailField("satellite-name", orbit ? satelliteName(orbit.satellite_id) : "Select a satellite",
    orbit?.satellite_id || "Pick a satellite symbol or select a Satellite row");
  const swatch = document.getElementById("satellite-swatch"), color = orbit ? orbitColor(orbit.satellite_id) : "#596777";
  if (swatch.dataset.color !== color) {
    swatch.style.backgroundColor = color;
    swatch.dataset.color = color;
  }
  if (orbit) {
    // Read XYZ and geodetic values from the same Cartesian position as the map,
    // including 1-second ephemeris interpolation and estimated extensions.
    const native = state.globe && state.orbitPositions.get(orbit.satellite_id)?.getValue(state.globe.clock.currentTime);
    const position = native ? [native.x, native.y, native.z] : state.orbitModels.get(orbit.satellite_id).cartesian(state.replay.time);
    const [longitude, latitude, altitude] = window.OrbitModel.toGeodetic(position);
    const fixed = value => { const text = value.toFixed(3); return text === "-0.000" ? "0.000" : text; };
    satelliteDetailField("satellite-altitude", `${(altitude / 1000).toFixed(1)} km`);
    satelliteDetailField("satellite-period", `${(orbit.period_s / 60).toFixed(1)} min`);
    satelliteDetailField("satellite-latitude", `${fixed(latitude)}°`);
    satelliteDetailField("satellite-longitude", `${fixed(longitude)}°`);
    ["x", "y", "z"].forEach((axis, i) => satelliteDetailField(`satellite-position-${axis}`, fixed(position[i] / 1000)));
  } else {
    satelliteDetailField("satellite-altitude", "— km");
    satelliteDetailField("satellite-period", "— min");
    for (const field of ["latitude", "longitude"]) satelliteDetailField(`satellite-${field}`, "—°");
    for (const axis of ["x", "y", "z"]) satelliteDetailField(`satellite-position-${axis}`, "—");
  }
  // Native EntityView has not yet moved its tracking camera to the new clock.
  // Reposition only after rendering; the offline SVG is already updated here.
  if (!state.globe) positionSatelliteDetails();
}

function satelliteDetailField(id, value, title = value) {
  const node = document.getElementById(id);
  if (node.textContent !== value) node.textContent = value;
  if (node.title !== title) node.title = title;
}

function closeSatelliteDetails() {
  state.satelliteDetailsOpen = false;
  document.getElementById("orbit-hud").hidden = true;
  delete document.getElementById("orbit-hud").dataset.anchorSide;
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
  if (hud.hidden) hud.hidden = false;
  // Leave the symbol unobstructed so the second click of a double-click still
  // reaches Cesium. The popup's responsive max-width guarantees side clearance.
  const popupWidth = hud.offsetWidth, popupHeight = hud.offsetHeight;
  const rightFits = point.x + popupWidth + 12 <= width - 12;
  const leftFits = point.x - popupWidth - 12 >= 12;
  // Keep the chosen side while it fits; a small overlap zone avoids alternating
  // left/right near the threshold, especially in narrow Follow viewports.
  let side = hud.dataset.anchorSide || (rightFits ? "right" : "left");
  if (side === "right" && !rightFits && leftFits) side = "left";
  if (side === "left" && !leftFits && rightFits) side = "right";
  if (hud.dataset.anchorSide !== side) hud.dataset.anchorSide = side;
  const preferredX = side === "right" ? point.x + 12 : point.x - popupWidth - 12;
  const x = Math.round(Math.max(12, Math.min(width - popupWidth - 12, preferredX)));
  const y = Math.round(Math.max(12, Math.min(height - popupHeight - 12, point.y + 16)));
  const transform = `translate3d(${x}px, ${y}px, 0px)`;
  if (hud.style.transform !== transform) hud.style.transform = transform;
}

function cameraMotionDuration() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : .65;
}

function cancelSelectionFlight() {
  if (!state.selectionFlight) return;
  cancelAnimationFrame(state.selectionFlight.frame);
  state.selectionFlight = null;
}

function orientToMissionSelection(kind, id) {
  const viewer = state.globe, Cesium = window.Cesium;
  // Unfolded maps retain the user's extent: selecting an object only highlights it.
  if (!viewer || !Cesium || state.viewTransition || state.viewMode !== "3d") return;
  const getPosition = () => kind === "satellite"
    ? state.orbitPositions.get(id)?.getValue(viewer.clock.currentTime)
    : viewer.entities.getById(`target-${id}`)?.position.getValue(viewer.clock.currentTime);
  const target = getPosition();
  if (!target) return;
  viewer.camera.cancelFlight();
  releaseCameraTracking();
  state.cameraMode = "manual";
  // Cesium 1.143 exposes no public stop-inertia method. Discard only its cached
  // input samples so an earlier drag/zoom cannot pull the completed view away.
  // A new map gesture produces fresh samples; normal inertia settings stay intact.
  const aggregator = viewer.scene.screenSpaceCameraController._aggregator;
  aggregator?.reset();
  for (const movement of Object.values(aggregator?._lastMovement || {})) movement.valid = false;
  const camera = viewer.camera, replay = window.OrbitReplay;
  const start = Cesium.Cartesian3.clone(camera.positionWC);
  const direction = Cesium.Cartesian3.clone(camera.directionWC), up = Cesium.Cartesian3.clone(camera.upWC);
  const array = vector => [vector.x, vector.y, vector.z];
  const cartesian = values => new Cesium.Cartesian3(...values);
  const eye = array(start), initialDirection = array(direction), initialUp = array(up);
  const radius = Math.hypot(...eye);
  // Orbit on a shortest great-circle arc, not a longitude interpolation. This
  // also avoids a long turn across the date line or a detour over the poles.
  // Gently remove an existing off-centre tilt without resetting screen roll.
  const align = replay.shortestArc(initialDirection, eye.map(value => -value), initialUp);
  const pose = (fraction, position) => {
    const arc = replay.shortestArc(eye, array(position), initialUp);
    const distance = Math.max(radius, Cesium.Cartesian3.magnitude(position) + 100000);
    const scale = 1 + (distance / radius - 1) * fraction;
    return {
      position: cartesian(replay.rotateVector(eye, arc, fraction).map(value => value * scale)),
      direction: cartesian(replay.rotateVector(replay.rotateVector(initialDirection, align, fraction), arc, fraction)),
      up: cartesian(replay.rotateVector(replay.rotateVector(initialUp, align, fraction), arc, fraction)),
    };
  };
  const apply = fraction => {
    const position = getPosition();
    if (!position) return;
    const next = pose(fraction, position);
    camera.worldToCameraCoordinatesPoint(next.position, camera.position);
    camera.worldToCameraCoordinatesVector(next.direction, camera.direction);
    camera.worldToCameraCoordinatesVector(next.up, camera.up);
    Cesium.Cartesian3.cross(camera.direction, camera.up, camera.right);
    viewer.scene.requestRender();
  };
  const duration = cameraMotionDuration() * 1000;
  if (duration === 0) apply(1);
  else {
    const flight = {frame: null, started: performance.now()};
    const tick = now => {
      if (state.selectionFlight !== flight) return;
      if (viewer.isDestroyed() || state.viewTransition) { cancelSelectionFlight(); return; }
      const fraction = Math.max(0, Math.min(1, (now - flight.started) / duration));
      apply(fraction * fraction * (3 - 2 * fraction));
      if (fraction < 1) flight.frame = requestAnimationFrame(tick);
      else state.selectionFlight = null;
    };
    state.selectionFlight = flight;
    flight.frame = requestAnimationFrame(tick);
  }
  updateOrbitHud();
}

function focusSelectedSatellite() {
  const viewer = state.globe;
  const Cesium = window.Cesium;
  if (!viewer || !Cesium || state.viewTransition || state.viewMode !== "3d") return;
  const position = state.orbitPositions.get(state.selectedSatelliteId)?.getValue(viewer.clock.currentTime);
  if (!position) return;
  releaseCameraTracking();
  state.cameraMode = "manual";
  state.orbitEmphasis = true;
  const range = window.OrbitReplay.fitRange(1000000, viewer.camera.frustum.fovy || Cesium.Math.PI_OVER_THREE, elements.globe.clientWidth / Math.max(1, elements.globe.clientHeight), 1.1);
  viewer.camera.flyToBoundingSphere(new Cesium.BoundingSphere(position, 1000000), {
    duration: cameraMotionDuration(), offset: new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-65), range),
  });
  viewer.scene.requestRender();
  updateOrbitHud();
  updateReplayVisuals();
}

function followSatelliteId() {
  const orbits = state.currentPayload?.replay?.orbits || [];
  const assignedId = state.assignments.get(state.selectedTaskId)?.satellite_id;
  return orbits.find(orbit => orbit.satellite_id === state.selectedSatelliteId)?.satellite_id
    || orbits.find(orbit => orbit.satellite_id === assignedId)?.satellite_id
    || orbits[0]?.satellite_id || null;
}

function followSelectedSatellite() {
  if (state.viewTransition) return;
  const viewer = state.globe;
  const id = followSatelliteId();
  if (!id) return;
  const entity = viewer?.entities.getById(`satellite-${id}`);
  if (viewer && (!entity || !entity.position.getValue(viewer.clock.currentTime))) return;
  // Follow can be started from a task selection or the initial overview. Only
  // this explicit action resolves a satellite; picking a task still does not.
  if (state.selectedSatelliteId !== id) selectSatellite(id);
  state.cameraMode = "follow";
  state.orbitEmphasis = true;
  cancelSelectionFlight();
  viewer?.camera.cancelFlight();
  // Keep Follow's selection/telemetry updates in unfolded views without moving
  // the map, even across the date line. Native EntityView is enabled only in 3D.
  if (viewer && state.viewMode === "3d") {
    if (viewer.trackedEntity !== entity) viewer.trackedEntity = entity;
  } else if (viewer?.trackedEntity) releaseCameraTracking();
  viewer?.scene.requestRender();
  updateOrbitHud();
}

function pickedMissionObject(viewer, point) {
  let first = viewer.scene.pick(point)?.id;
  if (first?.id?.startsWith("fov-")) {
    first = viewer.scene.drillPick(point, 10).find((hit) => !hit.id?.id?.startsWith("fov-"))?.id;
  }
  // Orbit paths can share a pixel with their satellite model.
  // Prefer the actual spacecraft there, without disabling depth testing.
  const satellite = typeof first?.id === "string" && !first.model && first.id.startsWith("orbit-")
    ? viewer.scene.drillPick(point, 5).find((hit) => hit.id?.model)?.id : null;
  const id = (satellite || first)?.id;
  if (typeof id !== "string") return null;
  if (id.startsWith("target-")) return {kind: "task", id: id.slice("target-".length)};
  for (const prefix of ["satellite-", "orbit-preview-", "orbit-"]) if (id.startsWith(prefix)) return {kind: "satellite", id: id.slice(prefix.length)};
  return null;
}

function bindGlobePicking(viewer, Cesium) {
  // Manual map gestures take ownership immediately, rather than fighting the
  // selection animation. Only 3D list and keyboard selections move the camera.
  viewer.canvas.addEventListener("pointerdown", cancelSelectionFlight);
  viewer.canvas.addEventListener("wheel", cancelSelectionFlight, {passive: true});
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

const MAP_VIEWS = {"3d": "morphTo3D", "2.5d": "morphToColumbusView", "2d": "morphTo2D"};

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
    cancelSelectionFlight();
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
  viewer.scene[MAP_VIEWS[mode]](cameraMotionDuration());
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
    if (state.replay.playing) { pauseReplay(); updateReplayVisuals(); return; }
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
  document.getElementById("replay-scrub").addEventListener("input", (event) => setReplayTime(event.target.value, true));
  document.getElementById("replay-speed").addEventListener("change", (event) => { state.replay.speed = Number(event.target.value); });
  bindOrbitControls();
  document.addEventListener("visibilitychange", () => { if (document.hidden) pauseReplay(); });
  for (const id of ["target-filter", "satellite-filter"]) {
    document.getElementById(id).addEventListener("change", () => {
      elements.targetList.scrollTop = 0;
      elements.timeline.scrollTop = 0;
      if (id === "satellite-filter" && document.getElementById(id).value !== "all") selectSatellite(document.getElementById(id).value);
      refreshPanels();
    });
  }
}
