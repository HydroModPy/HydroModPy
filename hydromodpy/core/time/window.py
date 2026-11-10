"""Canonical simulation-time utilities for launcher workflows.

This module is intentionally a single authority for temporal behavior driven
by ``[simulation.time]`` so launchers, data loaders, and solver builders do
not reimplement similar logic with subtle differences.

Key conventions
---------------
- User input is an *inclusive* window: ``[start_datetime, end_datetime]``.
- Internal period math is computed on *half-open* bounds:
  ``[start_datetime, end_exclusive)``.
- Stress-period lengths are exported in **seconds** for solver-facing ``lenper``.
- Coverage checks can enforce one of three policies:
  ``error`` / ``warn`` / ``ignore``.

The functions below are pure helpers around these conventions, with explicit
validation errors intended to be user-facing.
"""

from __future__ import annotations

import dataclasses
import re
import warnings
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from hydromodpy.core.config_kit.types import CoveragePolicy, TimePeriodUnit
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.units import (
    normalize_time_unit,
    parse_scalar_and_unit,
    timedelta_to_seconds,
)
from hydromodpy.core.units.parse import parse_to_canonical_magnitude

logger = get_logger(__name__)

_VALID_POLICIES = {"error", "warn", "ignore"}
_VALID_MODES = {"explicit"}
_VALID_STEP_UNITS = {"hour", "day", "month", "year"}

# Both launcher time grids below carry their period lengths in seconds, so this
# is the unit every solver backend declares to MODFLOW. Single-sourced here so
# the MF6 TDIS token, the MODFLOW-NWT ITMUNI code and the tracking clock the
# extractors store cannot drift apart: a mismatch between any two of them is a
# silent factor 86400 on fluxes or travel times.
SIMULATION_TIME_UNIT = "seconds"


@dataclass(frozen=True)
class ResolvedSimulationTimeWindow:
    """Normalized runtime representation of ``[simulation.time]``.

    Attributes are already validated and canonicalized:
    - datetimes parsed as :class:`pandas.Timestamp`,
    - step values normalized to positive integer + explicit unit token,
    - policy constrained to ``error|warn|ignore``.
    """

    start: pd.Timestamp
    end: pd.Timestamp
    step_value: int
    step_unit: TimePeriodUnit
    coverage_policy: CoveragePolicy
    period_bounds: tuple[tuple[pd.Timestamp, pd.Timestamp], ...] | None = None
    """Explicit half-open periods, when the window is not cut by its step.

    A steady run carries one period over the whole window here, whatever
    ``step_value`` says. ``None`` cuts the window by the step.
    """

    def to_date_bounds(self) -> tuple[str, str]:
        """Return inclusive date bounds as ISO ``YYYY-MM-DD`` strings.

        This helper is mainly used by data APIs that consume date-only bounds.
        """
        return self.start.date().isoformat(), self.end.date().isoformat()


@dataclass(frozen=True)
class ResolvedSimulationTimeGrid:
    """Canonical stress-period mesh derived from one resolved window."""

    window: ResolvedSimulationTimeWindow
    boundaries: tuple[pd.Timestamp, ...]
    period_lengths_seconds: tuple[float, ...]
    nstp_per_period: int = 1

    @property
    def nper(self) -> int:
        """Number of stress periods."""
        return len(self.period_lengths_seconds)

    @property
    def period_starts(self) -> tuple[pd.Timestamp, ...]:
        """Period start timestamps (inclusive)."""
        return self.boundaries[:-1]

    @property
    def period_ends_exclusive(self) -> tuple[pd.Timestamp, ...]:
        """Period end timestamps (exclusive)."""
        return self.boundaries[1:]


