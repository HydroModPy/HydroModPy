"""The catchment budget row of a MODFLOW-NWT run, and the basin it sums (fluxes in m3/s).

NWT meshes the buffered box, so its domain row also sums the drains of the neighboring
basins. On the Nancon the catchment is under half of the box. A run without per-cell drains
rebuilds the catchment row from the basin the build left in its sidecar. A synthetic domain
has no catchment, so its runs carry the domain row alone and its discharge sums the domain.
The listing file gives the mass balance of each step.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.synthetic.catchment import build_synthetic_geographic
from hydromodpy.catchment.synthetic.synthetic_config import (
    LinearTopography,
    SyntheticGeographicConfig,
    SyntheticGridConfig,
)
from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.exceptions import ExtractError
from hydromodpy.core.scope import CATCHMENT, DOMAIN
from hydromodpy.model.domain.geometry import CatchmentGeometry
from hydromodpy.model.model import Geometry
from hydromodpy.solver.modflow_common.catchment_basin import catchment_cell_mask, run_basin
from hydromodpy.solver.modflow_common.descent_store import (
    DESCENT_SIDECAR_SUFFIX,
    write_descent_sidecar,
)
from hydromodpy.solver.modflow_common.flow_directions import build_solver_mesh_descent
from hydromodpy.solver.modflow_nwt.extractors import flow as nwt_flow
from hydromodpy.solver.modflow_nwt.extractors.flow import (
    ModflowNwtOutputAdapter,
    catchment_basin_the_build_left,
)
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

pytestmark = pytest.mark.unit

NLAY, NROW, NCOL = 1, 1, 4
N_CELLS = NROW * NCOL
BASIN = np.array([True, True, False, False])


class RecordingStore:
    def __init__(self) -> None:
        self.budgets: list[dict] = []
        self.mass_balances: list[dict] = []

    def write_budgets(self, sim_id: str, records: list[dict]) -> None:
        self.budgets.extend(records)

    def write_mass_balances(self, sim_id: str, records: list[dict]) -> None:
        self.mass_balances = records

    def write_field_stack(self, *args, **kwargs) -> None:
        pass

    def open_zarr(self, sim_id: str) -> RecordingStore:
        return self

    def write_budget_policy(self, keep: BudgetKeep, written) -> None:
        pass

    def close(self) -> None:
        pass


def fake_cbc(records: dict[str, np.ndarray]):
    names = list(records)

    class FakeCellBudgetFile:
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

    return FakeCellBudgetFile


def budget_rows(monkeypatch, tmp_path: Path, *, catchment_mask) -> dict[tuple[str, str], dict]:
    records = {
        "DRAINS": np.array([-2.0, -1.0, -3.0, -4.0]),
        "RECHARGE": np.full(N_CELLS, 1.25),
    }
    monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", fake_cbc(records))
    store = RecordingStore()
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


def test_catchment_row_sums_the_basin_alone(tmp_path, monkeypatch):
    rows = budget_rows(monkeypatch, tmp_path, catchment_mask=BASIN)

    assert rows[(DOMAIN, "drain")]["flux_out"] == pytest.approx(10.0)  # 2 + 1 + 3 + 4
    assert rows[(CATCHMENT, "drain")]["flux_out"] == pytest.approx(3.0)  # cells 0 and 1
    assert rows[(CATCHMENT, "recharge")]["flux_in"] == pytest.approx(2.5)  # 2 x 1.25


def descent_sidecar(tmp_path: Path, monkeypatch, record) -> Path:
    (tmp_path / f"model{DESCENT_SIDECAR_SUFFIX}").write_bytes(b"")
    monkeypatch.setattr(nwt_flow, "read_descent_sidecar", lambda path: record)
    return tmp_path


def test_basin_is_the_one_the_build_left(tmp_path, monkeypatch):
    record = SimpleNamespace(basin=BASIN, basin_rule="near_point")
    folder = descent_sidecar(tmp_path, monkeypatch, record)

    mask = catchment_basin_the_build_left(folder, n_cells=N_CELLS)

    assert mask is not None
    assert mask.tolist() == BASIN.tolist()


NO_CATCHMENT_RECORDS = [
    pytest.param(SimpleNamespace(basin=BASIN, basin_rule="largest_basin"), id="largest basin"),
    pytest.param(SimpleNamespace(basin=None, basin_rule=""), id="no basin"),
    pytest.param(
        SimpleNamespace(basin=np.ones(N_CELLS + 1, dtype=bool), basin_rule="near_point"),
        id="other mesh",
    ),
    pytest.param(None, id="empty sidecar"),
]


@pytest.mark.parametrize("record", NO_CATCHMENT_RECORDS)
def test_no_catchment_basin_means_no_catchment_row(tmp_path, monkeypatch, record):
    folder = descent_sidecar(tmp_path, monkeypatch, record)

    assert catchment_basin_the_build_left(folder, n_cells=N_CELLS) is None


# A synthetic geographic writes its box as the watershed for masks and figures. That box is
# the domain, and it closes no catchment.

N = 10
DX_M = 10.0


def synthetic_domain(tmp_path: Path):
    config = SyntheticGeographicConfig(
        case_id="tilted",
        grid=SyntheticGridConfig(
            length_x=f"{N * DX_M} m", length_y=f"{N * DX_M} m", nx=N, ny=N, xmin=0.0, ymin=0.0
        ),
        topography=LinearTopography(base_elevation=20.0, right_to_left_amplitude=5.0),
    )
    geographic = build_synthetic_geographic(config=config, output_dir=tmp_path / "synthetic")
    top = np.asarray(geographic.surface_topo.as_array(), dtype=float)
    mesh = solver_mesh_from_structured_arrays(
        nrow=N, ncol=N, top=top, botm=np.full((1, N, N), 0.0), dx=DX_M, dy=DX_M
    )
    catchment = CatchmentGeometry.from_geographic(geographic, crs=None)
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    return mesh, catchment, descent, run_basin(catchment, mesh, descent)


def test_synthetic_run_carries_the_domain_row_alone(tmp_path):
    _, _, descent, basin = synthetic_domain(tmp_path)
    write_descent_sidecar(descent, tmp_path, "flow", basin=basin)

    assert catchment_basin_the_build_left(tmp_path, n_cells=N * N) is None


def test_discharge_of_a_synthetic_domain_sums_the_whole_domain(tmp_path):
    mesh, catchment, _, basin = synthetic_domain(tmp_path)
    model = SimpleNamespace(
        model_name="flow",
        inputs=make_model(geometry=Geometry(cells=None, domain=None, catchment=catchment)),
        solver_mesh=mesh,
        descent_basin=basin,
    )

    np.testing.assert_array_equal(catchment_cell_mask(model), np.ones(N * N, dtype=bool))


# MODFLOW-NWT listing, rates in L3/T scaled to m3/s.

LISTING = """MODFLOW-NWT-SWR1
                     VOLUMETRIC BUDGET FOR ENTIRE MODEL AT END OF TIME STEP    1 IN STRESS PERIOD    1
  ---------------------------------------------------------------------------

     CUMULATIVE VOLUMES      L**3       RATES FOR THIS TIME STEP      L**3/T
     ------------------                 ------------------------

           IN:                                      IN:
           ---                                      ---
             STORAGE =           0.0000               STORAGE =           0.0000
       CONSTANT HEAD =           0.0000         CONSTANT HEAD =           0.0000
            RECHARGE =           1.0000              RECHARGE =           2.0000

            TOTAL IN =           1.0000              TOTAL IN =           2.0000

          OUT:                                     OUT:
          ----                                     ----
             STORAGE =           0.0000               STORAGE =           0.5000
       CONSTANT HEAD =           0.0000         CONSTANT HEAD =           1.5000
            RECHARGE =           0.0000              RECHARGE =           0.0000

           TOTAL OUT =           1.0000             TOTAL OUT =           2.0000

            IN - OUT =           0.0000              IN - OUT =           0.0000

 PERCENT DISCREPANCY =           0.00     PERCENT DISCREPANCY =           0.00

          TIME SUMMARY AT END OF TIME STEP    1 IN STRESS PERIOD    1
                    SECONDS     MINUTES      HOURS       DAYS        YEARS
                    -----------------------------------------------------------
   TIME STEP LENGTH  1.0000      1.66667E-02 2.77778E-04 1.15741E-05 3.16881E-08
 STRESS PERIOD TIME  1.0000      1.66667E-02 2.77778E-04 1.15741E-05 3.16881E-08
         TOTAL TIME  1.0000      1.66667E-02 2.77778E-04 1.15741E-05 3.16881E-08
