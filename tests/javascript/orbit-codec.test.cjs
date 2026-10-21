const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {createHash, webcrypto} = require("node:crypto");
const root = path.resolve(__dirname, "../..");
const archive = JSON.parse(fs.readFileSync(path.join(root,"data/eos-bench/reference.json")));
const ids = new Set(archive.scenario.satellites.map(s=>s.satellite_id));
const context = vm.createContext({window:{crypto:webcrypto,fetch:()=>{}},atob,TextDecoder,Uint8Array,AbortController,setTimeout,clearTimeout});
for (const name of ['replay.js','data-store.js','orbit-codec.js','orbit-ephemeris.js','orbit-model.js']) {
  vm.runInContext(fs.readFileSync(path.join(root,'packages/orbitops/web/static',name),'utf8'),context);
}
const {OrbitCodec,OrbitEphemeris,OrbitModel} = context.window;
const fixtureDir = process.env.ORBITOPS_PACKED_ORBIT_DIR;
const hash = raw => createHash('sha256').update(raw).digest('hex');
const entry = (raw, original) => ({...original,encoding:'f64le-column-byteplanes-base64',
  source_sha256:original.sha256,source_bytes:original.bytes,bytes:raw.length,sha256:hash(raw)});
const buffer = raw => raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength);
const sourceBytes = name => fs.readFileSync(path.join(root,'data/eos-bench/orbits',name.split('?')[0]));

test("Python-built envelopes recover all 2,592,720 original JavaScript Number values exactly", {skip:!fixtureDir}, () => {
  let count = 0;
  for (const original of archive.replay.ephemeris.chunks) {
    const raw = fs.readFileSync(path.join(fixtureDir,original.filename));
    const expected = JSON.parse(sourceBytes(original.filename));
    const actual = OrbitCodec.decode(JSON.parse(raw),entry(raw,original),ids);
    for (const key of ['epoch_utc','frame','start_s','end_s','step_s']) assert.equal(actual[key],expected[key]);
    for (let satellite=0;satellite<expected.orbits.length;satellite++) {
      const a=actual.orbits[satellite], b=expected.orbits[satellite];
      assert.equal(a.satellite_id,b.satellite_id);
      assert.equal(a.cartographic_degrees.length,b.cartographic_degrees.length);
      for (let i=0;i<b.cartographic_degrees.length;i++) {
        if (!Object.is(a.cartographic_degrees[i],b.cartographic_degrees[i])) assert.fail(`Changed source bit at ${original.filename}/${satellite}/${i}`);
        count++;
      }
    }
  }
  assert.equal(count,2592720);
});

test("encoded and original loaders give identical fractional Cartesian positions across boundaries and reverse seeks", {skip:!fixtureDir}, async () => {
  const manifest={...archive.replay.ephemeris,chunks:archive.replay.ephemeris.chunks.map(original=>entry(fs.readFileSync(path.join(fixtureDir,original.filename)),original))};
  let calls=0;
  const packed=OrbitEphemeris.create(manifest,archive.scenario.epoch_utc,[...ids],async url=>{
    calls++;
    const raw=fs.readFileSync(path.join(fixtureDir,url.split('/').at(-1).split('?')[0]));
    return {ok:true,arrayBuffer:async()=>buffer(raw)};
  });
  const plain=OrbitEphemeris.create(archive.replay.ephemeris,archive.scenario.epoch_utc,[...ids],async url=>{
    const raw=sourceBytes(url.split('/').at(-1));
    return {ok:true,arrayBuffer:async()=>buffer(raw)};
  });
  const models=archive.replay.orbits.map(orbit=>{
    const elements=archive.scenario.satellites.find(s=>s.satellite_id===orbit.satellite_id).orbital_params;
    return [OrbitModel.create(orbit,elements,(id,t)=>plain.samples(id,t)),OrbitModel.create(orbit,elements,(id,t)=>packed.samples(id,t))];
  });
  for (const time of [0,0.5,3599.5,3600,3600.5,7200.25,25253,43199.5,43200,3600.5,1,0,-1,86400]) {
    await Promise.all([packed.ensure(time,3064),plain.ensure(time,3064)]);
    assert.ok(packed.cacheSize<=4);
    for (const [a,b] of models) {
      assert.deepEqual(a.cartesian(time),b.cartesian(time));
      assert.deepEqual(a.point(time),b.point(time));
    }
  }
  assert.ok(calls>1);
  packed.dispose();plain.dispose();
});

