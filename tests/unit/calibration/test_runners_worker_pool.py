"""Tests of `runners.worker_pool`: real spawned workers, on evaluators that need no solver."""

from __future__ import annotations

import gc
import json
import math
import multiprocessing as mp
import os
import pickle
import signal
import struct
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from multiprocessing.connection import Connection
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

import hydromodpy
from hydromodpy.calibration.evaluation import registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.metrics.trial_series_capture import TrialSeriesSink
from hydromodpy.calibration.runners import worker_pool
from hydromodpy.calibration.runners.kept_solves import TrialSolveRetention
from hydromodpy.calibration.runners.pipeline_evaluator import PipelineTrialEvaluator
from hydromodpy.calibration.runners.trial import TrialContext
from hydromodpy.calibration.runners.worker_pool import (
    DEFAULT_TRIAL_LIMIT_S,
    TrialWorkerPool,
    _serve,
)
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.logging import current_verbosity
from hydromodpy.solver.base.plan import RunExecutionResult

pytestmark = pytest.mark.allow_subprocess

DIE, HANG, RAISE, HALF = -1.0, -2.0, -3.0, -4.0


class _Config(BaseModel):
    K: float = 1.0


def _cost(ctx, *, objective: str, variable: str) -> tuple[float, dict[str, float]]:
    """A cost with all its digits, at the top level so that it crosses to a worker."""
    del objective, variable
    K = ctx.cfg.K
    return math.log10(K) ** 2 / 3.0 + math.sin(K * 1e5), {"a": math.exp(K * 1e4) / 7.0}


class _Scripted:
    """Does what the sample says: dies, hangs with a child process, fails, or keeps a solve."""

    evaluator_id: ClassVar[str] = "scripted_for_the_pool"
    needs_prepared_model: ClassVar[bool] = True

    def __init__(self, *, trial_ctx: TrialContext) -> None:
        self._trial_ctx = trial_ctx
        self.trial_series_sink = TrialSeriesSink()

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        cost = request.values["cost"]
        folder = _folder(self._trial_ctx, request.trial_id)
        folder.mkdir()
        if cost == DIE:
            os._exit(7)
        if cost == RAISE:
            raise ValueError("the real reason")
        if cost == HALF:
            # The header of a message of 100 bytes and 6 of them, then the end of the pipe.
            [conn] = [item for item in gc.get_objects() if isinstance(item, Connection)]
            os.write(conn.fileno(), struct.pack("!i", 100) + b"abcdef")
            os._exit(0)
        if cost == HANG:
            child = subprocess.Popen(["sleep", "60"])
            (folder.parent / "child.pid").write_text(str(child.pid))
            time.sleep(60)
        self.trial_series_sink.record(
            output="o", station="s", times=[1], simulated=[cost], observed=[0.0]
        )
        retention = self._trial_ctx.kept_solves
        if retention is not None:
            result = RunExecutionResult(None, folder, {"m": cost})
            retention.offer(request.trial_id, cost, [folder], {"flow": result})
        return TrialOutcome(
            cost=cost, status="completed", duration_s=0.0, components={"pid": float(os.getpid())}
        )


def _folder(trial_ctx: TrialContext, trial_id: int) -> Path:
    return trial_ctx.ctx.setup.workspace.solver_scratch_folder / f"toy_trial{trial_id:06d}"


def _trial_ctx(tmp_path: Path, **context) -> TrialContext:
    workspace = SimpleNamespace(solver_scratch_folder=tmp_path)
    return TrialContext(
        base_cfg=_Config(),
        ctx=SimpleNamespace(
            setup=SimpleNamespace(run_id="toy", workspace=workspace),
            data_plan=None,
            loaded_data=None,
            execution=SimpleNamespace(rng=None),
        ),
        earliest=0,
        downstream_steps=(),
        override_paths={"K": "K"},
        workspace=tmp_path,
        cfg_path=tmp_path / "project.toml",
        **context,
    )


def _pool(trial_ctx: TrialContext) -> closing[TrialWorkerPool]:
    return closing(TrialWorkerPool(_Scripted, {"trial_ctx": trial_ctx}, width=1))


