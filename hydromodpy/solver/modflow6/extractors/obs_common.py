"""Shared MF6 OBS6-CSV parsing helpers for the advanced-package extractors.

LAK and SFR both write a per-feature observation CSV keyed by ``totim`` plus a
build-time JSON sidecar mapping each obs column to its feature / quantity. These
helpers hold the package-agnostic pieces: CSV reading, the totim alignment guard
and the TIMESERIES_SCHEMA record shape.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "ordered_unique",
    "read_obs_csv",
    "rows_matrix",
    "timeseries_record",
    "verify_obs_time_alignment",
]


def read_obs_csv(obs_path: Path) -> tuple[list[str], list[list[float]]]:
    """Return the upper-cased header and float rows of an MF6 obs CSV."""
    with obs_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = [token.strip().upper() for token in next(reader)]
        rows: list[list[float]] = []
        for raw in reader:
            if not raw:
                continue
            rows.append([float(value) for value in raw])
    return header, rows


def rows_matrix(rows: Sequence[Sequence[float]], n_steps: int) -> np.ndarray:
    """Stack the first ``n_steps`` obs rows into a float matrix.

    A truncated final row (killed run) pads with NaN so callers can mask the
    missing cells; MF6 itself never writes NaN values.
    """
    rows = rows[:n_steps]
    if not rows:
        return np.empty((0, 0), dtype="float64")
    lengths = {len(row) for row in rows}
    if len(lengths) == 1:
        return np.asarray(rows, dtype="float64")
    matrix = np.full((len(rows), max(lengths)), np.nan, dtype="float64")
    for t, row in enumerate(rows):
        matrix[t, : len(row)] = row
    return matrix


def verify_obs_time_alignment(
    rows: Sequence[Sequence[float]],
    times: Sequence[float],
    col_index: Mapping[str, int],
    n_steps: int,
    obs_path: Path,
) -> None:
    """Guard the positional obs-CSV / totim alignment with the TIME column.

    The per-feature series are matched to the solver ``totim`` by row order; if
    the obs CSV and the solver output ever drift, that would silently mis-stamp
    every value. MF6 writes the observation time in the first ``time`` column, so
    we cross-check it against the expected ``totim`` and fail loudly on a
    mismatch.
    """
    time_col = col_index.get("TIME")
    if time_col is None:
        return
    for t in range(n_steps):
        row = rows[t]
        if time_col >= len(row):
            continue
        csv_time = float(row[time_col])
        if not math.isclose(csv_time, float(times[t]), rel_tol=1e-6, abs_tol=1e-3):
            raise ValueError(
                f"Obs CSV {obs_path.name} time {csv_time} at row {t} does not match the "
                f"solver totim {float(times[t])}; the obs output is misaligned with the time axis."
            )


def timeseries_record(
    *,
    station: str,
    quantity: str,
    timestep: int,
    time: Any,
    value: float,
    unit: str,
) -> dict[str, Any]:
    """Build one TIMESERIES_SCHEMA record for an advanced-package quantity."""
    record: dict[str, Any] = {
        "station_id": station,
        "variable": quantity,
        "component": None,
        "timestep": int(timestep),
        "value": float(value),
        "unit": unit,
        "qflag": "simulated",
    }
    if time is not None:
        record["time"] = pd.Timestamp(time)
    return record


def ordered_unique(values: Any) -> list[str]:
    """Return the unique values preserving first-seen order."""
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(str(value), None)
    return list(seen)
