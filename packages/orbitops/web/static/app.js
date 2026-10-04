"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const state = {
  referenceData: null,
  globe: null,
  imageryFallbackActive: false,
  currentPayload: null,
  selectedTaskId: null,
  busy: false,
  pages: {},
  layers: { targets: true, track: true, rays: true, fov: true, illumination: true, labels: false, satelliteLabels: true },
  cameraHome: null,
  targetRowsKey: null,
  assignments: new Map(),
  taskById: new Map(),
  replay: { time: 0, playing: false, speed: 60, direction: 1, windowStart: 0, windowEnd: 43200, lastFrame: 0, lastPaint: 0 },
  orbitModels: new Map(),
  orbitPositions: new Map(),
  orbitStyles: new Map(),
  sensorFovs: new Map(),
  fovPrimitives: null,
  entityTaskStates: new Map(),
  selectedSatelliteId: null,
  satelliteDetailsOpen: false,
  geometrySelectionKey: null,
  cameraMode: "overview",
  viewMode: "3d",
  viewTransition: false,
  orbitEmphasis: false,
};
const deployment = window.ORBITOPS_DEPLOYMENT || { mode: "api" };
const staticDeployment = deployment.mode === "static";
let staticDatasetPromise = null;

const elements = {
  solver: document.getElementById("solver-select"),
  status: document.getElementById("status"),
  results: document.getElementById("results"),
  timeline: document.getElementById("timeline-chart"),
  resources: document.getElementById("resource-chart"),
  globe: document.getElementById("mission-globe"),
  globeLoading: document.getElementById("globe-loading"),
  comparisonChart: document.getElementById("comparison-chart"),
  comparisonLegend: document.getElementById("comparison-legend"),
  comparisonValues: document.getElementById("comparison-values"),
  shell: document.querySelector(".shell"),
  statusIndicator: document.getElementById("status-indicator"),
  targetList: document.getElementById("target-list"),
};
const TASK_COLORS = Object.fromEntries(Object.entries({
  Planned: "accent", Observing: "peach", Completed: "sage", Available: "peach", Unassigned: "danger",
}).map(([status, token]) => [status, getComputedStyle(elements.shell).getPropertyValue(`--${token}`).trim()]));

function textField(id, value) {
  const node = document.getElementById(id);
  node.textContent = value;
  node.title = String(value);
}

function layoutSize(name) {
  return parseFloat(getComputedStyle(elements.shell).getPropertyValue(`--${name}`));
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

function setWorkspaceView(view) {
  elements.shell.dataset.workspaceView = view;
  document.querySelectorAll(".workspace-nav button").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.workspaceView === view));
  });
  setLayersOpen(false);
  refreshPanels();
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
  const tasks = filteredTasks(scenario);
  textField("target-count", tasks.length === scenario.tasks.length ? scenario.tasks.length : `${tasks.length}/${scenario.tasks.length}`);
  // Reuse list nodes during selection, playback and resize: preserve focus and
  // scroll position even with all 500 tasks, including the live "Active now" filter.
  const key = `${result.schedule.solver_name}:${tasks.map((task) => task.task_id).join(",")}`;
  if (state.targetRowsKey === key) {
    elements.targetList.querySelectorAll(".target-row").forEach((row) => {
      const selected = row.dataset.taskId === state.selectedTaskId;
      row.classList.toggle("is-selected", selected);
      row.setAttribute("aria-pressed", String(selected));
      row.dataset.state = taskState(row.dataset.taskId);
      row.querySelector(".target-state").textContent = row.dataset.state;
    });
    return;
  }
  state.targetRowsKey = key;
  const scrollTop = elements.targetList.scrollTop;
  const focusedTaskId = elements.targetList.contains(document.activeElement) ? document.activeElement.dataset.taskId : null;
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
    detail.textContent = `P${task.priority_value.toFixed(0)} · ${task.visibility_windows.length} windows`;
    name.append(title, detail);
    const status = document.createElement("span");
    status.className = "target-state";
    status.textContent = currentState;
    row.append(dot, name, status);
    row.addEventListener("click", () => selectTarget(task.task_id));
    return row;
  });
  elements.targetList.replaceChildren(...rows);
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "chart-empty";
    empty.textContent = "No matching tasks";
    elements.targetList.append(empty);
  }
  elements.targetList.scrollTop = scrollTop;
  if (focusedTaskId) {
    const row = rows.find((item) => item.dataset.taskId === focusedTaskId);
    (row || elements.targetList).focus({ preventScroll: true });
  }
}

