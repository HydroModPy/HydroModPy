from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.solver.modflow_common import calibration_extractors as extractors


def test_drain_budget_array_to_positive_outflow_by_cell_sums_layers() -> None:
    signed = np.array(
        [
            [-2.0, 1.0, -0.5],
            [-3.0, -4.0, 2.0],
        ],
        dtype="float64",
    )

    out = extractors.drain_budget_array_to_positive_outflow_by_cell(signed, n_cells=3)

    np.testing.assert_allclose(out, np.array([5.0, 4.0, 0.5]))


def test_drain_budget_array_to_positive_outflow_by_cell_keeps_positive_convention() -> None:
    positive = np.array([[2.0, 0.0, 0.5]], dtype="float64")

    out = extractors.drain_budget_array_to_positive_outflow_by_cell(positive, n_cells=3)

    np.testing.assert_allclose(out, np.array([2.0, 0.0, 0.5]))


def test_drain_budget_array_to_positive_outflow_by_cell_validates_n_cells() -> None:
    with pytest.raises(ValueError, match="multiple of n_cells"):
        extractors.drain_budget_array_to_positive_outflow_by_cell([1.0, 2.0], n_cells=3)


def test_extract_drain_outflow_by_cell_from_cbc_returns_m3_per_s(monkeypatch, tmp_path) -> None:
    class _FakeCellBudgetFile:
        def __init__(self, path: str):
            self.path = path
            self.closed = False

        def get_unique_record_names(self):
            return [b"DRAINS"]

        def get_times(self):
            return [1.0, 2.0]

        def get_kstpkper(self):
            return [(0, 0), (0, 1)]

        def get_data(self, *, text, kstpkper, totim, full3D):
            del text, kstpkper, full3D
            if totim == 1.0:
                return [np.array([[-86400.0, 0.0, -43200.0]], dtype="float64")]
            return []

        def close(self):
            self.closed = True

    import flopy.utils.binaryfile as bf

    monkeypatch.setattr(bf, "CellBudgetFile", _FakeCellBudgetFile)

    output_dir = tmp_path
    (output_dir / "model.cbc").write_text("", encoding="utf-8")
    (output_dir / "model.dis").write_text("1 1 1\n1 4\n", encoding="utf-8")
    index = pd.DatetimeIndex(["2020-01-01", "2020-02-01"])

    frame = extractors.extract_drain_outflow_by_cell_from_cbc(
        output_dir,
        "model",
        time_index=index,
        n_cells=3,
    )

    assert list(frame.index) == list(index)
    assert list(frame.columns) == [0, 1, 2]
    np.testing.assert_allclose(frame.iloc[0].to_numpy(), np.array([1.0, 0.0, 0.5]))
    np.testing.assert_allclose(frame.iloc[1].to_numpy(), np.array([0.0, 0.0, 0.0]))


class _FakeHeadFile:
    """Two snapshots of a two-layer, three-cell model, layer-major."""

    def __init__(self, path):
        self.path = path

    def get_times(self):
        return [1.0, 2.0]

    def get_data(self, *, totim):
        if totim == 1.0:
            # layer 0: 12, 8, 1e30 (dry) - layer 1 must never be read
            return np.array([[[12.0, 8.0, 1e30]], [[-5.0, -5.0, -5.0]]])
        return np.array([[[20.0, 4.0, 6.0]], [[-5.0, -5.0, -5.0]]])

    def close(self):
        return None


def test_extract_saturated_thickness_reads_the_uppermost_layer(tmp_path, monkeypatch):
    import flopy.utils.binaryfile as bf

    monkeypatch.setattr(bf, "HeadFile", _FakeHeadFile)
    output_dir = tmp_path
    (output_dir / "model.hds").write_text("", encoding="utf-8")

    index = pd.date_range("2020-01-01", periods=2, freq="D")
    frame = extractors.extract_saturated_thickness_by_cell_from_hds(
        output_dir,
        "model",
        top=np.array([10.0, 10.0, 10.0]),
        bottom=np.array([0.0, 0.0, 0.0]),
        time_index=index,
    )

    assert list(frame.index) == list(index)
    assert list(frame.columns) == [0, 1, 2]
    # 12 m of head over a 10 m aquifer saturates it without inflating it; 8 m
    # gives 8 m; the dry sentinel is not a thickness.
    assert frame.iloc[0].tolist()[:2] == [10.0, 8.0]
    assert np.isnan(frame.iloc[0].tolist()[2])
    assert frame.iloc[1].tolist() == [10.0, 4.0, 6.0]


def test_extract_saturated_thickness_clips_below_the_aquifer_base(tmp_path, monkeypatch):
    import flopy.utils.binaryfile as bf

    monkeypatch.setattr(bf, "HeadFile", _FakeHeadFile)
    (tmp_path / "model.hds").write_text("", encoding="utf-8")

    frame = extractors.extract_saturated_thickness_by_cell_from_hds(
        tmp_path,
        "model",
        top=np.array([30.0, 30.0, 30.0]),
        bottom=np.array([10.0, 10.0, 10.0]),
    )

    # Head at 8 m sits below the 10 m base: zero thickness, never negative.
    assert frame.iloc[0, 1] == 0.0
    assert frame.iloc[1, 0] == 10.0


def test_extract_saturated_thickness_validates_the_bounds(tmp_path, monkeypatch):
    import flopy.utils.binaryfile as bf

    monkeypatch.setattr(bf, "HeadFile", _FakeHeadFile)
    (tmp_path / "model.hds").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="top holds 3 cells but bottom holds 2"):
        extractors.extract_saturated_thickness_by_cell_from_hds(
            tmp_path, "model", top=np.zeros(3), bottom=np.zeros(2)
        )


def test_extract_saturated_thickness_needs_the_head_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="HDS file not found"):
        extractors.extract_saturated_thickness_by_cell_from_hds(
            tmp_path, "model", top=np.zeros(3), bottom=np.zeros(3)
        )
