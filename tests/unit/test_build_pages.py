from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import build_pages as pages


def test_pages_budget_and_omission_profiles_are_explicit() -> None:
    assert pages._evaluation_budget(3, stochastic=True) == 250
    assert pages._evaluation_budget(10, stochastic=True) == 120
    assert pages._evaluation_budget(18, stochastic=True) == 75
    assert pages._evaluation_budget(30, stochastic=True) == 40
    assert pages._evaluation_budget(30, stochastic=False) == 250

    capability = pages._omission_reason(
        {"task_count": 18},
        {"solver_name": "branch-and-bound", "max_tasks": 16},
    )
    pages_profile = pages._omission_reason(
        {"task_count": 10},
        {"solver_name": "brute-force", "max_tasks": 10},
    )
    representative = pages._omission_reason(
        {"task_count": 30},
        {"solver_name": "greedy-value", "max_tasks": None},
    )

    assert capability == {
        "code": "solver_capability_limit",
        "reason": "Method supports at most 16 tasks.",
    }
    assert pages_profile is not None
    assert pages_profile["code"] == "pages_exact_profile_limit"
    assert representative is not None
    assert representative["code"] == "pages_representative_method_set"


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
        "scenarios": {"scenarios": []},
        "solvers": {"solvers": []},
        "runs": {},
        "omissions": {},
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
