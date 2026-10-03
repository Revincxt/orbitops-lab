"""Build the EOS-Bench-only demo as a static GitHub Pages artifact."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from orbitops import __version__
from orbitops.web import LabApplication

PROJECT_ROOT = Path(__file__).parents[1]
SCENARIO_DIR = PROJECT_ROOT / "scenarios"
STATIC_DIR = PROJECT_ROOT / "packages" / "orbitops" / "web" / "static"
ARTIFACT_MARKER = ".orbitops-pages-artifact"
ARTIFACT_MARKER_CONTENT = "orbitops-pages-v0.2\n"


def _source_revision() -> str:
    revision = os.environ.get("GITHUB_SHA", "").strip()
    if revision:
        return revision

    head = PROJECT_ROOT / ".git" / "HEAD"
    try:
        value = head.read_text(encoding="utf-8").strip()
        if value.startswith("ref: "):
            reference = PROJECT_ROOT / ".git" / value.removeprefix("ref: ")
            value = reference.read_text(encoding="utf-8").strip()
        return value or "unavailable"
    except OSError:
        return "unavailable"


def build_dataset(application: LabApplication) -> dict[str, Any]:
    """Publish only the pinned EOS-Bench archive; never solve synthetic showcases."""
    reference = application.reference.export()
    if not reference:
        raise RuntimeError("EOS-Bench reference data is unavailable")
    return {
        "metadata": {
            "mode": "eos-bench-reference-replay",
            "schema_version": "0.3",
            "source_revision": _source_revision(),
            "software_version": __version__,
        },
        "reference": reference,
    }


def _validate_output_target(output: Path) -> None:
    protected = (PROJECT_ROOT.resolve(), STATIC_DIR.resolve(), SCENARIO_DIR.resolve())
    if output == protected[0] or output in protected[0].parents:
        raise ValueError("output directory must not replace the project or one of its parents")
    if any(output == path or output.is_relative_to(path) for path in protected[1:]):
        raise ValueError("output directory must not be inside project source assets")
    if output.exists() and not output.is_dir():
        raise ValueError("output path exists and is not a directory")
    if output.exists() and any(output.iterdir()):
        marker = output / ARTIFACT_MARKER
        try:
            marker_content = marker.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(
                "refusing to replace a non-empty directory without the OrbitOps artifact marker"
            ) from exc
        if marker_content != ARTIFACT_MARKER_CONTENT:
            raise ValueError("refusing to replace a directory with an invalid artifact marker")


def build_pages(output_dir: Path) -> None:
    output = output_dir.resolve()
    _validate_output_target(output)
    dataset = build_dataset(LabApplication(SCENARIO_DIR))
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as temporary:
        staging = Path(temporary) / "artifact"
        shutil.copytree(STATIC_DIR, staging)
        deployment_config = (
            '"use strict";\n\nwindow.ORBITOPS_DEPLOYMENT = Object.freeze({ mode: "static" });\n'
        )
        (staging / "deployment-config.js").write_text(deployment_config, encoding="utf-8")
        (staging / "pages-data.json").write_text(
            json.dumps(dataset, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        (staging / ARTIFACT_MARKER).write_text(ARTIFACT_MARKER_CONTENT, encoding="utf-8")
        (staging / ".nojekyll").touch()

        previous = Path(temporary) / "previous"
        if output.exists():
            output.replace(previous)
        try:
            staging.replace(output)
        except OSError:
            if previous.exists() and not output.exists():
                previous.replace(output)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "site")
    args = parser.parse_args()
    build_pages(args.output)


if __name__ == "__main__":
    main()
