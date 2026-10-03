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
  referencePayload(archive, plan) {
    return {
      mode: "reference", scenario: archive.scenario, replay: archive.replay,
      provenance: archive.provenance, reference_plan: plan,
      result: {
        schedule: {scenario_id: archive.scenario.scenario_id, solver_name: plan.plan_id, seed: null, tasks: plan.assignments, metadata: {stop_reason: "imported_reference", objective: plan.objective}},
        validation: {is_feasible: null, reference_consistent: !plan.checks.issues.length, scope: "reference consistency only", issues: plan.checks.issues, simulation: {tasks: plan.assignments}},
        metrics: {total_value: plan.recomputed_metrics.TP, completed_tasks: plan.assignments.length, total_slew_time_s: null},
        runtime_s: plan.source_metrics.RT,
      },
      evaluation: {...plan.recomputed_metrics, RT: plan.source_metrics.RT}, convergence: [],
      run_metadata: {seed: "not recorded", evaluation_budget: "not recorded", evaluations: null, stop_reason: "imported_reference", source_revision: archive.provenance.revision, software_version: "EOS-Bench", budget_profile: "source not recorded"},
    };
  },
});
