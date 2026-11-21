"""TOML surface of the soil reservoir.

This module declares what a project file can say, and ``model/soil`` says what
the numbers do with it. The only name this module reads there is the table of
methods, ``SOIL_METHODS``, so a method is named in one place. The two meet in
``soil_forcing.py``, which turns a :class:`SoilReservoirConfig` into the
kernel's ``SoilParameters``.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Annotated, Any, Literal

from annotated_types import Ge, Le
from pydantic import (
    Field,
    ValidationError,
    ValidationInfo,
    ValidatorFunctionWrapHandler,
    field_validator,
    model_validator,
)

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.core.units.types import DurationDays, LengthMillimeters
from hydromodpy.model.soil.laws import SOIL_METHODS


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


_BARE_NUMBER_UNITS: dict[str, str] = {
    "ru": "mm",
    "runoff_time": "days",
    "runoff_lag": "days",
    "transit_time": "days",
}
"""The unit a bare number of each field is read in, named when a string has none."""

_RANGE_RULES: dict[str, tuple[Callable[[float], bool], str]] = {
    "ru": (
        lambda v: 0 <= v <= 1000,
        "ru = {value:g} mm is outside 0 to 1000 mm, the range of a soil water "
        'capacity: ru is in mm, so write ru = 120 or ru = "120 mm".',
    ),
    "alpha": (
        lambda v: 0 < v <= 1,
        "alpha = {value:g}: alpha is the share of ru above which the soil "
        "evaporates at the full rate kc x ETP, above 0 and at most 1. Write a "
        "value such as 0.45.",
    ),
    "kc": (
        lambda v: 0 <= v <= 2,
        "kc = {value:g}: kc scales the loaded ETP, between 0 and 2. Write "
        "1.0 to take the ETP as loaded.",
    ),
    "impervious_fraction": (
        lambda v: 0 <= v < 1,
        "impervious_fraction = {value:g}: it is the sealed share of the area, "
        "a fraction from 0 up to, not including, 1: write 0.05 for 5 %, not 5, "
        "and 0.0 for a rural catchment.",
    ),
    "bypass_fraction": (
        lambda v: 0 <= v < 1,
        "bypass_fraction = {value:g}: it is the share of the rain that skips "
        "the soil, a fraction from 0 up to, not including, 1: write 0.1 for "
        "10 %, not 10, and 0.0 unless the site shows preferential flow.",
    ),
    "curve_number": (
        lambda v: 30 <= v <= 98,
        "curve_number = {value:g}: a SCS curve number (AMC II) is between "
        "30 and 98 (NEH-630 ch. 9, pp. 9-1 and 9-3). Write a value in that "
        "range, or remove the field to keep the term off.",
    ),
    "runoff_time": (
        lambda v: 0 <= v <= 10,
        "runoff_time = {value:g} days is outside 0 to 10 days: it routes a "
        "fast surface runoff, not groundwater. Write 0 to send it the same "
        "day, or a few days.",
    ),
    "runoff_lag": (
        lambda v: 0 <= v <= 5,
        "runoff_lag = {value:g} days is outside 0 to 5 days: it is a fixed "
        "travel time to the outlet, not the runoff_time reservoir. Write 0 to "
        "add no delay, or a fraction of a day.",
    ),
    "transit_time": (
        lambda v: 0 <= v <= 30,
        "transit_time = {value:g} days is outside 0 to 30 days: a longer "
        "delay would rebuild the slow groundwater memory MODFLOW computes "
        "itself. Write 0 to send the recharge the same day, or a few days.",
    ),
}
"""Each bounded field: the bound, and the refusal in the words of what the number means."""


def _check_range(name: str, value: object) -> object:
    """Refuse ``value`` of field ``name`` outside its bound, with its own message."""
    if value is None or isinstance(value, SeasonalKc):
        return value
    inside, message = _RANGE_RULES[name]
    if not inside(value):
        raise ValueError(message.format(value=value))
    return value


class SeasonalKc(HydroModelBase):
    """A crop coefficient that follows the growing season, as a trapezoid over the year.

    It is ``low`` before the planting month, rises linearly to ``high`` at the month
    of full cover, stays at ``high`` until senescence starts, then falls back to
    ``low`` at the harvest month. Each change happens on the first day of its month.
    This is the curve of ESPERE (BRGM RP-69538-FR), which accepts a winter crop too.
    """

    low: Annotated[float, Profile.USER] = Field(
        ...,
        ge=0.0,
        le=2.0,
        description="Crop coefficient outside the growing season, between 0 and 2.",
        json_schema_extra=field_metadata(unit="-"),
        examples=[0.6],
    )
    high: Annotated[float, Profile.USER] = Field(
        ...,
        ge=0.0,
        le=2.0,
        description="Crop coefficient at full cover, between 0 and 2.",
        json_schema_extra=field_metadata(unit="-"),
        examples=[1.15],
    )
    months: Annotated[tuple[int, int, int, int], Profile.USER] = Field(
        ...,
        description=(
            "Four months, 1 to 12, in the order of the season: planting, full cover, "
            "start of senescence, harvest. A winter crop wraps over the new year, "
            "for instance [10, 3, 6, 7]."
        ),
        examples=[[4, 6, 8, 10]],
    )

    @field_validator("months")
    @classmethod
    def _months_follow_the_season(cls, months: tuple[int, int, int, int]) -> tuple[int, ...]:
        if any(not 1 <= m <= 12 for m in months) or len(set(months)) != 4:
            raise ValueError(
                f"months = {list(months)}: write four different months between 1 and 12, "
                "planting, full cover, start of senescence and harvest."
            )
        drops = sum(months[i] > months[(i + 1) % 4] for i in range(4))
        if drops != 1:
            raise ValueError(
                f"months = {list(months)} do not follow one season: after planting come "
                "full cover, senescence and harvest, in calendar order, wrapping over "
                "the new year at most once."
            )
        return months


class SnowConfig(HydroModelBase):
    """Snow on the ground, melted linearly with the daily temperature.

    Its presence turns snow on and loads ``[data.temperature]``. A share of the
    precipitation falls as snow below ``melt_full`` and the pack melts as the
    temperature rises from ``melt_start`` to ``melt_full``. The defaults, 0 and
    6 degC, are those of ESPERE (BRGM RP-69538-FR).
    """

    melt_start: Annotated[float, Profile.USER] = Field(
        default=0.0,
        ge=-10.0,
        le=10.0,
        description="Temperature at or below which nothing melts and all precipitation is snow, in degC.",
        json_schema_extra=field_metadata(unit="degC"),
    )
    melt_full: Annotated[float, Profile.USER] = Field(
        default=6.0,
        ge=-5.0,
        le=15.0,
        description="Temperature at or above which the whole pack melts and no snow falls, in degC.",
        json_schema_extra=field_metadata(unit="degC"),
    )

    @model_validator(mode="after")
    def _full_melt_above_start(self) -> SnowConfig:
        if self.melt_full <= self.melt_start:
            raise ValueError(
                f"melt_full = {self.melt_full:g} degC is not above melt_start = "
                f"{self.melt_start:g} degC: the melt grows from the first to the second."
            )
        return self


class SoilReservoirConfig(HydroModelBase):
    """Daily soil reservoir that turns precipitation and ETP into recharge.

    Read by the recharge binder of every run and of every calibration trial;
    MODFLOW 6 only. See ``model/soil/kernel.py`` for the
    equations.
    """

    method: Annotated[str, Profile.USER] = Field(
        default="fao56",
        description=(
            "Storage law of the soil, the one thing that differs between methods. "
            '"fao56" lowers ETR linearly below alpha x ru (Allen et al. 1998). '
            '"thornthwaite" meets the full demand while water is left (Thornthwaite '
            '1948). "dingman" empties the soil as an exponential of the deficit on dry '
            'days (Dingman 2008). "edijatno_michel" is the production store of GR4J '
            "without its percolation (Edijatno and Michel 1989). The sealed share, the "
            "curve number, the bypass, the transit and the snow work the same around "
            "every law."
        ),
        json_schema_extra=field_metadata(
            value_docs={name: method.label for name, method in SOIL_METHODS.items()},
            stability="experimental",
        ),
        examples=["fao56", "thornthwaite"],
    )
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
        default=0.45,
        gt=0.0,
        le=1.0,
        description=(
            "Share of ru above which the soil evaporates at the full rate kc x ETP. "
            "Below alpha x ru, ETR falls linearly with the stored water. It is 1 - p "
            "of FAO-56 and LP of HBV. The default 0.45 is a choice: it means p = 0.55, "
            "the value of FAO-56 table 22 for cereals and maize (pasture 0.60). Above "
            "0, at most 1. Kept fixed by default: on the discharge alone it trades off "
            "with ru, since both move the annual volume."
        ),
        json_schema_extra=field_metadata(
            calibrable=Calibrable(bounds=(0.3, 1.0), units="-"), stability="experimental"
        ),
    )
    kc: Annotated[Annotated[float, Ge(0.0), Le(2.0)] | SeasonalKc, Profile.USER] = Field(
        default=1.0,
        description=(
            "Crop coefficient applied to the loaded ETP: the soil evaporates at most "
            "kc x ETP a day. 1.0 takes the ETP as loaded, which assumes the surface of "
            "that ETP looks like the site: check what the product refers to. Between 0 "
            "and 2. A table {low, high, months} makes it follow the growing season. "
            "Kept fixed by default: kc and ru move the same annual volume, and only a "
            "number can be calibrated."
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
            "range belongs to the site, so a file has to state it. [data.impervious] "
            "gives it cell by cell instead, and then it is not written here."
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
            "the soil group and the land use of the site. [data.curve_number] gives it "
            "cell by cell instead, and then it is not written here."
        ),
        json_schema_extra=field_metadata(
            calibrable=Calibrable(units="-"), stability="experimental"
        ),
    )
    infiltration_ratio: Annotated[float, Profile.USER] = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Share of the water leaving the soil that goes on to the aquifer, the RIPE of "
            "ESPERE (BRGM): the rest runs off on the same day, beside the sealed share and "
            "the curve number, and reaches the streams through the runoff of the run. 1, "
            "the default, sends it all to the aquifer, bit for bit as before, and the drains "
            "give back what saturates. Between 0 and 1. ESPERE proposes the lowest yearly "
            "baseflow index of the gauge, which the soil budget of `hmp run --until "
            "load_data` prints when a gauge is loaded: copy it here, the gauge never sets it "
            "on its own. [data.infiltration_ratio] gives it cell by cell instead, and then "
            "it is not written here."
        ),
        json_schema_extra=field_metadata(stability="experimental"),
    )
    runoff_time: Annotated[DurationDays, Profile.USER] = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description=(
            "Time constant of the linear reservoir that routes the curve-number "
            "runoff to the outlet, in days. No effect without a curve number, here or "
            "in [data.curve_number]. 0 "
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
            "any lag between the forcing's daily step and the gauge's. No effect without "
            "a curve number, here or in [data.curve_number]. 0 adds no delay, "
            'bit for bit as before; "0.75 days" also reads, interpolated linearly '
            "between the neighbouring whole-day shifts. Between 0 and 5 days: a longer "
            "shift belongs to runoff_time's reservoir, not to a fixed travel time. "
            "Calibrate it with [calibration.parameters.runoff_lag]."
        ),
        json_schema_extra=field_metadata(
            calibrable=Calibrable(bounds=(0.0, 5.0), units="day"), stability="experimental"
        ),
    )
    snow: Annotated[SnowConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Snow pack melted with the daily temperature of [data.temperature]. "
            "Absent, all precipitation reaches the ground as rain the same day."
        ),
        json_schema_extra=field_metadata(stability="experimental"),
    )
    spinup: Annotated[Literal["first_year", "none"], Profile.USER] = Field(
        default="first_year",
        description=(
            'State of the soil on the first day. "first_year" repeats the first '
            "365 days of the run until the storage at the end of that year moves by "
            "less than 0.1 mm, 20 times at most; the run must last 364 days "
            '(52 weeks) at least, and a 364-day run repeats those 364 days. "none" starts from a full soil, the state of a soil in a wet '
            "winter. Beside a cyclic spin-up of the aquifer (flow.ic.kind = "
            '"spinup_cyclic"), the two starts are computed over two windows: the soil '
            "settles on the first year, the heads on the whole run. That pair is allowed "
            "without a warning, because it is sometimes what the study wants."
        ),
        json_schema_extra=field_metadata(
            value_docs={
                "first_year": "Repeat the first year until the soil storage settles.",
                "none": "Start from a full soil and an empty transit store.",
            },
            stability="experimental",
        ),
    )

    @field_validator(*_BARE_NUMBER_UNITS, mode="before")
    @classmethod
    def _a_string_states_its_unit(cls, value: object, info: ValidationInfo) -> object:
        bare = _bare_number_string(value)
        if bare is None:
            return value
        name, unit = info.field_name, _BARE_NUMBER_UNITS[info.field_name]
        raise ValueError(
            f'{name} = "{bare}" has no unit: write {name} = {bare} (a bare number is in '
            f'{unit}) or {name} = "{bare} {unit}".'
        )

    @field_validator("kc", mode="before")
    @classmethod
    def _kc_number_in_range(cls, value: object) -> object:
        # kc is a number or a table, so the union would bury the range message.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _check_range("kc", float(value))
        return value

    @field_validator(*(name for name in _RANGE_RULES if name != "kc"), mode="wrap")
    @classmethod
    def _in_range(
        cls, value: object, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
    ) -> float | None:
        return _within_range(value, handler, partial(_check_range, info.field_name))

    @field_validator("method")
    @classmethod
    def _method_is_known(cls, method: str) -> str:
        if method not in SOIL_METHODS:
            names = ", ".join(f'"{name}"' for name in SOIL_METHODS)
            raise ValueError(f"method = {method!r} is not a soil method: write one of {names}.")
        return method

    @model_validator(mode="after")
    def _alpha_only_where_read(self) -> SoilReservoirConfig:
        if "alpha" in self.model_fields_set and not SOIL_METHODS[self.method].reads_alpha:
            readers = ", ".join(f'"{n}"' for n, m in SOIL_METHODS.items() if m.reads_alpha)
            raise ValueError(
                f'alpha is read by method = {readers} only, and method = "{self.method}" '
                "never reads it: remove alpha, or change the method."
            )
        return self

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


SOIL = "soil"
"""The trait a solver backend lists in ``supports`` when it reads the recharge of the soil reservoir."""


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
    "SOIL",
    "SPINUP_MIN_RUN_DAYS",
    "SeasonalKc",
    "SnowConfig",
    "SoilReservoirConfig",
    "soil_reservoir_of",
    "spinup_refusal",
    "steady_start_refusal",
]