@dataclass(frozen=True)
class ResolvedSteadySimulationTimeGrid:
    """Dedicated steady launcher time representation when ``[simulation.time]`` is absent.

    This keeps one explicit runtime contract for steady flow launchers without
    forcing them to invent an artificial user-facing simulation window.
    """

    period_lengths_seconds: tuple[float, ...] = (1.0,)
    boundaries: tuple[pd.Timestamp, ...] = ()
    window: None = None

    @property
    def nper(self) -> int:
        """Number of stress periods exposed to solver builders."""
        return len(self.period_lengths_seconds)

    @property
    def period_starts(self) -> tuple[pd.Timestamp, ...]:
        """Steady launcher runs without explicit window expose no absolute starts."""
        return ()

    @property
    def period_ends_exclusive(self) -> tuple[pd.Timestamp, ...]:
        """Steady launcher runs without explicit window expose no absolute ends."""
        return ()


def _as_timestamp(value: Any, *, name: str) -> pd.Timestamp:
    """Parse one timestamp-like value and validate it."""
    try:
        ts = pd.Timestamp(value)
    except Exception as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"{name} must be a valid datetime value.") from exc
    if pd.isna(ts):
        raise ValueError(f"{name} must be a valid datetime value.")
    return ts


def _simulation_time_config(cfg: Any) -> Any | None:
    """Return ``cfg.simulation.time`` when available, else ``None``."""
    simulation_cfg = getattr(cfg, "simulation", None)
    return getattr(simulation_cfg, "time", None) if simulation_cfg is not None else None


def _normalize_policy(raw_policy: Any) -> CoveragePolicy:
    """Normalize coverage-policy token and validate allowed values."""
    policy = str(raw_policy).strip().lower()
    if policy not in _VALID_POLICIES:
        raise ValueError("simulation.time.coverage_policy must be one of: error, warn, ignore.")
    return policy  # type: ignore[return-value]


def _normalize_mode(raw_mode: Any) -> Literal["explicit"]:
    """Normalize launcher mode.

    Launcher mode currently supports only ``explicit``. This guard keeps
    behavior fail-fast if unsupported values leak from config migrations.
    """
    mode = str(raw_mode).strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError("simulation.time.mode must be 'explicit' in launcher mode.")
    return mode  # type: ignore[return-value]


def _normalize_step_value(raw_step_value: Any) -> int:
    """Normalize and validate the time-step multiplier."""
    if isinstance(raw_step_value, bool):
        raise ValueError("simulation.time.step_value must be a positive integer.")
    try:
        step_value = float(raw_step_value)
    except Exception as exc:
        raise ValueError("simulation.time.step_value must be a positive integer.") from exc
    if not step_value.is_integer() or step_value <= 0:
        raise ValueError("simulation.time.step_value must be a positive integer.")
    return int(step_value)


def _normalize_step_unit(raw_step_unit: Any) -> TimePeriodUnit:
    """Normalize step-unit aliases to canonical tokens."""
    token = str(raw_step_unit).strip().lower()
    if token in {"m", "mo", "mon", "month", "months"}:
        return "month"
    try:
        canonical = normalize_time_unit(token)
    except ValueError:
        raise ValueError(
            "simulation.time.step_unit must be one of: hour, day, month, year."
        ) from None
    token_map = {
        "hours": "hour",
        "days": "day",
        "years": "year",
    }
    step_unit = token_map.get(canonical)
    if step_unit is None:
        raise ValueError("simulation.time.step_unit must be one of: hour, day, month, year.")
    return step_unit  # type: ignore[return-value]


_BARE_NUMBER_PATTERN = re.compile(r"^\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*$")


def _has_inline_unit(raw_step_value: Any) -> bool:
    """Return True when *raw_step_value* is a string carrying its own unit token."""
    if not isinstance(raw_step_value, str):
        return False
    return _BARE_NUMBER_PATTERN.match(raw_step_value) is None


