"""A run states the licence its inputs allow, and says once what it lacks.

The Zarr attributes and the Parquet footers carry the roll-up of the inputs'
sidecars, derived from the facts of the run. The warning about a missing
identity or licence is said once per workspace, not once per run.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import pytest
import zarr

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.core.tracking.input_file import TrackedFileEntry
from hydromodpy.core.workspace.workspace_toml import write_workspace_toml
from hydromodpy.results.storage.contract import (
    PARQUET_FILE_SUFFIX,
    RUN_CONFIG_FILENAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.licence import LicenceMember, TrackedPath, run_licence
from hydromodpy.results.storage.parquet_io import read_kv_metadata
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import IDENTITY_NOTICE_FILENAME, seal_completed
from tests._helpers.run_stores import open_run_store


def _input(root: Path, name: str, **sidecar: object) -> Path:
    path = root / "data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(name.encode())
    if sidecar:
        path.with_name(path.name + ".json").write_text(json.dumps(sidecar), encoding="utf-8")
    return path


def _tracked(paths: list[Path]) -> list[TrackedFileEntry]:
    return [
        TrackedFileEntry(
            role=path.stem,
            category="data",
            original_path=str(path),
            canonical_path=path,
            portable=True,
        )
        for path in paths
    ]


def _open(project: Path, inputs: list[Path], name: str = "run") -> RunStore:
    store = open_run_store(project, name, n_cells=4, crs_wkt="EPSG:2154", crs_epsg=2154)
    store.register_tracked_files(store.sim_id, _tracked(inputs))
    return store


def _seal(store: RunStore) -> dict:
    (store.run_dir / RUN_CONFIG_FILENAME).write_text("[flow]\nhk = 1e-5\n", encoding="utf-8")
    seal_completed(store)
    return dict(zarr.open_group(str(store.fields_path), mode="r").attrs)


def test_inputs_with_a_stated_licence_give_it_to_the_run(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    dem = _input(project, "dem.tif", source="ign_geoplateforme_dem", license="etalab-2.0")
    geology = _input(project, "geology.gpkg", source="brgm_1m", license=None)
    store = _open(project, [dem, geology])
    assert store.licence() == "etalab-2.0"
    index = pd.date_range("2020-01-01", periods=2, freq="D")
    store.write_timeseries(store.sim_id, "P01", "head", pd.Series([1.0, 2.0], index=index))

    attrs = _seal(store)

    footer = read_kv_metadata(store.tables_dir / f"timeseries{PARQUET_FILE_SUFFIX}")
    assert attrs["license"] == "etalab-2.0"
    assert footer["license"] == "etalab-2.0"
    assert footer["hmp.identity"]


def test_one_unknown_input_leaves_the_run_undetermined(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    dem = _input(project, "dem.tif", source="ign_geoplateforme_dem", license="etalab-2.0")
    recharge = _input(project, "recharge.csv", source="custom", license=UNDETERMINED_LICENSE)
    with _open(project, [dem, recharge]) as store:
        assert store.licence() == UNDETERMINED_LICENSE


def test_a_run_with_no_recorded_input_is_undetermined(tmp_path: Path) -> None:
    with _open(tmp_path / "demo", []) as store:
        assert store.licence() == UNDETERMINED_LICENSE
    assert run_licence([], [], tmp_path) == UNDETERMINED_LICENSE


def test_a_custom_record_counts_through_the_tracked_file_that_holds_it(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    series = _input(project, "recharge.csv", source="custom", license="etalab-2.0")
    from hydromodpy.results.storage.digests import sha256_streaming

    digest = sha256_streaming(series)
    members = [LicenceMember("custom", digest)]
    tracked = [TrackedPath(str(series), digest)]
    assert run_licence(members, tracked, project) == "etalab-2.0"
    assert run_licence([LicenceMember("custom", "ff" * 32)], tracked, project) == (
        UNDETERMINED_LICENSE
    )


def test_the_workspace_toml_identity_is_stamped(tmp_path: Path) -> None:
    write_workspace_toml(
        tmp_path, project_name="ws", creator_name="Ada Lovelace", creator_email="a@b.c"
    )
    toml_path = tmp_path / "workspace.toml"
    toml_path.write_text(
        toml_path.read_text().replace(
            'creator_institution = ""', 'creator_institution = "Univ Rennes"'
        )
    )
    project = tmp_path / "projects" / "demo"
    project.mkdir(parents=True)

    attrs = _seal(_open(project, []))

    assert attrs["creator_name"] == "Ada Lovelace"
    assert attrs["creator_institution"] == "Univ Rennes"


def test_the_unix_account_is_never_the_creator(tmp_path: Path) -> None:
    attrs = _seal(_open(tmp_path / "demo", []))
    assert "creator_name" not in attrs


def _sealed_without(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if "sealed without" in r.getMessage() and r.levelno == level
    ]


def test_the_warning_is_said_once_per_workspace(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="hydromodpy")
    project = tmp_path / "demo"
    for index in range(3):
        _seal(_open(project, [], name=f"run_{index}"))
    warnings = _sealed_without(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert len(_sealed_without(caplog, logging.INFO)) == 2
    (message,) = warnings
    assert message.startswith(
        "Runs of this workspace are sealed without creator_name, creator_institution "
        "and a known licence. "
    )
    assert 'Add creator_name = "..." and creator_institution = "..." under [workspace]' in message
    assert "workspace.toml" in message
    assert "'license' key of each input sidecar" in message
    assert message.count(". ") == 1
    assert "--verbose" not in message


def test_a_later_process_of_the_same_workspace_is_not_warned_again(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Each ``hmp run`` is a new process: the fact lives on disk, not in memory."""
    caplog.set_level(logging.INFO, logger="hydromodpy")
    project = tmp_path / "demo"
    _seal(_open(project, [], name="first"))
    marker = project / ".hmp" / IDENTITY_NOTICE_FILENAME
    assert json.loads(marker.read_text(encoding="utf-8"))["missing"] == [
        "a known licence",
        "creator_institution",
        "creator_name",
    ]
    caplog.clear()
    _seal(_open(project, [], name="second"))
    assert _sealed_without(caplog, logging.WARNING) == []
    assert (project / "runs" / "second" / TABLES_DIRNAME).is_dir()