def _ask(pool: TrialWorkerPool, trial_id: int, cost: float) -> TrialOutcome:
    return pool.evaluate(TrialRequest(trial_id=trial_id, values={"cost": cost}))


def _alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def _child_of_the_hanging_trial_is_dead(tmp_path: Path) -> bool:
    time.sleep(0.5)
    return not _alive(int((tmp_path / "child.pid").read_text()))


def test_a_trial_in_a_process_gives_the_digits_of_a_trial_in_a_thread(tmp_path: Path) -> None:
    hydromodpy.bootstrap()
    cfg = SimpleNamespace(
        objective="nse", variable="head", reject_water_budget_above=None, persist_trial_series=False
    )
    options = {"cfg": cfg, "trial_ctx": _trial_ctx(tmp_path), "metric_fn": _cost}
    request = TrialRequest(trial_id=3, values={"K": 3.7e-5})

    with ThreadPoolExecutor(1) as thread:
        in_thread = thread.submit(PipelineTrialEvaluator(**options).evaluate, request).result()
    with closing(TrialWorkerPool(PipelineTrialEvaluator, options, width=1)) as pool:
        in_process = pool.evaluate(request)

    assert (in_thread.status, in_process.status) == ("completed", "completed")
    assert in_thread.cost == in_process.cost == 6.017109178612426
    assert in_thread.components == in_process.components == {"a": 0.2068192306661892}


def test_the_parent_decides_which_solves_stay_and_a_worker_lasts(tmp_path: Path) -> None:
    retention = TrialSolveRetention(1)
    trial_ctx = _trial_ctx(tmp_path, kept_solves=retention)
    with _pool(trial_ctx) as pool:
        with ThreadPoolExecutor(2) as threads:
            first, second = threads.map(_ask, [pool, pool], [1, 2], [0.5, 0.2])
        third = _ask(pool, 3, 0.9)
        rows = pool.trial_series_sink.drain()

    # Width 1: two threads asking at once are served one after the other, by one worker.
    assert first.components == second.components == third.components
    assert not _alive(int(third.components["pid"]))
    assert [row["simulated"] for row in rows] == [0.9]
    assert [_folder(trial_ctx, n).exists() for n in (1, 2, 3)] == [False, True, False]
    kept, _ = retention.take(2)
    assert (kept.trial_id, kept.cost, kept.results["flow"].metrics) == (2, 0.2, {"m": 0.2})
    assert retention.take(1)[0] is None and retention.take(3)[0] is None
    with pytest.raises(CalibrationError, match="closed"):
        _ask(pool, 4, 0.1)


def test_a_dead_worker_costs_its_trial_alone_and_a_stop_kills_a_solving_one(tmp_path: Path) -> None:
    trial_ctx = _trial_ctx(tmp_path)
    with _pool(trial_ctx) as pool:
        before = _ask(pool, 1, 0.5)
        dead = _ask(pool, 2, DIE)
        after = _ask(pool, 3, 0.25)
        # Reaches this thread while it waits, as a Ctrl-C does.
        threading.Timer(1.0, os.kill, [os.getpid(), signal.SIGINT]).start()
        with pytest.raises(KeyboardInterrupt):
            _ask(pool, 4, HANG)

    assert dead.status == "crashed" and math.isnan(dead.cost)
    assert dead.error == "Trial 2 did not end: its worker process died (exit code 7)."
    assert (after.status, after.cost) == ("completed", 0.25)
    assert after.components != before.components
    assert not _alive(int(after.components["pid"]))
    assert not _folder(trial_ctx, 2).exists() and not _folder(trial_ctx, 4).exists()
    assert _child_of_the_hanging_trial_is_dead(tmp_path)


def test_half_an_answer_costs_its_trial_alone(tmp_path: Path) -> None:
    with _pool(_trial_ctx(tmp_path)) as pool:
        half = _ask(pool, 1, HALF)
        after = _ask(pool, 2, 0.25)

    assert half.status == "crashed" and math.isnan(half.cost)
    assert half.error == "Trial 1 did not end: its worker process died (exit code 0)."
    assert 0 <= half.duration_s < 60
    assert (after.status, after.cost) == ("completed", 0.25)


