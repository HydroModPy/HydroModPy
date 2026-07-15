from __future__ import annotations

from hydromodpy.core.state.paths import CATALOG_FILENAME
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.storage_paths import build_storage_basename
from hydromodpy.results.storage.contract import (
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

    with Catalog(workspace) as catalog:
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

        basename = build_storage_basename("Project A", sid)
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
