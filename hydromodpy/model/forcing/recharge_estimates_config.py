"""TOML surface of ``[recharge_estimates]``, the recharge compared with the run.

The section asks for a range of recharge on the catchment, computed from the
loaded weather, gauge and piezometers before the solver runs. Nothing it gives
enters the model. ``recharge_estimates.py`` holds the formulas.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.model.forcing.recharge_estimates import ESTIMATORS


class ChapmanMaxwellConfig(HydroModelBase):
    """Parameter of the Chapman and Maxwell filter; unset, it comes from the gauge."""

    k: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        lt=1.0,
        description=(
            "Daily recession constant, between 0 and 1. Unset, it is read on the "
            "recessions of the gauge."
        ),
        json_schema_extra=field_metadata(unit="-"),
    )


class EckhardtConfig(ChapmanMaxwellConfig):
    """Parameters of the Eckhardt filter; unset, they come from the gauge."""

    bfi_max: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        lt=1.0,
        description=(
            "Largest share of baseflow in the discharge, Eckhardt filter only. Unset, "
            "the largest yearly baseflow index of the Wallingford method, as ESPERE does. "
            "Eckhardt (2005) gives 0.80 for perennial streams on porous aquifers and "
            "0.25 on hard rock."
        ),
        json_schema_extra=field_metadata(unit="-"),
    )


class WtfConfig(HydroModelBase):
    """Water table fluctuation on each loaded piezometer."""

    specific_yield: Annotated[float, Profile.USER] = Field(
        ...,
        gt=0.0,
        le=0.5,
        description=(
            "Specific yield Sy at the piezometers. The estimate is proportional to it, "
            "so give the value the run uses or the calibrated one."
        ),
        json_schema_extra=field_metadata(unit="-"),
    )
    correction: Annotated[Literal["recession", "none"], Profile.USER] = Field(
        default="recession",
        description=(
            '"recession" adds the decline the water table would have made without the '
            'rain; "none" sums the rises alone (RISE).'
        ),
    )


class RechargeEstimatesConfig(HydroModelBase):
    """Recharge estimated from the loaded data, to compare with the run's own.

    Each method reads its data families, which the run then loads: precipitation
    and temperature for the yearly formulas, [data.hydrometry] at the outlet for
    the baseflow filters and the closing factor, [data.piezometry] for WTF. The
    run prints one block of yearly values and writes the table
    ``recharge_estimates``; the run's recharge sits beside them.
    """

    methods: Annotated[list[str] | Literal["all"], Profile.USER] = Field(
        default="all",
        description=(
            'Methods to run, or "all". "all" skips wtf when no specific yield is given. '
            "Weather: turc (an effective rainfall), guttman_zuckerman, kessler. Gauge: "
            "wallingford, chapman_maxwell, eckhardt, closing_factor. Piezometer: wtf."
        ),
        json_schema_extra=field_metadata(
            value_docs={name: method.reference for name, method in ESTIMATORS.items()}
        ),
        examples=["all", ["turc", "eckhardt"]],
    )
    chapman_maxwell: Annotated[ChapmanMaxwellConfig, Profile.USER] = Field(
        default_factory=ChapmanMaxwellConfig,
        description="Parameter of the Chapman and Maxwell filter.",
    )
    eckhardt: Annotated[EckhardtConfig, Profile.USER] = Field(
        default_factory=EckhardtConfig,
        description="Parameters of the Eckhardt filter.",
    )
    wtf: Annotated[WtfConfig | None, Profile.USER] = Field(
        default=None,
        description="Water table fluctuation; required when methods names wtf.",
    )

    @field_validator("methods")
    @classmethod
    def _methods_are_known(cls, methods: list[str] | str) -> list[str] | str:
        if methods == "all":
            return methods
        unknown = [name for name in methods if name not in ESTIMATORS]
        if unknown or not methods:
            names = ", ".join(ESTIMATORS)
            raise ValueError(f'methods = {methods}: write a list taken from {names}, or "all".')
        return list(dict.fromkeys(methods))

    @model_validator(mode="after")
    def _wtf_has_its_specific_yield(self) -> RechargeEstimatesConfig:
        if isinstance(self.methods, list) and "wtf" in self.methods and self.wtf is None:
            raise ValueError(
                "methods names wtf, and the water table fluctuation needs the specific "
                "yield: add [recharge_estimates.wtf] with specific_yield = 0.05, for instance."
            )
        return self

    def selected(self) -> tuple[str, ...]:
        """The methods to run, in the order of the table of estimators."""
        if self.methods == "all":
            return tuple(n for n in ESTIMATORS if n != "wtf" or self.wtf is not None)
        return tuple(n for n in ESTIMATORS if n in self.methods)

    def families(self) -> tuple[str, ...]:
        """The data families the selected methods read."""
        return tuple(
            dict.fromkeys(family for name in self.selected() for family in ESTIMATORS[name].reads)
        )


__all__ = ["ChapmanMaxwellConfig", "EckhardtConfig", "RechargeEstimatesConfig", "WtfConfig"]
