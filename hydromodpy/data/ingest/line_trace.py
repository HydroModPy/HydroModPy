"""Polyline trace ingest from CSV or vector formats into shapely LineString."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from shapely.geometry import LineString

logger = get_logger(__name__)


def _read_barrier_csv(path: str | Path, where: str) -> LineString:
    """Read a bare x,y (optionally z) CSV of ordered polyline vertices."""
    import pandas as pd
    from shapely.geometry import LineString

    df = pd.read_csv(path)
    cols = {c.strip().lower(): c for c in df.columns}
    xcol = cols.get("x") or cols.get("lon") or cols.get("easting") or df.columns[0]
    ycol = cols.get("y") or cols.get("lat") or cols.get("northing") or df.columns[1]
    coords = [(float(x), float(y)) for x, y in zip(df[xcol], df[ycol], strict=False)]
    if len(coords) < 2:
        raise ValueError(f"{where} CSV '{path}' needs at least two (x, y) rows.")
    return LineString(coords)


def read_line_trace(
    path: str | Path,
    *,
    where: str,
    project_crs: object = None,
) -> LineString:
    """Read a polyline trace from a CSV or vector file into a shapely LineString.

    Vector formats (.gpkg, .shp, .geojson) are reprojected to project_crs if
    needed, and merged into a single contiguous LineString.
    Bare CSV files are read as ordered x,y vertices in the project CRS.
    """
    import geopandas as gpd
    from shapely.geometry import LineString
    from shapely.ops import linemerge

    resolved = Path(path).expanduser()
    if str(resolved).lower().endswith(".csv"):
        return _read_barrier_csv(resolved, where)

    gdf = gpd.read_file(str(resolved))
    if gdf.empty:
        raise ValueError(f"{where} line_path '{resolved}' has no geometry.")
    if gdf.crs is None:
        logger.warning(
            "%s line_path '%s' has no CRS; assuming it is already in the project CRS.",
            where,
            resolved,
        )
    elif project_crs is not None:
        gdf = gdf.to_crs(project_crs)
    unioned = gdf.union_all()
    # linemerge stitches a MultiLineString into one; a lone LineString it rejects.
    merged = linemerge(unioned) if unioned.geom_type == "MultiLineString" else unioned
    if isinstance(merged, LineString) and not merged.is_empty:
        return merged
    raise ValueError(
        f"{where} line_path '{resolved}' resolves to a {merged.geom_type}, not a single "
        "LineString; provide one contiguous polyline (a branching or multi-part trace is "
        "not supported)."
    )
