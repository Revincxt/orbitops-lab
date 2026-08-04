from orbitops import ObservationTask, Satellite, Scenario, Target, TimeWindow
from orbitops.simulation.validator import validate_schedule
from orbitops.solvers.common import empty_schedule
from orbitops.solvers.exact_common import feasible_appends


def _energy_wait_scenario(*, energy_cost_wh: float = 5.0) -> Scenario:
    return Scenario(
        scenario_id="energy-wait",
        name="Energy wait dominance case",
        horizon_end_s=10.0,
        satellite=Satellite(
            satellite_id="sat",
            energy_capacity_wh=10.0,
            initial_energy_wh=0.0,
            recharge_rate_w=3600.0,
            storage_capacity_gb=10.0,
            initial_storage_gb=0.0,
            initial_attitude_deg=0.0,
            slew_rate_deg_s=1.0,
            settling_time_s=0.0,
        ),
        tasks=(
            ObservationTask(
                task_id="task",
                target=Target(
                    target_id="target",
                    name="Target",
                    latitude_deg=0.0,
                    longitude_deg=0.0,
                ),
                priority_value=1.0,
                duration_s=1.0,
                visibility_windows=(TimeWindow(window_id="window", start_s=0.0, end_s=10.0),),
                required_attitude_deg=0.0,
                energy_cost_wh=energy_cost_wh,
                storage_cost_gb=1.0,
            ),
        ),
    )


def test_exact_append_waits_only_until_energy_is_available() -> None:
    scenario = _energy_wait_scenario()
    schedule = empty_schedule(scenario, "test", seed=0)

    candidates = feasible_appends(
        scenario,
        schedule,
        scenario.tasks[0],
        validation=validate_schedule(scenario, schedule),
    )

    assert len(candidates) == 1
    assert candidates[0].inserted.start_s == 4.0
    assert candidates[0].validation.is_feasible


def test_exact_append_rejects_task_cost_above_battery_capacity() -> None:
    scenario = _energy_wait_scenario(energy_cost_wh=11.0)
    schedule = empty_schedule(scenario, "test", seed=0)

    assert feasible_appends(scenario, schedule, scenario.tasks[0]) == ()
