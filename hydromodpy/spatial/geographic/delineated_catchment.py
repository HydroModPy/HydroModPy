"""The catchment polygon a geographic delineated, read in one place.

The build, the discharge observable and the network criterion all ask the
same question: which polygon did the geographic step delineate as the
catchment? A synthetic geographic delineates none. It writes its box as
``watershed_shp`` for the data masks and the figures, but that box is the
domain, so it answers None, and a synthetic run carries the domain alone.

A mesh that follows the catchment follows the outline the planner smoothed, not
the staircase of the DEM pixels (``PlanarCellMesh.smoothed_catchment``). A cell
is read against that outline when the caller names the mesh, so that a cell and
the polygon agree where the faces follow it.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from hydromodpy.spatial.geographic.synthetic.config import SYNTHETIC_CATCH_DEF

if TYPE_CHECKING:
    import geopandas as gpd


def catchment_outline(
    geographic: object | None, cell_mesh: object | None = None
) -> gpd.GeoDataFrame | None:
    """The catchment polygon to read the cells of *cell_mesh* against, None when there is none.

    The outline the planner smoothed for *cell_mesh*, in its CRS, when it did.
    Else the polygon *geographic* delineated, in the frame of its file. None for
    a synthetic geographic, for a missing ``watershed_shp`` and for an empty
    file.
    """
    if getattr(geographic, "catch_def", None) == SYNTHETIC_CATCH_DEF:
        return None
    import geopandas as gpd

    smoothed = getattr(cell_mesh, "smoothed_catchment", None)
    if smoothed is not None:
        return gpd.GeoDataFrame(geometry=[smoothed], crs=cell_mesh.crs_wkt)
    shp = getattr(geographic, "watershed_shp", None)
    if not shp or not os.path.exists(str(shp)):
        return None
    frame = gpd.read_file(str(shp))
    return None if frame.empty else frame


__all__ = ["catchment_outline"]
