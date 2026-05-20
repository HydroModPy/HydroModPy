from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units import LengthMeters


class ConstantThicknessDepthModel(HydroModelBase):
    """
    Vertical model using one constant thickness below topography.

    Bottom elevation is computed cell-wise as:
    ``bottom = top_surface - thickness``.
    """

    kind: Annotated[Literal["constant_thickness"], Profile.USER] = Field(
        default="constant_thickness",
        description=(
            "Depth-model kind discriminator. Use 'constant_thickness' to define "
            "bottom as top-thickness."
        ),
    )
    thickness: Annotated[LengthMeters, Profile.USER] = Field(
        default=50.0,
        gt=0.0,
        description=(
            "Constant aquifer thickness applied below topography (canonical metres). "
            "Accepts inline units, e.g. '0.2 km'."
        ),
    )


class FlatSubstratumDepthModel(HydroModelBase):
    """
    Vertical model using one flat (constant-elevation) substratum.

    Bottom elevation is constant over the whole domain:
    ``bottom = substratum_elevation``.
    """

    kind: Annotated[Literal["flat_substratum"], Profile.USER] = Field(
        default="flat_substratum",
        description=(
            "Depth-model kind discriminator. "
            "Use 'flat_substratum' to define one constant bottom elevation."
        ),
    )
    substratum_elevation: Annotated[float, Profile.USER] = Field(
        default=0.0,
        description=("Flat substratum elevation (m) applied over the full domain."),
    )


DepthModelConfig: TypeAlias = Annotated[
    ConstantThicknessDepthModel | FlatSubstratumDepthModel,
    Field(
        discriminator="kind",
        description="Discriminated union of depth-model variants selected by the kind tag.",
    ),
]
