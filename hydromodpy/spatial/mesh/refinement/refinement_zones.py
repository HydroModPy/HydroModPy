"""Zones of local mesh refinement, one ``[[mesh.refinement_zone]]`` table each.

A zone is either a vector layer (gpkg / shp / GeoJSON) named by ``path``, or
the pixels of the DEM grid where a field passes a threshold, named by
``where``. Polygon features refine as zones; point and line features are
dilated by ``buffer`` into corridors. A field is the height of the ground above
the stream it drains to, computed from the DEM and the river network traced
from it, or the water-table depth or the seepage of an earlier run of the
project. Each zone becomes one term of the size field, which ramps back to
the background size over ``buffer``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyPath, NonEmptyStr, StripLower

__all__ = ["RUN_FIELDS", "RefinementZoneConfig", "ZoneField"]

ZoneField = Literal["height_above_stream", "watertable_depth", "seepage"]
"""What a zone drawn by a threshold reads."""

RUN_FIELDS: tuple[str, ...] = ("watertable_depth", "seepage")
"""The fields read from an earlier run, which ``run`` names."""


class RefinementZoneConfig(HydroModelBase):
    """One zone of local refinement: a vector layer, or where a field passes a threshold."""

    path: Annotated[NonEmptyPath | None, Profile.USER] = Field(
        default=None,
        description=(
            "Vector layer (gpkg / shp / GeoJSON) of polygons (zones) and/or "
            "points or lines (corridors). A bare filename resolves against "
            "<workspace>/data/refinement_zone/; relative paths resolve against "
            "that directory, the data directory, then the config directory. Give "
            "path or where, not both."
        ),
        examples=["refinement_zone.gpkg"],
    )
    where: Annotated[Annotated[ZoneField, StripLower] | None, Profile.USER] = Field(
        default=None,
        description=(
            "The field whose threshold draws the zone, on the pixels of the DEM, "
            "instead of a vector layer. The zone is the set of pixels where the field "
            "is below the value of below, or above the value of above. Give path or "
            "where, not both."
        ),
        json_schema_extra={
            "value_docs": {
                "height_above_stream": (
                    "Height in metres of the ground above the stream it drains to, "
                    "computed from the DEM and the river network traced from it "
                    "([geographic.river_network]). The mapped network never enters. "
                    "Takes below."
                ),
                "watertable_depth": (
                    "Depth in metres of the water table below the ground in the run "
                    "named by run, at any of its time steps: its minimum over time is "
                    "compared to below, its maximum to above."
                ),
                "seepage": (
                    "Drain outflow per cell area, in mm/d, in the run named by run, at "
                    "any of its time steps: its maximum over time is compared to above, "
                    "its minimum to below."
                ),
            }
        },
        examples=["height_above_stream", "watertable_depth", "seepage"],
    )
    below: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "The zone holds the pixels where the field of where is below this value: "
            "metres for height_above_stream and watertable_depth, mm/d for seepage."
        ),
        json_schema_extra={"unit": "m, or mm/d for seepage"},
        examples=[2.0],
    )
    above: Annotated[float | None, Profile.USER] = Field(
        default=None,
        ge=0.0,
        description=(
            "The zone holds the pixels where the field of where is above this value: "
            "metres for watertable_depth, mm/d for seepage. Not read for "
            "height_above_stream."
        ),
        json_schema_extra={"unit": "m, or mm/d for seepage"},
        examples=[0.5],
    )
    run: Annotated[NonEmptyStr | None, Profile.USER] = Field(
        default=None,
        description=(
            "The earlier run of this project whose field draws the zone, for "
            "watertable_depth and seepage: its name, with or without its .vN (the "
            "latest version without), or its full sim_id. The run must be sealed and "
            "hold the field. The mesh then depends on that run: its sim_id enters the "
            "mesh request and the mesh cache key."
        ),
        examples=["nancon_coarse"],
    )
    cell_size: Annotated[float, Profile.USER] = Field(
        gt=0.0,
        description=(
            "Target cell size, in metres, inside the zone: the side of the square of the "
            "same mean area as the cells, as mesh.cell_size."
        ),
        json_schema_extra={"unit": "m"},
        examples=[20.0],
    )
    buffer: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Distance in metres over which the size grows back to the background size "
            "outside the zone, and corridor half-width for the point and line features "
            "of a layer. When omitted, derives 2 * cell_size. Must be >= cell_size so a "
            "corridor holds at least one target cell."
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

    @model_validator(mode="after")
    def _validate_source(self) -> RefinementZoneConfig:
        """A zone is a layer or a threshold on one field, with the keys that field reads."""
        if (self.path is None) == (self.where is None):
            raise ValueError(
                "[[mesh.refinement_zone]] gives either path (a vector layer) or where "
                "(a field and its threshold), and exactly one of them."
            )
        if self.path is not None:
            given = [key for key in ("below", "above", "run") if getattr(self, key) is not None]
            if given:
                raise ValueError(
                    f"[[mesh.refinement_zone]] path = {str(self.path)!r} reads a vector "
                    f"layer, and below, above and run only go with where: drop {', '.join(given)}."
                )
            return self
        if (self.below is None) == (self.above is None):
            raise ValueError(
                f"[[mesh.refinement_zone]] where = {self.where!r} needs one threshold: "
                "below or above, not both."
            )
        if self.where == "height_above_stream":
            if self.above is not None:
                raise ValueError(
                    "[[mesh.refinement_zone]] where = 'height_above_stream' refines low "
                    "ground: give below, the height in metres, instead of above."
                )
            if self.run is not None:
                raise ValueError(
                    "[[mesh.refinement_zone]] where = 'height_above_stream' is computed "
                    "from the DEM and reads no run: drop run."
                )
            return self
        if self.run is None:
            raise ValueError(
                f"[[mesh.refinement_zone]] where = {self.where!r} reads an earlier run of "
                "the project: name it with run."
            )
        return self

    def describe(self) -> str:
        """The zone in a few words, for a log line or a note."""
        if self.path is not None:
            return f"layer {self.path}"
        unit = "mm/d" if self.where == "seepage" else "m"
        side, value = ("below", self.below) if self.below is not None else ("above", self.above)
        text = f"{self.where} {side} {value:g} {unit}"
        return text if self.run is None else f"{text} in run {self.run}"
