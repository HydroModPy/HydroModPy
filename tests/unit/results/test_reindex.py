"""The index is rebuildable: what is on disk is what gets indexed, twice the same."""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

import hydromodpy.results.catalog.reindex as reindex_module
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import catalog_path_for, runs_dir_for
from hydromodpy.core.tracking import TrackedFileEntry
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.reindex import rebuild_index
from hydromodpy.results.manifest import RUN_MANIFEST_FILENAME, is_sealed
from hydromodpy.results.storage.contract import (
    RUN_CONFIG_FILENAME,
    RUN_TRASH_FILENAME,
    TABLES_DIRNAME,
)

CATCHMENT = {
    "catch_area": "29.7",
    "x_outlet": "301.5",
    "y_outlet": "402.5",
    "dem_res": "5.0",
    "nrow": "120",
    "ncol": "240",
    "crs_proj": "EPSG:2154",
    "epsg": "2154",
}


def _seal_run(catalog: Catalog, name: str, *, inputs: Sequence[TrackedFileEntry] = ()) -> str:
    """Register, populate and finalise one run; return its sim_id."""
    sid = str(uuid.uuid4())
    registration = catalog.register_simulation(
        sid,
        project="demo",
        solver="modflow6",
        name=name,
        flow_regime="transient",
        n_cells=64,
        n_layers=2,
        n_timesteps=3,
        bbox=[0.0, 0.0, 100.0, 100.0],
        crs="EPSG:2154",
        config={"flow": {"hk": 1e-5}},
        study_area_name="Demo",
    )
    if registration.zarr is not None:
        registration.zarr.close()
    catalog.write_parameters(
        sid,
        [
            {"param_name": "hk", "value": 1e-5, "unit": "m/s"},
            {"param_name": "sy", "value": 0.02, "unit": "1", "zone_id": "upper"},
        ],
    )
    catalog.write_metric(sid, "__outlet__", "nse", 0.66, variable="discharge", n_samples=365)
    catalog.write_geographic_metadata(sid, dict(CATCHMENT))
    catalog.write_geographic_feature(sid, "watershed", _watershed())
    catalog.write_run_environment(sid, solver_name="modflow6")
    if inputs:
        catalog.register_tracked_files(sid, list(inputs))
    (catalog.run_dir_for(sid) / RUN_CONFIG_FILENAME).write_text("[flow]\nhk = 1e-5\n")
    catalog.finalize(sid, status="completed", duration_s=12.0)
    return sid


def _watershed() -> gpd.GeoDataFrame:
    polygon = Polygon([(0, 0), (0, 100), (100, 100), (100, 0)])
    return gpd.GeoDataFrame({"name": ["demo"]}, geometry=[polygon], crs="EPSG:2154")


def _index_content(project_root, tables) -> dict[str, list[tuple]]:
    """Return the rows of ``tables``, sorted, as read from the project index."""
    with Catalog(project_root, read_only=True) as catalog:
        return {
            table: sorted(str(row) for row in catalog.backend.fetch_all(f"SELECT * FROM {table}"))
            for table in tables
        }


@pytest.fixture
def project(tmp_path):
    """A project holding two sealed runs."""
    root = tmp_path / "demo"
    with Catalog(root) as catalog:
        _seal_run(catalog, "alpha")
        _seal_run(catalog, "beta")
    return root


# -- invariant 1: the disk is the set of runs -------------------------------


def test_every_sealed_run_on_disk_is_indexed(project):
    catalog_path_for(project).unlink()

    report = rebuild_index(project)

    sealed = {p.name for p in runs_dir_for(project).iterdir() if is_sealed(p)}
    with Catalog(project, read_only=True) as catalog:
        indexed = set(catalog.list_simulations()["name"])
    assert sealed == indexed == set(report.indexed)


def test_a_run_missing_from_the_index_comes_back(project):
    with Catalog(project) as catalog:
        catalog.backend.execute("DELETE FROM simulations WHERE name = 'beta'")
        assert set(catalog.list_simulations()["name"]) == {"alpha"}

    rebuild_index(project)

    with Catalog(project, read_only=True) as catalog:
        assert set(catalog.list_simulations()["name"]) == {"alpha", "beta"}


def test_a_run_deleted_from_disk_leaves_the_index(project):
    import shutil

    shutil.rmtree(runs_dir_for(project) / "beta")

    report = rebuild_index(project)

    assert report.indexed == ("alpha",)
    with Catalog(project, read_only=True) as catalog:
        assert set(catalog.list_simulations()["name"]) == {"alpha"}


