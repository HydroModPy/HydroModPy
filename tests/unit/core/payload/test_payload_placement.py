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
    write_file,
    write_stations,
)


def _file(path: Path, payload: bytes, dest: str) -> PayloadFile:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return PayloadFile(dest=dest, size=len(payload), sha256=hashlib.sha256(payload).hexdigest())


def test_identical_bytes_cost_nothing_and_an_absent_file_comes_with_its_sidecar(tmp_path) -> None:
    workspace = tmp_path / "ws"
    blob = tmp_path / "blob.csv"
    item = _file(blob, b"datetime,value\n", "data/hydrometry/a.csv")
    sidecar = tmp_path / "sidecar.json"
    sidecar.write_text('{"source": "file"}', encoding="utf-8")

    (first,) = plan_files({"workspace": workspace}, [item])
    assert first.status == "absent"
    write_file(first, blob, sidecar=sidecar)
    (second,) = plan_files({"workspace": workspace}, [item])

    target = workspace / "data" / "hydrometry" / "a.csv"
    assert target.read_bytes() == b"datetime,value\n"
    assert (target.parent / "a.csv.json").read_text(encoding="utf-8") == '{"source": "file"}'
    assert second.status == "unchanged"
    assert not list(target.parent.glob(".*partial"))


def test_the_same_path_with_other_bytes_is_refused_with_both_digests(tmp_path) -> None:
    workspace = tmp_path / "ws"
    theirs = workspace / "data" / "dem" / "dem.tif"
    theirs.parent.mkdir(parents=True)
    theirs.write_bytes(b"their dem")
    item = _file(tmp_path / "blob.tif", b"our dem", "data/dem/dem.tif")

    placements = plan_files({"workspace": workspace}, [item])
    with pytest.raises(PayloadConflictError) as refused:
        refuse_conflicts(placements, advice="Rename one of them.")

    message = str(refused.value)
    assert "data/dem/dem.tif" in message
    assert hashlib.sha256(b"their dem").hexdigest() in message
    assert item.sha256 in message
    assert "nothing written" in message
    assert theirs.read_bytes() == b"their dem"


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


def test_station_rows_merge_into_their_registry(tmp_path) -> None:
    registry = tmp_path / "data" / "hydrometry" / "hydrometry_custom_LOC.csv"
    _registry(registry, "id,x,y\nEXAMPLE,1,2\nNANCON,389285.9,6816518.7\n")
    same = PayloadStation(
        dest="data/hydrometry/hydrometry_custom_LOC.csv",
        row=(("id", "NANCON"), ("x", "389285.9"), ("y", "6816518.7")),
    )
    new = PayloadStation(
        dest="data/hydrometry/hydrometry_custom_LOC.csv",
        row=(("id", "OTHER"), ("x", "1"), ("y", "3")),
    )

    merges = plan_stations(tmp_path, [same, new])
    refuse_conflicts([], merges, advice="")
    written = write_stations(merges)

    assert written == ["data/hydrometry/hydrometry_custom_LOC.csv (station OTHER)"]
    assert registry.read_text(encoding="utf-8").splitlines() == [
        "id,x,y",
        "EXAMPLE,1,2",
        "NANCON,389285.9,6816518.7",
        "OTHER,1,3",
    ]


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
