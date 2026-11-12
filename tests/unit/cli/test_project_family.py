"""Tests for the ``hmp project`` actions O5 owns: new, list, delete, promote, prune, and ``hmp show`` of a project.

``promote`` and ``prune`` are driven through their own module, registered on
a local parser, so the test does not depend on the order of ``ACTIONS``;
``test_cli_surface_matches_the_target.py`` checks the family registers them."""

from __future__ import annotations

import argparse
import csv
import importlib
import io
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

from hydromodpy.cli.commands.campaign import array, collect, promote, prune
from hydromodpy.cli.commands.project import log
from hydromodpy.cli.exit_codes import (
    EXIT_CONFIG,
    EXIT_GENERIC,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_VALIDATION,
    exit_code_for,
)
from hydromodpy.project.launch.journal import Journal, new_job_dir
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.run.sealed import MixedWindowsError
from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.session.journal import read_trials
from hydromodpy.results.trash import list_trash
from tests._helpers.cli_runner import CliRunner
from tests._helpers.published_runs import (
    RUN_NAME,
    make_sealed_run,
    make_summary,
)
from tests._helpers.published_runs import (
    make_project as make_published_project,
)
from tests._helpers.sealed_runs import make_project, seal_run, write_attempt, write_session_dir
from tests.unit.project.launch._helpers import planned_project

from ._hmp import run_main as _run


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
        ["hmp", "show", "demo"],
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


def test_show_project_by_name_prints_the_runs_by_status(monkeypatch, capsys, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    project = make_project(workspace / "projects" / "demo")
    seal_run(project, "alpha")

    assert _run(monkeypatch, ["hmp", "show", "demo", "-w", str(workspace)]) == 0
    out = capsys.readouterr().out
    assert "runs     : 1 (completed 1)" in out
    assert "missing (hmp catalog reindex builds it)" in out


def test_show_project_dot_reads_the_project_of_the_cwd(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    workspace = _make_workspace(tmp_path)
    project = make_project(workspace / "projects" / "demo")
    seal_run(project, "alpha")
    monkeypatch.chdir(project / "runs")

    assert _run(monkeypatch, ["hmp", "show", "."]) == 0
    out = capsys.readouterr().out
    assert "# project: demo" in out
    assert "runs     : 1 (completed 1)" in out


def test_show_project_a_path_without_a_project_is_refused_by_name(
    monkeypatch, capsys, outside
) -> None:
    code = _run(monkeypatch, ["hmp", "show", "."])

    assert code == 10
    assert f"No project.toml at or above {outside.resolve()}" in capsys.readouterr().err


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
        ["promote", "calibration", "--trial", "1", "--name", "k_low", "-w", str(project)],
    )

    assert code == 0
    assert (project / "runs" / "k_low" / "manifest.json").is_file()
    assert not (project / "sessions" / "calibration" / "trials" / "0001").exists()
    line = {item.trial: item for item in read_trials(project / "sessions" / "calibration")}[1]
    assert line.only_case.rel_dir == "runs/k_low"
    assert "runs/k_low" in capsys.readouterr().out


def test_promote_without_a_trial_lists_the_best_ones(capsys, tmp_path) -> None:
    project = _calibrated_project(tmp_path, kept=())

    code = _run_action(promote, ["promote", "calibration", "-w", str(project)])

    assert code == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "trial 3 (steady_k): cost -0.8, K = 3e-05",
        "trial 2 (steady_k): cost -0.7, K = 2e-05",
        "trial 1 (steady_k): cost -0.6, K = 1e-05",
    ]
    assert not (project / "runs").exists()


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


def _journalled_project(tmp_path: Path) -> Path:
    project = tmp_path / "campaign"
    project.mkdir()
    (project / "project.toml").write_text("[sites]\n", encoding="utf-8")
    journal = Journal(new_job_dir(project, "local"))
    journal.append("launch_start", plan_hash="abc", n_cases=2)
    journal.append("case_end", case_id="alpha-base", status="completed", exit_code=0)
    journal.append(
        "case_end",
        case_id="beta-base",
        status="failed",
        exit_code=15,
        error={"type": "SolverError", "message": "boom"},
        rel_dir="runs/beta-base",
    )
    return project