def test_an_unsealed_run_is_reported_and_left_out(project):
    (runs_dir_for(project) / "beta" / RUN_MANIFEST_FILENAME).unlink()

    report = rebuild_index(project)

    assert report.indexed == ("alpha",)
    assert [item.run for item in report.skipped] == ["beta"]
    assert RUN_MANIFEST_FILENAME in report.skipped[0].reason


def test_a_sealed_run_without_its_index_row_is_reported(project):
    (runs_dir_for(project) / "beta" / TABLES_DIRNAME / "simulation.parquet").unlink()

    report = rebuild_index(project)

    assert report.indexed == ("alpha",)
    assert "simulation.parquet" in report.skipped[0].reason


def test_a_manifest_naming_another_run_is_refused(project):
    beta = runs_dir_for(project) / "beta"
    alpha_manifest = (runs_dir_for(project) / "alpha" / RUN_MANIFEST_FILENAME).read_text()
    (beta / RUN_MANIFEST_FILENAME).write_text(alpha_manifest)

    report = rebuild_index(project)

    assert report.indexed == ("alpha",)
    assert "two identities" in report.skipped[0].reason


# -- invariant 2: rebuilding twice describes the same project ---------------


def test_two_rebuilds_produce_the_same_index(project):
    tables = (
        "simulations",
        "parameters",
        "metrics",
        "provenance",
        "geographic_metadata",
        "geographic_features",
        "runs_environment",
    )
    rebuild_index(project)
    first = _index_content(project, tables)

    rebuild_index(project)

    assert _index_content(project, tables) == first


def test_rebuilding_a_live_index_does_not_duplicate_rows(project):
    with Catalog(project, read_only=True) as catalog:
        before = len(catalog.list_simulations())

    rebuild_index(project)

    with Catalog(project, read_only=True) as catalog:
        assert len(catalog.list_simulations()) == before


# -- what comes back --------------------------------------------------------


def test_the_rebuild_restores_what_execution_reads_back(project):
    catalog_path_for(project).unlink()

    rebuild_index(project)

    with Catalog(project, read_only=True) as catalog:
        sid = catalog.resolve("alpha")
        run = catalog[sid]
        assert run.status == "completed"
        assert run.n_cells == 64
        assert catalog.read_geographic_metadata(sid) == CATCHMENT
        assert catalog.list_geographic_features(sid) == ["watershed"]
        assert len(catalog.read_geographic_feature(sid, "watershed")) == 1
        params = {
            row[0]: row[1]
            for row in catalog.backend.fetch_all(
                "SELECT param_name, value FROM parameters WHERE sim_id = ?", [sid]
            )
        }
        assert params == {"hk": pytest.approx(1e-5), "sy": pytest.approx(0.02)}
        metric = catalog.backend.fetch_one(
            "SELECT metric_name, value FROM metrics WHERE sim_id = ?", [sid]
        )
        assert metric[0] == "nse"
        environment = catalog.backend.fetch_one(
            "SELECT solver_name FROM runs_environment WHERE sim_id = ?", [sid]
        )
        assert environment[0] == "modflow6"


def test_the_run_configuration_stays_readable(project):
    catalog_path_for(project).unlink()

    rebuild_index(project)

    with Catalog(project, read_only=True) as catalog:
        sid = catalog.resolve("alpha")
        assert catalog[sid].config_snapshot == {"flow": {"hk": 1e-5}}


def test_the_directory_names_the_run(project):
    (runs_dir_for(project) / "alpha").rename(runs_dir_for(project) / "alpha_renamed")
    catalog_path_for(project).unlink()

    rebuild_index(project)

    with Catalog(project, read_only=True) as catalog:
        row = catalog.backend.fetch_one(
            "SELECT name, storage_basename, zarr_path FROM simulations WHERE name_stem = ?",
            ["alpha_renamed"],
        )
        assert row[0] == "alpha_renamed"
        assert row[1] == "alpha_renamed"
        assert row[2] == "runs/alpha_renamed/fields.zarr"
        assert catalog.fields_path_for(catalog.resolve("alpha_renamed")).is_dir()


