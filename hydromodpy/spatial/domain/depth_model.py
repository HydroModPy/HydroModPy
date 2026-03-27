from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, Field, field_validator

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.core.units.length import parse_length_to_m


class ConstantThicknessDepthModel(BaseModel):
    """
    Vertical model using one constant thickness below topography.

    Bottom elevation is computed cell-wise as:
    ``bottom = top_surface - thickness``.
    """

    type: Annotated[Literal["constant_thickness"], ParamLevel("user")] = Field(
        default="constant_thickness",
        description=(
            "Depth-model type selector. "
            "Use 'constant_thickness' to define bottom as top-thickness."
        ),
    )
    thickness: Annotated[float, ParamLevel("user")] = Field(
        default=50.0,
        gt=0.0,
        description=(
            "Constant aquifer thickness (m) applied below topography."
        ),
    )

    @field_validator("thickness", mode="before")
    @classmethod
    def _parse_thickness_to_m(cls, value):
        return parse_length_to_m(
            value,
            default_unit="m",
            label="domain.depth_model.thickness",
        )


class FlatSubstratumDepthModel(BaseModel):
    """
    Vertical model using one flat (constant-elevation) substratum.

    Bottom elevation is constant over the whole domain:
    ``bottom = substratum_elevation``.
    """

    type: Annotated[Literal["flat_substratum"], ParamLevel("user")] = Field(
        default="flat_substratum",
        description=(
            "Depth-model type selector. "
            "Use 'flat_substratum' to define one constant bottom elevation."
        ),
    )
    substratum_elevation: Annotated[float, ParamLevel("user")] = Field(
        default=0.0,
        description=(
            "Flat substratum elevation (m) applied over the full domain."
        ),
    )


DepthModelConfig: TypeAlias = Annotated[
    ConstantThicknessDepthModel | FlatSubstratumDepthModel,
    Field(discriminator="type"),
]
