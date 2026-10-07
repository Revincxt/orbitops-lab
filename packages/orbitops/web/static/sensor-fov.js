"use strict";

// Illustrative 45-degree circular field of view, aligned with the source sensor
// angle and steered by the same world-frame attitude as the satellite model.
// Earth intersections do not certify terrain visibility or access feasibility.
(() => {
  const ANGLE_DEG = 45;
  const HALF_ANGLE = ANGLE_DEG * Math.PI / 360;
  const SEGMENTS = 128, SURFACE_HEIGHT = 15;
  const A = 6378137, B = A * (1 - 1 / 298.257223563);
  const radii = [A, A, B];
  const dot = (a, b) => a.reduce((sum, value, i) => sum + value * b[i], 0);
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const unit = (v) => { const length = Math.hypot(...v); return length > 1e-12 ? v.map((value) => value / length) : null; };

  function intersection(origin, direction) {
    const p = origin.map((value, i) => value / radii[i]);
    const d = direction.map((value, i) => value / radii[i]);
    const a = dot(d, d), b = 2 * dot(p, d), c = dot(p, p) - 1;
    const discriminant = b * b - 4 * a * c;
    if (c <= 0 || b >= 0 || discriminant < 0) return null;
    // Stable near root: avoids subtracting two almost-equal positive numbers.
    const distance = 2 * c / (-b + Math.sqrt(discriminant));
    return origin.map((value, i) => value + distance * direction[i]);
  }

  function boundary(origin, direction, right, north) {
    const ray = angle => direction.map((value, j) => value * Math.cos(HALF_ANGLE)
      + (right[j] * Math.cos(angle) + north[j] * Math.sin(angle)) * Math.sin(HALF_ANGLE));
    const step = 2 * Math.PI / SEGMENTS;
    const edges = Array.from({length: SEGMENTS}, (_, i) => intersection(origin, ray(i * step)));
    if (edges.every(Boolean)) return {footprint: edges, clipped: false};
    // The intersection of the apparent Earth disc and the circular FOV is
    // bounded by cone-edge hits and the visible ellipsoid limb. This also
    // handles partial coverage when the central ray itself misses Earth.
    const points = edges.filter(Boolean);
    const p = origin.map((value, i) => value / radii[i]), squared = dot(p, p);
    const pole = unit(p), u = unit(cross(Math.abs(pole[2]) > .99 ? [1, 0, 0] : [0, 0, 1], pole));
    const v = cross(pole, u), size = Math.sqrt(1 - 1 / squared);
    const limb = angle => p.map((value, i) => radii[i] * (value / squared
      + size * (u[i] * Math.cos(angle) + v[i] * Math.sin(angle))));
    const inside = point => dot(unit(point.map((value, i) => value - origin[i])), direction) >= Math.cos(HALF_ANGLE);
    const limbs = Array.from({length: SEGMENTS}, (_, i) => limb(i * step));
    const included = limbs.map(inside);
    for (let i = 0; i < SEGMENTS; i++) {
      const next = (i + 1) % SEGMENTS;
      if (included[i]) points.push(limbs[i]);
      if (Boolean(edges[i]) !== Boolean(edges[next])) {
        let low = i * step, high = (i + 1) * step;
        for (let j = 0; j < 36; j++) {
          const middle = (low + high) / 2;
          if (Boolean(intersection(origin, ray(middle))) === Boolean(edges[i])) low = middle; else high = middle;
        }
        const point = intersection(origin, ray(edges[i] ? low : high));
        if (point) points.push(point);
      }
      if (included[i] !== included[next]) {
        let low = i * step, high = (i + 1) * step;
        for (let j = 0; j < 36; j++) {
          const middle = (low + high) / 2;
          if (inside(limb(middle)) === included[i]) low = middle; else high = middle;
        }
        points.push(limb((low + high) / 2));
      }
    }
    if (points.length < 3) return {footprint: [], clipped: true};
    // Sort in the apparent-disc plane, never longitude: valid at both poles
    // and the date line, including crescent-shaped partial intersections.
    const sight = unit(points.reduce((sum, point) => sum.map((value, i) => value + point[i] - origin[i]), [0, 0, 0]));
    const horizontal = unit(cross(Math.abs(sight[2]) > .99 ? [1, 0, 0] : [0, 0, 1], sight));
    const vertical = cross(sight, horizontal);
    const bearing = point => Math.atan2(dot(point, vertical) - dot(origin, vertical), dot(point, horizontal) - dot(origin, horizontal));
    points.sort((a, b) => bearing(a) - bearing(b));
    const footprint = points.filter((point, i) => !i || Math.hypot(...point.map((value, j) => value - points[i - 1][j])) > .1);
    if (footprint.length > 1 && Math.hypot(...footprint[0].map((value, i) => value - footprint.at(-1)[i])) < .1) footprint.pop();
    return {footprint: footprint.length >= 3 ? footprint : [], clipped: true};
  }

  function frame(origin, boresight = null, reference = null) {
    if (!Array.isArray(origin) || origin.length !== 3 || !origin.every(Number.isFinite)) {
      throw new RangeError("Sensor origin must contain three finite Cartesian coordinates.");
    }
    if (boresight && (boresight.length !== 3 || !boresight.every(Number.isFinite) || Math.hypot(...boresight) < 1e-12)) throw new RangeError("Sensor direction must be finite and nonzero.");
    const scale = 1 / Math.hypot(...origin.map((v, i) => v / radii[i]));
    if (scale >= 1) return null;
    const up = boresight ? unit(boresight).map(v => -v) : unit(origin);
    const right = (reference && unit(reference.map((v, i) => v - dot(reference, up) * up[i])))
      || unit(cross(Math.hypot(up[0], up[1]) < 1e-8 ? [1, 0, 0] : [0, 0, 1], up));
    const north = cross(up, right);
    const direction = up.map(value => -value), ground = intersection(origin, direction);
    const offNadir = Math.acos(Math.max(-1, Math.min(1, dot(direction, unit(origin).map(value => -value)))));
    const outside = offNadir - HALF_ANGLE > Math.asin(Math.min(1, A / Math.hypot(...origin))) + 1e-10;
    const {footprint, clipped} = outside ? {footprint: [], clipped: true} : boundary(origin, direction, right, north);
    // Both mesh and outline use the exact same elevated surface vertices.
    // No flat bottom cap, buried extension or independently projected circle.
    const surfaceBoundary = footprint.map(point => {
      const normal = unit(point.map((value, i) => value / radii[i] ** 2));
      return point.map((value, i) => value + SURFACE_HEIGHT * normal[i]);
    });
    const length = surfaceBoundary.length ? Math.max(...surfaceBoundary.map(point => dot(
      origin.map((value, i) => value - point[i]), up))) : Math.hypot(...origin) * (1 - scale) + 200;
    const radius = length * Math.tan(HALF_ANGLE);
    const rim = surfaceBoundary.length ? surfaceBoundary : Array.from({length: SEGMENTS}, (_, i) => {
      const angle = i * 2 * Math.PI / SEGMENTS;
      return origin.map((value, j) => value - up[j] * length
        + radius * (right[j] * Math.cos(angle) + north[j] * Math.sin(angle)));
    });
    return {
      origin: [...origin], up, right, north, ground, footprint, surfaceBoundary, rim, length, clipped,
      center: origin.map((value, i) => value - up[i] * length / 2),
      radius,
    };
  }

  function mesh(frame) {
    const positions = new Float64Array((frame.rim.length + 1) * 3);
    positions.set([0, 0, .5]);
    frame.rim.forEach((point, i) => {
      const offset = point.map((value, j) => value - frame.center[j]);
      positions.set([dot(offset, frame.right) / frame.radius,
        dot(offset, frame.north) / frame.radius, dot(offset, frame.up) / frame.length], (i + 1) * 3);
    });
    const indices = new Uint16Array(frame.rim.length * 3);
    for (let i = 0; i < frame.rim.length; i++) indices.set([0, i + 1, (i + 1) % frame.rim.length + 1], i * 3);
    return {positions, indices};
  }
  window.SensorFov = Object.freeze({ANGLE_DEG, HALF_ANGLE, SEGMENTS, SURFACE_HEIGHT, frame, mesh});
})();
