"""The index is rebuildable: what is on disk is what gets indexed, twice the same."""

from __future__ import annotations

import uuid

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from hydromodpy.core.state.paths import catalog_path_for, runs_dir_for
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


def _seal_run(catalog: Catalog, name: str) -> str:
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


def test_the_previous_index_survives_a_failed_rebuild(project, monkeypatch):
    import hydromodpy.results.catalog.reindex as reindex_module

    index_before = catalog_path_for(project).read_bytes()

    def _boom(*_args, **_kwargs):
        raise OSError("publish refused")

    monkeypatch.setattr(reindex_module.os, "replace", _boom)
    with pytest.raises(OSError, match="publish refused"):
        rebuild_index(project)

    assert catalog_path_for(project).read_bytes() == index_before
    leftovers = list(catalog_path_for(project).parent.glob("*.rebuild-*"))
    assert leftovers == []


def test_the_rebuild_leaves_no_staging_file(project):
    rebuild_index(project)

    assert list(catalog_path_for(project).parent.glob("*.rebuild-*")) == []


def test_a_reader_keeps_reading_across_the_swap(project):
    reader = Catalog(project, read_only=True)
    try:
        assert len(reader.list_simulations()) == 2

        rebuild_index(project)

        assert len(reader.list_simulations()) == 2
    finally:
        reader.close()


def test_the_rebuild_restores_the_input_provenance(tmp_path):
    """``tracked_files`` comes back from the manifest, digests included."""
    from hydromodpy.core.tracking import TrackedFileEntry

    root = tmp_path / "demo"
    dem = tmp_path / "inputs" / "dem.tif"
    dem.parent.mkdir(parents=True)
    dem.write_bytes(b"elevation")
    with Catalog(root) as catalog:
        sid = str(uuid.uuid4())
        registration = catalog.register_simulation(
            sid, project="demo", solver="modflow6", name="alpha"
        )
        if registration.zarr is not None:
            registration.zarr.close()
        catalog.register_tracked_files(
            sid,
            [
                TrackedFileEntry(
                    role="dem",
                    category="raster",
                    original_path="inputs/dem.tif",
                    canonical_path=dem,
                    portable=True,
                )
            ],
        )
        catalog.finalize(sid, status="completed", duration_s=1.0)
        expected = catalog.list_tracked_files(sid).to_dict(orient="records")

    catalog_path_for(root).unlink()
    rebuild_index(root)

    with Catalog(root, read_only=True) as catalog:
        assert catalog.list_tracked_files(sid).to_dict(orient="records") == expected
