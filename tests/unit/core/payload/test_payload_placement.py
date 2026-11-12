"""The one installer of a package: plan every placement, then write.

Identical bytes already there cost nothing. An absent file is copied with its
sidecar. The same path with other bytes is a conflict named with both digests,
refused before anything is written. A station row is merged into its registry;
the same id with other values is a conflict.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.core.payload.index import PayloadFile, PayloadStation
from hydromodpy.core.payload.install import (
    PayloadConflictError,
    plan_files,
    plan_stations,
    refuse_conflicts,
)


def _file(path: Path, payload: bytes, dest: str) -> PayloadFile:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return PayloadFile(dest=dest, size=len(payload), sha256=hashlib.sha256(payload).hexdigest())


def test_a_project_file_lands_under_the_project_and_nothing_escapes(tmp_path) -> None:
    project = tmp_path / "ws" / "projects" / "nancon"
    item = PayloadFile(dest="step1.toml", size=1, sha256="0" * 64, root="project")

    (placement,) = plan_files({"workspace": tmp_path / "ws", "project": project}, [item])

    assert placement.path == (project / "step1.toml").resolve()
    escaping = PayloadFile(dest="../../etc/passwd", size=1, sha256="0" * 64)
    with pytest.raises(DataRequestError, match="outside"):
        plan_files({"workspace": tmp_path / "ws"}, [escaping])


def _registry(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_station_row_with_other_values_is_a_conflict(tmp_path) -> None:
    registry = tmp_path / "data" / "hydrometry" / "hydrometry_custom_LOC.csv"
    _registry(registry, "id,x,y\nNANCON,1,1\n")
    moved = PayloadStation(
        dest="data/hydrometry/hydrometry_custom_LOC.csv",
        row=(("id", "NANCON"), ("x", "389285.9"), ("y", "6816518.7")),
    )

    merges = plan_stations(tmp_path, [moved])

    with pytest.raises(PayloadConflictError, match="station NANCON"):
        refuse_conflicts([], merges, advice="")
    assert registry.read_text(encoding="utf-8") == "id,x,y\nNANCON,1,1\n"
