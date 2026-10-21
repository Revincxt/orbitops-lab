const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.resolve(__dirname, "../..");
const context = vm.createContext({window:{}});
vm.runInContext(fs.readFileSync(path.join(root,"packages/orbitops/web/static/replay.js"),"utf8"),context);
const R = context.window.OrbitReplay;
const archive = JSON.parse(fs.readFileSync(path.join(root,"data/eos-bench/reference.json"),"utf8"));
const original = JSON.stringify(archive);

function expected(scenario, assignments, task, time) {
  const assignment = assignments.get(task.task_id);
  if (time < scenario.horizon_start_s || time >= scenario.horizon_end_s) {
    return assignment ? (time < scenario.horizon_start_s ? "Planned" : "Completed") : "Unassigned";
  }
  return R.taskState(time,assignment,task.visibility_windows);
}

test("event-indexed state matches every task across all source plans and arbitrary reverse seeks",()=>{
  const scenario = archive.scenario;
  for (const plan of archive.plans) {
    const assignments = new Map(plan.assignments.map(a=>[a.task_id,a]));
    const states = R.createTaskStates(scenario,assignments);
    const times = [-86400,0,43200,86400,43199.999,0,1200.25,1200.2501];
    for(let i=0;i<80;i++) times.push(((i*7919)%43200)+(i%3)*.25);
    for(const time of times) {
      states.update(time);
      for(const task of scenario.tasks) {
        assert.equal(states.get(task.task_id),expected(scenario,assignments,task,time),plan.plan_id+" at "+time);
      }
    }
    for(const task of scenario.tasks) {
      const intervals = assignments.has(task.task_id) ? [assignments.get(task.task_id)] : task.visibility_windows;
      for(const interval of intervals) for(const boundary of [interval.start_s,interval.end_s]) {
        for(const time of [boundary-1e-6,boundary,boundary+1e-6,boundary-1e-6]) {
          states.update(time);
          assert.equal(states.get(task.task_id),expected(scenario,assignments,task,time));
        }
      }
    }
  }
  assert.equal(JSON.stringify(archive),original);
});

test("overlapping windows and simultaneous boundaries preserve half-open visibility states",()=>{
  const scenario = {horizon_start_s:0,horizon_end_s:100,tasks:[
    {task_id:"visible",visibility_windows:[{start_s:10,end_s:30},{start_s:20,end_s:40}]},
    {task_id:"planned",visibility_windows:[]},
  ]};
  const assignments = new Map([["planned",{start_s:20,end_s:30}]]);
  const states = R.createTaskStates(scenario,assignments);
  for(const time of [-1,0,9.99,10,20,30,39.99,40,100,30,20,19.99,0]) {
    states.update(time);
    for(const task of scenario.tasks) assert.equal(states.get(task.task_id),expected(scenario,assignments,task,time));
  }
});

test("a stable clock interval performs no additional task-state resolutions",()=>{
  let resolutions = 0;
  const counted = {...R,taskState(...args){resolutions++;return R.taskState(...args);}};
  const scenario = {horizon_start_s:0,horizon_end_s:100,tasks:Array.from({length:500},(_,i)=>(
    {task_id:String(i),visibility_windows:[{start_s:20,end_s:30}]}))};
  const states = counted.createTaskStates(scenario,new Map());
  states.update(0);
  assert.equal(resolutions,500);
  for(let i=0;i<100;i++) states.update(i/10);
  assert.equal(resolutions,500);
  assert.equal(states.update(20).length,500);
  assert.equal(resolutions,1000);
  assert.equal(states.update(30).length,500);
});

test("selection rotation follows the shortest arc through the date line and poles",()=>{
  const vector=(longitude,latitude)=>{
    const lon=longitude*Math.PI/180,lat=latitude*Math.PI/180;
    return [Math.cos(lat)*Math.cos(lon),Math.cos(lat)*Math.sin(lon),Math.sin(lat)];
  };
  const near=(actual,expected,tolerance=1e-10)=>actual.forEach((value,i)=>{
    assert.ok(Math.abs(value-expected[i])<tolerance,`${actual} != ${expected}`);
  });
  for(const [from,to] of [[vector(179,0),vector(-179,0)],
    [vector(0,89),vector(180,89)],[vector(60,-30),vector(-110,45)],
    [[0,0,1],[0,0,-1]],[[1,0,0],[-1,0,0]],[[1,0,0],[1,0,0]]]) {
    const original=JSON.stringify([from,to]);
    const arc=R.shortestArc(from,to,from);
    const angle=Math.acos(Math.max(-1,Math.min(1,from.reduce((s,v,i)=>s+v*to[i],0))));
    assert.ok(arc.angle>=0 && arc.angle<=Math.PI);
    assert.ok(Math.abs(arc.angle-angle)<1e-10);
    near(R.rotateVector(from,arc),to);
    near(R.rotateVector(from,arc,0),from);
    for(const fraction of [.1,.25,.5,.9]) {
      const value=R.rotateVector(from,arc,fraction);
      assert.ok(Math.abs(Math.hypot(...value)-1)<1e-10);
      const travelled=Math.acos(Math.max(-1,Math.min(1,from.reduce((s,v,i)=>s+v*value[i],0))));
      assert.ok(Math.abs(travelled-arc.angle*fraction)<1e-10);
    }
    assert.equal(JSON.stringify([from,to]),original);
  }
  assert.ok(Math.abs(R.shortestArc(vector(179,0),vector(-179,0)).angle-2*Math.PI/180)<1e-12);
  assert.equal(R.shortestArc([0,0,0],[1,0,0]),null);
  assert.equal(R.shortestArc([Infinity,0,0],[1,0,0]),null);
});

