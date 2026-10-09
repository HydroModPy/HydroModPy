"""Diffuse evapotranspiration payload for the flow process."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, PrivateAttr, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units import Length, LengthMeters
from hydromodpy.physics.flow.sinks_sources._units import normalize_first_clim
from hydromodpy.physics.forcing.types import InterpolationMethod, SpatialMode
from hydromodpy.physics.forcing.validation import ensure_non_negative_numeric_payload


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
            "ETP rate of every steady stress period, read by MODFLOW-NWT: every "
            "period of a steady run, and the first period of a transient run when "
            "flow.first_period_steady is true. 'mean' is the mean of the "
            "per-period rates, one weight per period; 'first' is the rate of "
            "period 0; a number is that rate. A transient period keeps its own "
            "rate."
        ),
        examples=["mean", "first", 2.0],
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
            "Distance (m) the EVT surface sits below its reference. Under "
            "MODFLOW-NWT the reference is the topographic surface and the "
            "default is 2 m. In soil mode under MODFLOW 6 the reference is the "
            "drain elevation of the cell (the top, or the top minus half of "
            "solver.drain_band_depth_m) and the default is 0 m, since the soil "
            "reservoir has already taken the ETP it could."
        ),
    )
    extinction_depth: Annotated[LengthMeters, Profile.USER] = Field(
        default=1.0,
        gt=0.0,
        description=(
            "Depth (m) below the EVT surface where the water table stops "
            "evaporating; the rate falls linearly between the surface and this "
            "depth. 1 m by default. Read by MODFLOW-NWT, and by MODFLOW 6 in "
            "soil mode for the ETP the soil left unmet. Calibrate it with "
            "[calibration.parameters.extinction_depth]; the range belongs to the "
            "site, so a file has to state it."
        ),
        json_schema_extra=field_metadata(calibrable=Calibrable(units="m")),
    )
    spatial_mode: Annotated[SpatialMode, Profile.DEV] = Field(
        default="auto",
        description=(
            "How to interpret spatial data: 'auto' (points->homogeneous, "
            "fields->heterogeneous), 'homogeneous', or 'heterogeneous'."
        ),
    )
    interpolation_method: Annotated[InterpolationMethod, Profile.DEV] = Field(
        default="nearest",
        description=(
            "Spatial interpolation method for gridded/point data onto the "
            "MODFLOW grid. Options: 'nearest', 'linear', 'idw'."
        ),
    )

    _from_soil_reservoir: bool = PrivateAttr(default=False)

    @property
    def from_soil_reservoir(self) -> bool:
        """Whether this ETP is what the soil reservoir left unmet."""
        return self._from_soil_reservoir

    @field_validator("first_clim", mode="before")
    @classmethod
    def _validate_first_clim(cls, value):
        return normalize_first_clim(value)

    @field_validator("values", mode="before")
    @classmethod
    def _validate_values(cls, value):
        ensure_non_negative_numeric_payload(value, label="flow.sinks_sources.etp.values")
        return value
