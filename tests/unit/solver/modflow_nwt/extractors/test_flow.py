"""The MODFLOW-NWT extractor reads a face flow with its sign and masks the head sentinels.

A budget term is positive where water enters the aquifer and negative where it leaves, and is stored
as an inflow and an outflow, both positive. A face flow is positive towards the cell of the larger flat
index. A head equal to ``hdry`` or ``hnoflo`` (or of about 1e30) is not a head and becomes NaN.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.exceptions import ExtractError
from hydromodpy.solver.modflow_common.flow_run import final_state_head
from hydromodpy.solver.modflow_nwt.extractors.flow import (
    ModflowNwtOutputAdapter,
    face_connections,
)

# --------------------------------------------------------------------------- budget sign


class _Store:
    def __init__(self) -> None:
        self.budgets: list[dict] = []

    def write_budgets(self, _sim_id: str, records: list[dict]) -> None:
        self.budgets.extend(records)

    def write_field_stack(self, *_args, **_kwargs) -> None:
        return None

    def open_zarr(self, _sim_id: str) -> _Store:
        return self

    def write_budget_policy(self, *_args) -> None:
        return None

    def close(self) -> None:
        return None


def _fake_cbc(name: str, values: list[float]):
    class _File:
        def __init__(self, _path: str, precision: str = "double") -> None:
            self.recordarray = np.array(
                [(1, 1, name.rjust(16).encode(), 1, 1.0, 1.0)],
                dtype=[
                    ("kstp", "<i4"),
                    ("kper", "<i4"),
                    ("text", "S16"),
                    ("imeth", "<i4"),
                    ("delt", "<f4"),
                    ("totim", "<f4"),
                ],
            )

        def get_unique_record_names(self) -> list[bytes]:
            return [name.encode()]

        def get_record(self, _idx: int, full3D: bool = False) -> np.ndarray:
            return np.array(values, dtype=float).reshape(1, 1, -1)

        def close(self) -> None:
            return None

    return _File


def _row(monkeypatch, tmp_path: Path, name: str, values: list[float], scale: float = 1.0) -> dict:
    monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", _fake_cbc(name, values))
    store = _Store()
    ModflowNwtOutputAdapter()._extract_budget(
        "sim",
        store,
        tmp_path / "run.cbc",
        [1.0],
        [(0, 0)],
        1,
        1,
        len(values),
        budget_terms=BudgetKeep.everything(),
        flux_scale_to_m3_s=scale,
    )
    return next(row for row in store.budgets if row["zone_id"] != "catchment")


# One row per cell set of a drain record: the signed values in model units, the scale to m3/s, the
# inflow and the outflow stored. A drain loses water, so its values are negative.
_BUDGET = [
    pytest.param([-2.0], 1.0, 0.0, 2.0, id="a_drain_leaving"),
    pytest.param([3.0], 1.0, 3.0, 0.0, id="water_entering"),
    pytest.param([-2.0, 3.0, 0.0], 1.0, 3.0, 2.0, id="mixed_cells_split_on_their_own_sign"),
    pytest.param([0.0], 1.0, 0.0, 0.0, id="no_flux"),
    pytest.param([-0.0], 1.0, 0.0, 0.0, id="negative_zero_is_no_flux"),
    pytest.param([-1.0e-12], 1.0, 0.0, 1.0e-12, id="a_tiny_loss_is_a_loss"),
    pytest.param([-864.0], 1.0 / 86400.0, 0.0, 0.01, id="per_day_to_per_second"),
]


@pytest.mark.parametrize(("values", "scale", "flux_in", "flux_out"), _BUDGET)
def test_a_budget_term_is_split_into_a_positive_inflow_and_outflow(
    monkeypatch, tmp_path, values, scale, flux_in, flux_out
) -> None:
    row = _row(monkeypatch, tmp_path, "DRAINS", values, scale)

    assert row["component"] == "drain"
    assert row["flux_in"] == pytest.approx(flux_in, abs=1e-18)
    assert row["flux_out"] == pytest.approx(flux_out, abs=1e-18)


# --------------------------------------------------------------------------- face sign


def _faces(right, front=None, lower=None, *, active=None):
    shape = np.shape(right)
    zeros = np.zeros(shape)
    return face_connections(
        np.asarray(right, dtype=float),
        zeros if front is None else np.asarray(front, dtype=float),
        zeros if lower is None else np.asarray(lower, dtype=float),
        active=np.ones(shape, dtype=bool) if active is None else active,
    )


def test_a_face_flow_is_positive_towards_the_larger_flat_index() -> None:
    # One layer, one row, three columns. A value sits on the cell it leaves to the right: +2 flows
    # from cell 0 to cell 1, -3 flows from cell 2 to cell 1 (against the index), and the last
    # column has no face to the right, so its 9.0 is dropped.
    cells, flows = _faces([[[2.0, -3.0, 9.0]]])

    assert cells.tolist() == [[0, 1], [1, 2]]
    assert flows.tolist() == [2.0, -3.0]


def test_a_front_face_goes_to_the_next_row_and_a_lower_face_to_the_next_layer() -> None:
    # Two layers, two rows, one column: flat index = layer * 2 + row.
    right = np.zeros((2, 2, 1))
    front = np.array([[[1.5], [0.0]], [[2.5], [0.0]]])
    lower = np.array([[[4.0], [5.0]], [[0.0], [0.0]]])

    cells, flows = face_connections(right, front, lower, active=np.ones((2, 2, 1), dtype=bool))

    assert cells.tolist() == [[0, 1], [0, 2], [1, 3], [2, 3]]
    assert flows.tolist() == [1.5, 4.0, 5.0, 2.5]


def test_a_pair_that_touches_an_inactive_cell_is_left_out() -> None:
    active = np.array([[[True, False, True, True]]])

    cells, flows = _faces([[[1.0, 2.0, 3.0, 4.0]]], active=active)

    assert cells.tolist() == [[2, 3]]
    assert flows.tolist() == [3.0]


def test_a_face_record_of_another_shape_is_refused() -> None:
    with pytest.raises(ExtractError, match="face flows of this run cannot be read"):
        face_connections(
            np.zeros((1, 1, 3)),
            np.zeros((1, 1, 2)),
            np.zeros((1, 1, 3)),
            active=np.ones((1, 1, 3), dtype=bool),
        )


# --------------------------------------------------------------------------- sentinel heads

_HDRY = -888.0
_HNOFLO = -9999.0

# One row per head: its value and whether it becomes NaN. The sentinels the run was configured
# with are caught within one meter, and a head of the order of 1e30 is caught whatever the config.
_HEADS = [
    pytest.param(120.0, False, id="a_head"),
    pytest.param(-888.0, True, id="hdry"),
    pytest.param(-888.5, True, id="hdry_within_a_meter"),
    pytest.param(-9999.0, True, id="hnoflo"),
    pytest.param(-9999.9, True, id="hnoflo_within_a_meter"),
    pytest.param(-880.0, False, id="not_the_sentinel"),
    pytest.param(1.0e30, True, id="mf6_style_dry"),
    pytest.param(-1.0e30, True, id="mf6_style_dry_negative"),
    pytest.param(0.0, False, id="zero_is_a_head"),
]


@pytest.mark.parametrize(("head", "masked"), _HEADS)
def test_a_sentinel_head_becomes_nan(head, masked) -> None:
    final = final_state_head(np.array([[head]]), nlay=1, n_cells=1, sentinels=(_HDRY, _HNOFLO))

    assert bool(np.isnan(final[0, 0])) is masked
    if not masked:
        assert final[0, 0] == head