test("shortest rotation preserves camera radius, roll basis and finite antipodal poses",()=>{
  const eye=[22000000,0,0],direction=[-1,0,0],up=[0,0,1];
  for(const target of [[0,6378137,0],[-6378137,0,0],[-6378137,1e-8,0],[0,0,6356752]]) {
    const arc=R.shortestArc(eye,target,up);
    for(const fraction of [0,.2,.6,1]) {
      const next=R.rotateVector(eye,arc,fraction),d=R.rotateVector(direction,arc,fraction),u=R.rotateVector(up,arc,fraction);
      assert.ok(next.every(Number.isFinite));
      assert.ok(Math.abs(Math.hypot(...next)-Math.hypot(...eye))<1e-7);
      assert.ok(Math.abs(d.reduce((s,v,i)=>s+v*u[i],0))<1e-10);
      assert.ok(Math.abs(Math.hypot(...d)-1)<1e-10);
      assert.ok(Math.abs(Math.hypot(...u)-1)<1e-10);
    }
  }
});

function playbackHarness(native, direction = 1, phase = "idle") {
  const calls = {clock: [], sensors: [], ui: [], renders: 0, scheduled: 0};
  const state = {
    currentPayload: {scenario: {epoch_utc: "2025-11-18T12:00:00Z"}},
    replay: {time: 0, playing: true, speed: 60, direction, lastFrame: 0, lastPaint: 0},
    globe: native ? {scene: {requestRender() {calls.renders++;}}} : null,
    attitudeFrames: new Map([["satellite", {frame: {phase}}]]),
  };
  const runner = vm.createContext({state, window: {},
    requestAnimationFrame() {calls.scheduled++;}});
  vm.runInContext(fs.readFileSync(path.join(root, "packages/orbitops/web/static/mission.js"), "utf8"), runner);
  Object.assign(runner, {
    updateCesiumClock() {calls.clock.push(state.replay.time);},
    updateSensorFovs() {calls.sensors.push(state.replay.time);},
    updateReplayVisuals() {calls.ui.push(state.replay.time);},
  });
  return {state, calls, animate: runner.animateReplay};
}

function timelineHarness(viewMode = "3d", cameraMode = "follow", viewTransition = false) {
  const state = {viewMode, cameraMode, viewTransition, selectedSatelliteId: "old", replay: {time: 100}};
  const calls = [];
  const runner = vm.createContext({state, window: {},
    document: {getElementById(id) {return id;}}});
  vm.runInContext(fs.readFileSync(path.join(root, "packages/orbitops/web/static/mission.js"), "utf8"), runner);
  Object.assign(runner, {
    selectTarget(id, reveal, seek) {
      calls.push(["task", id, reveal, seek]);
      if (reveal) { state.selectedSatelliteId = null; if (state.cameraMode === "follow") state.cameraMode = "manual"; }
      if (seek) state.replay.time = 200;
    },
    selectSatellite(id, reorient) {
      assert.equal(reorient, undefined, "timeline selection must not start a selection flight");
      state.selectedSatelliteId = id;
      calls.push(["satellite", id]);
    },
    activateTab(id) {calls.push(["tab", id]);},
    revealSelectedTask() {calls.push(["reveal"]);},
  });
  return {state, calls, select: runner.selectTimelineItem};
}

test("timeline tasks retain Follow only in 3D while keeping task seeks and details",()=>{
  for (const view of ["3d", "2d", "2.5d"]) for (const mode of ["overview", "manual", "follow"]) {
    const {state, calls, select} = timelineHarness(view, mode);
    select("new", "task");
    const follow = view === "3d" && mode === "follow";
    assert.deepEqual(calls[0], ["task", "task", !follow, true]);
    assert.equal(state.replay.time, 200);
    assert.equal(state.selectedSatelliteId, follow ? "new" : null);
    assert.equal(state.cameraMode, follow ? "follow" : mode === "follow" ? "manual" : mode);
    assert.equal(calls.filter(call=>call[0]==="satellite").length, follow ? 1 : 0);
    assert.equal(calls.filter(call=>call[0]==="tab").length, follow ? 1 : 0);
  }
});

