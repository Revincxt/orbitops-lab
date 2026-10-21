const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {createHash, webcrypto} = require("node:crypto");
const root = path.resolve(__dirname, "../..");
const archive = JSON.parse(fs.readFileSync(path.join(root, "data/eos-bench/reference.json")));
const rawPlans = new Map(), summaries = archive.plans.map(plan => {
  const raw = Buffer.from(JSON.stringify(plan)), sha256 = createHash("sha256").update(raw).digest("hex");
  const filename = `${plan.plan_id}.${sha256}.json`;
  rawPlans.set(filename, raw);
  return Object.fromEntries([...['plan_id','label','objective','source_metrics','recomputed_metrics'].map(key => [key, plan[key]]),
    ['asset',{filename,sha256,bytes:raw.length}]]);
});
const snapshot = JSON.stringify(summaries);
function create(fetcher, plans = summaries, options = {}) {
  const window = {crypto: webcrypto, fetch: () => { throw new Error("Unexpected network"); }};
  const context = vm.createContext({window, TextDecoder, Uint8Array, AbortController, setTimeout: options.setTimeout || setTimeout, clearTimeout});
  for (const name of ['data-store.js','reference-plans.js']) vm.runInContext(fs.readFileSync(path.join(root,'packages/orbitops/web/static',name),'utf8'), context);
  return window.ReferencePlans.create(plans, fetcher);
}
const response = raw => ({ok:true,arrayBuffer:async()=>raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength)});

test("creation does not prefetch plans; parallel selection deduplicates and repeated selection reuses the plan", async () => {
  const calls = [];
  const loader = create(async url => { calls.push(url); return response(rawPlans.get(url.split('/').at(-1))); });
  assert.equal(calls.length, 0);
  const [a,b] = await Promise.all([loader.load('eos-sa-balanced'),loader.load('eos-sa-balanced')]);
  assert.equal(a, b);
  assert.equal(a, await loader.load('eos-sa-balanced'));
  assert.equal(calls.length, 1);
  assert.equal(a.assignments.length, 488);
  assert.equal(summaries.length, 7);
  assert.ok(summaries.every(plan => plan.recomputed_metrics && plan.source_metrics && !plan.assignments));
  await loader.load('eos-ppo-profit');
  assert.equal(calls.length, 2);
  assert.equal(JSON.stringify(summaries), snapshot);
});

test("failed downloads are retryable rather than permanently memoized", async () => {
  let failed = true, calls = 0;
  const loader = create(async url => {
    calls++;
    return failed ? {ok:false,status:503} : response(rawPlans.get(url.split('/').at(-1)));
  });
  await assert.rejects(loader.load('eos-sa-balanced'), /503/);
  failed = false;
  assert.equal((await loader.load('eos-sa-balanced')).plan_id, 'eos-sa-balanced');
  assert.equal(calls, 2);
});

test("corruption, mismatched plan identity, and altered comparison metrics cannot be installed", async () => {
  const first = summaries[0], raw = rawPlans.get(first.asset.filename);
  const corrupted = create(async () => { const value = Buffer.from(raw); value[0] ^= 1; return response(value); });
  await assert.rejects(corrupted.load(first.plan_id), /integrity/);
  for (const mutation of [plan => {plan.plan_id='wrong';}, plan => {plan.recomputed_metrics.TP++;}, plan => {delete plan.checks;}]) {
    const plan = JSON.parse(raw);
    mutation(plan);
    const changed = Buffer.from(JSON.stringify(plan));
    const sha256 = createHash('sha256').update(changed).digest('hex');
    const summary = {...first,asset:{filename:`${first.plan_id}.${sha256}.json`,bytes:changed.length,sha256}};
    const loader = create(async () => response(changed),[summary]);
    await assert.rejects(loader.load(first.plan_id), /Invalid reference plan data/);
  }
});

test("unlisted ids, path traversal, and external plan URLs do not make requests", async () => {
  const forbidden = async () => { throw new Error('unexpected network'); };
  await assert.rejects(create(forbidden).load('not-a-plan'), /unavailable/);
  for (const filename of ['../source.json','https://example.test/file.json']) {
    const first = summaries[0];
    await assert.rejects(create(forbidden,[{...first,asset:{...first.asset,filename}}]).load(first.plan_id), /manifest/);
  }
  assert.throws(() => create(forbidden,[summaries[0],summaries[0]]), /Duplicate/);
});

test("the local API can keep using its full, validated archive without extra plan requests", async () => {
  const loader = create(async () => { throw new Error('unexpected network'); },archive.plans);
  for (const original of archive.plans) assert.equal(await loader.load(original.plan_id), original);
});

test("a timed-out plan request leaves the selected summary retryable", async () => {
  let calls = 0, timeouts = 0;
  // Only force the failed first attempt; hashing a successful retry can exceed
  // 1 ms when the other source-attitude tests run in parallel on CI.
  const loader = create((url,{signal}) => {
    if (++calls > 1) return Promise.resolve(response(rawPlans.get(url.split('/').at(-1))));
    return new Promise((resolve,reject) => signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true}));
  }, summaries, {setTimeout:(fn,ms)=>setTimeout(fn,ms===15000 && ++timeouts===1 ? 1 : ms)});
  await assert.rejects(loader.load('eos-sa-balanced'), /timed out/);
  assert.equal((await loader.load('eos-sa-balanced')).assignments.length, 488);
  assert.equal(calls, 2);
  assert.equal(timeouts, 2);
});
