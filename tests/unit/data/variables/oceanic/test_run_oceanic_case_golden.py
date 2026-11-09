"""Golden non-regression test of the custom oceanic loader on a local sea level sample."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data.loading.store import DataStore
from hydromodpy.data.variables.oceanic.config import OceanicConfig, OceanicSourceConfig

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
GOLDEN_FILE = HERE / "golden" / "run_oceanic_case_golden.json"
START, END = "2003-01-01", "2003-01-30"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _signature() -> dict:
    source = OceanicSourceConfig(source="file", path=DATA_DIR, col_datetime="timestamp")
    config = OceanicConfig(sources=[source], date_start=START, date_end=END)
    store = DataStore(project_period=(datetime.fromisoformat(START), datetime.fromisoformat(END)))
    records = [
        r for r in store.load_oceanic(config).points if r.variable in ("sea_level", "oceanic")
    ]
    assert records, "the loader returned no sea level record"
    frame = records[0].data.assign(value=lambda df: pd.to_numeric(df["value"], errors="coerce"))
    frame = frame.dropna(subset=["datetime", "value"]).sort_values("datetime")
    values = frame["value"]
    return {
        "row_count": int(len(frame)),
        "first_timestamp": frame["datetime"].iloc[0].strftime("%Y-%m-%d %H:%M:%S"),
        "last_timestamp": frame["datetime"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S"),
        "mean_msl_m": round(float(values.mean()), 12),
        "min_msl_m": round(float(values.min()), 12),
        "max_msl_m": round(float(values.max()), 12),
    }


@pytest.mark.slow
def test_run_oceanic_case_golden(update_goldens: bool) -> None:
    """The row count, the time span and the sea level statistics stay the same."""
    actual = _signature()

    if update_goldens:
        _write_json(GOLDEN_FILE, actual)
        return

    if not GOLDEN_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {GOLDEN_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    assert actual == _load_json(GOLDEN_FILE)
