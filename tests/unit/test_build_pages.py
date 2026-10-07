from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from orbitops.web import LabApplication

from scripts import build_pages as pages


def test_pages_artifact_contains_only_eos_bench_and_performs_no_solves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = LabApplication(pages.REFERENCE_PATH)

    def forbidden_dispatch(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Demo generation must not request local catalogs or solve scenarios")

    monkeypatch.setattr(application, "dispatch", forbidden_dispatch)
    dataset = pages.build_dataset(application)
    assert set(dataset) == {"metadata", "reference"}
    assert dataset["metadata"]["mode"] == "eos-bench-reference-replay"
    assert dataset["reference"]["scenario"]["scenario_id"] == "eos-s1-20-500"
    assert len(dataset["reference"]["plans"]) == 7


def test_pages_build_fails_if_reference_archive_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = LabApplication(pages.REFERENCE_PATH)
    monkeypatch.setattr(application.reference, "export", lambda: None)
    with pytest.raises(RuntimeError, match="EOS-Bench reference data is unavailable"):
        pages.build_dataset(application)


def test_pages_build_bundles_fonts_and_orbit_extension(tmp_path: Path) -> None:
    output = tmp_path / "site"
    pages.build_pages(output)
    for filename in ["InterVariable.woff2", "OFL.txt", "README.txt"]:
        assert (output / "fonts" / filename).read_bytes() == (
            pages.STATIC_DIR / "fonts" / filename
        ).read_bytes()
    assert 'href="./fonts/InterVariable.woff2"' in (output / "index.html").read_text()
    assert (output / "orbit-model.js").read_bytes() == (
        pages.STATIC_DIR / "orbit-model.js"
    ).read_bytes()
    assert "./orbit-model.js?v=0.26.0" in (output / "index.html").read_text()
    assert (output / "sensor-fov.js").read_bytes() == (
        pages.STATIC_DIR / "sensor-fov.js"
    ).read_bytes()
    assert "./sensor-fov.js?v=0.26.0" in (output / "index.html").read_text()
    for name in ["orbit-ephemeris.js", "satellite-attitude.js"]:
        assert (output / name).read_bytes() == (pages.STATIC_DIR / name).read_bytes()
    reference = LabApplication(pages.REFERENCE_PATH).reference
    for entry in reference.data["replay"]["ephemeris"]["chunks"]:
        assert (output / "orbit-data" / entry["filename"]).read_bytes() == reference.orbit_chunk(
            entry["filename"]
        )
    assert (output / "models/earth-observer.glb").read_bytes() == (
        pages.STATIC_DIR / "models/earth-observer.glb"
    ).read_bytes()


@pytest.mark.parametrize("target", ["scenarios", "data", "data/eos-bench/orbits"])
def test_pages_builder_protects_source_scenarios_and_data(target: str) -> None:
    with pytest.raises(ValueError, match="source assets"):
        pages._validate_output_target((pages.PROJECT_ROOT / target).resolve())


def test_pages_builder_refuses_unmarked_nonempty_output(tmp_path: Path) -> None:
    output = tmp_path / "foreign-directory"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("user data", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact marker"):
        pages.build_pages(output)

    assert sentinel.read_text(encoding="utf-8") == "user data"


def test_pages_builder_replaces_only_marked_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    scenario_dir = tmp_path / "scenario-source"
    scenario_dir.mkdir()
    output = tmp_path / "site"
    output.mkdir()
    (output / pages.ARTIFACT_MARKER).write_text(
        pages.ARTIFACT_MARKER_CONTENT,
        encoding="utf-8",
    )
    (output / "stale.txt").write_text("old", encoding="utf-8")

    dataset: dict[str, Any] = {
        "metadata": {"schema_version": "0.2"},
        "reference": {"scenario": {"scenario_id": "eos-s1-20-500"}, "plans": []},
    }
    monkeypatch.setattr(pages, "STATIC_DIR", static_dir)
    monkeypatch.setattr(pages, "SCENARIO_DIR", scenario_dir)
    monkeypatch.setattr(pages, "LabApplication", lambda _: object())
    monkeypatch.setattr(pages, "build_dataset", lambda _: dataset)

    pages.build_pages(output)

    assert not (output / "stale.txt").exists()
    assert (output / "index.html").read_text(encoding="utf-8") == "<!doctype html>"
    assert json.loads((output / "pages-data.json").read_text(encoding="utf-8")) == dataset
    assert (output / pages.ARTIFACT_MARKER).read_text(encoding="utf-8") == (
        pages.ARTIFACT_MARKER_CONTENT
    )
