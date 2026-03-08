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


def _to_m_per_day(series: pd.Series, *, units: object, label: str) -> pd.Series:
    """Normalize recharge/runoff units to m/day."""
    unit = str(units).strip().lower()
    if unit in {"m/day", "m/d"}:
        return series.astype(float)
    if unit in {"mm/day", "mm/d"}:
        return series.astype(float) / 1000.0
    raise ValueError(f"{label} units must be 'mm/day' or 'm/day'. Got: {units!r}")


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
    """Build recharge/runoff series from inline synthetic payload."""
    cfg_root = _as_mapping(raw_toml.get("recharge_chronicle"), name="recharge_chronicle")
    cfg = _as_mapping(
        cfg_root.get("synthetic_generated"),
        name="recharge_chronicle.synthetic_generated",
    )

    raw_values = cfg.get("values_mm_day", default_values)
    if isinstance(raw_values, (list, tuple)):
        values = [float(v) for v in raw_values]
    elif isinstance(raw_values, (int, float)) and not isinstance(raw_values, bool):
        values = [float(raw_values)]
    else:
        raise ValueError(
            "recharge_chronicle.synthetic_generated.values_mm_day must be "
            "a scalar or a list of numeric values."
        )

    if simulation_window is None:
        periods = int(cfg.get("periods", len(values)))
        if len(values) not in {1, periods}:
            raise ValueError(
                "recharge_chronicle.synthetic_generated.values_mm_day length must be 1 "
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
                "recharge_chronicle.synthetic_generated.values_mm_day length must be 1 "
                "or match the number of simulation stress periods "
                f"({periods}) derived from simulation.time."
            )
        if len(values) == 1:
            values = values * periods

    recharge_raw = pd.Series(values, index=index, dtype=float)
    recharge = _to_m_per_day(
        recharge_raw,
        units=cfg.get("units", "mm/day"),
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
    recharge = _to_m_per_day(
        recharge_raw,
        units=cfg.get("units", "mm/day"),
        label="synthetic_csv recharge",
    )

    if isinstance(runoff_column, str) and runoff_column in df.columns:
        runoff_raw = pd.Series(df[runoff_column].astype(float).values, index=dates).sort_index()
        runoff = _to_m_per_day(
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
    mode = _normalize_recharge_mode(raw_toml)
    if mode is None:
        return None

    if mode == "observed_csv":
        observed = _build_observed_request(
            raw_toml,
            config_path=config_path,
            default_observed_path=default_observed_path,
            default_sim_state=default_sim_state,
            simulation_window=simulation_window,
        )
        return RechargeChroniclePayload(mode=mode, observed=observed)

    if mode == "synthetic_generated":
        recharge, runoff = _build_synthetic_generated_series(
            raw_toml,
            default_values=default_values,
            simulation_window=simulation_window,
        )
    else:
        recharge, runoff = _build_synthetic_csv_series(
            raw_toml,
            config_path=config_path,
            simulation_window=simulation_window,
        )
    return RechargeChroniclePayload(
        mode=mode,
        recharge=recharge,
        runoff=runoff,
    )
