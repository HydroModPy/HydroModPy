"""Lake-aware local mesh refinement.

Refinement targets what matters physically around a lake: the shoreline band
(the marnage / LAK-footprint edge, where cell size controls the footprint
accuracy), the hydraulic structures (dam cutoff wall, lake-to-lake sill,
spillway or SFR entry points), and optionally the lake interior (bathymetry
needs). Each target becomes one regional size field that ramps back to the
background size, so the mesh stays coarse elsewhere. The lake interior is
NOT refined by default: interior cells contribute exact area whatever their
size, only the shoreline cells control the footprint over-count.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

__all__ = ["LakeRefinementConfig"]


class LakeRefinementConfig(HydroModelBase):
    """Local mesh-refinement targets for the lake shoreline and the hydraulic structures."""

    cell_size: Annotated[float, Profile.USER] = Field(
        default=40.0,
        gt=0.0,
        description="Target cell size, in metres, in the lake shoreline band.",
        json_schema_extra={"unit": "m"},
    )
    shoreline_band: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Half-width, in metres, of the refined band around the lake shoreline. "
            "When omitted, derives 2 * cell_size. Must be >= cell_size so the "
            "band holds at least one target cell (a thinner band would slip "
            "between the size-field sampling nodes)."
        ),
        json_schema_extra={"unit": "m"},
    )
    buffer: Annotated[float, Profile.USER] = Field(
        default=200.0,
        ge=0.0,
        description="Transition distance, in metres, over which the lake sizes ramp back to global.",
        json_schema_extra={"unit": "m"},
    )
    interior_size: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Optional target cell size, in metres, inside the whole lake footprint "
            "(marnage / bathymetry resolution). When omitted, the interior "
            "keeps the background size."
        ),
        json_schema_extra={"unit": "m"},
    )
    dam_cell_size: Annotated[float, Profile.USER] = Field(
        default=30.0,
        gt=0.0,
        description="Target cell size, in metres, in the hydraulic-structure zones (cutoff wall, sill).",
        json_schema_extra={"unit": "m"},
    )
    dam_buffer: Annotated[float, Profile.USER] = Field(
        default=150.0,
        gt=0.0,
        description=(
            "Base half-width, in metres, of the structure refinement corridors; also the "
            "radius of the optional dam-outlet disk."
        ),
        json_schema_extra={"unit": "m"},
    )
    hfb_buffer: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Half-width, in metres, of the refined zone around the dam cutoff wall (HFB). "
            "The zone covers the lake outlet area. When omitted, derives 2 * dam_buffer. "
            "Must be >= dam_cell_size so the zone holds at least one target cell."
        ),
        json_schema_extra={"unit": "m"},
    )
    dam_outlet_disk: Annotated[bool | None, Profile.USER] = Field(
        default=None,
        description=(
            "Refine a disk of radius dam_buffer around the dam / catchment outlet. "
            "None (auto) emits the disk unless a cutoff-wall zone overlaps it: the "
            "widened HFB zone then already covers the outlet."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _the_table_alone_switches_the_refinement_on(cls, data: Any) -> Any:
        """Refuse ``enabled``: the table is the switch, and removing it switches it off."""
        if isinstance(data, Mapping) and "enabled" in data:
            raise ValueError(
                "[mesh.lake_refinement] has no 'enabled' key: the table being present "
                "switches the lake refinement on. Remove the key, or remove the table to "
                "mesh without lake refinement."
            )
        return data

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
