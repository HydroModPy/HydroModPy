"""The soil reservoir's recharge and unmet ETP reach a real MODFLOW 6 model.

A 2x2 SAFRAN grid of 100 m cells sits over a structured 10x10 model of 20 m
cells, so each quarter of the model shares one SAFRAN column. ``compute_soil_
forcings`` turns synthetic precipitation and ETP into a recharge and a
residual-ETP grid; ``resolve_deferred_heterogeneous_recharge`` and
``build_soil_evta_payload`` discretize them onto the model, exactly as
``build.py`` does, and a real MF6 run reads them back through RCHA and EVTA.

Two identities, checked without going through the production discretization
a second time (nearest-neighbour mapping computed here, by hand):

- per period, the RCHA budget sums to the area-weighted recharge of the
  nearest SAFRAN cell (row 84 of ``tests/TOLERANCES.md``);
- per cell and period, EVTA never draws more than the soil's residual ETP
  allows (row 85).

The global water-budget closure (row 2) and the CHD cell (whose stress-flux
budget MODFLOW 6 always reports as zero) round out the check.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts import FieldRecord, LoadResult
from hydromodpy.physics.flow.sinks_sources import FlowRechargeConfig
from hydromodpy.physics.flow.structure_binders import apply_etp_load_result_to_flow
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.simulation.soil_recharge import compute_soil_forcings
from hydromodpy.solver.modflow6.builders import (
    bind_recharge_from_flow,
    bind_soil_etp_from_flow,
    build_soil_evta_payload,
    externalize_recharge_spd,
    recharge_to_spd,
    resolve_deferred_heterogeneous_recharge,
    resolve_deferred_soil_etp,
)
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_common.flow_adapter_helpers import last_percent_discrepancy
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.tolerances import tol

_MM_DAY_TO_M_S = 1.0 / 86_400_000.0
_MODEL_NAME = "soilrch"
_NPER = 120
_NROW = _NCOL = 10
_DX = _DY = 20.0
_CELL_AREA_M2 = _DX * _DY
_TOP_M = 10.0
_CHD_HEAD_M = 5.0
_CHD_NODE_FLAT = 0  # (row 0, col 0): the model corner.
_CRS = "EPSG:2154"
_SAFRAN_X = np.array([50.0, 150.0])
_SAFRAN_Y = np.array([50.0, 150.0])
# Every-other-day rain, one distinct rate per SAFRAN cell so a mis-mapped
# column shows up as a wrong period sum. Cell (1, 0) rains less than it
# evaporates, on average, so it dries down and exercises the EVTA path.
_RAIN_MM_DAY = {(0, 0): 5.0, (0, 1): 8.0, (1, 0): 3.0, (1, 1): 10.0}
_ETP_MM_DAY = 2.0

_RCHA_TOL = tol("soil_recharge_into_mf6_rcha__per_period_sum_q_rch_sum_pe_a_sum_pe_a")
_EVTA_TOL = tol("soil_unmet_etp_into_mf6_evta__per_cell_and_period_q_evt_etpres_a_etpres_a")
_BUDGET_CLOSURE_FRACTION = tol("global_water_budget_closure__relative_error_in_out_in")


class _FakeFlow:
    """The slice of ``Flow`` the MF6 builders read: active sinks and their payloads."""

    def __init__(self) -> None:
        self.active_sinks_sources = ["recharge", "etp"]
        self.sinks_sources: dict[str, object] = {}

    def set_recharge(self, cfg: object) -> None:
        self.sinks_sources["recharge"] = cfg

    def set_etp(self, cfg: object) -> None:
        self.sinks_sources["etp"] = cfg


def _days() -> pd.DatetimeIndex:
    return pd.date_range("2001-01-01", periods=_NPER, freq="D")


def _grid_values(rates: dict[tuple[int, int], float]) -> np.ndarray:
    """(T, 2, 2) mm/day, ``rates`` every other day, zero the days between."""
    arr = np.zeros((_NPER, 2, 2))
    for (iy, ix), rate in rates.items():
        arr[0::2, iy, ix] = rate
    return arr


def _field_record(name: str, values: np.ndarray, days: pd.DatetimeIndex) -> FieldRecord:
    dataset = xr.Dataset(
        {name: (("time", "y", "x"), values)},
        coords={"time": days.values, "y": _SAFRAN_Y, "x": _SAFRAN_X},
    )
    return FieldRecord(
        variable=name,
        source="test",
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, float(_NCOL * _DX), float(_NROW * _DY)),
        crs=_CRS,
        date_start=pd.Timestamp(days[0]),
        date_end=pd.Timestamp(days[-1]),
        frequency="D",
        metadata={"array_name": name},
    )


def _window(days: pd.DatetimeIndex) -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp(days[0]),
        end=pd.Timestamp(days[-1]),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )


def _mesh() -> SolverMesh:
    top = np.full((_NROW, _NCOL), _TOP_M)
    botm = np.zeros((1, _NROW, _NCOL))
    return SolverMesh.from_structured_arrays(
        nrow=_NROW, ncol=_NCOL, top=top, botm=botm, dx=_DX, dy=_DY
    )


def _nearest_safran_index(model_centers: np.ndarray, safran_centers: np.ndarray) -> np.ndarray:
    """Index of the closest SAFRAN cell centre, one per model row or column."""
    return np.array([int(np.argmin(np.abs(c - safran_centers))) for c in model_centers])


def _compute_soil():
    days = _days()
    precipitation = LoadResult(
        fields=[_field_record("precipitation", _grid_values(_RAIN_MM_DAY), days)]
    )
    etp = LoadResult(fields=[_field_record("etp", np.full((_NPER, 2, 2), _ETP_MM_DAY), days)])
    config = SoilReservoirConfig(ru=20.0, spinup="none")
    window = _window(days)
    soil = compute_soil_forcings(
        precipitation=precipitation, etp=etp, config=config, window=window, model_crs=_CRS
    )
    return soil, window


def _build_and_run(ws: Path):
    """Build the flopy model from the production builders and run it, in ``ws``.

    Returns the nearest-SAFRAN row and column indices for the manual
    comparison, and ``soil`` itself: the caller reads the run's own files.
    """
    import flopy

    soil, window = _compute_soil()
    mesh = _mesh()

    fake_flow = _FakeFlow()
    apply_etp_load_result_to_flow(
        flow=fake_flow,
        etp_result=soil.residual_etp,
        simulation_window=window,
        from_soil_reservoir=True,
    )
    fake_flow.sinks_sources["recharge"] = FlowRechargeConfig(
        values=0.0, heterogeneous_source=soil.recharge, interpolation_method="nearest"
    )

    model = SimpleNamespace(
        flow=fake_flow,
        recharge=None,
        first_clim=None,
        nper=_NPER,
        ncpl=_NROW * _NCOL,
        steady=np.zeros(_NPER, dtype=bool),
        time_grid=SimpleNamespace(window=window),
        solver_mesh=mesh,
        model_name_mf6=_MODEL_NAME,
        drain_band_depth_m=0.0,
    )

    bind_recharge_from_flow(model)
    resolve_deferred_heterogeneous_recharge(model)
    bind_soil_etp_from_flow(model)
    resolve_deferred_soil_etp(model)
    evta = build_soil_evta_payload(
        model,
        mesh,
        ocean_support_mask=np.zeros(model.ncpl, dtype=bool),
        stream_support_mask=np.zeros(model.ncpl, dtype=bool),
        lake_cell_ids=[],
        drain_active=True,
        shared_dir=None,
    )
    assert evta is not None
    evta_rate, evta_surface, evta_depth = evta

    rcha_spd = recharge_to_spd(model)
    rcha_payload = externalize_recharge_spd(
        rcha_spd, basename=_MODEL_NAME, shared_dir=None, package="rcha"
    )
    for record in rcha_payload.values():
        record["data"] = np.asarray(record["data"]).reshape(_NROW, _NCOL)
    for record in evta_rate.values():
        record["data"] = np.asarray(record["data"]).reshape(_NROW, _NCOL)

    exe = str(ensure_solver_binary("mf6"))
    ws.mkdir(parents=True, exist_ok=True)
    sim = flopy.mf6.MFSimulation(sim_name=_MODEL_NAME, sim_ws=str(ws), exe_name=exe)
    flopy.mf6.ModflowTdis(
        sim, time_units="seconds", nper=_NPER, perioddata=[(86_400.0, 1, 1.0)] * _NPER
    )
    flopy.mf6.ModflowIms(sim, complexity="MODERATE", outer_maximum=200, inner_maximum=200)
    gwf = flopy.mf6.ModflowGwf(sim, modelname=_MODEL_NAME, save_flows=True)
    flopy.mf6.ModflowGwfdis(
        gwf, nlay=1, nrow=_NROW, ncol=_NCOL, delr=_DX, delc=_DY, top=_TOP_M, botm=0.0
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0e-4, save_specific_discharge=True)
    flopy.mf6.ModflowGwfic(gwf, strt=_CHD_HEAD_M)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=0.1, ss=1.0e-5, transient={0: True})
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=[[(0, 0, 0), _CHD_HEAD_M]])
    drain_cells = [
        (0, r, c) for r in range(_NROW) for c in range(_NCOL) if r * _NCOL + c != _CHD_NODE_FLAT
    ]
    flopy.mf6.ModflowGwfdrn(
        gwf, stress_period_data=[[cid, _TOP_M - 0.5, 1.0e-3] for cid in drain_cells]
    )
    flopy.mf6.ModflowGwfrcha(gwf, recharge=rcha_payload, pname="RCHA")
    flopy.mf6.ModflowGwfevta(
        gwf,
        surface=evta_surface.reshape(_NROW, _NCOL),
        rate=evta_rate,
        depth=float(evta_depth),
        pname="EVTA",
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{_MODEL_NAME}.hds",
        budget_filerecord=f"{_MODEL_NAME}.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    success, _buff = sim.run_simulation(silent=True)
    assert success, "soil-recharge MF6 run did not converge"

    iy_nearest = _nearest_safran_index(np.arange(_NROW) * _DY + _DY / 2.0, _SAFRAN_Y)
    ix_nearest = _nearest_safran_index(np.arange(_NCOL) * _DX + _DX / 2.0, _SAFRAN_X)
    return iy_nearest, ix_nearest, soil


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_the_rcha_budget_sums_to_the_nearest_safran_cells_recharge(tmp_path: Path) -> None:
    iy_nearest, ix_nearest, soil = _build_and_run(tmp_path)
    recharge_mm_day = soil.recharge.fields[0].data["recharge"].values  # (T, 2, 2)
    expected_grid = recharge_mm_day[:, iy_nearest[:, None], ix_nearest[None, :]]
    expected_flat = expected_grid.reshape(_NPER, _NROW * _NCOL)
    # MF6 reports zero RCH flux at a constant-head cell (the entire cell
    # balance is absorbed by CHD): exclude it to match what the budget holds.
    expected_flat[:, _CHD_NODE_FLAT] = 0.0
    expected_m3s = expected_flat.sum(axis=1) * _CELL_AREA_M2 * _MM_DAY_TO_M_S

    import flopy

    cbc = flopy.utils.CellBudgetFile(str(tmp_path / f"{_MODEL_NAME}.cbc"))
    for kper in range(_NPER):
        record = cbc.get_data(text="RCH", kstpkper=(0, kper))[0]
        actual_m3s = float(np.sum(record["q"]))
        assert actual_m3s == pytest.approx(float(expected_m3s[kper]), rel=_RCHA_TOL, abs=1.0e-15), (
            f"period {kper}"
        )


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_the_evta_rate_never_exceeds_the_soils_residual_etp(tmp_path: Path) -> None:
    iy_nearest, ix_nearest, soil = _build_and_run(tmp_path)
    residual_mm_day = soil.residual_etp.fields[0].data["etp"].values  # (T, 2, 2)
    expected_grid = residual_mm_day[:, iy_nearest[:, None], ix_nearest[None, :]]
    expected_flat_m3s = expected_grid.reshape(_NPER, _NROW * _NCOL) * _CELL_AREA_M2 * _MM_DAY_TO_M_S
    assert np.any(expected_flat_m3s > 0.0), "the dry SAFRAN cell must leave some ETP unmet"

    import flopy

    cbc = flopy.utils.CellBudgetFile(str(tmp_path / f"{_MODEL_NAME}.cbc"))
    for kper in range(_NPER):
        record = cbc.get_data(text="EVT", kstpkper=(0, kper))[0]
        drawn_m3s = -np.asarray(record["q"], dtype=float)
        allowed_m3s = expected_flat_m3s[kper] * (1.0 + _EVTA_TOL)
        assert np.all(drawn_m3s <= allowed_m3s), f"period {kper}"


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_the_model_budget_closes(tmp_path: Path) -> None:
    _build_and_run(tmp_path)
    discrepancy = last_percent_discrepancy(tmp_path)
    assert discrepancy is not None
    assert abs(discrepancy) / 100.0 <= _BUDGET_CLOSURE_FRACTION
