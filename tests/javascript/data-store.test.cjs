const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {createHash, webcrypto} = require("node:crypto");
const source = fs.readFileSync(path.join(__dirname, "../../packages/orbitops/web/static/data-store.js"), "utf8");
const scope = "https://example.test/orbitops-lab/";
const cacheName = "orbitops-orbits-v1:/orbitops-lab/";
const bytes = value => Buffer.from(JSON.stringify(value));
const asset = raw => ({bytes: raw.length, sha256: createHash("sha256").update(raw).digest("hex")});
const url = entry => `./orbit-data/00000.json?sha256=${entry.sha256}`;
const pause = () => new Promise(resolve => setTimeout(resolve, 20));

function storage() {
  const caches = new Map();
  return {
    caches,
    async open(name) {
      if (!caches.has(name)) {
        const entries = new Map();
        caches.set(name, {
          entries,
          async match(key) { return entries.get(typeof key === "string" ? key : key.url)?.clone(); },
          async put(key, value) { entries.set(typeof key === "string" ? key : key.url, value.clone()); },
          async delete(key) { return entries.delete(typeof key === "string" ? key : key.url); },
          async keys() { return [...entries.keys()].map(url => ({url})); },
        });
      }
      return caches.get(name);
    },
  };
}

function runtime(caches, options = {}) {
  const window = {crypto: webcrypto, fetch: () => { throw new Error("Unexpected network"); },
    caches, location: {href: options.scope || scope}};
  const context = vm.createContext({window, URL, Response, Uint8Array, setTimeout: options.setTimeout || setTimeout, clearTimeout});
  vm.runInContext(source, context);
  return window.MissionData;
}

test("a verified cold download is reused across loader/page instances without another fetch", async () => {
  const caches = storage(), data = bytes({value: 123.456}), entry = asset(data);
  let calls = 0;
  const fetcher = async () => { calls++; return new Response(data); };
  const first = runtime(caches).create({fetcher, persistent: true});
  assert.equal(await first.read(url(entry), entry, {decode: raw => Buffer.from(raw).toString()}), data.toString());
  await pause();
  assert.equal((await (await caches.open(cacheName)).keys()).length, 1);
  const second = runtime(caches).create({fetcher, persistent: true});
  assert.equal(Buffer.from(await second.read(url(entry), entry)).toString(), data.toString());
  assert.equal(calls, 1);
});

test("a changed content hash downloads a new version while UI-only changes can reuse the old hash", async () => {
  const caches = storage(), one = bytes({revision: 1}), two = bytes({revision: 2});
  let calls = 0;
  const fetcher = async address => { calls++; return new Response(address === url(asset(one)) ? one : two); };
  const store = runtime(caches).create({fetcher, persistent: true});
  await store.read(url(asset(one)), asset(one));
  await pause();
  await store.read(url(asset(two)), asset(two));
  await pause();
  assert.equal(calls, 2);
  await store.read(url(asset(one)), asset(one));
  assert.equal(calls, 2);
  assert.equal((await (await caches.open(cacheName)).keys()).length, 2);
});

test("corrupt cached bytes are discarded, fetched again, checked, and replaced", async () => {
  const caches = storage(), data = bytes({valid: true}), entry = asset(data);
  const cache = await caches.open(cacheName), key = new URL(url(entry), scope).href;
  await cache.put(key, new Response("bad", {headers: {"X-OrbitOps-Bytes": "3"}}));
  let calls = 0;
  const store = runtime(caches).create({persistent: true, fetcher: async () => { calls++; return new Response(data); }});
  assert.equal(Buffer.from(await store.read(url(entry), entry)).toString(), data.toString());
  assert.equal(calls, 1);
  await pause();
  assert.equal(await (await cache.match(key)).text(), data.toString());
});

test("bad checksums and invalid decoded schemas from the network never reach the persistent cache", async () => {
  const caches = storage(), data = bytes({valid: true}), entry = asset(data);
  const broken = runtime(caches).create({persistent: true, fetcher: async () => new Response(Buffer.alloc(data.length))});
  await assert.rejects(broken.read(url(entry), entry), /integrity/);
  const invalid = runtime(caches).create({persistent: true, fetcher: async () => new Response(data)});
  await assert.rejects(invalid.read(url(entry), entry, {decode() { throw new Error("schema"); }}), /schema/);
  await pause();
  assert.equal((await (await caches.open(cacheName)).keys()).length, 0);
});

test("a schema-invalid cache entry is also revalidated against the network", async () => {
  const caches = storage(), data = bytes({valid: true}), entry = asset(data);
  const cache = await caches.open(cacheName), key = new URL(url(entry), scope).href;
  await cache.put(key, new Response(data, {headers: {"X-OrbitOps-Bytes": String(data.length)}}));
  let calls = 0, decodes = 0;
  const store = runtime(caches).create({persistent: true, fetcher: async () => { calls++; return new Response(data); }});
  await store.read(url(entry), entry, {decode() { if (++decodes === 1) throw new Error("schema"); return "ok"; }});
  assert.equal(calls, 1);
  assert.equal(decodes, 2);
});

