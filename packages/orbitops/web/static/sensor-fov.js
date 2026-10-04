"use strict";

// Illustrative circular, geocentric field of view. Not source sensor attitude,
// access windows, terrain visibility or task-execution evidence.
(() => {
  const ANGLE_DEG = 30;
  const HALF_ANGLE = ANGLE_DEG * Math.PI / 360;
  const A = 6378137, B = A * (1 - 1 / 298.257223563);
  const radii = [A, A, B];
  const dot = (a, b) => a.reduce((sum, value, i) => sum + value * b[i], 0);
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const unit = (v) => { const length = Math.hypot(...v); return v.map((value) => value / length); };

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

  function frame(origin) {
    if (!Array.isArray(origin) || origin.length !== 3 || !origin.every(Number.isFinite)) {
      throw new RangeError("Sensor origin must contain three finite Cartesian coordinates.");
    }
    const up = unit(origin);
    const right = unit(cross(Math.hypot(up[0], up[1]) < 1e-8 ? [1, 0, 0] : [0, 0, 1], up));
    const north = cross(up, right);
    const ground = intersection(origin, up.map((value) => -value));
    if (!ground) return null;
    const footprint = [];
    let length = 0;
    for (let i = 0; i < 48; i++) {
      const angle = i / 48 * 2 * Math.PI;
      const direction = up.map((value, j) => -value * Math.cos(HALF_ANGLE)
        + (right[j] * Math.cos(angle) + north[j] * Math.sin(angle)) * Math.sin(HALF_ANGLE));
      const point = intersection(origin, direction);
      if (!point) return null; // Do not invent a footprint when a ray misses Earth.
      footprint.push(point);
      length = Math.max(length, dot(origin.map((value, j) => value - point[j]), up));
    }
    // Bury the flat primitive cap; the opaque Earth clips its rim naturally.
    length += 200;
    return {
      origin: [...origin], up, right, north, ground, footprint, length,
      center: origin.map((value, i) => value - up[i] * length / 2),
      radius: length * Math.tan(HALF_ANGLE),
    };
  }
  window.SensorFov = Object.freeze({ANGLE_DEG, HALF_ANGLE, frame});
})();
