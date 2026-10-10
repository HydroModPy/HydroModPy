"""Shared MF6 OBS6-CSV parsing helpers for the advanced-package extractors.

LAK and SFR both write a per-feature observation CSV keyed by ``totim`` plus a
build-time JSON sidecar mapping each obs column to its feature / quantity. These
helpers hold the package-agnostic pieces: CSV reading, the totim alignment guard
and the TIMESERIES_SCHEMA record shape.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.solver.modflow_common.period_steps import group_ends_by_stamp

__all__ = [
    "obs_rows_on_stamps",
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


def obs_rows_on_stamps(
    rows: Sequence[Sequence[float]],
    times: Sequence[float],
    col_index: Mapping[str, int],
    *,
    mean_positions: Iterable[int],
) -> list[list[float]]:
    """Put the per-step rows of an MF6 obs CSV on the stamps of the run.

    MF6 writes an observation at every time step; the store keeps one value
    per stress period, stamped at its end. ``times`` are those stamps. Each
    stamp takes the rows of the steps it closes: a rate column (in
    ``mean_positions``) their mean weighted by step length, any other column,
    a state, the value of the last row, at the stamp. A run of one step per
    period has one row per stamp, returned unchanged. Rows after the last
    stamp, and the stamps after the last row (a run cut short), are left out.
    A stamp no row reaches while later rows exist is a misaligned file and
    raises ``ValueError``.
    """
    time_col = col_index.get("TIME")
    if time_col is None or not rows:
        return [list(row) for row in rows]
    groups = group_ends_by_stamp([float(row[time_col]) for row in rows], times)
    if len(rows) == len(groups) and all(len(group.positions) == 1 for group in groups):
        return [list(row) for row in rows]
    means = sorted(set(int(pos) for pos in mean_positions))
    filled = [bool(group.positions) for group in groups]
    if any(not here and later for here, later in zip(filled, _any_after(filled), strict=True)):
        empty = filled.index(False)
        raise ValueError(
            f"Obs CSV rows do not reach the solver totim {float(times[empty])} of stamp "
            f"{empty} while later stamps have rows; the obs output is misaligned with the "
            "time axis."
        )
    if not any(filled) and rows:
        raise ValueError(
            f"Obs CSV first time {float(rows[0][time_col])} is past every solver totim; "
            "the obs output is misaligned with the time axis."
        )
    out: list[list[float]] = []
    for group in groups:
        if not group.positions:
            break
        block = rows_matrix([rows[i] for i in group.positions], len(group.positions))
        row = block[-1].copy()
        weights = np.asarray(group.weights, dtype="float64")
        for pos in means:
            if pos < block.shape[1] and pos != time_col:
                row[pos] = float(weights @ block[:, pos])
        out.append(row.tolist())
    return out


def _any_after(flags: Sequence[bool]) -> list[bool]:
    """For each position, whether a later position is true."""
    out = [False] * len(flags)
    seen = False
    for index in range(len(flags) - 1, -1, -1):
        out[index] = seen
        seen = seen or bool(flags[index])
    return out


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
