from __future__ import annotations

import copy
import gzip
import hashlib
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
    assert "./orbit-model.js?v=0.42.0" in (output / "index.html").read_text()
    assert (output / "sensor-fov.js").read_bytes() == (
        pages.STATIC_DIR / "sensor-fov.js"
    ).read_bytes()
    assert (output / "imagery.js").read_bytes() == (pages.STATIC_DIR / "imagery.js").read_bytes()
    assert "./sensor-fov.js?v=0.42.0" in (output / "index.html").read_text()
    for name in ["orbit-ephemeris.js", "satellite-attitude.js"]:
        assert (output / name).read_bytes() == (pages.STATIC_DIR / name).read_bytes()
    for name in ["data-store", "reference-plans"]:
        assert (output / f"{name}.js").read_bytes() == (
            pages.STATIC_DIR / f"{name}.js"
        ).read_bytes()
        assert f"./{name}.js?v=0.43.0" in (output / "index.html").read_text()
    reference = LabApplication(pages.REFERENCE_PATH).reference
    for entry in reference.data["replay"]["ephemeris"]["chunks"]:
        assert (output / "orbit-data" / entry["filename"]).read_bytes() == reference.orbit_chunk(
            entry["filename"]
        )
    assert (output / "models/earth-observer.glb").read_bytes() == (
        pages.STATIC_DIR / "models/earth-observer.glb"
    ).read_bytes()
    bootstrap = json.loads((output / "pages-data.json").read_text())
    assert bootstrap["metadata"]["schema_version"] == "0.4"
    for summary, original in zip(
        bootstrap["reference"]["plans"], reference.export()["plans"], strict=True
    ):
        asset = summary["asset"]
        raw = (output / "plan-data" / asset["filename"]).read_bytes()
        assert len(raw) == asset["bytes"]
        assert hashlib.sha256(raw).hexdigest() == asset["sha256"]
        assert json.loads(raw) == original
        assert "assignments" not in summary and "checks" not in summary
        for field in pages.PLAN_SUMMARY_FIELDS:
            assert summary[field] == original[field]


def test_plan_split_preserves_the_source_and_reduces_default_cold_download() -> None:
    full = pages.build_dataset(LabApplication(pages.REFERENCE_PATH))
    snapshot = copy.deepcopy(full)
    bootstrap, assets = pages.split_plan_data(full)
    assert full == snapshot
    assert bootstrap["reference"]["scenario"] == full["reference"]["scenario"]
    assert bootstrap["reference"]["replay"] == full["reference"]["replay"]
    assert len(assets) == 7
    summary = next(p for p in bootstrap["reference"]["plans"] if p["plan_id"] == "eos-sa-balanced")

    def compressed(value: Any) -> int:
        return len(gzip.compress(json.dumps(value, separators=(",", ":")).encode()))

    initial_bytes = compressed(bootstrap) + len(gzip.compress(assets[summary["asset"]["filename"]]))
    assert initial_bytes < compressed(full) * 0.6
    assert pages.split_plan_data(full) == (bootstrap, assets)


@pytest.mark.parametrize("plan_id", ["../outside", "/tmp/outside", "", "UPPER", None])
def test_plan_split_rejects_unsafe_asset_names(plan_id: str | None) -> None:
    dataset = {"reference": {"plans": [{"plan_id": plan_id}]}, "metadata": {}}
    with pytest.raises(ValueError, match="Invalid reference plan id"):
        pages.split_plan_data(dataset)


def test_plan_assets_do_not_change_with_a_ui_only_source_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = LabApplication(pages.REFERENCE_PATH)
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    first, first_assets = pages.split_plan_data(pages.build_dataset(application))
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    second, second_assets = pages.split_plan_data(pages.build_dataset(application))
    assert first["metadata"] != second["metadata"]
    assert first["reference"] == second["reference"]
    assert first_assets == second_assets


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
    assert (
        json.loads((output / "pages-data.json").read_text(encoding="utf-8"))
        == (pages.split_plan_data(dataset)[0])
    )
    assert (output / pages.ARTIFACT_MARKER).read_text(encoding="utf-8") == (
        pages.ARTIFACT_MARKER_CONTENT
    )
