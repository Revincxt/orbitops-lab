"""Versioned contracts for the dependency-free learning experiment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from orbitops.domain.models import DomainModel, Scenario

FEATURE_NAMES = (
    "bias",
    "value_share",
    "value_density",
    "deadline_urgency",
    "duration_efficiency",
    "energy_efficiency",
    "storage_efficiency",
    "slew_efficiency",
    "remaining_fraction",
    "plan_end_energy_headroom",
    "plan_end_storage_headroom",
)


def scenario_fingerprint(scenario: Scenario) -> str:
    """Hash the complete canonical scenario contract used for policy training."""

    payload = json.dumps(
        scenario.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


class QLearningConfig(DomainModel):
    """Committed hyperparameters for one per-scenario training campaign."""

    episodes: int = Field(default=500, gt=0, le=1_000_000)
    learning_rate: float = Field(default=0.12, gt=0, le=1)
    discount_factor: float = Field(default=0.95, ge=0, le=1)
    initial_epsilon: float = Field(default=0.35, ge=0, le=1)
    final_epsilon: float = Field(default=0.02, ge=0, le=1)

    @model_validator(mode="after")
    def validate_epsilon_schedule(self) -> Self:
        if self.final_epsilon > self.initial_epsilon:
            raise ValueError("final_epsilon cannot exceed initial_epsilon")
        return self


class TrainingPoint(DomainModel):
    episode: int = Field(gt=0)
    epsilon: float = Field(ge=0, le=1)
    mean_abs_td_error: float = Field(ge=0)
    total_value: float = Field(ge=0)
    completed_tasks: int = Field(ge=0)
    total_slew_time_s: float = Field(ge=0)


class LinearQPolicy(DomainModel):
    """Portable, scenario-bound v2 linear action-value model."""

    schema_version: Literal["2"] = "2"
    algorithm: Literal["linear-q-learning"] = "linear-q-learning"
    training_scenario_id: str = Field(min_length=1)
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_names: tuple[str, ...] = Field(min_length=1)
    weights: tuple[float, ...] = Field(min_length=1)
    seed: int
    episodes_completed: int = Field(ge=0)
    transitions: int = Field(ge=0)
    selected_checkpoint_episode: int | None = Field(ge=1)
    evaluated_checkpoints: int = Field(ge=0)
    learning_rate: float = Field(gt=0, le=1)
    discount_factor: float = Field(ge=0, le=1)
    initial_epsilon: float = Field(ge=0, le=1)
    final_epsilon: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_feature_vector(self) -> Self:
        if len(self.feature_names) != len(self.weights):
            raise ValueError("feature_names and weights must have equal length")
        if len(self.feature_names) != len(set(self.feature_names)):
            raise ValueError("feature_names must be unique")
        if self.evaluated_checkpoints > self.episodes_completed:
            raise ValueError("evaluated_checkpoints cannot exceed episodes_completed")
        if self.selected_checkpoint_episode is None:
            if self.evaluated_checkpoints != 0:
                raise ValueError(
                    "selected_checkpoint_episode is required when checkpoints were evaluated"
                )
        elif self.evaluated_checkpoints == 0:
            raise ValueError("evaluated_checkpoints must be positive when a checkpoint is selected")
        elif self.selected_checkpoint_episode > self.evaluated_checkpoints:
            raise ValueError("selected checkpoint cannot follow the evaluated checkpoints")
        return self

    def q_value(self, features: tuple[float, ...]) -> float:
        if len(features) != len(self.weights):
            raise ValueError("feature vector length does not match policy weights")
        return sum(weight * feature for weight, feature in zip(self.weights, features, strict=True))

    @classmethod
    def from_json(cls, path: str | Path) -> Self:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def to_json(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
