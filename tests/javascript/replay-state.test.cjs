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
