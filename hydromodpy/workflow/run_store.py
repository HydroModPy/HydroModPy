"""The store of a run, opened for the span of one caller.

A run writes arrays to its Zarr store, tables to its Parquet payloads and
facts to its checkpoint, all inside its own directory. The handle that does
it (:class:`~hydromodpy.results.storage.run_store.RunStore`) holds open
array handles: it is a resource, not state, and it does not belong on the
:class:`WorkflowContext` that describes the run. Whoever writes opens it,
writes, and lets the ``with`` close it before returning, so no handle
crosses a step boundary. The index is never opened here: a run writes its
directory, the indexer reads it afterwards.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import PipelineError
from hydromodpy.results.storage.run_store import RunStore

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext


def _persistence_of(ctx: WorkflowContext):
    """Return the persistence policy this run writes under."""
    return ctx.cfg.simulation.results.persistence


def run_is_persisted(ctx: WorkflowContext) -> bool:
    """Say whether this run writes a run directory at all.

    A lightweight run (a calibration trial) writes nothing, and neither does
    a run whose ``[simulation.results.persistence] save_catalog`` is false.
    Whether a directory exists to hold the run is deliberately not part of
    the answer: a run that asked to be persisted and has nowhere to write is
    a broken run, and :func:`run_store` raises on it.
    """
    if getattr(getattr(ctx, "execution", None), "lightweight", False):
        return False
    return bool(_persistence_of(ctx).save_catalog)


@contextmanager
def run_store(ctx: WorkflowContext) -> Iterator[RunStore]:
    """Open the store of the run of ``ctx`` for the span of the caller.

    Raises
    ------
    hydromodpy.core.exceptions.PipelineError
        If the run has no directory yet. The step that opens the run
        (``prepare_solver``) sets ``ctx.run_dir`` and writes the facts;
        every later step finds them on disk.
    """
    run_dir = getattr(ctx, "run_dir", None)
    if run_dir is None:
        raise PipelineError("The run has no directory yet: prepare_solver opens it.")
    workspace = getattr(getattr(ctx, "setup", None), "workspace", None)
    project_root = getattr(workspace, "project_root", None)
    store = RunStore.open(run_dir, persistence=_persistence_of(ctx), workspace=project_root)
    try:
        yield store
    finally:
        store.close()


__all__ = ("run_is_persisted", "run_store")