def _reject_bad_step_value_type_or_sign(raw_step_value: Any) -> None:
    """Raise the positive-integer diagnosis before any unit check runs.

    A boolean or a negative/zero bare number is wrong regardless of whether a
    unit is attached, and that is the more useful thing to tell the caller
    than "has no unit".
    """
    if isinstance(raw_step_value, bool):
        raise ValueError("simulation.time.step_value must be a positive integer.")
    if isinstance(raw_step_value, int | float) and raw_step_value <= 0:
        raise ValueError("simulation.time.step_value must be a positive integer.")
    if isinstance(raw_step_value, str) and _BARE_NUMBER_PATTERN.match(raw_step_value):
        if float(raw_step_value.strip()) <= 0:
            raise ValueError("simulation.time.step_value must be a positive integer.")


def reject_invalid_step_value_spec(raw_step_value: Any, raw_step_unit: Any) -> str | None:
    """Run the ordered step_value/step_unit guards shared by every caller.

    Order matters: a boolean step_value, then a non-positive one, are
    diagnosed before the missing-unit check, since that is the more useful
    message to a caller who wrote neither a unit nor a positive number.

    Returns the stripped explicit unit token, or ``None`` when the caller
    gave no ``step_unit`` and relies on an inline unit instead.

    Raises
    ------
    ValueError
        When step_value is a boolean, non-positive, or has neither an inline
        unit nor an explicit step_unit.
    """
    _reject_bad_step_value_type_or_sign(raw_step_value)

    explicit_unit_raw: str | None = None
    if raw_step_unit is not None and str(raw_step_unit).strip() != "":
        explicit_unit_raw = str(raw_step_unit).strip()

    if explicit_unit_raw is None and not _has_inline_unit(raw_step_value):
        raise ValueError(
            "simulation.time.step_value has no unit. Write an inline unit "
            "(for example '1 month' or '30 day') or set simulation.time.step_unit."
        )
    return explicit_unit_raw


def _parse_step_spec(
    *,
    raw_step_value: Any,
    raw_step_unit: Any,
) -> tuple[int, TimePeriodUnit]:
    explicit_unit_raw = reject_invalid_step_value_spec(raw_step_value, raw_step_unit)

    default_unit = explicit_unit_raw or "day"
    scalar, resolved_unit = parse_scalar_and_unit(
        raw_step_value,
        location="simulation.time.step_value",
        default_unit=default_unit,
    )
    step_value = _normalize_step_value(scalar)
    step_unit = _normalize_step_unit(resolved_unit)

    if explicit_unit_raw is not None:
        expected_unit = _normalize_step_unit(explicit_unit_raw)
        if step_unit != expected_unit:
            raise ValueError(
                "simulation.time.step_value unit conflicts with simulation.time.step_unit."
            )
    return step_value, step_unit


def parse_step_spec(raw_step_value: Any, raw_step_unit: Any = None) -> tuple[int, TimePeriodUnit]:
    """Return the ``(step_value, step_unit)`` a ``[simulation.time]`` step spells.

    ``("7 days", None)`` and ``(7, "day")`` both read ``(7, "day")``. Raises
    ``ValueError`` with the user-facing reason when the spec is not a step.
    """
    return _parse_step_spec(raw_step_value=raw_step_value, raw_step_unit=raw_step_unit)


def nominal_step_days(step_value: int, step_unit: str) -> float:
    """Return the nominal length of one timestep in days.

    A month is the pint month (30.4375 days) and a year 365.25 days, the same
    conventions a duration written in the step's own unit is read with, so
    ``"1 month"`` over a monthly step is exactly one step.
    """
    return parse_to_canonical_magnitude(
        step_value,
        location="simulation.time.step_value",
        canonical_unit="day",
        explicit_unit=step_unit,
    )


def _time_step_offset(*, step_value: int, step_unit: str) -> pd.DateOffset | pd.Timedelta:
    """Build a pandas offset from one canonical step specification."""
    if step_unit == "hour":
        return pd.to_timedelta(step_value, unit="h")
    if step_unit == "day":
        return pd.to_timedelta(step_value, unit="d")
    if step_unit == "month":
        return pd.DateOffset(months=step_value)
    if step_unit == "year":
        return pd.DateOffset(years=step_value)
    raise ValueError(f"Unsupported simulation.time.step_unit={step_unit!r}.")


