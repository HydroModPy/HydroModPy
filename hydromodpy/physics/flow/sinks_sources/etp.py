"""Diffuse evapotranspiration payload for the flow process."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, field_validator

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile
from hydromodpy.core.units import Length
from hydromodpy.physics.flow.sinks_sources._units import normalize_first_clim


class FlowEtpConfig(HydroModelBase):
    """
    Typed payload for diffuse evapotranspiration over the model domain.

    Drives the MODFLOW EVT package. Conceptually parallel to
    :class:`FlowRechargeConfig`: scalar / list / mapping / runtime-series
    payloads are accepted and converted to SI ``m/s`` at runtime via
    ``apply_etp_load_result_to_flow``. The actual conversion to a
    stress-period dictionary is handled by
    :class:`FlowToModflowAdapter._build_etp_payload`. This is the unique
    entry point for the EVT package.
    """

    model_config = ConfigDict(extra="forbid")

    values: Annotated[Any, Profile.USER] = Field(
        default=0.0,
        description=(
            "ETP payload: scalar, list (one per stress period), "
            "mapping {kper: value}, or runtime series. Values must be "
            "non-negative; the EVT package treats them as outflow rates."
        ),
    )
    heterogeneous_source: Annotated[Any, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional raw data source for heterogeneous (2D per-cell) ETP. "
            "When set, the solver adapter discretizes FieldRecords onto the "
            "MODFLOW grid instead of using the scalar 'values' field. "
            "Expected: LoadResult with FieldRecords."
        ),
    )
    first_clim: Annotated[str | float, Profile.DEV] = Field(
        default="mean",
        description=(
            "Period-0 policy when values is a sequence: "
            "'mean' (series average), 'first' (first element), or a numeric scalar."
        ),
    )
    units: Annotated[str, Profile.DEV] = Field(
        default="mm/day",
        description=(
            "Units of the ETP data source. Data-manager outputs use mm/day "
            "by convention; converted to m/s at runtime."
        ),
    )
    surface_offset: Annotated[Length, Profile.DEV] = Field(
        default=2.0,
        ge=0.0,
        description=(
            "Distance below the topographic surface (m) where the EVT "
            "extraction surface sits. MODFLOW EVT extracts water linearly "
            "between this surface and surface - extinction_depth. Legacy "
            "default was DEM - 2 m."
        ),
    )
    extinction_depth: Annotated[Length, Profile.DEV] = Field(
        default=1.0,
        gt=0.0,
        description=(
            "EVT extinction depth (m): below surface_offset + extinction_depth, "
            "evapotranspiration is zero. Legacy default was 1 m."
        ),
    )
    spatial_mode: Annotated[Literal["auto", "homogeneous", "heterogeneous"], Profile.DEV] = Field(
        default="auto",
        description=(
            "How to interpret spatial data: 'auto' (points->homogeneous, "
            "fields->heterogeneous), 'homogeneous', or 'heterogeneous'."
        ),
    )
    interpolation_method: Annotated[Literal["nearest", "linear", "idw"], Profile.DEV] = Field(
        default="nearest",
        description=(
            "Spatial interpolation method for gridded/point data onto the "
            "MODFLOW grid. Options: 'nearest', 'linear', 'idw'."
        ),
    )

    @field_validator("first_clim", mode="before")
    @classmethod
    def _validate_first_clim(cls, value):
        return normalize_first_clim(value)
