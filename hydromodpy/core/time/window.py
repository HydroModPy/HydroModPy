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

from dataclasses import dataclass
import warnings
from typing import Any, Literal

import pandas as pd

from hydromodpy.core.units import (
    normalize_time_unit,
    parse_scalar_and_unit,
    timedelta_to_seconds,
)


_VALID_POLICIES = {"error", "warn", "ignore"}
_VALID_MODES = {"explicit"}
_VALID_STEP_UNITS = {"hour", "day", "month", "year"}


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
    step_unit: Literal["hour", "day", "month", "year"]
    coverage_policy: Literal["error", "warn", "ignore"]

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


def _normalize_policy(raw_policy: Any) -> Literal["error", "warn", "ignore"]:
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


def _normalize_step_unit(raw_step_unit: Any) -> Literal["hour", "day", "month", "year"]:
    """Normalize step-unit aliases to canonical tokens."""
    token = str(raw_step_unit).strip().lower()
    if token in {"m", "mo", "mon", "month", "months"}:
        return "month"
    try:
        canonical = normalize_time_unit(token)
    except ValueError as exc:
        raise ValueError("simulation.time.step_unit must be one of: hour, day, month, year.")
    token_map = {
        "hours": "hour",
        "days": "day",
        "years": "year",
    }
    step_unit = token_map.get(canonical)
    if step_unit is None:
        raise ValueError("simulation.time.step_unit must be one of: hour, day, month, year.")
    return step_unit  # type: ignore[return-value]


def _parse_step_spec(
    *,
    raw_step_value: Any,
    raw_step_unit: Any,
) -> tuple[int, Literal["hour", "day", "month", "year"]]:
    explicit_unit_raw: str | None = None
    if raw_step_unit is not None and str(raw_step_unit).strip() != "":
        explicit_unit_raw = str(raw_step_unit).strip()

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
        raise ValueError("simulation.time.end_datetime must be greater than or equal to start_datetime.")

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
    mode = _normalize_mode(getattr(time_cfg, "mode", "explicit"))
    if mode != "explicit":
        return None

    window = resolve_simulation_time_window(cfg)
    if window is None:
        return None
    # Build explicit period boundaries first, then derive second-based lenper.
    boundaries = _build_time_boundaries(window)
    perlen_seconds = _period_lengths_in_seconds_from_boundaries(boundaries)
    return ResolvedSimulationTimeGrid(
        window=window,
        boundaries=tuple(boundaries),
        period_lengths_seconds=tuple(perlen_seconds),
        nstp_per_period=int(getattr(time_cfg, "substeps_per_period", 1)),
    )


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
        raw_type = process_cfg.get("type", "")
    else:
        raw_type = getattr(process_cfg, "type", "")
    return str(raw_type).strip().lower()


def has_flow_simulation_process(cfg: Any) -> bool:
    """Return ``True`` when the simulation plan declares at least one flow process."""
    return any(_process_type(process_cfg) == "flow" for process_cfg in _iter_simulation_processes(cfg))


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

    Launcher flow solvers no longer accept solver ``tgrid`` sections as a
    fallback source for stress periods. When at least one flow process is
    declared, ``[simulation.time]`` must therefore resolve to one canonical
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
            "Steady flow runs may omit it, but transient runs still require it. "
            "Solver tgrid fallback is no longer supported."
        )
    return grid


def build_simulation_time_boundaries(
    window: ResolvedSimulationTimeWindow,
) -> list[pd.Timestamp]:
    """Return half-open simulation boundaries [t0, ..., tN] from one window."""
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
        return f"{step}H"
    if window.step_unit == "day":
        return f"{step}D"
    if window.step_unit == "month":
        return f"{step}{'MS' if anchor == 'start' else 'ME'}"
    if window.step_unit == "year":
        return f"{step}{'YS' if anchor == 'start' else 'YE'}"
    raise ValueError(f"Unsupported simulation.time.step_unit={window.step_unit!r}.")


