"""Regular cell mesh on the grid of a surface, for the scripts that drive a MODFLOW model by hand."""

from __future__ import annotations

from pyproj import CRS
from shapely.geometry import box

from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.request import MeshRequest, RasterGridSpec
from hydromodpy.spatial.surface import Surface


def regular_cell_mesh_of(
    surface: Surface, *, shape: tuple[int, int] | None = None
) -> PlanarCellMesh:
    """Return the ``regular`` engine mesh over the extent of *surface*.

    One cell per pixel of the surface support, or ``shape = (nrow, ncol)`` cells when given.
    """
    support = surface.support
    crs_wkt = CRS.from_user_input(support.crs).to_wkt()
    grid = RasterGridSpec.from_raster_support(support, crs_wkt=crs_wkt)
    options = {} if shape is None else {"shape": [int(shape[0]), int(shape[1])]}
    request = MeshRequest(
        domain=box(grid.xmin, grid.ymin, grid.xmax, grid.ymax),
        crs_wkt=crs_wkt,
        grid=grid,
        nominal_size_m=grid.dx,
        options=options,
    )
    return registry.create("regular").build(request)
