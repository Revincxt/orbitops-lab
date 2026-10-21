"use strict";

// Reconstruct the original Number values before the existing orbit validator,
// interpolation, attitude, and rendering paths see a sample.
(() => {
  const ENCODING = "f64le-column-byteplanes-base64";

  function decode(data, entry, ids) {
    if (!entry.encoding && data?.schema_version === "eos-orbit-chunk-1") return data;
    if (entry.encoding !== ENCODING || data?.schema_version !== "eos-orbit-f64-1"
        || data.encoding !== ENCODING || !/^[a-f0-9]{64}$/.test(entry.source_sha256)
        || data.source_sha256 !== entry.source_sha256
        || data.step_s !== 1 || data.start_s !== entry.start_s || data.end_s !== entry.end_s
        || !Array.isArray(data.satellite_ids) || data.satellite_ids.length !== ids.size
        || ids.size < 1 || ids.size > 64
        || new Set(data.satellite_ids).size !== ids.size
        || data.satellite_ids.some(id => !ids.has(id))) {
      throw new Error("Invalid packed orbit metadata.");
    }
    const samples = entry.end_s - entry.start_s + 1;
    if (!Number.isSafeInteger(samples) || samples !== 3601) throw new Error("Invalid packed orbit length.");
    const count = ids.size * samples * 3, byteLength = count * 8;
    const text = data.values_base64;
    if (typeof text !== "string" || text.length !== 4 * Math.ceil(byteLength / 3)) {
      throw new Error("Invalid packed orbit payload length.");
    }
    let binary;
    try { binary = atob(text); }
    catch { throw new Error("Invalid packed orbit base64."); }
    if (binary.length !== byteLength) throw new Error("Invalid packed orbit byte count.");
    const bytes = new Uint8Array(byteLength);
    for (let plane = 0; plane < 8; plane++) {
      const start = plane * count;
      for (let i = 0; i < count; i++) bytes[i * 8 + plane] = binary.charCodeAt(start + i);
    }
    const view = new DataView(bytes.buffer);
    const orbits = data.satellite_ids.map((satellite_id, satellite) => {
      const values = new Array(samples * 3), start = satellite * samples * 3 * 8;
      for (let i = 0; i < samples; i++) {
        for (let axis = 0; axis < 3; axis++) {
          values[i * 3 + axis] = view.getFloat64(start + (axis * samples + i) * 8, true);
        }
      }
      return {satellite_id, cartographic_degrees: values};
    });
    return {schema_version: "eos-orbit-chunk-1", epoch_utc: data.epoch_utc, frame: data.frame,
      start_s: data.start_s, end_s: data.end_s, step_s: data.step_s, orbits};
  }

  window.OrbitCodec = Object.freeze({decode});
})();
