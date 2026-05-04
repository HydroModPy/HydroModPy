from __future__ import annotations

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.catalog.storage_paths import build_storage_basename
from hydromodpy.results.storage_contract import (
    CATALOG_FILENAME,
    PARQUET_DIR_SUFFIX,
    RESULT_STORAGE_LAYERS,
    SIMULATION_STORAGE_LAYER_NAMES,
    SIMULATIONS_DIRNAME,
    WORKSPACE_STORAGE_LAYER_NAMES,
    ZARR_SUFFIX,
    ZARR_ZIP_SUFFIX,
)


def test_storage_layers_make_workspace_vs_simulation_scope_explicit():
    assert WORKSPACE_STORAGE_LAYER_NAMES == ("catalog",)
    assert SIMULATION_STORAGE_LAYER_NAMES == ("zarr", "parquet")
    assert [layer.name for layer in RESULT_STORAGE_LAYERS] == [
        "catalog",
        "zarr",
        "parquet",
    ]


def test_catalog_is_workspace_scoped_and_artifacts_are_per_simulation(tmp_path):
    workspace = tmp_path / "workspace"
    sid = "00000000-0000-4000-8000-000000000001"

    with SimulationCatalog(workspace) as catalog:
        assert catalog.catalog_path == workspace.resolve() / CATALOG_FILENAME
        assert catalog.simulations_dir == workspace.resolve() / SIMULATIONS_DIRNAME

        reg = catalog.register_simulation(
            sid,
            project="Project A",
            solver="modflow6",
            name="Run One",
            n_cells=1,
            n_layers=1,
        )
        assert reg.zarr is not None
        reg.zarr.close()

        basename = build_storage_basename("Project A", "Run One", sid)
        assert catalog.zarr_path_for(sid) == catalog.simulations_dir / f"{basename}{ZARR_SUFFIX}"
        assert catalog.parquet_dir_for(sid) == (
            catalog.simulations_dir / f"{basename}{PARQUET_DIR_SUFFIX}"
        )

        row = catalog.connection.execute(
            "SELECT zarr_path, storage_basename FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row == (
            f"{SIMULATIONS_DIRNAME}/{basename}{ZARR_SUFFIX}",
            basename,
        )


def test_legacy_catalog_row_without_storage_basename_uses_raw_sim_id(tmp_path):
    workspace = tmp_path / "workspace"
    sid = "11111111-1111-4111-8111-111111111111"

    with SimulationCatalog(workspace) as catalog:
        catalog.connection.execute(
            "INSERT INTO simulations (sim_id, project, solver) VALUES (?, ?, ?)",
            [sid, "legacy", "modflow6"],
        )

        assert catalog.zarr_path_for(sid) == catalog.simulations_dir / f"{sid}{ZARR_SUFFIX}"
        assert catalog.parquet_dir_for(sid) == (
            catalog.simulations_dir / f"{sid}{PARQUET_DIR_SUFFIX}"
        )

        legacy_zip = catalog.simulations_dir / f"{sid}{ZARR_ZIP_SUFFIX}"
        legacy_zip.write_bytes(b"")
        assert catalog.zarr_path_for(sid) == legacy_zip


def test_legacy_storage_names_can_be_normalized_explicitly(tmp_path):
    workspace = tmp_path / "workspace"
    sid = "22222222-2222-4222-8222-222222222222"

    with SimulationCatalog(workspace) as catalog:
        catalog.connection.execute(
            "INSERT INTO simulations "
            "(sim_id, project, name, solver, zarr_path, zarr_packed) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                sid,
                "Project A",
                "Run One",
                "modflow6",
                f"{SIMULATIONS_DIRNAME}/{sid}{ZARR_ZIP_SUFFIX}",
                True,
            ],
        )
        legacy_zarr = catalog.simulations_dir / f"{sid}{ZARR_ZIP_SUFFIX}"
        legacy_zarr.write_bytes(b"zip")
        legacy_parquet = catalog.simulations_dir / f"{sid}{PARQUET_DIR_SUFFIX}"
        legacy_parquet.mkdir(parents=True)

        expected = build_storage_basename("Project A", "Run One", sid)
        dry_run = catalog.normalize_storage_names()
        assert len(dry_run) == 1
        assert dry_run[0].ready
        assert dry_run[0].new_basename == expected
        assert legacy_zarr.exists()
        assert legacy_parquet.exists()

        applied = catalog.normalize_storage_names(dry_run=False)
        assert len(applied) == 1
        assert applied[0].ready

        new_zarr = catalog.simulations_dir / f"{expected}{ZARR_ZIP_SUFFIX}"
        new_parquet = catalog.simulations_dir / f"{expected}{PARQUET_DIR_SUFFIX}"
        assert not legacy_zarr.exists()
        assert not legacy_parquet.exists()
        assert new_zarr.is_file()
        assert new_parquet.is_dir()
        assert catalog.zarr_path_for(sid) == new_zarr
        assert catalog.parquet_dir_for(sid) == new_parquet

        row = catalog.connection.execute(
            "SELECT zarr_path, storage_basename FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row == (f"{SIMULATIONS_DIRNAME}/{expected}{ZARR_ZIP_SUFFIX}", expected)


def test_legacy_storage_normalization_blocks_target_collisions(tmp_path):
    workspace = tmp_path / "workspace"
    sid = "33333333-3333-4333-8333-333333333333"

    with SimulationCatalog(workspace) as catalog:
        catalog.connection.execute(
            "INSERT INTO simulations (sim_id, project, name, solver) VALUES (?, ?, ?, ?)",
            [sid, "Project A", "Run One", "modflow6"],
        )
        expected = build_storage_basename("Project A", "Run One", sid)
        legacy_parquet = catalog.simulations_dir / f"{sid}{PARQUET_DIR_SUFFIX}"
        legacy_parquet.mkdir(parents=True)
        collision = catalog.simulations_dir / f"{expected}{PARQUET_DIR_SUFFIX}"
        collision.mkdir(parents=True)

        actions = catalog.normalize_storage_names(dry_run=False)

        assert len(actions) == 1
        assert not actions[0].ready
        assert "target Parquet directory already exists" in str(actions[0].reason)
        assert legacy_parquet.is_dir()
        assert collision.is_dir()
        row = catalog.connection.execute(
            "SELECT storage_basename FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row == (None,)
