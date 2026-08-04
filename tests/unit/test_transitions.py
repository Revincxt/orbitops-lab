import pytest
from orbitops import Satellite
from orbitops.domain.transitions import (
    angular_distance_deg,
    recharge_energy_wh,
    required_slew_time_s,
)


@pytest.fixture
def satellite() -> Satellite:
    return Satellite(
        satellite_id="test-sat",
        energy_capacity_wh=100.0,
        initial_energy_wh=50.0,
        recharge_rate_w=36.0,
        storage_capacity_gb=20.0,
        initial_storage_gb=1.0,
        initial_attitude_deg=0.0,
        slew_rate_deg_s=2.0,
        settling_time_s=5.0,
    )


def test_angular_distance_wraps_at_signed_boundary() -> None:
    assert angular_distance_deg(170.0, -170.0) == 20.0
    assert angular_distance_deg(-170.0, 170.0) == 20.0


def test_zero_distance_needs_no_settling(satellite: Satellite) -> None:
    assert required_slew_time_s(satellite, 10.0, 10.0) == 0.0


def test_slew_includes_movement_and_settling(satellite: Satellite) -> None:
    assert required_slew_time_s(satellite, 10.0, 30.0) == 15.0


def test_recharge_converts_watts_and_seconds_to_watt_hours(satellite: Satellite) -> None:
    assert recharge_energy_wh(satellite, 50.0, 1000.0) == 60.0


def test_recharge_is_capped_at_capacity(satellite: Satellite) -> None:
    assert recharge_energy_wh(satellite, 99.0, 1000.0) == 100.0


def test_negative_elapsed_time_is_rejected(satellite: Satellite) -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        recharge_energy_wh(satellite, 50.0, -1.0)
