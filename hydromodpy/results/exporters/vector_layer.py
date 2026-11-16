"""Export a vector layer of a run to a GIS file: a stored layer, or its pathlines.

The layers a run stores as GeoParquet (``watershed``,
``hydrographic_network_reference``...) are written as they are. The pathlines are
built from the particle tracks, one line per particle. Both keep the CRS they
hold, or are reprojected into the one asked for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

_DRIVERS = {"geopackage": "GPKG", "shapefile": "ESRI Shapefile"}


def export_geographic_feature(
    catalog: Any,
    sim_id: str,
    name: str,
    output_path: str | Path,
    *,
    fmt: str = "geopackage",
    crs: str | None = None,
    model_crs: str | None = None,
) -> Path:
    """Write one stored geographic feature to a GeoPackage or a Shapefile.

    Parameters
    ----------
    catalog
        The catalog the run lives in (``read_geographic_feature``).
    sim_id
        Simulation UUID.
    name
        Stored feature name, e.g. ``"watershed"``.
    output_path
        Destination file.
    fmt
        ``"geopackage"`` or ``"shapefile"``.
    crs
        CRS to reproject into. Left out, the stored CRS is kept.
    model_crs
        CRS stated on a layer stored without one, before any reprojection.

    Raises
    ------
    KeyError
        The run stores no feature of that name.
    """
    if fmt not in _DRIVERS:
        raise ValueError(f"A vector layer is written as {' or '.join(_DRIVERS)}, not {fmt!r}.")
    frame = catalog.read_geographic_feature(sim_id, name)
    return _write(frame, name, Path(output_path), fmt, crs, model_crs)


def export_pathlines(
    run: Any,
    output_path: str | Path,
    *,
    fmt: str = "geopackage",
    crs: str | None = None,
    model_crs: str | None = None,
) -> Path:
    """Write one line per particle that moved, from its release to where it leaves the aquifer.

    Each line carries ``travel_yr``, the time the water takes along it in years, a name
    short enough for a Shapefile. The lines are
    those of :func:`hydromodpy.results.run.particles.moving_tracks`, stated in ``model_crs``.
    """
    import geopandas as gpd
    import shapely

    from hydromodpy.results.exporters.export_spec import PATHLINES
    from hydromodpy.results.run.particles import moving_tracks

    if fmt not in _DRIVERS:
        raise ValueError(f"A vector layer is written as {' or '.join(_DRIVERS)}, not {fmt!r}.")
    tracks, years = moving_tracks(run)
    lines = [shapely.LineString(track[:, :2]) for track in tracks]
    frame = gpd.GeoDataFrame({"travel_yr": years}, geometry=lines, crs=model_crs)
    return _write(frame, PATHLINES, Path(output_path), fmt, crs, model_crs)


def _write(
    gdf: Any, name: str, output_path: Path, fmt: str, crs: str | None, model_crs: str | None
) -> Path:
    """Write ``gdf`` as the layer ``name``, in its CRS or reprojected into ``crs``."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if gdf.crs is None and model_crs is not None:
        gdf = gdf.set_crs(model_crs)
    if crs is not None:
        if gdf.crs is None:
            raise ValueError(
                f"Layer {name!r} carries no CRS, so it cannot be reprojected to {crs}."
            )
        gdf = gdf.to_crs(crs)
    if fmt == "geopackage":
        # GDAL takes a column named fid as the key of a GeoPackage and refuses one
        # of floats, which a Shapefile saved by QGIS holds. The key gets its own name.
        own_key = "fid" in {str(column).lower() for column in gdf.columns}
        options = {"FID": "gpkg_fid"} if own_key else None
        gdf.to_file(str(output_path), driver=_DRIVERS[fmt], layer=name, layer_options=options)
    else:
        gdf.to_file(str(output_path), driver=_DRIVERS[fmt])
    logger.info("Exported %s layer %s: %s (%d features)", fmt, name, output_path, len(gdf))
    return output_path