def test_a_versioned_directory_keeps_its_version(tmp_path):
    root = tmp_path / "demo"
    with Catalog(root) as catalog:
        _seal_run(catalog, "alpha")
        _seal_run(catalog, "alpha")
    catalog_path_for(root).unlink()

    rebuild_index(root)

    with Catalog(root, read_only=True) as catalog:
        rows = dict(catalog.backend.fetch_all("SELECT name, version_int FROM simulations"))
        assert rows == {"alpha": 1, "alpha.v2": 2}


def _name_and_status(catalog) -> list[tuple]:
    """Return ``(name, original_name, status)`` per run, sorted."""
    return sorted(
        catalog.backend.fetch_all(
            "SELECT COALESCE(name, ''), COALESCE(original_name, ''), st.code "
            "FROM simulations s JOIN statuses st ON s.status_id = st.id"
        )
    )


def test_a_trashed_run_stays_trashed_across_a_rebuild(project):
    with Catalog(project) as catalog:
        sid = catalog.resolve("beta")
        catalog.trash(sid)
        assert (catalog.run_dir_for(sid) / RUN_TRASH_FILENAME).is_file()
        before = _name_and_status(catalog)
    catalog_path_for(project).unlink()

    report = rebuild_index(project)

    assert set(report.indexed) == {"alpha", "beta"}
    with Catalog(project, read_only=True) as catalog:
        assert _name_and_status(catalog) == before
        assert [entry["original_name"] for entry in catalog.list_trash()] == ["beta"]


def test_a_restored_run_comes_back_live_across_a_rebuild(project):
    with Catalog(project) as catalog:
        sid = catalog.resolve("beta")
        catalog.trash(sid)
        catalog.restore(sid)
        assert not (catalog.run_dir_for(sid) / RUN_TRASH_FILENAME).exists()
    catalog_path_for(project).unlink()

    rebuild_index(project)

    with Catalog(project, read_only=True) as catalog:
        assert _name_and_status(catalog) == [
            ("alpha", "", "completed"),
            ("beta", "", "completed"),
        ]
        assert catalog.list_trash() == []


def test_a_trashed_failed_run_keeps_the_status_it_must_be_restored_to(project):
    with Catalog(project) as catalog:
        sid = catalog.resolve("beta")
        catalog.finalize(sid, status="failed")
        catalog.trash(sid)
    catalog_path_for(project).unlink()

    rebuild_index(project)

    with Catalog(project) as catalog:
        restored = catalog.restore(catalog.list_trash()[0]["sim_id"])
        status = catalog.backend.fetch_one(
            "SELECT st.code FROM simulations s JOIN statuses st ON s.status_id = st.id "
            "WHERE name = ?",
            [restored],
        )
        assert status[0] == "failed"


def test_a_malformed_trash_marker_is_reported_not_ignored(project):
    (runs_dir_for(project) / "beta" / RUN_TRASH_FILENAME).write_text("[]", encoding="utf-8")
    catalog_path_for(project).unlink()

    report = rebuild_index(project)

    assert report.indexed == ("alpha",)
    assert [entry.run for entry in report.skipped] == ["beta"]


# -- the live index survives ------------------------------------------------
#
# The publish is one atomic rename, whatever the platform calls it: the index
# path never goes missing, never holds half a database, and a reader that was
# reading keeps reading valid data across it.


def test_the_previous_index_survives_a_failed_rebuild(project, monkeypatch):
    index_before = catalog_path_for(project).read_bytes()

    def _boom(*_args, **_kwargs):
        raise OSError("publish refused")

    monkeypatch.setattr(reindex_module, "rename_over_open_file", _boom)
    with pytest.raises(OSError, match="publish refused") as refused:
        rebuild_index(project)

    assert "still readable" in str(refused.value)
    assert catalog_path_for(project).read_bytes() == index_before
    leftovers = list(catalog_path_for(project).parent.glob("*.rebuild-*"))
    assert leftovers == []


def test_an_interrupt_before_the_publish_leaves_the_old_index(project, monkeypatch):
    """A rebuild killed once the staging database is full still has an index.

    That is the window the publish closes: between the last row written and
    the swap, the project is still described by the index it already had.
    """
    index_path = catalog_path_for(project)
    index_before = index_path.read_bytes()

    def _interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(reindex_module, "_publish", _interrupted)
    with pytest.raises(KeyboardInterrupt):
        rebuild_index(project)

    assert index_path.read_bytes() == index_before
    assert list(index_path.parent.glob("*.rebuild-*")) == []
    with Catalog(project, read_only=True) as catalog:
        assert len(catalog.list_simulations()) == 2


