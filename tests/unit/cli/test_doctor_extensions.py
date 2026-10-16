"""Tests for the ``hmp doctor`` flags (--cross-catalog, --lifecycle, --prt, --fix-config)."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from tests._helpers.sealed_runs import make_project, seal_run, write_attempt


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


def _make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "ws"
    project = make_project(workspace / "projects" / "demo")
    (workspace / "data").mkdir()
    return workspace, project


def _checks(out: str) -> dict[str, dict]:
    return {entry["name"]: entry for entry in json.loads(out)["checks"]}


def test_doctor_help_lists_new_flags(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "doctor", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "--cross-catalog" in out
    assert "--lifecycle" in out
    assert "--prt" in out
    assert "--fix-config" in out
    assert "--migrate" not in out


def test_doctor_lifecycle_counts_a_stale_attempt_from_the_disk(
    monkeypatch, tmp_path, capsys, isolated_state
) -> None:
    workspace, project = _make_workspace(tmp_path)
    write_attempt(project, "runs/stuck", heartbeat_age_s=24 * 3600)

    code = _run(
        monkeypatch,
        ["hmp", "doctor", "--workspace", str(workspace), "--lifecycle", "--json"],
    )

    assert code in (0, 1)
    checks = _checks(capsys.readouterr().out)
    assert checks["lifecycle:stale_attempts"]["status"] == "WARN"
    assert "demo/runs/stuck" in checks["lifecycle:stale_attempts"]["detail"]
    assert checks["lifecycle:orphan_calibration_sessions"]["status"] == "OK"
    assert "lifecycle:tmp_files" in checks


def test_doctor_cross_catalog_names_a_run_the_index_lacks(
    monkeypatch, tmp_path, capsys, isolated_state
) -> None:
    from hydromodpy.results.catalog.indexer import rebuild_index

    workspace, project = _make_workspace(tmp_path)
    seal_run(project, "first")
    rebuild_index(project)
    seal_run(project, "second")

    code = _run(
        monkeypatch,
        ["hmp", "doctor", "--workspace", str(workspace), "--cross-catalog", "--json"],
    )

    assert code in (0, 1)
    checks = _checks(capsys.readouterr().out)
    assert checks["cross_catalog:projects_indexed"]["status"] == "OK"
    assert checks["cross_catalog:runs_vs_index"]["status"] == "WARN"
    assert "1 missing" in checks["cross_catalog:runs_vs_index"]["detail"]
    assert checks["cross_catalog:index_vs_runs"]["status"] == "OK"


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


def test_doctor_finds_the_workspace_that_holds_the_cwd(
    monkeypatch, tmp_path, capsys, isolated_state
) -> None:
    workspace, project = _make_workspace(tmp_path)
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    monkeypatch.chdir(project)

    code = _run(monkeypatch, ["hmp", "doctor", "--json"])

    assert code in (0, 1)
    checks = _checks(capsys.readouterr().out)
    assert checks["workspace"] == {
        "name": "workspace",
        "status": "OK",
        "detail": str(workspace.resolve()),
        "hint": None,
    }


def test_doctor_takes_w(monkeypatch, tmp_path, capsys, isolated_state) -> None:
    workspace, _project = _make_workspace(tmp_path)

    code = _run(monkeypatch, ["hmp", "doctor", "-w", str(workspace), "--json"])

    assert code in (0, 1)
    assert _checks(capsys.readouterr().out)["workspace"]["status"] == "OK"


def test_doctor_fix_config_rewrites_a_v1_file_in_place_and_says_what_changed(
    monkeypatch, tmp_path, capsys
) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        '# my project\n[simulation]\nrun_id = "cheze"\non_collision = "replace"\n',
        encoding="utf-8",
    )

    code = _run(monkeypatch, ["hmp", "doctor", "--fix-config", str(path)])

    assert code == 0
    out = capsys.readouterr().out
    assert f"Migrated {path}:" in out
    assert "on_collision -> if_exists" in out
    assert "run_id -> name" in out
    text = path.read_text(encoding="utf-8")
    assert "# my project" in text
    assert 'name = "cheze"' in text
    assert 'if_exists = "version"' in text
    assert "run_id" not in text and "on_collision" not in text

    code = _run(monkeypatch, ["hmp", "doctor", "--fix-config", str(path)])

    assert code == 0
    assert "already up to date" in capsys.readouterr().out


def test_doctor_fix_config_names_a_missing_file(monkeypatch, tmp_path, capsys) -> None:
    from hydromodpy.cli.helpers import EXIT_NOT_FOUND

    code = _run(monkeypatch, ["hmp", "doctor", "--fix-config", str(tmp_path / "absent.toml")])

    assert code == EXIT_NOT_FOUND
    assert "absent.toml" in capsys.readouterr().err