def _inclusive_end_to_exclusive_end(
    end_inclusive: pd.Timestamp,
    *,
    step_unit: str,
) -> pd.Timestamp:
    """Convert an inclusive end instant to the equivalent exclusive bound.

    Hourly windows advance by one hour; all coarser units advance by one day.
    This keeps date-level inclusive semantics intuitive for day/month/year
    configurations.
    """
    # Inclusive simulation windows are entered as dates/timestamps in TOML.
    # We convert to half-open bounds [start, end_exclusive) for period lengths.
    if step_unit == "hour":
        return end_inclusive + pd.to_timedelta(1, unit="h")
    return end_inclusive + pd.to_timedelta(1, unit="d")


def _build_time_boundaries(window: ResolvedSimulationTimeWindow) -> list[pd.Timestamp]:
    """Build strictly increasing half-open boundaries ``[t0, ..., tN]``."""
    start = window.start
    end = window.end
    if end < start:
        raise ValueError(
            "simulation.time.end_datetime must be greater than or equal to start_datetime."
        )

    end_exclusive = _inclusive_end_to_exclusive_end(
        end,
        step_unit=window.step_unit,
    )
    step_offset = _time_step_offset(
        step_value=window.step_value,
        step_unit=window.step_unit,
    )

    boundaries = [start]
    current = start
    while current < end_exclusive:
        # Advancing by one canonical step guarantees deterministic boundaries.
        current = current + step_offset
        boundaries.append(current)

    if boundaries[-1] != end_exclusive:
        # Reject partial trailing periods: periodization must exactly fit window.
        raise ValueError(
            "simulation.time window is not aligned with step_value/step_unit under "
            "inclusive end semantics. Ensure end_datetime falls exactly on a "
            "time-step boundary."
        )
    return boundaries


def _period_lengths_in_seconds_from_boundaries(
    boundaries: list[pd.Timestamp],
) -> list[float]:
    """Convert boundary deltas to positive ``lenper`` values in seconds."""
    out: list[float] = []
    for idx in range(len(boundaries) - 1):
        delta = boundaries[idx + 1] - boundaries[idx]
        seconds = timedelta_to_seconds(delta)
        if seconds <= 0:
            raise ValueError("Computed non-positive stress-period length from simulation.time.")
        out.append(float(seconds))
    if not out:
        raise ValueError("simulation.time resolved to an empty stress-period sequence.")
    return out


def _period_lengths_in_seconds(window: ResolvedSimulationTimeWindow) -> list[float]:
    """Convenience wrapper: window -> boundaries -> second-based period lengths."""
    boundaries = _build_time_boundaries(window)
    return _period_lengths_in_seconds_from_boundaries(boundaries)


def resolve_simulation_time_grid(cfg: Any) -> ResolvedSimulationTimeGrid | None:
    """Resolve canonical stress periods from ``simulation.time``.

    Returns ``None`` when no ``simulation.time`` section exists.
    """
    time_cfg = _simulation_time_config(cfg)
    if time_cfg is None:
        return None

    window = resolve_simulation_time_window(cfg)
    if window is None:
        return None
    # Build explicit period boundaries first, then derive second-based lenper.
    boundaries = build_simulation_time_boundaries(window)
    perlen_seconds = _period_lengths_in_seconds_from_boundaries(boundaries)
    return ResolvedSimulationTimeGrid(
        window=window,
        boundaries=tuple(boundaries),
        period_lengths_seconds=tuple(perlen_seconds),
        nstp_per_period=int(getattr(time_cfg, "substeps_per_period", 1)),
    )


def time_grid_start(grid: Any) -> str | None:
    """Return the start of a resolved time grid as an ISO string, or ``None``.

    It is the first boundary of the grid, else the start of its window, else its
    first date. ``None`` is no grid, or a grid that dates nothing. An extractor
    anchors the solver output times to this start when the solver writes no
    calendar of its own.
    """
    if grid is None:
        return None
    boundaries = getattr(grid, "boundaries", None)
    if boundaries:
        return str(boundaries[0])
    start = getattr(getattr(grid, "window", None), "start", None)
    if start is not None:
        return str(start)
    datetimes = getattr(grid, "datetimes", None)
    return str(datetimes[0]) if datetimes else None


