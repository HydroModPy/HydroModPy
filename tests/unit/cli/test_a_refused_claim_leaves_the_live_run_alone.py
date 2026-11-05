"""A second ``hmp run`` on a live case is refused in one sentence and touches nothing.

The case is running elsewhere with a fresh pulse. The newcomer loses the
claim, exits with the write-conflict code and the sentence of the claim, and
the outcome of the worker that holds the case still says ``running``: the
launcher side of the newcomer closes only an attempt this process claimed.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

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
    monkeypatch.setenv("HMP_PROJECT_ROOT", str(tmp_path))
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
