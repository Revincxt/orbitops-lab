const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), vm = require("node:vm"), path = require("node:path");
const root = path.resolve(__dirname, "../.."), context = vm.createContext({window: {}});
for (const name of ["replay.js", "orbit-model.js", "satellite-attitude.js", "sensor-fov.js"]) {
  vm.runInContext(fs.readFileSync(path.join(root, "packages/orbitops/web/static", name), "utf8"), context);
}
const {OrbitModel: M, SatelliteAttitude: A, SensorFov: F} = context.window;
const archive = JSON.parse(fs.readFileSync(path.join(root, "data/eos-bench/reference.json")));
const original = JSON.stringify(archive);
const models = new Map(archive.replay.orbits.map(o => [o.satellite_id, M.create(o,
  archive.scenario.satellites.find(s => s.satellite_id === o.satellite_id).orbital_params)]));
const dot = (a, b) => a.reduce((sum, v, i) => sum + v*b[i], 0);
const distance = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));
const identityModel = {fixedVector: vector => vector};
const assignment = angles => ({start_s: 10, end_s: 12, sat_angles: {
  yaw_angles: angles.map(a => a[0]), pitch_angles: angles.map(a => a[1]), roll_angles: angles.map(a => a[2]),
}});

// Independent elemental vector rotations, not the production quaternion formula.
function bodyToReference(vector, yaw, pitch, roll) {
  const rad = Math.PI/180;
  let [x, y, z] = vector;
  [y, z] = [y*Math.cos(roll*rad) - z*Math.sin(roll*rad), y*Math.sin(roll*rad) + z*Math.cos(roll*rad)];
  [x, z] = [x*Math.cos(pitch*rad) + z*Math.sin(pitch*rad), -x*Math.sin(pitch*rad) + z*Math.cos(pitch*rad)];
  [x, y] = [x*Math.cos(yaw*rad) - y*Math.sin(yaw*rad), x*Math.sin(yaw*rad) + y*Math.cos(yaw*rad)];
  return [x, y, z];
}

test("ZYX frame-transform samples are inverted and the model's -Z matches Orekit's sensor +Z", () => {
  for (const angles of [[0,0,0], [90,0,0], [0,90,0], [0,0,90], [35,25,-40]]) {
    const frame = A.frame(assignment([angles, angles]), 10, identityModel);
    assert.ok(distance(frame.direction, bodyToReference([0,0,1], ...angles)) < 1e-12);
    assert.ok(distance(frame.x, bodyToReference([1,0,0], ...angles)) < 1e-12);
    assert.ok(distance(frame.y, bodyToReference([0,-1,0], ...angles)) < 1e-12);
    assert.ok(distance(frame.modelAxes.slice(6).map(v => -v), frame.direction) < 1e-12);
  }
});

test("all seven plans use every original Euler sample without target-lock corrections", () => {
  let misses = 0, clipped = 0, samples = 0;
  for (const plan of archive.plans) for (const a of plan.assignments) {
    const model = models.get(a.satellite_id), angles = a.sat_angles;
    for (let i = 0; i < angles.yaw_angles.length; i++) {
      const time = a.start_s + i, frame = A.frame(a, time, model), origin = model.cartesian(time);
      const expected = model.fixedVector(bodyToReference([0,0,1],
        angles.yaw_angles[i], angles.pitch_angles[i], angles.roll_angles[i]), time);
      assert.ok(distance(frame.direction, expected) < 1e-12);
      const axes = [frame.x, frame.y, frame.modelAxes.slice(6)];
      for (const axis of axes) assert.ok(Math.abs(Math.hypot(...axis) - 1) < 1e-12);
      assert.ok(Math.abs(dot(axes[0], axes[1])) < 1e-12);
      const fov = F.frame(origin, frame.direction, frame.x);
      assert.ok(fov && fov.footprint.every(p => p.every(Number.isFinite)));
      assert.ok(dot(fov.up.map(v => -v), frame.direction) > 1 - 1e-12);
      if (!fov.footprint.length) misses++;
      if (fov.clipped && fov.footprint.length) clipped++;
      samples++;
    }
    assert.equal(A.frame(a, a.end_s, model), null);
    assert.equal(A.frame(a, a.start_s - .001, model), null);
  }
  assert.ok(samples > 30000);
  assert.ok(misses > 0 && clipped > 0, "source attitudes exercise missed Earth and clipped footprints");
  assert.equal(JSON.stringify(archive), original);
});

