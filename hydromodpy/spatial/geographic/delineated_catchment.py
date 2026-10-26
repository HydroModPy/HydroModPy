"""The catchment polygon a geographic delineated, read in one place.

The build, the discharge observable and the network criterion all ask the
same question: which polygon did the geographic step delineate as the
catchment? A synthetic geographic delineates none. It writes its box as
``watershed_shp`` for the data masks and the figures, but that box is the
domain, so it answers None, and a synthetic run carries the domain alone.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from hydromodpy.spatial.geographic.synthetic.config import SYNTHETIC_CATCH_DEF

if TYPE_CHECKING:
    import geopandas as gpd


def catchment_outline(geographic: object | None) -> gpd.GeoDataFrame | None:
    """The delineated catchment polygon of ``geographic``, None when it delineated none.

    None for a synthetic geographic, for a missing ``watershed_shp`` and for an
    empty file.
    """
    if getattr(geographic, "catch_def", None) == SYNTHETIC_CATCH_DEF:
        return None
    shp = getattr(geographic, "watershed_shp", None)
    if not shp or not os.path.exists(str(shp)):
        return None
    import geopandas as gpd

    frame = gpd.read_file(str(shp))
    return None if frame.empty else frame


__all__ = ["catchment_outline"]