function selectTarget(taskId, reveal = true, seek = reveal) {
  const payload = state.currentPayload;
  if (!payload) return;
  const task = payload.scenario.tasks.find((item) => item.task_id === taskId);
  if (!task) return;
  closeSatelliteDetails();
  state.selectedTaskId = taskId;
  const assignment = payload.result.validation.simulation?.tasks.find((item) => item.task_id === taskId);
  if (payload.mode === "reference") {
    state.selectedSatelliteId = assignment?.satellite_id || null;
    if (reveal) state.orbitEmphasis = true;
    if (!assignment && state.cameraMode === "follow") {
      releaseCameraTracking();
      state.cameraMode = "manual";
    }
  }
  if (seek && assignment) {
    state.replay.windowStart = payload.scenario.horizon_start_s;
    state.replay.windowEnd = payload.scenario.horizon_end_s;
    setReplayTime(assignment.start_s, true);
  }
  textField("selected-id", task.task_id);
  textField("selected-coordinates", `${task.target.latitude_deg.toFixed(2)}°, ${task.target.longitude_deg.toFixed(2)}°`);
  textField("selected-priority", `P${task.priority_value.toFixed(0)} / ${task.duration_s.toFixed(1)}s`);
  textField("selected-window", assignment ? `${timeLabel(assignment.start_s)}–${timeLabel(assignment.end_s)}` : "Not scheduled");
  textField("selected-assignment", assignment ? satelliteName(assignment.satellite_id || payload.scenario.satellite.satellite_id) : `${task.visibility_windows.length} candidate windows`);
  document.getElementById("selected-assignment").title = assignment ? `${assignment.satellite_id || payload.scenario.satellite.satellite_id} · ${assignment.window_id}` : "No selected assignment";
  textField("selected-resource-label", "Data / orbit");
  textField("selected-resources", payload.mode === "reference" ? (assignment ? `${(assignment.data_volume_gb * 1024).toFixed(2)} MB / #${assignment.orbit_number}` : "No source assignment") : `${task.energy_cost_wh.toFixed(1)} Wh / ${task.storage_cost_gb.toFixed(1)} GB`);
  textField("selected-state", taskState(taskId));
  document.getElementById("selected-state").classList.toggle("scheduled", Boolean(assignment));
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
    if (window.matchMedia("(max-width: 1000px)").matches) setWorkspaceView("summary");
  }
  if (reveal) {
    if (!filteredTasks(payload.scenario).some((candidate) => candidate.task_id === taskId)) {
      document.getElementById("target-search").value = "";
      document.getElementById("target-filter").value = "all";
      document.getElementById("satellite-filter").value = "all";
    }
    const filtered = filteredTasks(payload.scenario);
    const index = filtered.findIndex((candidate) => candidate.task_id === taskId);
    const capacity = Math.max(1, Math.floor((elements.timeline.clientHeight - 33) / layoutSize("timeline-row-height")));
    if (payload.mode === "reference" && assignment) {
      const selectedSatellite = document.getElementById("satellite-filter").value;
      const satellites = payload.scenario.satellites.filter((satellite) => selectedSatellite === "all" || selectedSatellite === satellite.satellite_id);
      const lane = satellites.findIndex((satellite) => satellite.satellite_id === assignment.satellite_id);
      if (lane >= 0) state.pages.timeline = Math.floor(lane / capacity);
    } else if (index >= 0) state.pages.timeline = Math.floor(index / capacity);
  }
  renderTargetCatalog();
  if (reveal) revealSelectedTask();
  if (!document.getElementById("pane-timeline").hidden) renderGantt(payload.scenario, payload.result);
  if (payload.mode === "reference") renderWorkloads();
  updateReplayVisuals();
}

