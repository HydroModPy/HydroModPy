"""Tests for ``hmp privacy``."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from hydromodpy.core.state.paths import RUNS_DIRNAME, catalog_path_for
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


def _make_workspace_with_project(tmp_path: Path) -> tuple[Path, Path]:
    from hydromodpy.results.catalog import Catalog

    workspace = tmp_path / "ws"
    workspace.mkdir()
    project = workspace / "projects" / "demo"
    project.mkdir(parents=True)
    with Catalog(project):
        pass
    return workspace, project


def _seed_simulation(project: Path, sim_id: str = "00000000-0000-0000-0000-000000000010") -> str:
    import duckdb

    conn = duckdb.connect(str(catalog_path_for(project)))
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
            [
                sim_id,
                "to-be-purged",
                "demo",
                f"{RUNS_DIRNAME}/to-be-purged/{FIELDS_STORE_NAME}",
                "to-be-purged",
            ],
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


def test_privacy_purge_certificate_is_pii_free(monkeypatch, tmp_path) -> None:
    """The default certificate carries no snapshot, no paths, no PII fields."""
    workspace, project = _make_workspace_with_project(tmp_path)
    sim_id = _seed_simulation(project)

    code = _run(
        monkeypatch,
        ["hmp", "privacy", "purge", sim_id, "--workspace", str(project), "-y"],
    )
    assert code == 0
    cert_path = workspace / ".hmp" / "purge_certificates" / f"{sim_id}.json"
    payload = json.loads(cert_path.read_text())
    forbidden = {
        "snapshot",
        "removed_paths",
        "contact_email",
        "principal_id",
        "outlet_x",
        "outlet_y",
        "name",
        "project",
    }
    leaked = forbidden & set(payload.keys())
    assert not leaked, f"PII leaked into purge certificate: {sorted(leaked)}"
    assert "operator" in payload, "certificate must record the operator id"


def test_privacy_purge_certificate_is_mode_0o600(monkeypatch, tmp_path) -> None:
    """The certificate file is created with restrictive permissions."""
    import os
    import stat

    if os.name != "posix":
        pytest.skip("POSIX-only permission check")

    workspace, project = _make_workspace_with_project(tmp_path)
    sim_id = _seed_simulation(project)

    _run(
        monkeypatch,
        ["hmp", "privacy", "purge", sim_id, "--workspace", str(project), "-y"],
    )
    cert_path = workspace / ".hmp" / "purge_certificates" / f"{sim_id}.json"
    mode = stat.S_IMODE(cert_path.stat().st_mode)
    assert mode == 0o600, f"certificate must be 0o600, got {oct(mode)}"


def test_privacy_purge_archive_pii_opt_in(monkeypatch, tmp_path) -> None:
    """``--archive-pii`` writes a sibling 0o600 file with the snapshot."""
    import os
    import stat

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
            "--archive-pii",
        ],
    )
    assert code == 0

    archive_path = workspace / ".hmp" / "purge_certificates" / f"{sim_id}.pii.json"
    assert archive_path.is_file(), "PII archive must exist when --archive-pii is passed"
    archive = json.loads(archive_path.read_text())
    assert "snapshot" in archive
    assert "removed_paths" in archive
    if os.name == "posix":
        mode = stat.S_IMODE(archive_path.stat().st_mode)
        assert mode == 0o600


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

    conn = duckdb.connect(str(catalog_path_for(project)), read_only=True)
    try:
        row = conn.execute("SELECT 1 FROM simulations WHERE sim_id = ?", [sim_id]).fetchone()
    finally:
        conn.close()
    assert row is None
