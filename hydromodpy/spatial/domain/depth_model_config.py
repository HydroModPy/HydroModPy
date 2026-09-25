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
    substratum_elevation: Annotated[LengthMeters, Profile.USER] = Field(
        default=0.0,
        description=(
            "Flat substratum elevation applied over the full domain (canonical metres). "
            "Accepts inline units, e.g. '40 m'. This is an ABSOLUTE elevation, not a "
            "depth below topography: where the land surface drops under it, no aquifer "
            "is left. Use 'constant_thickness' to follow the relief instead."
        ),
    )


class RasterDepthModel(HydroModelBase):
    """
    What the two raster depth models share.

    Both read the raster ``[data.substratum]`` declares. It is reprojected onto
    the grid of the top surface and must cover every cell of the domain: the
    whole catchment for ``geographic.domain_extent = "watershed"``, the whole
    buffered box for ``"box"``. The substratum it places is shifted by
    ``offset``, then capped at ``top - min_thickness``.
    """

    kind: str
    offset: Annotated[LengthMeters, Profile.USER] = Field(
        default=0.0,
        description=(
            "Vertical shift added to the substratum everywhere (canonical metres). "
            "Positive raises it, so it thins the aquifer. One number to move the whole "
            "surface, for a sensitivity test for example. Accepts inline units, e.g. '-5 m'."
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


class RasterSubstratumDepthModel(RasterDepthModel):
    """
    Vertical model reading the substratum elevation from a raster.

    The raster twin of ``flat_substratum``: ``bottom = raster + offset``.
    """

    kind: Annotated[Literal["raster_substratum"], Profile.USER] = Field(
        default="raster_substratum",
        description=(
            "Depth-model kind discriminator. Use 'raster_substratum' when the raster "
            "declared under [data.substratum] holds the elevation of the substratum "
            "(metres, same datum as the DEM)."
        ),
    )


class RasterThicknessDepthModel(RasterDepthModel):
    """
    Vertical model reading the aquifer thickness from a raster.

    The raster twin of ``constant_thickness``:
    ``bottom = top - scale * raster + offset``.
    """

    kind: Annotated[Literal["raster_thickness"], Profile.USER] = Field(
        default="raster_thickness",
        description=(
            "Depth-model kind discriminator. Use 'raster_thickness' when the raster "
            "declared under [data.substratum] holds the aquifer thickness below the "
            "top surface (metres)."
        ),
    )
    scale: Annotated[float, Profile.USER] = Field(
        default=1.0,
        gt=0.0,
        description="Factor applied to the thickness raster (dimensionless).",
    )


RASTER_DEPTH_MODEL_KINDS = frozenset({"raster_substratum", "raster_thickness"})
"""The depth-model kinds that read the ``[data.substratum]`` raster."""


DepthModelConfig: TypeAlias = Annotated[
    ConstantThicknessDepthModel
    | FlatSubstratumDepthModel
    | RasterSubstratumDepthModel
    | RasterThicknessDepthModel,
    Field(
        discriminator="kind",
        description="Discriminated union of depth-model variants selected by the kind tag.",
    ),
]
