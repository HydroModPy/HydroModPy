"""The writable catalog of a run, opened for the span of one caller.

A run writes rows to the project index and arrays to the Zarr and Parquet
payloads that index points at. The handle that does it owns a DuckDB
connection, a lock and a list of live Zarr handles: it is a resource, not
state, and it does not belong on the :class:`WorkflowContext` that describes
the run. Whoever writes opens it, writes, and lets the ``with`` close it
before returning, so no handle crosses a step boundary and nothing a step
leaves behind pins a connection for the next one.

Reopening costs about a tenth of a second and a run does it a handful of
times. Two handles on one index coexist in a process, so a nested scope is
correct if it ever appears; it is simply slower than passing the open one
down, which is what every caller here does.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import PipelineError

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.results.catalog import Catalog


def _persistence_of(ctx: WorkflowContext):
    """Return the persistence policy this run writes under."""
    results_cfg = getattr(ctx, "effective_results_config", None) or ctx.cfg.simulation.results
    return results_cfg.persistence


def run_is_catalogued(ctx: WorkflowContext) -> bool:
    """Say whether this run has a project index to write to.

    This is the question the pipeline used to ask as ``ctx.store is None``,
    which answered it by accident: a closed handle and a run that was never
    meant to be catalogued gave the same answer. A lightweight run (a
    calibration trial) writes nothing, and neither does a run whose
    ``[simulation.results.persistence] save_catalog`` is false.
    """
    if getattr(getattr(ctx, "execution", None), "lightweight", False):
        return False
    if not _persistence_of(ctx).save_catalog:
        return False
    return getattr(getattr(ctx, "setup", None), "workspace", None) is not None


@contextmanager
def run_catalog(ctx: WorkflowContext) -> Iterator[Catalog]:
    """Open the writable catalog of ``ctx`` for the span of the caller.

    Raises
    ------
    hydromodpy.core.exceptions.PipelineError
        If the run has no workspace to open a catalog in. Callers gate on
        :func:`run_is_catalogued` first.
    """
    from hydromodpy.results.catalog import Catalog

    workspace = getattr(getattr(ctx, "setup", None), "workspace", None)
    if workspace is None:
        raise PipelineError("A workspace is required before opening the catalog of a run.")
    with Catalog.from_workspace(workspace, persistence=_persistence_of(ctx)) as catalog:
        yield catalog


__all__ = ("run_catalog", "run_is_catalogued")
