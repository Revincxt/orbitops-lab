from __future__ import annotations

import json
import math
import struct
from typing import Any

from scripts.build_satellite_model import MODEL_PATH, build_model


def model_parts() -> tuple[dict[str, Any], bytes]:
    data = MODEL_PATH.read_bytes()
    magic, version, length = struct.unpack_from("<III", data)
    assert magic == 0x46546C67 and version == 2 and length == len(data)
    size, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON" and size % 4 == 0
    metadata = json.loads(data[20 : 20 + size])
    binary_size, kind = struct.unpack_from("<I4s", data, 20 + size)
    assert kind == b"BIN\0" and binary_size % 4 == 0
    binary = data[28 + size :]
    assert len(binary) == binary_size == metadata["buffers"][0]["byteLength"]
    return metadata, binary


def test_satellite_asset_is_reproducible_self_contained_and_lightweight() -> None:
    data = MODEL_PATH.read_bytes()
    assert build_model() == data
    assert len(data) < 256 * 1024
    metadata, _ = model_parts()
    assert metadata["asset"]["version"] == "2.0"
    assert "MIT" in metadata["asset"]["copyright"]
    assert "uri" not in metadata["buffers"][0]
    assert not any(key in metadata for key in ["textures", "images", "extensionsRequired"])
    assert len(metadata["materials"]) == 6
    assert len(metadata["meshes"][0]["primitives"]) == 6
    assert metadata["extras"]["illustrative"]
    assert metadata["extras"]["sourceAttitude"] is False


def test_all_mesh_accessors_are_aligned_finite_and_bounded() -> None:
    metadata, binary = model_parts()
    triangle_count = 0
    for primitive in metadata["meshes"][0]["primitives"]:
        arrays = {}
        for attribute, number in {**primitive["attributes"], "INDEX": primitive["indices"]}.items():
            accessor = metadata["accessors"][number]
            view = metadata["bufferViews"][accessor["bufferView"]]
            index = attribute == "INDEX"
            assert accessor["componentType"] == (5123 if index else 5126)
            assert view["target"] == (34963 if index else 34962)
            assert view["byteOffset"] % 4 == 0
            count = accessor["count"] * (1 if index else 3)
            code = "H" if index else "f"
            end = view["byteOffset"] + view["byteLength"]
            assert end <= len(binary)
            values = struct.unpack_from(f"<{count}{code}", binary, view["byteOffset"])
            assert all(math.isfinite(value) for value in values)
            if not index:
                for component in range(3):
                    assert min(values[component::3]) == accessor["min"][component]
                    assert max(values[component::3]) == accessor["max"][component]
            arrays[attribute] = values
        assert len(arrays["POSITION"]) == len(arrays["NORMAL"])
        assert max(arrays["INDEX"]) < len(arrays["POSITION"]) // 3
        assert len(arrays["INDEX"]) % 3 == 0
        assert primitive["mode"] == 4
        for index in range(0, len(arrays["NORMAL"]), 3):
            assert math.isclose(math.hypot(*arrays["NORMAL"][index : index + 3]), 1, abs_tol=1e-6)
        triangle_count += len(arrays["INDEX"]) // 3
    assert 1000 < triangle_count < 4000


def test_model_triangle_winding_matches_surface_normals() -> None:
    metadata, binary = model_parts()

    def values(number: int, code: str, components: int) -> tuple[float, ...]:
        accessor = metadata["accessors"][number]
        view = metadata["bufferViews"][accessor["bufferView"]]
        return struct.unpack_from(
            f"<{accessor['count'] * components}{code}", binary, view["byteOffset"]
        )

    for primitive in metadata["meshes"][0]["primitives"]:
        positions = values(primitive["attributes"]["POSITION"], "f", 3)
        normals = values(primitive["attributes"]["NORMAL"], "f", 3)
        indices = values(primitive["indices"], "H", 1)
        for offset in range(0, len(indices), 3):
            a, b, c = [positions[int(i) * 3 : int(i) * 3 + 3] for i in indices[offset : offset + 3]]
            u = [b[i] - a[i] for i in range(3)]
            v = [c[i] - a[i] for i in range(3)]
            cross = [
                u[1] * v[2] - u[2] * v[1],
                u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0],
            ]
            normal = normals[int(indices[offset]) * 3 : int(indices[offset]) * 3 + 3]
            assert sum(cross[i] * normal[i] for i in range(3)) > 0
