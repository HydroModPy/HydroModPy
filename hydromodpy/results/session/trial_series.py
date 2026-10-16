"""The scored series of one trial: ``sessions/<case>/trial_series/trial-NNNNNN.parquet``.

Opt-in (``[calibration] persist_trial_series``): one small Parquet table per
completed trial, long format, one row per (output, time): ``trial``,
``output``, ``station`` (None when the output names none), ``time``,
``simulated``, ``observed``. Only point and series outputs reach here; a
network or spatial output's cost is already in ``trials.jsonl``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa

from hydromodpy.results.storage.contract import (
    SESSION_TRIAL_SERIES_DIRNAME,
    session_trial_series_filename,
)
from hydromodpy.results.storage.parquet_io import write_table_atomic

COLUMNS: tuple[str, ...] = ("trial", "output", "station", "time", "simulated", "observed")
"""Columns of one trial series table, in order."""


def write_trial_series(
    session_dir: str | Path, trial: int, rows: Sequence[Mapping[str, Any]]
) -> Path | None:
    """Write one completed trial's scored series; ``None`` rows write nothing."""
    if not rows:
        return None
    table = pa.table(
        {
            "trial": pa.array([int(trial)] * len(rows), type=pa.int64()),
            "output": pa.array([row.get("output") for row in rows], type=pa.string()),
            "station": pa.array([row.get("station") for row in rows], type=pa.string()),
            "time": pa.array([pd.Timestamp(row["time"]) for row in rows]),
            "simulated": pa.array([float(row["simulated"]) for row in rows], type=pa.float64()),
            "observed": pa.array([float(row["observed"]) for row in rows], type=pa.float64()),
        }
    )
    target = Path(session_dir) / SESSION_TRIAL_SERIES_DIRNAME / session_trial_series_filename(trial)
    return write_table_atomic(table, target)


def read_trial_series(session_dir: str | Path) -> pd.DataFrame:
    """Return every trial's scored series of one session, concatenated.

    An empty frame with the same columns when the session never wrote
    ``trial_series/``.
    """
    directory = Path(session_dir) / SESSION_TRIAL_SERIES_DIRNAME
    if not directory.is_dir():
        return pd.DataFrame(columns=COLUMNS)
    frames = [pd.read_parquet(path) for path in sorted(directory.glob("trial-*.parquet"))]
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat(frames, ignore_index=True)


__all__ = ["COLUMNS", "read_trial_series", "write_trial_series"]
