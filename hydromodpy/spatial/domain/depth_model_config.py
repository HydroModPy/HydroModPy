from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import ConfigDict, Field, field_validator

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile
from hydromodpy.core.units.length import parse_length_to_m


class ConstantThicknessDepthModel(HydroModelBase):
    """
    Vertical model using one constant thickness below topography.

    Bottom elevation is computed cell-wise as:
    ``bottom = top_surface - thickness``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Annotated[Literal["constant_thickness"], Profile.USER] = Field(
        default="constant_thickness",
        description=(
            "Depth-model type selector. Use 'constant_thickness' to define bottom as top-thickness."
        ),
    )
    thickness: Annotated[float, Profile.USER] = Field(
        default=50.0,
        gt=0.0,
        description=("Constant aquifer thickness (m) applied below topography."),
    )

    @field_validator("thickness", mode="before")
    @classmethod
    def _parse_thickness_to_m(cls, value):
        return parse_length_to_m(
            value,
            default_unit="m",
            label="domain.depth_model.thickness",
        )


class FlatSubstratumDepthModel(HydroModelBase):
    """
    Vertical model using one flat (constant-elevation) substratum.

    Bottom elevation is constant over the whole domain:
    ``bottom = substratum_elevation``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Annotated[Literal["flat_substratum"], Profile.USER] = Field(
        default="flat_substratum",
        description=(
            "Depth-model type selector. "
            "Use 'flat_substratum' to define one constant bottom elevation."
        ),
    )
    substratum_elevation: Annotated[float, Profile.USER] = Field(
        default=0.0,
        description=("Flat substratum elevation (m) applied over the full domain."),
    )


DepthModelConfig: TypeAlias = Annotated[
    ConstantThicknessDepthModel | FlatSubstratumDepthModel,
    Field(discriminator="type"),
]
