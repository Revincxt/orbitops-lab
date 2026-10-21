"""Lossless browser transport for the pinned, one-second geodetic source samples.

The source JSON stays untouched. IEEE-754 binary64 values are grouped by satellite
and coordinate, byte-shuffled, and base64-wrapped in JSON so static hosts can use
their normal gzip encoding. No quantization, float32 conversion, or resampling.
"""

from __future__ import annotations

import array
import base64
import hashlib
import json
import math
import sys
from typing import Any

ENCODING = "f64le-column-byteplanes-base64"
PACKED_SCHEMA = "eos-orbit-f64-1"


def encode_orbit_chunk(raw: bytes) -> bytes:
    """Encode the exact binary64 numbers a browser reads from source JSON."""
    # JSON.parse preserves the sign of the integer spelling -0 as well as -0.0.
    data: Any = json.loads(raw, parse_int=lambda value: -0.0 if value == "-0" else int(value))
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != "eos-orbit-chunk-1"
        or data.get("frame") != "WGS84 geodetic"
        or data.get("step_s") != 1
        or not isinstance(data.get("start_s"), int)
        or not isinstance(data.get("end_s"), int)
        or data["end_s"] - data["start_s"] != 3600
        or not isinstance(data.get("epoch_utc"), str)
        or not isinstance(data.get("orbits"), list)
        or not 1 <= len(data["orbits"]) <= 64
    ):
        raise ValueError("Invalid source orbit chunk metadata")
    samples = data["end_s"] - data["start_s"] + 1
    ids: list[str] = []
    columns = array.array("d")
    for orbit in data["orbits"]:
        if not isinstance(orbit, dict):
            raise ValueError("Invalid source orbit samples")
        satellite_id = orbit.get("satellite_id")
        values = orbit.get("cartographic_degrees")
        if (
            not isinstance(satellite_id, str)
            or not satellite_id
            or satellite_id in ids
            or not isinstance(values, list)
            or len(values) != samples * 3
        ):
            raise ValueError("Invalid source orbit samples")
        for i, value in enumerate(values):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or (
                    abs(value) > 180
                    if i % 3 == 0
                    else abs(value) > 90
                    if i % 3 == 1
                    else value <= 0
                )
            ):
                raise ValueError("Invalid source orbit coordinate")
        ids.append(satellite_id)
        for axis in range(3):
            columns.extend(values[axis::3])
    if columns.itemsize != 8:
        raise RuntimeError("IEEE-754 binary64 transport requires eight-byte doubles")
    if sys.byteorder != "little":
        columns.byteswap()
    packed = columns.tobytes()
    shuffled = b"".join(packed[plane::8] for plane in range(8))
    envelope = {
        **{key: value for key, value in data.items() if key != "orbits"},
        "schema_version": PACKED_SCHEMA,
        "encoding": ENCODING,
        "satellite_ids": ids,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "values_base64": base64.b64encode(shuffled).decode("ascii"),
    }
    return (
        json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()
