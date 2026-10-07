const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(root, "packages/orbitops/web/static/mission.js"), "utf8"), context);
const archive = JSON.parse(fs.readFileSync(path.join(root, "data/eos-bench/reference.json"), "utf8"));
const original = JSON.stringify(archive);
const metric = (series, key) => series.metrics.find(axis => axis.key === key);
const source = (metrics) => ({recomputed_metrics: {...metrics}, source_metrics: {RT: metrics.RT}});

test("all seven selected plans retain exact raw metrics on five bounded radar axes", () => {
  const series = context.radarSeries(archive.plans);
  assert.equal(series.length, 7);
  for (const item of series) {
    assert.equal(item.metrics.map(m => m.key).join(","), "TP,TCR,TM,RT,BD");
    for (const axis of item.metrics) {
      assert.equal(axis.raw, axis.key === "RT" ? item.plan.source_metrics.RT : item.plan.recomputed_metrics[axis.key]);
      assert.ok(Number.isFinite(axis.score) && axis.score >= 0 && axis.score <= 1);
    }
  }
  assert.equal(JSON.stringify(archive), original);
});

test("natural fractions are preserved instead of turning the lowest completion rate into zero", () => {
  const series = context.radarSeries(archive.plans);
  for (const item of series) {
    assert.equal(metric(item, "TCR").score, item.plan.recomputed_metrics.TCR);
    assert.equal(metric(item, "BD").score, item.plan.recomputed_metrics.BD);
    assert.equal(metric(item, "TM").score, 1 - item.plan.recomputed_metrics.TM);
    assert.equal(metric(item, "TP").score, item.plan.recomputed_metrics.TP / 2833);
  }
  const greedy = series.find(s => s.plan.plan_id === "eos-greedy-profit");
  assert.equal(metric(greedy, "TCR").score, .824);
});

test("lower source TM and runtime plot farther outward", () => {
  const series = context.radarSeries(archive.plans);
  const balanced = series.find(s => s.plan.plan_id === "eos-sa-balanced");
  const ppo = series.find(s => s.plan.plan_id === "eos-ppo-profit");
  const greedy = series.find(s => s.plan.plan_id === "eos-greedy-profit");
  assert.ok(metric(balanced, "TM").score > metric(ppo, "TM").score);
  assert.ok(metric(balanced, "RT").score > metric(ppo, "RT").score);
  assert.equal(metric(greedy, "RT").score, 1);
  assert.equal(metric(ppo, "RT").score, greedy.plan.source_metrics.RT / ppo.plan.source_metrics.RT);
});

test("missing, negative and nonfinite metrics are not invented as scored data", () => {
  const [series] = context.radarSeries([source({TP: NaN, TCR: null, TM: -1, RT: Infinity})]);
  for (const axis of series.metrics) {
    assert.equal(axis.raw, null);
    assert.equal(axis.score, null);
  }
  assert.equal(context.radarSeries([]).length, 0);
});

test("zero profit, zero runtime and bounded fractions never produce NaN", () => {
  const series = context.radarSeries([
    source({TP: 0, TCR: 0, TM: 0, BD: 0, RT: 0}),
    source({TP: 0, TCR: 1, TM: 1, BD: 1, RT: 2}),
  ]);
  assert.equal(metric(series[0], "TP").score, 0);
  assert.equal(metric(series[0], "RT").score, 1);
  assert.equal(metric(series[1], "RT").score, 0);
  for (const item of series) {
    assert.ok(item.metrics.every(axis => Number.isFinite(axis.score) && axis.score >= 0 && axis.score <= 1));
  }
});
