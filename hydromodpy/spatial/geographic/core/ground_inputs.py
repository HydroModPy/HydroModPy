"""Read the lake footprint polygons that ``[geographic.enforce_lakes]`` declares.

The lakes of the ground are read from one polygon file: the crossing notch
leaves a lake alone, and the bed regularization skips it. The routing DEM is no
longer carved at the lakes (a ramp toward the outlet, an outlet notch, a stream
capture): the cell drainage ``D`` already makes the water cross a lake, and
those carves moved neither the basin, the network, nor the drains.
"""

from __future__ import annotations

from pathlib import Path


def _data_dir(setup: object) -> Path:
    """The data folder around the DEM the project declared (data/dem/x.tif -> data)."""
    return Path(str(setup.dem_init_path)).resolve().parent.parent


def lakes_from_config(enforce: object, setup: object) -> list:
    """Read the enforcement lake polygons, resolving the path against the DEM data dir."""
    import geopandas as gpd

    lgp = getattr(enforce, "lake_geometry_path", None)
    if lgp is None:
        raise ValueError(
            "geographic.enforce_lakes.enabled is true but lake_geometry_path is unset."
        )
    path = Path(lgp)
    if not path.exists():
        # A bare filename (or a mis-resolved one): look under <data>/lake_geometry/,
        # where <data> is the parent of the DEM's family dir (data/dem/x.tif -> data).
        candidate = _data_dir(setup) / "lake_geometry" / path.name
        if candidate.exists():
            path = candidate
    if not path.exists():
        raise FileNotFoundError(
            f"geographic.enforce_lakes.lake_geometry_path not found: {lgp} "
            "(tried as-is and under <data>/lake_geometry/)."
        )
    gdf = gpd.read_file(path)
    if getattr(setup, "crs_project", None) is not None:
        gdf = gdf.to_crs(setup.crs_project)
    return [g for g in gdf.geometry if g is not None and not g.is_empty]