function singleEnvelope() {
  const samples=3601, values=[];
  for (let i=0;i<samples;i++) values.push(-0,-0,Number.MIN_VALUE);
  const columns=Buffer.alloc(samples*3*8);
  for (let axis=0;axis<3;axis++) for (let i=0;i<samples;i++) columns.writeDoubleLE(values[i*3+axis],(axis*samples+i)*8);
  const shuffled=Buffer.alloc(columns.length), count=values.length;
  for (let plane=0;plane<8;plane++) for (let i=0;i<count;i++) shuffled[plane*count+i]=columns[i*8+plane];
  const descriptor={encoding:'f64le-column-byteplanes-base64',source_sha256:'a'.repeat(64),source_bytes:1,start_s:0,end_s:3600};
  return {descriptor,data:{schema_version:'eos-orbit-f64-1',encoding:descriptor.encoding,source_sha256:descriptor.source_sha256,
    epoch_utc:archive.scenario.epoch_utc,frame:'WGS84 geodetic',step_s:1,start_s:0,end_s:3600,satellite_ids:['one'],values_base64:shuffled.toString('base64')}};
}

test("binary64 decoding preserves signed zero and subnormal bits", () => {
  const {data,descriptor}=singleEnvelope();
  const values=OrbitCodec.decode(data,descriptor,new Set(['one'])).orbits[0].cartographic_degrees;
  for (let i=0;i<values.length;i+=3) {
    assert.ok(Object.is(values[i],-0));assert.ok(Object.is(values[i+1],-0));assert.equal(values[i+2],Number.MIN_VALUE);
  }
});

test("invalid encoding, source hash, satellite identity and payload size fail before installing samples", () => {
  for (const change of [
    data=>{data.encoding='float32';}, data=>{data.source_sha256='b'.repeat(64);},
    data=>{data.satellite_ids=['wrong'];}, data=>{data.satellite_ids=['one','one'];},
    data=>{data.end_s=7200;}, data=>{data.values_base64=data.values_base64.slice(4);},
    data=>{data.values_base64='!'+data.values_base64.slice(1);},
  ]) {
    const {data,descriptor}=singleEnvelope();change(data);
    assert.throws(()=>OrbitCodec.decode(data,descriptor,new Set(['one'])),/Invalid packed orbit/);
  }
  const {data,descriptor}=singleEnvelope();
  assert.throws(()=>OrbitCodec.decode(data,{...descriptor,end_s:7200},new Set(['one'])),/Invalid packed orbit/);
  const raw={schema_version:'eos-orbit-chunk-1'};
  assert.equal(OrbitCodec.decode(raw,{},new Set()),raw);
  assert.throws(()=>OrbitCodec.decode(raw,descriptor,new Set(['one'])),/Invalid packed orbit/);
});

test("even checksum-valid encoded nonfinite coordinates fail the existing source validator", async () => {
  const {data,descriptor}=singleEnvelope();
  const shuffled=Buffer.from(data.values_base64,'base64'), count=3601*3;
  const nonfinite=Buffer.alloc(8);nonfinite.writeDoubleLE(Infinity);
  for (let plane=0;plane<8;plane++) shuffled[plane*count]=nonfinite[plane];
  data.values_base64=shuffled.toString('base64');
  const raw=Buffer.from(JSON.stringify(data));
  const manifest={chunks:[{...descriptor,filename:'00000.json',sha256:hash(raw),bytes:raw.length}]};
  const loader=OrbitEphemeris.create(manifest,archive.scenario.epoch_utc,['one'],async()=>({ok:true,arrayBuffer:async()=>buffer(raw)}));
  await assert.rejects(loader.ensure(0),/Invalid orbit chunk samples/);
  assert.equal(loader.cacheSize,0);loader.dispose();
});
