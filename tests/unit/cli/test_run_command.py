"""``hmp run``: what it says around a run, and how it refuses a case that is already running.

The solver is never played. A live case is one with a fresh heartbeat on this host.
"""

from __future__ import annotations

import importlib
import os
import socket
import sys
from pathlib import Path

import pytest

from hydromodpy.cli.commands import run as run_command
from hydromodpy.cli.commands.run import HEAD_ONLY_MESSAGE
from hydromodpy.cli.exit_codes import EXIT_WRITE_CONFLICT
from hydromodpy.cli.main import main
from hydromodpy.results.outcome import read_outcome
from tests._helpers.sealed_runs import write_attempt
from tests.unit.project._helpers import DEM, PROJECT_TOML

from ._hmp import run_main as _run


@pytest.mark.fast
def test_overview_recap(tmp_path, monkeypatch, capsys):
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


def test_head_only_window(monkeypatch, tmp_path: Path, capsys) -> None:
    config = tmp_path / "run.toml"
    config.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")
    # A window that stops before the model keeps no run: the runner gives nothing back.
    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.run_simulation", lambda *a, **k: None)

    code = _run(monkeypatch, ["hmp", "run", str(config), "--until", "build_mesh", "--case", "x"])

    assert code == 0
    assert HEAD_ONLY_MESSAGE in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()


def test_window_reaching_the_model(monkeypatch, tmp_path: Path, capsys) -> None:
    config = tmp_path / "run.toml"
    config.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")
    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.run_simulation", lambda *a, **k: None)

    code = _run(monkeypatch, ["hmp", "run", str(config), "--until", "run_solver"])

    assert code == 0
    assert HEAD_ONLY_MESSAGE not in capsys.readouterr().err


def test_until_on_an_overview(monkeypatch, tmp_path, capsys) -> None:
    config_path = tmp_path / "overview.toml"
    config_path.write_text('[workflow]\nmode = "overview"\n', encoding="utf-8")

    code = _run(monkeypatch, ["hmp", "run", str(config_path), "--until", "load_data"])

    from hydromodpy.cli.exit_codes import EXIT_CONFIG

    assert code == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "detected 'overview'" in err
    assert "workflow.mode=simulation" not in err


CASE = "declared_name"  # [simulation] name of the project TOML, which names the case


def test_live_case_is_refused(
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


def test_index_built_after_the_worker(tmp_path: Path) -> None:
    from hydromodpy.core.state.layout import catalog_path_for
    from tests._helpers.sealed_runs import make_project, seal_run

    project = make_project(tmp_path / "ws")
    seal_run(project, "case")
    assert not catalog_path_for(project).exists()

    run_command._index_after_worker(project)

    assert catalog_path_for(project).is_file()


def test_failing_index(monkeypatch, tmp_path: Path, caplog) -> None:
    from tests._helpers.sealed_runs import make_project, seal_run

    project = make_project(tmp_path / "ws")
    seal_run(project, "case")

    def refuse(_root):
        raise RuntimeError("the index does not read")

    monkeypatch.setattr("hydromodpy.results.catalog.indexer.index_after_run", refuse)

    run_command._index_after_worker(project)

    assert "Index not refreshed after the run: the index does not read" in caplog.text


def _sealed_config(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / "config.toml").write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")
    (folder / "manifest.json").write_text("{}", encoding="utf-8")
    (folder / "inputs.json").write_text("{}", encoding="utf-8")
    return folder / "config.toml"


def test_frozen_on_a_sealed_config(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    config = _sealed_config(tmp_path / "runs" / "probe")

    code = _run(monkeypatch, ["hmp", "run", str(config), "--frozen"])

    from hydromodpy.cli.exit_codes import EXIT_CONFIG

    assert code == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "--frozen does not play a run again" in err
    assert "hmp replay runs/probe" in err


def test_frozen_on_an_ordinary_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "run.toml"
    config.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")

    assert run_command._refuse_frozen_replay(config) is None
