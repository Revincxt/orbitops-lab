"use strict";

// Pure replay utilities. All intervals are half-open and all absolute times UTC.
window.OrbitReplay = Object.freeze({
  taskState(time, assignment, windows = []) {
    if (assignment) {
      if (time >= assignment.end_s) return "Completed";
      if (time >= assignment.start_s) return "Observing";
      return "Planned";
    }
    return windows.some((window) => window.start_s <= time && time < window.end_s) ? "Available" : "Unassigned";
  },
  createTaskStates(scenario, assignments) {
    // Only tasks crossing a source boundary can change state. Keep the original
    // resolver for exact half-open semantics, including reverse playback/seeks.
    const byId = new Map(scenario.tasks.map(task => [task.task_id, task]));
    const events = [];
    for (const task of scenario.tasks) {
      const assignment = assignments.get(task.task_id);
      const intervals = assignment ? [assignment] : task.visibility_windows;
      for (const interval of intervals) {
        events.push([interval.start_s, task.task_id], [interval.end_s, task.task_id]);
      }
      events.push([scenario.horizon_start_s, task.task_id], [scenario.horizon_end_s, task.task_id]);
    }
    events.sort((a, b) => a[0] - b[0]);
    const upperBound = time => {
      let low = 0, high = events.length;
      while (low < high) {
        const middle = (low + high) >>> 1;
        if (events[middle][0] <= time) low = middle + 1; else high = middle;
      }
      return low;
    };
    const values = new Map();
    let previousTime = null, position = 0, changed = [];
    const resolve = this.taskState.bind(this);
    function update(time) {
      if (time === previousTime) return changed;
      const nextPosition = upperBound(time);
      const candidates = previousTime === null ? byId.keys() : new Set(
        events.slice(Math.min(position, nextPosition), Math.max(position, nextPosition)).map(event => event[1]));
      changed = [];
      for (const id of candidates) {
        const assignment = assignments.get(id);
        const outside = time < scenario.horizon_start_s || time >= scenario.horizon_end_s;
        const current = outside ? (assignment ? (time < scenario.horizon_start_s ? "Planned" : "Completed") : "Unassigned")
          : resolve(time, assignment, byId.get(id).visibility_windows);
        if (values.get(id) !== current) { values.set(id, current); changed.push(id); }
      }
      previousTime = time;
      position = nextPosition;
      return changed;
    }
    return Object.freeze({update, get: id => values.get(id)});
  },
  utc(epoch, seconds, date = false) {
    if (!epoch) return `T+${Math.floor(seconds / 3600).toString().padStart(2, "0")}:${Math.floor(seconds % 3600 / 60).toString().padStart(2, "0")}:${Math.floor(seconds % 60).toString().padStart(2, "0")}`;
    const iso = new Date(Date.parse(epoch) + seconds * 1000).toISOString();
    return date ? `${iso.slice(0, 10)} ${iso.slice(11, 19)} UTC` : iso.slice(11, 19);
  },
  sampleIndex(samples, time) {
    let left = 0;
    let right = samples.length - 1;
    while (left < right) {
      const middle = Math.ceil((left + right) / 2);
      if (samples[middle][0] <= time) left = middle;
      else right = middle - 1;
    }
    return left;
  },
  point(samples, time) {
    const index = this.sampleIndex(samples, time);
    const a = samples[index];
    const b = samples[Math.min(index + 1, samples.length - 1)];
    const fraction = b[0] === a[0] ? 0 : Math.max(0, Math.min(1, (time - a[0]) / (b[0] - a[0])));
    const delta = ((b[1] - a[1] + 540) % 360) - 180;
    return [((a[1] + delta * fraction + 540) % 360) - 180, a[2] + (b[2] - a[2]) * fraction, a[3] + (b[3] - a[3]) * fraction];
  },
  trackSegments(samples, start, end) {
    start = Math.max(samples[0][0], start);
    end = Math.min(samples.at(-1)[0], end);
    if (end <= start) return [];
    const points = [[start, ...this.point(samples, start)],
      ...samples.slice(this.sampleIndex(samples, start) + 1, this.sampleIndex(samples, end) + 1)];
    if (points.at(-1)[0] !== end) points.push([end, ...this.point(samples, end)]);
    const segments = [[]];
    points.forEach((point, index) => {
      const previous = points[index - 1];
      if (previous && Math.abs(point[1] - previous[1]) > 180) {
        const unwrapped = point[1] + (previous[1] > 0 ? 360 : -360);
        const edge = previous[1] > 0 ? 180 : -180;
        const fraction = (edge - previous[1]) / (unwrapped - previous[1]);
        const crossing = [previous[0] + (point[0] - previous[0]) * fraction, edge,
          previous[2] + (point[2] - previous[2]) * fraction, previous[3] + (point[3] - previous[3]) * fraction];
        segments.at(-1).push(crossing);
        segments.push([[crossing[0], -edge, crossing[2], crossing[3]]]);
      }
      segments.at(-1).push(point);
    });
    return segments.filter((segment) => segment.length > 1);
  },
  fitRange(radius, verticalFov, aspect, padding = 1.035) {
    const halfVertical = verticalFov / 2;
    const halfHorizontal = Math.atan(Math.tan(halfVertical) * aspect);
    return radius / Math.sin(Math.min(halfVertical, halfHorizontal)) * padding;
  },
  flatMapRange(halfWidth, halfHeight, altitude, pitch, verticalFov, aspect, padding = 1.06) {
    // Fit a tilted geographic map and its source-altitude envelope in both axes.
    const vertical = Math.tan(verticalFov / 2);
    const horizontal = vertical * aspect;
    const sin = Math.sin(pitch), cos = Math.cos(pitch);
    return Math.max(halfWidth / horizontal + halfHeight * cos + altitude * sin,
      halfHeight * sin / vertical + halfHeight * cos,
      (halfHeight * sin + altitude * cos) / vertical - halfHeight * cos + altitude * sin) * padding;
  },
  referencePayload(archive, plan) {
    return {
      mode: "reference", scenario: archive.scenario, replay: archive.replay,
      provenance: archive.provenance, reference_plan: plan,
      result: {
        schedule: {scenario_id: archive.scenario.scenario_id, solver_name: plan.plan_id, seed: null, tasks: plan.assignments, metadata: {stop_reason: "imported_reference", objective: plan.objective}},
        validation: {is_feasible: null, reference_consistent: !plan.checks.issues.length, scope: "reference consistency only", issues: plan.checks.issues, constraints: plan.checks.constraints, simulation: {tasks: plan.assignments}},
        metrics: {total_value: plan.recomputed_metrics.TP, completed_tasks: plan.assignments.length, total_slew_time_s: null},
        runtime_s: plan.source_metrics.RT,
      },
      evaluation: {...plan.recomputed_metrics, RT: plan.source_metrics.RT},
    };
  },
});