test("storage denial and failed writes never prevent valid data from loading", async () => {
  const data = bytes({valid: true}), entry = asset(data);
  for (const caches of [undefined, {open() { throw new Error("denied"); }}, {async open() { throw new Error("denied"); }}]) {
    const store = runtime(caches).create({persistent: true, fetcher: async () => new Response(data)});
    assert.equal(Buffer.from(await store.read(url(entry), entry)).toString(), data.toString());
  }
  const caches = storage(), cache = await caches.open(cacheName);
  cache.put = async () => { throw new Error("read-only storage"); };
  const store = runtime(caches).create({persistent: true, fetcher: async () => new Response(data)});
  await store.read(url(entry), entry);
  await pause();
  assert.equal((await cache.keys()).length, 0);
});

test("a stalled storage lookup falls back to a normal download", async () => {
  const data = bytes({valid: true}), entry = asset(data);
  const api = runtime({open: () => new Promise(() => {})}, {setTimeout: (fn, ms) => setTimeout(fn, ms === 500 ? 1 : ms)});
  let calls = 0;
  const store = api.create({persistent: true, fetcher: async () => { calls++; return new Response(data); }});
  await store.read(url(entry), entry);
  assert.equal(calls, 1);
});

test("disk eviction bounds both bytes and entries and does not touch unrelated caches", async () => {
  const caches = storage(), unrelated = await caches.open("another-project-cache");
  await unrelated.put("https://example.test/other", new Response("keep"));
  const api = runtime(caches);
  const store = api.create({persistent: true, maxEntries: 2, maxBytes: 140,
    fetcher: async address => new Response(bytes({value: address.split("?")[0]}))});
  for (let i = 0; i < 5; i++) {
    const address = `./orbit-data/${i}.json`, raw = bytes({value: address});
    await store.read(`${address}?sha256=${asset(raw).sha256}`, asset(raw));
    await pause();
  }
  const cache = await caches.open(cacheName), keys = await cache.keys();
  assert.ok(keys.length <= 2);
  let total = 0;
  for (const key of keys) total += Number((await cache.match(key)).headers.get("X-OrbitOps-Bytes"));
  assert.ok(total <= 140);
  assert.equal(await (await unrelated.match("https://example.test/other")).text(), "keep");
});

test("quota errors evict only our bounded data cache and retry persistence once", async () => {
  const caches = storage(), cache = await caches.open(cacheName), original = cache.put.bind(cache);
  let puts = 0;
  cache.put = async (...args) => {
    if (++puts === 1) { const error = new Error("quota"); error.name = "QuotaExceededError"; throw error; }
    return original(...args);
  };
  const raw = bytes({value: "ok"}), entry = asset(raw);
  const store = runtime(caches).create({persistent: true, fetcher: async () => new Response(raw)});
  await store.read(url(entry), entry);
  await pause();
  assert.equal(puts, 2);
  assert.equal((await cache.keys()).length, 1);
});

test("cache namespaces include the Pages project path", async () => {
  const caches = storage(), raw = bytes({value: "ok"}), entry = asset(raw);
  let calls = 0;
  for (const scope of ["https://example.test/one/", "https://example.test/two/"]) {
    const store = runtime(caches, {scope}).create({persistent: true, fetcher: async () => { calls++; return new Response(raw); }});
    await store.read(url(entry), entry);
    await pause();
  }
  assert.equal(calls, 2);
  assert.ok(caches.caches.has("orbitops-orbits-v1:/one/"));
  assert.ok(caches.caches.has("orbitops-orbits-v1:/two/"));
});

test("abort interrupts a stalled cache lookup without starting a replacement download", async () => {
  const raw = bytes({value: "ok"}), entry = asset(raw), controller = new AbortController();
  let calls = 0;
  const store = runtime({open: () => new Promise(() => {})}).create({persistent: true,
    fetcher: async () => { calls++; return new Response(raw); }});
  const loading = store.read(url(entry), entry, {signal: controller.signal});
  controller.abort();
  await assert.rejects(loading, {name: "AbortError"});
  assert.equal(calls, 0);
});

test("ordinary plan reads do not open or write a persistent orbit cache", async () => {
  const raw = bytes({value: "plan"}), entry = asset(raw);
  let opens = 0;
  const store = runtime({open() { opens++; throw new Error("should not open"); }}).create({fetcher: async () => new Response(raw)});
  await store.read("./plan-data/file.json", entry);
  assert.equal(opens, 0);
  await assert.rejects(store.read("./plan-data/file.json", {...entry, bytes: 10000001}), /manifest/);
});
