"""Export a geographic vector layer of a run (catchment, networks) to a GIS file.

The layers a run stores as GeoParquet (``watershed``,
``hydrographic_network_reference``...) are written as they are, in the CRS
they were stored in, or reprojected into the one asked for.
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
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gdf = catalog.read_geographic_feature(sim_id, name)
    if gdf.crs is None and model_crs is not None:
        gdf = gdf.set_crs(model_crs)
    if crs is not None:
        if gdf.crs is None:
            raise ValueError(
                f"Layer {name!r} carries no CRS, so it cannot be reprojected to {crs}."
            )
        gdf = gdf.to_crs(crs)
    if fmt == "geopackage":
        gdf.to_file(str(output_path), driver=_DRIVERS[fmt], layer=name)
    else:
        gdf.to_file(str(output_path), driver=_DRIVERS[fmt])
    logger.info("Exported %s layer %s: %s (%d features)", fmt, name, output_path, len(gdf))
    return output_path
