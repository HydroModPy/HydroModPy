"""Diffuse recharge payload for the flow process."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.physics.flow.sinks_sources._units import normalize_first_clim


class FlowRechargeConfig(HydroModelBase):
    """
    Typed payload for diffuse recharge over the model domain.

    Recharge drives the MODFLOW RCH package. The conversion to MODFLOW
    stress-period dictionaries is handled by
    ``FlowToModflowAdapter._build_recharge_payload``. Negative values are
    rejected: evapotranspiration is configured separately through
    :class:`FlowEtpConfig` (one unique EVT entry point).

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
        Policy for stress-period 0 when ``values`` is a sequence.
        MODFLOW steady-state warm-up periods often need a representative rate
        that differs from the first raw time step. Options:

        - ``"mean"``: arithmetic mean of the entire series (default),
        - ``"first"``: first value of the series,
        - *numeric*: explicit scalar.

    units : str
        Physical units of ``values``. The flow runtime converts the payload
        to SI ``m/s`` when the process is built.
    """

    model_config = ConfigDict(extra="forbid")

    values: Annotated[Any, Profile.USER] = Field(
        default=0.0,
        description=(
            "Recharge payload: scalar, list (one per stress period), "
            "mapping {kper: value}, or runtime series."
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
            "Period-0 policy when values is a sequence: "
            "'mean' (series average), 'first' (first element), or a numeric scalar."
        ),
    )
    units: Annotated[str, Profile.DEV] = Field(
        default="mm/day",
        description=(
            "Units of the recharge data source. Data-manager outputs use "
            "mm/day by convention; override when providing values in another "
            "unit (e.g. 'm/day'). Converted to m/s at runtime via "
            "factor_to_m_per_s()."
        ),
    )
    spatial_mode: Annotated[Literal["auto", "homogeneous", "heterogeneous"], Profile.DEV] = Field(
        default="auto",
        description=(
            "How to interpret spatial data: 'auto' (points->homogeneous, "
            "fields->heterogeneous), 'homogeneous' (force spatial averaging), "
            "'heterogeneous' (force per-cell discretization, including "
            "point-to-grid interpolation when stations have coordinates)."
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
