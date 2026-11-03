"""The two tables of local mesh refinement, ``[mesh.lake_refinement]`` and ``[[mesh.refinement_zone]]``.

The lake refinement targets what matters physically around a lake: the
shoreline band (the marnage / LAK-footprint edge, where cell size controls the
footprint accuracy), the hydraulic structures (dam cutoff wall, lake-to-lake
sill, spillway or SFR entry points), and optionally the lake interior
(bathymetry needs). The lake interior is NOT refined by default: interior cells
contribute exact area whatever their size, only the shoreline cells control the
footprint over-count.

A refinement zone is either a vector layer (gpkg / shp / GeoJSON) named by
``path``, or the pixels of the DEM grid where a field passes a threshold, named
by ``where``. Polygon features refine as zones; point and line features are
dilated by ``buffer`` into corridors. A field is the height of the ground above
the stream it drains to, computed from the DEM and the river network traced
from it, or the water-table depth or the seepage of an earlier run of the
project.

Each target becomes one term of the size field, which ramps back to the
background size over its buffer, so the mesh stays coarse elsewhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyPath, NonEmptyStr, StripLower

__all__ = ["RUN_FIELDS", "LakeRefinementConfig", "RefinementZoneConfig", "ZoneField"]

ZoneField = Literal["height_above_stream", "watertable_depth", "seepage"]
"""What a zone drawn by a threshold reads."""

RUN_FIELDS: tuple[str, ...] = ("watertable_depth", "seepage")
"""The fields read from an earlier run, which ``run`` names."""


class RefinementZoneConfig(HydroModelBase):
    """One zone of local refinement: a vector layer, or where a field passes a threshold."""

    model_config = ConfigDict(allow_inf_nan=False)

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


class LakeRefinementConfig(HydroModelBase):
    """Local mesh-refinement targets for the lake shoreline and the hydraulic structures."""

    model_config = ConfigDict(allow_inf_nan=False)

    cell_size: Annotated[float, Profile.USER] = Field(
        default=40.0,
        gt=0.0,
        description=(
            "Target cell size, in metres, in the lake shoreline band: the side of the "
            "square of the same mean area as the cells, as mesh.cell_size."
        ),
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
            "(marnage / bathymetry resolution), with the meaning of mesh.cell_size. When "
            "omitted, the interior keeps the background size."
        ),
        json_schema_extra={"unit": "m"},
    )
    dam_cell_size: Annotated[float, Profile.USER] = Field(
        default=30.0,
        gt=0.0,
        description=(
            "Target cell size, in metres, in the hydraulic-structure zones (cutoff wall, "
            "sill), with the meaning of mesh.cell_size."
        ),
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

    @property
    def resolved_shoreline_band(self) -> float:
        """Half-width of the shoreline band, in metres: the key, else ``2 * cell_size``."""
        return self.shoreline_band if self.shoreline_band is not None else 2.0 * self.cell_size

    @property
    def resolved_hfb_buffer(self) -> float:
        """Half-width of the cutoff-wall zone, in metres: the key, else ``2 * dam_buffer``."""
        return self.hfb_buffer if self.hfb_buffer is not None else 2.0 * self.dam_buffer

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
