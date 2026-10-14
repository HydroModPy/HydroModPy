"""User-provided zones of interest for local mesh refinement.

Each ``[[mesh.refinement_zone]]`` entry names a vector layer
(gpkg / shp / GeoJSON) and a target cell size. Polygon features refine as
zones; point and line features are dilated by ``buffer`` into corridors.
All features of one entry merge into one regional size field that
ramps back to the background size over ``buffer``.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyPath

__all__ = ["RefinementZoneConfig"]


class RefinementZoneConfig(HydroModelBase):
    """One user-provided refinement zone layer."""

    path: Annotated[NonEmptyPath, Profile.USER] = Field(
        description=(
            "Vector layer (gpkg / shp / GeoJSON) of polygons (zones) and/or "
            "points or lines (corridors). A bare filename resolves against "
            "<workspace>/data/refinement_zone/; relative paths resolve against "
            "that directory, the data directory, then the config directory."
        ),
        examples=["refinement_zone.gpkg"],
    )
    cell_size: Annotated[float, Profile.USER] = Field(
        gt=0.0,
        description="Target cell size, in metres, inside the zone.",
        json_schema_extra={"unit": "m"},
        examples=[20.0],
    )
    buffer: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Corridor half-width, in metres, for point / line features, and transition "
            "distance back to the background size. When omitted, derives 2 * cell_size. "
            "Must be >= cell_size so the corridor holds at least one target cell."
        ),
        json_schema_extra={"unit": "m"},
    )

    @model_validator(mode="after")
    def _validate_buffer(self) -> RefinementZoneConfig:
        if self.buffer is not None and self.buffer < self.cell_size:
            raise ValueError(
                "buffer must be >= cell_size: a corridor thinner than one target "
                "cell slips between the size-field sampling nodes and silently "
                "meshes at the background size."
            )
        return self
