"""The scored series of one trial: ``sessions/<case>/trial_series/trial-NNNNNN.parquet``.

Opt-in (``[calibration] persist_trial_series``): one small Parquet table per
completed trial, long format, one row per (output, time): ``trial``,
``output``, ``station`` (None when the output names none), ``time``,
``simulated``, ``observed``. Only point and series outputs reach here; a
network or spatial output's cost is already in ``trials.jsonl``.

Each file carries ``hmp.schema_version = "hydromodpy.trial_series.v1"`` and
``hydromodpy_version`` in its footer. The window of the family is
:data:`TRIAL_SERIES_VERSIONS`, its own: a series is not a table of a run and never
goes through ``read_checked_table``, which would refuse it. A file written by the
2.0.0 carries no key and reads as v1, the form it had; a version this code does not
know is refused by name.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from hydromodpy.core.io.document_version import VersionWindow, check_version
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.results.storage.contract import (
    SESSION_TRIAL_SERIES_DIRNAME,
    session_trial_series_filename,
)
from hydromodpy.results.storage.parquet_io import write_table_atomic

COLUMNS: tuple[str, ...] = ("trial", "output", "station", "time", "simulated", "observed")
"""Columns of one trial series table, in order."""

TRIAL_SERIES_SCHEMA: Final[str] = "hydromodpy.trial_series.v1"
"""Version of one trial series file, the value of its ``hmp.schema_version`` key."""

TRIAL_SERIES_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest=TRIAL_SERIES_SCHEMA, current=TRIAL_SERIES_SCHEMA
)
"""Versions of a trial series file this code reads."""

_VERSION_KEY: Final[str] = "hmp.schema_version"


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
    return write_table_atomic(
        table,
        target,
        kv_metadata={_VERSION_KEY: TRIAL_SERIES_SCHEMA, "hydromodpy_version": HYDROMODPY_VERSION},
    )


def _read_one(path: Path) -> pd.DataFrame:
    """Read one series file; a file with no version key is the 2.0.0 form, v1."""
    metadata = pq.read_schema(path).metadata or {}
    found = metadata.get(_VERSION_KEY.encode())
    writer = metadata.get(b"hydromodpy_version")
    check_version(
        TRIAL_SERIES_SCHEMA if found is None else found.decode("utf-8"),
        TRIAL_SERIES_VERSIONS,
        document=path,
        key=_VERSION_KEY,
        writer=None if writer is None else writer.decode("utf-8"),
    )
    return pd.read_parquet(path)


def read_trial_series(session_dir: str | Path) -> pd.DataFrame:
    """Return every trial's scored series of one session, concatenated.

    An empty frame with the same columns when the session never wrote
    ``trial_series/``.
    """
    directory = Path(session_dir) / SESSION_TRIAL_SERIES_DIRNAME
    if not directory.is_dir():
        return pd.DataFrame(columns=COLUMNS)
    frames = [_read_one(path) for path in sorted(directory.glob("trial-*.parquet"))]
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat(frames, ignore_index=True)


__all__ = [
    "COLUMNS",
    "TRIAL_SERIES_SCHEMA",
    "TRIAL_SERIES_VERSIONS",
    "read_trial_series",
    "write_trial_series",
]
