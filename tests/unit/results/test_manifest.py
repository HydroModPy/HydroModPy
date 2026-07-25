"""The run manifest: a run directory that describes itself without the index."""

from __future__ import annotations

import json

import pyarrow.parquet as pq
import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.manifest import (
    KEY_PACKAGES,
    MANIFEST_SCHEMA_VERSION,
    RUN_MANIFEST_FILENAME,
    build_manifest,
    build_provenance,
    is_sealed,
    read_manifest,
    seal_run,
)
from hydromodpy.results.storage.contract import (
    PARQUET_FILE_SUFFIX,
    RUN_CONFIG_FILENAME,
    RUN_FIGURES_DIRNAME,
    RUN_PROVENANCE_FILENAME,
    TABLES_DIRNAME,
)

SID = "00000000-0000-4000-8000-00000000c0de"


def _register(catalog: Catalog, *, name: str = "cheze_demo", sid: str = SID) -> str:
    reg = catalog.register_simulation(
        sid,
        project="Cheze",
        solver="modflow6",
        name=name,
        flow_regime="transient",
        n_cells=1024,
        n_layers=3,
        n_timesteps=7,
        bbox=[10.0, 20.0, 110.0, 220.0],
        crs="EPSG:2154",
        period_start="2020-01-01",
        period_end="2020-01-08",
        time_unit="day",
        config={"flow": {"hk": 1e-5}},
        study_area_name="Cheze",
        outlet_x=300.0,
        outlet_y=400.0,
    )
    if reg.zarr is not None:
        reg.zarr.close()
    return reg.name


def _populate(catalog: Catalog, sid: str = SID) -> None:
    catalog.write_parameters(
        sid,
        [
            {"param_name": "hk", "value": 1e-5, "unit": "m/s", "parameterization": "calibrated"},
            {"param_name": "sy", "value": 0.02, "unit": "1", "zone_id": "upper"},
        ],
    )
    catalog.write_geographic_metadata(
        sid,
        {
            "catch_area": "29.7",
            "x_outlet": "301.5",
            "y_outlet": "402.5",
            "dem_res": "5",
            "nrow": "120",
            "ncol": "240",
            "crs_proj": "EPSG:2154",
            "epsg": "2154",
            "catch_def": "from_outlet_coord",
        },
    )
    catalog.write_metric(sid, "__outlet__", "nse", 0.66, variable="discharge", n_samples=365)
    catalog.write_run_environment(sid, solver_name="modflow6")


@pytest.fixture
def sealed_run(tmp_path):
    """A finalised run, yielding ``(run_dir, manifest)``."""
    with Catalog(tmp_path / "project") as catalog:
        _register(catalog)
        _populate(catalog)
        (catalog.run_dir_for(SID) / RUN_CONFIG_FILENAME).write_text("[flow]\nhk = 1e-5\n")
        catalog.finalize(SID, status="completed", duration_s=42.0)
        run_dir = catalog.run_dir_for(SID)
    return run_dir, read_manifest(run_dir)


# -- sealing ----------------------------------------------------------------