def test_an_exception_of_a_worker_stops_the_search_with_its_reason(tmp_path: Path) -> None:
    trial_ctx = _trial_ctx(tmp_path)
    with _pool(trial_ctx) as pool:
        with pytest.raises(CalibrationError, match=r"Trial 3 failed .*ValueError: the real reason"):
            _ask(pool, 3, RAISE)
        after = _ask(pool, 4, 0.25)

    assert not _folder(trial_ctx, 3).exists()
    assert (after.status, after.cost) == ("completed", 0.25)


def test_a_worker_whose_setup_fails_tells_the_parent_why() -> None:
    conn = Mock(recv_bytes=Mock(return_value=b"not a state"))

    _serve(conn)

    [error] = conn.send.call_args.args
    assert isinstance(error, pickle.UnpicklingError)


def test_a_pool_is_refused_in_a_worker_with_the_guard_to_write(monkeypatch) -> None:
    monkeypatch.setattr(mp.current_process(), "name", "SpawnProcess-1")
    with pytest.raises(CalibrationError, match=r"parallel = 2 .*if __name__ == .*__main__.*:"):
        TrialWorkerPool(_Scripted, {}, width=2)


_PARENT_OF_A_HANGING_POOL = """
import importlib, json, sys
from pathlib import Path
sys.path[:] = json.loads(sys.argv[1])
module = importlib.import_module(sys.argv[2])
pool = module.TrialWorkerPool(
    module._Scripted, {"trial_ctx": module._trial_ctx(Path(sys.argv[3]))}, width=1
)
pool.evaluate(module.TrialRequest(trial_id=1, values={"cost": module.HANG}))
"""


def test_workers_do_not_outlive_a_parent_killed_hard(tmp_path: Path) -> None:
    argv = [json.dumps(sys.path), __name__, str(tmp_path)]
    parent = subprocess.Popen([sys.executable, "-c", _PARENT_OF_A_HANGING_POOL, *argv])
    try:
        pid_file = tmp_path / "child.pid"
        for _ in range(300):
            if pid_file.exists() and pid_file.read_text():
                break
            time.sleep(0.1)
        child = int(pid_file.read_text())
        # The solver of the trial hangs under the worker, which hangs under the parent.
        worker = int(Path(f"/proc/{child}/stat").read_text().rsplit(")", 1)[1].split()[1])
        assert _alive(worker) and _alive(child)
        parent.kill()
        parent.wait()
        time.sleep(1.0)
    finally:
        parent.kill()

    assert not _alive(worker) and not _alive(child)


def test_a_trial_past_its_limit_is_killed_with_the_solver_it_started(tmp_path: Path) -> None:
    trial_ctx = _trial_ctx(tmp_path)
    runtime = SimpleNamespace(mf6_api_timeout_s=30.0)
    trial_ctx.base_cfg = SimpleNamespace(modflow6=SimpleNamespace(runtime=runtime))
    with _pool(trial_ctx) as pool:
        assert pool._limit_s == 30.0
        before = _ask(pool, 1, 0.5)
        pool._limit_s = 2.0
        stuck = _ask(pool, 2, HANG)
        pool._limit_s = 30.0
        after = _ask(pool, 3, 0.25)

    assert stuck.status == "crashed" and math.isnan(stuck.cost)
    assert "wall-clock limit of 2 s" in stuck.error
    assert "[modflow6.runtime] mf6_api_timeout_s" in stuck.error
    assert not _folder(trial_ctx, 2).exists()
    assert _child_of_the_hanging_trial_is_dead(tmp_path)
    assert after.status == "completed" and after.components != before.components


def test_the_limit_is_the_default_without_a_modflow6_section(tmp_path: Path) -> None:
    with _pool(_trial_ctx(tmp_path)) as pool:
        assert pool._limit_s == DEFAULT_TRIAL_LIMIT_S == 14400.0


