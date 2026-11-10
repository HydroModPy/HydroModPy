"""``hmp run``: what it says before, during and after a run, and how it refuses a live case."""

from __future__ import annotations

import importlib
import os
import socket
import sys
from pathlib import Path

import pytest

from hydromodpy.cli.commands import run as run_command
from hydromodpy.cli.commands.run import HEAD_ONLY_MESSAGE, _stops_before_setup_process
from hydromodpy.cli.helpers import EXIT_WRITE_CONFLICT, exit_code_for
from hydromodpy.cli.main import main
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import (
    CLAIMED_ELSEWHERE,
    AttemptClaimedError,
    CaseAliveError,
    DirectoryWithoutOutcomeError,
)
from tests._helpers.sealed_runs import write_attempt
from tests.unit.project._helpers import DEM, PROJECT_TOML

from ._hmp import run_main as _run


@pytest.mark.fast
def test_overview_recap_names_the_page_and_the_figures(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    figures = tmp_path / "runs" / "overview" / "figures"
    summary = {
        "mode": "data_overview",
        "name": "Nançon",
        "catchment_area_km2": 64.6325,
        "report_paths": [str(figures / "map_dem.png"), str(figures / "stats_card.png")],
        "web_report": str(tmp_path / "runs" / "overview" / "report" / "index.html"),
    }

    run_command._print_overview_recap(summary)

    assert capsys.readouterr().err.splitlines() == [
        "Overview of Nançon ready (64.6 km²)",
        "  Report:  runs/overview/report/index.html",
        "  Figures: runs/overview/figures/ (2)",
    ]


@pytest.mark.parametrize(
    ("until", "expected"),
    [
        (None, False),
        ("build_geographic", True),
        ("load_data", True),
        ("build_mesh", True),
        ("setup_process", False),
        ("run_solver", False),
        ("seal", False),
    ],
)
def test_only_a_window_that_ends_before_setup_process_is_head_only(
    until: str | None, expected: bool
) -> None:
    assert _stops_before_setup_process(until) is expected


def test_a_head_only_window_prints_one_line_and_exits_zero(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    config = tmp_path / "run.toml"
    config.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")
    # A window that stops before the model keeps no run: the runner gives nothing back.
    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.run_simulation", lambda *a, **k: None)

    code = _run(monkeypatch, ["hmp", "run", str(config), "--until", "build_mesh", "--case", "x"])

    assert code == 0
    assert HEAD_ONLY_MESSAGE in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()


def test_a_window_that_reaches_the_model_phase_says_nothing_of_it(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    config = tmp_path / "run.toml"
    config.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")
    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.run_simulation", lambda *a, **k: None)

    code = _run(monkeypatch, ["hmp", "run", str(config), "--until", "run_solver"])

    assert code == 0
    assert HEAD_ONLY_MESSAGE not in capsys.readouterr().err


def test_until_on_a_calibration_file_names_the_simulation_workaround(
    monkeypatch, tmp_path, capsys
) -> None:
    config_path = tmp_path / "calibration.toml"
    config_path.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")

    code = _run(monkeypatch, ["hmp", "run", str(config_path), "--until", "load_data"])

    from hydromodpy.cli.helpers import EXIT_CONFIG

    assert code == EXIT_CONFIG
    err = capsys.readouterr().err
    assert (
        "--from / --until are only supported for the 'simulation' workflow "
        "(detected 'calibration'). To run the first steps of this file, for "
        "example to check the soil reservoir alone, add "
        "--set workflow.mode=simulation: "
        "hmp run calibration.toml --until load_data --set workflow.mode=simulation"
    ) in err


def test_from_on_a_calibration_file_gets_the_same_text(monkeypatch, tmp_path, capsys) -> None:
    config_path = tmp_path / "calibration.toml"
    config_path.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")

    code = _run(monkeypatch, ["hmp", "run", str(config_path), "--from", "load_data"])

    from hydromodpy.cli.helpers import EXIT_CONFIG

    assert code == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "--set workflow.mode=simulation" in err
    assert "detected 'calibration'" in err


def test_until_on_an_overview_file_keeps_the_generic_text(monkeypatch, tmp_path, capsys) -> None:
    config_path = tmp_path / "overview.toml"
    config_path.write_text('[workflow]\nmode = "overview"\n', encoding="utf-8")

    code = _run(monkeypatch, ["hmp", "run", str(config_path), "--until", "load_data"])

    from hydromodpy.cli.helpers import EXIT_CONFIG

    assert code == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "detected 'overview'" in err
    assert "workflow.mode=simulation" not in err


def test_an_overview_receives_the_environment_of_the_command(monkeypatch, tmp_path, capsys) -> None:
    """The CLI builds the Environment and hands it to the overview adapter."""
    from hydromodpy.core.exceptions import HydroModPyError
    from hydromodpy.project.dispatch import workflow as dispatch_module

    asked: dict = {}

    def fake_overview(request, *, base, environment=None):
        asked["environment"] = environment
        raise HydroModPyError("sentinel-of-the-overview")

    monkeypatch.setitem(dispatch_module.DISPATCH, "overview", fake_overview)
    config_path = tmp_path / "overview.toml"
    config_path.write_text('[workflow]\nmode = "overview"\n', encoding="utf-8")

    code = _run(
        monkeypatch,
        [
            "hmp",
            "run",
            str(config_path),
            "--allow-host",
            "data.geopf.fr",
            "--max-download-bytes",
            "4096",
        ],
    )

    assert code == exit_code_for(HydroModPyError("x"))
    environment = asked["environment"]
    assert environment is not None
    assert environment.bounds.allowed_hosts == frozenset({"data.geopf.fr"})
    assert environment.bounds.max_download_bytes == 4096
    assert "sentinel-of-the-overview" in capsys.readouterr().err


CASE = "declared_name"


"""``[simulation] name`` of the project TOML, which names the case."""


@pytest.mark.parametrize(
    "error",
    [
        AttemptClaimedError(f"{CLAIMED_ELSEWHERE}: x"),
        CaseAliveError("x is running on node12 (pid 4421)"),
        DirectoryWithoutOutcomeError("x carries neither outcome.json nor manifest.json"),
    ],
)
def test_a_lost_claim_exits_as_a_write_conflict(error: Exception) -> None:
    assert exit_code_for(error) == EXIT_WRITE_CONFLICT


def test_a_second_hmp_run_on_a_live_case_is_refused_and_leaves_it_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=tmp_path.as_posix(), dem=DEM.as_posix()), encoding="utf-8"
    )
    # The live worker: another process of this host, with a fresh pulse.
    live_pid = os.getppid()
    run_dir = write_attempt(
        tmp_path,
        f"runs/{CASE}",
        status="running",
        attempt=1,
        heartbeat_age_s=1.0,
        host=socket.gethostname(),
        pid=live_pid,
        step="run_solver",
    )
    before = read_outcome(run_dir)
    monkeypatch.setenv("HMP_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("MPLBACKEND", "Agg")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as info:
        main(["run", str(config_path), "--no-display"])

    assert info.value.code == EXIT_WRITE_CONFLICT
    err = capsys.readouterr().err
    assert f"{CASE} is running on {socket.gethostname()} (pid {live_pid})" in err
    assert "pulse is fresh" in err
    after = read_outcome(run_dir)
    assert after is not None
    assert after.status == "running", "the loser must not touch the winner"
    assert (after.attempt, after.attempt_id, after.pid) == (1, before.attempt_id, live_pid)
    assert after.written_by == "worker"
    assert not (run_dir / "attempts").exists()
    assert [entry.name for entry in (tmp_path / "runs").iterdir()] == [CASE], "no .v2"


def test_an_unreadable_outcome_never_hides_the_error_of_the_run(tmp_path: Path) -> None:
    """The attempt of this process is still closed, past a folder whose outcome cannot be read."""
    broken = tmp_path / "runs" / "a_broken"
    broken.mkdir(parents=True)
    (broken / "outcome.json").write_text("{not json", encoding="utf-8")
    run_dir = write_attempt(
        tmp_path, "runs/case", status="running", host=socket.gethostname(), pid=os.getpid()
    )

    run_command._close_dead_attempt(tmp_path, RuntimeError("the error of the run"))

    assert read_outcome(run_dir).status == "failed"


def _sealed_config(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / "config.toml").write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")
    (folder / "manifest.json").write_text("{}", encoding="utf-8")
    (folder / "inputs.json").write_text("{}", encoding="utf-8")
    return folder / "config.toml"


def test_frozen_on_the_config_of_a_sealed_run_names_the_replay_verb(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _sealed_config(tmp_path / "runs" / "probe")

    code = _run(monkeypatch, ["hmp", "run", str(config), "--frozen"])

    from hydromodpy.cli.helpers import EXIT_CONFIG

    assert code == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "--frozen does not play a run again" in err
    assert "hmp replay runs/probe" in err


def test_frozen_on_the_config_of_a_published_copy_names_the_replay_verb(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _sealed_config(tmp_path / "publication")
    (config.parent / "PUBLICATION.json").write_text("{}", encoding="utf-8")

    code = _run(monkeypatch, ["hmp", "run", str(config), "--frozen"])

    from hydromodpy.cli.helpers import EXIT_CONFIG

    assert code == EXIT_CONFIG
    assert "hmp replay publication" in capsys.readouterr().err


def test_frozen_on_an_ordinary_config_is_no_replay_and_is_let_through(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "run.toml"
    config.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")

    assert run_command._refuse_frozen_replay(config) is None
