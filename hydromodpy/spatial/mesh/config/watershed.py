"""Optional watershed-boundary mesh-constraint configs."""

from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units import Length


class MeshCatchmentWatershedBoundarySmoothingConfig(HydroModelBase):
    """Optional smoothing controls for the watershed-boundary constraint."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "If true, apply the smoothing controls below before converting the watershed boundary into one linear constraint."
        ),
    )
    distance: Annotated[Length | None, Profile.DEV] = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional regularization tolerance, in projected metres, used to simplify the watershed boundary "
            "at roughly the target internal mesh scale before it is injected as a linear mesh constraint. "
            "When omitted, the mesher reuses zone_meshing.global_size."
        ),
    )
    river_buffer_distance: Annotated[Length | None, Profile.DEV] = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional protective buffer around river traces, in projected metres, merged into the boundary-support "
            "polygon before smoothing so the final watershed boundary stays slightly outside river corridors near the basin edge."
        ),
    )
    outer_bias_distance: Annotated[Length | None, Profile.DEV] = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional outward bias, in projected metres, applied after smoothing so the final watershed boundary "
            "remains slightly englobing instead of cutting back toward the raw catchment contour."
        ),
    )


class MeshCatchmentWatershedOutsideCoarseningConfig(HydroModelBase):
    """Optional coarse-background size controls outside the watershed."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "If true, add one regional mesh-size field that keeps the current background size inside the watershed "
            "and coarsens the mesh outside it."
        ),
    )
    size_factor: Annotated[float, Profile.DEV] = Field(
        default=2.0,
        ge=1.0,
        description=(
            "Multiplicative factor applied to zone_meshing.global_size outside the watershed. "
            "Use 2.0 for an outside background roughly twice as coarse as the internal baseline."
        ),
    )
    transition_distance: Annotated[Length | None, Profile.DEV] = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional transition width, in projected metres, used to ramp from the internal background size "
            "to the coarser outside size away from the watershed boundary."
        ),
    )
    grid_resolution: Annotated[Length | None, Profile.DEV] = Field(
        default=None,
        gt=0.0,
        description=(
            "Optional structured-grid resolution, in projected metres, used to discretize the outside coarsening field. "
            "When omitted, the mesher reuses zone_meshing.global_size."
        ),
    )


class MeshCatchmentWatershedGeologyConformityConfig(HydroModelBase):
    """Optional control of where geology remains conformal around the watershed."""

    model_config = ConfigDict(extra="forbid")

    mode: Annotated[str, Profile.USER] = Field(
        default="full_domain",
        description=(
            "Control where geology remains conformal. "
            "Use 'full_domain' to keep the current behavior, or 'buffered_watershed_envelope' "
            "to keep geology interfaces active only inside one buffered envelope around the regularized watershed, "
            "without creating one strict partition boundary on that envelope."
        ),
    )
    buffer_distance: Annotated[Length | None, Profile.DEV] = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional outward buffer, in projected metres, added around the regularized watershed before selecting "
            "where geology interfaces remain active. When omitted in buffered_watershed_envelope mode, the mesher reuses zone_meshing.global_size."
        ),
    )

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, value: object) -> str:
        token = str(value).strip().lower()
        if token not in {"full_domain", "buffered_watershed_envelope"}:
            raise ValueError(
                "geology_conformity.mode must be 'full_domain' or 'buffered_watershed_envelope'."
            )
        return token


class MeshCatchmentWatershedBoundaryConfig(HydroModelBase):
    """Optional watershed-boundary mesh constraint."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "If true, inject the watershed boundary as one dedicated linear constraint in addition to geology "
            "and/or river constraints."
        ),
    )
    boundary_refinement_distance: Annotated[Length | None, Profile.DEV] = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional influence distance, in projected metres, used for the watershed-boundary refinement family. "
            "When omitted, the mesher derives one conservative distance from the boundary extent."
        ),
    )
    smoothing: Annotated[MeshCatchmentWatershedBoundarySmoothingConfig, Profile.USER] = Field(
        default_factory=MeshCatchmentWatershedBoundarySmoothingConfig,
        description=(
            "Optional regularization controls applied before the watershed boundary is converted to a linear constraint."
        ),
    )
    outside_coarsening: Annotated[MeshCatchmentWatershedOutsideCoarseningConfig, Profile.USER] = (
        Field(
            default_factory=MeshCatchmentWatershedOutsideCoarseningConfig,
            description=(
                "Optional coarse-background size field applied outside the regularized watershed while keeping the geology partition unchanged."
            ),
        )
    )
    geology_conformity: Annotated[MeshCatchmentWatershedGeologyConformityConfig, Profile.USER] = (
        Field(
            default_factory=MeshCatchmentWatershedGeologyConformityConfig,
            description=(
                "Optional control of where geology remains conformal relative to the watershed. "
                "Keep the default full_domain mode to preserve the current behavior."
            ),
        )
    )


__all__ = [
    "MeshCatchmentWatershedBoundaryConfig",
    "MeshCatchmentWatershedBoundarySmoothingConfig",
    "MeshCatchmentWatershedGeologyConformityConfig",
    "MeshCatchmentWatershedOutsideCoarseningConfig",
]
