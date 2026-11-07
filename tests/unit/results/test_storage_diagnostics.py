from __future__ import annotations

import shutil
from pathlib import Path

from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.diagnostics import diagnose_result_storage, is_run_directory
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store


def _by_name(diagnostics):
    return {diagnostic.name: diagnostic for diagnostic in diagnostics}


def _seal(project: Path, name: str) -> tuple[str, Path]:
    """Seal a one-cell run with a field store; return its id and directory."""
    store = open_run_store(project, name, n_cells=1, n_layers=1)
    sid, run_dir = store.sim_id, store.run_dir
    seal_completed(store)
    return sid, run_dir


def _with_tmp_parquet_and_orphan(project: Path) -> tuple[Path, Path]:
    """Seal and index one run, then leave a partial Parquet file and an orphan run."""
    _, run_dir = _seal(project, "with_tmp")
    rebuild_index(project)
    tables_dir = run_dir / TABLES_DIRNAME
    tables_dir.mkdir(parents=True, exist_ok=True)
    tmp_parquet = tables_dir / f"timeseries{PARQUET_FILE_SUFFIX}.tmp-0a1b2c3d"
    tmp_parquet.write_bytes(b"partial")
    orphan_run = project / "runs" / "orphan_run"
    (orphan_run / FIELDS_STORE_NAME).mkdir(parents=True)
    return tmp_parquet, orphan_run


def test_clean_project_storage_reports_ok(tmp_path):
    project = tmp_path / "project"
    _seal(project, "baseline")
    rebuild_index(project)

    diagnostics = _by_name(diagnose_result_storage(project))

    assert diagnostics["results:layout"].status == "OK"
    assert "1 index row(s)" in diagnostics["results:layout"].detail
    assert "1 run director" in diagnostics["results:layout"].detail


def test_completed_row_missing_fields_store_is_reported(tmp_path):
    project = tmp_path / "project"
    sid, run_dir = _seal(project, "missing_fields")
    rebuild_index(project)

    shutil.rmtree(run_dir / FIELDS_STORE_NAME)
    diagnostics = _by_name(diagnose_result_storage(project))

    assert diagnostics["results:missing_zarr"].status == "WARN"
    assert "1 completed index row(s)" in diagnostics["results:missing_zarr"].detail
    assert sid in str(diagnostics["results:missing_zarr"].hint)


def test_orphan_run_directory_and_tmp_parquet_are_reported(tmp_path):
    project = tmp_path / "project"
    tmp_parquet, orphan_run = _with_tmp_parquet_and_orphan(project)

    diagnostics = _by_name(diagnose_result_storage(project))

    assert diagnostics["results:orphan_runs"].status == "WARN"
    assert diagnostics["results:orphan_runs"].hint == "first: orphan_run"
    assert diagnostics["results:orphan_runs"].paths == (str(orphan_run),)
    assert diagnostics["results:parquet_tmp"].status == "WARN"
    assert diagnostics["results:parquet_tmp"].paths == (str(tmp_parquet),)


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
    rebuild_index(project)

    checks = {check["name"]: check for check in _probe_result_storage(project)}

    assert checks["results:layout"]["status"] == "OK"
    assert checks["results:layout"]["hint"] is None


def test_a_file_changed_since_the_seal_is_reported(tmp_path):
    project = tmp_path / "project"
    _, run_dir = _seal(project, "tampered")
    rebuild_index(project)
    assert "results:seal_digest" not in _by_name(diagnose_result_storage(project))

    table = next((run_dir / TABLES_DIRNAME).glob(f"*{PARQUET_FILE_SUFFIX}"))
    table.write_bytes(table.read_bytes() + b"x")
    diagnostics = _by_name(diagnose_result_storage(project))

    assert diagnostics["results:seal_digest"].status == "WARN"
    assert table.name in diagnostics["results:seal_digest"].hint
