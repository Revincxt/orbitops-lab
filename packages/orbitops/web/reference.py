"""Read-only reference artifacts, kept outside the single-satellite solver contract."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ATTITUDE_DISPLAY = {
    "rendering": (
        "Source Euler replay with display-only Earthward reversal and a 29.5-degree "
        "off-nadir limit; no target-lock correction."
    ),
    "sample_interpolation": (
        "Raw samples use quaternion SLERP; "
        "Earthward horizon crossings use continuous axis/twist arcs."
    ),
    "display_correction": (
        "Reverse skyward boresights by 180 degrees about body X, then limit off-nadir "
        "deflection to 29.5 degrees with a minimal inward rotation; preserve raw Euler arrays."
    ),
    "max_display_off_nadir_deg": 29.5,
    "display_transitions": (
        "Angle-timed preparation/recovery in idle gaps, minimum 30 simulation seconds, "
        "nominal 0.5 degrees per simulation second; short gaps retarget directly. "
        "Deterministic replay-time interpolation, not certified spacecraft dynamics."
    ),
    "fixed_frame_transform": (
        "Source orbit anchors and constant Earth rotation; illustrative, not Orekit/IERS."
    ),
}


class ReferenceArchive:
    """Serve a pinned, integrity-checked EOS-Bench snapshot without solving it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] | None = None
        if path.is_file():
            raw = path.read_bytes()
            checksum = path.with_suffix(".sha256")
            if (
                not checksum.is_file()
                or hashlib.sha256(raw).hexdigest() != checksum.read_text().strip()
            ):
                raise ValueError("reference archive integrity check failed")
            data = json.loads(raw)
            if data.get("schema_version") != "eos-reference-1":
                raise ValueError("unsupported reference archive schema")
            self.data = data

    def export(self) -> dict[str, Any] | None:
        """Copy data for a static build; no run is recomputed or re-labelled."""
        data = deepcopy(self.data)
        if data is not None:
            data["replay"]["attitude"].update(ATTITUDE_DISPLAY)
        return data

    def orbit_chunk(self, filename: str) -> bytes:
        """Read only manifest-listed files; validate content before serving/building."""
        entries = self.data["replay"].get("ephemeris", {}).get("chunks", []) if self.data else []
        entry = next((e for e in entries if e["filename"] == filename), None)
        if entry is None or Path(filename).name != filename:
            raise ValueError("unknown orbit chunk")
        raw = (self.path.parent / "orbits" / filename).read_bytes()
        if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("orbit chunk integrity check failed")
        return raw
