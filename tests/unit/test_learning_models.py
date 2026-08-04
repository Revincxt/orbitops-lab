import json
from pathlib import Path

import pytest
from orbitops import Scenario
from orbitops.learning import (
    FEATURE_NAMES,
    LinearQPolicy,
    QLearningConfig,
    scenario_fingerprint,
)
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).parents[2]
SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"


def make_policy(scenario: Scenario) -> LinearQPolicy:
    return LinearQPolicy(
        training_scenario_id=scenario.scenario_id,
        scenario_sha256=scenario_fingerprint(scenario),
        feature_names=FEATURE_NAMES,
        weights=(0.0,) * len(FEATURE_NAMES),
        seed=7,
        episodes_completed=12,
        transitions=30,
        learning_rate=0.12,
        discount_factor=0.95,
        initial_epsilon=0.35,
        final_epsilon=0.02,
    )


def test_scenario_fingerprint_is_canonical_and_content_sensitive() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    equivalent = Scenario.model_validate_json(
        json.dumps(scenario.model_dump(mode="json"), sort_keys=True)
    )
    changed = scenario.model_copy(update={"name": "Changed name"})

    assert scenario_fingerprint(scenario) == scenario_fingerprint(equivalent)
    assert scenario_fingerprint(scenario) != scenario_fingerprint(changed)
    assert len(scenario_fingerprint(scenario)) == 64


def test_learning_config_validates_epsilon_decay() -> None:
    assert QLearningConfig().episodes == 500

    with pytest.raises(ValidationError, match="final_epsilon"):
        QLearningConfig(initial_epsilon=0.1, final_epsilon=0.2)


def test_policy_round_trips_and_scores_features(tmp_path: Path) -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    policy = make_policy(scenario).model_copy(
        update={"weights": tuple(float(index) for index in range(len(FEATURE_NAMES)))}
    )
    path = tmp_path / "models" / "demo-policy.json"

    policy.to_json(path)
    restored = LinearQPolicy.from_json(path)

    assert restored == policy
    assert restored.q_value((1.0,) * len(FEATURE_NAMES)) == sum(range(len(FEATURE_NAMES)))


def test_policy_rejects_invalid_feature_contracts() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    payload = make_policy(scenario).model_dump(mode="json")
    payload["weights"] = [0.0]

    with pytest.raises(ValidationError, match="equal length"):
        LinearQPolicy.model_validate(payload)

    payload = make_policy(scenario).model_dump(mode="json")
    payload["feature_names"] = ["same"] * len(FEATURE_NAMES)
    with pytest.raises(ValidationError, match="must be unique"):
        LinearQPolicy.model_validate(payload)

    policy = make_policy(scenario)
    with pytest.raises(ValueError, match="vector length"):
        policy.q_value((1.0,))
