"""Build the original, texture-free glTF satellite illustration reproducibly.

Dimensions are illustrative metres, not a replica of any source spacecraft.
The glTF +Y axis is outward/up and the -Y payload faces Earth after Cesium's
Y-up conversion. Six material batches keep the 20-instance scene lightweight.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MODEL_PATH = (
    Path(__file__).resolve().parents[1] / "packages/orbitops/web/static/models/earth-observer.glb"
)
Vec3 = tuple[float, float, float]


@dataclass
class Mesh:
    positions: list[float] = field(default_factory=list)
    normals: list[float] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)

    def triangle(self, a: Vec3, b: Vec3, c: Vec3) -> None:
        u = tuple(b[i] - a[i] for i in range(3))
        v = tuple(c[i] - a[i] for i in range(3))
        normal = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        length = math.hypot(*normal)
        if length < 1e-10:
            return
        first = len(self.positions) // 3
        for point in (a, b, c):
            self.positions.extend(point)
            self.normals.extend(value / length for value in normal)
        self.indices.extend((first, first + 1, first + 2))

    def quad(self, a: Vec3, b: Vec3, c: Vec3, d: Vec3) -> None:
        self.triangle(a, b, c)
        self.triangle(a, c, d)

    def box(self, centre: Vec3, size: Vec3) -> None:
        x, y, z = centre
        a, b, c = (value / 2 for value in size)
        vertices = [
            (x - a, y - b, z - c),
            (x + a, y - b, z - c),
            (x + a, y + b, z - c),
            (x - a, y + b, z - c),
            (x - a, y - b, z + c),
            (x + a, y - b, z + c),
            (x + a, y + b, z + c),
            (x - a, y + b, z + c),
        ]
        for face in [
            (0, 3, 2, 1),
            (4, 5, 6, 7),
            (0, 4, 7, 3),
            (1, 2, 6, 5),
            (0, 1, 5, 4),
            (3, 7, 6, 2),
        ]:
            self.quad(*(vertices[index] for index in face))

    def cylinder(self, centre: Vec3, radius: float, length: float, segments: int = 24) -> None:
        x, y, z = centre
        bottom, top = y - length / 2, y + length / 2
        for i in range(segments):
            a, b = i * math.tau / segments, (i + 1) * math.tau / segments
            p = (x + radius * math.cos(a), bottom, z + radius * math.sin(a))
            q = (x + radius * math.cos(b), bottom, z + radius * math.sin(b))
            r = (q[0], top, q[2])
            s = (p[0], top, p[2])
            self.quad(p, s, r, q)
            self.triangle((x, bottom, z), p, q)
            self.triangle((x, top, z), r, s)

    def dish(self, centre: Vec3, radius: float) -> None:
        x, y, z = centre
        # Double-sided shallow paraboloid, with a finite, rounded rim.
        for ring in range(5):
            inner, outer = radius * ring / 5, radius * (ring + 1) / 5
            for i in range(32):
                a, b = i * math.tau / 32, (i + 1) * math.tau / 32

                def point(r: float, angle: float, offset: float) -> Vec3:
                    return (
                        x + r * math.cos(angle),
                        y + 0.25 * (r / radius) ** 2 + offset,
                        z + r * math.sin(angle),
                    )

                self.quad(
                    point(inner, a, 0), point(inner, b, 0), point(outer, b, 0), point(outer, a, 0)
                )
                self.quad(
                    point(inner, a, -0.018),
                    point(outer, a, -0.018),
                    point(outer, b, -0.018),
                    point(inner, b, -0.018),
                )


def material(name: str, colour: Vec3, metallic: float, roughness: float) -> dict[str, Any]:
    return {
        "name": name,
        "pbrMetallicRoughness": {
            "baseColorFactor": [*colour, 1],
            "metallicFactor": metallic,
            "roughnessFactor": roughness,
        },
        # Modest display fill keeps detail legible at map-icon scale, not a light
        # source or physical illumination/eclipsing calculation.
        "emissiveFactor": [value * 0.035 for value in colour],
    }


def build_model() -> bytes:
    gold, alloy, panel, cell, dark, lens = (Mesh() for _ in range(6))
    materials = [
        material("Gold thermal blanket", (0.72, 0.46, 0.12), 0.65, 0.43),
        material("Brushed aluminium", (0.68, 0.73, 0.78), 0.8, 0.34),
        material("Solar wing substrate", (0.025, 0.06, 0.13), 0.4, 0.52),
        material("Blue photovoltaic cells", (0.035, 0.17, 0.39), 0.45, 0.3),
        material("Carbon and radiator", (0.035, 0.045, 0.06), 0.15, 0.65),
        material("Optical glass", (0.05, 0.26, 0.37), 0.75, 0.13),
    ]
    # Main bus with bevelled vertical edges and separate metallic end plates.
    outline = [
        (-0.58, -0.7),
        (0.58, -0.7),
        (0.7, -0.58),
        (0.7, 0.58),
        (0.58, 0.7),
        (-0.58, 0.7),
        (-0.7, 0.58),
        (-0.7, -0.58),
    ]
    for i, (x, z) in enumerate(outline):
        nx, nz = outline[(i + 1) % len(outline)]
        gold.quad((x, -0.82, z), (x, 0.82, z), (nx, 0.82, nz), (nx, -0.82, nz))
    alloy.box((0, 0.85, 0), (1.36, 0.08, 1.36))
    alloy.box((0, -0.85, 0), (1.36, 0.08, 1.36))
    # Raised thermal-blanket folds and strips.
    for z in [-0.48, -0.16, 0.16, 0.48]:
        gold.box((-0.704, 0, z), (0.018, 1.48, 0.025))
        gold.box((0.704, 0, z), (0.018, 1.48, 0.025))
    dark.box((0, 0.02, -0.712), (0.86, 1.18, 0.025))
    for x in [-0.3, -0.15, 0, 0.15, 0.3]:
        alloy.box((x, 0.02, -0.73), (0.025, 1.1, 0.015))
    # Two deployed segmented solar wings, with both faces represented.
    for side in [-1, 1]:
        alloy.box((side * 1.04, 0.12, 0), (0.68, 0.075, 0.075))
        panel.box((side * 2.66, 0.12, 0), (2.62, 0.065, 1.78))
        for x in [1.36, 2.01, 2.66, 3.31, 3.97]:
            alloy.box((side * x, 0.12, 0), (0.027, 0.084, 1.81))
        for z in [-0.89, 0.89]:
            alloy.box((side * 2.66, 0.12, z), (2.66, 0.084, 0.025))
        for column in range(8):
            for row in range(4):
                x = side * (1.53 + column * 0.316)
                z = -0.66 + row * 0.44
                cell.box((x, 0.158, z), (0.287, 0.008, 0.398))
                cell.box((x, 0.082, z), (0.287, 0.008, 0.398))
    # Earth-facing camera barrel, dark aperture and blue lens.
    alloy.cylinder((0, -1.05, 0), 0.42, 0.32)
    dark.cylinder((0, -1.27, 0), 0.36, 0.18)
    lens.cylinder((0, -1.367, 0), 0.29, 0.02)
    # Communications dish, feed mast and small star tracker / antenna.
    alloy.cylinder((0, 1.01, 0), 0.065, 0.32, 12)
    alloy.dish((0, 1.18, 0), 0.57)
    dark.cylinder((0, 1.47, 0), 0.025, 0.58, 8)
    alloy.cylinder((0, 1.76, 0), 0.06, 0.08, 12)
    dark.box((0.45, 1.04, -0.42), (0.3, 0.28, 0.32))
    lens.box((0.45, 1.187, -0.42), (0.16, 0.013, 0.18))
    alloy.cylinder((-0.5, 1.16, -0.46), 0.016, 0.52, 8)

    binary = bytearray()
    views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []
    primitives = []

    def accessor(values: list[float] | list[int], kind: str, indices: bool = False) -> int:
        binary.extend(b"\0" * (-len(binary) % 4))
        offset = len(binary)
        binary.extend(struct.pack(f"<{len(values)}{'H' if indices else 'f'}", *values))
        views.append(
            {
                "buffer": 0,
                "byteOffset": offset,
                "byteLength": len(binary) - offset,
                "target": 34963 if indices else 34962,
            }
        )
        components = 1 if indices else 3
        entry = {
            "bufferView": len(views) - 1,
            "componentType": 5123 if indices else 5126,
            "count": len(values) // components,
            "type": kind,
        }
        if not indices:
            # Bounds must reflect float32, the actual binary accessor values.
            packed = struct.unpack(f"<{len(values)}f", binary[offset:])
            entry["min"] = [min(packed[i::3]) for i in range(3)]
            entry["max"] = [max(packed[i::3]) for i in range(3)]
        accessors.append(entry)
        return len(accessors) - 1

    for index, mesh in enumerate((gold, alloy, panel, cell, dark, lens)):
        positions = accessor(mesh.positions, "VEC3")
        normals = accessor(mesh.normals, "VEC3")
        indices = accessor(mesh.indices, "SCALAR", True)
        primitives.append(
            {
                "attributes": {"POSITION": positions, "NORMAL": normals},
                "indices": indices,
                "material": index,
                "mode": 4,
            }
        )
    binary.extend(b"\0" * (-len(binary) % 4))
    document = {
        "asset": {
            "version": "2.0",
            "generator": "OrbitOps procedural satellite model",
            "copyright": "Original OrbitOps illustration, MIT license",
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "Generic Earth observation satellite"}],
        "meshes": [{"name": "Satellite", "primitives": primitives}],
        "materials": materials,
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": accessors,
        "extras": {
            "illustrative": True,
            "units": "metres",
            "payloadDirection": "-Y",
            "sourceAttitude": False,
        },
    }
    metadata = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    metadata += b" " * (-len(metadata) % 4)
    length = 12 + 8 + len(metadata) + 8 + len(binary)
    return (
        struct.pack("<III", 0x46546C67, 2, length)
        + struct.pack("<I4s", len(metadata), b"JSON")
        + metadata
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )


def main() -> None:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    model = build_model()
    MODEL_PATH.write_bytes(model)
    print(f"Built {MODEL_PATH.relative_to(MODEL_PATH.parents[5])}: {len(model)} bytes")


if __name__ == "__main__":
    main()
