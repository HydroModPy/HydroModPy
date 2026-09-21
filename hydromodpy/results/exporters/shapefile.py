"""Export cell geometries with field values to a Shapefile."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry
from hydromodpy.results.derive.virtual_fields import derive_field_slice
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
) -> gpd.GeoDataFrame:
    """Build a ``GeoDataFrame`` of mesh-cell polygons with one field's values.

    Shared by the Shapefile and GeoPackage exporters. Requires ``geopandas`` and
    ``shapely`` and an explicit ``crs``, the CRS of the returned frame: the
    geometries are reprojected into it when the store holds another one.
    """
    import geopandas as gpd
    from shapely.geometry import Polygon

    if crs is None:
        raise ValueError("Vector export requires an explicit CRS.")
    descriptor = field_registry.get(variable)

    sz = SimulationZarr(zarr_path)
    try:
        grp = sz.root
        mesh = grp["mesh"]
        vertices = mesh["vertices"][:]
        connectivity = mesh["face_node_connectivity"][:]
        native_crs = _native_crs(grp)

        # Rebuilt on the fly when the field was never persisted, like the raster
        # exporter does: a vector export of seepage_mask must not fail on a run
        # where the same call succeeds as a GeoTIFF.
        arr = _resolve_zarr_path(grp, descriptor.zarr_path)
        if arr is not None:
            data = arr[timestep]
        else:
            data = derive_field_slice(sz, str(sim_id), variable, timestep)
            if data is None:
                raise KeyError(
                    f"Variable '{variable}' (zarr_path={descriptor.zarr_path!r}) "
                    f"not found for sim={sim_id}"
                )
    finally:
        sz.close()
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

    # The polygons are built from mesh/vertices, so the frame is born in the
    # store's own CRS. Stating that first is what turns to_crs into a real
    # reprojection instead of a rename (on a frame with no CRS it raises).
    # With no grid mapping in the store the caller's value is the only
    # statement about these coordinates: tag with it and reproject nothing.
    gdf = gpd.GeoDataFrame(
        {"cell_id": cell_ids, variable: values},
        geometry=geometries,
        crs=native_crs if native_crs is not None else crs,
    )
    if native_crs is None:
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
        Coordinate reference system of the output. Cells are reprojected into
        it when the mesh is stored in another one.

    Returns
    -------
    Path
        The written file path.

    Raises
    ------
    ValueError
        Raised when ``crs`` is missing.
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
    gdf = build_cell_geodataframe(zarr_path, sim_id, variable, timestep, layer=layer, crs=crs)
    gdf.to_file(str(output_path))
    logger.info("Exported Shapefile: %s (%d cells)", output_path, len(gdf))
    return output_path


def _native_crs(grp) -> str | None:
    """CRS the mesh vertices are expressed in, from the store's CF grid mapping."""
    node = grp.get("crs")
    if node is None:
        return None
    attrs = dict(node.attrs)
    epsg = attrs.get("epsg_code")
    if epsg is not None:
        return f"EPSG:{int(epsg)}"
    wkt = attrs.get("crs_wkt")
    return str(wkt) if wkt else None


def _resolve_zarr_path(grp, zarr_path: str):
    """Resolve a registry zarr_path inside the simulation group, or None if absent."""
    parts = zarr_path.split("/")
    cursor = grp
    for part in parts[:-1]:
        sub = cursor.get(part)
        if sub is None:
            return None
        cursor = sub
    leaf = parts[-1]
    if leaf in cursor:
        return cursor[leaf]
    return None
