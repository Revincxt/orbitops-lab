const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const context = vm.createContext({window: {}});
for (const filename of ["replay.js", "orbit-model.js", "sensor-fov.js"]) {
  vm.runInContext(fs.readFileSync(path.join(root, "packages/orbitops/web/static", filename), "utf8"), context);
}
const {SensorFov, OrbitModel} = context.window;
const archive = JSON.parse(fs.readFileSync(path.join(root, "data/eos-bench/reference.json"), "utf8"));
const original = JSON.stringify(archive);
const dot = (a, b) => a.reduce((sum, value, i) => sum + value * b[i], 0);
const distance = (a, b) => Math.hypot(...a.map((x, i) => x - b[i]));
const unit = v => v.map(x => x / Math.hypot(...v));
const a = 6378137, b = a * (1 - 1 / 298.257223563);

test("15 degrees is the full cone angle, not its half-angle", () => {
  assert.equal(SensorFov.ANGLE_DEG, 15);
  assert.equal(SensorFov.HALF_ANGLE, 7.5 * Math.PI / 180);
});

test("all twenty cones point at Earth and intersect WGS84 at the same half-angle", () => {
  for (const orbit of archive.replay.orbits) {
    const params = archive.scenario.satellites.find(s => s.satellite_id === orbit.satellite_id).orbital_params;
    const model = OrbitModel.create(orbit, params);
    for (const time of [-86400, 0, 3600, 43200, 3*86400]) {
      const origin = model.cartesian(time), frame = SensorFov.frame(origin);
      assert.ok(frame);
      assert.equal(frame.footprint.length, 48);
      assert.ok(distance(frame.center.map((v, i) => v + frame.up[i]*frame.length/2), origin) < 1e-8);
      assert.ok(Math.abs(frame.radius/frame.length - Math.tan(SensorFov.HALF_ANGLE)) < 1e-12);
      assert.ok(Math.abs(dot(frame.right,frame.up)) < 1e-12);
      assert.ok(Math.abs(dot(frame.north,frame.up)) < 1e-12);
      for (const point of frame.footprint) {
        assert.ok(Math.abs((point[0]**2+point[1]**2)/a**2+point[2]**2/b**2-1) < 1e-12);
        const beam = unit(point.map((v, i) => v - origin[i]));
        assert.ok(Math.abs(dot(beam,frame.up.map(v=>-v)) - Math.cos(SensorFov.HALF_ANGLE)) < 1e-12);
      }
    }
  }
  assert.equal(JSON.stringify(archive), original);
});

test("polar and date-line frames remain orthonormal and finite", () => {
  for (const point of [[0,90,500000],[0,-90,500000],[179.99,0,500000],[-179.99,89.9,800000]]) {
    const frame = SensorFov.frame(OrbitModel.toCartesian(point));
    assert.ok(frame && frame.footprint.every(p=>p.every(Number.isFinite)));
    for (const axis of [frame.up,frame.right,frame.north]) assert.ok(Math.abs(Math.hypot(...axis)-1) < 1e-12);
  }
});

test("no footprint is invented when a cone ray misses Earth or the apex is inside it", () => {
  assert.equal(SensorFov.frame([1,0,0]), null);
  assert.equal(SensorFov.frame([50000000,0,0]), null);
  for (const point of [[], [NaN,0,0], [Infinity,0,0]]) assert.throws(()=>SensorFov.frame(point), /finite Cartesian/);
});

test("cone ribs do not abruptly rotate when an orbit crosses high latitudes", () => {
  const expectedEast = [-Math.sin(120*Math.PI/180),Math.cos(120*Math.PI/180),0];
  for (const latitude of [-89.9,-80,-72,-70,0,70,72,80,89.9]) {
    const frame = SensorFov.frame(OrbitModel.toCartesian([120,latitude,500000]));
    assert.ok(dot(frame.right,expectedEast) > 1-1e-12);
  }
});