def test_the_rebuild_leaves_no_staging_file(project):
    rebuild_index(project)

    assert list(catalog_path_for(project).parent.glob("*.rebuild-*")) == []


def test_the_index_is_replaced_in_one_step(project, monkeypatch):
    """No window: the index name is never freed, nor written into in place.

    A publish that unlinks before it moves leaves the project index-less for
    an instant; one that copies into the live file leaves it half-written for
    much longer. The staged database must arrive whole, under its own file,
    without the name it takes ever being removed.
    """
    index_path = catalog_path_for(project)
    index_before = index_path.read_bytes()
    file_id_before = index_path.stat().st_ino
    freed: list[Path] = []
    swapped: dict[str, bytes] = {}
    publish = reindex_module._publish
    path_unlink = Path.unlink
    os_unlink = os.unlink

    def _record_path(self: Path, missing_ok: bool = False) -> None:
        freed.append(Path(self))
        path_unlink(self, missing_ok=missing_ok)

    def _record_os(path: Any, *, dir_fd: int | None = None) -> None:
        freed.append(Path(path))
        os_unlink(path, dir_fd=dir_fd)

    def _watched(staging: Path, target: Path) -> None:
        swapped["staging"] = staging.read_bytes()
        swapped["target"] = target.read_bytes()
        publish(staging, target)

    monkeypatch.setattr(Path, "unlink", _record_path)
    monkeypatch.setattr(os, "unlink", _record_os)
    monkeypatch.setattr(os, "remove", _record_os)
    monkeypatch.setattr(reindex_module, "_publish", _watched)

    rebuild_index(project)

    assert swapped["target"] == index_before
    assert index_path not in freed
    assert index_path.read_bytes() == swapped["staging"]
    assert index_path.stat().st_ino != file_id_before


def test_a_reader_keeps_reading_across_the_swap(project, monkeypatch):
    """An open reader is not asked to close: it keeps reading valid data.

    The reader is made to query from inside the publish, so it is provably
    holding the index file at the instant of the swap rather than by timing.
    """
    reader = Catalog(project, read_only=True)
    publish = reindex_module._publish

    def _publish_under_a_live_reader(staging: Path, target: Path) -> None:
        reader.list_simulations()
        publish(staging, target)

    monkeypatch.setattr(reindex_module, "_publish", _publish_under_a_live_reader)
    try:
        before = sorted(reader.list_simulations()["name"])
        assert before == ["alpha", "beta"]

        rebuild_index(project)

        assert sorted(reader.list_simulations()["name"]) == before
        assert reader.read_geographic_metadata(reader.resolve("alpha")) == CATCHMENT
    finally:
        reader.close()

    with Catalog(project, read_only=True) as reopened:
        assert sorted(reopened.list_simulations()["name"]) == before


def test_the_rename_over_an_open_index_is_what_publishes(project, monkeypatch):
    """The publish is exercised with a handle really on the file it replaces.

    A rebuild with nothing open never reaches the rename that gives Windows
    the POSIX semantics: ``os.replace`` alone is refused as soon as another
    handle is on the index, and only then does the fallback run. So a reader
    is opened first, kept reading across the swap, and the index it names
    must still end up being a different file afterwards.
    """
    index_path = catalog_path_for(project)
    file_id_before = index_path.stat().st_ino
    published: list[str] = []
    rename = reindex_module.rename_over_open_file

    def _watched(source: Path, target: Path) -> None:
        rename(source, target)
        published.append(Path(target).name)

    monkeypatch.setattr(reindex_module, "rename_over_open_file", _watched)

    reader = Catalog(project, read_only=True)
    try:
        before = sorted(reader.list_simulations()["name"])
        assert before == ["alpha", "beta"]

        rebuild_index(project)

        assert published == [index_path.name]
        assert index_path.stat().st_ino != file_id_before
        assert sorted(reader.list_simulations()["name"]) == before
    finally:
        reader.close()

    with Catalog(project, read_only=True) as reopened:
        assert sorted(reopened.list_simulations()["name"]) == before


