"use strict";

// Verified JSON bytes, with optional best-effort, project-scoped disk reuse.
// No service worker, global prefetch, or change to source sampling/precision.
(() => {
  function cancelled(signal) {
    if (!signal?.aborted) return;
    const error = new Error("Data request cancelled.");
    error.name = "AbortError";
    throw error;
  }

  function wait(promise, signal) {
    if (!signal) return Promise.resolve(promise);
    return new Promise((resolve, reject) => {
      const abort = () => {
        signal.removeEventListener("abort", abort);
        try { cancelled(signal); } catch (error) { reject(error); }
      };
      signal.addEventListener("abort", abort, {once: true});
      Promise.resolve(promise).then(
        value => { signal.removeEventListener("abort", abort); resolve(value); },
        error => { signal.removeEventListener("abort", abort); reject(error); },
      );
      if (signal.aborted) abort();
    });
  }

  function create({fetcher = window.fetch.bind(window), persistent = false,
    maxBytes = 64 * 1024 * 1024, maxEntries = 24} = {}) {
    let cachePromise, writes = Promise.resolve(), queuedWrites = 0;

    function openCache() {
      if (!cachePromise) {
        cachePromise = Promise.resolve().then(() => {
          if (!persistent || !window.caches) return null;
          const scope = new URL("./", window.location.href).pathname;
          return window.caches.open(`orbitops-orbits-v1:${scope}`);
        }).catch(() => null);
      }
      return cachePromise;
    }

    async function verify(raw, asset, signal, decode) {
      cancelled(signal);
      if (raw.byteLength !== asset.bytes) throw new Error("Data size mismatch.");
      const digest = await wait(window.crypto.subtle.digest("SHA-256", raw), signal);
      const hash = Array.from(new Uint8Array(digest), v => v.toString(16).padStart(2, "0")).join("");
      if (hash !== asset.sha256) throw new Error("Data integrity check failed.");
      cancelled(signal);
      return decode(raw);
    }

    async function trim(cache, reserve = 0, replacing = null) {
      const entries = [];
      for (const key of await cache.keys()) {
        if (key.url === replacing) continue;
        const response = await cache.match(key);
        const bytes = Number(response?.headers.get("X-OrbitOps-Bytes"));
        if (!Number.isSafeInteger(bytes) || bytes <= 0 || bytes > maxBytes) {
          await cache.delete(key);
        } else entries.push({key, bytes});
      }
      let total = entries.reduce((sum, item) => sum + item.bytes, reserve);
      while (entries.length && (total > maxBytes || entries.length + (reserve ? 1 : 0) > maxEntries)) {
        const item = entries.shift();
        await cache.delete(item.key);
        total -= item.bytes;
      }
    }

    function remember(cache, key, raw, asset, signal) {
      if (!cache || raw.byteLength > maxBytes || queuedWrites >= 4) return;
      queuedWrites++;
      writes = writes.then(async () => {
        cancelled(signal);
        await trim(cache, asset.bytes, key);
        cancelled(signal);
        const response = () => new Response(raw, {headers: {
          "Content-Type": "application/json", "X-OrbitOps-Bytes": String(asset.bytes),
        }});
        try { await cache.put(key, response()); }
        catch (error) {
          if (error.name !== "QuotaExceededError") return;
          // Only our own data cache is pruned; never clear other project/site storage.
          for (const entry of await cache.keys()) await cache.delete(entry);
          cancelled(signal);
          await cache.put(key, response());
        }
        await trim(cache);
      }).catch(() => {}).finally(() => { queuedWrites--; });
    }

    async function read(url, asset, {signal, decode = raw => raw} = {}) {
      if (!/^[a-f0-9]{64}$/.test(asset?.sha256) || !Number.isSafeInteger(asset.bytes)
          || asset.bytes <= 0 || asset.bytes > 10000000) throw new Error("Invalid data manifest.");
      cancelled(signal);
      let cache = null, key = null, timer;
      if (persistent) {
        // Storage denial, quota pressure, or a stalled cache must not block playback.
        const lookup = openCache().then(async storage => {
          cache = storage;
          if (!cache) return null;
          key = new URL(url, window.location.href).href;
          const response = await cache.match(key);
          if (!response) return null;
          try {
            return {value: await verify(await response.arrayBuffer(), asset, signal, decode)};
          } catch (error) {
            cancelled(signal);
            await cache.delete(key).catch(() => {});
            return null;
          }
        }).catch(() => { cancelled(signal); return null; });
        try {
          const hit = await wait(Promise.race([lookup, new Promise(resolve => {
            timer = setTimeout(() => resolve(null), 500);
          })]), signal);
          if (hit) return hit.value;
        } finally { clearTimeout(timer); }
      }
      const response = await wait(fetcher(url, {signal}), signal);
      if (!response.ok) throw new Error(`Data unavailable (${response.status}).`);
      const raw = await wait(response.arrayBuffer(), signal);
      const value = await verify(raw, asset, signal, decode);
      cancelled(signal);
      if (cache && key) remember(cache, key, raw, asset, signal);
      return value;
    }

    return Object.freeze({read});
  }

  window.MissionData = Object.freeze({create});
})();