def resolve_simulation_time_window(cfg: Any) -> ResolvedSimulationTimeWindow | None:
    """Resolve and validate the canonical simulation window.

    This function performs normalization only; it does not mutate solver tgrid
    sections. Use :func:`apply_explicit_time_window_to_tgrids` for propagation.
    """
    time_cfg = _simulation_time_config(cfg)
    if time_cfg is None:
        return None

    coverage_policy = _normalize_policy(getattr(time_cfg, "coverage_policy", "error"))
    mode = _normalize_mode(getattr(time_cfg, "mode", "explicit"))
    step_value, step_unit = _parse_step_spec(
        raw_step_value=getattr(time_cfg, "step_value", 1),
        raw_step_unit=getattr(time_cfg, "step_unit", None),
    )

    start = _as_timestamp(getattr(time_cfg, "start_datetime", None), name="simulation.time.start_datetime")
    end = _as_timestamp(getattr(time_cfg, "end_datetime", None), name="simulation.time.end_datetime")
    if end < start:
        raise ValueError("simulation.time.end_datetime must be greater than or equal to start_datetime.")
    return ResolvedSimulationTimeWindow(
        start=start,
        end=end,
        step_value=step_value,
        step_unit=step_unit,
        coverage_policy=coverage_policy,
    )


def apply_explicit_time_window_to_tgrids(cfg: Any) -> ResolvedSimulationTimeWindow | None:
    """Apply resolved ``simulation.time`` to flow-solver ``tgrid`` sections.

    The launcher keeps temporal authority in ``[simulation.time]`` and writes
    synchronized values into ``modflownwt.tgrid`` and ``modflow6.tgrid`` when
    those sections are present.
    """
    time_cfg = _simulation_time_config(cfg)
    if time_cfg is None:
        return None
    _normalize_mode(getattr(time_cfg, "mode", "explicit"))
    window = resolve_simulation_time_window(cfg)
    if window is None:
        return None

    grid = resolve_simulation_time_grid(cfg)
    if grid is None:
        return window
    perlen_seconds = list(grid.period_lengths_seconds)
    nper = grid.nper

    for solver_section_name in ("modflownwt", "modflow6"):
        solver_cfg = getattr(cfg, solver_section_name, None)
        tgrid_cfg = getattr(solver_cfg, "tgrid", None) if solver_cfg is not None else None
        if tgrid_cfg is None:
            continue
        # Persist the same canonical window in each active flow solver section.
        tgrid_cfg.start_datetime = window.start.to_pydatetime()
        tgrid_cfg.end_datetime = window.end.to_pydatetime()
        # Launcher temporal mesh is materialized in seconds for SI consistency.
        tgrid_cfg.itmuni = "seconds"
        tgrid_cfg.genmtd = "synthetic_regular"
        tgrid_cfg.nper = nper
        tgrid_cfg.lenper = perlen_seconds
        # Keep launcher temporal control centralized in [simulation.time].
        tgrid_cfg.ntsp = int(getattr(time_cfg, "substeps_per_period", 1))
        tgrid_cfg.tsmult = 1.0
    return window


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
    - otherwise enforce continuous coverage over the inclusive window bounds.
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

    # Exact period-start alignment is the strongest/cleanest contract.
    boundaries = _build_time_boundaries(window)
    period_starts = pd.DatetimeIndex(boundaries[:-1])
    index = pd.DatetimeIndex(series.index)
    is_period_aligned = len(index) == len(period_starts) and index.equals(period_starts)
    if is_period_aligned:
        window_values = series
    else:
        # Fallback path: accept denser/sparser chronologies if they still fully
        # cover window bounds and contain values inside the target interval.
        series_start = pd.Timestamp(series.index.min())
        series_end = pd.Timestamp(series.index.max())
        if series_start > start or series_end < end:
            _handle_recharge_coverage_violation(
                policy,
                "Recharge coverage check failed: recharge range "
                f"[{series_start}, {series_end}] does not fully cover "
                f"simulation window [{start}, {end}].",
            )
            return

        window_values = series.loc[(series.index >= start) & (series.index <= end)]
        if window_values.empty:
            _handle_recharge_coverage_violation(
                policy,
                "Recharge coverage check failed: no recharge values inside simulation window "
                f"[{start}, {end}].",
            )
            return

    if window_values.isna().any():
        _handle_recharge_coverage_violation(
            policy,
            "Recharge coverage check failed: recharge contains NaN values within "
            f"simulation window [{start}, {end}].",
        )
