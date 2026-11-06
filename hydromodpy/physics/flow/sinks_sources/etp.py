"""Diffuse evapotranspiration payload for the flow process."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, PrivateAttr, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units import Length, LengthMeters
from hydromodpy.physics.forcing.steady_periods import normalize_first_clim
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

    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Whether the model takes this evapotranspiration. Declaring it is what activates it. false keeps the table "
            "and builds nothing from it."
        ),
    )
    values: Annotated[Any, Profile.USER] = Field(
        default=0.0,
        description=(
            "Evapotranspiration rate, in the unit that units names (mm/day by default): "
            "one number, one number per stress period, a table {period: value}, or the "
            "series loaded from [data.etp]. Values must not be negative: the EVT package "
            "takes them as outflow rates."
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
            "per-period rates, each weighted by its length; 'first' is the rate of "
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
            "Distance (m) the EVT surface sits below its reference. The rule has two "
            "cases. In soil mode under MODFLOW 6 the reference is the drain elevation of "
            "the cell (the top, or the top minus half of solver.drain_band_depth_m), and "
            "with the key unset the distance is 0 m, since the soil reservoir has already "
            "taken the ETP it could. In every other case the reference is the topographic "
            "surface, as MODFLOW-NWT reads it, and with the key unset the distance is "
            "2 m, also when this table is absent and the ETP comes from [data.etp] alone. "
            "A value written here wins in both cases. The run writes the value it used "
            "in config.resolved.toml, table resolved_at_build."
        ),
        json_schema_extra=field_metadata(unit="m"),
    )
    extinction_depth: Annotated[LengthMeters, Profile.USER] = Field(
        default=2.0,
        gt=0.0,
        description=(
            "Depth (m) below the EVT surface where the water table stops "
            "evaporating; the rate falls linearly between the surface and this "
            "depth. 2 m by default, a choice: this depth often reaches the deepest "
            "roots, and 150 mm of soil capacity means about 1 to 2 m of them. Read by "
            "MODFLOW-NWT, and by MODFLOW 6 in soil mode for the ETP the soil left "
            "unmet. Calibrate it with "
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
            "How gridded or station data reach the cells of the solver mesh: "
            "'nearest' (source value at the cell centre), 'linear', 'idw' "
            "(inverse distance), or 'area' (gridded data only: each pixel "
            "weighted by the area it shares with the cell, so the volume over "
            "the domain equals the integral of the grid)."
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