def _iter_simulation_processes(cfg: Any) -> tuple[Any, ...]:
    """Return declared simulation processes as a stable tuple."""
    simulation_cfg = getattr(cfg, "simulation", None)
    processes = getattr(simulation_cfg, "process", None) if simulation_cfg is not None else None
    if processes is None:
        return ()
    if isinstance(processes, tuple):
        return processes
    if isinstance(processes, list):
        return tuple(processes)
    return (processes,)


def _process_type(process_cfg: Any) -> str:
    """Return normalized process type from typed objects or mappings."""
    if isinstance(process_cfg, dict):
        raw_type = process_cfg.get("kind", "")
    else:
        raw_type = getattr(process_cfg, "kind", "")
    return str(raw_type).strip().lower()


def has_flow_simulation_process(cfg: Any) -> bool:
    """Return ``True`` when the simulation plan declares at least one flow process."""
    return any(
        _process_type(process_cfg) == "flow" for process_cfg in _iter_simulation_processes(cfg)
    )


def _flow_regime(cfg: Any) -> str | None:
    """Return normalized launcher flow regime from the shared ``[flow]`` section."""
    flow_cfg = getattr(cfg, "flow", None)
    if flow_cfg is None:
        return None
    raw_regime = getattr(flow_cfg, "flow_regime", None)
    if raw_regime is None:
        return None
    regime = str(raw_regime).strip().lower()
    if regime in {"steady", "transient"}:
        return regime
    return None


def require_flow_simulation_time_grid(
    cfg: Any,
) -> ResolvedSimulationTimeGrid | ResolvedSteadySimulationTimeGrid | None:
    """Return canonical launcher time-grid, enforcing it for flow runs.

    ``[simulation.time]`` is the only source of stress periods. When at least
    one flow process is declared, it must resolve to one canonical
    ``ResolvedSimulationTimeGrid``.

    Exception
    ---------
    Pure steady flow launcher runs may omit ``[simulation.time]`` entirely.
    In that case, one dedicated steady runtime representation is returned so
    downstream solvers still receive one explicit single-period contract.
    """
    grid = resolve_simulation_time_grid(cfg)
    if not has_flow_simulation_process(cfg):
        return grid
    if grid is None and _flow_regime(cfg) == "steady":
        return ResolvedSteadySimulationTimeGrid()
    if grid is None:
        raise ValueError(
            "Launcher flow processes require a valid [simulation.time] section. "
            "Steady flow runs may omit it, but transient runs still require it."
        )
    return grid


def build_simulation_time_boundaries(
    window: ResolvedSimulationTimeWindow,
) -> list[pd.Timestamp]:
    """Return half-open simulation boundaries [t0, ..., tN] from one window."""
    explicit_bounds = getattr(window, "period_bounds", None)
    if explicit_bounds is not None:
        boundaries: list[pd.Timestamp] = []
        for raw_start, raw_end in tuple(explicit_bounds):
            start = pd.Timestamp(raw_start)
            end = pd.Timestamp(raw_end)
            if not boundaries:
                boundaries.append(start)
            elif boundaries[-1] != start:
                boundaries.append(start)
            boundaries.append(end)
        if len(boundaries) >= 2:
            return boundaries
    return _build_time_boundaries(window)