def _args(project: Path, fmt: str) -> argparse.Namespace:
    return argparse.Namespace(
        project=str(project), workspace=None, failed=False, job=None, format=fmt, verbosity=None
    )


def test_csv_is_one_row_per_event(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _journalled_project(tmp_path)

    log.run(_args(project, "csv"))

    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert [row["event"] for row in rows] == ["launch_start", "case_end", "case_end"]
    assert rows[2]["case_id"] == "beta-base"
    assert rows[2]["error"] == "SolverError: boom"
    assert rows[2]["exit_code"] == "15"
    assert rows[0]["case_id"] == ""


def test_json_stays_the_events(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = _journalled_project(tmp_path)

    log.run(_args(project, "json"))

    events = json.loads(capsys.readouterr().out)["data"]
    assert [event["event"] for event in events] == ["launch_start", "case_end", "case_end"]


def _invoke_array(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="hmp project")
    array.register(parser.add_subparsers())
    try:
        args = parser.parse_args([array.NAME, *argv])
        args._handler(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_the_action_writes_the_job_and_prints_the_submission(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "p"
    planned_project(root, threads=2)

    code = _invoke_array([str(root), "--scheduler", "slurm", "--partition", "normal"])

    assert code == 0
    jobs = list((root / "jobs").iterdir())
    assert len(jobs) == 1 and jobs[0].name.endswith("-slurm")
    assert {"prepare.sh", "array.sh", "cases.txt"} <= {p.name for p in jobs[0].iterdir()}
    out = capsys.readouterr().out
    assert f"sbatch --parsable {jobs[0] / 'prepare.sh'}" in out
    assert f"sbatch --dependency=afterok:$prep {jobs[0] / 'array.sh'}" in out
    assert "3 case(s)" in out and "Not verified on a cluster" in out


def test_the_project_file_names_its_project(tmp_path: Path) -> None:
    root = tmp_path / "p"
    planned_project(root)

    assert _invoke_array([str(root / "project.toml"), "--scheduler", "slurm"]) == 0
    assert (root / "jobs").is_dir()


def test_errors_leave_through_typed_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unplanned = tmp_path / "unplanned"
    unplanned.mkdir()
    assert _invoke_array([str(unplanned), "--scheduler", "slurm"]) == EXIT_NOT_FOUND
    assert "no plan" in capsys.readouterr().err

    root = tmp_path / "p"
    planned_project(root)
    assert _invoke_array([str(root), "--scheduler", "slurm", "--time", "5"]) == EXIT_CONFIG
    assert "walltime" in capsys.readouterr().err


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="hmp project")
    sub = parser.add_subparsers(dest="action")
    collect.register(sub)
    return parser.parse_args([collect.NAME, *argv])


def _collect_project(tmp_path: Path) -> Path:
    root = tmp_path / "bretagne"
    root.mkdir()
    (root / "project.toml").write_text(
        '[sites]\ntable = "sites.csv"\n\n[sites.summary]\nbest = "any"\n', encoding="utf-8"
    )
    return root


def test_the_action_carries_the_four_symbols_of_a_family_action() -> None:
    assert collect.NAME == "collect"
    assert collect.HELP
    assert callable(collect.register)
    assert callable(collect.run)


def test_collect_writes_the_summary_of_the_project(tmp_path, capsys) -> None:
    root = _collect_project(tmp_path)
    seal_run(root, "a-base", project="bretagne", site="a", recipe="base", nse=0.6)

    args = _parse([str(root / "runs"), "--write-sites"])
    args._handler(args)

    out = capsys.readouterr().out
    assert f"wrote {root / 'summary'}" in out
    assert "catalog.csv" in out
    assert (root / "summary" / "by_site.csv").is_file()
    assert (root / "summary" / "catalog.csv").is_file()


def test_mixed_windows_exit_with_the_validation_code(tmp_path, capsys) -> None:
    root = _collect_project(tmp_path)
    seal_run(root, "a-base", project="bretagne", site="a", recipe="base", nse=0.6)
    seal_run(
        root,
        "b-base",
        project="bretagne",
        site="b",
        recipe="base",
        nse=0.7,
        window=DateWindow(start=date(2010, 1, 1), end=date(2014, 12, 31)),
    )

    args = _parse([str(root)])
    with pytest.raises(MixedWindowsError, match="--mixed-windows") as refused:
        args._handler(args)
    assert exit_code_for(refused.value) == EXIT_VALIDATION

    args = _parse([str(root), "--mixed-windows"])
    args._handler(args)
    assert (root / "summary" / "by_site.parquet").is_file()


def test_a_folder_outside_any_project_is_not_found(tmp_path) -> None:
    lonely = tmp_path / "lonely"
    lonely.mkdir()

    args = _parse([str(lonely)])
    with pytest.raises(FileNotFoundError) as missing:
        args._handler(args)
    assert exit_code_for(missing.value) == EXIT_NOT_FOUND


def test_a_figure_not_drawn_is_named_on_stderr(tmp_path, capsys) -> None:
    root = _collect_project(tmp_path)
    (root / "project.toml").write_text(
        '[sites]\ntable = "sites.csv"\n\n[sites.summary]\nbest = "any"\nmetrics = ["nse", "kge"]\n'
        'figures = ["distribution"]\nvariables = ["kge"]\n',
        encoding="utf-8",
    )
    seal_run(root, "a-base", project="bretagne", site="a", recipe="base", nse=0.6)

    args = _parse([str(root)])
    args._handler(args)

    assert "figure not drawn: distribution of kge: " in capsys.readouterr().err


def _invoke_publish(*args: str):
    return CliRunner().invoke(["publish", *args])


def _published(tmp_path: Path) -> Path:
    project = make_published_project(tmp_path)
    make_sealed_run(project)
    make_summary(project, error_message="diverged")
    destination = tmp_path / "out"
    result = _invoke_publish(".", "--to", str(destination), "-w", str(project))
    assert result.exit_code == EXIT_OK, result.stderr
    return destination


def test_a_project_copy_is_verified_through_its_own_publication(tmp_path: Path) -> None:
    destination = _published(tmp_path)

    result = _invoke_publish("--verify", str(destination))

    assert result.exit_code == EXIT_OK, result.stderr
    assert "a campaign copy" not in result.stderr
    assert "every file matches PUBLICATION.json" in result.stderr


def test_a_removed_member_is_named(tmp_path: Path) -> None:
    destination = _published(tmp_path)
    shutil.rmtree(destination / RUN_NAME)

    result = _invoke_publish("--verify", str(destination))

    assert result.exit_code == EXIT_GENERIC
    assert f"{RUN_NAME}: missing" in result.stdout


def test_a_changed_file_names_its_member(tmp_path: Path) -> None:
    destination = _published(tmp_path)
    (destination / "summary" / "by_case.csv").write_text("changed\n", encoding="utf-8")
    (destination / "notes.txt").write_text("added by hand\n", encoding="utf-8")

    result = _invoke_publish("--verify", str(destination))

    assert result.exit_code == EXIT_GENERIC
    assert "summary/by_case.csv: digest differs" in result.stdout
    assert "notes.txt: not listed in PUBLICATION.json" in result.stdout
    assert f"{RUN_NAME}/" not in result.stdout


def test_a_folder_of_copies_without_the_project_publication_is_verified(tmp_path: Path) -> None:
    destination = _published(tmp_path)
    (destination / "PUBLICATION.json").unlink()
    (destination / "notes.txt").write_text("added by hand\n", encoding="utf-8")

    result = _invoke_publish("--verify", str(destination))

    assert result.exit_code == EXIT_GENERIC
    assert "a campaign copy: verifying its 2 members" in result.stderr
    assert "notes.txt: not a published copy" in result.stdout
    assert f"{RUN_NAME}/" not in result.stdout


def test_a_folder_without_any_copy_is_refused_by_name(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    result = _invoke_publish("--verify", str(empty))

    assert result.exit_code == EXIT_NOT_FOUND
    assert "holds no PUBLICATION.json and no published copy" in result.stderr
    assert "Errno" not in result.stderr
