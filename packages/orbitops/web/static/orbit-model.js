"use strict";

// Display-only elliptic two-body extension. Source samples are never rewritten.
// Source: EOS-Bench draw/orekit_to_czml.py (EME2000 Keplerian elements, WGS84).
// We calibrate the inertial-to-Earth-fixed orientation at each source boundary
// instead of pretending a simplified sidereal rotation reproduces Orekit/IERS.
(() => {
  const TAU = 2 * Math.PI;
  const RAD = Math.PI / 180;
  const MU = 3.986004418e14;
  const EARTH_RATE = 7.292115e-5;
  const A = 6378137;
  const F = 1 / 298.257223563;
  const E2 = F * (2 - F);
  const norm = (v) => Math.hypot(...v);
  const dot = (a, b) => a.reduce((sum, value, i) => sum + value * b[i], 0);
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const unit = (v) => { const length = norm(v); return v.map((value) => value / length); };
  const spin = (v, angle) => [Math.cos(angle) * v[0] - Math.sin(angle) * v[1], Math.sin(angle) * v[0] + Math.cos(angle) * v[1], v[2]];

  function epochUTC(value) {
    const match = /^(\d{1,2}) ([A-Za-z]{3}) (\d{4}) (\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)$/.exec(value);
    if (!match) {
      const iso = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(value) ? value + "Z" : value;
      return Date.parse(iso);
    }
    const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].indexOf(match[2]);
    if (month < 0) return NaN;
    return Date.parse(`${match[3]}-${String(month + 1).padStart(2, "0")}-${match[1].padStart(2, "0")}T${match[4]}:${match[5]}:${match[6]}Z`);
  }

  function toCartesian([lon, lat, altitude]) {
    const phi = lat * RAD, lambda = lon * RAD;
    const n = A / Math.sqrt(1 - E2 * Math.sin(phi) ** 2);
    return [(n + altitude) * Math.cos(phi) * Math.cos(lambda), (n + altitude) * Math.cos(phi) * Math.sin(lambda), (n * (1 - E2) + altitude) * Math.sin(phi)];
  }

  function toGeodetic([x, y, z]) {
    const p = Math.hypot(x, y);
    if (p < 1e-7) return [0, Math.sign(z) * 90, Math.abs(z) - A * (1 - F)];
    let latitude = Math.atan2(z, p * (1 - E2));
    for (let i = 0; i < 8; i++) {
      const n = A / Math.sqrt(1 - E2 * Math.sin(latitude) ** 2);
      latitude = Math.atan2(z + E2 * n * Math.sin(latitude), p);
    }
    const n = A / Math.sqrt(1 - E2 * Math.sin(latitude) ** 2);
    const altitude = p * Math.cos(latitude) + z * Math.sin(latitude) - n * (1 - E2 * Math.sin(latitude) ** 2);
    return [Math.atan2(y, x) / RAD, latitude / RAD, altitude];
  }

  function create(orbit, elements) {
    const a = Number(elements?.semi_major_axis_km) * 1000;
    const e = Number(elements?.eccentricity);
    const angles = ["inclination_deg", "argument_of_perigee_deg", "right_ascension_of_ascending_node_deg", "mean_anomaly_deg"].map((key) => Number(elements?.[key]) * RAD);
    const offset = (epochUTC(orbit.epoch_utc) - epochUTC(elements?.epoch || "")) / 1000;
    if (![a, e, offset, ...angles].every(Number.isFinite) || a <= A || e < 0 || e >= 1 || orbit.samples.length < 2) {
      throw new Error(`Cannot extend ${orbit.satellite_id}: invalid source orbital elements.`);
    }
    const [inclination, argument, node, mean] = angles;
    const period = TAU * Math.sqrt(a ** 3 / MU);
    const p = [Math.cos(node) * Math.cos(argument) - Math.sin(node) * Math.sin(argument) * Math.cos(inclination), Math.sin(node) * Math.cos(argument) + Math.cos(node) * Math.sin(argument) * Math.cos(inclination), Math.sin(argument) * Math.sin(inclination)];
    const q = [-Math.cos(node) * Math.sin(argument) - Math.sin(node) * Math.cos(argument) * Math.cos(inclination), -Math.sin(node) * Math.sin(argument) + Math.cos(node) * Math.cos(argument) * Math.cos(inclination), Math.cos(argument) * Math.sin(inclination)];
    const normal = unit(cross(p, q));
    const sourceStart = orbit.samples[0][0], sourceEnd = orbit.samples.at(-1)[0];

    function inertial(time) {
      const m = ((mean + TAU * ((time + offset) % period) / period + Math.PI) % TAU + TAU) % TAU - Math.PI;
      let eccentric = m;
      for (let iteration = 0; iteration < 20; iteration++) {
        const delta = (eccentric - e * Math.sin(eccentric) - m) / (1 - e * Math.cos(eccentric));
        eccentric -= delta;
        if (Math.abs(delta) < 1e-13) break;
      }
      const x = a * (Math.cos(eccentric) - e), y = a * Math.sqrt(1 - e * e) * Math.sin(eccentric);
      return p.map((value, i) => value * x + q[i] * y);
    }

    function anchor(index, adjacent) {
      const sample = orbit.samples[index], other = orbit.samples[adjacent];
      const fixed = toCartesian(sample.slice(1));
      const delta = other[0] - sample[0];
      const second = spin(toCartesian(other.slice(1)), EARTH_RATE * delta);
      const radial = unit(fixed);
      const n = unit(cross(fixed, second).map((value) => value * Math.sign(delta)));
      const tangent = unit(cross(n, radial));
      const initial = inertial(sample[0]);
      const u = unit(initial), v = unit(cross(normal, u));
      return {time: sample[0], radial, tangent, normal: n, u, v, scale: norm(fixed) / norm(initial)};
    }
    const before = anchor(0, 1), after = anchor(orbit.samples.length - 1, orbit.samples.length - 2);

    function cartesian(time) {
      if (!Number.isFinite(time)) throw new RangeError("Orbit time must be finite.");
      if (sourceStart <= time && time <= sourceEnd) {
        const index = window.OrbitReplay.sampleIndex(orbit.samples, time);
        const start = orbit.samples[index], end = orbit.samples[Math.min(index + 1, orbit.samples.length - 1)];
        const fraction = end[0] === start[0] ? 0 : (time - start[0]) / (end[0] - start[0]);
        const x = toCartesian(start.slice(1)), y = toCartesian(end.slice(1));
        return x.map((value, i) => value + (y[i] - value) * fraction);
      }
      const frame = time < sourceStart ? before : after;
      const position = inertial(time);
      const components = [dot(position, frame.u), dot(position, frame.v), dot(position, normal)];
      const fixedAtAnchor = frame.radial.map((value, i) => frame.scale * (components[0] * value + components[1] * frame.tangent[i] + components[2] * frame.normal[i]));
      return spin(fixedAtAnchor, -EARTH_RATE * ((time - frame.time) % (TAU / EARTH_RATE)));
    }

    function point(time) {
      return sourceStart <= time && time <= sourceEnd ? window.OrbitReplay.point(orbit.samples, time) : toGeodetic(cartesian(time));
    }

    function trackSamples(start, end) {
      // A bounded, one-period display window; never accumulate an unbounded ephemeris.
      const times = [start];
      for (let time = Math.floor(start / 30) * 30 + 30; time < end; time += 30) times.push(time);
      for (const boundary of [sourceStart, sourceEnd]) if (start < boundary && boundary < end && !times.includes(boundary)) times.push(boundary);
      times.push(end);
      return times.sort((x, y) => x - y).map((time) => [time, ...point(time)]);
    }
    return Object.freeze({period, sourceStart, sourceEnd, cartesian, point, trackSamples});
  }
  window.OrbitModel = Object.freeze({create, epochUTC, toCartesian, toGeodetic});
})();