test("timeline satellite rows select once without seeking or changing camera mode",()=>{
  for (const view of ["3d", "2d", "2.5d"]) for (const mode of ["overview", "follow"]) {
    const {state, calls, select} = timelineHarness(view, mode);
    select("new");
    assert.deepEqual(calls, [["satellite", "new"]]);
    assert.equal(state.replay.time, 100);
    assert.equal(state.cameraMode, mode);
  }
  const {calls, select} = timelineHarness("3d", "follow", true);
  select("new", "task");
  assert.deepEqual(calls, [], "ignore timeline selection while the native view is morphing");
});

test("native camera and all coverage advance each frame regardless of task phase or direction",()=>{
  for (const direction of [1, -1]) for (const phase of ["idle", "observing", "slew-in", "slew-out"]) {
    const {state, calls, animate} = playbackHarness(true, direction, phase);
    for (let frame = 0; frame <= 120; frame++) animate(1000 + frame * 1000 / 60);
    assert.equal(calls.clock.length, 121);
    assert.deepEqual(calls.sensors, calls.clock);
    assert.equal(calls.renders, 121);
    assert.equal(calls.scheduled, 121);
    assert.ok(calls.ui.length >= 18 && calls.ui.length <= 21);
    assert.ok(Math.abs(state.replay.time - direction * 120) < 1e-9);
    for (let i = 1; i < calls.clock.length; i++) {
      assert.ok(Math.abs((calls.clock[i] - calls.clock[i - 1]) * direction - 1) < 1e-9);
    }
  }
});

test("offline replay remains bounded and pause stops both scene and UI work",()=>{
  const {state, calls, animate} = playbackHarness(false);
  for (let frame = 0; frame <= 60; frame++) animate(1000 + frame * 1000 / 60);
  assert.equal(calls.clock.length, 0);
  assert.equal(calls.sensors.length, 0);
  assert.equal(calls.renders, 0);
  assert.ok(calls.ui.length >= 9 && calls.ui.length <= 11);
  const before = JSON.stringify(calls), time = state.replay.time;
  state.replay.playing = false;
  animate(3000);
  assert.equal(state.replay.time, time);
  assert.equal(JSON.stringify(calls), before);
});

test("native playback caps a stalled frame and resumes without an obsolete clock jump",()=>{
  const {state, calls, animate} = playbackHarness(true);
  animate(1000);
  animate(5000);
  assert.equal(state.replay.time, 15);
  assert.equal(calls.clock.at(-1), 15);
  state.replay.lastFrame = 0;
  animate(10000);
  assert.equal(state.replay.time, 15);
  animate(10000 + 1000 / 60);
  assert.ok(Math.abs(state.replay.time - 16) < 1e-9);
});

test("workspace attitude cache resolves a schedule only once and resets with source or plan",()=>{
  let calls = 0, extraReads = 0;
  const schedule = new Proxy([], {get(target, name) {extraReads++; return target[name];}});
  const model = {};
  const state = {replay: {time: 0}, ephemeris: {revision: 0}, attitudeFrames: new Map(),
    orbitModels: new Map([["satellite", model]]), satelliteSchedules: new Map([["satellite", schedule]]),
    currentPayload: {replay: {attitude: {sample_step_s: 1}}}};
  const runner = vm.createContext({state, window: {SatelliteAttitude: {
    replay(items, time, actualModel, step, revision) {
      assert.equal(items, schedule);
      assert.equal(actualModel, model);
      assert.equal(step, 1);
      calls++;
      return {time, revision, calls};
    },
  }}});
  vm.runInContext(fs.readFileSync(path.join(root, "packages/orbitops/web/static/mission.js"), "utf8"), runner);
  const first = runner.satelliteFrame("satellite");
  for (let i = 0; i < 100; i++) assert.equal(runner.satelliteFrame("satellite"), first);
  assert.equal(calls, 1);
  assert.equal(extraReads, 0, "schedule traversal belongs to the attitude resolver, not its cache wrapper");
  runner.satelliteFrame("satellite", 1);
  state.ephemeris.revision++;
  const revised = runner.satelliteFrame("satellite", 1);
  assert.equal(revised.revision, 1);
  assert.equal(calls, 3);
  state.attitudeFrames.clear();
  assert.notEqual(runner.satelliteFrame("satellite", 1), revised);
  assert.equal(calls, 4);
  assert.equal(state.attitudeFrames.size, 1);
});