def simulation_time_pandas_frequency(
    window: ResolvedSimulationTimeWindow,
    *,
    anchor: Literal["start", "end"] = "start",
) -> str:
    """Return a pandas-compatible frequency alias for one simulation window.

    For month/year units, ``anchor`` selects period starts (``MS``/``YS``) or
    period ends (``ME``/``YE``).
    """
    if anchor not in {"start", "end"}:
        raise ValueError("anchor must be 'start' or 'end'.")
    step = int(window.step_value)
    if window.step_unit == "hour":
        return f"{step}h"
    if window.step_unit == "day":
        return f"{step}D"
    if window.step_unit == "month":
        return f"{step}{'MS' if anchor == 'start' else 'ME'}"
    if window.step_unit == "year":
        return f"{step}{'YS' if anchor == 'start' else 'YE'}"
    raise ValueError(f"Unsupported simulation.time.step_unit={window.step_unit!r}.")


def resolve_simulation_time_window(cfg: Any) -> ResolvedSimulationTimeWindow | None:
    """Resolve and validate the canonical simulation window.

    Normalization only: no solver section is mutated. Both MODFLOW backends
    read their stress periods from the grid this window feeds.
    """
    time_cfg = _simulation_time_config(cfg)
    if time_cfg is None:
        return None

    coverage_policy = _normalize_policy(getattr(time_cfg, "coverage_policy", "error"))
    _normalize_mode(getattr(time_cfg, "mode", "explicit"))
    step_value, step_unit = _parse_step_spec(
        raw_step_value=getattr(time_cfg, "step_value", 1),
        raw_step_unit=getattr(time_cfg, "step_unit", None),
    )

    start = _as_timestamp(
        getattr(time_cfg, "start_datetime", None), name="simulation.time.start_datetime"
    )
    end = _as_timestamp(
        getattr(time_cfg, "end_datetime", None), name="simulation.time.end_datetime"
    )
    if end < start:
        raise ValueError(
            "simulation.time.end_datetime must be greater than or equal to start_datetime."
        )
    window = ResolvedSimulationTimeWindow(
        start=start,
        end=end,
        step_value=step_value,
        step_unit=step_unit,
        coverage_policy=coverage_policy,
    )
    if _flow_regime(cfg) == "steady":
        return _one_period_over_the_window(window)
    return window


def _one_period_over_the_window(
    window: ResolvedSimulationTimeWindow,
) -> ResolvedSimulationTimeWindow:
    """Return ``window`` as one stress period, the form a steady run takes.

    A steady period stands for the long-term state, so several of them over
    one window are the same solve repeated. The step is not read; when it
    would have cut the window, the run says so once.
    """
    end_exclusive = _inclusive_end_to_exclusive_end(window.end, step_unit=window.step_unit)
    try:
        cut = len(_build_time_boundaries(window)) - 1
    except ValueError:
        cut = 0
    if cut > 1:
        logger.info(
            "flow_regime = 'steady': one stress period over %s to %s. The step of "
            "[simulation.time], %d %s (%d periods), is not read.",
            window.start.date().isoformat(),
            window.end.date().isoformat(),
            window.step_value,
            window.step_unit,
            cut,
        )
    return dataclasses.replace(window, period_bounds=((window.start, end_exclusive),))


def resolve_simulation_time_window_dates(
    cfg: Any,
    *,
    strict: bool = True,
) -> tuple[str, str] | None:
    """Resolve canonical simulation date bounds as ``YYYY-MM-DD`` strings."""
    try:
        window = resolve_simulation_time_window(cfg)
    except ValueError:
        if strict:
            raise
        return None
    if window is None:
        return None
    return window.to_date_bounds()


def _handle_recharge_coverage_violation(policy: str, message: str) -> None:
    """Apply configured coverage policy to one validation failure message."""
    if policy == "ignore":
        return
    if policy == "warn":
        warnings.warn(message, stacklevel=2)
        return
    raise ValueError(message)


