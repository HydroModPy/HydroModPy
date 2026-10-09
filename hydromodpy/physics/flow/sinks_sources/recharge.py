"""Diffuse recharge payload for the flow process."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.physics.flow.sinks_sources._units import normalize_first_clim
from hydromodpy.physics.forcing.types import InterpolationMethod, SpatialMode
from hydromodpy.physics.forcing.validation import (
    ensure_finite_numeric_payload,
    ensure_non_negative_numeric_payload,
)
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig


class FlowRechargeConfig(HydroModelBase):
    """
    Typed payload for diffuse recharge over the model domain.

    Recharge drives the MODFLOW RCH package. The conversion to MODFLOW
    stress-period dictionaries is handled by
    ``FlowToModflowAdapter._build_recharge_payload``. Negative values can be
    routed to EVT when ``negative_to_evt`` is enabled.

    Attributes
    ----------
    values :
        Recharge payload. Accepted forms:

        - **scalar** ``float``: uniform rate applied to every stress period,
        - **list / numpy array**: one value per stress period
          (length must match ``nper``),
        - **mapping** ``{period_index: value}``: explicit per-period assignment,
        - **runtime series** (pandas-like object with ``.iloc``): used when
          recharge is computed dynamically (e.g. from PyHELP output).

    first_clim : str | float
        Rate of every steady stress period, taken from the rates of all the
        periods (``hydromodpy.physics.forcing.steady_periods``). A transient
        period keeps its own rate. Options:

        - ``"mean"``: mean of the per-period rates, one weight per period
          (default),
        - ``"first"``: rate of period 0,
        - *numeric*: that rate.

    units : str
        Physical units of ``values``. The flow runtime converts the payload
        to SI ``m/s`` when the process is built.
    """

    values: Annotated[Any, Profile.USER] = Field(
        default=0.0,
        description=(
            "Recharge rate: one number, one number per stress period, a table "
            "{period: value}, or the series loaded from [data.recharge], in the unit that "
            "'units' names (mm/day by default). A calibration reads its bounds "
            "in that unit too. The "
            "'matching_hydrographic_network' protocol calibrates conductivity "
            "against the ratio K/R in its steady stage and requires this value "
            "held frozen there."
        ),
        # No unit on the Calibrable: the search writes its sample as is into
        # this field, so the unit is the one 'units' declares, whatever it is.
        json_schema_extra=field_metadata(calibrable=Calibrable(), unit="mm/day"),
    )
    soil: Annotated[SoilReservoirConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Soil reservoir that computes the recharge from the daily precipitation "
            "and ETP loaded under [data.precipitation] and [data.etp], MODFLOW 6 "
            "only. It replaces [data.recharge]. Check it alone with "
            "`hmp run <file> --until load_data`, which prints its water budget in "
            "mm/year and writes no run."
        ),
    )
    heterogeneous_source: Annotated[Any, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional raw data source for heterogeneous (2D per-cell) recharge. "
            "When set, the solver adapter discretizes FieldRecords onto the "
            "MODFLOW grid instead of using the scalar 'values' field. "
            "Expected: LoadResult with FieldRecords."
        ),
    )
    first_clim: Annotated[str | float, Profile.DEV] = Field(
        default="mean",
        description=(
            "Recharge rate of every steady stress period: every period of a steady "
            "run, and the first period of a transient run when "
            "flow.first_period_steady is true. 'mean' is the mean of the "
            "per-period rates, one weight per period; 'first' is the rate of "
            "period 0; a number is that rate, in the units of values. A transient "
            "period keeps its own rate. The same rule holds for one value per "
            "period and for one grid per period, under every solver. With "
            "negative_to_evt, the steady period takes the rule on the recharge "
            "part and on the deficit part, so its net rate is the one stated here."
        ),
        examples=["mean", "first", 2.0],
    )
    units: Annotated[str, Profile.USER] = Field(
        default="mm/day",
        description=(
            "Unit of 'values' and of the recharge data source. Data-manager "
            "outputs use mm/day by convention; set it when you write 'values' "
            "in another unit. The run converts the rate to m/s."
        ),
        examples=["mm/day", "m/day", "m/s"],
    )
    negative_to_evt: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description=(
            "When true, negative recharge values are routed to the solver EVT "
            "package and RCH receives the non-negative clipped recharge."
        ),
    )
    spatial_mode: Annotated[SpatialMode, Profile.DEV] = Field(
        default="auto",
        description=(
            "How to interpret spatial data: 'auto' (points->homogeneous, "
            "fields->heterogeneous), 'homogeneous' (force spatial averaging), "
            "'heterogeneous' (force per-cell discretization, including "
            "point-to-grid interpolation when stations have coordinates)."
        ),
    )
    interpolation_method: Annotated[InterpolationMethod, Profile.DEV] = Field(
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

    @field_validator("values", mode="before")
    @classmethod
    def _validate_values(cls, value):
        ensure_finite_numeric_payload(value, label="flow.sinks_sources.recharge.values")
        return value

    @model_validator(mode="after")
    def _validate_negative_policy(self):
        if not self.negative_to_evt:
            ensure_non_negative_numeric_payload(
                self.values,
                label="flow.sinks_sources.recharge.values",
            )
            if isinstance(self.first_clim, float) and self.first_clim < 0.0:
                raise ValueError(
                    f"flow.sinks_sources.recharge.first_clim = {self.first_clim} is a "
                    "negative rate, and negative_to_evt is false: a steady period "
                    "cannot take it. Set negative_to_evt = true to route it to EVT, "
                    "or give a rate of zero or more."
                )
        return self

    @model_validator(mode="after")
    def _refuse_a_recharge_rate_beside_a_soil_reservoir(self):
        if self.soil is not None and "values" in self.model_fields_set:
            raise ValueError(
                f"flow.sinks_sources.recharge.values = {self.values!r} is ignored "
                "when [flow.sinks_sources.recharge.soil] computes the recharge: "
                "remove values, or remove the soil section to impose this rate."
            )
        return self
