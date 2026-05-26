"""Tests for ``hmp catalog gc``."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import duckdb
import pytest


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


def _make_minimal_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "projects").mkdir()
    (workspace / "data").mkdir()
    return workspace


def _make_project_with_catalog(workspace: Path, project_name: str = "demo") -> Path:
    from hydromodpy.results.catalog import SimulationCatalog

    project = workspace / "projects" / project_name
    project.mkdir(parents=True)
    (project / "simulations").mkdir()
    # touch a catalog by opening it once
    with SimulationCatalog(project):
        pass
    return project


def test_gc_help_displays(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()
    assert "--dry-run" in out


def test_gc_dry_run_on_empty_workspace(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "calibration_sessions" in out
    assert "geographic_cache" in out
    assert "tmp_parquet" in out
    assert "stale_running_sims" in out


def test_gc_basic_invocation_no_targets(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Summary" in out


def test_gc_removes_tmp_parquet(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    tmp_file = workspace / "data" / "spurious.tmp-abc.parquet"
    tmp_file.write_bytes(b"x")
    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace)])
    assert code == 0
    assert not tmp_file.exists()


def test_gc_removes_orphan_geographic_cache(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    cache_dir = workspace / "geographic" / "deadbeef"
    cache_dir.mkdir(parents=True)
    (cache_dir / "blob.bin").write_bytes(b"y")

    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace)])
    assert code == 0
    assert not cache_dir.exists()


def test_gc_dry_run_does_not_remove_anything(monkeypatch, tmp_path) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    tmp_file = workspace / "data" / "still.tmp-keep.parquet"
    tmp_file.write_bytes(b"keep")
    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace), "--dry-run"])
    assert code == 0
    assert tmp_file.exists()


def test_gc_marks_stale_running_simulation(monkeypatch, tmp_path) -> None:
    workspace = _make_minimal_workspace(tmp_path)
    project = _make_project_with_catalog(workspace, "demo")

    # Force a running sim with an old event-stream heartbeat.
    cat_path = project / "catalog.duckdb"
    conn = duckdb.connect(str(cat_path))
    try:
        conn.execute(
            """
            INSERT INTO simulations
                (sim_id, name, project, solver_id, status_id, zarr_path,
                 storage_basename, mesh_topology_id)
            VALUES (?, ?, ?,
                    (SELECT id FROM solvers WHERE code = 'modflow6'),
                    (SELECT id FROM statuses WHERE code = 'running'),
                    ?, ?,
                    (SELECT id FROM mesh_topologies WHERE code = 'structured_3d'))
            """,
            [
                "00000000-0000-0000-0000-000000000001",
                "stale",
                "demo",
                "simulations/stale.zarr",
                "stale",
            ],
        )
        conn.execute(
            """
            INSERT INTO workflow_events (run_id, step_name, event_type, ts)
            VALUES (?, 'pipeline', 'heartbeat', TIMESTAMP '2000-01-01 00:00:00+00')
            """,
            ["00000000-0000-0000-0000-000000000001"],
        )
    finally:
        conn.close()

    code = _run(monkeypatch, ["hmp", "catalog", "gc", "--workspace", str(workspace)])
    assert code == 0

    conn = duckdb.connect(str(cat_path), read_only=True)
    try:
        row = conn.execute(
            "SELECT st.code FROM simulations s "
            "JOIN statuses st ON s.status_id = st.id "
            "WHERE s.sim_id = ?",
            ["00000000-0000-0000-0000-000000000001"],
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "failed"
