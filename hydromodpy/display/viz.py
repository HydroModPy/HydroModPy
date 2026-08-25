"""Public ``hmp.viz`` dispatcher exposed at the top level.

Single-entry function ``show(data, downsample="auto", crs=None)`` that
auto-dispatches based on the input type:

- :class:`xarray.DataArray` -> rasterize via datashader when the array is
  dense or when ``downsample="auto"`` triggers, otherwise straight to
  ``plot.imshow`` style.
- :class:`pandas.Series` -> LTTB-downsample when dense, then plot.
- :class:`geopandas.GeoDataFrame` -> render via geopandas
  (datashader/holoviews layered backends are reserved for the
  ``interactive`` extra).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from matplotlib.figure import Figure as MplFigure


DownsampleMode = Literal["auto", "lttb", "none"] | None


def show(
    data: Any,
    *,
    downsample: DownsampleMode = "auto",
    crs: str | int | None = None,
    target_px: tuple[int, int] = (1200, 800),
    n_out: int = 5_000,
    **opts: Any,
) -> MplFigure:
    """Display ``data`` with auto-dispatch and optional downsampling.

    Parameters
    ----------
    data
        ``xarray.DataArray``, ``pandas.Series`` or ``geopandas.GeoDataFrame``.
    downsample
        ``"auto"`` (default), ``"lttb"``, ``"none"`` or ``None``.
    crs
        Optional CRS string (``"EPSG:2154"``) or EPSG integer code.
    target_px
        Target raster resolution for ``DataArray`` inputs.
    n_out
        Target sample count for series inputs.

    Returns
    -------
    matplotlib.figure.Figure
        Figure produced by the dispatched backend.

    Raises
    ------
    TypeError
        If ``data`` is not one of the supported types.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> da = hmp.read(run, "head", time=-1, lazy=True)
    >>> fig = hmp.viz.show(da)
    >>> ts = hmp.read(run, "discharge", sel={"station": "outlet"})
    >>> hmp.viz.show(ts, downsample="lttb", n_out=2_000)
    """
    import matplotlib.pyplot as plt

    array_like = _maybe_dataarray(data)
    if array_like is not None:
        return _show_array(
            array_like,
            downsample=downsample,
            crs=crs,
            target_px=target_px,
            **opts,
        )

    series_like = _maybe_series(data)
    if series_like is not None:
        return _show_series(series_like, downsample=downsample, n_out=n_out, **opts)

    gdf_like = _maybe_geodataframe(data)
    if gdf_like is not None:
        fig, ax = plt.subplots(constrained_layout=True)
        gdf_like.plot(ax=ax, **opts)
        return fig

    raise TypeError(
        "hmp.viz.show expects an xarray.DataArray, pandas.Series, or "
        f"geopandas.GeoDataFrame; got {type(data).__name__}"
    )


def _show_array(
    da: Any,
    *,
    downsample: DownsampleMode,
    crs: str | int | None,
    target_px: tuple[int, int],
    **opts: Any,
) -> MplFigure:
    import matplotlib.pyplot as plt

    from hydromodpy.display.scalable import (
        DEFAULT_CELL_THRESHOLD,
        is_datashader_available,
        rasterize_field,
        should_rasterize,
    )

    size = int(getattr(da, "size", 0)) or int(da.values.size)
    needs_raster = (
        downsample == "lttb" or downsample is None or downsample == "none" or downsample == "auto"
    )
    if downsample == "auto":
        needs_raster = should_rasterize(size, threshold=DEFAULT_CELL_THRESHOLD)
    elif downsample in (None, "none"):
        needs_raster = False
    elif downsample == "lttb":
        # LTTB on 2D fields makes no sense; fall back to rasterization.
        needs_raster = should_rasterize(size, threshold=DEFAULT_CELL_THRESHOLD)

    if needs_raster and is_datashader_available():
        aggregated = rasterize_field(da, target_px=target_px)
        fig, ax = plt.subplots(constrained_layout=True)
        try:
            aggregated.plot.imshow(ax=ax, **opts)
        except AttributeError:
            ax.imshow(aggregated.values, origin="lower")
        if crs is not None:
            ax.set_title(f"CRS: {crs}")
        return fig

    fig, ax = plt.subplots(constrained_layout=True)
    try:
        da.plot.imshow(ax=ax, **opts)
    except AttributeError:
        ax.imshow(da.values, origin="lower")
    if crs is not None:
        ax.set_title(f"CRS: {crs}")
    return fig


def _show_series(
    series: Any,
    *,
    downsample: DownsampleMode,
    n_out: int,
    **opts: Any,
) -> MplFigure:
    import matplotlib.pyplot as plt

    from hydromodpy.results.derive.downsample import (
        DEFAULT_TIMESERIES_THRESHOLD,
        lttb_downsample,
        should_downsample,
    )

    decimated = series
    if downsample == "lttb":
        decimated = lttb_downsample(series, n_out=int(n_out))
    elif downsample == "auto":
        if should_downsample(len(series), threshold=DEFAULT_TIMESERIES_THRESHOLD):
            decimated = lttb_downsample(series, n_out=int(n_out))

    fig, ax = plt.subplots(constrained_layout=True)
    ax.plot(decimated.index, decimated.values, **opts)
    return fig


def _maybe_dataarray(data: Any):
    try:
        import xarray as xr
    except ImportError:
        return None
    return data if isinstance(data, xr.DataArray) else None


def _maybe_series(data: Any):
    try:
        import pandas as pd
    except ImportError:
        return None
    return data if isinstance(data, pd.Series) else None


def _maybe_geodataframe(data: Any):
    try:
        import geopandas as gpd
    except ImportError:
        return None
    return data if isinstance(data, gpd.GeoDataFrame) else None


__all__ = ["show"]
