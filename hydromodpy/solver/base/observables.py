"""Turn a solver series or field into an observable result.

Every backend produces its quantities as a pandas object first, then has to
hand back an :class:`~hydromodpy.core.contracts.observables.ObservableResult`
sliced to the timesteps the request asked for. That last step is identical
whatever wrote the numbers, so it lives beside the Protocol rather than in one
backend's package.

A backend also says which observables it can serve, in three states
(``ObservableSupport``). Whether it can serve one depends on the packages the
resolved configuration builds: MODFLOW 6 hands back a lake stage only if the
file declares a lake, MODFLOW-NWT never can. So an observable is servable now,
servable once the configuration declares what it needs (with the sentence that
says what to declare), or unavailable on this backend whatever the file says.
This is the shape ``boundary_condition_registry.supported_backends`` uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    select_time_indices,
)


def series_observable(
    request: ObservableRequest,
    series: pd.Series,
    *,
    units: str,
    includes_runoff: bool = False,
) -> ObservableResult:
    """Wrap a full series as one observable, sliced to the requested timesteps.

    Public because every backend needs it, not only the MODFLOW pair.
    """
    values = np.asarray(series.to_numpy(), dtype=float)
    keep = select_time_indices(values.size, request.times)
    index = series.index
    times = index[keep] if isinstance(index, pd.DatetimeIndex) else None
    return ObservableResult(
        request_id=request.id,
        values=values[keep],
        units=units,
        times=times,
        includes_runoff=includes_runoff,
    )


def scalar_observable(
    request: ObservableRequest,
    value: float,
    *,
    units: str,
) -> ObservableResult:
    """Wrap one time-invariant number as an observable.

    ``ObservableResult`` carries the shape in the data, so a scalar is a ``()``
    array and no consumer needs a new branch to read it.
    """
    return ObservableResult(
        request_id=request.id,
        values=np.asarray(float(value), dtype=float),
        units=units,
        times=None,
    )


def field_observable(
    request: ObservableRequest,
    frame: pd.DataFrame,
    *,
    units: str,
) -> ObservableResult:
    """Wrap a full per-cell field as one observable, sliced to its timesteps."""
    values = np.asarray(frame.to_numpy(), dtype=float)
    keep = select_time_indices(values.shape[0], request.times)
    index = frame.index
    times = index[keep] if isinstance(index, pd.DatetimeIndex) else None
    return ObservableResult(
        request_id=request.id,
        values=values[keep, :],
        units=units,
        times=times,
    )


State = Literal["servable", "servable_under_condition", "unavailable"]


@dataclass(frozen=True)
class ObservableSupport:
    """Whether one named observable can be served, and what it would take."""

    name: str
    state: State
    reason: str
    """A sentence a reader who did not write the backend can act on."""

    @property
    def is_servable_now(self) -> bool:
        return self.state == "servable"

    @property
    def can_never_be_served(self) -> bool:
        return self.state == "unavailable"


def servable(name: str, reason: str = "") -> ObservableSupport:
    """Declare an observable this run can produce as it stands."""
    return ObservableSupport(name=name, state="servable", reason=reason or "served by this run")


def under_condition(name: str, reason: str) -> ObservableSupport:
    """Declare an observable one declaration away, naming the declaration."""
    return ObservableSupport(name=name, state="servable_under_condition", reason=reason)


def unavailable(name: str, reason: str) -> ObservableSupport:
    """Declare an observable this backend cannot produce, whatever the file says."""
    return ObservableSupport(name=name, state="unavailable", reason=reason)


__all__ = [
    "ObservableSupport",
    "State",
    "field_observable",
    "scalar_observable",
    "series_observable",
    "servable",
    "unavailable",
    "under_condition",
]