function revealSelectedTask() {
  const row = [...elements.targetList.children].find((item) => item.dataset.taskId === state.selectedTaskId);
  if (!row) return;
  const bounds = elements.targetList.getBoundingClientRect();
  const box = row.getBoundingClientRect();
  if (box.top < bounds.top) elements.targetList.scrollTop += box.top - bounds.top;
  else if (box.bottom > bounds.bottom) elements.targetList.scrollTop += box.bottom - bounds.bottom;
}

function refreshPanels() {
  const payload = state.currentPayload;
  if (!payload) return;
  renderTargetCatalog();
  if (!document.getElementById("pane-timeline").hidden) renderGantt(payload.scenario, payload.result);
  renderComparison();
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

async function loadStaticDataset() {
  if (!staticDatasetPromise) {
    staticDatasetPromise = fetch("./pages-data.json").then(async (response) => {
      if (!response.ok) throw new Error("EOS-Bench dataset is unavailable.");
      const dataset = await response.json();
      return dataset;
    });
  }
  return staticDatasetPromise;
}

async function api(path) {
  if (staticDeployment) return (await loadStaticDataset()).reference;
  const response = await fetch(path);
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

function setBusy(busy, message) {
  state.busy = busy;
  elements.solver.disabled = busy;
  elements.results.setAttribute("aria-busy", String(busy));
  elements.statusIndicator.classList.toggle("is-busy", busy);
  elements.statusIndicator.classList.remove("is-error");
  elements.status.classList.remove("error");
  if (message) elements.status.textContent = message;
}

function renderComparison() {
  renderReferenceComparison();
}

function renderGantt() {
  renderReferenceGantt();
}

function renderResources() {
  renderWorkloads();
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
  scenario.tasks.forEach((task) => {
    const [x, y] = project(task.target.longitude_deg, task.target.latitude_deg);
    const marker = svgElement("g", { class: `map-marker${scheduledIds.has(task.task_id) ? " is-scheduled" : ""}`,
      "data-task-id": task.task_id, role: "button", tabindex: "0",
      "aria-label": `Inspect ${task.target.name}` });
    marker.append(svgElement("circle", { cx: x, cy: y, r: 4 }));
    marker.append(svgElement("title", {}, `${task.target.name}: ${task.target.latitude_deg.toFixed(2)}°, ${task.target.longitude_deg.toFixed(2)}°`));
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
  map.append(svgElement("text", { x: 20, y: 485, class: "map-caption" }, "2D SCHEMATIC · WGS84"));
  if (state.currentPayload?.replay) addFallbackOrbits(map);
  elements.globe.replaceChildren(map);
  map.addEventListener("click", (event) => {
    if (!event.target.closest(".map-satellite")) closeSatelliteDetails();
  });
  elements.globe.dataset.engine = "fallback";
  updateMapViewControls();
  elements.globeLoading.classList.add("is-hidden");
  updateReplayVisuals();
}

function updateGlobeLayers() {
  if (state.globe) {
    state.globe.entities.values.forEach((entity) => {
      if (entity.id.startsWith("target-")) entity.show = state.layers.targets;
      if (entity.id.startsWith("orbit-")) entity.show = state.layers.track;
      if (entity.id.startsWith("ray-")) entity.show = state.layers.rays;
      if (entity.label && entity.id.startsWith("target-")) entity.label.show = state.layers.labels || entity.id === `target-${state.selectedTaskId}`;
    });
    state.globe.scene.requestRender();
  } else {
    document.querySelectorAll(".map-marker").forEach((marker) => { marker.style.display = state.layers.targets ? "" : "none"; });
    document.querySelectorAll(".map-orbit").forEach((track) => { track.style.display = state.layers.track ? "" : "none"; });
    document.querySelectorAll(".map-ray").forEach((ray) => { ray.style.display = state.layers.rays ? "" : "none"; });
  }
}

function fitMissionView(duration = 0) {
  if (!state.globe || !state.cameraHome || state.viewTransition) return;
  const Cesium = window.Cesium;
  const viewer = state.globe;
  const home = state.cameraHome;
  releaseCameraTracking();
  state.cameraMode = "overview";
  state.orbitEmphasis = false;
  viewer.resize();
  const aspect = elements.globe.clientWidth / Math.max(1, elements.globe.clientHeight);
  if (home.global && state.viewMode === "2d") {
    viewer.camera.flyTo({destination: Cesium.Rectangle.MAX_VALUE, duration,
      orientation: {heading: 0, pitch: -Cesium.Math.PI_OVER_TWO, roll: 0}});
  } else if (home.global && state.viewMode === "2.5d") {
    const edge = viewer.scene.mapProjection.project(Cesium.Cartographic.fromDegrees(180, 90));
    const altitude = home.missionCenter.radius - Cesium.Ellipsoid.WGS84.maximumRadius;
    const pitch = Cesium.Math.toRadians(55);
    const range = window.OrbitReplay.flatMapRange(edge.x, edge.y, altitude, pitch, viewer.camera.frustum.fovy, aspect);
    viewer.camera.flyTo({destination: new Cesium.Cartesian3(0, -range * Math.cos(pitch), range * Math.sin(pitch)),
      orientation: {heading: 0, pitch: -pitch, roll: 0}, convert: false, duration});
  } else if (home.global) {
    const range = Math.max(1400000, window.OrbitReplay.fitRange(home.missionCenter.radius, viewer.camera.frustum.fovy, aspect, 1.035));
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(home.longitudeCenter, home.latitudeCenter, range - Cesium.Ellipsoid.WGS84.maximumRadius),
      orientation: { heading: 0, pitch: -Cesium.Math.PI_OVER_TWO, roll: 0 },
      duration,
    });
  } else {
    const range = Math.max(1400000, window.OrbitReplay.fitRange(home.missionCenter.radius, viewer.camera.frustum.fovy || Cesium.Math.PI_OVER_THREE, aspect, 1.12));
    viewer.camera.flyToBoundingSphere(home.missionCenter, {
      duration,
      offset: new Cesium.HeadingPitchRange(state.viewMode === "3d" ? Cesium.Math.toRadians(-18) : 0, Cesium.Math.toRadians(state.viewMode === "2d" ? -90 : -68), range),
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
  return commandImageryLayer(Cesium, provider);
}

function commandImageryLayer(Cesium, provider) {
  // Presentation only: keep geometry, task colours and source data untouched.
  return new Cesium.ImageryLayer(provider, {
    brightness: .84,
    contrast: .98,
    saturation: .66,
    gamma: 1.1,
  });
}

function geographicGridLayer(Cesium) {
  // Geographic tile guides only: not sensor coverage, orbits or measured data.
  const provider = new Cesium.GridImageryProvider({
    tilingScheme: new Cesium.GeographicTilingScheme(),
    cells: 4,
    color: Cesium.Color.fromCssColorString("#6ad6ee").withAlpha(.16),
    glowColor: Cesium.Color.TRANSPARENT,
    glowWidth: 0,
    backgroundColor: Cesium.Color.TRANSPARENT,
  });
  return new Cesium.ImageryLayer(provider);
}

function nasaBlueMarbleLayer(Cesium) {
  const provider = new Cesium.UrlTemplateImageryProvider({
    url: "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg",
    tilingScheme: new Cesium.WebMercatorTilingScheme(),
    maximumLevel: 8,
    credit: new Cesium.Credit("NASA Earth Observatory · GIBS"),
  });
  return commandImageryLayer(Cesium, provider);
}

function styleMapAttribution() {
  // Keep Cesium's original credit popup and required provider attribution.
  const link = elements.globe.querySelector(".cesium-credit-expand-link");
  if (!link) return;
  const icon = svgElement("svg", {viewBox: "0 0 24 24", "aria-hidden": "true"});
  icon.append(svgElement("circle", {cx: 12, cy: 12, r: 8}), svgElement("path", {d: "M12 11v6m0-10v.5"}));
  link.replaceChildren(icon);
  link.classList.add("attribution-icon");
  link.setAttribute("role", "button");
  link.setAttribute("aria-label", "Map credits");
  link.title = "Map credits";
  link.tabIndex = 0;
  link.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      link.click();
    }
  });
}

function renderMissionGlobe(scenario, result) {
  const scheduledTasks = result.validation.simulation?.tasks || [];
  const scheduledIds = new Set(scheduledTasks.map((task) => task.task_id));
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
        scene3DOnly: false,
        sceneModePicker: false,
        mapMode2D: Cesium.MapMode2D.ROTATE,
        selectionIndicator: false,
        timeline: false,
        shouldAnimate: false,
        requestRenderMode: true,
        maximumRenderTimeChange: Infinity,
      });
      styleMapAttribution();
      state.globe.imageryLayers.add(primaryImagery);
      state.globe.imageryLayers.add(geographicGridLayer(Cesium));
      bindGlobePicking(state.globe, Cesium);
      bindMapViewEvents(state.globe);
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
      state.globe.scene.backgroundColor = Cesium.Color.fromCssColorString("#02060b");
      state.globe.scene.globe.baseColor = Cesium.Color.fromCssColorString("#0a2538");
      state.globe.scene.globe.enableLighting = true;
      // Keep the day/night distinction when following a low-orbit satellite.
      state.globe.scene.globe.lightingFadeOutDistance = 0;
      state.globe.scene.globe.lightingFadeInDistance = 1;
      state.globe.scene.globe.dynamicAtmosphereLighting = true;
      state.globe.scene.globe.dynamicAtmosphereLightingFromSun = true;
      state.globe.scene.globe.showGroundAtmosphere = true;
      state.globe.scene.globe.atmosphereBrightnessShift = -.22;
      state.globe.scene.skyAtmosphere.brightnessShift = -.05;
      // Native star map stays behind the Earth and fades out in planar views.
      state.globe.scene.skyBox.show = true;
      state.globe.scene.sun.show = true;
      state.globe.scene.sun.glowFactor = .4;
      state.globe.scene.sunBloom = false;
      state.globe.scene.moon.show = false;
      state.globe.useBrowserRecommendedResolution = false;
      state.globe.resolutionScale = Math.min(2, window.devicePixelRatio || 1) / (window.devicePixelRatio || 1);
      state.globe.scene.screenSpaceCameraController.minimumZoomDistance = 15000;
    }

    const viewer = state.globe;
    releaseCameraTracking();
    clearSensorFovs();
    viewer.entities.removeAll();
    state.orbitPositions.clear();
    state.orbitStyles.clear();
    state.entityTaskStates.clear();
    state.geometrySelectionKey = null;
    setupReferenceGlobe(viewer, Cesium);
  } catch (error) {
    console.warn("Cesium mission view unavailable", error);
    if (state.globe && !state.globe.isDestroyed()) state.globe.destroy();
    state.globe = null;
    state.fovPrimitives = null;
    state.sensorFovs.clear();
    state.imageryFallbackActive = false;
    renderGlobeFallback(scenario, scheduledIds);
  }
}

