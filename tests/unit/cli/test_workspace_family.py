"""Tests for the ``hmp workspace`` family (init, list, clean)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_workspace_family_help_lists_actions(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "workspace", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    for action in ("init", "list", "clean"):
        assert action in out


def test_workspace_init_scaffolds_workspace(monkeypatch, tmp_path) -> None:
    target = tmp_path / "fresh_ws"
    monkeypatch.setattr(sys, "argv", ["hmp", "workspace", "init", "--path", str(target)])
    _load_main().main()
    assert target.is_dir()
    assert (target / "projects").is_dir()
    assert (target / "data").is_dir()


def test_workspace_clean_requires_a_group(monkeypatch, capsys, tmp_path) -> None:
    target = tmp_path / "ws"
    target.mkdir()
    (target / "data").mkdir()
    code = _run(
        monkeypatch,
        ["hmp", "workspace", "clean", "--workspace", str(target)],
    )
    assert code == 14
    err = capsys.readouterr().err
    assert "group" in err.lower() or "--all" in err


# --- clean --results goes through the trash (H29) -----------------------------


def _workspace_with_results(tmp_path: Path) -> tuple[Path, Path]:
    from hydromodpy.results.catalog.indexer import rebuild_index
    from tests._helpers.sealed_runs import make_project, seal_run, write_session_dir

    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    project = make_project(workspace / "projects" / "demo")
    seal_run(project, "alpha")
    write_session_dir(project, "calibration", trials=2, best_trial=1)
    rebuild_index(project)
    return workspace, project


def test_clean_results_moves_every_run_to_the_trash(monkeypatch, capsys, tmp_path) -> None:
    from hydromodpy.core.state.paths import catalog_path_for
    from hydromodpy.results.catalog.registration import reserve_version_dirname
    from hydromodpy.results.trash import list_trash

    workspace, project = _workspace_with_results(tmp_path)

    code = _run(monkeypatch, ["hmp", "workspace", "clean", "--results", "-w", str(workspace), "-y"])

    assert code == 0
    assert sorted(entry.rel_dir for entry in list_trash(project)) == [
        "runs/alpha",
        "sessions/calibration",
    ]
    assert list((project / "runs").iterdir()) == []
    assert not catalog_path_for(project).exists()
    assert reserve_version_dirname(project, "run", "alpha").name == "alpha.v2"


def test_clean_results_dry_run_moves_nothing(monkeypatch, capsys, tmp_path) -> None:
    workspace, project = _workspace_with_results(tmp_path)

    code = _run(monkeypatch, ["hmp", "workspace", "clean", "--results", "-w", str(workspace)])

    assert code == 0
    out = capsys.readouterr().out
    assert "Dry-run, would move 2 run(s) and session(s)" in out
    assert (project / "runs" / "alpha").is_dir()
    assert not (project / "trash").exists()


def test_clean_results_refuses_while_an_attempt_runs(monkeypatch, capsys, tmp_path) -> None:
    from tests._helpers.sealed_runs import write_attempt

    workspace, project = _workspace_with_results(tmp_path)
    write_attempt(project, "runs/busy", status="running", heartbeat_age_s=1)

    code = _run(monkeypatch, ["hmp", "workspace", "clean", "--results", "-w", str(workspace), "-y"])

    assert code == 12
    assert "runs/busy" in capsys.readouterr().err
    assert (project / "runs" / "alpha").is_dir()
    assert not (project / "trash").exists()


def test_workspace_list_takes_w(monkeypatch, capsys, tmp_path) -> None:
    workspace, _project = _workspace_with_results(tmp_path)

    code = _run(monkeypatch, ["hmp", "workspace", "list", "-w", str(workspace), "--json"])

    assert code == 0
    assert "alpha" in capsys.readouterr().out