test("fractional playback uses shortest-arc SLERP and holds the last sample until task end", () => {
  const a = assignment([[0,0,0], [0,0,90]]);
  const frame = A.frame(a, 10.5, identityModel);
  assert.ok(distance(frame.direction, [0,-Math.SQRT1_2,Math.SQRT1_2]) < 1e-12);
  const last = A.frame(a, 11, identityModel);
  assert.ok(distance(A.frame(a, 11.999, identityModel).direction, last.direction) < 1e-12);
  const seam = A.frame(assignment([[179,0,0], [-179,0,0]]), 10.5, identityModel);
  assert.ok(distance(seam.x, [-1,0,0]) < 1e-12);
  assert.equal(A.sample(a, 12), null);
  const first = A.frame(a, 10.25, identityModel);
  A.frame(a, 10.75, identityModel);
  assert.ok(distance(A.frame(a, 10.25, identityModel).direction, first.direction) < 1e-12);
});

test("missing or malformed samples never fabricate a source attitude", () => {
  assert.equal(A.frame(null, 0, null), null);
  for (const sat_angles of [null, {}, {yaw_angles: [], pitch_angles: [], roll_angles: []},
    {yaw_angles: [0], pitch_angles: [0,1], roll_angles: [0]},
    {yaw_angles: [NaN], pitch_angles: [0], roll_angles: [0]}]) {
    assert.equal(A.frame({...assignment([[0,0,0]]), sat_angles}, 10, identityModel), null);
  }
  assert.equal(A.sample(assignment([[0,0,0]]), NaN), null);
  assert.equal(A.sample(assignment([[0,0,0]]), 10, 0), null);
  assert.equal(archive.replay.attitude.frame_verified, false);
});

test("idle model and sensor share a finite right-handed nadir frame beyond the scenario", () => {
  for (const model of models.values()) for (const time of [-86400, 8, 43200, 3*86400]) {
    const frame = A.nadir(time, model), position = model.cartesian(time);
    assert.ok(dot(frame.direction, position.map(v => -v/Math.hypot(...position))) > 1 - 1e-12);
    assert.ok(Math.abs(dot(frame.x, frame.direction)) < 1e-12);
    assert.ok(F.frame(position, frame.direction, frame.x));
  }
});

const displayModel = {fixedVector: vector => [...vector], cartesian: time => [10*time,0,7000000]};
const displayAssignment = (start, rolls) => ({task_id:`task-${start}`,start_s:start,
  end_s:start+rolls.length,sat_angles:{yaw_angles:rolls.map(()=>0),pitch_angles:rolls.map(()=>0),roll_angles:rolls}});
const offNadir = (pose, time, model = displayModel) =>
  Math.acos(Math.max(-1,Math.min(1,dot(pose.direction,A.nadir(time,model).direction))))*180/Math.PI;

