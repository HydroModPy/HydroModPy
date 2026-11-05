"""The trials of a search in worker processes that last.

Threads share one interpreter, so a trial's Python work runs one at a time: 8
threads gain 1.2, 8 processes gain 4.8. The parent keeps the engine, the journal,
the cache and the catalog. It serializes the prepared state once. Each worker reads
it, builds its own evaluator and answers one trial at a time on its own pipe.

The engine keeps its threads, which only wait now. A thread takes a free worker or
starts one, so a free worker takes the next trial, and a parent always knows which
trial a dead worker held. ``concurrent.futures.ProcessPoolExecutor`` cannot say
that: a dead worker breaks every pending future, and no limit can kill one worker.

Workers start in ``spawn`` and inherit the environment, so the run scratch and the thread budget of the launcher
hold in them. A script that calibrates at ``parallel > 1`` needs the usual
``if __name__ == "__main__":`` guard, because ``spawn`` imports it again, and a
pool built in a worker is refused.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import pickle
import queue
import signal
import threading
import time
from collections.abc import Mapping
from dataclasses import replace
from multiprocessing.connection import Connection, wait
from multiprocessing.process import BaseProcess
from typing import Any

from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.metrics.trial_series_capture import TrialSeriesSink
from hydromodpy.calibration.runners.kept_solves import TrialSolveRetention
from hydromodpy.calibration.runners.sandbox import sandbox_of
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.logging import current_verbosity, set_verbosity
from hydromodpy.core.runtime.bootstrap_hook import ensure_bootstrapped
from hydromodpy.core.stream.geometry import recharge_session

# A non-converging solve can spin forever, which would wedge a whole search on one
# trial. It only has to stop that: a daily solve takes ~15 min alone and several
# times that at width 8. Override with ``[modflow6.runtime] mf6_api_timeout_s``.
DEFAULT_TRIAL_LIMIT_S = 14400.0


def _serve(conn: Connection) -> None:
    """Build the evaluator from the state on ``conn``, then answer trials until the parent goes.

    An exception goes to the parent as the answer, and the worker ends: the parent
    cannot read the worker's stderr, and a failure here is a bug or a bad setup.
    """
    try:
        ensure_bootstrapped()
        evaluator_class, options, keeps_solves, verbosity = pickle.loads(conn.recv_bytes())
        set_verbosity(verbosity)
        # Keeps every solve of this worker until the parent, which alone sees the
        # costs of all the workers, has said which ones the session keeps.
        retention = TrialSolveRetention(None) if keeps_solves else None
        if keeps_solves:
            options["trial_ctx"].kept_solves = retention
        # A class registered at run time in the parent is not known to a new process.
        if not evaluation_registry.is_registered(evaluator_class.evaluator_id):
            evaluation_registry.register(evaluator_class)
        evaluator = evaluation_registry.create(evaluator_class.evaluator_id, **options)
        sink = getattr(evaluator, "trial_series_sink", None)
        # The recharge of two builds is compared inside one worker, not across them.
        with recharge_session("worker"):
            while True:
                request = conn.recv()
                outcome = evaluator.evaluate(request)
                rows = sink.drain() if sink is not None else []
                kept = None
                if retention is not None:
                    kept, _ = retention.take(request.trial_id)
                    retention.promoted(request.trial_id)
                conn.send((outcome, rows, kept))
    except (EOFError, BrokenPipeError):
        return
    except Exception as exc:
        conn.send(exc)


def _worker_main(conn: Connection) -> None:
    """Entry point of a worker, at module scope so that ``spawn`` can import it."""
    # Its own group, so that a limit also kills the solver this worker started.
    os.setsid()
    # The limit lives in the parent. Without it a worker would outlive a parent
    # killed hard (OOM, kill -9, closed terminal), and so would the solver it started.
    threading.Thread(target=_die_with_the_parent, daemon=True).start()
    # libmf6 writes each time step on fd 1, which no Python redirect reaches.
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
    _serve(conn)


def _die_with_the_parent() -> None:
    wait([mp.parent_process().sentinel])
    os.killpg(0, signal.SIGKILL)


class TrialWorkerPool:
    """Answer ``evaluate`` from worker processes, ``width`` of them at most.

    ``options`` are those the registry builds the evaluator class from, and its
    ``trial_ctx`` is the prepared state every worker reads. A worker's first trial
    counts its start, 3 to 10 s, against the wall-clock limit.
    """

    def __init__(self, evaluator_class: type, options: Mapping[str, Any], *, width: int) -> None:
        if mp.current_process().name != "MainProcess":
            raise CalibrationError(
                f"parallel = {width} starts worker processes, and this script runs again in "
                'each of them. Put the calibration under `if __name__ == "__main__":` '
                "in the script, or write parallel = 1."
            )
        self._trial_ctx = options["trial_ctx"]
        self._retention: TrialSolveRetention | None = self._trial_ctx.kept_solves
        runtime = getattr(getattr(self._trial_ctx.base_cfg, "modflow6", None), "runtime", None)
        override = getattr(runtime, "mf6_api_timeout_s", None)
        self._limit_s = float(override) if override is not None else DEFAULT_TRIAL_LIMIT_S
        readable = {**options, "trial_ctx": replace(self._trial_ctx, kept_solves=None)}
        keeps_solves = self._retention is not None
        try:
            self._state = pickle.dumps(
                (evaluator_class, readable, keeps_solves, current_verbosity())
            )
        except (pickle.PicklingError, AttributeError, TypeError) as exc:
            raise CalibrationError(
                f"parallel = {width} runs each trial in its own process, and this search cannot "
                f"be sent to one: {exc}. A metric function must be defined at the top level of a "
                "module, not as a lambda or a closure. Or write parallel = 1."
            ) from exc
        self._context = mp.get_context("spawn")
        self._slots = threading.BoundedSemaphore(width)
        self._idle: queue.SimpleQueue[tuple[BaseProcess, Connection]] = queue.SimpleQueue()
        self._processes: set[BaseProcess] = set()
        self._lock = threading.Lock()
        self._closed = False
        # Read by the caller right after evaluate, on the same thread.
        self.trial_series_sink = TrialSeriesSink()

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        """Run one trial in a free worker. A worker that dies or overruns costs this trial only."""
        started = time.monotonic()
        with self._slots:
            process, conn, fresh = self._free_worker()
            answer = None
            try:
                if fresh:
                    conn.send_bytes(self._state)
                conn.send(request)
                if conn.poll(self._limit_s):
                    answer = conn.recv()
                else:
                    error = (
                        f"it passed its wall-clock limit of {self._limit_s:.0f} s and was killed. "
                        "A long chronicle can simply need more: raise it with "
                        "[modflow6.runtime] mf6_api_timeout_s."
                    )
            except (EOFError, OSError):
                process.join(1.0)
                error = f"its worker process died (exit code {process.exitcode})."
            finally:
                if answer is None or isinstance(answer, Exception):
                    self._kill(process)
                    with sandbox_of(self._trial_ctx, request.trial_id):
                        pass
        if isinstance(answer, Exception):
            raise CalibrationError(
                f"Trial {request.trial_id} failed in its worker process: "
                f"{type(answer).__name__}: {answer}"
            ) from answer
        if answer is None:
            return TrialOutcome(
                cost=float("nan"),
                status="crashed",
                duration_s=time.monotonic() - started,
                error=f"Trial {request.trial_id} did not end: {error}",
            )
        self._idle.put((process, conn))
        outcome, self.trial_series_sink.rows, kept = answer
        if kept is not None:
            self._retention.adopt(kept)
        return outcome

    def close(self) -> None:
        """Kill every worker, the ones still solving included. Nothing starts afterwards."""
        with self._lock:
            self._closed = True
            processes = list(self._processes)
        for process in processes:
            self._kill(process)

    def _free_worker(self) -> tuple[BaseProcess, Connection, bool]:
        """Return a worker and whether it is new, so still waits for the state."""
        with self._lock:
            if self._closed:
                raise CalibrationError("The search has stopped: its workers are closed.")
            try:
                return (*self._idle.get_nowait(), False)
            except queue.Empty:
                parent_end, worker_end = self._context.Pipe()
                process = self._context.Process(target=_worker_main, args=(worker_end,))
                process.start()
                worker_end.close()
                self._processes.add(process)
                return process, parent_end, True

    def _kill(self, process: BaseProcess) -> None:
        with self._lock:
            self._processes.discard(process)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            # Gone already, or killed before it could open its group.
            process.kill()
        process.join()


__all__ = ["TrialWorkerPool"]
