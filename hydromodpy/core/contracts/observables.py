"""Named observables a solver adapter can produce from one run.

This is the solver-facing half of calibration: what a backend must be able to
read back while a trial is still running, before anything reaches Zarr or
Parquet. A trial evaluates in lightweight mode, where the extraction step is
short-circuited and only the native solver files exist, so the adapter is the
only thing that can answer.

Not to be confused with ``analysis/comparison/runtime/observables.py``, which
reads a run that has already been written and serves the comparison report.
The two never meet: this one is a request made of a live run, that one is a
query over stored results.

Why ``core``: ``solver``, ``calibration``, ``results`` and ``analysis`` share
no layer but ``core`` and ``schema``, and all four have to agree on what an
observable is. ``core/contracts/solver_registry.py`` is the same pattern.

The contract is a batch: an adapter receives every request for a run at once,
so it opens each binary file once instead of once per request, and a backend
driven through an API knows before the solve which timesteps it must keep.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:  # pragma: no cover - a runtime pandas import costs half a second
    import pandas as pd

ObservableSupport = Literal["domain", "cell", "cells", "boundary", "lake"]
"""Where an observable lives: the whole domain, one cell, every cell of the
mesh, a named boundary, or a named lake.

There is no ``point`` support on purpose. A request carries a cell, never
coordinates, so a caller holding an ``(x, y)`` resolves it against the mesh
first and asks for that cell; a ``point`` member would be a name no request
could ever be built with."""

TimeSelector = Literal["all", "last", "first"] | tuple[int, ...]
"""Which timesteps to keep. Explicit indices are allowed so a caller can ask
for a handful of dates without carrying the whole transient field."""

_KEYED_SUPPORTS = ("boundary", "lake")


@dataclass(frozen=True, slots=True)
class ObservableRequest:
    """One named quantity asked of a solver adapter for one run.

    ``id`` is the caller's own label and is what keys the returned mapping;
    ``name`` is the canonical field name (``release_flux``, ``head``,
    ``discharge``, ``saturated_thickness``, ...). Selecting the timesteps here
    rather than reducing afterwards is what keeps a trial affordable: a
    transient per-cell field is ``8 * n_times * n_cells`` bytes, hundreds of
    megabytes on a real catchment, times the calibration thread pool.
    """

    id: str
    name: str
    support: ObservableSupport
    key: str | None = None
    cell: tuple[int, int, int] | None = None
    times: TimeSelector = "all"

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("an observable request needs a non-empty id.")
        if not self.name:
            raise ValueError(f"observable request {self.id!r} needs a non-empty name.")
        if self.support in _KEYED_SUPPORTS and not self.key:
            raise ValueError(
                f"observable request {self.id!r} on support {self.support!r} needs a key "
                "naming the boundary or the lake."
            )
        if self.support == "cell" and self.cell is None:
            raise ValueError(
                f"observable request {self.id!r} on support 'cell' needs a (layer, row, col) cell."
            )
        if isinstance(self.times, tuple) and not self.times:
            raise ValueError(f"observable request {self.id!r} selects an empty set of timesteps.")


@dataclass(frozen=True, slots=True)
class ObservableResult:
    """What an adapter returns for one request.

    The shape is carried by the data, not by the type: ``()`` for a scalar,
    ``(n_times,)`` for a series, ``(n_times, n_cells)`` for a field. One class
    therefore covers every support, and a consumer reads ``values.ndim``.

    ``units`` travels with the values because the registry and the comparison
    layer already disagree on the unit of at least one field, and a cost that
    cannot check the unit it is given cannot catch that.
    """

    request_id: str
    values: np.ndarray
    units: str
    times: pd.DatetimeIndex | None = None


def require_unique_request_ids(requests: Sequence[ObservableRequest]) -> None:
    """Refuse a batch holding two requests with the same id.

    The returned mapping is keyed by id, so duplicates would silently collapse
    into whichever request an adapter happened to serve last.
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    for request in requests:
        if request.id in seen:
            duplicates.add(request.id)
        seen.add(request.id)
    if duplicates:
        raise ValueError(
            f"observable requests must have distinct ids; {sorted(duplicates)} repeat."
        )


def select_time_indices(n_times: int, selector: TimeSelector) -> np.ndarray:
    """Resolve a time selector against a run holding ``n_times`` timesteps.

    Every adapter needs this, so it lives with the contract rather than being
    written once per backend. Explicit indices are bounds-checked and may be
    negative, counted from the end like a Python index.
    """
    total = int(n_times)
    if total < 0:
        raise ValueError(f"n_times must be positive, got {total}.")
    if selector == "all":
        return np.arange(total, dtype=int)
    if total == 0:
        raise ValueError(f"the run holds no timestep, so selector {selector!r} has no answer.")
    if selector == "first":
        return np.zeros(1, dtype=int)
    if selector == "last":
        return np.array([total - 1], dtype=int)
    if not isinstance(selector, tuple):
        raise ValueError(f"unknown time selector {selector!r}.")
    indices = np.asarray(selector, dtype=int)
    resolved = np.where(indices < 0, indices + total, indices)
    if np.any(resolved < 0) or np.any(resolved >= total):
        raise ValueError(
            f"time selector {selector!r} is out of range for a run of {total} timesteps."
        )
    return resolved


__all__ = (
    "ObservableRequest",
    "ObservableResult",
    "ObservableSupport",
    "TimeSelector",
    "require_unique_request_ids",
    "select_time_indices",
)