test("a skyward 160-degree boresight is reversed to 20 degrees with a right-handed model frame", () => {
  const a = displayAssignment(0,[20,20]), original = JSON.stringify(a);
  const raw = A.frame(a,0,displayModel), display = A.displayFrame(a,0,displayModel);
  assert.ok(Math.abs(offNadir(raw,0)-160)<1e-10);
  assert.ok(Math.abs(offNadir(display,0)-20)<1e-10);
  assert.equal(display.reversed,true);
  assert.ok(distance(raw.direction,display.sourceDirection)<1e-12);
  assert.ok(distance(display.direction,raw.direction.map(v=>-v))<1e-12);
  assert.ok(distance(display.x,raw.x)<1e-12);
  assert.ok(distance(display.y,raw.y.map(v=>-v))<1e-12);
  const cross = (a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  assert.ok(dot(cross(display.x,display.y),display.modelAxes.slice(6))>1-1e-12);
  assert.equal(JSON.stringify(a),original);
});

test("all seven plans keep original samples while every displayed boresight stays below 30 degrees", () => {
  let reversed = 0, unchanged = 0, limited = 0;
  for(const plan of archive.plans) for(const a of plan.assignments) {
    const model=models.get(a.satellite_id);
    for(let i=0;i<a.sat_angles.yaw_angles.length;i++) {
      const time=a.start_s+i, raw=A.frame(a,time,model), displayed=A.displayFrame(a,time,model);
      assert.ok(offNadir(displayed,time,model)<=A.MAX_OFF_NADIR_DEG+1e-9);
      if(displayed.limited) {
        limited++;
        assert.ok(Math.abs(offNadir(displayed,time,model)-29.5)<1e-9);
      } else assert.ok(distance(displayed.direction,raw.direction.map(v=>displayed.reversed?-v:v))<1e-12);
      assert.ok(distance(displayed.sourceDirection,raw.direction)<1e-12);
      assert.ok(Math.abs(dot(displayed.x,displayed.direction))<1e-12);
      assert.ok(distance(displayed.modelAxes.slice(6).map(v=>-v),displayed.direction)<1e-12);
      displayed.reversed ? reversed++ : unchanged++;
    }
  }
  assert.ok(reversed>10000 && unchanged>10000 && limited>10000);
  assert.ok(A.MAX_OFF_NADIR_DEG<30);
  assert.equal(JSON.stringify(archive),original);
});

test("horizon crossings interpolate corrected samples instead of snapping the axis by 180 degrees", () => {
  const a=displayAssignment(0,[89,91]);
  let previous=A.displayFrame(a,0,displayModel);
  assert.equal(previous.reversed,true);
  for(let i=1;i<=100;i++) {
    const time=i/100, current=A.displayFrame(a,time,displayModel);
    assert.ok(offNadir(current,time)<=A.MAX_OFF_NADIR_DEG+1e-9);
    assert.ok(distance(previous.direction,current.direction)<.06);
    for(const axis of [current.x,current.y,current.modelAxes.slice(6)]) assert.ok(Math.abs(Math.hypot(...axis)-1)<1e-12);
    previous=current;
  }
  assert.equal(previous.reversed,false);
});

test("angle-timed entry and recovery are continuous at task boundaries and deterministic on reverse seeks", () => {
  const a=displayAssignment(0,[20,20]),schedule=[a];
  assert.equal(A.replay(schedule,-60,displayModel).phase,'idle');
  assert.equal(A.replay(schedule,-20,displayModel).phase,'preparing');
  assert.equal(A.replay(schedule,0,displayModel).phase,'observing');
  assert.equal(A.replay(schedule,2,displayModel).phase,'recovery');
  assert.equal(A.replay(schedule,50,displayModel).phase,'idle');
  for(const time of [0,2]) {
    const left=A.replay(schedule,time-1e-6,displayModel),right=A.replay(schedule,time+1e-6,displayModel);
    assert.ok(distance(left.modelAxes,right.modelAxes)<1e-6);
  }
  const times=[-60,-40,-20,-.000001,0,.5,1.999999,2,20,42,60];
  const forward=times.map(t=>JSON.stringify(A.replay(schedule,t,displayModel)));
  times.slice().reverse().forEach(t=>A.replay(schedule,t,displayModel));
  assert.deepEqual(times.map(t=>JSON.stringify(A.replay(schedule,t,displayModel))),forward);
  assert.ok(A.slewDuration(A.nadir(0,displayModel),A.displayFrame(displayAssignment(0,[70]),0,displayModel))>
    A.slewDuration(A.nadir(0,displayModel),A.displayFrame(a,0,displayModel)));
});

test("short idle gaps retarget continuously without inventing observations or altering plans", () => {
  const previous=displayAssignment(0,[20,20]),next=displayAssignment(14,[70,70]);
  const schedule=[previous,next],before=JSON.stringify(schedule);
  for(let time=2;time<14;time+=.1) {
    const pose=A.replay(schedule,time,displayModel);
    assert.equal(pose.phase,'retarget');
    assert.equal(pose.transition.duration_s,12);
    assert.ok(offNadir(pose,time)<=A.MAX_OFF_NADIR_DEG+1e-9);
  }
  for(const time of [2,14]) assert.ok(distance(
    A.replay(schedule,time-1e-6,displayModel).modelAxes,
    A.replay(schedule,time+1e-6,displayModel).modelAxes)<1e-6);
  assert.equal(JSON.stringify(schedule),before);
  assert.equal(A.sample(previous,5),null);
  assert.equal(A.sample(next,5),null);
});

test("every published schedule is continuous at all entry and exit boundaries, including short gaps", () => {
  let boundaries=0,shortGaps=0;
  for(const plan of archive.plans) for(const [id,model] of models) {
    const schedule=plan.assignments.filter(a=>a.satellite_id===id).sort((a,b)=>a.start_s-b.start_s);
    for(const a of schedule) for(const time of [a.start_s,a.end_s]) {
      const before=A.replay(schedule,time-1e-6,model),after=A.replay(schedule,time+1e-6,model);
      assert.ok(distance(before.modelAxes,after.modelAxes)<1e-4,`${plan.plan_id} ${a.task_id} at ${time}`);
      assert.ok(offNadir(before,time-1e-6,model)<=A.MAX_OFF_NADIR_DEG+1e-7);
      assert.ok(offNadir(after,time+1e-6,model)<=A.MAX_OFF_NADIR_DEG+1e-7);
      boundaries++;
    }
    for(let i=1;i<schedule.length;i++) {
      const t=(schedule[i-1].end_s+schedule[i].start_s)/2,pose=A.replay(schedule,t,model);
      assert.ok(offNadir(pose,t,model)<=A.MAX_OFF_NADIR_DEG+1e-7);
      if(pose.phase==='retarget') shortGaps++;
    }
  }
  assert.ok(boundaries>6000 && shortGaps>0);
  assert.equal(JSON.stringify(archive),original);
});
