const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const context = vm.createContext({window: {}});
for (const filename of ["replay.js", "orbit-model.js"]) {
  vm.runInContext(fs.readFileSync(path.join(root, "packages/orbitops/web/static", filename), "utf8"), context);
}
const {OrbitModel, OrbitReplay} = context.window;
const archive = JSON.parse(fs.readFileSync(path.join(root, "data/eos-bench/reference.json"), "utf8"));
const original = JSON.stringify(archive);
const elements = (orbit) => archive.scenario.satellites.find(s => s.satellite_id === orbit.satellite_id).orbital_params;
const distance = (a, b) => Math.hypot(...a.map((x, i) => x - b[i]));

test("source epochs are explicitly UTC, including Orekit's textual epoch", () => {
  assert.equal(OrbitModel.epochUTC("18 Nov 2025 12:00:00.000"), Date.parse("2025-11-18T12:00:00Z"));
  assert.equal(OrbitModel.epochUTC("2025-11-18T12:00:00Z"), Date.parse("2025-11-18T12:00:00Z"));
  assert.ok(Number.isNaN(OrbitModel.epochUTC("not an epoch")));
});

test("WGS84 Cartesian/geodetic conversion round-trips near both poles and the seam", () => {
  for (const point of [[180,0,500000], [-179.999,89.999,700000], [130,-89.999,300000], [72,-11,600000]]) {
    const restored = OrbitModel.toGeodetic(OrbitModel.toCartesian(point));
    assert.ok(distance(restored, point) < 1e-6, `${restored} != ${point}`);
  }
});

test("all twenty satellites retain every original source sample and period", () => {
  for (const orbit of archive.replay.orbits) {
    const model = OrbitModel.create(orbit, elements(orbit));
    assert.ok(Math.abs(model.period - orbit.period_s) < 1e-8);
    for (const sample of orbit.samples) {
      assert.ok(distance(model.cartesian(sample[0]), OrbitModel.toCartesian(sample.slice(1))) < 1e-6);
      assert.deepEqual(Array.from(model.point(sample[0])), Array.from(OrbitReplay.point(orbit.samples, sample[0])));
    }
  }
});

test("both source boundaries are position-continuous, with no frozen endpoint", () => {
  for (const orbit of archive.replay.orbits) {
    const model = OrbitModel.create(orbit, elements(orbit));
    for (const [boundary, direction] of [[model.sourceStart,-1], [model.sourceEnd,1]]) {
      const exact = model.cartesian(boundary);
      assert.ok(distance(model.cartesian(boundary + direction * .001), exact) < 10);
      assert.ok(distance(model.cartesian(boundary + direction * 60), exact) > 300000);
    }
  }
});

test("source-calibrated inertial vectors rotate without position scaling", () => {
  for (const orbit of archive.replay.orbits) {
    const model = OrbitModel.create(orbit, elements(orbit));
    for (const time of [-86400, 0, 123.5, 21600, 43200, 43201]) {
      const axes = [[1,0,0], [0,1,0], [0,0,1]].map(v => model.fixedVector(v, time));
      const dot = (a, b) => a.reduce((sum, v, i) => sum + v*b[i], 0);
      const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
      for (const axis of axes) assert.ok(Math.abs(Math.hypot(...axis) - 1) < 1e-12);
      assert.ok(Math.abs(dot(axes[0], axes[1])) < 1e-12);
      assert.ok(distance(cross(axes[0], axes[1]), axes[2]) < 1e-12);
      assert.ok(Math.abs(Math.hypot(...model.fixedVector([3,4,0], time)) - 5) < 1e-12);
    }
    assert.throws(() => model.fixedVector([NaN,0,0], 0), /finite/);
    assert.throws(() => model.fixedVector([1,0,0], Infinity), /finite/);
  }
});

test("forward and backward holdouts agree with unseen Orekit source samples", () => {
  for (const orbit of archive.replay.orbits) {
    for (const subset of [orbit.samples.slice(0,21), orbit.samples.slice(-21)]) {
      const model = OrbitModel.create({...orbit, samples:subset}, elements(orbit));
      for (const time of [0, 630, 3600, 21600, 43200]) {
        if (model.sourceStart <= time && time <= model.sourceEnd) continue;
        const truth = OrbitModel.toCartesian(orbit.samples.find(sample => sample[0] === time).slice(1));
        assert.ok(distance(model.cartesian(time), truth) < 100, `${orbit.satellite_id} at ${time}`);
      }
    }
  }
});

test("multi-day, multi-year extensions remain finite and bounded by the source ellipse", () => {
  for (const orbit of archive.replay.orbits) {
    const params = elements(orbit), model = OrbitModel.create(orbit, params);
    for (const time of [-3650*86400, -30*86400, -1, 43201, 30*86400, 3650*86400]) {
      const position = model.cartesian(time), radius = Math.hypot(...position);
      assert.ok(position.every(Number.isFinite));
      assert.ok(radius >= params.semi_major_axis_km * 1000 * (1 - params.eccentricity) - .01);
      assert.ok(radius <= params.semi_major_axis_km * 1000 * (1 + params.eccentricity) + .01);
    }
  }
});

test("track sampling stays bounded, monotonic, and preserves date-line splits", () => {
  for (const orbit of archive.replay.orbits) {
    const model = OrbitModel.create(orbit, elements(orbit));
    for (const time of [-30*86400, -1, 0, 43200, 43201, 30*86400]) {
      const start = time - model.period/2, end = time + model.period/2;
      const samples = model.trackSamples(start, end);
      assert.ok(samples.length <= Math.ceil(model.period/30) + 4);
      assert.equal(samples[0][0], start);
      assert.equal(samples.at(-1)[0], end);
      assert.ok(samples.every((sample, i) => !i || sample[0] > samples[i-1][0]));
      for (const segment of OrbitReplay.trackSegments(samples,start,end)) {
        assert.ok(segment.every((point, i) => !i || Math.abs(point[1]-segment[i-1][1]) <= 180));
      }
    }
  }
});

test("invalid source elements or non-finite time fail explicitly", () => {
  const orbit = archive.replay.orbits[0], params = elements(orbit);
  for (const patch of [{eccentricity:1}, {semi_major_axis_km:1}, {epoch:"invalid"}, {inclination_deg:NaN}]) {
    assert.throws(() => OrbitModel.create(orbit,{...params,...patch}), /invalid source orbital elements/);
  }
  assert.throws(() => OrbitModel.create(orbit,params).cartesian(NaN), /finite/);
  assert.equal(JSON.stringify(archive), original);
});
