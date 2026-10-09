"""Variable read dispatch shared by ``hmp.read`` and ``Catalog.read``.

One rule, three storage kinds (no ``lazy`` flag):

- Zarr field -> ``xr.DataArray`` (lazy). When ``time`` is an ``int``, the
  eager ``np.ndarray`` for that single timestep instead.
- timeseries -> ``pd.Series``.
- geographic feature -> ``gpd.GeoDataFrame``.

The dispatch lives in the ``results`` layer so both the functional facade
(:mod:`hydromodpy._api`) and the catalog facade
(:class:`hydromodpy.catalog.Catalog`) reach it without crossing layers.
"""

from __future__ import annotations

from typing import Any

#: The name ``read_variable`` gives to the particle paths of a run.
PARTICLES = "particles"


def read_variable(
    run: Any,
    var: str,
    *,
    time: Any = None,
    layer: int | None = None,
    sel: dict | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> Any:
    """Read ``var`` from ``run`` with storage-kind auto-dispatch.

    Resolves ``var`` against the field registry (Zarr fields), then the
    DuckDB ``timeseries`` table, then the geographic features. Returns a
    lazy ``xr.DataArray`` for fields (an ``np.ndarray`` when ``time`` names
    one period), a ``pd.Series`` for timeseries, a ``gpd.GeoDataFrame`` for
    features. ``"particles"`` returns the particle paths as a
    ``pd.DataFrame``, one row per recorded position (see
    :func:`hydromodpy.results.run.particles.particle_frame`).

    ``time`` names one period of a field: an ``int`` index (negative counts
    from the end), a date (``"2002-10-15"``, ``datetime.date``,
    ``pandas.Timestamp``) that resolves to the stress period holding it, or
    ``"first"`` / ``"last"``. A ``slice`` of indexes keeps several periods.
    A series or a feature takes no ``time``: a series is windowed by
    ``sel={"period": (start, end)}``.
    """
    from hydromodpy.results import field_registry
    from hydromodpy.results.errors import FieldNotFoundError
    from hydromodpy.results.run import Run

    if not isinstance(run, Run):
        raise TypeError(f"read expects a Run object as first argument, got {type(run).__name__}")

    sel_kw: dict = dict(sel or {})

    if var == PARTICLES:
        from hydromodpy.results.run.particles import particle_frame

        _refuse_time(var, time, "the particle paths", "no time selector")
        return particle_frame(run)

    if field_registry.has(var):
        return _read_field(run, var, time=_period_index(run, time), layer=layer, bbox=bbox)

    if _has_timeseries_var(run, var):
        _refuse_time(var, time, "a series", 'sel={"period": (start, end)}')
        station = sel_kw.pop("station", None)
        period = sel_kw.pop("period", None)
        return run.timeseries(var, station=station, period=period)

    if _has_geographic_feature(run, var):
        _refuse_time(var, time, "a geographic feature", "no time selector")
        return run.geographic(var)

    available = ", ".join(sorted(field_registry.all_names()))
    raise FieldNotFoundError(
        f"Variable '{var}' not found in any backend (field_registry, timeseries, "
        f"geographic_features). Known field-registry names: {available}.",
        sim_id=run.sim_id,
        variable=var,
    )


def _period_index(run: Any, time: Any) -> int | slice | None:
    """Turn the ``time`` of a field read into a period index or a slice.

    A date used to be ignored without a word, and every period came back.
    """
    import datetime

    import numpy as np
    import pandas as pd

    if time is None or isinstance(time, slice):
        if isinstance(time, slice) and not all(
            bound is None or isinstance(bound, int) for bound in (time.start, time.stop, time.step)
        ):
            raise TypeError(
                "A time slice takes period indexes (time=slice(0, 12)). For a "
                "window of dates, take the indexes from run.periods.steps_for("
                "period=(start, end))."
            )
        return time
    if isinstance(time, bool):
        raise TypeError("time must be a period index, a date, 'first' or 'last', not a bool.")
    if isinstance(time, (int, np.integer)):
        return int(time)
    if isinstance(time, (str, datetime.date, pd.Timestamp, np.datetime64)):
        return int(
            run.periods.step_at(pd.Timestamp(time) if isinstance(time, np.datetime64) else time)
        )
    raise TypeError(
        f"time must be a period index, a slice of indexes, a date, 'first' or "
        f"'last'; got {type(time).__name__}."
    )


def _refuse_time(var: str, time: Any, kind: str, instead: str) -> None:
    """Refuse a ``time`` selector the variable cannot honour."""
    if time is not None:
        raise ValueError(
            f"'{var}' is {kind}, and time= selects a period of a field. Use {instead}."
        )


def _read_field(
    run: Any,
    var: str,
    *,
    time: int | slice | None,
    layer: int | None,
    bbox: tuple[float, float, float, float] | None,
) -> Any:
    """Field read: eager ndarray for a single timestep, lazy DataArray otherwise.

    ``time`` is ignored for a field with no time dimension (topography, layer
    thickness), the same way the store reader ignores a timestep on a static
    array: every field a run reports as available reads back with or without
    a time selector.
    """
    if isinstance(time, int):
        return run.field(var, timestep=time, layer=layer, bbox=bbox)
    da = run.array.to_xarray_batch((var,), bbox=bbox)[var]
    if isinstance(time, slice) and "time" in da.dims:
        da = da.isel(time=time)
    if layer is not None and "layer" in da.dims:
        da = da.isel(layer=layer)
    return da


def _has_timeseries_var(run: Any, variable: str) -> bool:
    """True when ``variable`` appears in the simulation ``timeseries`` table."""
    df = run._catalog.backend.query(
        "SELECT 1 FROM timeseries WHERE sim_id = ? AND variable = ? LIMIT 1",
        [run.sim_id, variable],
    )
    return not df.empty


def _has_geographic_feature(run: Any, feature_name: str) -> bool:
    """True when ``feature_name`` is a persisted geographic feature."""
    try:
        names = run._catalog.list_geographic_features(run.sim_id)
    except Exception:
        return False
    return feature_name in names


__all__ = ["read_variable"]
