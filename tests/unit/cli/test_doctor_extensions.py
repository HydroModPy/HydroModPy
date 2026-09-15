"""Tests for the ``hmp doctor`` extension flags (--cross-catalog, --lifecycle, --prt)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    """Run ``hmp`` and tolerate handlers that do not call sys.exit explicitly."""
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("HMP_STATE_HOME", str(state))
    yield state


def _make_workspace_with_catalog(tmp_path: Path) -> Path:
    from hydromodpy.results.catalog import Catalog

    workspace = tmp_path / "ws"
    workspace.mkdir()
    project = workspace / "projects" / "demo"
    project.mkdir(parents=True)
    (workspace / "data").mkdir()
    with Catalog(project):
        pass
    return workspace


def test_doctor_help_lists_new_flags(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "doctor", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "--cross-catalog" in out
    assert "--lifecycle" in out
    assert "--prt" in out


def test_doctor_lifecycle_on_clean_workspace(monkeypatch, tmp_path, capsys, isolated_state) -> None:
    workspace = _make_workspace_with_catalog(tmp_path)
    code = _run(
        monkeypatch,
        ["hmp", "doctor", "--workspace", str(workspace), "--lifecycle", "--json"],
    )
    # exit may be 0 even with WARN entries; just verify the new checks render
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert "lifecycle:stale_running_sims" in out
    assert "lifecycle:orphan_calibration_sessions" in out
    assert "lifecycle:tmp_parquet" in out


def test_doctor_cross_catalog_on_workspace(monkeypatch, tmp_path, capsys, isolated_state) -> None:
    workspace = _make_workspace_with_catalog(tmp_path)
    code = _run(
        monkeypatch,
        ["hmp", "doctor", "--workspace", str(workspace), "--cross-catalog", "--json"],
    )
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert "cross_catalog:" in out


@pytest.fixture
def doctor_module():
    return importlib.import_module("hydromodpy.cli.commands.doctor")


def test_doctor_prt_accepts_a_recent_mf6(monkeypatch, tmp_path, capsys, doctor_module) -> None:
    mf6 = tmp_path / "mf6"
    mf6.touch()
    monkeypatch.setattr(doctor_module, "_locate_mf6", lambda: mf6)
    monkeypatch.setattr(doctor_module, "_mf6_version", lambda _exe: ("mf6: 6.6.3", (6, 6, 3)))

    checks = {entry["name"]: entry for entry in doctor_module._prt_checks()}
    assert checks["prt:mf6"]["status"] == "OK"
    assert checks["prt:mf6_version"]["status"] == "OK"
    assert checks["prt:flopy"]["status"] == "OK"


def test_doctor_prt_rejects_a_pre_prt_mf6(monkeypatch, tmp_path, doctor_module) -> None:
    mf6 = tmp_path / "mf6"
    mf6.touch()
    monkeypatch.setattr(doctor_module, "_locate_mf6", lambda: mf6)
    monkeypatch.setattr(doctor_module, "_mf6_version", lambda _exe: ("mf6: 6.4.1", (6, 4, 1)))

    checks = {entry["name"]: entry for entry in doctor_module._prt_checks()}
    assert checks["prt:mf6_version"]["status"] == "KO"
    assert "install-binaries" in checks["prt:mf6_version"]["hint"]


def test_doctor_prt_reports_a_missing_mf6(monkeypatch, doctor_module) -> None:
    monkeypatch.setattr(doctor_module, "_locate_mf6", lambda: None)

    checks = doctor_module._prt_checks()
    assert [entry["status"] for entry in checks] == ["KO"]
    assert checks[0]["name"] == "prt:mf6"


def test_doctor_prt_renders_in_the_report(monkeypatch, tmp_path, capsys, doctor_module) -> None:
    mf6 = tmp_path / "mf6"
    mf6.touch()
    monkeypatch.setattr(doctor_module, "_locate_mf6", lambda: mf6)
    monkeypatch.setattr(doctor_module, "_mf6_version", lambda _exe: ("mf6: 6.6.3", (6, 6, 3)))

    code = _run(monkeypatch, ["hmp", "doctor", "--workspace", str(tmp_path), "--prt", "--json"])
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert "prt:mf6_version" in out
