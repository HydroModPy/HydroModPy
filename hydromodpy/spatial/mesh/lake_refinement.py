"""Lake-aware local mesh refinement for the GMSH conformal mesher.

Refinement targets what matters physically around a lake: the shoreline band
(the marnage / LAK-footprint edge, where cell size controls the footprint
accuracy), the hydraulic structures (dam cutoff wall, lake-to-lake sill,
spillway or SFR entry points), and optionally the lake interior (bathymetry
needs). Each target becomes one GMSH regional size field that ramps back to
the background size, so the mesh stays coarse elsewhere. The lake interior is
NOT refined by default: interior cells contribute exact area whatever their
size, only the shoreline cells control the footprint over-count.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

if TYPE_CHECKING:
    from collections.abc import Sequence

    from shapely.geometry.base import BaseGeometry

__all__ = ["LakeRefinementConfig", "build_lake_refinement_size_fields"]


class LakeRefinementConfig(HydroModelBase):
    """Local mesh-refinement targets for the lake shoreline and the hydraulic structures."""

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Refine the GMSH mesh on the lake shoreline band (+ hydraulic structures).",
    )
    cell_size: Annotated[float, Profile.USER] = Field(
        default=40.0,
        gt=0.0,
        description="Target cell size [L] in the lake shoreline band.",
    )
    shoreline_band: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Half-width [L] of the refined band around the lake shoreline. "
            "When omitted, derives 2 * cell_size. Must be >= cell_size so the "
            "band holds at least one target cell (a thinner band would slip "
            "between the size-field sampling nodes)."
        ),
    )
    buffer: Annotated[float, Profile.USER] = Field(
        default=200.0,
        ge=0.0,
        description="Transition distance [L] over which the lake sizes ramp back to global.",
    )
    interior_size: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Optional target cell size [L] inside the whole lake footprint "
            "(marnage / bathymetry resolution). When omitted, the interior "
            "keeps the background size."
        ),
    )
    dam_cell_size: Annotated[float, Profile.USER] = Field(
        default=30.0,
        gt=0.0,
        description="Target cell size [L] in the hydraulic-structure zones (cutoff wall, sill).",
    )
    dam_buffer: Annotated[float, Profile.USER] = Field(
        default=150.0,
        gt=0.0,
        description=(
            "Base half-width [L] of the structure refinement corridors; also the "
            "radius of the optional dam-outlet disk."
        ),
    )
    hfb_buffer: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Half-width [L] of the refined zone around the dam cutoff wall (HFB). "
            "The zone covers the lake outlet area. When omitted, derives 2 * dam_buffer. "
            "Must be >= dam_cell_size so the zone holds at least one target cell."
        ),
    )
    dam_outlet_disk: Annotated[bool | None, Profile.USER] = Field(
        default=None,
        description=(
            "Refine a disk of radius dam_buffer around the dam / catchment outlet. "
            "None (auto) emits the disk unless a cutoff-wall zone overlaps it: the "
            "widened HFB zone then already covers the outlet."
        ),
    )

    @model_validator(mode="after")
    def _validate_cross_constraints(self) -> LakeRefinementConfig:
        if self.interior_size is not None and self.interior_size < self.cell_size:
            raise ValueError(
                "interior_size refines the lake interior below the shoreline band "
                "(cell_size); set cell_size lower instead."
            )
        if self.shoreline_band is not None and self.shoreline_band < self.cell_size:
            raise ValueError(
                "shoreline_band must be >= cell_size: a band thinner than one target "
                "cell slips between the size-field sampling nodes and silently "
                "meshes at the background size."
            )
        if self.hfb_buffer is not None and self.hfb_buffer < self.dam_cell_size:
            raise ValueError(
                "hfb_buffer must be >= dam_cell_size: a corridor thinner than one "
                "target cell slips between the size-field sampling nodes."
            )
        return self


def build_lake_refinement_size_fields(
    *,
    lake_polygon: BaseGeometry | None,
    dam_xy: tuple[float, float] | None,
    cfg: LakeRefinementConfig,
    global_size: float,
    feature_geometries: Sequence[tuple[str, BaseGeometry, float, float]] = (),
    has_cutoff_wall: bool = False,
) -> tuple:
    """Return the GMSH regional size fields refining the lake + hydraulic features.

    ``lake_polygon`` (any shape) drives the shoreline band field (the polygon
    boundary buffered to ``shoreline_band``), plus one optional interior field
    when ``interior_size`` is set. ``feature_geometries`` are ``(label,
    geometry, target_size, zone_buffer)`` tuples for the discrete hydraulic
    structures that must be well resolved so their HFB face / weir / exchange
    lands cleanly on the mesh: the dam cutoff wall (voile), the sill between
    two coupled lakes (its target size must be smaller than the lake-to-lake
    gap, else one cell straddles both lakes and MF6 LAK rejects it), spillway /
    outlet points, SFR->lake entries. Point and line geometries are dilated by
    ``zone_buffer`` to a refinement zone; polygons are used as-is and
    ``zone_buffer`` only sets the transition distance. The ``dam_xy`` disk is
    redundant with a cutoff-wall zone (the wall sits at the lake outlet), so
    with ``dam_outlet_disk=None`` it is emitted only when ``has_cutoff_wall``
    is False. All fields ramp back to ``global_size``. Returns ``()`` when
    refinement is disabled or no geometry is available.
    """
    from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.contracts import (
        ZoneRegionalSizeField,
    )

    if not cfg.enabled:
        return ()

    fields: list = []
    if lake_polygon is not None and not lake_polygon.is_empty:
        band = float(cfg.shoreline_band if cfg.shoreline_band is not None else 2.0 * cfg.cell_size)
        fields.append(
            ZoneRegionalSizeField(
                name="lake::shoreline",
                region_geometry=lake_polygon.boundary.buffer(band),
                inside_size=float(cfg.cell_size),
                outside_size=float(global_size),
                transition_distance=float(cfg.buffer),
                grid_resolution=float(min(cfg.cell_size, global_size)),
            )
        )
        if cfg.interior_size is not None:
            fields.append(
                ZoneRegionalSizeField(
                    name="lake::interior",
                    region_geometry=lake_polygon,
                    inside_size=float(cfg.interior_size),
                    outside_size=float(global_size),
                    transition_distance=float(cfg.buffer),
                    grid_resolution=float(min(cfg.interior_size, global_size)),
                )
            )
    emit_dam_disk = cfg.dam_outlet_disk is True or (
        cfg.dam_outlet_disk is None and not has_cutoff_wall
    )
    if dam_xy is not None and emit_dam_disk:
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
    for label, geom, target_size, zone_buffer in feature_geometries:
        if geom is None or geom.is_empty:
            continue
        size = float(target_size)
        width = float(zone_buffer)
        region = geom if geom.geom_type in ("Polygon", "MultiPolygon") else geom.buffer(width)
        fields.append(
            ZoneRegionalSizeField(
                name=f"feature::{label}",
                region_geometry=region,
                inside_size=size,
                outside_size=float(global_size),
                transition_distance=width,
                grid_resolution=float(min(size, global_size)),
            )
        )
    return tuple(fields)
