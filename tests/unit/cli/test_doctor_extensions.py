"""The ``hmp doctor`` flags --lifecycle, --cross-catalog, --prt and --fix-config.

Each flag adds named checks to the JSON report. --fix-config rewrites a TOML file
of an earlier release in place and tells what it changed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests._helpers.sealed_runs import make_project, seal_run, write_attempt

from ._hmp import run_main as _run


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
    return {entry["name"]: entry for entry in json.loads(out)["data"]["checks"]}


def test_lifecycle_stale_attempt(monkeypatch, tmp_path, capsys, isolated_state) -> None:
    workspace, project = _make_workspace(tmp_path)
    write_attempt(project, "runs/stuck", heartbeat_age_s=24 * 3600)

    code = _run(
        monkeypatch,
        ["hmp", "doctor", "--workspace", str(workspace), "--lifecycle", "--format", "json"],
    )

    assert code in (0, 1)
    checks = _checks(capsys.readouterr().out)
    assert checks["lifecycle:stale_attempts"]["status"] == "WARN"
    assert "demo/runs/stuck" in checks["lifecycle:stale_attempts"]["detail"]
    assert checks["lifecycle:orphan_calibration_sessions"]["status"] == "OK"
    assert "lifecycle:tmp_files" in checks


def test_cross_catalog_missing_run(monkeypatch, tmp_path, capsys, isolated_state) -> None:
    from hydromodpy.results.catalog.indexer import rebuild_index

    workspace, project = _make_workspace(tmp_path)
    seal_run(project, "first")
    rebuild_index(project)
    seal_run(project, "second")

    code = _run(
        monkeypatch,
        ["hmp", "doctor", "--workspace", str(workspace), "--cross-catalog", "--format", "json"],
    )

    assert code in (0, 1)
    checks = _checks(capsys.readouterr().out)
    assert checks["cross_catalog:projects_indexed"]["status"] == "OK"
    assert checks["cross_catalog:runs_vs_index"]["status"] == "WARN"
    assert "1 missing" in checks["cross_catalog:runs_vs_index"]["detail"]
    assert checks["cross_catalog:index_vs_runs"]["status"] == "OK"


def test_prt_in_report(monkeypatch, tmp_path, capsys) -> None:
    from hydromodpy.project import doctor

    mf6 = tmp_path / "mf6"
    mf6.touch()
    monkeypatch.setattr(doctor, "locate_mf6", lambda: mf6)
    monkeypatch.setattr(doctor, "mf6_version", lambda _exe: ("mf6: 6.6.3", (6, 6, 3)))

    code = _run(
        monkeypatch, ["hmp", "doctor", "--workspace", str(tmp_path), "--prt", "--format", "json"]
    )
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert "prt:mf6_version" in out


def test_fix_config_rewrites_in_place(monkeypatch, tmp_path, capsys) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        '# my project\n[modflow6.runtime]\nmf6_ims_complexity = "SIMPLE"\n'
        '[[simulation.process]]\nid = "flow"\ntype = "flow"\n',
        encoding="utf-8",
    )

    code = _run(monkeypatch, ["hmp", "doctor", "--fix-config", str(path)])

    assert code == 0
    out = capsys.readouterr().out
    assert f"Migrated {path}:" in out
    assert "modflow6 -> [solver.modflow6]" in out
    assert "type -> kind" in out
    text = path.read_text(encoding="utf-8")
    assert "# my project" in text
    assert 'mf6_ims_complexity = "SIMPLE"' in text
    assert 'kind = "flow"' in text
    assert "[modflow6" not in text and "type =" not in text

    code = _run(monkeypatch, ["hmp", "doctor", "--fix-config", str(path)])

    assert code == 0
    assert "already up to date" in capsys.readouterr().out


def test_fix_config_missing_file(monkeypatch, tmp_path, capsys) -> None:
    from hydromodpy.cli.exit_codes import EXIT_NOT_FOUND

    code = _run(monkeypatch, ["hmp", "doctor", "--fix-config", str(tmp_path / "absent.toml")])

    assert code == EXIT_NOT_FOUND
    assert "absent.toml" in capsys.readouterr().err


def test_fix_config_follows_base_config(monkeypatch, tmp_path, capsys) -> None:
    # An old key in a parent is told under the parent, and the fix does not come back.
    from hydromodpy.project.api import check

    parent = tmp_path / "project.toml"
    parent.write_text('[modflow6.runtime]\nmf6_ims_complexity = "SIMPLE"\n', encoding="utf-8")
    child = tmp_path / "run.toml"
    child.write_text('base_config = "project.toml"\n', encoding="utf-8")

    told = [item.detail for item in check(child) if item.code == "old_key"]
    assert any(line.startswith(f"{parent}: modflow6 -> [solver.modflow6]") for line in told)

    code = _run(monkeypatch, ["hmp", "doctor", "--fix-config", str(child)])

    assert code == 0
    out = capsys.readouterr().out
    assert f"Migrated {parent}:" in out
    assert "modflow6 -> [solver.modflow6]" in out
    assert f"{child} is already up to date." in out
    assert "[solver.modflow6.runtime]" in parent.read_text(encoding="utf-8")
    assert not [item for item in check(child) if item.code == "old_key"]


def test_fix_config_old_forms_left(monkeypatch, tmp_path, capsys) -> None:
    # A form the check still reads as old after the rewrite is told, not left in silence.
    from hydromodpy.core.diagnostic import Diagnostic

    config = tmp_path / "run.toml"
    config.write_text('[simulation]\nname = "demo"\n', encoding="utf-8")
    left = Diagnostic(
        path="flow.old", code="old_key", severity="warning", detail="flow.old -> flow.new"
    )
    monkeypatch.setattr("hydromodpy.project.doctor.findings_of", lambda file: [left])

    code = _run(monkeypatch, ["hmp", "doctor", "--fix-config", str(config)])

    out = capsys.readouterr().out
    assert code == 0
    assert f"{config} has nothing to migrate, and the check still reads old forms:" in out
    assert "  - flow.old -> flow.new" in out
    assert "already up to date" not in out


def test_fix_config_retired_keys(monkeypatch, tmp_path, capsys) -> None:
    from hydromodpy.cli.exit_codes import EXIT_CONFIG
    from hydromodpy.core.diagnostic import Diagnostic

    config = tmp_path / "run.toml"
    config.write_text('[simulation]\nname = "demo"\n', encoding="utf-8")
    retired = Diagnostic(
        path="flow.gone",
        code="retired_key",
        severity="error",
        detail="flow.gone was removed in 2.0.0",
    )
    monkeypatch.setattr("hydromodpy.project.doctor.findings_of", lambda file: [retired])

    code = _run(monkeypatch, ["hmp", "doctor", "--fix-config", str(config)])

    out = capsys.readouterr().out
    assert code == EXIT_CONFIG
    assert "and the check still refuses it:" in out
    assert "  - flow.gone was removed in 2.0.0" in out
