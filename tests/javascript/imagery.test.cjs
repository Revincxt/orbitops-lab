const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

function event() {
  const listeners = new Set();
  return {listeners, addEventListener(listener) {listeners.add(listener); return () => listeners.delete(listener);},
    raise(...args) {for (const listener of [...listeners]) listener(...args);}};
}

function harness(local = true) {
  const timers = new Map(), resources = [], sources = [];
  const online = event(), visibility = event(), progress = event();
  let timerId = 0, probeResult = () => Promise.resolve({type: "image/jpeg", size: 100});
  let imageResult = () => Promise.resolve({image: true});
  class Resource {
    constructor(options) {Object.assign(this, options); resources.push(this); this.request = {cancel() {}};}
    fetchBlob() {return probeResult();}
  }
  class Provider {
    constructor(options) {Object.assign(this, options); this.errorEvent = event();}
    requestImage(...args) {return imageResult(...args);}
  }
  const layers = {items: [{base: true}],
    add(layer, index = this.items.length) {this.items.splice(index, 0, layer); return layer;},
    remove(layer) {const i = this.items.indexOf(layer); if (i >= 0) this.items.splice(i, 1);},
    indexOf(layer) {return this.items.indexOf(layer);}};
  const viewer = {imageryLayers: layers, isDestroyed: () => false,
    scene: {globe: {tilesLoaded: true, tileLoadProgressEvent: progress}, requestRender() {}}};
  const document = {hidden: false, addEventListener: (_, fn) => visibility.listeners.add(fn),
    removeEventListener: (_, fn) => visibility.listeners.delete(fn)};
  const window = {addEventListener: (_, fn) => online.listeners.add(fn),
    removeEventListener: (_, fn) => online.listeners.delete(fn)};
  const context = vm.createContext({window, document,
    setTimeout(fn, ms) {const id = ++timerId; timers.set(id, {fn, ms}); return id;},
    clearTimeout(id) {timers.delete(id);}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../../packages/orbitops/web/static/imagery.js"), "utf8"), context);
  const controller = window.MissionImagery.create({Resource, UrlTemplateImageryProvider: Provider,
    WebMercatorTilingScheme: class {}, Credit: class {}}, viewer,
    {local, makeLayer: provider => ({imageryProvider: provider, show: true, alpha: 1}), onSource: source => sources.push(source)});
  const flush = async () => {for (let i = 0; i < 6; i++) await Promise.resolve();};
  return {controller, layers, viewer, document, resources, timers, sources, online, visibility, progress,
    primary: layers.items[1], flush,
    setImageResult(fn) {imageResult = fn;}, setProbeResult(fn) {probeResult = fn;},
    fail(layer = layers.items[1], count = 1) {for (let i = 0; i < count; i++) layer.imageryProvider.errorEvent.raise({});},
    async run(ms) {const found = [...timers].find(([, timer]) => timer.ms === ms);
      assert.ok(found, `Expected ${ms}ms timer; found ${[...timers.values()].map(t => t.ms)}`);
      timers.delete(found[0]); found[1].fn(); await flush();}};
}

test("local uses the fixed same-origin gateway; static builds retain NASA access", () => {
  for (const local of [true, false]) {
    const h = harness(local);
    assert.equal(h.primary.imageryProvider.maximumLevel, 8);
    assert.equal(h.resources[0].retryAttempts, 2);
    assert.equal(h.resources[0].url.startsWith("./imagery/nasa/"), local);
    assert.equal(h.resources[0].url.startsWith("https://gibs.earthdata.nasa.gov/"), !local);
    h.controller.dispose();
  }
});

test("one failed tile keeps the primary layer visible and does not start a recovery loop", () => {
  const h = harness();
  h.fail();
  assert.equal(h.primary.show, true);
  assert.equal(h.layers.items.length, 2);
  assert.equal(h.timers.size, 0);
  h.controller.dispose();
});

test("partial failure keeps successful imagery and respects request throttling", async () => {
  const h = harness();
  await h.primary.imageryProvider.requestImage(1, 1, 1);
  h.fail();
  assert.equal(h.sources.at(-1), "nasa-blue-marble-partial");
  h.setImageResult(() => undefined);
  assert.equal(h.primary.imageryProvider.requestImage(1, 1, 1), undefined);
  assert.equal(h.primary.show, true);
  h.controller.dispose();
});

test("tile retries back off and permanent HTTP errors are not retried", async () => {
  const h = harness(), resource = h.resources[0];
  assert.equal(resource.retryCallback(resource, {statusCode: 404}), false);
  const first = resource.retryCallback(resource, {statusCode: 503});
  await h.run(750);
  assert.equal(await first, true);
  const second = resource.retryCallback(resource, {});
  await h.run(2250);
  assert.equal(await second, true);
  assert.equal(h.timers.size, 0);
  h.controller.dispose();
});

test("a single recovery probe is scheduled and repeated failures back off to one minute", async () => {
  const h = harness();
  h.setProbeResult(() => Promise.reject(new Error("offline")));
  h.fail(h.primary, 10);
  assert.equal(h.timers.size, 1);
  await h.run(15000);
  assert.equal(h.timers.size, 1);
  await h.run(30000);
  await h.run(60000);
  assert.deepEqual([...h.timers.values()].map(t => t.ms), [60000]);
  h.controller.dispose();
});

test("recovery warms a replacement before removing old images, without changing the viewer", async () => {
  const h = harness();
  const scene = h.viewer.scene;
  h.fail(h.primary, 3);
  await h.run(15000);
  assert.equal(h.layers.items.length, 3);
  assert.equal(h.primary.alpha, 1);
  const replacement = h.layers.items[2];
  assert.equal(replacement.alpha, .001);
  await replacement.imageryProvider.requestImage(1, 1, 1);
  h.progress.raise(0);
  assert.equal(h.layers.items.length, 2);
  assert.equal(h.layers.items[1], replacement);
  assert.equal(replacement.alpha, 1);
  assert.equal(h.viewer.scene, scene);
  assert.equal(h.sources.at(-1), "nasa-blue-marble");
  assert.equal(h.timers.size, 0);
  assert.equal(h.progress.listeners.size, 0);
  h.controller.dispose();
});

test("failed replacement is discarded while the previous image layer is retained", async () => {
  const h = harness();
  h.fail(h.primary, 3);
  await h.run(15000);
  h.fail(h.layers.items[2]);
  assert.equal(h.layers.items.length, 2);
  assert.equal(h.layers.items[1], h.primary);
  assert.equal(h.primary.show, true);
  assert.equal(h.progress.listeners.size, 0);
  h.controller.dispose();
});

test("background tabs stop recovery polling and visibility/online trigger a bounded retry", async () => {
  const h = harness();
  h.fail(h.primary, 3);
  h.document.hidden = true;
  h.visibility.raise();
  assert.equal(h.timers.size, 0);
  h.document.hidden = false;
  h.visibility.raise();
  h.online.raise();
  assert.equal(h.timers.size, 1);
  assert.equal([...h.timers.values()][0].ms, 1000);
  h.controller.dispose();
});

test("dispose cancels timers and pending retries and unregisters every listener", async () => {
  const h = harness();
  const pending = h.resources[0].retryCallback(h.resources[0], {});
  h.fail(h.primary, 3);
  h.controller.dispose();
  h.controller.dispose();
  assert.equal(await pending, false);
  assert.equal(h.timers.size, 0);
  assert.equal(h.online.listeners.size, 0);
  assert.equal(h.visibility.listeners.size, 0);
  assert.equal(h.layers.items.length, 1);
});

test("stalled probes time out and resume the bounded recovery backoff", async () => {
  const h = harness();
  h.setProbeResult(() => new Promise(() => {}));
  h.fail(h.primary, 3);
  await h.run(15000);
  await h.run(8000);
  assert.equal(h.layers.items[1], h.primary);
  assert.equal(h.timers.size, 1);
  assert.equal([...h.timers.values()][0].ms, 30000);
  h.controller.dispose();
});

test("a stalled replacement preserves existing tiles and backs off instead of rebuilding in a loop", async () => {
  const h = harness();
  h.fail(h.primary, 3);
  await h.run(15000);
  await h.run(12000);
  assert.equal(h.layers.items.length, 2);
  assert.equal(h.layers.items[1], h.primary);
  assert.equal(h.progress.listeners.size, 0);
  assert.equal([...h.timers.values()][0].ms, 30000);
  h.controller.dispose();
});
