"""Public constraint-validation facade."""

from __future__ import annotations

from orbitops.domain.models import Scenario, Schedule, ValidationReport
from orbitops.simulation.simulator import DiscreteEventSimulator


class ConstraintValidator:
    def __init__(self, simulator: DiscreteEventSimulator | None = None) -> None:
        self.simulator = simulator or DiscreteEventSimulator()

    def validate(self, scenario: Scenario, schedule: Schedule) -> ValidationReport:
        outcome = self.simulator.simulate(scenario, schedule)
        return ValidationReport(issues=outcome.issues, simulation=outcome.result)


def validate_schedule(scenario: Scenario, schedule: Schedule) -> ValidationReport:
    """Validate a schedule with the shared deterministic simulator."""

    return ConstraintValidator().validate(scenario, schedule)
