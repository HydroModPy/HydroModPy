"""Everything the planner reads besides ``[mesh]``, gathered by the mesh step."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from shapely.geometry import LineString, Point, Polygon

from hydromodpy.mesh.planning.geology_contacts import GeologyLines
from hydromodpy.mesh.planning.lake_structures import LakeStructure
from hydromodpy.mesh.planning.refinement_zones import RefinementZone
from hydromodpy.mesh.request import InputTriangulation, RasterGridSpec

if TYPE_CHECKING:
    from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace

__all__ = ["PlanningInputs"]


@dataclass(frozen=True)
class PlanningInputs:
    """The project inputs of one mesh request, as plain data.

    ``domain`` is the polygon of the active extent; it is replaced by the
    outline of ``input_triangulation`` when a triangulation is read.
    ``watershed`` is the catchment the outside coarsening ramps away from.
    ``synthetic`` marks an analytical support, which has no catchment.
    ``barriers`` are the flow barrier lines: the cutoff wall of each lake laid on
    its shore, then the general flow barriers. ``outlet`` is the outlet the
    configuration declares, None without one: the smoothing of the catchment
    outline keeps it on the outline when it lies on it, as it keeps the end of
    a river. ``notes`` are what the mesh step left out while gathering the
    inputs; they reach the QA.
    """

    dem_grid: RasterGridSpec
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
    outlet: Point | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Freeze the sequences as tuples."""
        object.__setattr__(self, "lakes", tuple(self.lakes))
        object.__setattr__(self, "lake_structures", tuple(self.lake_structures))
        object.__setattr__(self, "refinement_zones", tuple(self.refinement_zones))
        object.__setattr__(self, "barriers", tuple(self.barriers))
        object.__setattr__(self, "notes", tuple(self.notes))

    @property
    def crs_wkt(self) -> str:
        """The CRS of the inputs, the one of the DEM grid."""
        return self.dem_grid.crs_wkt