def test_a_write_ahead_log_that_will_not_delete_does_not_undo_the_rebuild(
    project, monkeypatch, rebuild_warnings
):
    """Past the swap there is nothing left to fail: the leftover is reported.

    The journal of the replaced index is deleted after the publish, and on
    Windows a reader still holding it makes that delete raise. The rebuild is
    finished by then, so the file is named out loud and the report stands.
    """
    index_path = catalog_path_for(project)
    wal_path = index_path.with_name(f"{index_path.name}.wal")
    unlink = Path.unlink

    def _refuse_the_journal(self: Path, missing_ok: bool = False) -> None:
        if Path(self) == wal_path:
            raise PermissionError("the write-ahead log is open in another process")
        unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", _refuse_the_journal)

    report = rebuild_index(project)

    assert sorted(report.indexed) == ["alpha", "beta"]
    assert _said(rebuild_warnings, "write-ahead log") != []
    with Catalog(project, read_only=True) as reopened:
        assert sorted(reopened.list_simulations()["name"]) == ["alpha", "beta"]


# -- the inputs block: present, empty, or absent ----------------------------


@pytest.fixture
def rebuild_warnings(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Capture what a rebuild says out loud.

    The ``hydromodpy`` node stops propagating as soon as a ``LogManager``
    exists, and ``caplog`` only sees what reaches the root, so propagation is
    restored for the duration of the test.
    """
    parent = get_logger("hydromodpy")
    propagate = parent.propagate
    parent.propagate = True
    caplog.set_level(logging.WARNING, logger="hydromodpy")
    try:
        yield caplog
    finally:
        parent.propagate = propagate


def _dem_entry(tmp_path: Path) -> TrackedFileEntry:
    """One tracked input file, as the setup step declares it at run time."""
    dem = tmp_path / "inputs" / "dem.tif"
    dem.parent.mkdir(parents=True, exist_ok=True)
    dem.write_bytes(b"elevation")
    return TrackedFileEntry(
        role="dem",
        category="raster",
        original_path="inputs/dem.tif",
        canonical_path=dem,
        portable=True,
    )


def _tracked_files(project_root: Path, sid: str) -> list[dict[str, Any]]:
    """Return the ``tracked_files`` rows the index holds for one run."""
    with Catalog(project_root, read_only=True) as catalog:
        return catalog.list_tracked_files(sid).to_dict(orient="records")


def _edit_manifest(run_dir: Path, edit: Callable[[dict[str, Any]], object]) -> None:
    """Rewrite the manifest of a run, the way an older seal would have left it."""
    path = run_dir / RUN_MANIFEST_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    edit(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _said(caplog: pytest.LogCaptureFixture, needle: str) -> list[str]:
    """Return the captured messages mentioning ``needle``."""
    return [record.getMessage() for record in caplog.records if needle in record.getMessage()]


def test_a_declared_input_comes_back_with_its_digest(tmp_path, rebuild_warnings):
    """``tracked_files`` comes back from the manifest, digests included."""
    root = tmp_path / "demo"
    with Catalog(root) as catalog:
        sid = _seal_run(catalog, "alpha", inputs=[_dem_entry(tmp_path)])
        expected = catalog.list_tracked_files(sid).to_dict(orient="records")
    catalog_path_for(root).unlink()

    rebuild_index(root)

    assert len(expected) == 1
    assert _tracked_files(root, sid) == expected
    assert _said(rebuild_warnings, "inputs block") == []


def test_a_run_declaring_no_input_indexes_none_and_stays_silent(project, rebuild_warnings):
    """An empty block is an answer: this run was fed no declared file."""
    with Catalog(project, read_only=True) as catalog:
        sid = catalog.resolve("beta")
    catalog_path_for(project).unlink()

    report = rebuild_index(project)

    assert set(report.indexed) == {"alpha", "beta"}
    assert _tracked_files(project, sid) == []
    assert _said(rebuild_warnings, "inputs block") == []


def test_a_manifest_without_the_inputs_block_says_the_provenance_is_unknown(
    project, rebuild_warnings
):
    """Absence is not emptiness: a seal carrying no block must be heard."""
    _edit_manifest(runs_dir_for(project) / "beta", lambda payload: payload.pop("inputs"))
    with Catalog(project, read_only=True) as catalog:
        sid = catalog.resolve("beta")
    catalog_path_for(project).unlink()

    report = rebuild_index(project)

    assert set(report.indexed) == {"alpha", "beta"}
    assert _tracked_files(project, sid) == []
    (message,) = _said(rebuild_warnings, "inputs block")
    assert "beta" in message
    assert "unknown, not empty" in message
