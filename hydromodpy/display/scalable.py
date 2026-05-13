"""Scalable rasterization helpers for dense meshes and large 2D fields.

Wraps datashader so dense meshes (> 100k cells) and dense gridded arrays
can be rendered as raster images at a target pixel resolution. Auto-trigger
threshold defaults to 100_000 cells.

Used by the public ``hmp.viz.show`` dispatcher and by figures that opt-in
to downsampling when they detect a mesh too large for matplotlib's
PolyCollection path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import xarray as xr

DEFAULT_TARGET_PX: tuple[int, int] = (1200, 800)
DEFAULT_CELL_THRESHOLD: int = 100_000


def is_datashader_available() -> bool:
    """Return True when the optional ``datashader`` package is importable."""
    try:
        import datashader  # noqa: F401
    except ImportError:
        return False
    return True


def should_rasterize(n_cells: int, *, threshold: int = DEFAULT_CELL_THRESHOLD) -> bool:
    """Return True when the cell count crosses the rasterization threshold."""
    return int(n_cells) > int(threshold)


def rasterize_field(
    da: xr.DataArray,
    *,
    target_px: tuple[int, int] = DEFAULT_TARGET_PX,
    agg: str = "mean",
) -> xr.DataArray:
    """Rasterize a field via datashader ``Canvas.raster``.

    ``da`` must be a 2D :class:`xarray.DataArray` with at least two named
    spatial dims (``x``, ``y`` or ``lon``, ``lat``). The returned DataArray
    keeps these dims but at the requested ``target_px = (width, height)``
    resolution.

    Parameters
    ----------
    da
        Input 2D field.
    target_px
        Target raster resolution as ``(width, height)`` in pixels.
    agg
        Aggregation method passed to ``ds.Canvas.raster``. One of
        ``"mean"``, ``"min"``, ``"max"``, ``"sum"``.
    """
    if not is_datashader_available():
        raise RuntimeError(
            "datashader is not installed. Install the optional 'viz' extra: "
            "`pip install hydromodpy[viz]`."
        )
    import datashader as ds

    width, height = int(target_px[0]), int(target_px[1])
    if width <= 0 or height <= 0:
        raise ValueError("target_px must be strictly positive on both axes")
    if agg not in {"mean", "min", "max", "sum"}:
        raise ValueError(f"unsupported agg '{agg}'")

    cvs = ds.Canvas(plot_width=width, plot_height=height)
    # datashader.Canvas.raster expects an xr.DataArray with monotonic coords.
    aggregated = cvs.raster(da, agg=agg)
    return aggregated


def rasterize_points(
    x: np.ndarray,
    y: np.ndarray,
    values: np.ndarray,
    *,
    target_px: tuple[int, int] = DEFAULT_TARGET_PX,
    agg: str = "mean",
) -> np.ndarray:
    """Rasterize scattered (x, y, value) points to a 2D numpy array.

    Useful for unstructured mesh fields where centroids are known but the
    full connectivity is not needed (e.g. quick preview of head distribution
    on a 1M-face DISV mesh).
    """
    if not is_datashader_available():
        raise RuntimeError("datashader is not installed. Install the optional 'viz' extra.")
    import datashader as ds
    import pandas as pd

    width, height = int(target_px[0]), int(target_px[1])
    if width <= 0 or height <= 0:
        raise ValueError("target_px must be strictly positive on both axes")

    frame = pd.DataFrame(
        {
            "x": np.asarray(x, dtype=float).ravel(),
            "y": np.asarray(y, dtype=float).ravel(),
            "value": np.asarray(values, dtype=float).ravel(),
        }
    )
    cvs = ds.Canvas(plot_width=width, plot_height=height)
    if agg == "mean":
        aggregator = ds.mean("value")
    elif agg == "sum":
        aggregator = ds.sum("value")
    elif agg == "min":
        aggregator = ds.min("value")
    elif agg == "max":
        aggregator = ds.max("value")
    else:
        raise ValueError(f"unsupported agg '{agg}'")
    raster = cvs.points(frame, x="x", y="y", agg=aggregator)
    return np.asarray(raster.values)


__all__ = [
    "DEFAULT_CELL_THRESHOLD",
    "DEFAULT_TARGET_PX",
    "is_datashader_available",
    "rasterize_field",
    "rasterize_points",
    "should_rasterize",
]
