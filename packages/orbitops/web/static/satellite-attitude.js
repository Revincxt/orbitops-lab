"use strict";

// Replay EOS-Bench's declared EME2000 / ZYX / FRAME_TRANSFORM attitude samples.
// Orekit's rotation maps reference coordinates into the spacecraft frame;
// invert it for display, then map Orekit's sensor +Z onto the GLB's sensor -Z.
// Keep raw source replay separate from the Earthward, eased display treatment.
// Neither path changes source angles, assignments or target/orbit data.
(() => {
  const dot = (a, b) => a.reduce((sum, v, i) => sum + v * b[i], 0);
  const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
  const unit = a => { const n = Math.hypot(...a); return n > 1e-12 ? a.map(v => v/n) : null; };
  const normalizeQuaternion = q => { const n = Math.hypot(...q); return q.map(v => v/n); };

  function quaternion(yaw, pitch, roll) {
    const half = Math.PI / 360;
    const cy = Math.cos(yaw*half), sy = Math.sin(yaw*half);
    const cp = Math.cos(pitch*half), sp = Math.sin(pitch*half);
    const cr = Math.cos(roll*half), sr = Math.sin(roll*half);
    // Body-to-EME2000: Rz(yaw) Ry(pitch) Rx(roll), the inverse of the
    // source's ZYX frame transform. Components are [w, x, y, z].
    return [cy*cp*cr + sy*sp*sr, cy*cp*sr - sy*sp*cr,
      cy*sp*cr + sy*cp*sr, sy*cp*cr - cy*sp*sr];
  }

  function slerp(a, b, fraction) {
    let cosine = dot(a, b);
    if (cosine < 0) { b = b.map(v => -v); cosine = -cosine; }
    if (cosine > .9995) return normalizeQuaternion(a.map((v, i) => v + fraction*(b[i] - v)));
    const angle = Math.acos(Math.min(1, cosine)), sine = Math.sin(angle);
    const left = Math.sin((1 - fraction)*angle)/sine, right = Math.sin(fraction*angle)/sine;
    return normalizeQuaternion(a.map((v, i) => left*v + right*b[i]));
  }

  function sample(assignment, time, step = 1) {
    if (!assignment || !Number.isFinite(time) || !Number.isFinite(step) || step <= 0
      || time < assignment.start_s || time >= assignment.end_s) return null;
    const arrays = ["yaw_angles", "pitch_angles", "roll_angles"].map(key => assignment.sat_angles?.[key]);
    if (!arrays.every(a => Array.isArray(a) && a.length && a.length === arrays[0].length)) return null;
    const offset = Math.max(0, (time - assignment.start_s)/step);
    const index = Math.min(Math.floor(offset), arrays[0].length - 1);
    const next = Math.min(index + 1, arrays[0].length - 1);
    const fraction = next === index ? 0 : offset - index;
    const a = arrays.map(values => values[index]), b = arrays.map(values => values[next]);
    if (![...a, ...b].every(Number.isFinite)) return null;
    return {index, fraction, quaternion: slerp(quaternion(...a), quaternion(...b), fraction)};
  }

  function frame(assignment, time, model, step = 1) {
    const sampled = sample(assignment, time, step);
    if (!sampled) return null;
    const [w, a, b, c] = sampled.quaternion;
    const x = model.fixedVector([1 - 2*(b*b + c*c), 2*(a*b + w*c), 2*(a*c - w*b)], time);
    const bodyY = model.fixedVector([2*(a*b - w*c), 1 - 2*(a*a + c*c), 2*(b*c + w*a)], time);
    const direction = model.fixedVector([2*(a*c + w*b), 2*(b*c - w*a), 1 - 2*(a*a + b*b)], time);
    const y = bodyY.map(v => -v), up = direction.map(v => -v);
    return {x, y, direction, modelAxes: [...x, ...y, ...up], sample: sampled,
      basis: "source Euler replay; declared EME2000; source-calibrated Earth-fixed display"};
  }

  function nadir(time, model) {
    const origin = model.cartesian(time);
    const direction = unit(origin.map(v => -v));
    if (!direction) return null;
    const before = model.cartesian(time - .5), after = model.cartesian(time + .5);
    const velocity = after.map((v, i) => v - before[i]);
    const x = unit(velocity.map((v, i) => v - dot(velocity, direction) * direction[i]));
    if (!x) return null;
    const up = direction.map(v => -v), y = cross(up, x);
    return {x, y, direction, modelAxes: [...x, ...y, ...up], basis: "idle nadir illustration"};
  }

  const clamp = value => Math.max(-1, Math.min(1, value));
  const angle = (a, b) => Math.acos(clamp(dot(a, b)));
  const MIN_SLEW_S = 30, SLEW_DEG_PER_S = .5;
  // Display boresight limit, separate from the sensor's 45-degree full FOV.
  const MAX_OFF_NADIR_DEG = 29.5;
  const smooth = value => value * value * (3 - 2 * value);
  const axes = (x, direction, extra = {}) => {
    direction = unit(direction);
    x = unit(x.map((value, i) => value - dot(x, direction) * direction[i]));
    const up = direction.map(value => -value), y = cross(up, x);
    return {...extra, x, y, direction, modelAxes: [...x, ...y, ...up]};
  };
  const idleLocal = axes([1, 0, 0], [0, 0, -1]);

  function relative(pose, idle) {
    const up = idle.modelAxes.slice(6);
    const local = vector => [dot(vector, idle.x), dot(vector, idle.y), dot(vector, up)];
    return axes(local(pose.x), local(pose.direction));
  }

  function world(pose, idle, extra) {
    const up = idle.modelAxes.slice(6);
    const fixed = vector => idle.x.map((value, i) => value * vector[0]
      + idle.y[i] * vector[1] + up[i] * vector[2]);
    return axes(fixed(pose.x), fixed(pose.direction), extra);
  }

  function rotate(vector, axis, radians) {
    const cosine = Math.cos(radians), sine = Math.sin(radians), perpendicular = cross(axis, vector);
    return vector.map((value, i) => value * cosine + perpendicular[i] * sine
      + axis[i] * dot(axis, vector) * (1 - cosine));
  }

  function blend(from, to, fraction) {
    if (fraction <= 0) return from;
    if (fraction >= 1) return to;
    const radians = angle(from.direction, to.direction);
    // The shortest boresight arc stays in the Earthward hemisphere. A separate
    // twist matches the body X axis without a full-frame SLERP rolling it skyward.
    let axis = unit(cross(from.direction, to.direction));
    if (!axis) axis = unit(cross(from.direction, [0, 0, -1]))
      || unit(cross(from.direction, [1, 0, 0]));
    const direction = rotate(from.direction, axis, radians * fraction);
    const endX = rotate(from.x, axis, radians);
    const twist = Math.atan2(dot(to.direction, cross(endX, to.x)), clamp(dot(endX, to.x)));
    const x = rotate(rotate(from.x, axis, radians * fraction), direction, twist * fraction);
    return axes(x, direction);
  }

  function earthward(raw, idle) {
    const reversed = dot(raw.direction, idle.direction) < 0;
    // A true 180-degree body-X rotation, not a reflection (determinant stays +1).
    // The 160-degree off-nadir example becomes 20 degrees, with its axis reversed.
    let direction = reversed ? raw.direction.map(value => -value) : raw.direction;
    let x = raw.x;
    const offNadir = angle(direction, idle.direction), limit = MAX_OFF_NADIR_DEG * Math.PI / 180;
    const limited = offNadir > limit;
    if (limited) {
      const axis = unit(cross(direction, idle.direction));
      // Minimal inward rotation preserves pointing azimuth and transports roll.
      x = rotate(x, axis, offNadir - limit);
      direction = rotate(direction, axis, offNadir - limit);
    }
    return axes(x, direction, {...raw, reversed, limited, sourceDirection: [...raw.direction],
      basis: "source Euler display; Earthward correction and 29.5-degree off-nadir limit"});
  }

  function boundary(assignment, time, model, step) {
    const sampledTime = Math.max(assignment.start_s, Math.min(time, assignment.end_s - 1e-7));
    const raw = frame(assignment, sampledTime, model, step);
    const idle = nadir(sampledTime, model);
    return raw && idle ? relative(earthward(raw, idle), idle) : null;
  }

  function displayFrame(assignment, time, model, step = 1) {
    const raw = frame(assignment, time, model, step);
    if (!raw) return null;
    const idle = nadir(time, model), corrected = earthward(raw, idle);
    const {index, fraction} = raw.sample;
    if (fraction > 0) {
      const firstTime = assignment.start_s + index * step;
      const nextTime = Math.min(firstTime + step, assignment.end_s - 1e-7);
      const first = frame(assignment, firstTime, model, step), next = frame(assignment, nextTime, model, step);
      const firstIdle = nadir(firstTime, model), nextIdle = nadir(nextTime, model);
      const a = earthward(first, firstIdle), b = earthward(next, nextIdle);
      if (a.reversed !== b.reversed || corrected.reversed !== a.reversed) {
        // A source axis can cross the horizon inside an observation. Interpolate
        // corrected sample endpoints through the Earthward side, not a sign snap.
        return world(blend(relative(a, firstIdle), relative(b, nextIdle), smooth(fraction)), idle,
          {...corrected, phase: "observing", hemisphereBlend: true});
      }
    }
    return {...corrected, phase: "observing"};
  }

  function slewDuration(from, to) {
    const boresight = angle(from.direction, to.direction);
    const trace = dot(from.x, to.x) + dot(from.y, to.y)
      + dot(from.modelAxes.slice(6), to.modelAxes.slice(6));
    const rotation = Math.acos(clamp((trace - 1) / 2));
    // Boresight dominates; substantial body twist also receives time to settle.
    const degrees = Math.max(boresight, rotation / 2) * 180 / Math.PI;
    return degrees < 1e-5 ? 0 : Math.max(MIN_SLEW_S, degrees / SLEW_DEG_PER_S);
  }

  function replay(schedule, time, model, step = 1) {
    let low = 0, high = schedule.length;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (schedule[middle].start_s <= time) low = middle + 1; else high = middle;
    }
    const previous = schedule[low - 1], next = schedule[low];
    if (previous && time < previous.end_s) return displayFrame(previous, time, model, step)
      || {...nadir(time, model), phase: "idle"};
    const idle = nadir(time, model);
    const exit = previous && boundary(previous, previous.end_s, model, step);
    const entry = next && boundary(next, next.start_s, model, step);
    const exitDuration = exit ? slewDuration(exit, idleLocal) : 0;
    const entryDuration = entry ? slewDuration(idleLocal, entry) : 0;
    const transition = (from, to, progress, phase, duration) => world(
      blend(from, to, smooth(progress)), idle, {
        basis: "display-only angle-timed attitude transition", phase, reversed: false,
        transition: {progress, duration_s: duration, from_task: previous?.task_id || null,
          to_task: next?.task_id || null},
      });
    const gap = previous && next ? next.start_s - previous.end_s : Infinity;
    if (exit && entry && gap > 0 && exitDuration + entryDuration > gap) {
      return transition(exit, entry, (time - previous.end_s) / gap, "retarget", gap);
    }
    if (exit && exitDuration > 0 && time < previous.end_s + exitDuration) {
      return transition(exit, idleLocal, (time - previous.end_s) / exitDuration, "recovery", exitDuration);
    }
    if (entry && entryDuration > 0 && time >= next.start_s - entryDuration) {
      return transition(idleLocal, entry, (time - next.start_s + entryDuration) / entryDuration, "preparing", entryDuration);
    }
    return {...idle, phase: "idle", reversed: false};
  }
  window.SatelliteAttitude = Object.freeze({frame, nadir, sample, displayFrame, replay, slewDuration,
    MIN_SLEW_S, SLEW_DEG_PER_S, MAX_OFF_NADIR_DEG});
})();
