"""Recharge chronicle parsing and synthetic-series builders.

This module is launcher-agnostic. It parses the ``[recharge_chronicle]``
section and returns normalized payloads used by runtime orchestration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from hydromodpy.simulation.time import (
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
    simulation_time_pandas_frequency,
)
from hydromodpy.hydrology.synthetic.forcing import build_hydrological_step_series
from hydromodpy.simulation.forcing.recharge_chronicle_config import (
    validate_recharge_chronicle_section,
)
from hydromodpy.support.units import factor_to_m_per_s, normalize_time_unit, parse_scalar_and_unit


RechargeChronicleMode = Literal["observed_csv", "synthetic_generated", "synthetic_csv"]


@dataclass(frozen=True)
class ObservedRechargeChronicleRequest:
    """Normalized request for observed recharge/runoff loading."""

    path_file: Path
    clim_mod: str
    clim_sce: str
    first_year: int
    last_year: int
    time_step: str
    sim_state: str


@dataclass(frozen=True)
class RechargeChroniclePayload:
    """Parsed recharge chronicle payload for one launcher session."""

    mode: RechargeChronicleMode
    observed: ObservedRechargeChronicleRequest | None = None
    recharge: pd.Series | None = None
    runoff: pd.Series | None = None


def _as_mapping(value: object, *, name: str) -> dict[str, Any]:
    """Return a shallow dict copy from a mapping-like payload."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    raise ValueError(f"{name} must be a mapping")


def _resolve_config_path(
    config_path: Path,
    path_value: object,
    *,
    name: str,
) -> Path:
    """Resolve one path relative to the launcher TOML location."""
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError(f"{name} must be a non-empty string path")
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = (config_path.parent / path).resolve()
    return path


def _to_m_per_s(series: pd.Series, *, units: object, label: str) -> pd.Series:
    """Normalize recharge/runoff units to m/s."""
    try:
        factor = factor_to_m_per_s(units)
    except ValueError as exc:
        raise ValueError(
            f"{label} units must be compatible with m/s (for example mm/day, m/day, m/s). "
            f"Got: {units!r}"
        ) from exc
    return series.astype(float) * float(factor)


def _normalize_recharge_mode(raw_toml: Mapping[str, Any]) -> RechargeChronicleMode | None:
    """Return recharge chronicle mode, or ``None`` when section is absent."""
    cfg = _as_mapping(raw_toml.get("recharge_chronicle"), name="recharge_chronicle")
    if not cfg:
        return None
    mode = str(cfg.get("mode", "synthetic_generated")).strip().lower()
    allowed = {"observed_csv", "synthetic_generated", "synthetic_csv"}
    if mode not in allowed:
        raise ValueError(
            "recharge_chronicle.mode must be one of "
            "'observed_csv', 'synthetic_generated', 'synthetic_csv'."
        )
    return mode  # type: ignore[return-value]


def _period_starts_from_window(window: ResolvedSimulationTimeWindow) -> pd.DatetimeIndex:
    boundaries = build_simulation_time_boundaries(window)
    return pd.DatetimeIndex(boundaries[:-1])