def validate_recharge_coverage(
    recharge: object,
    window: ResolvedSimulationTimeWindow | None,
) -> None:
    """Validate that recharge covers the canonical simulation window.

    Accepted input types:
    - ``pandas.Series`` (preferred),
    - ``pandas.DataFrame`` (first column is used).

    Validation modes:
    - if recharge index exactly matches period starts, use values as-is,
    - otherwise apply the coverage rule of :mod:`hydromodpy.core.time.coverage`.
    """
    if window is None:
        return
    start = window.start
    end = window.end
    policy = window.coverage_policy
    if policy == "ignore":
        return

    if recharge is None:
        _handle_recharge_coverage_violation(
            policy,
            "Recharge coverage check failed: recharge data is missing.",
        )
        return

    if isinstance(recharge, pd.Series):
        series = recharge.copy()
    elif isinstance(recharge, pd.DataFrame):
        if recharge.empty:
            _handle_recharge_coverage_violation(
                policy,
                "Recharge coverage check failed: recharge DataFrame is empty.",
            )
            return
        series = recharge.iloc[:, 0].copy()
    else:
        _handle_recharge_coverage_violation(
            policy,
            "Recharge coverage check requires a datetime-indexed Series/DataFrame "
            f"for window [{start}, {end}], got {type(recharge).__name__}.",
        )
        return

    if not isinstance(series.index, pd.DatetimeIndex):
        try:
            series.index = pd.to_datetime(series.index)
        except Exception:
            _handle_recharge_coverage_violation(
                policy,
                "Recharge coverage check failed: recharge index is not datetime-like.",
            )
            return

    series = series.sort_index()
    if series.empty:
        _handle_recharge_coverage_violation(
            policy,
            "Recharge coverage check failed: recharge series is empty.",
        )
        return

    # A series already on the period starts holds one value per period. Any
    # other record goes through the coverage rule every forcing reader uses
    # (hydromodpy.core.time.coverage).
    boundaries = build_simulation_time_boundaries(window)
    period_starts = pd.DatetimeIndex(boundaries[:-1])
    index = pd.DatetimeIndex(series.index)
    is_period_aligned = len(index) == len(period_starts) and index.equals(period_starts)
    if is_period_aligned:
        window_values = series
    else:
        from hydromodpy.core.time.coverage import enforce_coverage, samples_by_period

        enforce_coverage(
            samples_by_period(index, boundaries),
            boundaries,
            policy=policy,
            label="Recharge coverage check failed: the recharge record",
        )
        window_values = series.loc[(series.index >= start) & (series.index <= end)]

    if window_values.isna().any():
        _handle_recharge_coverage_violation(
            policy,
            "Recharge coverage check failed: recharge contains NaN values within "
            f"simulation window [{start}, {end}].",
        )


# Windows of a chain ---------------------------------------------------------
#
# ``[simulation.time] window_length`` cuts a long transient run into windows,
# each one a sealed run that starts from the final state of the one before.
# A window edge is a period edge, so it is written here and nowhere else.


@dataclass(frozen=True, slots=True)
class ChainWindow:
    """One window of a chain over the grid of the whole simulation.

    ``index`` counts from 1 to ``count``. ``first_period`` is the index of its
    first period in the grid of the whole simulation and ``stop_period`` the
    index after its last one. ``start`` is its first instant and ``end`` its
    exclusive end, a period end of the whole grid.
    """

    index: int
    count: int
    first_period: int
    stop_period: int
    start: pd.Timestamp
    end: pd.Timestamp

    @property
    def nper(self) -> int:
        """Number of stress periods of the window."""
        return self.stop_period - self.first_period


def parse_window_length(raw_length: Any) -> tuple[int, TimePeriodUnit]:
    """Return the ``(count, unit)`` of a ``window_length`` written ``"<n> <unit>"``.

    The unit is one of hour, day, month and year, written in the string: a
    bare number is refused, because a window of 6 is not a length.
    """
    location = "simulation.time.window_length"
    if not isinstance(raw_length, str) or not _has_inline_unit(raw_length):
        raise ValueError(
            f'{location} is a calendar length written "<n> <unit>", such as "6 months" '
            f'or "1 year"; got {raw_length!r}.'
        )
    scalar, unit = parse_scalar_and_unit(raw_length, location=location, default_unit="day")
    try:
        count = _normalize_step_value(scalar)
        step_unit = _normalize_step_unit(unit)
    except ValueError:
        raise ValueError(
            f"{location} is a positive whole number of hours, days, months or years; "
            f"got {raw_length!r}."
        ) from None
    return count, step_unit


