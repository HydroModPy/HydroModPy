from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

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
    substratum_elevation: Annotated[LengthMeters, Profile.USER] = Field(
        default=0.0,
        description=(
            "Flat substratum elevation applied over the full domain (canonical metres). "
            "Accepts inline units, e.g. '40 m'. This is an ABSOLUTE elevation, not a "
            "depth below topography: where the land surface drops under it, no aquifer "
            "is left. Use 'constant_thickness' to follow the relief instead."
        ),
    )


class RasterSubstratumDepthModel(HydroModelBase):
    """
    Vertical model reading the substratum from a raster.

    The raster is the one ``[data.substratum]`` declares. It is reprojected
    onto the grid of the top surface and must cover every cell of the domain,
    so the whole catchment for ``geographic.domain_extent = "watershed"`` and
    the whole buffered box for ``"box"``. Bottom elevation is computed cell-wise
    as ``bottom = raster + offset`` for an elevation raster, and
    ``bottom = top - scale * raster + offset`` for a thickness raster. It is then
    capped at ``top - min_thickness``.
    """

    kind: Annotated[Literal["raster"], Profile.USER] = Field(
        default="raster",
        description=(
            "Depth-model kind discriminator. Use 'raster' to read the substratum "
            "from the raster declared under [data.substratum]."
        ),
    )
    quantity: Annotated[Literal["elevation", "thickness"], Profile.USER] = Field(
        default="elevation",
        description=(
            "What the raster values are. 'elevation': the absolute elevation of the "
            "substratum (metres, same datum as the DEM). 'thickness': the aquifer "
            "thickness below the top surface (metres)."
        ),
    )
    offset: Annotated[LengthMeters, Profile.USER] = Field(
        default=0.0,
        description=(
            "Vertical shift added to the substratum everywhere (canonical metres). "
            "Positive raises it, so it thins the aquifer. One number to move the whole "
            "surface, for a sensitivity test for example. Accepts inline units, e.g. '-5 m'."
        ),
    )
    scale: Annotated[float, Profile.USER] = Field(
        default=1.0,
        gt=0.0,
        description=(
            "Factor applied to a thickness raster before it is subtracted from the "
            "top (dimensionless). Only valid with quantity = 'thickness'."
        ),
    )
    min_thickness: Annotated[LengthMeters, Profile.USER] = Field(
        default=1.0,
        gt=0.0,
        description=(
            "Smallest aquifer thickness kept under the top (canonical metres). Where "
            "the raster places the substratum higher than top - min_thickness, it is "
            "lowered to that level and a warning counts the cells."
        ),
    )

    @model_validator(mode="after")
    def _scale_needs_a_thickness(self) -> RasterSubstratumDepthModel:
        if self.quantity == "elevation" and self.scale != 1.0:
            raise ValueError(
                "domain.depth_model.scale multiplies a thickness raster; with "
                "quantity = 'elevation' use offset to move the substratum."
            )
        return self


DepthModelConfig: TypeAlias = Annotated[
    ConstantThicknessDepthModel | FlatSubstratumDepthModel | RasterSubstratumDepthModel,
    Field(
        discriminator="kind",
        description="Discriminated union of depth-model variants selected by the kind tag.",
    ),
]
