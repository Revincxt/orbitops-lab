# Satellite display asset

`earth-observer.glb` is an original, generic Earth-observation satellite
illustration licensed under this repository's MIT license. It is generated
reproducibly by `scripts/build_satellite_model.py`, without third-party models,
textures, decoders or network dependencies. The asset uses glTF 2.0 PBR materials,
six mesh batches, blue photovoltaic wings, a thermal-blanket bus, an optical
payload and communications hardware.

The glTF coordinates are illustrative metres, with +Y outward and the optical
payload towards -Y. Cesium converts glTF Y-up to its entity reference frame.
The viewer replays declared source attitude samples during observations and
uses an illustrative nadir orientation otherwise. The model's sensor axis and
FOV share the same orientation, with a minimum screen size for legibility.
Neither the shape, dimensions, source-calibrated attitude transform,
solar-array direction nor exaggerated screen size is spacecraft telemetry.
Source positions, schedules and sensor FOV remain
unchanged. The original satellites are not claimed to share this actual shape.

Build with `.venv/bin/python scripts/build_satellite_model.py`. Unit tests check
the deterministic binary, buffer bounds, winding, normals and self-contained
asset structure. The local server, Pages artifact and Python wheel include it.

References: [glTF 2.0](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html),
[Cesium model display scaling](https://cesium.com/learn/cesiumjs/ref-doc/ModelGraphics.html),
[model orientation](https://cesium.com/learn/cesiumjs/ref-doc/Entity.html#orientation).
