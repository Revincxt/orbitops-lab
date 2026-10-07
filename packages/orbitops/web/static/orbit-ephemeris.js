"use strict";

// Verified, bounded hourly source ephemeris. No data is inserted into the archive.
(() => {
  function create(manifest, epoch, satelliteIds, fetcher = window.fetch.bind(window), onLoad = () => {}) {
    const entries = manifest?.chunks || [];
    const ids = new Set(satelliteIds);
    const cache = new Map(), pending = new Map(), failures = new Map();
    let desired = new Set(), disposed = false, revision = 0;
    for (const [i, entry] of entries.entries()) {
      if (!/^\d{5}\.json$/.test(entry.filename) || !/^[a-f0-9]{64}$/.test(entry.sha256)
          || !Number.isInteger(entry.bytes) || entry.bytes <= 0 || entry.bytes > 10000000
          || entry.start_s !== i * 3600 || entry.end_s !== entry.start_s + 3600) {
        throw new Error("Invalid source ephemeris manifest.");
      }
    }

    function trim() {
      for (const key of cache.keys()) {
        if (cache.size <= 4) break;
        if (!desired.has(key)) cache.delete(key);
      }
    }

    async function read(entry, signal) {
      const response = await fetcher(`./orbit-data/${entry.filename}`, {signal});
      if (!response.ok) throw new Error(`Orbit data unavailable (${response.status}).`);
      const raw = await response.arrayBuffer();
      if (raw.byteLength !== entry.bytes) throw new Error("Orbit data size mismatch.");
      const digest = await window.crypto.subtle.digest("SHA-256", raw);
      const hash = Array.from(new Uint8Array(digest), v => v.toString(16).padStart(2, "0")).join("");
      if (hash !== entry.sha256) throw new Error("Orbit data integrity check failed.");
      const data = JSON.parse(new TextDecoder().decode(raw));
      if (data.schema_version !== "eos-orbit-chunk-1" || data.epoch_utc !== epoch
          || data.frame !== "WGS84 geodetic" || data.step_s !== 1
          || data.start_s !== entry.start_s || data.end_s !== entry.end_s
          || data.orbits?.length !== ids.size) throw new Error("Invalid orbit chunk metadata.");
      const orbits = new Map();
      for (const orbit of data.orbits) {
        const values = orbit.cartographic_degrees;
        if (!ids.has(orbit.satellite_id) || orbits.has(orbit.satellite_id)
            || values?.length !== (entry.end_s - entry.start_s + 1) * 3
            || !values.every((v, i) => Number.isFinite(v) && (i % 3 === 0 ? Math.abs(v) <= 180 : i % 3 === 1 ? Math.abs(v) <= 90 : v > 0))) {
          throw new Error("Invalid orbit chunk samples.");
        }
        orbits.set(orbit.satellite_id, values);
      }
      return {entry, orbits};
    }

    function load(entry) {
      const key = entry.filename;
      if (cache.has(key)) return Promise.resolve();
      if (pending.has(key) && !pending.get(key).controller.signal.aborted) return pending.get(key).promise;
      const failed = failures.get(key);
      if (failed && Date.now() < failed.retryAt) return Promise.reject(failed.error);
      const controller = new AbortController();
      let timedOut = false;
      const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
      const promise = read(entry, controller.signal).then(data => {
        if (disposed || controller.signal.aborted || !desired.has(key)) return;
        cache.set(key, data);
        failures.delete(key);
        revision++;
        trim();
        onLoad();
      }).catch(error => {
        if (disposed || !desired.has(key) || (controller.signal.aborted && !timedOut)) return;
        const failure = timedOut ? new Error("Orbit data request timed out.") : error;
        failures.set(key, {error: failure, retryAt: Date.now() + 10000});
        throw failure;
      }).finally(() => {
        clearTimeout(timeout);
        if (pending.get(key)?.controller === controller) pending.delete(key);
      });
      pending.set(key, {controller, promise});
      return promise;
    }

    function ensure(time, radius = 0) {
      if (!Number.isFinite(time) || !Number.isFinite(radius) || radius < 0) return Promise.reject(new RangeError("Invalid ephemeris time."));
      if (disposed) return Promise.resolve();
      const wanted = entries.filter(e => e.end_s >= time - radius && e.start_s <= time + radius);
      if (wanted.length > 4) return Promise.reject(new RangeError("Ephemeris window exceeds bounded cache."));
      desired = new Set(wanted.map(e => e.filename));
      for (const [key, request] of pending) if (!desired.has(key)) request.controller.abort();
      trim();
      return Promise.all(wanted.map(load)).then(() => undefined);
    }

    function samples(id, time) {
      for (const {entry, orbits} of cache.values()) {
        if (time < entry.start_s || time > entry.end_s) continue;
        const values = orbits.get(id);
        if (!values) return null;
        const index = Math.floor(time - entry.start_s);
        const next = Math.min(index + 1, entry.end_s - entry.start_s);
        return [[entry.start_s + index, ...values.slice(index * 3, index * 3 + 3)],
          [entry.start_s + next, ...values.slice(next * 3, next * 3 + 3)]];
      }
      return null;
    }
    function dispose() { disposed = true; for (const p of pending.values()) p.controller.abort(); cache.clear(); }
    return Object.freeze({ensure, samples, dispose, get revision() { return revision; },
      get cacheSize() { return cache.size; }, get pendingCount() { return pending.size; }});
  }
  window.OrbitEphemeris = Object.freeze({create});
})();
