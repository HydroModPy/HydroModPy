"""Export cell geometries with field values to a Shapefile."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.results.exporters._fields import native_crs, one_layer, read_field_step
from hydromodpy.results.zarr_store import SimulationZarr

if TYPE_CHECKING:
    import geopandas as gpd

logger = get_logger(__name__)


def build_cell_geodataframe(
    zarr_path: str | Path,
    sim_id: str,
    variable: str,
    timestep: int,
    *,
    layer: int | None = None,
    crs: str | None = None,
    values: np.ndarray | None = None,
    fmt: str = "vector layer",
) -> gpd.GeoDataFrame:
    """Build a ``GeoDataFrame`` of mesh-cell polygons with one field's values.

    Shared by the Shapefile and GeoPackage exporters. Requires ``geopandas`` and
    ``shapely`` and an explicit ``crs``, the CRS of the returned frame: the
    geometries are reprojected into it when the store holds another one.
    ``values`` are the per-cell values when the caller computed them; the
    store is then read for the mesh only. A field of several layers needs
    ``layer``: a vector layer holds one value per cell.
    """
    import geopandas as gpd
    from shapely.geometry import Polygon

    if crs is None:
        raise ValueError("Vector export requires an explicit CRS.")

    sz = SimulationZarr(zarr_path)
    try:
        grp = sz.root
        mesh = grp["mesh"]
        vertices = mesh["vertices"][:]
        connectivity = mesh["face_node_connectivity"][:]
        source_crs = native_crs(grp)
        # Rebuilt on the fly when the field was never persisted, like the raster
        # exporter does: a vector export of seepage_mask must not fail on a run
        # where the same call succeeds as a GeoTIFF.
        data = values if values is not None else read_field_step(sz, sim_id, variable, timestep)
    finally:
        sz.close()
    data = one_layer(data, variable, layer, fmt)

    geometries = []
    cell_values = []
    cell_ids = []
    for i, face in enumerate(connectivity):
        node_ids = face[face >= 0]
        coords = vertices[node_ids, :2]
        if len(coords) < 3:
            continue
        poly = Polygon(coords)
        if poly.is_valid and not poly.is_empty:
            geometries.append(poly)
            cell_values.append(float(data[i]))
            cell_ids.append(i)

    # The polygons are built from mesh/vertices, so the frame is born in the
    # store's own CRS. Stating that first is what turns to_crs into a real
    # reprojection instead of a rename (on a frame with no CRS it raises).
    # With no grid mapping in the store the caller's value is the only
    # statement about these coordinates: tag with it and reproject nothing.
    gdf = gpd.GeoDataFrame(
        {"cell_id": cell_ids, variable: cell_values},
        geometry=geometries,
        crs=source_crs if source_crs is not None else crs,
    )
    if source_crs is None:
        logger.warning("No CRS recorded in the run store: tagging as %s without reprojecting.", crs)
        return gdf
    return gdf.to_crs(crs)


def export_shapefile(
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
        Timestep index. Ignored for a static field.
    output_path : str or Path
        Destination ``.shp`` file (or directory).
    layer : int, optional
        Layer of a field of several layers. Required when the field holds
        more than one.
    crs : str
        Coordinate reference system of the output. Cells are reprojected into
        it when the mesh is stored in another one.
    values : numpy.ndarray, optional
        The per-cell values to write, when the caller computed them.

    Returns
    -------
    Path
        The written file path.

    Raises
    ------
    ValueError
        Raised when ``crs`` is missing, or when the field holds several
        layers and none is given.
    KeyError
        Raised when ``variable`` is not stored in the Zarr hierarchy.

    Examples
    --------
    >>> export_shapefile(
    ...     run_zarr, run.sim_id, "head", -1, "head_cells.shp", crs="EPSG:2154"
    ... )  # doctest: +SKIP
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
        fmt="Shapefile",
    )
    gdf.to_file(str(output_path))
    logger.info("Exported Shapefile: %s (%d cells)", output_path, len(gdf))
    return output_path
