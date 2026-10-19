"""Everything the planner reads besides ``[mesh]``, gathered by the mesh step."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.planning.geology import GeologyLines
from hydromodpy.spatial.mesh.planning.refinement import RefinementZone
from hydromodpy.spatial.mesh.request import InputTriangulation, RasterGridSpec

if TYPE_CHECKING:
    from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace

__all__ = ["LakeStructure", "PlanningInputs"]

LakeStructure = tuple[str, BaseGeometry, float, float]
"""``(label, geometry, cell size [m], buffer [m])`` of a hydraulic structure of a lake."""


@dataclass(frozen=True)
class PlanningInputs:
    """The project inputs of one mesh request, as plain data.

    ``domain`` is the polygon of the active extent; it is replaced by the
    outline of ``input_triangulation`` when a triangulation is read.
    ``watershed`` is the catchment the outside coarsening ramps away from.
    ``synthetic`` marks an analytical support, which has no catchment.
    ``barriers`` are the flow barrier lines: the cutoff wall of each lake laid on
    its shore, then the general flow barriers. ``notes`` are what the mesh step
    left out while gathering the inputs; they reach the QA.
    """

    dem_grid: RasterGridSpec
    crs_wkt: str
    domain: Polygon
    river_trace: RiverMeshTrace | None
    watershed: Polygon | None
    lakes: tuple[Polygon, ...]
    lake_structures: tuple[LakeStructure, ...]
    geology: GeologyLines | None
    refinement_zones: tuple[RefinementZone, ...]
    input_triangulation: InputTriangulation | None
    synthetic: bool
    barriers: tuple[LineString, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a CRS that differs from the grid one."""
        if self.crs_wkt != self.dem_grid.crs_wkt:
            raise MeshRequestError("the planning inputs and the DEM grid name different CRS")
        object.__setattr__(self, "lakes", tuple(self.lakes))
        object.__setattr__(self, "lake_structures", tuple(self.lake_structures))
        object.__setattr__(self, "refinement_zones", tuple(self.refinement_zones))
        object.__setattr__(self, "barriers", tuple(self.barriers))
        object.__setattr__(self, "notes", tuple(self.notes))
