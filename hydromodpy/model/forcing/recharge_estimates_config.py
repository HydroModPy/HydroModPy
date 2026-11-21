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
from hydromodpy.model.forcing.recharge_estimators import ESTIMATORS
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.soil.laws import SOIL_METHODS


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
    soil_methods: Annotated[list[str] | Literal["all"], Profile.USER] = Field(
        default_factory=list,
        description=(
            'Soil laws to run on the same weather and the same ru, or "all". Each gives a '
            "daily recharge and runoff, written as monthly rows and as yearly recharge, to "
            "set beside the run's own and beside a loaded product. The laws read the soil "
            "section of the run, else [recharge_estimates.soil]. One ru is not one soil: "
            "the ru that closes the budget differs from law to law."
        ),
        json_schema_extra=field_metadata(
            value_docs={name: method.reference for name, method in SOIL_METHODS.items()},
            stability="experimental",
        ),
        examples=["all", ["fao56", "dingman"]],
    )
    soil: Annotated[SoilReservoirConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "The soil the laws of soil_methods run with, when the run has no "
            "[flow.sinks_sources.recharge.soil] of its own, such as a run forced by SIM2. "
            "Its method is replaced by each law in turn. The run then loads "
            "[data.precipitation] and [data.etp], and never reads this soil."
        ),
        json_schema_extra=field_metadata(stability="experimental"),
    )
    compare_loaded: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "In a run whose soil section computes the recharge, load [data.recharge] and "
            "[data.runoff] for the comparison only, such as SIM2 DRAINC and RUNC: they are "
            "written beside the soil laws and never reach the model. List recharge, and "
            "runoff if it has one, in data.types."
        ),
        json_schema_extra=field_metadata(stability="experimental"),
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

    @field_validator("soil_methods")
    @classmethod
    def _soil_methods_are_known(cls, laws: list[str] | str) -> list[str] | str:
        if laws == "all":
            return laws
        unknown = [name for name in laws if name not in SOIL_METHODS]
        if unknown:
            names = ", ".join(SOIL_METHODS)
            raise ValueError(f'soil_methods = {laws}: write a list taken from {names}, or "all".')
        return list(dict.fromkeys(laws))

    @model_validator(mode="after")
    def _a_soil_only_for_its_laws(self) -> RechargeEstimatesConfig:
        if self.soil is not None and not self.laws():
            raise ValueError(
                '[recharge_estimates.soil] is read by soil_methods only: write soil_methods = "all", '
                "or remove the soil table."
            )
        if self.soil is not None and "method" in self.soil.model_fields_set:
            raise ValueError(
                f"[recharge_estimates.soil] method = {self.soil.method!r} is replaced by each law "
                "of soil_methods in turn: remove it."
            )
        return self

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

    def laws(self) -> tuple[str, ...]:
        """The soil laws to compare, in the order of the table of soil methods."""
        if self.soil_methods == "all":
            return tuple(SOIL_METHODS)
        return tuple(name for name in SOIL_METHODS if name in self.soil_methods)

    def signals(self) -> bool:
        """Whether the monthly recharge and runoff of each method are written."""
        return bool(self.laws()) or self.compare_loaded

    def families(self) -> tuple[str, ...]:
        """The data families the selected methods read."""
        families = [family for name in self.selected() for family in ESTIMATORS[name].reads]
        if self.soil is not None:
            families += ["precipitation", "etp"]
            if self.soil.snow is not None:
                families.append("temperature")
        return tuple(dict.fromkeys(families))


__all__ = ["ChapmanMaxwellConfig", "EckhardtConfig", "RechargeEstimatesConfig", "WtfConfig"]
