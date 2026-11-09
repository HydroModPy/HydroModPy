"""Golden non-regression test of the custom intermittency loader on three ONDE stations."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from hydromodpy.data.loading.store import DataStore
from hydromodpy.data.variables.intermittency.config import (
    IntermittencyConfig,
    IntermittencySourceConfig,
)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
GOLDEN_FILE = HERE / "golden" / "run_intermittency_case_golden.json"
START, END = "2018-01-01", "2023-12-31"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _signature() -> dict:
    config = IntermittencyConfig(
        sources=[IntermittencySourceConfig(source="file", path=DATA_DIR)],
        date_start=START,
        date_end=END,
    )
    store = DataStore(project_period=(datetime.fromisoformat(START), datetime.fromisoformat(END)))
    points = store.load_intermittency(config).points
    codes = [int(code) for record in points for code in record.data["value"]]
    dates = [record.data["datetime"] for record in points if not record.data.empty]
    station_ids = sorted({record.station_id for record in points})
    return {
        "station_count": len(station_ids),
        "station_ids": station_ids,
        "total_observations": sum(len(record.data) for record in points),
        "date_start": min(d.min() for d in dates).strftime("%Y-%m-%d"),
        "date_end": max(d.max() for d in dates).strftime("%Y-%m-%d"),
        "flow_code_hist": {str(code): codes.count(code) for code in sorted(set(codes))},
    }


@pytest.mark.slow
def test_run_intermittency_case_golden(update_goldens: bool) -> None:
    """The stations, the observation count, the dates and the flow codes stay the same."""
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
