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
| `energy_headroom` | Simulated final energy over capacity after the action. |
| `storage_headroom` | Remaining storage capacity after the action. |

The scalar shaped reward is

```text
task value / total scenario value
+ 0.01 / task count
- 0.001 × positive incremental slew / horizon
```

This reward guides temporal-difference learning; it does not replace the
project's authoritative lexicographic objective. Completed episodes are ranked
with `ObjectiveScore`, and the final result retains the deterministic
`greedy-insertion` schedule unless a learned episode is objectively better.

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

The JSON policy records the feature names and weights, training hyperparameters,
seed, completed episodes, transition count, scenario ID, and SHA-256 fingerprint
of the complete scenario. Replay refuses a different ID, modified scenario, or
unsupported feature contract instead of silently applying an incompatible
model.

## Evidence and comparison boundary

`evaluation_budget` means complete training episodes for `q-learning`; local
search and genetic search count unique decoded genomes. Equal numeric budgets
therefore control work within each solver but are not identical units of
algorithmic effort. Runtime and transition counts must accompany comparisons.

The committed smoke campaign exercises reproducibility and integration:

```bash
orbitops benchmark configs/learning-smoke.toml --output runs/learning-smoke
```

It is not a claim that reinforcement learning outperforms the hand-written
heuristics. A credible generalization study would require separate training and
held-out scenario distributions, frozen hyperparameters, substantially more
seeds, and confidence intervals. None of those claims are made in Stage 9.
