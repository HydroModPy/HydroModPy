from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.analysis.comparison.runtime import (
    load_variable_series as load_runtime_variable_series,
)
from hydromodpy.analysis.comparison.runtime.series import load_variable_series
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME


class _FakeStore:
    zarr_path = Path(FIELDS_STORE_NAME)

    def __init__(self, root: dict[str, object]) -> None:
        self._root = root

    def open_zarr(self, sim_id: str) -> SimpleNamespace:
        assert sim_id == "sim"
        return SimpleNamespace(root=self._root, close=lambda: None)

    def fields_path_for(self, sim_id: str) -> Path:
        assert sim_id == "sim"
        return self.zarr_path


def test_load_variable_series_uses_root_time_when_bouss_state_axis_is_degenerate(
    tmp_path: Path,
) -> None:
    store = _FakeStore(
        {
            "head": np.asarray([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]], dtype=float),
            "time": np.asarray([0.0, 10.0, 30.0], dtype=float),
            "boussinesq_state": {
                "period_lengths_seconds": np.asarray([0.0, 0.0], dtype=float),
                "snapshot_elapsed_seconds": np.asarray([0.0, 0.0, 0.0], dtype=float),
            },
        }
    )

    series = load_variable_series(
        run_folder=tmp_path,
        variable="head",
        store=store,
        sim_id="sim",
    )

    assert [item.elapsed_seconds for item in series.slices] == [0.0, 10.0, 30.0]
    assert [item.is_initial_state for item in series.slices] == [True, False, False]


def test_load_variable_series_does_not_mark_root_time_as_initial_without_bouss_state(
    tmp_path: Path,
) -> None:
    store = _FakeStore(
        {
            "head": np.asarray([[3.0, 4.0], [5.0, 6.0]], dtype=float),
            "time": np.asarray([10.0, 30.0], dtype=float),
        }
    )

    series = load_variable_series(
        run_folder=tmp_path,
        variable="head",
        store=store,
        sim_id="sim",
    )

    assert [item.elapsed_seconds for item in series.slices] == [10.0, 30.0]
    assert [item.is_initial_state for item in series.slices] == [False, False]


def test_single_snapshot_boussinesq_store_field_is_steady_result(
    tmp_path: Path,
) -> None:
    root = {
        "derived": {
            "watertable_elevation": np.asarray([[7.5, 8.0]], dtype=float),
        },
        "time": np.asarray([0.0], dtype=float),
        "boussinesq_state": {
            "period_lengths_seconds": np.asarray([], dtype=float),
            "snapshot_elapsed_seconds": np.asarray([0.0], dtype=float),
        },
    }

    for loader in (load_variable_series, load_runtime_variable_series):
        series = loader(
            run_folder=tmp_path,
            variable="watertable_elevation",
            store=_FakeStore(root),
            sim_id="sim",
        )

        assert [item.elapsed_seconds for item in series.slices] == [0.0]
        assert [item.is_initial_state for item in series.slices] == [False]


def test_single_snapshot_boussinesq_state_history_is_steady_result(
    tmp_path: Path,
) -> None:
    root = {
        "boussinesq_state": {
            "head_history_m": np.asarray([[7.5, 8.0]], dtype=float),
            "period_lengths_seconds": np.asarray([], dtype=float),
        },
    }

    for loader in (load_variable_series, load_runtime_variable_series):
        series = loader(
            run_folder=tmp_path,
            variable="head_history_m",
            store=_FakeStore(root),
            sim_id="sim",
        )

        assert [item.elapsed_seconds for item in series.slices] == [0.0]
        assert [item.is_initial_state for item in series.slices] == [False]


def test_load_boussinesq_state_series_marks_root_time_initial_when_periods_match(
    tmp_path: Path,
) -> None:
    store = _FakeStore(
        {
            "time": np.asarray([0.0, 10.0, 30.0], dtype=float),
            "boussinesq_state": {
                "head_m": np.asarray(
                    [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]],
                    dtype=float,
                ),
                "period_lengths_seconds": np.asarray([0.0, 0.0], dtype=float),
            },
        }
    )

    series = load_variable_series(
        run_folder=tmp_path,
        variable="head_m",
        store=store,
        sim_id="sim",
    )

    assert [item.elapsed_seconds for item in series.slices] == [0.0, 10.0, 30.0]
    assert [item.is_initial_state for item in series.slices] == [True, False, False]
