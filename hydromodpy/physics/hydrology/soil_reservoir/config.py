"""TOML surface of the soil reservoir.

``kernel.py`` and this module are written in parallel and stay independent:
this module declares what a project file can say, the kernel says what the
numbers do with it. The two meet in ``simulation/soil_recharge.py``, which
turns a :class:`SoilReservoirConfig` into the kernel's ``SoilParameters``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.core.units.types import DurationDays, LengthMillimeters


class SoilReservoirConfig(HydroModelBase):
    """Daily soil reservoir that turns precipitation and ETP into recharge.

    Read by the recharge binder of every run and of every calibration trial;
    MODFLOW 6 only. See ``physics/hydrology/soil_reservoir/kernel.py`` for the
    equations.
    """

    ru: Annotated[LengthMillimeters, Profile.USER] = Field(
        ...,
        description=(
            "Available water capacity of the soil (réserve utile), in mm of water: "
            "what the roots can draw between field capacity and wilting point. A bare "
            'number is in mm; "120 mm" and "12 cm" also read. Between 0 and 1000 mm. '
            "Required, since it belongs to the site. In doubt, start from 150 mm and "
            "compare the recharge the soil alone prints for 50 to 250 mm with the "
            "gauged discharge (hmp run <file> --until load_data). With "
            "[data.soil_capacity], it is the mean capacity of the SAFRAN cells, and "
            "the raster spreads it over classes inside each cell. Calibrate it with "
            "[calibration.parameters.ru]."
        ),
        json_schema_extra=field_metadata(calibrable=Calibrable(units="mm")),
    )
    alpha: Annotated[float, Profile.USER] = Field(
        default=0.6,
        description=(
            "Share of ru above which the soil evaporates at the full rate kc x ETP. "
            "Below alpha x ru, ETR falls linearly with the stored water. It is 1 - p "
            "of FAO-56 and LP of HBV. Above 0, at most 1. Kept fixed by default: the "
            "discharge alone hardly constrains it."
        ),
        json_schema_extra=field_metadata(calibrable=Calibrable(bounds=(0.3, 1.0), units="-")),
    )
    kc: Annotated[float, Profile.USER] = Field(
        default=1.0,
        description=(
            "Crop coefficient applied to the loaded ETP: the soil evaporates at most "
            "kc x ETP a day. 1.0 takes the ETP as loaded, a reference grass. Between "
            "0 and 2. Kept fixed by default: kc and ru move the same annual volume."
        ),
        json_schema_extra=field_metadata(calibrable=Calibrable(bounds=(0.7, 1.3), units="-")),
    )
    impervious_fraction: Annotated[float, Profile.USER] = Field(
        default=0.0,
        description=(
            "Share of the area that is sealed (roofs, roads). The rain that falls on "
            "it runs off at once, with no infiltration and no evaporation, and "
            "reaches the streams, the lakes and the gauged discharge. The soil "
            "reservoir covers the rest of the area. From 0 up to, not including, 1."
        ),
    )
    bypass_fraction: Annotated[float, Profile.USER] = Field(
        default=0.0,
        description=(
            "Share of the rain on the unsealed area that skips the soil through "
            "macropores and joins the recharge the same day, even when the soil is "
            "dry. From 0 up to, not including, 1. Keep it at 0 while K and Sy are "
            "calibrated: a bypass can rebuild the summer recharge the soil "
            "reservoir removes."
        ),
        json_schema_extra=field_metadata(calibrable=Calibrable(bounds=(0.0, 0.3), units="-")),
    )
    transit_time: Annotated[DurationDays, Profile.USER] = Field(
        default=0.0,
        description=(
            "Mean time the water leaving the soil takes to cross the unsaturated "
            "zone down to the water table, in days. A linear reservoir with this "
            "time constant delays and smooths the recharge; 0 sends it the same "
            'day. A bare number is in days; "5 days" also reads. At most 30 days: '
            "a longer delay would rebuild the slow groundwater memory MODFLOW "
            "computes itself."
        ),
        json_schema_extra=field_metadata(calibrable=Calibrable(bounds=(0.0, 30.0), units="day")),
    )
    spinup: Annotated[Literal["first_year", "none"], Profile.USER] = Field(
        default="first_year",
        description=(
            'State of the soil on the first day. "first_year" repeats the first '
            "365 days of the run until the storage at the end of that year moves by "
            "less than 0.1 mm, 20 times at most; the run must last one year at "
            'least. "none" starts from a full soil, the state of a soil in a wet '
            "winter."
        ),
        json_schema_extra={
            "value_docs": {
                "first_year": "Repeat the first year until the soil storage settles.",
                "none": "Start from a full soil and an empty transit store.",
            }
        },
    )

    @field_validator("ru")
    @classmethod
    def _ru_is_a_plausible_soil_capacity(cls, value: float) -> float:
        if not 0 <= value <= 1000:
            raise ValueError(
                f"ru = {value:g} mm is outside 0 to 1000 mm, the range of a soil water "
                'capacity: ru is in mm, so write ru = 120 or ru = "120 mm".'
            )
        return value

    @field_validator("alpha")
    @classmethod
    def _alpha_is_a_share_of_ru(cls, value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError(
                f"alpha = {value:g}: alpha is the share of ru above which the soil "
                "evaporates at the full rate kc x ETP, above 0 and at most 1. Write a "
                "value such as 0.6."
            )
        return value

    @field_validator("kc")
    @classmethod
    def _kc_scales_the_loaded_etp(cls, value: float) -> float:
        if not 0 <= value <= 2:
            raise ValueError(
                f"kc = {value:g}: kc scales the loaded ETP, between 0 and 2. Write "
                "1.0 to take the ETP as loaded."
            )
        return value

    @field_validator("impervious_fraction")
    @classmethod
    def _impervious_fraction_is_a_fraction(cls, value: float) -> float:
        if not 0 <= value < 1:
            raise ValueError(
                f"impervious_fraction = {value:g}: it is the sealed share of the area, "
                "a fraction from 0 up to, not including, 1: write 0.05 for 5 %, not 5, "
                "and 0.0 for a rural catchment."
            )
        return value

    @field_validator("bypass_fraction")
    @classmethod
    def _bypass_fraction_is_a_fraction(cls, value: float) -> float:
        if not 0 <= value < 1:
            raise ValueError(
                f"bypass_fraction = {value:g}: it is the share of the rain that skips "
                "the soil, a fraction from 0 up to, not including, 1: write 0.1 for "
                "10 %, not 10, and 0.0 unless the site shows preferential flow."
            )
        return value

    @field_validator("transit_time")
    @classmethod
    def _transit_time_stays_under_the_groundwater_memory(cls, value: float) -> float:
        if not 0 <= value <= 30:
            raise ValueError(
                f"transit_time = {value:g} days is outside 0 to 30 days: a longer "
                "delay would rebuild the slow groundwater memory MODFLOW computes "
                "itself. Write 0 to send the recharge the same day, or a few days."
            )
        return value

    @field_validator("spinup", mode="before")
    @classmethod
    def _spinup_is_one_of_two_starts(cls, value: object) -> object:
        if value not in ("first_year", "none"):
            raise ValueError(
                f'spinup = {value!r}: write "first_year" to repeat the first year '
                'of the run until the soil storage settles, or "none" to start from '
                "a full soil."
            )
        return value


def soil_reservoir_of(flow_config: object) -> SoilReservoirConfig | None:
    """Return the soil section a [flow] config declares, or None."""
    sinks_sources = getattr(flow_config, "sinks_sources", None)
    recharge = getattr(sinks_sources, "recharge", None)
    return getattr(recharge, "soil", None)


def steady_start_refusal(flow_config: object, window: ResolvedSimulationTimeWindow) -> str | None:
    """Say why a soil run must not open on a one-period steady state, or None."""
    if soil_reservoir_of(flow_config) is None:
        return None
    if getattr(flow_config, "flow_regime", None) != "transient":
        return None
    if not getattr(flow_config, "first_period_steady", False):
        return None
    return (
        "[flow.sinks_sources.recharge.soil] sends each day's recharge to MODFLOW, "
        "and flow.first_period_steady = true solves the first stress period "
        f"({window.step_value} {window.step_unit}) as a steady state under that "
        "period's recharge alone, zero after a dry day: the run would start from a "
        "drained aquifer. Write first_period_steady = false under [flow] and add "
        '[flow.ic] type = "steady_state", which starts the run from the steady '
        "state under the mean recharge of the whole run."
    )


def spinup_refusal(config: SoilReservoirConfig, run_days: int) -> str | None:
    """Say why the first year cannot be repeated, or None."""
    if config.spinup != "first_year" or run_days >= 365:
        return None
    return (
        'spinup = "first_year" repeats the first 365 days of the run, and '
        f'[simulation.time] covers {run_days} days: write spinup = "none" under '
        "[flow.sinks_sources.recharge.soil] to start from a full soil, or extend "
        "the run to one year at least."
    )


__all__ = [
    "SoilReservoirConfig",
    "soil_reservoir_of",
    "spinup_refusal",
    "steady_start_refusal",
]
