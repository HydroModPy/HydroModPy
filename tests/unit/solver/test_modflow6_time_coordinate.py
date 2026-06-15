"""Audit P0 - MF6 Zarr /time coordinate is absolute calendar time.

The extractor must anchor the relative MF6 ``totim`` to the TDIS
``START_DATE_TIME`` so the CF ``/time`` axis decodes to real dates. Writing the
relative totim under a 'seconds since 1970' label decodes ~33 years too early.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hydromodpy.solver.modflow6.extractors.flow import (
    _read_start_datetime,
    _write_time_coordinate,
)


class _CaptureStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def write_time(self, sim_id, values, *, epoch=None, calendar=None, units=None) -> None:
        self.calls.append(
            {
                "sim_id": sim_id,
                "values": np.asarray(values, dtype="int64"),
                "epoch": epoch,
                "units": units,
            }
        )


def _epoch_seconds(iso: str) -> int:
    return int((pd.Timestamp(iso) - pd.Timestamp("1970-01-01T00:00:00Z")).total_seconds())


def test_write_time_coordinate_anchors_to_start_datetime(tmp_path) -> None:
    tdis = tmp_path / "model.tdis"
    tdis.write_text(
        "BEGIN OPTIONS\n  TIME_UNITS SECONDS\n  START_DATE_TIME 2003-01-01T00:00:00\nEND OPTIONS\n",
        encoding="utf-8",
    )
    store = _CaptureStore()
    totim = [2592000.0, 5184000.0, 7776000.0]  # 30, 60, 90 days in seconds

    _write_time_coordinate(store, "sim", totim, "SECONDS", tdis)

    assert len(store.calls) == 1
    call = store.calls[0]
    start_epoch = _epoch_seconds("2003-01-01T00:00:00Z")
    expected = np.asarray([start_epoch + int(t) for t in totim], dtype="int64")
    np.testing.assert_array_equal(call["values"], expected)
    assert "1970-01-01" in str(call["units"])
    # Decoded calendar dates land in 2003, not 1970.
    decoded = pd.to_datetime(call["values"], unit="s", utc=True)
    assert decoded[0] == pd.Timestamp("2003-01-31T00:00:00Z")
    assert decoded[-1] == pd.Timestamp("2003-04-01T00:00:00Z")


def test_write_time_coordinate_falls_back_to_launcher_start(tmp_path) -> None:
    # No TDIS START_DATE_TIME, but the launcher passes the start: still anchored.
    tdis = tmp_path / "model.tdis"
    tdis.write_text("BEGIN OPTIONS\n  TIME_UNITS SECONDS\nEND OPTIONS\n", encoding="utf-8")
    store = _CaptureStore()
    totim = [2592000.0, 5184000.0]

    _write_time_coordinate(store, "sim", totim, "SECONDS", tdis, "2003-01-01T00:00:00")

    assert _read_start_datetime(tdis) is None
    assert len(store.calls) == 1
    decoded = pd.to_datetime(store.calls[0]["values"], unit="s", utc=True)
    assert decoded[0] == pd.Timestamp("2003-01-31T00:00:00Z")


def test_write_time_coordinate_relative_without_any_anchor(tmp_path) -> None:
    # No anchor at all: write the relative axis at field resolution (length must
    # match the field arrays) referenced to the 1970 epoch, not skip.
    tdis = tmp_path / "model.tdis"
    tdis.write_text("BEGIN OPTIONS\n  TIME_UNITS SECONDS\nEND OPTIONS\n", encoding="utf-8")
    store = _CaptureStore()
    totim = [2592000.0, 5184000.0, 7776000.0]

    _write_time_coordinate(store, "sim", totim, "SECONDS", tdis, None)

    assert _read_start_datetime(tdis) is None
    assert len(store.calls) == 1
    np.testing.assert_array_equal(store.calls[0]["values"], np.asarray(totim, dtype="int64"))
