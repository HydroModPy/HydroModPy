"""Tests for the ``hmp project`` actions O5 owns: new, list, show, delete, promote, prune.

``promote`` and ``prune`` are driven through their own module, registered on
a local parser, so the test does not depend on the order of ``ACTIONS``;
``test_cli_surface_matches_the_target.py`` checks the family registers them.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

import pytest

from hydromodpy.cli.commands.project import promote, prune
from hydromodpy.cli.helpers import exit_code_for
from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.session.journal import read_trials
from hydromodpy.results.trash import list_trash
from tests._helpers.sealed_runs import make_project, seal_run, write_attempt, write_session_dir


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


def _run_action(module, argv: list[str]) -> int:
    """Parse ``argv`` with the action alone and run it the way ``main`` does."""
    parser = argparse.ArgumentParser(prog="hmp project")
    module.register(parser.add_subparsers(dest="action"))
    try:
        args = parser.parse_args(argv)
        args._handler(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:  # noqa: BLE001 - mirrors main._dispatch
        print(str(exc), file=sys.stderr)
        return exit_code_for(exc)
    return 0


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True)
    (workspace / "data").mkdir()
    (workspace / "projects").mkdir()
    return workspace


@pytest.fixture
def outside(tmp_path, monkeypatch) -> Path:
    """A current directory no workspace holds, with no HMP_WORKSPACE."""
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    directory = tmp_path / "elsewhere"
    directory.mkdir()
    monkeypatch.chdir(directory)
    return directory


def test_project_family_help_lists_actions(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "project", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    for action in ("new", "list", "show", "delete"):
        assert action in out


def test_project_new_scaffolds_project(monkeypatch, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    assert _run(monkeypatch, ["hmp", "project", "new", "demo", "-w", str(workspace)]) == 0
    assert (workspace / "projects" / "demo").is_dir()


def test_project_new_finds_the_workspace_above_the_cwd(monkeypatch, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    monkeypatch.chdir(workspace / "projects")
    assert _run(monkeypatch, ["hmp", "project", "new", "demo"]) == 0
    assert (workspace / "projects" / "demo").is_dir()


def test_project_list_empty_workspace(monkeypatch, capsys, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    assert _run(monkeypatch, ["hmp", "project", "list", "-w", str(workspace)]) == 0
    assert "no projects" in capsys.readouterr().out.lower()


@pytest.mark.parametrize(
    "argv",
    [
        ["hmp", "project", "list"],
        ["hmp", "project", "new", "demo"],
        ["hmp", "project", "show", "demo"],
        ["hmp", "project", "delete", "demo", "-y"],
    ],
)
def test_without_a_workspace_the_verb_stops_and_names_w(
    monkeypatch, capsys, tmp_path, outside, argv
) -> None:
    from hydromodpy.data.workspace import scaffold

    home_workspace = _make_workspace(tmp_path / "home")
    (home_workspace / "projects" / "demo").mkdir()
    monkeypatch.setattr(scaffold, "DEFAULT_ROOT", home_workspace)

    assert _run(monkeypatch, argv) == 10
    captured = capsys.readouterr()
    assert "-w" in captured.err
    assert str(home_workspace) not in captured.out + captured.err
    assert (home_workspace / "projects" / "demo").is_dir()


def test_project_show_missing_project_returns_not_found(monkeypatch, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    code = _run(monkeypatch, ["hmp", "project", "show", "missing", "-w", str(workspace)])
    assert code == 10


def test_project_show_counts_what_the_directories_hold(monkeypatch, capsys, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    project = make_project(workspace / "projects" / "demo")
    seal_run(project, "alpha")
    write_attempt(project, "runs/beta", status="failed")
    write_session_dir(project, "calibration", trials=3, best_trial=2)
    (project / "run_daily.toml").write_text("", encoding="utf-8")

    code = _run(monkeypatch, ["hmp", "project", "show", "-w", str(project), "--format", "json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "demo"
    assert payload["runs"] == {"completed": 1, "failed": 1}
    assert payload["sessions"] == {"completed": 1}
    assert payload["configs"] == ["run_daily.toml"]
    assert payload["has_index"] is False
    assert payload["plan"] is None


def test_project_show_by_name_prints_the_runs_by_status(monkeypatch, capsys, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    project = make_project(workspace / "projects" / "demo")
    seal_run(project, "alpha")

    assert _run(monkeypatch, ["hmp", "project", "show", "demo", "-w", str(workspace)]) == 0
    out = capsys.readouterr().out
    assert "runs     : 1 (completed 1)" in out
    assert "missing (hmp catalog reindex builds it)" in out


def test_project_delete_removes_project_directory(monkeypatch, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    project_dir = workspace / "projects" / "demo"
    project_dir.mkdir(parents=True)
    (project_dir / "marker.txt").write_text("hello")

    code = _run(monkeypatch, ["hmp", "project", "delete", "demo", "-w", str(workspace), "-y"])
    assert code == 0
    assert not project_dir.exists()


def test_project_delete_refuses_without_yes_in_non_tty(monkeypatch, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    project_dir = workspace / "projects" / "demo"
    project_dir.mkdir(parents=True)

    code = _run(monkeypatch, ["hmp", "project", "delete", "demo", "-w", str(workspace)])
    assert code == 2
    assert project_dir.exists()


def test_project_delete_refuses_a_project_with_a_running_attempt(
    monkeypatch, capsys, tmp_path
) -> None:
    workspace = _make_workspace(tmp_path)
    project = make_project(workspace / "projects" / "demo")
    write_attempt(project, "runs/busy", status="running", heartbeat_age_s=1)

    code = _run(monkeypatch, ["hmp", "project", "delete", "demo", "-w", str(workspace), "-y"])

    assert code == 12
    assert "runs/busy" in capsys.readouterr().err
    assert project.is_dir()


# --- promote and prune --------------------------------------------------------


def _calibrated_project(tmp_path: Path, *, kept: tuple[int, ...]) -> Path:
    project = make_project(tmp_path / "demo")
    write_session_dir(project, "calibration", trials=3, best_trial=2)
    for number in kept:
        trial_dir = project / "sessions" / "calibration" / "trials" / f"{number:04d}"
        trial_dir.mkdir(parents=True)
        (trial_dir / "manifest.json").write_text("{}", encoding="utf-8")
    return project


def test_promote_moves_a_kept_trial_to_runs(capsys, tmp_path) -> None:
    project = _calibrated_project(tmp_path, kept=(1,))

    code = _run_action(
        promote,
        ["promote", "calibration", "--trial", "1", "--as", "k_low", "-w", str(project)],
    )

    assert code == 0
    assert (project / "runs" / "k_low" / "manifest.json").is_file()
    assert not (project / "sessions" / "calibration" / "trials" / "0001").exists()
    line = {item.trial: item for item in read_trials(project / "sessions" / "calibration")}[1]
    assert line.rel_dir == "runs/k_low"
    assert "runs/k_low" in capsys.readouterr().out


def test_promote_from_inside_the_project(monkeypatch, tmp_path) -> None:
    project = _calibrated_project(tmp_path, kept=(1,))
    monkeypatch.chdir(project / "sessions")

    assert _run_action(promote, ["promote", "calibration", "--trial", "1"]) == 0
    assert (project / "runs" / "calibration" / "manifest.json").is_file()


def test_promote_a_trial_the_session_never_journaled_exits_as_a_calibration_error(
    capsys, tmp_path
) -> None:
    project = _calibrated_project(tmp_path, kept=())

    code = _run_action(promote, ["promote", "calibration", "--trial", "9", "-w", str(project)])

    assert code == 21
    assert "journals no trial 9" in capsys.readouterr().err
    assert not (project / "runs").exists()


def test_promote_an_unknown_case_names_the_sessions(capsys, tmp_path) -> None:
    project = _calibrated_project(tmp_path, kept=())

    code = _run_action(promote, ["promote", "nowhere", "--trial", "1", "-w", str(project)])

    assert code == 14
    assert "calibration" in capsys.readouterr().err


def test_promote_needs_the_trial_number(capsys, tmp_path) -> None:
    project = _calibrated_project(tmp_path, kept=())
    assert _run_action(promote, ["promote", "calibration", "-w", str(project)]) == 2


def test_promote_outside_a_project_exits_not_found(capsys, outside) -> None:
    assert _run_action(promote, ["promote", "calibration", "--trial", "1"]) == 10
    assert "project.toml" in capsys.readouterr().err


def test_prune_keeps_the_best_and_trashes_the_others(capsys, tmp_path) -> None:
    project = _calibrated_project(tmp_path, kept=(1, 2, 3))

    code = _run_action(prune, ["prune", "calibration", "--keep", "best", "-w", str(project), "-y"])

    assert code == 0
    trials = project / "sessions" / "calibration" / "trials"
    assert sorted(path.name for path in trials.iterdir()) == ["0002"]
    assert sorted(entry.rel_dir for entry in list_trash(project)) == [
        "sessions/calibration/trials/0001",
        "sessions/calibration/trials/0003",
    ]
    assert read_session(project / "sessions" / "calibration").best.trial == 2
    assert "moved 2 trial(s)" in capsys.readouterr().out


def test_prune_refuses_without_yes_in_non_tty(tmp_path) -> None:
    project = _calibrated_project(tmp_path, kept=(1, 3))

    assert _run_action(prune, ["prune", "calibration", "-w", str(project)]) == 2
    assert list_trash(project) == []


def test_prune_knows_only_the_best_policy(tmp_path) -> None:
    project = _calibrated_project(tmp_path, kept=(1,))
    assert _run_action(prune, ["prune", "calibration", "--keep", "all", "-w", str(project)]) == 2
