"""TOML surface of the soil reservoir.

``kernel.py`` and this module are written in parallel and stay independent:
this module declares what a project file can say, the kernel says what the
numbers do with it. The two meet in ``simulation/soil_recharge.py``, which
turns a :class:`SoilReservoirConfig` into the kernel's ``SoilParameters``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, ValidatorFunctionWrapHandler, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.core.units.types import DurationDays, LengthMillimeters


def _bare_number_string(value: object) -> str | None:
    """``value`` itself if it is a string that reads as a plain number, else None."""
    if not isinstance(value, str):
        return None
    try:
        float(value)
    except ValueError:
        return None
    return value


_RANGE_ERRORS = frozenset({"greater_than", "greater_than_equal", "less_than", "less_than_equal"})


def _within_range(
    value: object,
    handler: ValidatorFunctionWrapHandler,
    check: Callable[[Any], Any],
) -> Any:
    """Validate *value*, then let *check* word a range refusal.

    The bounds live on the field, so the reference shows them. A value outside
    them would get the generic Pydantic message; *check* repeats the bound with
    what the number means.
    """
    try:
        return check(handler(value))
    except ValidationError as exc:
        errors = exc.errors()
        if errors and all(error["type"] in _RANGE_ERRORS for error in errors):
            check(errors[0]["input"])
        raise


class SoilReservoirConfig(HydroModelBase):
    """Daily soil reservoir that turns precipitation and ETP into recharge.

    Read by the recharge binder of every run and of every calibration trial;
    MODFLOW 6 only. See ``physics/hydrology/soil_reservoir/kernel.py`` for the
    equations.
    """

    ru: Annotated[LengthMillimeters, Profile.USER] = Field(
        ...,
        ge=0.0,
        le=1000.0,
        description=(
            "Available water capacity of the soil, in mm of water: "
            "what the roots can draw between field capacity and wilting point. A bare "
            'number is in mm; "120 mm" and "12 cm" also read. Between 0 and 1000 mm. '
            "Required, since it belongs to the site. Start from a soil map, then "
            "compare the recharge the soil alone prints for 50 to 250 mm with the "
            "gauged discharge (hmp run <file> --until load_data). With "
            "[data.soil_capacity], it is the mean capacity over the catchment, and "
            "the raster spreads it over classes inside each cell. Calibrate it with "
            "[calibration.parameters.ru]."
        ),
        json_schema_extra=field_metadata(calibrable=Calibrable(units="mm")),
        examples=["150 mm"],
    )
    alpha: Annotated[float, Profile.USER] = Field(
        default=0.6,
        gt=0.0,
        le=1.0,
        description=(
            "Share of ru above which the soil evaporates at the full rate kc x ETP. "
            "Below alpha x ru, ETR falls linearly with the stored water. It is 1 - p "
            "of FAO-56 and LP of HBV. The default 0.6 is a choice: it means p = 0.40, "
            "under FAO-56 table 22 for pasture (0.60), cereals and maize (0.55). Above "
            "0, at most 1. Kept fixed by default: on the discharge alone it trades off "
            "with ru, since both move the annual volume."
        ),
        json_schema_extra=field_metadata(
            calibrable=Calibrable(bounds=(0.3, 1.0), units="-"), stability="experimental"
        ),
    )
    kc: Annotated[float, Profile.USER] = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description=(
            "Crop coefficient applied to the loaded ETP: the soil evaporates at most "
            "kc x ETP a day. 1.0 takes the ETP as loaded, and it is neutral only if "
            "the surface of that ETP looks like the site: check what the product "
            "refers to. Between 0 and 2. Kept fixed by default: kc and ru move the same "
            "annual volume."
        ),
        json_schema_extra=field_metadata(
            calibrable=Calibrable(bounds=(0.7, 1.3), units="-"), stability="experimental"
        ),
    )
    impervious_fraction: Annotated[float, Profile.USER] = Field(
        default=0.0,
        ge=0.0,
        lt=1.0,
        description=(
            "Share of the area that is sealed (roofs, roads). The rain that falls on "
            "it runs off at once, with no infiltration and no evaporation, and "
            "reaches the streams, the lakes and the gauged discharge. The soil "
            "reservoir covers the rest of the area. From 0 up to, not including, 1. "
            "Calibrate it with [calibration.parameters.impervious_fraction]; the "
            "range belongs to the site, so a file has to state it."
        ),
        json_schema_extra=field_metadata(
            calibrable=Calibrable(units="-"), stability="experimental"
        ),
    )
    bypass_fraction: Annotated[float, Profile.USER] = Field(
        default=0.0,
        ge=0.0,
        lt=1.0,
        description=(
            "Share of the rain on the unsealed area that skips the soil through "
            "macropores and joins the recharge the same day, even when the soil is "
            "dry. From 0 up to, not including, 1. Keep it at 0 while K and Sy are "
            "calibrated: a bypass can rebuild the summer recharge the soil "
            "reservoir removes."
        ),
        json_schema_extra=field_metadata(
            calibrable=Calibrable(bounds=(0.0, 0.3), units="-"), stability="experimental"
        ),
    )
    transit_time: Annotated[DurationDays, Profile.USER] = Field(
        default=0.0,
        ge=0.0,
        le=30.0,
        description=(
            "Mean time the water leaving the soil takes to cross the unsaturated "
            "zone down to the water table, in days. A linear reservoir with this "
            "time constant delays and smooths the recharge; 0 sends it the same "
            'day. A bare number is in days; "5 days" also reads. At most 30 days: '
            "a longer delay would rebuild the slow groundwater memory MODFLOW "
            "computes itself."
        ),
        json_schema_extra=field_metadata(
            calibrable=Calibrable(bounds=(0.0, 30.0), units="day"), stability="experimental"
        ),
    )
    curve_number: Annotated[float | None, Profile.USER] = Field(
        default=None,
        ge=30.0,
        le=98.0,
        description=(
            "SCS curve number (AMC II), dimensionless, of a HELP-style surface runoff "
            "(Schroeder et al. 1994): the unsealed share of the rain above a daily "
            "retention loses some to a fast runoff, more as the soil is wetter. None "
            "turns the term off, bit for bit as before. Between 30 and 98. It reads the "
            "soil and never the water table, so it renders saturation runoff badly: "
            "leave it off where the drains already give that runoff. To calibrate it, "
            "state a range under [calibration.parameters.curve_number]: it belongs to "
            "the soil group and the land use of the site."
        ),
        json_schema_extra=field_metadata(
            calibrable=Calibrable(units="-"), stability="experimental"
        ),
    )
    runoff_time: Annotated[DurationDays, Profile.USER] = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description=(
            "Time constant of the linear reservoir that routes the curve-number "
            "runoff to the outlet, in days. No effect while curve_number is None. 0 "
            'sends it the same day; "2 days" also reads. Between 0 and 10 days: a '
            "longer delay would smooth away the fast surface peak the term exists "
            "for."
        ),
        json_schema_extra=field_metadata(
            calibrable=Calibrable(bounds=(0.0, 10.0), units="day"), stability="experimental"
        ),
    )
    runoff_lag: Annotated[DurationDays, Profile.USER] = Field(
        default=0.0,
        ge=0.0,
        le=5.0,
        description=(
            "Pure delay applied to the routed curve-number runoff, after runoff_time, "
            "before it reaches the gauged discharge: the travel time to the outlet plus "
            "any lag between the forcing's daily step and the gauge's. No effect while "
            "curve_number is None. 0 adds no delay, "
            'bit for bit as before; "0.75 days" also reads, interpolated linearly '
            "between the neighbouring whole-day shifts. Between 0 and 5 days: a longer "
            "shift belongs to runoff_time's reservoir, not to a fixed travel time. "
            "Calibrate it with [calibration.parameters.runoff_lag]."
        ),
        json_schema_extra=field_metadata(
            calibrable=Calibrable(bounds=(0.0, 5.0), units="day"), stability="experimental"
        ),
    )
    spinup: Annotated[Literal["first_year", "none"], Profile.USER] = Field(
        default="first_year",
        description=(
            'State of the soil on the first day. "first_year" repeats the first '
            "365 days of the run until the storage at the end of that year moves by "
            "less than 0.1 mm, 20 times at most; the run must last 364 days "
            '(52 weeks) at least, and a 364-day run repeats those 364 days. "none" starts from a full soil, the state of a soil in a wet '
            "winter."
        ),
        json_schema_extra=field_metadata(
            value_docs={
                "first_year": "Repeat the first year until the soil storage settles.",
                "none": "Start from a full soil and an empty transit store.",
            },
            stability="experimental",
        ),
    )

    @field_validator("ru", mode="before")
    @classmethod
    def _ru_string_states_its_unit(cls, value: object) -> object:
        bare = _bare_number_string(value)
        if bare is None:
            return value
        raise ValueError(
            f'ru = "{bare}" has no unit: write ru = {bare} (a bare number is in mm) '
            f'or ru = "{bare} mm".'
        )

    @field_validator("ru", mode="wrap")
    @classmethod
    def _ru_in_range(cls, value: object, handler: ValidatorFunctionWrapHandler) -> float:
        return _within_range(value, handler, cls._ru_is_a_plausible_soil_capacity)

    @staticmethod
    def _ru_is_a_plausible_soil_capacity(value: float) -> float:
        if not 0 <= value <= 1000:
            raise ValueError(
                f"ru = {value:g} mm is outside 0 to 1000 mm, the range of a soil water "
                'capacity: ru is in mm, so write ru = 120 or ru = "120 mm".'
            )
        return value

    @field_validator("alpha", mode="wrap")
    @classmethod
    def _alpha_in_range(cls, value: object, handler: ValidatorFunctionWrapHandler) -> float:
        return _within_range(value, handler, cls._alpha_is_a_share_of_ru)

    @staticmethod
    def _alpha_is_a_share_of_ru(value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError(
                f"alpha = {value:g}: alpha is the share of ru above which the soil "
                "evaporates at the full rate kc x ETP, above 0 and at most 1. Write a "
                "value such as 0.6."
            )
        return value

    @field_validator("kc", mode="wrap")
    @classmethod
    def _kc_in_range(cls, value: object, handler: ValidatorFunctionWrapHandler) -> float:
        return _within_range(value, handler, cls._kc_scales_the_loaded_etp)

    @staticmethod
    def _kc_scales_the_loaded_etp(value: float) -> float:
        if not 0 <= value <= 2:
            raise ValueError(
                f"kc = {value:g}: kc scales the loaded ETP, between 0 and 2. Write "
                "1.0 to take the ETP as loaded."
            )
        return value

    @field_validator("impervious_fraction", mode="wrap")
    @classmethod
    def _impervious_fraction_in_range(
        cls, value: object, handler: ValidatorFunctionWrapHandler
    ) -> float:
        return _within_range(value, handler, cls._impervious_fraction_is_a_fraction)

    @staticmethod
    def _impervious_fraction_is_a_fraction(value: float) -> float:
        if not 0 <= value < 1:
            raise ValueError(
                f"impervious_fraction = {value:g}: it is the sealed share of the area, "
                "a fraction from 0 up to, not including, 1: write 0.05 for 5 %, not 5, "
                "and 0.0 for a rural catchment."
            )
        return value

    @field_validator("bypass_fraction", mode="wrap")
    @classmethod
    def _bypass_fraction_in_range(
        cls, value: object, handler: ValidatorFunctionWrapHandler
    ) -> float:
        return _within_range(value, handler, cls._bypass_fraction_is_a_fraction)

    @staticmethod
    def _bypass_fraction_is_a_fraction(value: float) -> float:
        if not 0 <= value < 1:
            raise ValueError(
                f"bypass_fraction = {value:g}: it is the share of the rain that skips "
                "the soil, a fraction from 0 up to, not including, 1: write 0.1 for "
                "10 %, not 10, and 0.0 unless the site shows preferential flow."
            )
        return value

    @field_validator("curve_number", mode="wrap")
    @classmethod
    def _curve_number_in_range(
        cls, value: object, handler: ValidatorFunctionWrapHandler
    ) -> float | None:
        return _within_range(value, handler, cls._curve_number_is_a_plausible_cn)

    @staticmethod
    def _curve_number_is_a_plausible_cn(value: float | None) -> float | None:
        if value is None:
            return None
        if not 30 <= value <= 98:
            raise ValueError(
                f"curve_number = {value:g}: a SCS curve number (AMC II) is between "
                "30 and 98 (NEH-630 ch. 9, pp. 9-1 and 9-3). Write a value in that "
                "range, or remove the field to keep the term off."
            )
        return value

    @field_validator("runoff_time", mode="before")
    @classmethod
    def _runoff_time_string_states_its_unit(cls, value: object) -> object:
        bare = _bare_number_string(value)
        if bare is None:
            return value
        raise ValueError(
            f'runoff_time = "{bare}" has no unit: write runoff_time = {bare} (a bare '
            f'number is in days) or runoff_time = "{bare} days".'
        )

    @field_validator("runoff_time", mode="wrap")
    @classmethod
    def _runoff_time_in_range(cls, value: object, handler: ValidatorFunctionWrapHandler) -> float:
        return _within_range(value, handler, cls._runoff_time_is_a_short_delay)

    @staticmethod
    def _runoff_time_is_a_short_delay(value: float) -> float:
        if not 0 <= value <= 10:
            raise ValueError(
                f"runoff_time = {value:g} days is outside 0 to 10 days: it routes a "
                "fast surface runoff, not groundwater. Write 0 to send it the same "
                "day, or a few days."
            )
        return value

    @field_validator("runoff_lag", mode="before")
    @classmethod
    def _runoff_lag_string_states_its_unit(cls, value: object) -> object:
        bare = _bare_number_string(value)
        if bare is None:
            return value
        raise ValueError(
            f'runoff_lag = "{bare}" has no unit: write runoff_lag = {bare} (a bare '
            f'number is in days) or runoff_lag = "{bare} days".'
        )

    @field_validator("runoff_lag", mode="wrap")
    @classmethod
    def _runoff_lag_in_range(cls, value: object, handler: ValidatorFunctionWrapHandler) -> float:
        return _within_range(value, handler, cls._runoff_lag_is_a_short_travel_time)

    @staticmethod
    def _runoff_lag_is_a_short_travel_time(value: float) -> float:
        if not 0 <= value <= 5:
            raise ValueError(
                f"runoff_lag = {value:g} days is outside 0 to 5 days: it is a fixed "
                "travel time to the outlet, not the runoff_time reservoir. Write 0 to "
                "add no delay, or a fraction of a day."
            )
        return value

    @field_validator("transit_time", mode="before")
    @classmethod
    def _transit_time_string_states_its_unit(cls, value: object) -> object:
        bare = _bare_number_string(value)
        if bare is None:
            return value
        raise ValueError(
            f'transit_time = "{bare}" has no unit: write transit_time = {bare} (a bare '
            f'number is in days) or transit_time = "{bare} days".'
        )

    @field_validator("transit_time", mode="wrap")
    @classmethod
    def _transit_time_in_range(cls, value: object, handler: ValidatorFunctionWrapHandler) -> float:
        return _within_range(value, handler, cls._transit_time_stays_under_the_groundwater_memory)

    @staticmethod
    def _transit_time_stays_under_the_groundwater_memory(value: float) -> float:
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
        '[flow.ic] kind = "steady_state", which starts the run from the steady '
        "state under the mean recharge of the whole run."
    )


# Shortest run whose first days can stand for a year in the spin-up.
# 52 weekly stress periods cover 364 days. The spin-up then repeats that
# 364-day cycle, one day short of a calendar year.
SPINUP_MIN_RUN_DAYS = 52 * 7


def spinup_refusal(config: SoilReservoirConfig, run_days: int) -> str | None:
    """Say why the first year cannot be repeated, or None."""
    if config.spinup != "first_year" or run_days >= SPINUP_MIN_RUN_DAYS:
        return None
    return (
        'spinup = "first_year" repeats the first 52 weeks (364 days) of the run, and '
        f'[simulation.time] covers {run_days} days: write spinup = "none" under '
        "[flow.sinks_sources.recharge.soil] to start from a full soil, or extend "
        "the run to 52 weeks at least."
    )


__all__ = [
    "SPINUP_MIN_RUN_DAYS",
    "SoilReservoirConfig",
    "soil_reservoir_of",
    "spinup_refusal",
    "steady_start_refusal",
]