function renderResult(payload) {
  const { scenario, result } = payload;
  const previousScenarioId = state.currentPayload?.scenario.scenario_id;
  state.currentPayload = payload;
  state.taskById = new Map(scenario.tasks.map((task) => [task.task_id, task]));
  state.assignments = new Map((result.validation.simulation?.tasks || []).map((task) => [task.task_id, task]));
  configureReplay(payload);
  if (previousScenarioId !== scenario.scenario_id) {
    state.pages = {};
    state.selectedTaskId = result.validation.simulation?.tasks[0]?.task_id || scenario.tasks[0]?.task_id;
  }
  renderEvaluation(payload);
  configureModeDetails(payload);
  renderMissionGlobe(scenario, result);
  selectTarget(state.selectedTaskId, false);
  refreshPanels();
}

async function loadReferencePlan() {
  if (state.busy || !state.referenceData || !elements.solver.reportValidity()) return;
  setBusy(true, "Loading plan…");
  try {
    const plan = state.referenceData.plans.find((item) => item.plan_id === elements.solver.value);
    if (!plan) throw new Error("Reference plan is unavailable.");
    renderResult(window.OrbitReplay.referencePayload(state.referenceData, plan));
    elements.status.textContent = `${plan.label} · Ready`;
  } catch (error) {
    setBusy(false);
    elements.statusIndicator.classList.add("is-error");
    elements.status.classList.add("error");
    elements.status.textContent = error instanceof Error ? error.message : "Plan could not be loaded.";
  } finally {
    if (state.busy) setBusy(false);
    refreshPanels();
  }
}

