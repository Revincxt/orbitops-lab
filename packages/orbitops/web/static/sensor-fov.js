"use strict";

// Illustrative 45-degree circular field of view, aligned with the source sensor
// angle and steered by the same world-frame attitude as the satellite model.
// Earth intersections do not certify terrain visibility or access feasibility.
(() => {
  const ANGLE_DEG = 45;
  const HALF_ANGLE = ANGLE_DEG * Math.PI / 360;
  const SEGMENTS = 128, SURFACE_HEIGHT = 15;
  const HALF_COS = Math.cos(HALF_ANGLE), HALF_SIN = Math.sin(HALF_ANGLE);
  const RING_STEP = 2 * Math.PI / SEGMENTS;
  const RING = Array.from({length: SEGMENTS}, (_, i) => [Math.cos(i * RING_STEP), Math.sin(i * RING_STEP)]);
  const A = 6378137, B = A * (1 - 1 / 298.257223563);
  const radii = [A, A, B];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const unit = (v) => { const length = Math.hypot(...v); return length > 1e-12 ? v.map((value) => value / length) : null; };

  function intersector(origin) {
    // One origin is shared by every ray in a frame. Scale it once rather than
    // allocating scaled origin/direction arrays for all 128 rim intersections.
    const px = origin[0] / A, py = origin[1] / A, pz = origin[2] / B;
    const c = px * px + py * py + pz * pz - 1;
    return direction => {
      const dx = direction[0] / A, dy = direction[1] / A, dz = direction[2] / B;
      const a = dx * dx + dy * dy + dz * dz;
      const b = 2 * (px * dx + py * dy + pz * dz);
      const discriminant = b * b - 4 * a * c;
      if (c <= 0 || b >= 0 || discriminant < 0) return null;
      // Stable near root: avoids subtracting two almost-equal positive numbers.
      const distance = 2 * c / (-b + Math.sqrt(discriminant));
      return [origin[0] + distance * direction[0], origin[1] + distance * direction[1],
        origin[2] + distance * direction[2]];
    };
  }

  function boundary(origin, direction, right, north, intersect) {
    const rimRay = (cosine, sine) => [
      direction[0] * HALF_COS + (right[0] * cosine + north[0] * sine) * HALF_SIN,
      direction[1] * HALF_COS + (right[1] * cosine + north[1] * sine) * HALF_SIN,
      direction[2] * HALF_COS + (right[2] * cosine + north[2] * sine) * HALF_SIN,
    ];
    const ray = angle => rimRay(Math.cos(angle), Math.sin(angle));
    const step = RING_STEP;
    const edges = RING.map(([cosine, sine]) => intersect(rimRay(cosine, sine)));
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
    const inside = point => dot(unit(point.map((value, i) => value - origin[i])), direction) >= HALF_COS;
    const limbs = Array.from({length: SEGMENTS}, (_, i) => limb(i * step));
    const included = limbs.map(inside);
    for (let i = 0; i < SEGMENTS; i++) {
      const next = (i + 1) % SEGMENTS;
      if (included[i]) points.push(limbs[i]);
      if (Boolean(edges[i]) !== Boolean(edges[next])) {
        let low = i * step, high = (i + 1) * step;
        for (let j = 0; j < 36; j++) {
          const middle = (low + high) / 2;
          if (Boolean(intersect(ray(middle))) === Boolean(edges[i])) low = middle; else high = middle;
        }
        const point = intersect(ray(edges[i] ? low : high));
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
    const direction = up.map(value => -value), intersect = intersector(origin), ground = intersect(direction);
    const offNadir = Math.acos(Math.max(-1, Math.min(1, dot(direction, unit(origin).map(value => -value)))));
    const outside = offNadir - HALF_ANGLE > Math.asin(Math.min(1, A / Math.hypot(...origin))) + 1e-10;
    const {footprint, clipped} = outside ? {footprint: [], clipped: true} : boundary(origin, direction, right, north, intersect);
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
      const x = point[0] - frame.center[0], y = point[1] - frame.center[1], z = point[2] - frame.center[2];
      const offset = (i + 1) * 3;
      positions[offset] = (x * frame.right[0] + y * frame.right[1] + z * frame.right[2]) / frame.radius;
      positions[offset + 1] = (x * frame.north[0] + y * frame.north[1] + z * frame.north[2]) / frame.radius;
      positions[offset + 2] = (x * frame.up[0] + y * frame.up[1] + z * frame.up[2]) / frame.length;
    });
    const indices = new Uint16Array(frame.rim.length * 3);
    for (let i = 0; i < frame.rim.length; i++) indices.set([0, i + 1, (i + 1) % frame.rim.length + 1], i * 3);
    return {positions, indices};
  }
  window.SensorFov = Object.freeze({ANGLE_DEG, HALF_ANGLE, SEGMENTS, SURFACE_HEIGHT, frame, mesh});
})();