def test_a_state_that_cannot_cross_is_refused_with_what_to_write(tmp_path: Path) -> None:
    options = {"trial_ctx": _trial_ctx(tmp_path), "metric_fn": lambda: None}
    with pytest.raises(CalibrationError, match=r"parallel = 3 .*top level.*parallel = 1"):
        TrialWorkerPool(_Scripted, options, width=3)


@pytest.mark.parametrize(
    ("keeps_solves", "registered"), [(False, False), (True, False), (False, True)]
)
def test_a_worker_sends_the_outcome_the_rows_and_the_solve_it_kept(
    tmp_path: Path, keeps_solves: bool, registered: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In this process, because a coverage run does not see a spawned worker."""
    monkeypatch.setattr(registry.evaluators, "classes", {})
    if registered:
        registry.evaluators.register(_Scripted)
    trial_ctx = _trial_ctx(tmp_path)
    state = pickle.dumps((_Scripted, {"trial_ctx": trial_ctx}, keeps_solves, current_verbosity()))
    request = TrialRequest(trial_id=5, values={"cost": 0.5})
    conn = Mock(recv_bytes=Mock(return_value=state), recv=Mock(side_effect=[request, EOFError()]))

    _serve(conn)

    conn.send.assert_called_once()
    outcome, rows, kept = conn.send.call_args.args[0]
    assert (outcome.status, outcome.cost) == ("completed", 0.5)
    assert [(row["output"], row["station"], row["simulated"]) for row in rows] == [("o", "s", 0.5)]
    assert (kept is not None) is keeps_solves
    if keeps_solves:
        assert (kept.trial_id, kept.folders) == (5, (_folder(trial_ctx, 5),))


class _Sinkless(_Scripted):
    evaluator_id: ClassVar[str] = "sinkless_for_the_pool"

    def __init__(self, *, trial_ctx: TrialContext) -> None:
        pass

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        return TrialOutcome(cost=1.0, status="completed", duration_s=0.0)


def test_a_worker_whose_evaluator_has_no_series_sink_sends_no_rows(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(registry.evaluators, "classes", {})
    state = pickle.dumps(
        (_Sinkless, {"trial_ctx": _trial_ctx(tmp_path)}, False, current_verbosity())
    )
    conn = Mock(
        recv_bytes=Mock(return_value=state),
        recv=Mock(side_effect=[TrialRequest(trial_id=1, values={}), EOFError()]),
    )

    _serve(conn)

    assert conn.send.call_args.args[0][1:] == ([], None)


def test_a_worker_leaves_its_group_silences_fd_one_and_serves(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(worker_pool.os, "setsid", lambda: calls.append("setsid"))
    monkeypatch.setattr(
        worker_pool.os, "open", lambda path, flags: calls.append(("open", path)) or 7
    )
    monkeypatch.setattr(
        worker_pool.os, "dup2", lambda fd, target: calls.append(("dup2", fd, target))
    )
    monkeypatch.setattr(worker_pool, "_serve", lambda conn: calls.append(("serve", conn)))
    monkeypatch.setattr(
        worker_pool.threading,
        "Thread",
        lambda target, daemon: SimpleNamespace(
            start=lambda: calls.append(("watch", target, daemon))
        ),
    )

    worker_pool._worker_main("conn")

    assert calls == [
        "setsid",
        ("watch", worker_pool._die_with_the_parent, True),
        ("open", os.devnull),
        ("dup2", 7, 1),
        ("serve", "conn"),
    ]


def test_a_worker_kills_its_group_when_the_parent_goes(monkeypatch) -> None:
    kills = []
    monkeypatch.setattr(worker_pool.mp, "parent_process", lambda: SimpleNamespace(sentinel="s"))
    monkeypatch.setattr(worker_pool, "wait", lambda sentinels: kills.append(sentinels))
    monkeypatch.setattr(worker_pool.os, "killpg", lambda group, sig: kills.append((group, sig)))

    worker_pool._die_with_the_parent()

    assert kills == [["s"], (0, signal.SIGKILL)]
