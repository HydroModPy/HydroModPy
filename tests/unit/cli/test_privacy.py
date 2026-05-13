"""Tests for ``hmp privacy``."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


def _make_workspace_with_project(tmp_path: Path) -> tuple[Path, Path]:
    from hydromodpy.results.catalog import SimulationCatalog

    workspace = tmp_path / "ws"
    workspace.mkdir()
    project = workspace / "projects" / "demo"
    project.mkdir(parents=True)
    (project / "simulations").mkdir()
    with SimulationCatalog(project):
        pass
    return workspace, project


def _seed_simulation(project: Path, sim_id: str = "00000000-0000-0000-0000-000000000010") -> str:
    import duckdb

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
                    (SELECT id FROM statuses WHERE code = 'completed'),
                    ?, ?,
                    (SELECT id FROM mesh_topologies WHERE code = 'structured_3d'))
            """,
            [sim_id, "to-be-purged", "demo", "simulations/x.zarr", "x"],
        )
    finally:
        conn.close()
    return sim_id


def test_privacy_help_displays(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "privacy", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "purge" in out.lower()


def test_privacy_purge_help_displays(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "privacy", "purge", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "sim_ref" in out
    assert "--reason" in out


def test_privacy_purge_writes_certificate(monkeypatch, tmp_path, capsys) -> None:
    workspace, project = _make_workspace_with_project(tmp_path)
    sim_id = _seed_simulation(project)

    code = _run(
        monkeypatch,
        [
            "hmp",
            "privacy",
            "purge",
            sim_id,
            "--workspace",
            str(project),
            "--reason",
            "test-purge",
            "-y",
        ],
    )
    assert code == 0

    cert_path = workspace / ".hmp" / "purge_certificates" / f"{sim_id}.json"
    assert cert_path.is_file()

    payload = json.loads(cert_path.read_text())
    assert payload["sim_id"] == sim_id
    assert payload["reason"] == "test-purge"
    assert "timestamp_utc" in payload
    assert "sha256_snapshot" in payload
    assert len(payload["sha256_snapshot"]) == 64


def test_privacy_purge_removes_simulation_row(monkeypatch, tmp_path) -> None:
    import duckdb

    workspace, project = _make_workspace_with_project(tmp_path)
    sim_id = _seed_simulation(project)

    code = _run(
        monkeypatch,
        [
            "hmp",
            "privacy",
            "purge",
            sim_id,
            "--workspace",
            str(project),
            "-y",
        ],
    )
    assert code == 0

    conn = duckdb.connect(str(project / "catalog.duckdb"), read_only=True)
    try:
        row = conn.execute("SELECT 1 FROM simulations WHERE sim_id = ?", [sim_id]).fetchone()
    finally:
        conn.close()
    assert row is None
