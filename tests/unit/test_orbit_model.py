from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from orbitops.web.orbit_codec import encode_orbit_chunk


def test_display_orbit_model_against_source_holdouts_and_physical_invariants(
    tmp_path: Path,
) -> None:
    node = shutil.which("node")
    if not node:
        playwright = importlib.util.find_spec("playwright")
        if playwright and playwright.origin:
            bundled = Path(playwright.origin).parent / "driver" / "node"
            if bundled.is_file():
                node = str(bundled)
    if not node:
        pytest.skip("Node.js is required for pure JavaScript orbit-model checks")
    root = Path(__file__).parents[2]
    for source in (root / "data/eos-bench/orbits").glob("*.json"):
        (tmp_path / source.name).write_bytes(encode_orbit_chunk(source.read_bytes()))
    result = subprocess.run(
        [
            node,
            "--test",
            str(root / "tests/javascript/orbit-model.test.cjs"),
            str(root / "tests/javascript/sensor-fov.test.cjs"),
            str(root / "tests/javascript/radar.test.cjs"),
            str(root / "tests/javascript/orbit-ephemeris.test.cjs"),
            str(root / "tests/javascript/orbit-codec.test.cjs"),
            str(root / "tests/javascript/satellite-attitude.test.cjs"),
            str(root / "tests/javascript/replay-state.test.cjs"),
            str(root / "tests/javascript/imagery.test.cjs"),
            str(root / "tests/javascript/data-store.test.cjs"),
            str(root / "tests/javascript/reference-plans.test.cjs"),
        ],
        cwd=root,
        env={**os.environ, "ORBITOPS_PACKED_ORBIT_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
