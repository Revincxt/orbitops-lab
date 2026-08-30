# Per-scenario reinforcement learning

Stage 9 adds a dependency-free linear Q-learning experiment. It is an online
learner for one scheduling scenario, not a pretrained model and not evidence of
cross-scenario generalization. The experiment exists to make the complete
learning loop inspectable: environment, feature vector, reward, temporal-
difference update, exploration schedule, model artifact, replay, and comparison
against the existing algorithms all live in the repository.

## Environment contract

The environment state contains the current validated schedule, its simulated
resource state, and the remaining task IDs. An action selects the next task. The
shared feasible-insertion primitive chooses that task's best window, start time,
and chronological position, so every transition is accepted by the same
validator used in production paths.

An episode starts with an empty schedule and ends when no remaining task has a
feasible insertion. There is no explicit stop action because the v0.1 objective
has non-negative task values and prefers more completed tasks after equal value;
adding a feasible task therefore cannot worsen the first two lexicographic
components. The action abstraction searches task ordering while deliberately
delegating continuous timing to the deterministic insertion engine.

## Linear action-value model

The action-value approximation is

```text
Q(state, action) = weights · features(state, action)
```

All eleven committed features are normalized to `[0, 1]`:

| Feature | Meaning |
| --- | --- |
| `bias` | Constant intercept. |
| `value_share` | Task value divided by total scenario value. |
| `value_density` | Value per observation second, normalized by the scenario maximum. |
| `deadline_urgency` | One minus selected-window slack over the scenario horizon. |
| `duration_efficiency` | Preference signal for shorter observations. |
| `energy_efficiency` | One minus task energy cost over the scenario maximum. |
| `storage_efficiency` | One minus task storage cost over the scenario maximum. |
| `slew_efficiency` | One minus incremental slew over the scenario horizon. |
| `remaining_fraction` | Tasks not yet attempted over total task count. |
| `plan_end_energy_headroom` | Energy over capacity at the end of the candidate plan, before any later horizon recharge. |
| `plan_end_storage_headroom` | Remaining storage capacity at the end of the candidate plan. |

The scalar shaped reward is

```text
task value / total scenario value
+ 0.01 / task count
- 0.001 × positive incremental slew / horizon
```

This reward guides temporal-difference learning; it does not replace the
project's authoritative lexicographic objective. The exploratory schedule from
each completed episode is reported as a training diagnostic, but it is not a
pure-policy evaluation. The backward-compatible `q-learning` hybrid retains the
deterministic `greedy-insertion` schedule unless either a completed exploratory
episode or a completed policy-checkpoint replay is objectively better.
`q-policy-only` instead returns the best eligible greedily replayed checkpoint
with no incumbent fallback.

Weights use the standard one-step update:

```text
TD error = reward + gamma × max(next Q) - current Q
weights += learning_rate × TD error × features
```

Defaults are learning rate `0.12`, discount factor `0.95`, initial epsilon
`0.35`, and final epsilon `0.02`. Epsilon decays geometrically across the
requested episodes. All exploration uses a local seeded random generator.

## Training and replay

Train a policy and optionally keep the complete validated result:

```bash
orbitops train scenarios/examples/demo.json \
  --model-output runs/demo-policy.json \
  --result-output runs/demo-training-result.json \
  --seed 42 \
  --episodes 250
```

The command summary reports `policy_metrics` for the exported pure-policy
checkpoint and `hybrid_metrics` for the greedy-backed training result. They are
intentionally separate: the exported model can score differently from the
hybrid incumbent. When `--result-output` is set, that file contains the hybrid
result and identifies its returned-solution mode in schedule metadata.

Replay the saved policy:

```bash
orbitops apply-policy scenarios/examples/demo.json \
  runs/demo-policy.json \
  --output runs/demo-policy-replay.json
```

Or train directly through the common solver interface:

```bash
orbitops solve scenarios/examples/demo.json \
  --solver q-learning \
  --seed 42 \
  --evaluation-budget 250
```

For a clean policy-versus-heuristic comparison, replace the solver with
`q-policy-only`. The hybrid and pure-policy modes share training code but report
their `algorithm_variant` and `returned_solution_mode` explicitly.

After every completed episode, the current weights are greedily replayed from an
empty schedule with exploration disabled. Only a replay that reaches a terminal
state before the shared deadline is eligible for selection. The exported
weights are the best of all eligible episode checkpoints under the authoritative
objective, with deterministic schedule tie-breaking. The JSON policy records
the selected episode and number of evaluated checkpoints in addition to the
feature names and weights, training hyperparameters, seed, completed episodes,
transition count, scenario ID, and SHA-256 fingerprint.

Schedule metadata keeps the selection evidence explicit:

- `training_trace` contains the realized **exploratory episode schedule**
  objective, epsilon, and TD error. It is not a pure-policy curve.
- `policy_checkpoint_trace` contains the deterministic objective for every
  completed checkpoint replay.
- `policy_convergence` contains only improvements in the best pure-policy
  checkpoint, and is the convergence trace published by `q-policy-only`.
- `selected_checkpoint_episode`, `policy_checkpoints_evaluated`, and
  `policy_checkpoint_selection_complete` describe which checkpoint was
  exported and whether every completed episode was evaluated.

The recorded `policy_checkpoint_metrics` must equal a subsequent unrestricted
replay. Replay refuses a different ID, modified scenario, or unsupported feature
contract instead of silently applying an incompatible model. It also rejects an
incomplete timeout artifact for which no checkpoint replay was evaluated.

One absolute monotonic deadline covers greedy initialization, feasible-action
enumeration, the temporal-difference loop, and checkpoint replay. If it expires
during a checkpoint replay, that partial schedule is not eligible for policy
selection; timeout and selection-completeness metadata make the interruption
visible. `apply-policy` can also receive the same absolute deadline contract
through the Python API and then reports whether replay completed.
If `q-policy-only` times out before its first checkpoint replay completes, it
returns a feasible empty schedule labeled `no-complete-policy-checkpoint` rather
than presenting zero weights or the hybrid incumbent as a selected policy.

## Policy artifact compatibility

Policy schema v2 is intentionally breaking. The two resource-headroom features
now describe state at the end of the candidate plan; v1 weights were trained
against horizon-projected resource state after later recharge. Because each
weight is attached to a feature's semantics, there is no safe weight-only
migration from v1 to v2. A v1 artifact must be retrained with this release on its
original scenario. The committed v1 schema is retained as an archival contract,
but the current policy loader rejects v1 artifacts instead of relabeling them.

## Evidence and comparison boundary

`evaluation_budget` means requested training episodes for both Q-learning modes;
under a deadline, fewer episodes or checkpoint replays may complete. Local
search and genetic search count unique decoded genomes. Equal numeric budgets
therefore control work within each solver but are not identical units of
algorithmic effort. Runtime, transition counts, and evaluated-checkpoint counts
must accompany comparisons.

The committed smoke campaign exercises reproducibility and integration:

```bash
orbitops benchmark configs/learning-smoke.toml --output runs/learning-smoke
```

It is not a claim that reinforcement learning outperforms the hand-written
heuristics. A credible generalization study would require separate training and
held-out scenario distributions, frozen hyperparameters, substantially more
seeds, and confidence intervals. None of those claims are made in Stage 9.
