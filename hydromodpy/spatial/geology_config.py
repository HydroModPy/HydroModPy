"""Geology polygons or raster a mesh follows, and one geology field definition.

``[mesh_catchment.geology]`` is read with these models, and so is the mapping
``GeologyField.from_dict`` takes. The paths are typed ``Path``, so a testbed or
a comparison child makes them absolute like every other path of its config.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import (
    CellSamplingDensity,
    NonEmptyPath,
    NonEmptyStr,
    OptionalPath,
    StripLower,
)

SourceKind = Annotated[Literal["auto", "raster", "vector"], StripLower]


class GeologySource(HydroModelBase):
    """The geology dataset the mesh follows, and how its polygons or cells are read."""

    path: Annotated[NonEmptyPath, Profile.USER] = Field(
        description=(
            "Path to the raw geology dataset used by the meshing workflow. "
            "It can point to a raster or polygon vector file depending on kind."
        )
    )
    kind: Annotated[SourceKind, Profile.USER] = Field(
        default="auto",
        description=(
            "How to interpret the geology source. "
            "Use 'vector' for polygon geology, 'raster' for an already rasterized grid, or 'auto' to infer the type from the file."
        ),
    )
    code_field: Annotated[NonEmptyStr | None, Profile.USER] = Field(
        default=None,
        description=(
            "Attribute column carrying the geology code for each polygon when kind='vector'."
        ),
    )
    reference_raster_path: Annotated[OptionalPath, Profile.USER] = Field(
        default=None,
        description=(
            "Reference raster used when vector geology must be rasterized. "
            "Its extent and resolution define the target encoding grid."
        ),
    )
    all_touched: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Rasterization rule for vector geology. "
            "When true, any pixel touched by a polygon is filled; when false, only pixels whose center falls inside are filled."
        ),
    )

    @model_validator(mode="after")
    def _validate_vector_constraints(self):
        if self.kind == "vector":
            if self.code_field is None:
                raise ValueError("For vector source, 'code_field' is required")
            if self.reference_raster_path is None:
                raise ValueError("For vector source, 'reference_raster_path' is required")
        return self


class GeologyLandSea(HydroModelBase):
    """Optional sea-mask override for coastal workflows."""

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=("Enable the coastal override that replaces geology values over sea areas."),
    )
    path: Annotated[OptionalPath, Profile.USER] = Field(
        default=None,
        description=(
            "Mask raster or vector path used when landsea.enabled=true. "
            "The mask is interpreted so that sea pixels/features overwrite the base geology code."
        ),
    )
    sea_value: Annotated[float, Profile.USER] = Field(
        default=0.0,
        description=(
            "Value of the land/sea mask that marks the sea. Cells of the mask that hold it "
            "take the geology code override_code."
        ),
        json_schema_extra=field_metadata(unit="-"),
    )
    override_code: Annotated[NonEmptyStr, Profile.USER] = Field(
        default="1",
        description=(
            "Geology code written into sea areas after applying the land/sea mask. "
            "Choose a stable code that is meaningful in downstream parameter tables."
        ),
    )

    @model_validator(mode="after")
    def _validate_path_when_enabled(self):
        if self.enabled and self.path is None:
            raise ValueError("landsea.path is required when landsea.enabled=true")
        return self


class GeologyConfigBlock(HydroModelBase):
    """Geology the mesh follows: its source, an optional clip and a coastal override."""

    id: Annotated[NonEmptyStr, Profile.USER] = Field(
        default="field_geology",
        description=(
            "Logical identifier of the geology field once loaded into HydroModPy. "
            "This id is reused by support discretization and by parameter mappings that target geology-based zonation."
        ),
    )
    source: Annotated[GeologySource, Profile.USER] = Field(
        description=(
            "Raw geology source definition. "
            "This section explains where the geology polygons or raster come from and how they should be interpreted."
        )
    )
    clip_polygon_path: Annotated[OptionalPath, Profile.USER] = Field(
        default=None,
        description=(
            "Optional polygon mask applied before meshing or field projection. "
            "Use it to crop a very large national dataset to one smaller study area before further processing."
        ),
    )
    landsea: Annotated[GeologyLandSea, Profile.USER] = Field(
        default_factory=GeologyLandSea,
        description=("Optional coastal override applied after loading the base geology source."),
    )
    cell_samples_per_axis: Annotated[CellSamplingDensity, Profile.USER] = Field(
        default=8,
        description=(
            "Number of sample points along each axis of a mesh cell when the geology fractions "
            "are projected onto the mesh. More points give better fractions in narrow or "
            "irregular polygons and take longer."
        ),
        json_schema_extra=field_metadata(unit="-"),
    )


__all__ = ["GeologyConfigBlock", "GeologyLandSea", "GeologySource"]
