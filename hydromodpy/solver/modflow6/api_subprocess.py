"""Process-isolated MODFLOW 6 API (libmf6) runner.

``libmf6`` holds global Fortran state, so two in-process API solves sharing one
Python process (the calibration ``ThreadPoolExecutor`` threads) would corrupt
each other. Running each API solve in its own spawned child process gives it a
private ``libmf6`` instance, which makes the in-process API runner safe under
parallel calibration (and isolates a solver crash from the parent).

The exposed-band (marnage) runoff callback is rebuilt in the child from the
picklable :class:`~hydromodpy.solver.modflow6.lake_band_runoff.LakeBandRunoffSpec`
list, so no closure has to cross the process boundary. A custom, non-serializable
developer callback is NOT supported here; that path stays in-process in
:func:`hydromodpy.solver.modflow6.run._run_via_api` (and is single-threaded).

Spawn (not fork) is mandatory: a forked child would inherit a libmf6 the parent
may already have loaded, defeating the isolation.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue as queue_mod
from collections.abc import Sequence
from contextlib import contextmanager
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import SolverError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.solver.modflow6.lake_band_runoff import LakeBandRunoffSpec

logger = get_logger(__name__)

__all__ = ["run_mf6_api_isolated"]

# How often the parent polls for the child's result, so a child that dies
# without posting one (a libmf6 segfault) is detected promptly instead of
# hanging on an empty queue.
_POLL_SECONDS = 1.0


def _api_subprocess_entry(
    result_queue,
    sim_ws: str,
    band_specs: list,
    lib_path: str | None,
    progress_queue=None,
) -> None:
    """Child entry point: rebuild the callback and run the API solve.

    Posts ``(True, success_bool)`` on a completed solve or ``(False, detail)``
    when the run raises. When a ``progress_queue`` is given, it also relays
    ``(completed, total)`` solve progress so the parent can render a live bar the
    child process cannot draw itself. Runs at module scope so ``spawn`` can import it.
    """
    try:
        from hydromodpy.core import progress
        from hydromodpy.solver.modflow6.api_runner import Mf6ApiContext, run_mf6_api

        if band_specs:
            from hydromodpy.solver.modflow6.lake_band_runoff import (
                make_exposed_band_runoff_callback,
            )

            callback = make_exposed_band_runoff_callback(band_specs)
        else:

            def callback(ctx: Mf6ApiContext) -> None:
                return None

        sink = None
        if progress_queue is not None:

            def sink(completed: int, total: int | None) -> None:
                try:
                    progress_queue.put_nowait((completed, total))
                except Exception:  # noqa: BLE001 - progress relay must never fail the solve
                    pass

        # The child's own progress bar cannot render (only the main process drives
        # the terminal), so suppress it and redirect the stdout fd; the sink relays
        # progress to the parent instead.
        with progress.suppressed(), _silence_stdout_fd():
            success = run_mf6_api(
                sim_ws, callback, lib_path=lib_path, verbose=False, progress_sink=sink
            )
        result_queue.put((True, bool(success)))
    except BaseException as exc:  # noqa: BLE001 - relayed to the parent verbatim
        import traceback

        result_queue.put((False, f"{exc!r}\n{traceback.format_exc()}"))


@contextmanager
def _silence_stdout_fd():
    """Redirect the child's OS stdout (fd 1) to devnull.

    libmf6 / modflowapi write per-timestep progress through the Fortran/C stdout
    file descriptor, which ``contextlib.redirect_stdout`` cannot reach; on a
    daily multi-thousand-period solve that floods the log. Redirecting fd 1 keeps
    the parallel calibration console clean. The verdict is read from the listing,
    so nothing is lost. stderr (fd 2) stays intact for crash output.
    """
    saved = os.dup(1)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 1)
        yield
    finally:
        os.dup2(saved, 1)
        os.close(devnull)
        os.close(saved)


def _drain_progress(progress_queue, handle) -> None:
    """Apply every buffered ``(completed, total)`` relay to the live bar."""
    while True:
        try:
            completed, total = progress_queue.get_nowait()
        except queue_mod.Empty:
            return
        except (OSError, ValueError):  # queue closed as the child exits
            return
        if total is not None:
            handle.update(total=float(total))
        handle.update(completed=float(completed))


def run_mf6_api_isolated(
    sim_ws: str | PathLike[str],
    *,
    band_specs: Sequence[LakeBandRunoffSpec] | None = None,
    lib_path: str | PathLike[str] | None = None,
    timeout: float | None = None,
    label: str | None = None,
    _entry: Any = _api_subprocess_entry,
) -> bool:
    """Run :func:`run_mf6_api` in a dedicated ``spawn`` child process.

    Parameters mirror :func:`run_mf6_api`, plus ``band_specs`` (the exposed-band
    runoff coupling, rebuilt into the callback in the child) and an optional
    ``timeout`` in seconds. The child relays solve progress back through a queue,
    so this call shows a live "Solving <label>" bar in the parent process even
    though the child cannot draw one. Returns the convergence flag. Raises
    :class:`SolverError` when the child fails or dies without a result. ``_entry``
    is the child target; it exists only so tests can inject a spawn-importable
    stub without a real solve.
    """
    from hydromodpy.core import progress

    ctx = mp.get_context("spawn")
    result_queue: mp.Queue = ctx.Queue()
    progress_queue: mp.Queue = ctx.Queue()
    proc = ctx.Process(
        target=_entry,
        args=(
            result_queue,
            str(sim_ws),
            list(band_specs or []),
            None if lib_path is None else str(lib_path),
            progress_queue,
        ),
        daemon=False,
    )
    proc.start()

    description = f"Solving {label or Path(sim_ws).name}"
    result: tuple[bool, object] | None = None
    waited = 0.0
    with progress.task(description, total=None) as bar:
        while True:
            _drain_progress(progress_queue, bar)
            try:
                result = result_queue.get(timeout=_POLL_SECONDS)
                break
            except queue_mod.Empty:
                if not proc.is_alive():
                    # Drain a result that landed between the get() and is_alive().
                    try:
                        result = result_queue.get_nowait()
                    except queue_mod.Empty:
                        result = None
                    break
                waited += _POLL_SECONDS
                if timeout is not None and waited >= timeout:
                    proc.terminate()
                    proc.join(5)
                    raise SolverError(
                        f"MF6 API subprocess for {sim_ws} timed out after {timeout:.0f}s."
                    ) from None
        _drain_progress(progress_queue, bar)

    proc.join(30)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)

    if result is None:
        raise SolverError(
            f"MF6 API subprocess for {sim_ws} exited (code {proc.exitcode}) without "
            "a result; libmf6 likely crashed."
        )
    ok, payload = result
    if not ok:
        raise SolverError(f"MF6 API subprocess for {sim_ws} failed:\n{payload}")
    return bool(payload)
