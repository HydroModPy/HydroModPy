"""api-isolation scope is context-local, and the engine propagates it to workers.

Replaces a module global whose save/restore raced when two calibration sessions
overlapped in one process (finding 147).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from hydromodpy.solver.modflow6.run import api_isolation_context, api_isolation_enabled


def test_default_is_in_process() -> None:
    assert api_isolation_enabled() is False


def test_scope_sets_and_restores() -> None:
    assert api_isolation_enabled() is False
    with api_isolation_context(True):
        assert api_isolation_enabled() is True
    assert api_isolation_enabled() is False


def test_value_is_context_local_not_global() -> None:
    # Capturing the context inside the scope keeps the value even after the scope
    # exits. A module global would read False here (the scope restored it); the
    # ContextVar snapshot still reads True.
    with api_isolation_context(True):
        snapshot = copy_context()
    assert api_isolation_enabled() is False
    assert snapshot.run(api_isolation_enabled) is True


def test_overlapping_session_does_not_clobber() -> None:
    # A second session opening and closing in its own context must not flip our
    # binding back to in-process while we are still active.
    with api_isolation_context(True):

        def other_session() -> None:
            with api_isolation_context(False):
                assert api_isolation_enabled() is False

        copy_context().run(other_session)
        assert api_isolation_enabled() is True


def test_engine_style_propagation_reaches_workers() -> None:
    # Mirror engine._evaluate_batch: each worker runs a per-task copy of the
    # caller's context, so all workers observe the isolation scope.
    with api_isolation_context(True):
        tasks = [copy_context() for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            seen = list(pool.map(lambda ctx: ctx.run(api_isolation_enabled), tasks))
    assert seen == [True, True, True, True]


def test_bare_worker_thread_would_miss_the_scope() -> None:
    # Proves the propagation is load-bearing: without a copied context, a worker
    # thread reads the default (False), which would silently disable isolation.
    with api_isolation_context(True):
        with ThreadPoolExecutor(max_workers=2) as pool:
            bare = list(pool.map(lambda _i: api_isolation_enabled(), range(2)))
    assert bare == [False, False]
