"""Backend-neutral switch asking a solve to run in its own child process.

A solver library driven through a C API keeps global state, so two solves sharing
one interpreter can corrupt each other. The parallel calibration loop turns this
switch on so each worker's solve runs in a spawn child; a single run and the
promotion replay leave it off, keeping the in-process progress bar and avoiding a
per-solve process spawn.

The switch lives here rather than in a backend package because the shared
calibration runner wraps its whole ask/tell loop in it, whatever backend the run
selected. Holding it next to a backend meant importing that backend, and its
binding library, on every calibration: a Boussinesq or a lumped run paid for
MODFLOW it never used. Nothing in this module knows what a solve is; it only
carries the intent from the caller to whichever adapter reads it.

Scoped through a :class:`~contextvars.ContextVar`, not a module global: two
overlapping calibration sessions in one process each get an independent binding,
so one exiting can no longer flip the other back to in-process mid-run. Worker
threads do NOT inherit a ContextVar automatically; the parallel engine propagates
the caller's context to each worker.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_api_isolation_var: ContextVar[bool] = ContextVar("hmp_api_isolation", default=False)

# A non-converging api solve can spin at full CPU indefinitely (the solve call
# never returns), which would wedge a whole parallel calibration on one bad trial.
# The isolated child is killed after this wall-clock budget so the trial is
# recorded as failed and the session continues. Generous next to a normal daily
# solve (~15 min); override per model with ``[<backend>].mf6_api_timeout_s``.
API_ISOLATION_DEFAULT_TIMEOUT_S = 2400.0


@contextmanager
def api_isolation_context(enabled: bool):
    """Isolate api solves in a spawn child process within this dynamic scope.

    The setting is context-local, so overlapping sessions do not clobber each
    other and the token reset restores exactly the caller's prior value.
    Promotion, a single replay run, runs outside the scope and stays in-process.
    """
    token = _api_isolation_var.set(bool(enabled))
    try:
        yield
    finally:
        _api_isolation_var.reset(token)


def api_isolation_enabled() -> bool:
    """Whether the current context asked for api solves to run isolated."""
    return _api_isolation_var.get()


def api_isolation_timeout_s(model) -> float | None:
    """Wall-clock budget for one isolated solve, or the model's own override.

    Reads ``modflow_config.runtime.mf6_api_timeout_s`` by duck typing: a backend
    that carries no such setting gets the default, and one that names it
    differently is free to resolve its own budget instead of calling this.
    """
    runtime = getattr(getattr(model, "modflow_config", None), "runtime", None)
    override = getattr(runtime, "mf6_api_timeout_s", None)
    if override is not None:
        return float(override)
    return API_ISOLATION_DEFAULT_TIMEOUT_S


__all__ = [
    "API_ISOLATION_DEFAULT_TIMEOUT_S",
    "api_isolation_context",
    "api_isolation_enabled",
    "api_isolation_timeout_s",
]
