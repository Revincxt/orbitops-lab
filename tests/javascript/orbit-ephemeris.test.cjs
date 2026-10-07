const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const {webcrypto} = require("node:crypto");
const root = path.resolve(__dirname, "../..");
const archive = JSON.parse(fs.readFileSync(path.join(root, "data/eos-bench/reference.json")));
const original = JSON.stringify(archive);
const context = vm.createContext({window:{crypto:webcrypto, fetch:()=>{}}, TextDecoder, Uint8Array, AbortController, setTimeout, clearTimeout});
for (const name of ["replay.js", "orbit-model.js", "orbit-ephemeris.js"]) vm.runInContext(fs.readFileSync(path.join(root, "packages/orbitops/web/static", name), "utf8"),context);
const {OrbitEphemeris,OrbitModel} = context.window;
const ids = archive.scenario.satellites.map(s=>s.satellite_id);
const bytes = filename=>fs.readFileSync(path.join(root, "data/eos-bench/orbits",filename));
const response = raw=>({ok:true,arrayBuffer:async()=>raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength)});
const create = fetcher=>OrbitEphemeris.create(archive.replay.ephemeris,archive.scenario.epoch_utc,ids,fetcher);

test("complete hourly source data is verified and loaded with a four-chunk memory bound",async()=>{
  let calls=0;
  const loader=create(async url=>{calls++;return response(bytes(url.split('/').at(-1)));});
  for(let time=0;time<=43200;time+=3600){
    await loader.ensure(time,3000);
    assert.ok(loader.cacheSize<=4);
    assert.equal(loader.pendingCount,0);
    for(const id of ids) assert.ok(loader.samples(id,time));
  }
  assert.equal(calls,12);
  const previous=calls;
  await loader.ensure(-86400,3000);await loader.ensure(86400,3000);
  assert.equal(calls,previous);
  assert.equal(loader.samples(ids[0],-1),null);
  loader.dispose();assert.equal(loader.cacheSize,0);
  assert.equal(JSON.stringify(archive),original);
});

test("1-second Cartesian interpolation survives hour boundaries and preserves exact source samples",async()=>{
  const loader=create(async url=>response(bytes(url.split('/').at(-1))));
  await loader.ensure(3600,3000);
  for(const orbit of archive.replay.orbits){
    const elements=archive.scenario.satellites.find(s=>s.satellite_id===orbit.satellite_id).orbital_params;
    const model=OrbitModel.create(orbit,elements,(id,t)=>loader.samples(id,t));
    for(const time of [0,1,3599,3599.5,3600,3600.5,3601,43200]){
      await loader.ensure(time);
      const pair=loader.samples(orbit.satellite_id,time);
      const x=OrbitModel.toCartesian(pair[0].slice(1)),y=OrbitModel.toCartesian(pair[1].slice(1));
      const f=pair[0][0]===pair[1][0]?0:(time-pair[0][0])/(pair[1][0]-pair[0][0]);
      const expected=x.map((v,i)=>v+(y[i]-v)*f);
      assert.ok(Math.hypot(...model.cartesian(time).map((v,i)=>v-expected[i]))<1e-8);
      assert.ok(model.point(time).every(Number.isFinite));
    }
  }
  loader.dispose();
});

test("parallel callers deduplicate requests and corrupted data is never cached",async()=>{
  let calls=0;
  const loader=create(async url=>{calls++;return response(bytes(url.split('/').at(-1)));});
  await Promise.all([loader.ensure(0),loader.ensure(0),loader.ensure(0)]);
  assert.equal(calls,1);
  loader.dispose();
  const broken=create(async url=>{const raw=bytes(url.split('/').at(-1));raw[10]^=1;return response(raw);});
  await assert.rejects(broken.ensure(0),/integrity/);
  assert.equal(broken.cacheSize,0);
  assert.equal(broken.samples(ids[0],0),null);
  await assert.rejects(broken.ensure(0),/integrity/);
  broken.dispose();
});

test("rapid seeks abort obsolete transfers and never install stale chunks",async()=>{
  const loader=create((url,{signal})=>new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>resolve(response(bytes(url.split('/').at(-1)))),15);
    signal.addEventListener('abort',()=>{clearTimeout(timer);reject(new Error('cancelled'));},{once:true});
  }));
  const obsolete=loader.ensure(0).catch(()=>{});
  await loader.ensure(40000);
  await obsolete;
  assert.equal(loader.samples(ids[0],0),null);
  assert.ok(loader.samples(ids[0],40000));
  assert.equal(loader.pendingCount,0);
  loader.dispose();
});

test("manifest paths, finite time and oversized windows are rejected",async()=>{
  const manifest=JSON.parse(JSON.stringify(archive.replay.ephemeris));manifest.chunks[0].filename='../secret.json';
  assert.throws(()=>OrbitEphemeris.create(manifest,archive.scenario.epoch_utc,ids),/manifest/);
  const loader=create(async()=>{throw new Error('unexpected network');});
  await assert.rejects(loader.ensure(NaN),/time/);
  await assert.rejects(loader.ensure(20000,20000),/bounded/);
  loader.dispose();
});

test("timeouts are explicit failures, not silently ignored seek cancellation",async()=>{
  const isolated=vm.createContext({window:{crypto:webcrypto,fetch:()=>{}},TextDecoder,Uint8Array,AbortController,
    setTimeout:(fn,ms)=>setTimeout(fn,ms===15000?1:ms),clearTimeout});
  vm.runInContext(fs.readFileSync(path.join(root,"packages/orbitops/web/static/orbit-ephemeris.js"),"utf8"),isolated);
  const loader=isolated.window.OrbitEphemeris.create(archive.replay.ephemeris,archive.scenario.epoch_utc,ids,
    (url,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('aborted')))));
  await assert.rejects(loader.ensure(0),/timed out/);
  assert.equal(loader.cacheSize,0);
  assert.equal(loader.pendingCount,0);
  loader.dispose();
});

test("a chunk arrival notifies a paused renderer before the full prefetch window completes",async()=>{
  let changes=0;
  const loader=OrbitEphemeris.create(archive.replay.ephemeris,archive.scenario.epoch_utc,ids,
    async url=>response(bytes(url.split('/').at(-1))),()=>changes++);
  await loader.ensure(3600,3000);
  assert.equal(changes,2);
  await loader.ensure(3600,3000);
  assert.equal(changes,2);
  loader.dispose();
});
