"use strict";

// Comparison summaries remain available even when full plans have not been fetched.
(() => {
  function create(summaries, fetcher = window.fetch.bind(window)) {
    const plans = new Map(summaries.map(plan => [plan.plan_id, plan]));
    if (plans.size !== summaries.length) throw new Error("Duplicate reference plan.");
    const loaded = new Map(), pending = new Map();
    const store = window.MissionData.create({fetcher});

    function load(id) {
      const summary = plans.get(id);
      if (!summary) return Promise.reject(new Error("Reference plan is unavailable."));
      // The local API still serves the complete, validated reference archive.
      if (Array.isArray(summary.assignments)) return Promise.resolve(summary);
      if (loaded.has(id)) return Promise.resolve(loaded.get(id));
      if (pending.has(id)) return pending.get(id);
      const asset = summary.asset;
      if (!/^[a-z0-9][a-z0-9-]{0,79}$/.test(id)
          || asset?.filename !== `${id}.${asset?.sha256}.json`) {
        return Promise.reject(new Error("Invalid reference plan manifest."));
      }
      const controller = new AbortController();
      let timedOut = false;
      const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
      const promise = store.read(`./plan-data/${asset.filename}`, asset, {
        signal: controller.signal,
        decode(raw) {
          const plan = JSON.parse(new TextDecoder().decode(raw));
          if (plan.plan_id !== id || !Array.isArray(plan.assignments)
              || !Array.isArray(plan.checks?.issues) || !plan.checks.constraints
              || !plan.workloads || !Array.isArray(plan.unassigned_tasks)
              || plan.label !== summary.label || plan.objective !== summary.objective
              || ["source_metrics", "recomputed_metrics"].some(field =>
                JSON.stringify(plan[field]) !== JSON.stringify(summary[field]))) {
            throw new Error("Invalid reference plan data.");
          }
          return plan;
        },
      }).then(plan => { loaded.set(id, plan); return plan; }).catch(error => {
        if (timedOut) throw new Error("Reference plan request timed out.");
        throw error;
      }).finally(() => { clearTimeout(timeout); pending.delete(id); });
      pending.set(id, promise);
      return promise;
    }

    return Object.freeze({load});
  }

  window.ReferencePlans = Object.freeze({create});
})();
