"""Lake-aware local mesh refinement for the GMSH conformal mesher.

A lake footprint (any shape) and the under-dam outlet are refined by adding
GMSH regional size fields: small target cells inside the lake polygon (the
shoreline / marnage band and the bathymetric bed resolve far better), and a
small disk around the dam/outlet (the under-dam vertical leakage zone). The
fields ramp back to the background size over a buffer, so the mesh stays coarse
elsewhere. The polygon makes it adaptable to any lake shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

__all__ = ["LakeRefinementConfig", "build_lake_refinement_size_fields"]


class LakeRefinementConfig(HydroModelBase):
    """Local mesh-refinement targets for the lake footprint and the dam outlet."""

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Refine the GMSH mesh on the lake footprint (+ the dam outlet).",
    )
    cell_size: Annotated[float, Profile.USER] = Field(
        default=40.0,
        gt=0.0,
        description="Target cell size [L] inside the lake footprint.",
    )
    buffer: Annotated[float, Profile.USER] = Field(
        default=200.0,
        ge=0.0,
        description="Transition distance [L] over which the lake size ramps back to global.",
    )
    dam_cell_size: Annotated[float, Profile.USER] = Field(
        default=30.0,
        gt=0.0,
        description="Target cell size [L] in the under-dam outlet zone.",
    )
    dam_buffer: Annotated[float, Profile.USER] = Field(
        default=150.0,
        gt=0.0,
        description="Radius [L] of the refined disk around the dam / catchment outlet.",
    )


def build_lake_refinement_size_fields(
    *,
    lake_polygon: BaseGeometry | None,
    dam_xy: tuple[float, float] | None,
    cfg: LakeRefinementConfig,
    global_size: float,
) -> tuple:
    """Return the GMSH regional size fields refining the lake (+ dam outlet).

    ``lake_polygon`` (any shape) drives the lake field; ``dam_xy`` the under-dam
    disk. Both ramp back to ``global_size`` over their buffer. Returns ``()`` when
    refinement is disabled or no geometry is available.
    """
    from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.contracts import (
        ZoneRegionalSizeField,
    )

    if not cfg.enabled:
        return ()

    fields: list = []
    if lake_polygon is not None and not lake_polygon.is_empty:
        fields.append(
            ZoneRegionalSizeField(
                name="lake::footprint",
                region_geometry=lake_polygon,
                inside_size=float(cfg.cell_size),
                outside_size=float(global_size),
                transition_distance=float(cfg.buffer),
                grid_resolution=float(min(cfg.cell_size, global_size)),
            )
        )
    if dam_xy is not None:
        from shapely.geometry import Point

        dam_region = Point(float(dam_xy[0]), float(dam_xy[1])).buffer(float(cfg.dam_buffer))
        fields.append(
            ZoneRegionalSizeField(
                name="lake::dam_outlet",
                region_geometry=dam_region,
                inside_size=float(cfg.dam_cell_size),
                outside_size=float(global_size),
                transition_distance=float(cfg.dam_buffer),
                grid_resolution=float(min(cfg.dam_cell_size, global_size)),
            )
        )
    return tuple(fields)
