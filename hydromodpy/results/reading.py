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


def read_variable(
    run: Any,
    var: str,
    *,
    time: int | slice | None = None,
    layer: int | None = None,
    sel: dict | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> Any:
    """Read ``var`` from ``run`` with storage-kind auto-dispatch.

    Resolves ``var`` against the field registry (Zarr fields), then the
    DuckDB ``timeseries`` table, then the geographic features. Returns a
    lazy ``xr.DataArray`` for fields (an ``np.ndarray`` when ``time`` is an
    ``int``), a ``pd.Series`` for timeseries, a ``gpd.GeoDataFrame`` for
    features.
    """
    from hydromodpy.results import field_registry
    from hydromodpy.results.errors import FieldNotFoundError
    from hydromodpy.results.run import Run

    if not isinstance(run, Run):
        raise TypeError(f"read expects a Run object as first argument, got {type(run).__name__}")

    sel_kw: dict = dict(sel or {})

    if field_registry.has(var):
        return _read_field(run, var, time=time, layer=layer, bbox=bbox)

    if _has_timeseries_var(run, var):
        station = sel_kw.pop("station", None)
        period = sel_kw.pop("period", None)
        return run.timeseries(var, station=station, period=period)

    if _has_geographic_feature(run, var):
        return run.geographic(var)

    available = ", ".join(sorted(field_registry.all_names()))
    raise FieldNotFoundError(
        f"Variable '{var}' not found in any backend (field_registry, timeseries, "
        f"geographic_features). Known field-registry names: {available}.",
        sim_id=run.sim_id,
        variable=var,
    )


def _read_field(
    run: Any,
    var: str,
    *,
    time: int | slice | None,
    layer: int | None,
    bbox: tuple[float, float, float, float] | None,
) -> Any:
    """Field read: eager ndarray for a single timestep, lazy DataArray otherwise."""
    if isinstance(time, int):
        return run.field(var, timestep=time, layer=layer, bbox=bbox)
    da = run.array.to_xarray_batch((var,), bbox=bbox)[var]
    if isinstance(time, slice):
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