def _normalize_positive_integer(value: object, *, location: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{location} must be a positive integer.")
    try:
        parsed = float(value)
    except Exception as exc:
        raise ValueError(f"{location} must be a positive integer.") from exc
    if not parsed.is_integer() or parsed <= 0.0:
        raise ValueError(f"{location} must be a positive integer.")
    return int(parsed)


def _normalize_generation_step_unit(
    raw_unit: object,
    *,
    location: str,
) -> Literal["hour", "day", "month", "year"]:
    token = str(raw_unit).strip().lower()
    if token in {"m", "mo", "mon", "month", "months"}:
        return "month"
    try:
        canonical = normalize_time_unit(token)
    except ValueError as exc:
        raise ValueError(f"{location} must use one of: hour, day, month, year.") from exc
    token_map = {
        "hours": "hour",
        "days": "day",
        "years": "year",
    }
    normalized = token_map.get(canonical)
    if normalized is None:
        raise ValueError(f"{location} must use one of: hour, day, month, year.")
    return normalized  # type: ignore[return-value]


def _parse_generation_step(
    raw_step: object,
    *,
    location: str,
) -> tuple[int, Literal["hour", "day", "month", "year"]]:
    scalar, raw_unit = parse_scalar_and_unit(
        raw_step if raw_step is not None else "1 day",
        location=location,
        default_unit="day",
    )
    return _normalize_positive_integer(scalar, location=location), _normalize_generation_step_unit(
        raw_unit,
        location=location,
    )


def _generation_step_offset(
    *,
    step_value: int,
    step_unit: Literal["hour", "day", "month", "year"],
) -> pd.DateOffset | pd.Timedelta:
    if step_unit == "hour":
        return pd.to_timedelta(step_value, unit="h")
    if step_unit == "day":
        return pd.to_timedelta(step_value, unit="d")
    if step_unit == "month":
        return pd.DateOffset(months=step_value)
    return pd.DateOffset(years=step_value)


def _build_generation_index(
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    step_value: int,
    step_unit: Literal["hour", "day", "month", "year"],
    label: str,
) -> pd.DatetimeIndex:
    if end < start:
        raise ValueError(f"{label} end must be greater than or equal to start.")

    offset = _generation_step_offset(step_value=step_value, step_unit=step_unit)
    values = [start]
    current = start
    while True:
        current = current + offset
        if current > end:
            break
        values.append(current)
    return pd.DatetimeIndex(values)


def _raw_synthetic_values(
    cfg: Mapping[str, Any],
    *,
    default_values: object | None,
) -> list[float]:
    raw_values = cfg.get("values", default_values)
    if isinstance(raw_values, (list, tuple)):
        return [float(v) for v in raw_values]
    if isinstance(raw_values, (int, float)) and not isinstance(raw_values, bool):
        return [float(raw_values)]
    raise ValueError(
        "recharge_chronicle.synthetic_generated.values must be "
        "a scalar or a list of numeric values."
    )


def _build_synthetic_generated_series_from_values(
    cfg: Mapping[str, Any],
    *,
    default_values: object | None,
    simulation_window: ResolvedSimulationTimeWindow | None,
) -> pd.Series:
    values = _raw_synthetic_values(cfg, default_values=default_values)

    if simulation_window is None:
        periods = int(cfg.get("periods", len(values)))
        if len(values) not in {1, periods}:
            raise ValueError(
                "recharge_chronicle.synthetic_generated.values length must be 1 "
                "or match periods."
            )
        if len(values) == 1:
            values = values * periods
        start_date = str(cfg.get("start_date", "2003-01-01"))
        freq = str(cfg.get("freq", "ME"))
        index = pd.date_range(start=start_date, periods=periods, freq=freq)
    else:
        index = _period_starts_from_window(simulation_window)
        periods = len(index)
        if len(values) not in {1, periods}:
            raise ValueError(
                "recharge_chronicle.synthetic_generated.values length must be 1 "
                "or match the number of simulation stress periods "
                f"({periods}) derived from simulation.time."
            )
        if len(values) == 1:
            values = values * periods

    return pd.Series(values, index=index, dtype=float)


def _generation_bounds(
    cfg: Mapping[str, Any],
    *,
    simulation_window: ResolvedSimulationTimeWindow | None,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    if simulation_window is not None:
        return simulation_window.start, simulation_window.end

    raw_start = cfg.get("start_date")
    raw_end = cfg.get("end_date")
    if raw_start is None or raw_end is None:
        raise ValueError(
            "recharge_chronicle.synthetic_generated.generator requires "
            "simulation.time or explicit start_date/end_date bounds."
        )
    return pd.Timestamp(raw_start), pd.Timestamp(raw_end)


def _build_synthetic_generated_series_from_generator(
    cfg: Mapping[str, Any],
    *,
    simulation_window: ResolvedSimulationTimeWindow | None,
) -> pd.Series:
    generator = str(cfg.get("generator", "")).strip().lower()
    if generator != "seasonal_step":
        raise ValueError(
            "recharge_chronicle.synthetic_generated.generator must be "
            "'seasonal_step'."
        )

    start, end = _generation_bounds(cfg, simulation_window=simulation_window)
    step_value, step_unit = _parse_generation_step(
        cfg.get("generation_step", "1 day"),
        location="recharge_chronicle.synthetic_generated.generation_step",
    )
    index = _build_generation_index(
        start=start,
        end=end,
        step_value=step_value,
        step_unit=step_unit,
        label="recharge_chronicle.synthetic_generated",
    )

    seasonal_cfg = _as_mapping(
        cfg.get("seasonal_step"),
        name="recharge_chronicle.synthetic_generated.seasonal_step",
    )
    wet_months_raw = seasonal_cfg.get("wet_months", (10, 11, 12, 1, 2, 3))
    if not isinstance(wet_months_raw, (list, tuple)):
        raise ValueError(
            "recharge_chronicle.synthetic_generated.seasonal_step.wet_months must be a list."
        )
    wet_months = tuple(int(month) for month in wet_months_raw)
    values = build_hydrological_step_series(
        index.to_pydatetime(),
        wet_months=wet_months,
        wet_value=float(seasonal_cfg.get("wet_value", 0.003)),
        dry_value=float(seasonal_cfg.get("dry_value", 0.0004)),
    )
    return pd.Series(values, index=index, dtype=float)


def _align_series_to_simulation_window(
    series: pd.Series,
    *,
    simulation_window: ResolvedSimulationTimeWindow,
    label: str,
) -> pd.Series:
    """Aggregate one datetime-indexed series to simulation stress periods.

    Aggregation policy
    ------------------
    - One output value per stress period.
    - Value = arithmetic mean over values in [period_start, period_end).
    - If no value falls in a period, reuse the last available value before
      period_end (forward carry).
    """
    if series.empty:
        raise ValueError(f"{label} series is empty and cannot be aligned to simulation.time.")

    data = series.copy()
    if not isinstance(data.index, pd.DatetimeIndex):
        data.index = pd.to_datetime(data.index)
    data = data.sort_index()

    boundaries = build_simulation_time_boundaries(simulation_window)
    starts = pd.DatetimeIndex(boundaries[:-1])
    values: list[float] = []
    for left, right in zip(boundaries[:-1], boundaries[1:], strict=False):
        chunk = data.loc[(data.index >= left) & (data.index < right)]
        if not chunk.empty:
            values.append(float(chunk.mean()))
            continue

        # No value inside this period: carry the latest known value before the
        # period end so solver forcing remains continuous.
        history = data.loc[data.index < right]
        if history.empty:
            raise ValueError(
                f"{label} has no value available before simulation period ending at {right}."
            )
        values.append(float(history.iloc[-1]))

    return pd.Series(values, index=starts, dtype=float)


def align_forcing_series_to_simulation_window(
    series: pd.Series,
    *,
    simulation_window: ResolvedSimulationTimeWindow,
    label: str = "forcing",
) -> pd.Series:
    """Public wrapper for period aggregation on simulation-time boundaries."""
    return _align_series_to_simulation_window(
        series,
        simulation_window=simulation_window,
        label=label,
    )


def _build_synthetic_generated_series(
    raw_toml: Mapping[str, Any],
    *,
    default_values: object | None = None,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Build recharge/runoff series from synthetic payload."""
    cfg_root = _as_mapping(raw_toml.get("recharge_chronicle"), name="recharge_chronicle")
    cfg = _as_mapping(
        cfg_root.get("synthetic_generated"),
        name="recharge_chronicle.synthetic_generated",
    )
    generator = str(cfg.get("generator", "")).strip().lower()
    if generator:
        recharge_raw = _build_synthetic_generated_series_from_generator(
            cfg,
            simulation_window=simulation_window,
        )
    else:
        recharge_raw = _build_synthetic_generated_series_from_values(
            cfg,
            default_values=default_values,
            simulation_window=simulation_window,
        )

    recharge = _to_m_per_s(
        recharge_raw,
        units=cfg.get("units", "mm/day"),
        label="synthetic_generated recharge",
    )
    if generator and simulation_window is not None:
        recharge = _align_series_to_simulation_window(
            recharge,
            simulation_window=simulation_window,
            label="synthetic_generated recharge",
        )
    runoff_ratio = float(cfg.get("runoff_ratio", 0.1))
    runoff = recharge * runoff_ratio
    return recharge, runoff


def _build_synthetic_csv_series(
    raw_toml: Mapping[str, Any],
    *,
    config_path: Path,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Build recharge/runoff series from a CSV payload."""
    cfg_root = _as_mapping(raw_toml.get("recharge_chronicle"), name="recharge_chronicle")
    cfg = _as_mapping(
        cfg_root.get("synthetic_csv"),
        name="recharge_chronicle.synthetic_csv",
    )

    path_file = _resolve_config_path(
        config_path,
        cfg.get("path_file", ""),
        name="recharge_chronicle.synthetic_csv.path_file",
    )
    sep = str(cfg.get("sep", ","))
    date_column = str(cfg.get("date_column", "date"))
    recharge_column = str(cfg.get("recharge_column", "recharge_mm_day"))
    date_format = cfg.get("date_format")
    runoff_column = cfg.get("runoff_column")

    df = pd.read_csv(path_file, sep=sep)
    if date_column not in df.columns:
        raise ValueError(f"Column '{date_column}' not found in synthetic recharge CSV: {path_file}")
    if recharge_column not in df.columns:
        raise ValueError(
            f"Column '{recharge_column}' not found in synthetic recharge CSV: {path_file}"
        )

    if date_format is None:
        dates = pd.to_datetime(df[date_column])
    else:
        dates = pd.to_datetime(df[date_column], format=str(date_format))

    recharge_raw = pd.Series(df[recharge_column].astype(float).values, index=dates).sort_index()
    recharge = _to_m_per_s(
        recharge_raw,
        units=cfg.get("units", "mm/day"),
        label="synthetic_csv recharge",
    )

    if isinstance(runoff_column, str) and runoff_column in df.columns:
        runoff_raw = pd.Series(df[runoff_column].astype(float).values, index=dates).sort_index()
        runoff = _to_m_per_s(
            runoff_raw,
            units=cfg.get("runoff_units", cfg.get("units", "mm/day")),
            label="synthetic_csv runoff",
        )
    else:
        runoff_ratio = float(cfg.get("runoff_ratio", 0.1))
        runoff = recharge * runoff_ratio

    time_step = cfg.get("time_step")
    if isinstance(time_step, str) and time_step.strip():
        recharge = recharge.resample(time_step).mean().ffill()
        runoff = runoff.resample(time_step).mean().ffill()
    elif simulation_window is not None:
        freq = simulation_time_pandas_frequency(simulation_window, anchor="start")
        recharge = recharge.resample(freq).mean().ffill()
        runoff = runoff.resample(freq).mean().ffill()

    if simulation_window is not None:
        recharge = _align_series_to_simulation_window(
            recharge,
            simulation_window=simulation_window,
            label="synthetic_csv recharge",
        )
        runoff = _align_series_to_simulation_window(
            runoff,
            simulation_window=simulation_window,
            label="synthetic_csv runoff",
        )

    return recharge, runoff


def _build_observed_request(
    raw_toml: Mapping[str, Any],
    *,
    config_path: Path,
    default_observed_path: Path,
    default_sim_state: str,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
) -> ObservedRechargeChronicleRequest:
    """Build normalized observed recharge/runoff request payload."""
    cfg_root = _as_mapping(raw_toml.get("recharge_chronicle"), name="recharge_chronicle")
    cfg = _as_mapping(
        cfg_root.get("observed_csv"),
        name="recharge_chronicle.observed_csv",
    )

    path_file = _resolve_config_path(
        config_path,
        cfg.get("path_file", str(default_observed_path)),
        name="recharge_chronicle.observed_csv.path_file",
    )
    clim_mod = str(cfg.get("clim_mod", "REA"))
    clim_sce = str(cfg.get("clim_sce", "historic"))
    if simulation_window is None:
        first_year = int(cfg.get("first_year", 2003))
        last_year = int(cfg.get("last_year", first_year))
        time_step = str(cfg.get("time_step", "ME"))
    else:
        # In launcher-driven mode, force observed extraction to the canonical
        # simulation temporal grid.
        first_year = int(simulation_window.start.year)
        last_year = int(simulation_window.end.year)
        time_step = simulation_time_pandas_frequency(simulation_window, anchor="start")
    sim_state = str(cfg.get("sim_state", default_sim_state))

    return ObservedRechargeChronicleRequest(
        path_file=path_file,
        clim_mod=clim_mod,
        clim_sce=clim_sce,
        first_year=first_year,
        last_year=last_year,
        time_step=time_step,
        sim_state=sim_state,
    )


def build_recharge_chronicle_payload(
    raw_toml: Mapping[str, Any],
    *,
    config_path: Path,
    default_values: object | None = None,
    default_observed_path: Path,
    default_sim_state: str,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
) -> RechargeChroniclePayload | None:
    """Parse one ``[recharge_chronicle]`` section into a normalized payload."""
    validated_cfg = validate_recharge_chronicle_section(raw_toml.get("recharge_chronicle"))
    if validated_cfg is None:
        return None
    normalized_raw_toml = {
        "recharge_chronicle": validated_cfg.model_dump(mode="python", exclude_none=True)
    }
    mode = validated_cfg.mode

    if mode == "observed_csv":
        observed = _build_observed_request(
            normalized_raw_toml,
            config_path=config_path,
            default_observed_path=default_observed_path,
            default_sim_state=default_sim_state,
            simulation_window=simulation_window,
        )
        return RechargeChroniclePayload(mode=mode, observed=observed)

    if mode == "synthetic_generated":
        recharge, runoff = _build_synthetic_generated_series(
            normalized_raw_toml,
            default_values=default_values,
            simulation_window=simulation_window,
        )
    else:
        recharge, runoff = _build_synthetic_csv_series(
            normalized_raw_toml,
            config_path=config_path,
            simulation_window=simulation_window,
        )
    return RechargeChroniclePayload(
        mode=mode,
        recharge=recharge,
        runoff=runoff,
    )
