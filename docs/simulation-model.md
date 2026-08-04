# v0.1 simulation model

The simulator is the only component allowed to derive task end times, attitude
transitions, or resource states. A solver submits only task IDs, selected window
IDs, and start times.

## Event order

Assignments are normalized by `(start_s, task_id, input_position)`. For every
known, first-occurrence task, the simulator:

1. derives `end_s = start_s + duration_s`;
2. checks horizon and visibility-window containment;
3. computes the shortest signed-angle slew from the preceding attitude;
4. recharges the battery during elapsed time, capped at capacity;
5. recharges during observation and applies the task energy cost at task end;
6. adds task storage at task end; and
7. emits a trace containing resource state before and after the task.

## v0.1 assumptions

- Recharge is a constant background rate and remains active during observation.
- Slew has no separate energy cost.
- Storage only increases; downlink is outside v0.1.
- Task energy and storage costs are deterministic lumped quantities.
- A zero-distance attitude transition requires no settling time.
- Invalid schedules still produce a best-effort trace alongside stable issue codes.

These assumptions are intentionally simple and must be versioned if changed.
