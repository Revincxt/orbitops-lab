from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest


def test_display_orbit_model_against_source_holdouts_and_physical_invariants() -> None:
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
    result = subprocess.run(
        [
            node,
            "--test",
            str(root / "tests/javascript/orbit-model.test.cjs"),
            str(root / "tests/javascript/sensor-fov.test.cjs"),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
