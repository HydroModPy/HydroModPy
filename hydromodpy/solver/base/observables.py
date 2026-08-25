"""Turn a solver series or field into an observable result.

Every backend produces its quantities as a pandas object first, then has to
hand back an :class:`~hydromodpy.core.contracts.observables.ObservableResult`
sliced to the timesteps the request asked for. That last step is identical
whatever wrote the numbers, so it lives beside the Protocol rather than in one
backend's package.
"""

from __future__ import annotations

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


__all__ = ("field_observable", "series_observable")
