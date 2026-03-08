"""Time-window resolution helpers shared across launchers and data loaders.

This module centralizes the logic that decides where the canonical simulation
time-window comes from:

- explicit values declared in ``[simulation.time]``,
- or flow-solver ``tgrid`` values when ``mode='from_modflow'``.
"""

from __future__ import annotations

from dataclasses import dataclass
import warnings
from typing import Any, Literal

import pandas as pd


_VALID_POLICIES = {"error", "warn", "ignore"}
_VALID_MODES = {"explicit", "from_modflow"}


@dataclass(frozen=True)
class ResolvedSimulationTimeWindow:
    """Canonical simulation window resolved at runtime."""

    start: pd.Timestamp
    end: pd.Timestamp
    coverage_policy: Literal["error", "warn", "ignore"]

    def to_date_bounds(self) -> tuple[str, str]:
        """Return inclusive date bounds as ISO ``YYYY-MM-DD`` strings."""
        return self.start.date().isoformat(), self.end.date().isoformat()


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
    simulation_cfg = getattr(cfg, "simulation", None)
    return getattr(simulation_cfg, "time", None) if simulation_cfg is not None else None


def _flow_solver_preference(cfg: Any) -> list[str]:
    """Return preferred flow-solver order for time-window resolution."""
    preferred: list[str] = []
    simulation_cfg = getattr(cfg, "simulation", None)
    process_list = getattr(simulation_cfg, "process", ()) if simulation_cfg is not None else ()
    for process_cfg in process_list:
        if str(getattr(process_cfg, "type", "")).strip().lower() != "flow":
            continue
        for solver_name in getattr(process_cfg, "solvers", ()) or ():
            token = str(solver_name).strip().lower()
            if token in {"modflownwt", "modflow6"} and token not in preferred:
                preferred.append(token)
    for fallback in ("modflownwt", "modflow6"):
        if fallback not in preferred:
            preferred.append(fallback)
    return preferred


def _normalize_policy(raw_policy: Any) -> Literal["error", "warn", "ignore"]:
    policy = str(raw_policy).strip().lower()
    if policy not in _VALID_POLICIES:
        raise ValueError("simulation.time.coverage_policy must be one of: error, warn, ignore.")
    return policy  # type: ignore[return-value]


def _normalize_mode(raw_mode: Any) -> Literal["explicit", "from_modflow"]:
    mode = str(raw_mode).strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError("simulation.time.mode must be one of: explicit, from_modflow.")
    return mode  # type: ignore[return-value]


def _resolve_window_from_modflow_tgrids(cfg: Any) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    for solver_name in _flow_solver_preference(cfg):
        solver_cfg = getattr(cfg, solver_name, None)
        tgrid_cfg = getattr(solver_cfg, "tgrid", None) if solver_cfg is not None else None
        if tgrid_cfg is None:
            continue
        raw_start = getattr(tgrid_cfg, "start_datetime", None)
        raw_end = getattr(tgrid_cfg, "end_datetime", None)
        if raw_start is None and raw_end is None:
            continue
        if raw_start is None or raw_end is None:
            raise ValueError(
                "simulation.time.mode='from_modflow' requires both "
                f"{solver_name}.tgrid.start_datetime and {solver_name}.tgrid.end_datetime."
            )
        start = _as_timestamp(raw_start, name=f"{solver_name}.tgrid.start_datetime")
        end = _as_timestamp(raw_end, name=f"{solver_name}.tgrid.end_datetime")
        if end <= start:
            raise ValueError(f"{solver_name}.tgrid.end_datetime must be greater than start_datetime.")
        return start, end
    return None


def resolve_simulation_time_window(cfg: Any) -> ResolvedSimulationTimeWindow | None:
    """Resolve canonical simulation window from one launcher config object."""
    time_cfg = _simulation_time_config(cfg)
    if time_cfg is None:
        return None

    coverage_policy = _normalize_policy(getattr(time_cfg, "coverage_policy", "error"))
    mode = _normalize_mode(getattr(time_cfg, "mode", "explicit"))

    if mode == "explicit":
        start = _as_timestamp(getattr(time_cfg, "start_datetime", None), name="simulation.time.start_datetime")
        end = _as_timestamp(getattr(time_cfg, "end_datetime", None), name="simulation.time.end_datetime")
        if end <= start:
            raise ValueError("simulation.time.end_datetime must be greater than start_datetime.")
        return ResolvedSimulationTimeWindow(
            start=start,
            end=end,
            coverage_policy=coverage_policy,
        )

    # mode == "from_modflow"
    window = _resolve_window_from_modflow_tgrids(cfg)
    if window is None:
        raise ValueError(
            "simulation.time.mode='from_modflow' requires at least one flow solver "
            "tgrid window with both start_datetime and end_datetime."
        )
    start, end = window
    return ResolvedSimulationTimeWindow(
        start=start,
        end=end,
        coverage_policy=coverage_policy,
    )


def apply_explicit_time_window_to_tgrids(cfg: Any) -> ResolvedSimulationTimeWindow | None:
    """Apply explicit simulation window to flow solver tgrid sections."""
    time_cfg = _simulation_time_config(cfg)
    if time_cfg is None:
        return None
    mode = _normalize_mode(getattr(time_cfg, "mode", "explicit"))
    window = resolve_simulation_time_window(cfg)
    if window is None:
        return None
    if mode != "explicit":
        return window

    for solver_section_name in ("modflownwt", "modflow6"):
        solver_cfg = getattr(cfg, solver_section_name, None)
        tgrid_cfg = getattr(solver_cfg, "tgrid", None) if solver_cfg is not None else None
        if tgrid_cfg is None:
            continue
        tgrid_cfg.start_datetime = window.start.to_pydatetime()
        tgrid_cfg.end_datetime = window.end.to_pydatetime()
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
    """Validate that recharge fully covers the canonical simulation window."""
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

