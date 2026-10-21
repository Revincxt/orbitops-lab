"use strict";

// Keep good tiles visible. A failed tile is not a reason to hide an entire layer.
(() => {
  const NASA_URL = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg";

  function create(Cesium, viewer, {local = false, makeLayer, onSource}) {
    const url = local ? "./imagery/nasa/{z}/{y}/{x}.jpeg" : NASA_URL;
    const waits = new Map();
    const entries = new Set();
    let disposed = false, current, candidate = null;
    let recoveryTimer = null, probeTimer = null, warmTimer = null;
    let probeResource = null, removeWarmListener = null, recoveryDelay = 15000;

    function delay(entry, milliseconds) {
      return new Promise(resolve => {
        const timer = setTimeout(() => {
          waits.delete(timer);
          resolve(!disposed && entry.active && !document.hidden);
        }, milliseconds);
        waits.set(timer, resolve);
      });
    }

    function scheduleRecovery(milliseconds = recoveryDelay) {
      if (disposed || document.hidden || recoveryTimer !== null || probeResource || candidate) return;
      recoveryTimer = setTimeout(() => {
        recoveryTimer = null;
        probe();
      }, milliseconds);
    }

    function removeEntry(entry) {
      entry.active = false;
      entry.removeErrorListener();
      entries.delete(entry);
      if (!viewer.isDestroyed()) viewer.imageryLayers.remove(entry.layer, true);
    }

    function stopWarming() {
      clearTimeout(warmTimer);
      warmTimer = null;
      removeWarmListener?.();
      removeWarmListener = null;
    }

    function abandonCandidate() {
      stopWarming();
      if (candidate) removeEntry(candidate);
      candidate = null;
      recoveryDelay = Math.min(60000, recoveryDelay * 2);
      scheduleRecovery();
    }

    function buildEntry() {
      const entry = {active: true, successes: 0, failures: 0};
      const attempts = new WeakMap();
      const resource = new Cesium.Resource({url, retryAttempts: 2,
        retryCallback(resource, error) {
          if (disposed || !entry.active || document.hidden
              || [400, 401, 403, 404].includes(error?.statusCode)) return false;
          const attempt = (attempts.get(resource) || 0) + 1;
          attempts.set(resource, attempt);
          return delay(entry, attempt === 1 ? 750 : 2250);
        },
      });
      const provider = new Cesium.UrlTemplateImageryProvider({url: resource,
        tilingScheme: new Cesium.WebMercatorTilingScheme(), maximumLevel: 8,
        credit: new Cesium.Credit("NASA Earth Observatory · GIBS"),
      });
      const requestImage = provider.requestImage.bind(provider);
      provider.requestImage = (...args) => {
        const pending = requestImage(...args);
        if (!pending) return pending; // Preserve Cesium's request throttling.
        return Promise.resolve(pending).then(image => {
          if (!disposed && entry.active) {
            entry.successes++;
            entry.failures = 0;
            if (entry === current) onSource("nasa-blue-marble");
          }
          return image;
        });
      };
      entry.layer = makeLayer(provider);
      entry.removeErrorListener = provider.errorEvent.addEventListener(() => {
        if (disposed || !entry.active) return;
        entry.failures++;
        if (entry === candidate) {
          abandonCandidate();
        } else if (entry === current) {
          onSource(entry.successes ? "nasa-blue-marble-partial" : "natural-earth-fallback");
          if (entry.failures >= 3) scheduleRecovery();
        }
      });
      entries.add(entry);
      return entry;
    }

    function warmReplacement() {
      if (disposed || viewer.isDestroyed()) return;
      candidate = buildEntry();
      // Retain the old layer while the replacement acquires visible tiles.
      candidate.layer.alpha = .001;
      viewer.imageryLayers.add(candidate.layer, viewer.imageryLayers.indexOf(current.layer) + 1);
      const promote = () => {
        if (disposed || !candidate || !candidate.successes || !viewer.scene.globe.tilesLoaded) return;
        stopWarming();
        const previous = current;
        current = candidate;
        candidate = null;
        current.layer.alpha = 1;
        removeEntry(previous);
        recoveryDelay = 15000;
        onSource("nasa-blue-marble");
        viewer.scene.requestRender();
      };
      removeWarmListener = viewer.scene.globe.tileLoadProgressEvent.addEventListener(promote);
      warmTimer = setTimeout(abandonCandidate, 12000);
      viewer.scene.requestRender();
    }

    function probe() {
      if (disposed || document.hidden || viewer.isDestroyed()) return;
      const resource = new Cesium.Resource({url: url.replace("{z}", "0").replace("{y}", "0").replace("{x}", "0")});
      probeResource = resource;
      let finished = false;
      const finish = success => {
        if (finished) return;
        finished = true;
        clearTimeout(probeTimer);
        probeTimer = null;
        probeResource = null;
        if (disposed || document.hidden) return;
        if (success) warmReplacement();
        else {
          recoveryDelay = Math.min(60000, recoveryDelay * 2);
          scheduleRecovery();
        }
      };
      probeTimer = setTimeout(() => {
        resource.request?.cancel();
        finish(false);
      }, 8000);
      try {
        Promise.resolve(resource.fetchBlob()).then(
          blob => finish(blob?.type === "image/jpeg" && blob.size > 0),
          () => finish(false),
        );
      } catch {
        finish(false);
      }
    }

    function recoverWhenVisible() {
      if (document.hidden) {
        clearTimeout(recoveryTimer);
        recoveryTimer = null;
      } else if (current.failures >= 3) {
        clearTimeout(recoveryTimer);
        recoveryTimer = null;
        scheduleRecovery(1000);
      }
    }

    current = buildEntry();
    viewer.imageryLayers.add(current.layer);
    onSource("nasa-blue-marble");
    window.addEventListener("online", recoverWhenVisible);
    document.addEventListener("visibilitychange", recoverWhenVisible);
    return {
      dispose() {
        if (disposed) return;
        disposed = true;
        clearTimeout(recoveryTimer);
        clearTimeout(probeTimer);
        stopWarming();
        probeResource?.request?.cancel();
        for (const [timer, resolve] of waits) { clearTimeout(timer); resolve(false); }
        waits.clear();
        for (const entry of entries) removeEntry(entry);
        window.removeEventListener("online", recoverWhenVisible);
        document.removeEventListener("visibilitychange", recoverWhenVisible);
      },
    };
  }

  window.MissionImagery = Object.freeze({create});
})();
