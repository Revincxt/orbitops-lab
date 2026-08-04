import math

from hypothesis import given
from hypothesis import strategies as st
from orbitops import Satellite
from orbitops.domain.transitions import angular_distance_deg, recharge_energy_wh

finite_attitudes = st.floats(
    min_value=-180.0,
    max_value=180.0,
    allow_nan=False,
    allow_infinity=False,
)


@given(finite_attitudes, finite_attitudes)
def test_angular_distance_is_symmetric_and_bounded(first: float, second: float) -> None:
    forward = angular_distance_deg(first, second)
    backward = angular_distance_deg(second, first)

    assert 0.0 <= forward <= 180.0
    assert math.isclose(forward, backward, abs_tol=1e-9)


@given(
    current=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    elapsed=st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
)
def test_recharge_never_decreases_or_exceeds_capacity(current: float, elapsed: float) -> None:
    satellite = Satellite(
        satellite_id="property-sat",
        energy_capacity_wh=100.0,
        initial_energy_wh=50.0,
        recharge_rate_w=80.0,
        storage_capacity_gb=10.0,
        initial_storage_gb=0.0,
        initial_attitude_deg=0.0,
        slew_rate_deg_s=1.0,
        settling_time_s=0.0,
    )

    result = recharge_energy_wh(satellite, current, elapsed)

    assert current <= result <= satellite.energy_capacity_wh
