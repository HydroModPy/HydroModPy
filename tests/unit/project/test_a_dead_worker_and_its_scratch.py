"""A worker of this host whose pid is gone, and the machine scratch.

An OOM kill writes nothing: the outcome still says ``running`` with a fresh
pulse. On the host of the worker the process table proves the death, so the
reader says ``stale`` at once and ``hmp catalog watch`` says ``dead``. Under
``HMP_SCRATCH_ROOT`` the preprocessing of a run leaves the project, as the
solver folders already did.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

import hydromodpy.results.outcome as outcome_module
from hydromodpy.core.state.paths import (
    SCRATCH_ROOT_ENV,
    run_scratch,
    scratch_dir_for,
    scratch_root_for,
)
from hydromodpy.results.outcome import Outcome, effective_status, write_outcome

DEAD_PID = 424242


def _running(run_dir: Path, *, host: str, pid: int) -> None:
    run_dir.mkdir(parents=True)
    write_outcome(
        run_dir,
        Outcome(
            case_id="case",
            attempt=1,
            attempt_id="a1",
            status="running",
            written_by="worker",
            started_at=datetime.now(UTC),
            host=host,
            pid=pid,
        ),
    )


def _dead_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(outcome_module, "process_is_alive", lambda pid: pid != DEAD_PID)


def test_a_dead_pid_of_this_host_reads_stale_with_a_fresh_pulse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dead_pid(monkeypatch)
    _running(tmp_path / "dead", host=socket.gethostname(), pid=DEAD_PID)
    _running(tmp_path / "alive", host=socket.gethostname(), pid=os.getpid())
    _running(tmp_path / "elsewhere", host="node-12", pid=DEAD_PID)

    assert effective_status(tmp_path / "dead") == "stale"
    assert effective_status(tmp_path / "alive") == "running"
    assert effective_status(tmp_path / "elsewhere") == "running"


def test_watch_says_dead_for_a_proven_death(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from hydromodpy.cli.commands.catalog import watch

    _dead_pid(monkeypatch)
    project = tmp_path / "p"
    (project / "project.toml").parent.mkdir(parents=True)
    (project / "project.toml").write_text("", encoding="utf-8")
    _running(project / "runs" / "case", host=socket.gethostname(), pid=DEAD_PID)
    args = argparse.Namespace(
        workspace=str(project), stale_minutes=5.0, format="json", verbosity=None
    )

    watch.run(args)

    rows = json.loads(capsys.readouterr().out)["data"]
    assert [(row["rel_dir"], row["dead"]) for row in rows] == [("runs/case", True)]


def test_the_preprocessing_scratch_honours_the_machine_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "campaign"
    project.mkdir()
    machine = tmp_path / "node-scratch"
    monkeypatch.delenv("HMP_RUN_SCRATCH", raising=False)
    monkeypatch.setenv(SCRATCH_ROOT_ENV, str(machine))

    assert scratch_root_for(project) == machine / "campaign"
    with run_scratch(project, "alpha-base") as key:
        folder = scratch_dir_for(project)
        assert folder == machine / "campaign" / key
    assert not (project / ".hmp" / "scratch").exists()
