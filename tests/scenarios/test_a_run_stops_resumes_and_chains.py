"""A run stopped through its flag, resumed, and a run played as a chain of windows.

The first scenario stops a long MODFLOW 6 run while it solves, through the flag
``.hmp/stop.json`` that ``request_stop`` writes, then resumes it and compares the
sealed run with the same run played in one go. The second cuts one year into two
windows of six months and compares each window with the year played in one piece.
Both hold to the bit: a resume plays the stopped step again from its start, and
a window starts from the final state of the one before in double precision. The
third stops window 2 of a chain, resumes it by its name without a file, then
replays the sealed window from the configuration it froze.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd
import zarr

from hydromodpy.core.runtime.interrupts import STOP_FLAG_SCHEMA
from hydromodpy.core.state.layout import STOP_FLAG_FILENAME, stop_flag_for
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.record.manifest import read_manifest
from hydromodpy.results.record.record import read_inputs
from hydromodpy.results.record.request_identity import prior_state_digest
from hydromodpy.results.storage.attempt import request_stop
from hydromodpy.results.storage.final_state import read_final_state
from hydromodpy.results.storage.prior_state import prior_state_at
from hydromodpy.results.storage.run_profile import read_profile
from hydromodpy.workflow.record.journal import journal_path
from tests.scenarios.factory import island_files, write_project
from tests.scenarios.launcher import link_binaries

NEEDS = ("mf6", "libmf6.so")
SIGINT_EXIT = 130
POLL_S = 0.02


def _hmp(root: Path, env: Mapping[str, str], *argv: str, log: Path) -> subprocess.Popen[bytes]:
    """Start ``python -m hydromodpy <argv>`` in ``root``, its output in ``log``."""
    handle = open(log, "ab")  # noqa: SIM115 - the child writes it until it ends
    return subprocess.Popen(
        [sys.executable, "-m", "hydromodpy", *argv],
        cwd=root,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )


def _played(root: Path, env: Mapping[str, str], *argv: str, log: Path) -> int:
    process = _hmp(root, env, *argv, log=log)
    return process.wait(timeout=600)


def _tail(log: Path) -> str:
    return log.read_text(encoding="utf-8", errors="replace")[-3000:]


def _step_of(run_dir: Path) -> str | None:
    """The step the pulse of the run names, ``None`` before the first pulse."""
    beat = run_dir / "logs" / "heartbeat.json"
    try:
        return json.loads(beat.read_text(encoding="utf-8")).get("step")
    except (OSError, ValueError):
        return None


def _journal(run_dir: Path) -> dict[str, str]:
    """Each step of the journal of the attempt in progress, with its status."""
    rows = json.loads(journal_path(run_dir).read_text(encoding="utf-8"))["rows"]
    return {row["step_name"]: row["status"] for row in rows}


def _heads(run_dir: Path) -> np.ndarray:
    return np.asarray(zarr.open(str(run_dir / "fields.zarr"), mode="r")["head"][:])


def _times(run_dir: Path) -> np.ndarray:
    return np.asarray(zarr.open(str(run_dir / "fields.zarr"), mode="r")["time"][:])


def _table(run_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_parquet(run_dir / "tables.parquet" / f"{name}.parquet")


def _same_bits(left: np.ndarray, right: np.ndarray) -> bool:
    return left.shape == right.shape and left.tobytes() == right.tobytes()


def test_a_run_stopped_by_its_flag_resumes_to_the_run_played_in_one_go(
    tmp_path: Path, scenario_env, scenario_cache
) -> None:
    link_binaries(scenario_cache, NEEDS)
    root = write_project(tmp_path / "long", island_files("long"))
    log = tmp_path / "long.log"
    assert _played(root, scenario_env, "run", "ref.toml", log=log) == 0, _tail(log)
    run_dir = root / "runs" / "long"

    process = _hmp(root, scenario_env, "run", "project.toml", log=log)
    deadline = time.monotonic() + 600
    while _step_of(run_dir) != "run_solver":
        assert process.poll() is None, f"the run ended before its solve: {_tail(log)}"
        assert time.monotonic() < deadline, "the run never reached its solve"
        time.sleep(POLL_S)
    flag = request_stop(run_dir)
    code = process.wait(timeout=600)

    assert code == SIGINT_EXIT, _tail(log)
    outcome = read_outcome(run_dir)
    assert outcome is not None and outcome.status == "aborted"
    assert outcome.error is not None and outcome.error.type == "StopRequested"
    assert outcome.signal is None
    assert not (run_dir / "manifest.json").exists(), "a stopped run is never sealed"
    assert json.loads(flag.read_text(encoding="utf-8"))["schema"] == STOP_FLAG_SCHEMA
    # The pipeline reads the flag before each step up to the seal, so the stop lands
    # in the solve or, when the solve ended before the flag was written, a step after it.
    journal = _journal(run_dir)
    stopped = [step for step, status in journal.items() if status == "aborted"]
    assert len(stopped) == 1, journal
    assert journal["prepare_solver"] == "completed"
    stopped_step = stopped[0]

    code = _played(root, scenario_env, "run", "project.toml", "--resume", "long", log=log)

    assert code == 0, _tail(log)
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "attempts" / "1" / STOP_FLAG_FILENAME).is_file()
    assert not stop_flag_for(run_dir).exists()
    profile = read_profile(run_dir)
    assert profile is not None
    second = profile.of_attempt(2)
    assert any(line.reused == "prefix" for line in second), "the steps before were rebuilt"
    replayed = [line for line in second if line.kind == "step" and line.name == stopped_step]
    assert replayed and replayed[0].reused == "no", "the stopped step played again"
    ref = root / "runs" / "ref"
    assert _same_bits(_heads(run_dir), _heads(ref))
    for table in ("budgets", "mass_balance"):
        resumed, played = _table(run_dir, table), _table(ref, table)
        values = [name for name in resumed.columns if resumed[name].dtype.kind == "f"]
        assert values, table
        np.testing.assert_array_equal(resumed[values].to_numpy(), played[values].to_numpy())


def test_a_year_cut_in_two_windows_is_the_year_played_in_one_piece(
    tmp_path: Path, scenario_env, scenario_cache
) -> None:
    link_binaries(scenario_cache, NEEDS)
    root = write_project(tmp_path / "windows", island_files("windows"))
    log = tmp_path / "windows.log"
    assert _played(root, scenario_env, "run", "whole.toml", log=log) == 0, _tail(log)

    assert _played(root, scenario_env, "run", "project.toml", log=log) == 0, _tail(log)

    runs = root / "runs"
    whole, first, second = runs / "whole", runs / "island_w1", runs / "island_w2"
    for window in (first, second):
        assert (window / "manifest.json").is_file()
        state = read_final_state(window)
        assert state is not None and state.head.dtype == np.float64
        assert read_profile(window) is not None
    rows = [entry for entry in read_inputs(second).inputs if entry.variable == "initial_state"]
    assert len(rows) == 1
    assert rows[0].path == "runs/island_w1/final_state"
    assert rows[0].sha256 == prior_state_digest(prior_state_at(str(first)))
    assert read_outcome(second).request_id is not None

    heads_whole, heads_first, heads_second = _heads(whole), _heads(first), _heads(second)
    assert len(heads_first) + len(heads_second) == len(heads_whole)
    assert _same_bits(heads_first, heads_whole[: len(heads_first)])
    assert _same_bits(heads_second, heads_whole[len(heads_first) :])
    # Window 2 keeps the time axis of its own periods, from the edge of the window.
    times = _times(whole)
    np.testing.assert_array_equal(_times(second), times[len(heads_first) :])
    sealed = {path: read_manifest(path)["sealed_at"] for path in (first, second)}

    assert _played(root, scenario_env, "run", "project.toml", log=log) == 0, _tail(log)

    assert sorted(path.name for path in runs.iterdir()) == ["island_w1", "island_w2", "whole"]
    assert {path: read_manifest(path)["sealed_at"] for path in (first, second)} == sealed
    assert "identical to completed run" in _tail(log)
    shown = subprocess.run(
        [sys.executable, "-m", "hydromodpy", "show", "island_w2"],
        cwd=root,
        env=dict(scenario_env),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert shown.returncode == 0, shown.stderr[-2000:]
    assert "Profile" in shown.stdout
    assert "solve" in shown.stdout


def test_a_window_stopped_by_its_flag_resumes_by_its_name_and_replays_from_its_source(
    tmp_path: Path, scenario_env, scenario_cache
) -> None:
    link_binaries(scenario_cache, NEEDS)
    root = write_project(tmp_path / "chain", island_files("long_windows"))
    log = tmp_path / "chain.log"
    runs = root / "runs"
    first, second = runs / "chain_w1", runs / "chain_w2"

    process = _hmp(root, scenario_env, "run", "project.toml", log=log)
    deadline = time.monotonic() + 600
    while _step_of(second) != "run_solver":
        assert process.poll() is None, f"the chain ended before window 2 solved: {_tail(log)}"
        assert time.monotonic() < deadline, "window 2 never reached its solve"
        time.sleep(POLL_S)
    request_stop(second)
    assert process.wait(timeout=600) == SIGINT_EXIT, _tail(log)
    assert (first / "manifest.json").is_file()
    assert not (second / "manifest.json").exists(), "a stopped window is never sealed"
    sealed_first = read_manifest(first)["sealed_at"]

    # No file: the resume reads the configuration window 2 froze when it was claimed.
    code = _played(root, scenario_env, "run", "--resume", "chain_w2", log=log)

    assert code == 0, _tail(log)
    assert (second / "manifest.json").is_file()
    assert read_manifest(first)["sealed_at"] == sealed_first, "window 1 was played again"
    assert sorted(path.name for path in runs.iterdir()) == ["chain_w1", "chain_w2"]
    rows = [entry for entry in read_inputs(second).inputs if entry.variable == "initial_state"]
    assert [row.path for row in rows] == ["runs/chain_w1/final_state"]

    # The file window 2 froze is the request of window 2, from the state window 1 left,
    # so a plain run of it gives the sealed window back, and hmp replay plays it again.
    before = {path.name for path in runs.iterdir()}
    code = _played(root, scenario_env, "run", "runs/chain_w2/config.toml", log=log)

    assert code == 0, _tail(log)
    assert {path.name for path in runs.iterdir()} == before
    assert "identical to completed run" in _tail(log)

    code = _played(root, scenario_env, "replay", "runs/chain_w2", log=log)

    assert code == 0, _tail(log)
    added = sorted({path.name for path in runs.iterdir()} - before)
    assert len(added) == 1, added
    replay = runs / added[0]
    replayed = [entry for entry in read_inputs(replay).inputs if entry.variable == "initial_state"]
    assert [(row.path, row.sha256) for row in replayed] == [(rows[0].path, rows[0].sha256)]
    assert _same_bits(_heads(replay), _heads(second))
