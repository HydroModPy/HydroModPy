"""Export cell geometries with field values to a GeoPackage (OGC, single-file).

GeoPackage is the default vector container: unlike Shapefile it keeps full-length
column names, stores true NULLs and datetimes, and is a single file, so it is the
better hand-off for feature/cell export.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.results.exporters.shapefile import build_cell_geodataframe

logger = get_logger(__name__)


def export_geopackage(
    zarr_path: str | Path,
    sim_id: str,
    variable: str,
    timestep: int,
    output_path: str | Path,
    *,
    layer: int | None = None,
    crs: str | None = None,
    values: np.ndarray | None = None,
) -> Path:
    """Export mesh cells with one field's values to a ``.gpkg`` file.

    Requires ``geopandas`` and ``shapely`` and an explicit ``crs``. A field of
    several layers needs ``layer``. ``values`` are the per-cell values when
    the caller computed them.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gdf = build_cell_geodataframe(
        zarr_path,
        sim_id,
        variable,
        timestep,
        layer=layer,
        crs=crs,
        values=values,
        fmt="GeoPackage",
    )
    gdf.to_file(str(output_path), driver="GPKG", layer=variable)
    logger.info("Exported GeoPackage: %s (%d cells)", output_path, len(gdf))
    return output_path
