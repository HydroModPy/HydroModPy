from __future__ import annotations

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.storage_contract import PARQUET_FILE_SUFFIX
from hydromodpy.results.storage_diagnostics import (
    diagnose_result_storage,
    storage_artefact_basename,
    storage_artefact_kind,
)


def _by_name(diagnostics):
    return {diagnostic.name: diagnostic for diagnostic in diagnostics}


def test_clean_workspace_storage_reports_ok(tmp_path):
    workspace = tmp_path / "workspace"
    sid = "00000000-0000-4000-8000-000000000010"

    with SimulationCatalog(workspace) as catalog:
        reg = catalog.register_simulation(
            sid,
            project="p",
            solver="modflow6",
            name="baseline",
            n_cells=1,
            n_layers=1,
        )
        assert reg.zarr is not None
        reg.zarr.close()

    diagnostics = _by_name(diagnose_result_storage(workspace))

    assert diagnostics["results:layout"].status == "OK"
    assert "1 catalog row(s)" in diagnostics["results:layout"].detail
    assert "1 Zarr artefact(s)" in diagnostics["results:layout"].detail


def test_completed_row_missing_zarr_is_reported(tmp_path):
    workspace = tmp_path / "workspace"
    sid = "00000000-0000-4000-8000-000000000011"

    with SimulationCatalog(workspace) as catalog:
        reg = catalog.register_simulation(
            sid,
            project="p",
            solver="modflow6",
            name="missing-zarr",
            n_cells=1,
            n_layers=1,
        )
        assert reg.zarr is not None
        reg.zarr.close()
        catalog.finalize(sid, status="completed")
        zarr_path = catalog.zarr_path_for(sid)

    zarr_path.unlink()
    diagnostics = _by_name(diagnose_result_storage(workspace))

    assert diagnostics["results:missing_zarr"].status == "WARN"
    assert "1 completed catalog row(s)" in diagnostics["results:missing_zarr"].detail
    assert sid in str(diagnostics["results:missing_zarr"].hint)


def test_orphans_and_tmp_parquet_are_reported(tmp_path):
    workspace = tmp_path / "workspace"
    sid = "00000000-0000-4000-8000-000000000012"

    with SimulationCatalog(workspace) as catalog:
        reg = catalog.register_simulation(
            sid,
            project="p",
            solver="modflow6",
            name="with-tmp",
            n_cells=1,
            n_layers=1,
        )
        assert reg.zarr is not None
        reg.zarr.close()
        parquet_dir = catalog.parquet_dir_for(sid)
        parquet_dir.mkdir(parents=True)
        (parquet_dir / f"timeseries{PARQUET_FILE_SUFFIX}.tmp").write_bytes(b"partial")

        orphan_zarr = catalog.simulations_dir / "orphan.zarr"
        orphan_zarr.mkdir()
        orphan_parquet = catalog.simulations_dir / "orphan.parquet"
        orphan_parquet.mkdir()

    diagnostics = _by_name(diagnose_result_storage(workspace))

    assert diagnostics["results:orphan_zarr"].status == "WARN"
    assert diagnostics["results:orphan_zarr"].hint == "first: orphan"
    assert diagnostics["results:orphan_zarr"].paths == (str(orphan_zarr),)
    assert diagnostics["results:orphan_parquet"].status == "WARN"
    assert diagnostics["results:orphan_parquet"].hint == "first: orphan"
    assert diagnostics["results:orphan_parquet"].paths == (str(orphan_parquet),)
    assert diagnostics["results:parquet_tmp"].status == "WARN"
    assert diagnostics["results:parquet_tmp"].paths == (
        str(parquet_dir / f"timeseries{PARQUET_FILE_SUFFIX}.tmp"),
    )


def test_storage_artefact_helpers_use_shared_suffix_contract(tmp_path):
    zarr_zip = tmp_path / "demo.zarr.zip"
    zarr_zip.write_bytes(b"zip")
    zarr_dir = tmp_path / "demo.zarr"
    zarr_dir.mkdir()
    parquet_dir = tmp_path / "demo.parquet"
    parquet_dir.mkdir()

    assert storage_artefact_kind(zarr_zip) == "zarr.zip"
    assert storage_artefact_kind(zarr_dir) == "zarr"
    assert storage_artefact_kind(parquet_dir) == "parquet-dir"
    assert storage_artefact_basename(zarr_zip) == "demo"
    assert storage_artefact_basename(zarr_dir) == "demo"
    assert storage_artefact_basename(parquet_dir) == "demo"


def test_doctor_probe_returns_cli_check_shape(tmp_path):
    from hydromodpy.cli.commands.doctor import _probe_result_storage

    workspace = tmp_path / "workspace"
    with SimulationCatalog(workspace):
        pass

    checks = {check["name"]: check for check in _probe_result_storage(workspace)}

    assert checks["results:layout"]["status"] == "OK"
    assert checks["results:layout"]["hint"] is None


def test_manage_backend_exposes_and_cleans_diagnostic_paths(tmp_path):
    from hydromodpy.cli.commands.manage import _WorkspaceManagerBackend

    workspace = tmp_path / "workspace"
    with SimulationCatalog(workspace) as catalog:
        sid = "00000000-0000-4000-8000-000000000013"
        reg = catalog.register_simulation(
            sid,
            project="p",
            solver="modflow6",
            name="managed-cleanup",
            n_cells=1,
            n_layers=1,
        )
        assert reg.zarr is not None
        reg.zarr.close()
        parquet_dir = catalog.parquet_dir_for(sid)
        parquet_dir.mkdir(parents=True)
        tmp_file = parquet_dir / f"timeseries{PARQUET_FILE_SUFFIX}.tmp"
        tmp_file.write_bytes(b"partial")
        orphan = catalog.simulations_dir / "orphan.zarr"
        orphan.mkdir()

    backend = _WorkspaceManagerBackend(workspace_root=workspace)
    diagnostics = backend.result_diagnostics()["rows"]
    cleanup_paths = {path for row in diagnostics for path in row.get("paths", [])}

    assert str(tmp_file) in cleanup_paths
    assert str(orphan) in cleanup_paths

    result = backend.delete_orphans(None, [str(tmp_file), str(orphan)])

    assert result["deleted"]
    assert not tmp_file.exists()
    assert not orphan.exists()
    remaining = {
        path for row in backend.result_diagnostics()["rows"] for path in row.get("paths", [])
    }
    assert str(tmp_file) not in remaining
    assert str(orphan) not in remaining