def chain_windows(grid: ResolvedSimulationTimeGrid, length: str) -> tuple[ChainWindow, ...]:
    """Cut the grid of the whole simulation into windows of ``length``.

    The edges are ``start + j * length`` in calendar time from the start of the
    simulation. The last window ends with the simulation and may be shorter. A
    length longer than the simulation gives one window. An inner edge that does
    not fall on a period end is refused with the two period ends around it,
    because a window cut inside a period would split its forcing.
    """
    if not isinstance(grid, ResolvedSimulationTimeGrid):
        raise ConfigError(
            "simulation.time.window_length cuts the stress periods of a transient run; "
            "this run has no [simulation.time] periods to cut."
        )
    count, unit = parse_window_length(length)
    boundaries = tuple(pd.Timestamp(edge) for edge in grid.boundaries)
    position = {edge: index for index, edge in enumerate(boundaries)}
    start, end = boundaries[0], boundaries[-1]

    edges = [0]
    step = 1
    while True:
        edge = start + _time_step_offset(step_value=count * step, step_unit=unit)
        if edge >= end:
            break
        if edge not in position:
            after = next(index for index, value in enumerate(boundaries) if value > edge)
            raise ConfigError(
                f"simulation.time.window_length = {length!r} puts a window edge at "
                f"{edge.isoformat()}, inside the stress period from "
                f"{boundaries[after - 1].isoformat()} to {boundaries[after].isoformat()}. "
                "A window ends on a period end: pick a length that is a whole number of "
                "periods, or change [simulation.time]."
            )
        edges.append(position[edge])
        step += 1
    edges.append(len(boundaries) - 1)

    total = len(edges) - 1
    return tuple(
        ChainWindow(
            index=number + 1,
            count=total,
            first_period=edges[number],
            stop_period=edges[number + 1],
            start=boundaries[edges[number]],
            end=boundaries[edges[number + 1]],
        )
        for number in range(total)
    )


def _exclusive_end_to_inclusive_end(end_exclusive: pd.Timestamp, *, step_unit: str) -> pd.Timestamp:
    """The inclusive end a user would write for ``end_exclusive``, the inverse of the rule above."""
    if step_unit == "hour":
        return end_exclusive - pd.to_timedelta(1, unit="h")
    return end_exclusive - pd.to_timedelta(1, unit="d")


def window_grid(
    grid: ResolvedSimulationTimeGrid, window: ChainWindow
) -> ResolvedSimulationTimeGrid:
    """The grid of the periods of ``window``: the same lengths and the same sub-steps.

    The resolved window of the grid starts and ends with ``window``, so a
    reader of its dates sees the window. The last window keeps the end the
    user wrote. When cutting the window by its step would not give back the
    same periods, as for a grid whose periods are written out, the periods are
    written out in ``period_bounds`` too.
    """
    whole = grid.window
    boundaries = tuple(grid.boundaries[window.first_period : window.stop_period + 1])
    if window.stop_period == grid.nper:
        end = whole.end
    else:
        end = _exclusive_end_to_inclusive_end(window.end, step_unit=whole.step_unit)
    resolved = dataclasses.replace(whole, start=window.start, end=end, period_bounds=None)
    if whole.period_bounds is not None or tuple(_build_time_boundaries(resolved)) != boundaries:
        resolved = dataclasses.replace(
            resolved,
            period_bounds=tuple(zip(boundaries[:-1], boundaries[1:], strict=True)),
        )
    return ResolvedSimulationTimeGrid(
        window=resolved,
        boundaries=boundaries,
        period_lengths_seconds=tuple(
            grid.period_lengths_seconds[window.first_period : window.stop_period]
        ),
        nstp_per_period=grid.nstp_per_period,
    )
