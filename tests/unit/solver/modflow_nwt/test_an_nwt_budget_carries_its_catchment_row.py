"""A MODFLOW-NWT run writes the budget of its catchment, as a MODFLOW 6 run does.

MODFLOW-NWT meshes the buffered box, so its domain row also sums the drains of
the neighboring basins. On the Nancon the catchment is under half of the box.
A run that kept no per-cell drain (``keep_per_cell_budget = false``, or a trial
a calibration saves beside its best) had only that domain row to build its
``catchment`` discharge from. The series then carried about twice the water
the gauge sees, while the calibration trial had summed the drains of the basin
of D. The same model scored KGE 0.87 as a trial and 0.24 as a saved run.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.scope import CATCHMENT, DOMAIN
from hydromodpy.solver.modflow_common.descent_store import DESCENT_SIDECAR_SUFFIX
from hydromodpy.solver.modflow_nwt.extractors import flow as nwt_flow
from hydromodpy.solver.modflow_nwt.extractors.flow import ModflowNwtOutputAdapter

pytestmark = pytest.mark.unit

NLAY, NROW, NCOL = 1, 1, 4
N_CELLS = NROW * NCOL
BASIN = np.array([True, True, False, False])


class _RecordingStore:
    def __init__(self) -> None:
        self.budgets: list[dict] = []

    def write_budgets(self, sim_id: str, records: list[dict]) -> None:
        self.budgets.extend(records)

    def write_field_stack(self, *args, **kwargs) -> None:
        pass

    def open_zarr(self, sim_id: str) -> _RecordingStore:
        return self

    def write_budget_policy(self, keep: BudgetKeep, written) -> None:
        pass

    def close(self) -> None:
        pass


def _fake_cbc(records: dict[str, np.ndarray]):
    names = list(records)

    class _FakeCellBudgetFile:
        def __init__(self, path: str, precision: str = "double") -> None:
            self.recordarray = np.array(
                [(1, 1, name.rjust(16).encode(), 1, 1.0, 1.0) for name in names],
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
            return [name.encode() for name in records]

        def get_record(self, idx: int, full3D: bool = False) -> np.ndarray:
            return records[names[idx]].reshape(NLAY, NROW, NCOL)

        def close(self) -> None:
            pass

    return _FakeCellBudgetFile


def _rows(monkeypatch, tmp_path: Path, *, catchment_mask) -> dict[tuple[str, str], dict]:
    records = {
        "DRAINS": np.array([-2.0, -1.0, -3.0, -4.0]),
        "RECHARGE": np.full(N_CELLS, 1.25),
    }
    monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", _fake_cbc(records))
    store = _RecordingStore()
    ModflowNwtOutputAdapter()._extract_budget(
        "sim",
        store,
        tmp_path / "run.cbc",
        [1.0],
        [(0, 0)],
        NLAY,
        NROW,
        NCOL,
        budget_terms=BudgetKeep.of_terms(()),
        flux_scale_to_m3_s=1.0,
        catchment_mask=catchment_mask,
    )
    return {(row["zone_id"], row["component"]): row for row in store.budgets}


def test_the_catchment_row_sums_the_basin_alone(tmp_path, monkeypatch) -> None:
    rows = _rows(monkeypatch, tmp_path, catchment_mask=BASIN)

    assert rows[(DOMAIN, "drain")]["flux_out"] == pytest.approx(10.0)
    assert rows[(CATCHMENT, "drain")]["flux_out"] == pytest.approx(3.0)
    assert rows[(CATCHMENT, "recharge")]["flux_in"] == pytest.approx(2.5)


def _sidecar(tmp_path: Path, monkeypatch, record) -> Path:
    (tmp_path / f"model{DESCENT_SIDECAR_SUFFIX}").write_bytes(b"")
    monkeypatch.setattr(nwt_flow, "read_descent_sidecar", lambda path: record)
    return tmp_path


def test_the_basin_is_the_one_the_build_left(tmp_path, monkeypatch) -> None:
    record = SimpleNamespace(basin=BASIN, basin_rule="near_point")
    folder = _sidecar(tmp_path, monkeypatch, record)

    mask = nwt_flow.catchment_basin_the_build_left(folder, n_cells=N_CELLS)

    assert mask is not None
    assert mask.tolist() == BASIN.tolist()


@pytest.mark.parametrize(
    "record",
    [
        SimpleNamespace(basin=BASIN, basin_rule="largest_basin"),
        SimpleNamespace(basin=None, basin_rule=""),
        SimpleNamespace(basin=np.ones(N_CELLS + 1, dtype=bool), basin_rule="near_point"),
        None,
    ],
    ids=["largest_basin", "no_basin", "other_mesh", "empty_sidecar"],
)
def test_no_catchment_basin_means_no_catchment_row(tmp_path, monkeypatch, record) -> None:
    folder = _sidecar(tmp_path, monkeypatch, record)

    assert nwt_flow.catchment_basin_the_build_left(folder, n_cells=N_CELLS) is None
