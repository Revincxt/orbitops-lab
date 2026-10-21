import re
import tomllib
from pathlib import Path

from orbitops import __version__
from orbitops.cli import app

ROOT = Path(__file__).parents[2]


def test_project_description_and_release_metadata_are_consistent() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    citation = dict(
        re.findall(
            r'^(title|abstract|version): "?([^"\n]+)"?$',
            (ROOT / "CITATION.cff").read_text(),
            re.MULTILINE,
        )
    )
    readme = (ROOT / "README.md").read_text()

    assert project["version"] == __version__ == citation["version"]
    assert project["description"] == citation["abstract"] == app.info.help
    assert project["description"] in readme
    assert f"# {citation['title']}" in readme


def test_project_overview_describes_capabilities_without_display_internals() -> None:
    overview = (ROOT / "README.md").read_text().split("## Overview", 1)[1].split("## ", 1)[0]
    assert all(
        term not in overview.lower()
        for term in ["off-nadir", "earthward", "slerp", "retarget", "29.5"]
    )
