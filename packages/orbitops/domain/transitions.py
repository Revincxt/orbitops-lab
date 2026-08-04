"""Pure transition calculations shared by simulation and future solvers."""

from __future__ import annotations

from orbitops.domain.models import Satellite


def angular_distance_deg(from_attitude_deg: float, to_attitude_deg: float) -> float:
    """Return the shortest angular distance on a signed 360-degree circle."""

    return abs((to_attitude_deg - from_attitude_deg + 180.0) % 360.0 - 180.0)


def required_slew_time_s(
    satellite: Satellite,
    from_attitude_deg: float,
    to_attitude_deg: float,
) -> float:
    """Compute movement plus settling time for a change in attitude."""

    distance_deg = angular_distance_deg(from_attitude_deg, to_attitude_deg)
    if distance_deg == 0.0:
        return 0.0
    return distance_deg / satellite.slew_rate_deg_s + satellite.settling_time_s


def recharge_energy_wh(
    satellite: Satellite,
    current_energy_wh: float,
    elapsed_s: float,
) -> float:
    """Apply constant background charging, capped at battery capacity."""

    if elapsed_s < 0:
        raise ValueError("elapsed_s cannot be negative")
    gained_wh = satellite.recharge_rate_w * elapsed_s / 3600.0
    return min(satellite.energy_capacity_wh, current_energy_wh + gained_wh)
