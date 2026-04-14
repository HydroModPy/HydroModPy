"""Export cell geometries with field values to a Shapefile."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import zarr

logger = logging.getLogger(__name__)


def export_shapefile(
    zarr_path: str | Path,
    sim_id: str,
    variable: str,
    timestep: int,
    output_path: str | Path,
    *,
    layer: int | None = None,
    crs: str = "EPSG:2154",
) -> Path:
    """Export mesh cells with field values to a Shapefile.

    Requires ``geopandas`` and ``shapely``.

    Parameters
    ----------
    zarr_path : str or Path
        Path to the simulation Zarr store.
    sim_id : str
        Simulation UUID.
    variable : str
        Field name.
    timestep : int
        Timestep index.
    output_path : str or Path
        Destination ``.shp`` file (or directory).
    layer : int, optional
        Layer index for 3D fields. Defaults to the first layer.
    crs : str
        Coordinate reference system for the output.

    Returns
    -------
    Path
        The written file path.
    """
    import geopandas as gpd
    from shapely.geometry import Polygon

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    root = zarr.open_group(str(zarr_path), mode="r")
    grp = root
    mesh = grp["mesh"]

    vertices = mesh["vertices"][:]
    connectivity = mesh["face_node_connectivity"][:]

    arr = _find_variable(grp, variable)
    if arr is None:
        raise KeyError(f"Variable '{variable}' not found for sim={sim_id}")

    data = arr[timestep]
    if data.ndim == 2:
        data = data[layer or 0]

    geometries = []
    values = []
    cell_ids = []
    for i, face in enumerate(connectivity):
        node_ids = face[face >= 0]
        coords = vertices[node_ids, :2]
        if len(coords) < 3:
            continue
        poly = Polygon(coords)
        if poly.is_valid and not poly.is_empty:
            geometries.append(poly)
            values.append(float(data[i]))
            cell_ids.append(i)

    gdf = gpd.GeoDataFrame(
        {"cell_id": cell_ids, variable: values},
        geometry=geometries,
        crs=crs,
    )
    gdf.to_file(str(output_path))
    logger.info("Exported Shapefile: %s (%d cells)", output_path, len(gdf))
    return output_path


def _find_variable(grp, var_name: str):
    """Search for a variable in the simulation group and its subgroups."""
    if var_name in grp:
        return grp[var_name]
    for sub in ("derived", "budget"):
        sg = grp.get(sub)
        if sg is not None and var_name in sg:
            return sg[var_name]
    return None
