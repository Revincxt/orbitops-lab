from __future__ import annotations

import base64
import gzip
import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any

import pytest
from orbitops.web.orbit_codec import ENCODING, PACKED_SCHEMA, encode_orbit_chunk

ROOT = Path(__file__).parents[2]


def restore(encoded: bytes) -> dict[str, Any]:
    """Independent test decoder; the shipped browser decoder is tested by Node too."""
    envelope = json.loads(encoded)
    shuffled = base64.b64decode(envelope["values_base64"], validate=True)
    count = len(shuffled) // 8
    packed = bytearray(len(shuffled))
    for plane in range(8):
        packed[plane::8] = shuffled[plane * count : (plane + 1) * count]
    columns = [item[0] for item in struct.iter_unpack("<d", packed)]
    samples = envelope["end_s"] - envelope["start_s"] + 1
    orbits = []
    for satellite, satellite_id in enumerate(envelope["satellite_ids"]):
        start = satellite * samples * 3
        values = [columns[start + axis * samples + i] for i in range(samples) for axis in range(3)]
        orbits.append({"satellite_id": satellite_id, "cartographic_degrees": values})
    return {
        **{key: envelope[key] for key in ["epoch_utc", "frame", "start_s", "end_s", "step_s"]},
        "schema_version": "eos-orbit-chunk-1",
        "orbits": orbits,
    }


@pytest.mark.parametrize("start", range(0, 43200, 3600))
def test_each_hour_retains_every_original_float64_bit_and_reduces_transfer(start: int) -> None:
    source_path = ROOT / "data/eos-bench/orbits" / f"{start:05d}.json"
    raw = source_path.read_bytes()
    original = json.loads(raw)
    encoded = encode_orbit_chunk(raw)
    envelope = json.loads(encoded)
    assert envelope["encoding"] == ENCODING
    assert envelope["schema_version"] == PACKED_SCHEMA
    assert envelope["source_sha256"] == hashlib.sha256(raw).hexdigest()
    decoded = restore(encoded)
    assert decoded == original
    for actual, expected in zip(decoded["orbits"], original["orbits"], strict=True):
        values = expected["cartographic_degrees"]
        assert struct.pack(f"<{len(values)}d", *actual["cartographic_degrees"]) == struct.pack(
            f"<{len(values)}d", *values
        )
    assert len(encoded) < len(raw) * 0.6
    assert (
        len(gzip.compress(encoded, compresslevel=6))
        < len(gzip.compress(raw, compresslevel=6)) * 0.7
    )
    assert encoded == encode_orbit_chunk(raw)
    assert source_path.read_bytes() == raw


def sample_chunk() -> dict[str, Any]:
    return {
        "schema_version": "eos-orbit-chunk-1",
        "epoch_utc": "2025-11-18T12:00:00Z",
        "frame": "WGS84 geodetic",
        "start_s": 0,
        "end_s": 3600,
        "step_s": 1,
        "orbits": [{"satellite_id": "test", "cartographic_degrees": [-0.0, -0.0, 500000.0] * 3601}],
    }


def test_signed_zero_ulp_and_subnormal_values_are_not_quantized() -> None:
    source = sample_chunk()
    values = source["orbits"][0]["cartographic_degrees"]
    values[3:6] = [math.nextafter(180.0, 0.0), math.nextafter(1.0, 2.0), math.nextafter(0.0, 1.0)]
    values[6:9] = [-180.0, -90.0, math.nextafter(500000.0, math.inf)]
    raw = json.dumps(source, separators=(",", ":")).encode().replace(b"[-0.0,-0.0", b"[-0,-0.0")
    actual = restore(encode_orbit_chunk(raw))["orbits"][0]["cartographic_degrees"]
    assert struct.pack(f"<{len(values)}d", *actual) == struct.pack(f"<{len(values)}d", *values)


@pytest.mark.parametrize(
    ("key", "value"),
    [("step_s", 30), ("end_s", 7200), ("frame", "other"), ("orbits", []), ("epoch_utc", None)],
)
def test_invalid_source_metadata_is_not_silently_resampled(key: str, value: Any) -> None:
    source = sample_chunk()
    source[key] = value
    with pytest.raises(ValueError, match="metadata"):
        encode_orbit_chunk(json.dumps(source).encode())


@pytest.mark.parametrize("value", [181, math.nan, math.inf, True, None, "1"])
def test_invalid_coordinates_fail_explicitly(value: Any) -> None:
    source = sample_chunk()
    source["orbits"][0]["cartographic_degrees"][0] = value
    with pytest.raises(ValueError, match="coordinate"):
        encode_orbit_chunk(json.dumps(source).encode())


@pytest.mark.parametrize("problem", ["count", "duplicate", "orbit-type"])
def test_invalid_orbit_layout_cannot_produce_a_partial_transport(problem: str) -> None:
    source = sample_chunk()
    if problem == "count":
        source["orbits"][0]["cartographic_degrees"].pop()
    elif problem == "duplicate":
        source["orbits"].append(source["orbits"][0])
    else:
        source["orbits"][0] = None
    with pytest.raises(ValueError, match="samples"):
        encode_orbit_chunk(json.dumps(source).encode())
