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

test("45 degrees is the full cone angle, not its half-angle", () => {
  assert.equal(SensorFov.ANGLE_DEG, 45);
  assert.equal(SensorFov.HALF_ANGLE, 22.5 * Math.PI / 180);
});

test("all twenty cones point at Earth and intersect WGS84 at the same half-angle", () => {
  for (const orbit of archive.replay.orbits) {
    const params = archive.scenario.satellites.find(s => s.satellite_id === orbit.satellite_id).orbital_params;
    const model = OrbitModel.create(orbit, params);
    for (const time of [-86400, 0, 3600, 43200, 3*86400]) {
      const origin = model.cartesian(time), frame = SensorFov.frame(origin);
      assert.ok(frame);
      assert.equal(frame.footprint.length, SensorFov.SEGMENTS);
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

test("no footprint is invented inside Earth and a distant FOV clips to the visible limb", () => {
  assert.equal(SensorFov.frame([1,0,0]), null);
  const distant = SensorFov.frame([50000000,0,0]);
  assert.ok(distant.clipped && distant.footprint.length >= SensorFov.SEGMENTS);
  for (const p of distant.footprint) {
    assert.ok(Math.abs((p[0]**2+p[1]**2)/a**2+p[2]**2/b**2-1) < 1e-12);
    assert.ok(Math.abs(50000000*p[0]/a**2-1) < 1e-12, "true visible-limb plane");
  }
  for (const point of [[], [NaN,0,0], [Infinity,0,0]]) assert.throws(()=>SensorFov.frame(point), /finite Cartesian/);
});

test("circular cone frames do not abruptly rotate when an orbit crosses high latitudes", () => {
  const expectedEast = [-Math.sin(120*Math.PI/180),Math.cos(120*Math.PI/180),0];
  for (const latitude of [-89.9,-80,-72,-70,0,70,72,80,89.9]) {
    const frame = SensorFov.frame(OrbitModel.toCartesian([120,latitude,500000]));
    assert.ok(dot(frame.right,expectedEast) > 1-1e-12);
  }
});

test("a source-directed cone that misses Earth remains visible without invented coverage", () => {
  const origin = OrbitModel.toCartesian([0,0,500000]);
  const frame = SensorFov.frame(origin, [1,0,0], [0,1,0]);
  assert.ok(frame);
  assert.equal(frame.ground, null);
  assert.equal(frame.footprint.length, 0);
  assert.ok(frame.length > 500000 && frame.length < 501000);
  assert.ok(dot(frame.up, [-1,0,0]) > 1 - 1e-12);
  assert.ok(Math.abs(frame.radius/frame.length - Math.tan(SensorFov.HALF_ANGLE)) < 1e-12);
  assert.equal(SensorFov.frame([1,0,0], [1,0,0], [0,1,0]), null);
});

test("the open 128-segment round mesh has no flat cap or four-rib outline", () => {
  const origin = OrbitModel.toCartesian([120,30,500000]);
  const frame = SensorFov.frame(origin), mesh = SensorFov.mesh(frame);
  assert.equal(SensorFov.SEGMENTS, 128);
  assert.equal(mesh.positions.length, 129*3);
  assert.equal(mesh.indices.length, 128*3);
  assert.deepEqual(Array.from(mesh.positions.slice(0,3)), [0,0,.5]);
  const reconstruct = offset => frame.center.map((v,i) => v
    + frame.right[i]*mesh.positions[offset]*frame.radius
    + frame.north[i]*mesh.positions[offset+1]*frame.radius
    + frame.up[i]*mesh.positions[offset+2]*frame.length);
  assert.ok(distance(reconstruct(0),origin) < 1e-7);
  frame.surfaceBoundary.forEach((point,i) => {
    assert.ok(distance(reconstruct((i+1)*3),point) < 1e-7);
    assert.ok(Math.abs(distance(point,frame.footprint[i])-15) < 1e-8);
    assert.equal(mesh.indices[i*3],0,"every triangle is a side, never a bottom cap");
    assert.equal(mesh.indices[i*3+1],i+1);
    assert.equal(mesh.indices[i*3+2],(i+1)%128+1);
  });
});

test("an oblique cone changes its curved rim rather than scaling a flat circular base", () => {
  const origin=[a+500000,0,0];
  const theta=29.5*Math.PI/180;
  const frame=SensorFov.frame(origin,[-Math.cos(theta),Math.sin(theta),0],[0,0,1]);
  assert.equal(frame.footprint.length,128);
  const depths=frame.rim.map(p=>dot(origin.map((v,i)=>v-p[i]),frame.up));
  assert.ok(Math.max(...depths)-Math.min(...depths)>200000,"near and far rays end at different depths");
  for(const p of frame.footprint) assert.ok(Math.abs(dot(unit(p.map((v,i)=>v-origin[i])),frame.up.map(v=>-v))
    -Math.cos(SensorFov.HALF_ANGLE))<1e-12);
  assert.equal(frame.rim,frame.surfaceBoundary,"mesh and footprint have a single boundary");
});

test("partial limb coverage is retained even if the central boresight misses Earth", () => {
  const origin=[a+500000,0,0],theta=75*Math.PI/180;
  const frame=SensorFov.frame(origin,[-Math.cos(theta),Math.sin(theta),0],[0,0,1]);
  assert.equal(frame.ground,null);
  assert.ok(frame.clipped && frame.footprint.length>10);
  for(const p of frame.footprint) {
    assert.ok(Math.abs((p[0]**2+p[1]**2)/a**2+p[2]**2/b**2-1)<1e-10);
    assert.ok(dot(unit(p.map((v,i)=>v-origin[i])),frame.up.map(v=>-v))>=Math.cos(SensorFov.HALF_ANGLE)-1e-10);
    assert.ok(dot(origin.map((v,i)=>v/[a,a,b][i]),p.map((v,i)=>v/[a,a,b][i]))>=1-1e-9);
  }
  const parallel=SensorFov.frame(origin,[-1,0,0],[-1,0,0]);
  assert.ok(parallel.rim.every(p=>p.every(Number.isFinite)),"parallel reference uses a finite fallback");
});