def test_a_completed_run_is_sealed_by_a_manifest(sealed_run):
    run_dir, manifest = sealed_run

    assert is_sealed(run_dir)
    assert manifest["manifest_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["sealed_at"].endswith("+00:00")


def test_an_unfinished_run_has_no_manifest(tmp_path):
    with Catalog(tmp_path / "project") as catalog:
        _register(catalog)
        _populate(catalog)
        catalog.finalize(SID, status="failed")
        run_dir = catalog.run_dir_for(SID)

    assert not is_sealed(run_dir)
    with pytest.raises(FileNotFoundError, match="incomplete"):
        read_manifest(run_dir)


def test_seal_replaces_a_previous_manifest_without_leaving_a_temporary(tmp_path):
    with Catalog(tmp_path / "project") as catalog:
        _register(catalog)
        _populate(catalog)
        catalog.finalize(SID, status="completed", duration_s=1.0)
        run_dir = catalog.run_dir_for(SID)
        first = read_manifest(run_dir)["sealed_at"]

        seal_run(catalog, SID)
        second = read_manifest(run_dir)["sealed_at"]

    assert second >= first
    assert not list(run_dir.glob(f"{RUN_MANIFEST_FILENAME}.tmp-*"))


def test_a_failing_seal_leaves_the_run_unsealed_without_failing_finalize(tmp_path, monkeypatch):
    import hydromodpy.results.manifest as manifest_module

    def boom(catalog, sim_id):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(manifest_module, "seal_run", boom)

    with Catalog(tmp_path / "project") as catalog:
        _register(catalog)
        catalog.finalize(SID, status="completed", duration_s=1.0)
        run_dir = catalog.run_dir_for(SID)
        status = catalog.backend.fetch_one(
            "SELECT st.code FROM simulations s JOIN statuses st ON s.status_id = st.id "
            "WHERE s.sim_id = ?",
            [SID],
        )

    assert status[0] == "completed"
    assert not is_sealed(run_dir)


# -- identity, geometry, period ---------------------------------------------


def test_manifest_carries_the_run_identity(sealed_run):
    _, manifest = sealed_run
    run = manifest["run"]

    assert run["sim_id"] == SID
    assert run["name"] == "cheze_demo"
    assert run["version"] == 1
    assert run["status"] == "completed"
    assert run["project"] == "Cheze"
    assert run["solver"] == "modflow6"
    assert run["flow_regime"] == "transient"
    assert run["duration_s"] == 42.0
    assert run["started_at"] and run["ended_at"]


def test_manifest_carries_the_grid_geometry(sealed_run):
    _, manifest = sealed_run
    geometry = manifest["geometry"]

    assert geometry["n_cells"] == 1024
    assert geometry["n_layers"] == 3
    assert geometry["crs_epsg"] == 2154
    assert geometry["bbox"] == [10.0, 20.0, 110.0, 220.0]


def test_manifest_keeps_the_catchment_area_and_outlet(sealed_run):
    """Losing these turns a derived discharge into a silently wrong series."""
    _, manifest = sealed_run
    catchment = manifest["geometry"]["catchment"]

    assert catchment["catch_area"] == pytest.approx(29.7)
    assert catchment["x_outlet"] == pytest.approx(301.5)
    assert catchment["y_outlet"] == pytest.approx(402.5)
    assert catchment["dem_res"] == pytest.approx(5.0)
    assert (catchment["nrow"], catchment["ncol"]) == (120, 240)
    assert catchment["crs_proj"] == "EPSG:2154"
    assert catchment["catch_def"] == "from_outlet_coord"


def test_declared_outlet_is_kept_apart_from_the_delineated_one(sealed_run):
    _, manifest = sealed_run

    assert manifest["geometry"]["declared_outlet"] == {"x": 300.0, "y": 400.0}
    assert manifest["geometry"]["catchment"]["x_outlet"] == pytest.approx(301.5)


def test_manifest_carries_the_simulated_period(sealed_run):
    _, manifest = sealed_run
    period = manifest["period"]

    assert period["n_timesteps"] == 7
    assert period["time_unit"] == "day"
    assert period["start"].startswith("2020-01-01")
    assert period["end"].startswith("2020-01-08")


def test_manifest_fingerprints_the_configuration(sealed_run):
    _, manifest = sealed_run

    assert manifest["config"]["file"] == RUN_CONFIG_FILENAME
    assert len(manifest["config"]["hash"]) == 64


def test_a_run_without_a_frozen_config_says_so(tmp_path):
    with Catalog(tmp_path / "project") as catalog:
        _register(catalog)
        catalog.finalize(SID, status="completed")
        manifest = read_manifest(catalog.run_dir_for(SID))

    assert manifest["config"]["file"] is None


# -- artefacts ---------------------------------------------------------------


def test_manifest_inventories_every_artefact_of_the_run(sealed_run):
    run_dir, manifest = sealed_run
    by_path = {entry["path"]: entry for entry in manifest["artifacts"]}

    assert by_path["fields.zarr"] == {"path": "fields.zarr", "role": "fields", "format": "zarr"}
    assert by_path[RUN_MANIFEST_FILENAME]["role"] == "manifest"
    assert by_path[RUN_PROVENANCE_FILENAME]["role"] == "provenance"
    assert by_path[RUN_CONFIG_FILENAME]["role"] == "config"

    params = by_path[f"{TABLES_DIRNAME}/parameters{PARQUET_FILE_SUFFIX}"]
    assert params["role"] == "table:parameters"
    assert params["format"] == "parquet"
    assert params["bytes"] > 0

    listed = set(by_path) - {RUN_MANIFEST_FILENAME}
    assert listed, "the inventory must not be empty"
    for relative in listed:
        assert (run_dir / relative).exists()


def test_figures_of_the_run_are_inventoried(tmp_path):
    with Catalog(tmp_path / "project") as catalog:
        _register(catalog)
        figures = catalog.run_dir_for(SID) / RUN_FIGURES_DIRNAME
        figures.mkdir(parents=True)
        (figures / "watertable.png").write_bytes(b"\x89PNG")
        catalog.finalize(SID, status="completed")
        manifest = read_manifest(catalog.run_dir_for(SID))

    figure = next(e for e in manifest["artifacts"] if e["role"] == "figure")
    assert figure["path"] == f"{RUN_FIGURES_DIRNAME}/watertable.png"
    assert figure["format"] == "png"


# -- parameters --------------------------------------------------------------


def test_parameters_land_on_disk_as_parquet(sealed_run):
    run_dir, _ = sealed_run
    target = run_dir / TABLES_DIRNAME / f"parameters{PARQUET_FILE_SUFFIX}"

    table = pq.read_table(target)
    assert table.column_names == [
        "sim_id",
        "param_name",
        "zone_id",
        "value",
        "unit",
        "parameterization",
        "valid_from",
    ]
    rows = {(r["param_name"], r["zone_id"]): r for r in table.to_pylist()}
    assert rows[("hk", "__global__")]["value"] == pytest.approx(1e-5)
    assert rows[("hk", "__global__")]["parameterization"] == "calibrated"
    assert rows[("sy", "upper")]["value"] == pytest.approx(0.02)


def test_parameters_are_readable_from_the_manifest_too(sealed_run):
    _, manifest = sealed_run
    by_name = {(p["name"], p["zone"]): p for p in manifest["parameters"]}

    assert by_name[("hk", "__global__")]["unit"] == "m/s"
    assert by_name[("sy", "upper")]["value"] == pytest.approx(0.02)


def test_a_run_without_parameters_writes_no_parameter_table(tmp_path):
    with Catalog(tmp_path / "project") as catalog:
        _register(catalog)
        catalog.finalize(SID, status="completed")
        run_dir = catalog.run_dir_for(SID)
        manifest = read_manifest(run_dir)

    assert manifest["parameters"] == []
    assert not (run_dir / TABLES_DIRNAME / f"parameters{PARQUET_FILE_SUFFIX}").exists()


# -- metrics -----------------------------------------------------------------


def test_manifest_summarises_the_metrics(sealed_run):
    _, manifest = sealed_run

    assert manifest["metrics"] == [
        {
            "station": "__outlet__",
            "variable": "discharge",
            "metric": "nse",
            "value": pytest.approx(0.66),
            "n_samples": 365,
        }
    ]


# -- provenance --------------------------------------------------------------


def test_provenance_records_the_tool_python_platform_and_git_state(sealed_run):
    run_dir, _ = sealed_run
    provenance = json.loads((run_dir / RUN_PROVENANCE_FILENAME).read_text(encoding="utf-8"))

    assert provenance["tool"]["name"] == "hydromodpy"
    assert provenance["tool"]["version"]
    assert provenance["python"]["version"].count(".") == 2
    assert provenance["platform"]["platform"]
    assert provenance["platform"]["hostname"]
    assert isinstance(provenance["git"]["dirty"], (bool, type(None)))


def test_provenance_pins_the_key_scientific_packages(sealed_run):
    run_dir, _ = sealed_run
    provenance = json.loads((run_dir / RUN_PROVENANCE_FILENAME).read_text(encoding="utf-8"))
    packages = provenance["packages"]

    assert set(packages) <= set(KEY_PACKAGES)
    for pinned in ("numpy", "pyarrow", "duckdb"):
        assert pinned in packages, f"{pinned} version must be pinned in provenance"


def test_provenance_records_the_solver_and_the_timing(sealed_run):
    run_dir, _ = sealed_run
    provenance = json.loads((run_dir / RUN_PROVENANCE_FILENAME).read_text(encoding="utf-8"))

    assert provenance["solver"]["name"] == "modflow6"
    assert set(provenance["solver"]) == {"name", "version", "binary_path", "binary_sha256"}
    assert provenance["timing"]["duration_s"] == 42.0
    assert provenance["timing"]["started_at"] and provenance["timing"]["ended_at"]


def test_provenance_survives_a_run_with_no_recorded_environment(tmp_path):
    with Catalog(tmp_path / "project") as catalog:
        _register(catalog)
        payload = build_provenance(catalog, SID)

    assert payload["tool"]["version"] is None
    assert payload["packages"] == {}
    assert payload["environment"]["packages_frozen"] == []


# -- versioned runs ----------------------------------------------------------


def test_each_version_of_a_run_seals_its_own_directory(tmp_path):
    second = "00000000-0000-4000-8000-00000000cafe"
    with Catalog(tmp_path / "project") as catalog:
        _register(catalog)
        catalog.finalize(SID, status="completed")
        name = _register(catalog, sid=second)
        catalog.finalize(second, status="completed")
        first_dir = catalog.run_dir_for(SID)
        second_dir = catalog.run_dir_for(second)

    assert name == "cheze_demo.v2"
    assert second_dir.name == "cheze_demo.v2"
    assert read_manifest(first_dir)["run"]["version"] == 1
    assert read_manifest(second_dir)["run"]["version"] == 2


def test_manifest_can_be_rebuilt_without_writing_it(tmp_path):
    with Catalog(tmp_path / "project") as catalog:
        _register(catalog)
        _populate(catalog)
        catalog.finalize(SID, status="completed")
        on_disk = read_manifest(catalog.run_dir_for(SID))
        rebuilt = build_manifest(catalog, SID)

    assert rebuilt["run"] == on_disk["run"]
    assert rebuilt["geometry"] == on_disk["geometry"]
    assert rebuilt["parameters"] == on_disk["parameters"]
