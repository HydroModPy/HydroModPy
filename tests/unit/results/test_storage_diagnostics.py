from __future__ import annotations

import shutil

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.diagnostics import diagnose_result_storage, is_run_directory


def _by_name(diagnostics):
    return {diagnostic.name: diagnostic for diagnostic in diagnostics}


def test_clean_project_storage_reports_ok(tmp_path):
    project = tmp_path / "project"
    sid = "00000000-0000-4000-8000-000000000010"

    with Catalog(project) as catalog:
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

    diagnostics = _by_name(diagnose_result_storage(project))

    assert diagnostics["results:layout"].status == "OK"
    assert "1 index row(s)" in diagnostics["results:layout"].detail
    assert "1 run director" in diagnostics["results:layout"].detail


def test_completed_row_missing_fields_store_is_reported(tmp_path):
    project = tmp_path / "project"
    sid = "00000000-0000-4000-8000-000000000011"

    with Catalog(project) as catalog:
        reg = catalog.register_simulation(
            sid,
            project="p",
            solver="modflow6",
            name="missing-fields",
            n_cells=1,
            n_layers=1,
        )
        assert reg.zarr is not None
        reg.zarr.close()
        catalog.finalize(sid, status="completed")
        fields_path = catalog.fields_path_for(sid)

    shutil.rmtree(fields_path)
    diagnostics = _by_name(diagnose_result_storage(project))

    assert diagnostics["results:missing_zarr"].status == "WARN"
    assert "1 completed index row(s)" in diagnostics["results:missing_zarr"].detail
    assert sid in str(diagnostics["results:missing_zarr"].hint)


def test_orphan_run_directory_and_tmp_parquet_are_reported(tmp_path):
    project = tmp_path / "project"
    sid = "00000000-0000-4000-8000-000000000012"

    with Catalog(project) as catalog:
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
        tables_dir = catalog.tables_dir_for(sid)
        tables_dir.mkdir(parents=True, exist_ok=True)
        (tables_dir / f"timeseries{PARQUET_FILE_SUFFIX}.tmp").write_bytes(b"partial")

        orphan_run = catalog.runs_dir / "orphan_run"
        (orphan_run / FIELDS_STORE_NAME).mkdir(parents=True)

    diagnostics = _by_name(diagnose_result_storage(project))

    assert diagnostics["results:orphan_runs"].status == "WARN"
    assert diagnostics["results:orphan_runs"].hint == "first: orphan_run"
    assert diagnostics["results:orphan_runs"].paths == (str(orphan_run),)
    assert diagnostics["results:parquet_tmp"].status == "WARN"
    assert diagnostics["results:parquet_tmp"].paths == (
        str(tables_dir / f"timeseries{PARQUET_FILE_SUFFIX}.tmp"),
    )


def test_is_run_directory_recognises_fields_or_tables(tmp_path):
    with_fields = tmp_path / "with_fields"
    (with_fields / FIELDS_STORE_NAME).mkdir(parents=True)
    with_tables = tmp_path / "with_tables"
    (with_tables / TABLES_DIRNAME).mkdir(parents=True)
    plain = tmp_path / "plain"
    plain.mkdir()
    a_file = tmp_path / "a_file"
    a_file.write_bytes(b"x")

    assert is_run_directory(with_fields)
    assert is_run_directory(with_tables)
    assert not is_run_directory(plain)
    assert not is_run_directory(a_file)


def test_doctor_probe_returns_cli_check_shape(tmp_path):
    from hydromodpy.cli.commands.doctor import _probe_result_storage

    project = tmp_path / "project"
    with Catalog(project):
        pass

    checks = {check["name"]: check for check in _probe_result_storage(project)}

    assert checks["results:layout"]["status"] == "OK"
    assert checks["results:layout"]["hint"] is None


def test_manage_backend_exposes_and_cleans_diagnostic_paths(tmp_path):
    from hydromodpy.cli.commands.dev.manage import _WorkspaceManagerBackend

    project = tmp_path / "project"
    with Catalog(project) as catalog:
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
        tables_dir = catalog.tables_dir_for(sid)
        tables_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = tables_dir / f"timeseries{PARQUET_FILE_SUFFIX}.tmp"
        tmp_file.write_bytes(b"partial")
        orphan = catalog.runs_dir / "orphan_run"
        (orphan / FIELDS_STORE_NAME).mkdir(parents=True)

    backend = _WorkspaceManagerBackend(workspace_root=project)
    diagnostics = backend.result_diagnostics()["rows"]
    cleanup_paths = {path for row in diagnostics for path in row.get("paths", [])}

    assert str(tmp_file) in cleanup_paths
    assert str(orphan) in cleanup_paths
    assert backend.summary()["diagnostic_warning_count"] >= 1

    result = backend.delete_orphans(None, [str(tmp_file), str(orphan)])

    assert result["deleted"]
    assert not tmp_file.exists()
    assert not orphan.exists()
    remaining = {
        path for row in backend.result_diagnostics()["rows"] for path in row.get("paths", [])
    }
    assert str(tmp_file) not in remaining
    assert str(orphan) not in remaining
