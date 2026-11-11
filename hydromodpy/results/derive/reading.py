"""Variable read dispatch shared by ``Run.read`` and ``Catalog.read``.

One type per nature of variable, whatever the selectors say (no ``lazy`` flag):

- a field, Zarr or rebuilt on the fly -> ``xr.DataArray``.
- a time series -> ``pd.Series``.
- a geographic feature -> ``gpd.GeoDataFrame``.
- the particle paths -> ``pd.DataFrame``.

The dispatch lives in the ``results`` layer so both the functional facade
(:meth:`Run.read` and :func:`hydromodpy.project.api.show`) and the catalog facade
(:class:`hydromodpy.results.catalog.Catalog`) reach it without crossing layers.
"""

from __future__ import annotations

from typing import Any

from hydromodpy.core.scope import series_selector

#: The name ``read_variable`` gives to the particle paths of a run.
PARTICLES = "particles"


def read_variable(
    run: Any,
    variable: str,
    *,
    time: Any = None,
    layer: int | None = None,
    sel: dict | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> Any:
    """Read ``variable`` from ``run``, with one return type per nature of variable.

    Resolves ``variable`` against the field registry (Zarr fields), then the
    ``timeseries`` table, then the geographic features. Returns an ``xr.DataArray`` for
    a field, lazy when the store is, a ``pd.Series`` for a series, a ``gpd.GeoDataFrame``
    for a feature. ``"particles"`` returns the particle paths as a ``pd.DataFrame``, one
    row per recorded position (see :func:`hydromodpy.results.run.particles.particle_frame`).

    ``time`` selects in a field and never changes the type. One period, an ``int`` index
    (negative counts from the end), a date (``"2002-10-15"``, ``datetime.date``,
    ``pandas.Timestamp``) that resolves to the stress period holding it, or ``"first"`` /
    ``"last"``, removes the ``time`` dimension. A ``slice`` of indexes keeps several
    periods. A field without a time axis, such as a mesh quality field, reads the same
    whatever ``time`` says. A series or a feature takes no ``time``: a series is windowed
    by ``sel={"period": (start, end)}``.
    """
    from hydromodpy.results import field_registry
    from hydromodpy.results.derive.mesh_quality import MESH_QUALITY_DESCRIPTORS
    from hydromodpy.results.errors import FieldNotFoundError
    from hydromodpy.results.run import Run
    from hydromodpy.results.run.tables import has_rows

    if not isinstance(run, Run):
        raise TypeError(f"read expects a Run object as first argument, got {type(run).__name__}")

    sel_kw: dict = dict(sel or {})

    if variable == PARTICLES:
        from hydromodpy.results.run.particles import particle_frame

        _refuse_time(variable, time, "the particle paths", "no time selector")
        return particle_frame(run)

    if variable in MESH_QUALITY_DESCRIPTORS:
        return _read_mesh_quality(run, variable, layer=layer, bbox=bbox)

    if field_registry.has(variable):
        return _read_field(run, variable, time=_period_index(run, time), layer=layer, bbox=bbox)

    name, source = series_selector(variable)
    if has_rows(run, "timeseries", variable=name, source=source):
        _refuse_time(variable, time, "a series", 'sel={"period": (start, end)}')
        station = sel_kw.pop("station", None)
        period = sel_kw.pop("period", None)
        return run.timeseries(name, station=station, period=period, source=source)

    if _has_geographic_feature(run, variable):
        _refuse_time(variable, time, "a geographic feature", "no time selector")
        return run.geographic(variable)

    available = ", ".join(sorted(field_registry.all_names()))
    raise FieldNotFoundError(
        f"Variable '{variable}' not found in any backend (field_registry, timeseries, "
        f"geographic_features). Known field-registry names: {available}.",
        sim_id=run.sim_id,
        variable=variable,
    )


def _period_index(run: Any, time: Any) -> int | slice | None:
    """Turn the ``time`` of a field read into a period index or a slice of indexes.

    One period goes through :meth:`Run._period_index_of`, so a date resolves to
    the stress period holding it, as :meth:`Run.field` reads it.
    """
    if time is None:
        return None
    if not isinstance(time, slice):
        return run._period_index_of(time)
    if not all(
        bound is None or isinstance(bound, int) for bound in (time.start, time.stop, time.step)
    ):
        raise TypeError(
            "A time slice takes period indexes (time=slice(0, 12)). For a "
            "window of dates, take the indexes from run.periods.steps_for("
            "period=(start, end))."
        )
    return time


def _refuse_time(var: str, time: Any, kind: str, instead: str) -> None:
    """Refuse a ``time`` selector the variable cannot honor."""
    if time is not None:
        raise ValueError(
            f"'{var}' is {kind}, and time= selects a period of a field. Use {instead}."
        )


def _read_field(
    run: Any,
    variable: str,
    *,
    time: int | slice | None,
    layer: int | None,
    bbox: tuple[float, float, float, float] | None,
) -> Any:
    """Read a field as a ``DataArray``, whatever the selectors say.

    One period removes the ``time`` dimension, and only that period is read or rebuilt.
    ``time`` is ignored for a field with no time dimension (topography, layer
    thickness), the same way the store reader ignores a timestep on a static
    array: every field a run reports as available reads back with or without
    a time selector.
    """
    one_period = isinstance(time, int)
    window = slice(time, time + 1 or None) if one_period else time
    da = run.array.to_xarray_batch((variable,), time_slice=window, bbox=bbox)[variable]
    if one_period and "time" in da.dims:
        if da.sizes["time"] == 0:
            raise IndexError(f"time={time}: the run has no such period of '{variable}'.")
        da = da.isel(time=0)
    if layer is not None and "layer" in da.dims:
        da = da.isel(layer=layer)
    return da


def _read_mesh_quality(
    run: Any,
    variable: str,
    *,
    layer: int | None,
    bbox: tuple[float, float, float, float] | None,
) -> Any:
    """Read a mesh quality field, which has no time axis, as a ``DataArray``."""
    import numpy as np
    import xarray as xr

    values = np.asarray(run.field(variable, layer=layer))
    dims = ("cell",) if values.ndim == 1 else ("layer", "cell")
    da = xr.DataArray(values, dims=dims, name=variable)
    return da if bbox is None else da.isel(cell=np.flatnonzero(run.mesh.cells_in_bbox(bbox)))


def _has_geographic_feature(run: Any, feature_name: str) -> bool:
    """True when ``feature_name`` is a persisted geographic feature."""
    try:
        names = run._catalog.list_geographic_features(run.sim_id)
    except Exception:
        return False
    return feature_name in names


__all__ = ["read_variable"]
