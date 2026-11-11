"""Diffuse recharge payload for the flow process."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

import numpy as np
from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units.quantities import factor_to_m_per_s
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.forcing.steady_periods import normalize_first_clim
from hydromodpy.model.forcing.types import InterpolationMethod, SpatialMode
from hydromodpy.model.forcing.validation import (
    ensure_finite_numeric_payload,
    ensure_non_negative_numeric_payload,
    integer_period_keys,
    numeric_payload_array,
)


class FlowRechargeConfig(HydroModelBase):
    """
    Typed payload for diffuse recharge over the model domain.

    Recharge drives RCHA under MODFLOW 6, RCH under MODFLOW-NWT and the recharge
    term of the residual under Boussinesq. Each solver builds its own
    stress-period data from this payload. Negative values can be routed to EVT
    when ``negative_to_evt`` is enabled, under the two MODFLOW solvers only.

    Attributes
    ----------
    values :
        Recharge payload. Accepted forms:

        - **scalar** ``float``: uniform rate applied to every stress period,
        - **list / numpy array**: one value per stress period
          (length must match ``nper``),
        - **mapping** ``{period_index: value}``: one value for every stress
          period, the keys counted from 0,
        - **runtime series** (pandas-like object with ``.iloc``): used when
          recharge is computed dynamically (e.g. from PyHELP output).

    first_clim : str | float
        Rate of every steady stress period, taken from the rates of all the
        periods (``hydromodpy.model.forcing.steady_periods``). A transient
        period keeps its own rate. Options:

        - ``"mean"``: time mean of the per-period rates, each weighted by its length
          (default),
        - ``"first"``: rate of period 0,
        - *numeric*: that rate.

    units : str
        Physical units of ``values``. The flow runtime converts the payload
        to SI ``m/s`` when the process is built.
    """

    enabled: Annotated[bool, Profile.USER] = Field(
        default=True,
        description=(
            "Whether the model receives this recharge. Declaring it is what activates it. false keeps the table "
            "and builds nothing from it."
        ),
    )
    values: Annotated[Any, Profile.USER] = Field(
        default=0.0,
        description=(
            "Recharge rate: one number, one number per stress period, or a table "
            "{period: value} that states every period, in the unit that 'units' names "
            "(mm/day by default). It is positive when water enters the aquifer; a negative "
            "rate leaves it, through the EVT package when negative_to_evt holds. A "
            "calibration reads its bounds in that unit too. "
            "Do not write it beside [data.recharge] or the soil section, which "
            "replace it."
        ),
        # No unit on the Calibrable: the search writes its sample as is into
        # this field, so the unit is the one 'units' declares, whatever it is.
        json_schema_extra=field_metadata(calibrable=Calibrable(), unit="mm/day"),
    )
    factor: Annotated[float, Profile.USER] = Field(
        default=1.0,
        gt=0.0,
        description=(
            "Number that multiplies the recharge in force, from 'values' or from [data.recharge], "
            "a deficit and a numeric first_clim included. 1 changes nothing. Do not write it "
            "beside the soil section, whose recharge is an output."
        ),
        json_schema_extra=field_metadata(
            calibrable=Calibrable(
                bounds=(0.5, 2.0), search_space="log", sampling="log_uniform", units="-"
            )
        ),
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
            "per-period rates, each weighted by its length; 'first' is the rate of "
            "period 0; a number is that rate, in the units of values. A transient "
            "period keeps its own rate. The same rule holds for one value per "
            "period and for one grid per period, under every solver. With "
            "negative_to_evt, the steady period takes the rule on the recharge "
            "part and on the deficit part, so its net rate is the one stated here. "
            "Boussinesq has no EVT and refuses a negative number."
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
            "package and RCH receives the non-negative clipped recharge. Boussinesq "
            "has no EVT and refuses a negative rate whatever this says."
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
            "How gridded or station data reach the cells of the solver mesh: "
            "'nearest' (source value at the cell centre), 'linear', 'idw' "
            "(inverse distance), or 'area' (gridded data only: each pixel "
            "weighted by the area it shares with the cell, so the volume over "
            "the domain equals the integral of the grid)."
        ),
    )

    def peak_rate_mm_day(self) -> float:
        """Return the largest rate ``values`` states, whatever its sign, in mm/day."""
        payload = self.values
        if isinstance(payload, Mapping):
            payload = list(payload.values())
        array = numeric_payload_array(payload, label="flow.sinks_sources.recharge.values")
        peak = float(np.max(np.abs(array))) * self.factor
        return peak * (factor_to_m_per_s(self.units) / factor_to_m_per_s("mm/day"))

    @field_validator("first_clim", mode="before")
    @classmethod
    def _validate_first_clim(cls, value):
        return normalize_first_clim(value)

    @field_validator("values", mode="before")
    @classmethod
    def _validate_values(cls, value):
        label = "flow.sinks_sources.recharge.values"
        ensure_finite_numeric_payload(value, label=label)
        return integer_period_keys(value, label=label) if isinstance(value, Mapping) else value

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
        if self.soil is not None and self.factor != 1.0:
            raise ValueError(
                f"flow.sinks_sources.recharge.factor = {self.factor!r} has no rate to multiply "
                "beside [flow.sinks_sources.recharge.soil]: remove one of them."
            )
        return self


def recharge_factor_of(flow_config: object) -> float:
    """Return the factor a [flow] config declares on its recharge, 1 when it declares none."""
    sinks_sources = getattr(flow_config, "sinks_sources", None)
    return float(getattr(getattr(sinks_sources, "recharge", None), "factor", 1.0))