"""


def test_mass_balance_reads_rates_and_scales_them(tmp_path):
    listing = tmp_path / "run.list"
    listing.write_text(LISTING, encoding="utf-8")
    store = RecordingStore()

    ModflowNwtOutputAdapter()._extract_mass_balance(
        "sim", store, listing, 1.0 / 86400.0, stamp_keys=[(0, 0)]
    )

    assert len(store.mass_balances) == 1
    record = store.mass_balances[0]
    assert record["timestep"] == 0
    assert record["total_in"] == pytest.approx(2.0 / 86400.0)
    assert record["total_out"] == pytest.approx(2.0 / 86400.0)
    assert record["storage_out"] == pytest.approx(0.5 / 86400.0)
    # PERCENT_DISCREPANCY has no unit and is not scaled.
    assert record["percent_error"] == pytest.approx(0.0)
    assert np.isfinite(record["percent_error"])


def test_unreadable_listing_fails_loudly(tmp_path):
    listing = tmp_path / "run.list"
    listing.write_text("not a MODFLOW listing", encoding="utf-8")

    with pytest.raises(ExtractError, match="mass balance"):
        ModflowNwtOutputAdapter()._extract_mass_balance(
            "sim", RecordingStore(), listing, 1.0, stamp_keys=[(0, 0)]
        )