async function initialize() {
  setBusy(true, "Loading EOS-Bench…");
  try {
    // Fonts must be ready before Cesium rasterizes labels or SVG measures text.
    // A missing font must not prevent the source archive from opening.
    const fontReady = document.fonts.load('500 12px "Inter"').catch(() => []);
    const [referenceData] = await Promise.all([api("/api/reference/data"), fontReady]);
    if (!referenceData?.scenario || !referenceData.plans?.length) throw new Error("EOS-Bench reference data is unavailable.");
    state.referenceData = referenceData;
    populateSelect(elements.solver, referenceData.plans, "plan_id", (plan) => plan.label);
    elements.solver.value = referenceData.plans.some((plan) => plan.plan_id === "eos-sa-balanced") ? "eos-sa-balanced" : referenceData.plans[0].plan_id;
    setBusy(false);
    await loadReferencePlan();
  } catch (error) {
    setBusy(false);
    elements.solver.disabled = true;
    elements.statusIndicator.classList.add("is-error");
    elements.status.classList.add("error");
    elements.status.textContent = error instanceof Error ? error.message : "EOS-Bench could not start.";
  }
}

elements.solver.addEventListener("change", loadReferencePlan);
const comparisonInfo = document.getElementById("comparison-info");
const comparisonScales = document.getElementById("comparison-scales");
function setComparisonScalesOpen(open) {
  comparisonInfo.setAttribute("aria-expanded", String(open));
  comparisonScales.hidden = !open;
}
comparisonInfo.addEventListener("click", () => setComparisonScalesOpen(comparisonScales.hidden));
document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest(".comparison-card")) setComparisonScalesOpen(false);
});
document.querySelectorAll(".workspace-nav button").forEach((button) => {
  button.addEventListener("click", () => setWorkspaceView(button.dataset.workspaceView));
});
for (const name of ["targets", "track", "rays", "fov", "illumination", "labels"]) {
  document.getElementById(`toggle-${name}`).addEventListener("click", (event) => {
    state.layers[name] = !state.layers[name];
    event.currentTarget.setAttribute("aria-pressed", String(state.layers[name]));
    updateGlobeLayers();
    updateReplayVisuals();
  });
}
const layerToggle = document.getElementById("toggle-layers");
const layerOptions = document.getElementById("layer-options");
function setLayersOpen(open) {
  layerToggle.setAttribute("aria-expanded", String(open));
  layerOptions.hidden = !open;
}
layerToggle.addEventListener("click", () => setLayersOpen(layerOptions.hidden));
document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest("#layer-controls")) setLayersOpen(false);
});
document.getElementById("layer-controls").addEventListener("focusout", (event) => {
  if (!event.currentTarget.contains(event.relatedTarget)) setLayersOpen(false);
});
document.getElementById("reset-view").addEventListener("click", () => {
  if (state.globe && state.cameraHome) {
    fitMissionView(window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 0.6);
  } else if (state.currentPayload) {
    renderMissionGlobe(state.currentPayload.scenario, state.currentPayload.result);
  }
});
bindTabs();
bindMissionControls();
bindPager("timeline", refreshPanels);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !comparisonScales.hidden) {
    event.preventDefault();
    setComparisonScalesOpen(false);
    comparisonInfo.focus();
    return;
  }
  if (event.key === "Escape" && !layerOptions.hidden) {
    event.preventDefault();
    setLayersOpen(false);
    layerToggle.focus();
    return;
  }
});
let resizeFrame;
const resizeObserver = new ResizeObserver(() => {
  cancelAnimationFrame(resizeFrame);
  resizeFrame = requestAnimationFrame(refreshPanels);
});
for (const host of [elements.timeline, elements.resources, elements.targetList, elements.comparisonChart]) resizeObserver.observe(host);
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
