"""Tests for ``hmp privacy``."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from hydromodpy.core.state.layout import TOMBSTONES_FILENAME, catalog_path_for, trash_dir_for
from tests._helpers.sealed_runs import make_project, seal_run

from ._hmp import run_main as _run


def _make_workspace_with_project(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "ws"
    project = make_project(workspace / "projects" / "demo")
    return workspace, project


def _seed_simulation(project: Path, sim_id: str = "00000000-0000-0000-0000-000000000010") -> str:
    from hydromodpy.results.catalog.indexer import rebuild_index

    seal_run(project, "to_be_purged", sim_id=sim_id)
    rebuild_index(project)
    return sim_id


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


def test_privacy_purge_removes_the_directory_and_keeps_its_name(monkeypatch, tmp_path) -> None:
    import duckdb

    from hydromodpy.results.trash import read_tombstones

    _workspace, project = _make_workspace_with_project(tmp_path)
    sim_id = _seed_simulation(project)

    code = _run(
        monkeypatch,
        ["hmp", "privacy", "purge", sim_id, "--workspace", str(project), "-y"],
    )
    assert code == 0

    assert not (project / "runs" / "to_be_purged").exists()
    assert (trash_dir_for(project) / TOMBSTONES_FILENAME).is_file()
    assert [t.rel_dir for t in read_tombstones(project)] == ["runs/to_be_purged"]
    conn = duckdb.connect(str(catalog_path_for(project)), read_only=True)
    try:
        row = conn.execute("SELECT 1 FROM simulations WHERE sim_id = ?", [sim_id]).fetchone()
    finally:
        conn.close()
    assert row is None


def test_privacy_purge_of_an_unknown_reference_exits_not_found(monkeypatch, tmp_path) -> None:
    from hydromodpy.cli.exit_codes import EXIT_NOT_FOUND

    _workspace, project = _make_workspace_with_project(tmp_path)
    code = _run(
        monkeypatch,
        ["hmp", "privacy", "purge", "nothing_here", "--workspace", str(project), "-y"],
    )
    assert code == EXIT_NOT_FOUND
