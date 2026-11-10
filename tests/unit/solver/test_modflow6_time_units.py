"""WP3 - MODFLOW 6 outputs are converted to m3/s using the TDIS time unit.

MF6 emits fluxes in length^3 per TDIS time unit. HydroModPy observations are
m3/s, so every flux is divided by ``seconds_per_time_unit``. Under TDIS SECONDS
the factor is exactly 1.0 (no double scaling); under DAYS it is 86400.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
import pandas as pd
import pytest
import zarr

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.time import SIMULATION_TIME_UNIT
from hydromodpy.core.units import to_modflow_itmuni
from hydromodpy.model.domain.geometry import CatchmentGeometry
from hydromodpy.model.model import Geometry, ModelTime
from hydromodpy.solver.modflow6 import Modflow6
from hydromodpy.solver.modflow6.builders.boundary_conditions import collapse_identical_periods
from hydromodpy.solver.modflow6.builders.period_forcing import sto_period_settings
from hydromodpy.solver.modflow6.builders.recharge import empty_recharge_aux
from hydromodpy.solver.modflow6.builders.solver_options import build_ats_perioddata
from hydromodpy.solver.modflow6.extractors.budget import extract_budget
from hydromodpy.solver.modflow6.extractors.flow import (
    Modflow6OutputAdapter,
    _read_start_datetime,
    _write_time_coordinate,
)
from hydromodpy.solver.modflow_common import calibration_extractors as cal
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_common.time_units import (
    TRACKING_TIME_UNIT,
    factor_to_tracking_unit,
    read_itmuni_from_dis,
    read_time_units_from_tdis,
    resolve_solver_time_unit,
    seconds_per_solver_time_unit,
)
from hydromodpy.solver.modflow_grid.discretization_temporal import (
    build_temporal_discretization_from_time_grid,
)
from hydromodpy.solver.modflow_nwt.extractors.modpath import ModpathOutputAdapter
from tests._helpers.model_factory import make_model, small_geometry
from tests.unit.solver.modflow_common.solver_runs import keep_all, retention, solved_run


class _FakeStore:
    sim_id = "sim"
    # No field store: the extractor records no budget policy.
    save_zarr = False

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.times = None
        self.fields: list = []
        self.budgets: list | None = None
        self.mass: list | None = None

    def run_dir_for(self, sim_id: str) -> Path:
        """The run folder the extractor writes ``final_state/`` in."""
        return self.run_dir

    def write_time(self, sim_id, values, *, epoch=None, calendar=None, units=None) -> None:
        self.times = np.asarray(values)
        self.time_units = units

    def write_field(self, sim_id, name, t, values, n_timesteps=None, subgroup=None) -> None:
        self.fields.append((name, t, np.asarray(values)))

    def write_field_stack(
        self, sim_id, name, values, *, n_timesteps=None, timestep_offset=0, subgroup=None
    ) -> None:
        for offset, row in enumerate(np.asarray(values)):
            self.fields.append((name, timestep_offset + offset, row))

    def write_budgets(self, sim_id, records) -> None:
        self.budgets = records

    def write_mass_balances(self, sim_id, records) -> None:
        self.mass = records


class _FakeHeadFile:
    def __init__(self, path, precision: str = "double") -> None:
        del path

    def get_times(self):
        return [1.0]

    def get_kstpkper(self):
        return [(0, 0)]

    def get_data(self, *, totim):
        del totim
        return np.array([[[5.0, 6.0, 7.0]]], dtype=float)

    def close(self) -> None:
        pass


def _fake_cbc_factory(records: dict[str, np.ndarray]):
    # This stand-in imitates hydromodpy's OWN cbc reader, which does expose
    # `records` / `read_record`. The drain fixture further down imitates
    # flopy's CellBudgetFile instead, which exposes `get_indices` /
    # `get_record`: the two readers have different APIs and a stand-in that
    # blurs them is how an invented method reaches production.
    from hydromodpy.solver.modflow6.extractors.cbc_reader import CbcRecord

    flat = list(records.items())

    class _FakeCBC:
        def __init__(self, path, *args, **kwargs):
            del path, args, kwargs
            self.records = tuple(
                CbcRecord(
                    kstp=1,
                    kper=1,
                    text=text,
                    imeth=1,
                    delt=1.0,
                    totim=1.0,
                    ndim1=2,
                    ndim2=1,
                    ndim3=-1,
                    nlist=0,
                    aux_names=(),
                    data_pos=0,
                )
                for text, _ in flat
            )

        def unique_record_names(self):
            return [text for text, _ in flat]

        def read_record(self, idx: int):
            return flat[idx][1]

        def close(self) -> None:
            pass

    return _FakeCBC


def test_seconds_per_time_unit_collapses_to_core_units(tmp_path: Path) -> None:
    # The MF6 extractor reads its TDIS unit with the shared reader: a missing,
    # blank or UNKNOWN unit is the launcher's seconds.
    tdis = tmp_path / "m.tdis"
    for token, seconds in (("SECONDS", 1.0), ("DAYS", 86400.0), ("UNKNOWN", 1.0)):
        tdis.write_text(f"BEGIN options\n  TIME_UNITS {token}\nEND options\n")
        assert seconds_per_solver_time_unit(tmp_path, "m") == seconds
    tdis.write_text("BEGIN options\nEND options\n")
    assert seconds_per_solver_time_unit(tmp_path, "m") == 1.0


def _run_extract(tmp_path: Path, monkeypatch, time_units: str, records: dict[str, np.ndarray]):
    monkeypatch.setattr("flopy.utils.binaryfile.HeadFile", _FakeHeadFile, raising=True)
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.extractors.cbc_reader.Mf6CellBudgetReader",
        _fake_cbc_factory(records),
        raising=True,
    )
    # The extractor finds the run by its .hds; the fake HeadFile never reads it.
    (tmp_path / "flow.hds").write_text("", encoding="utf-8")
    (tmp_path / "flow.cbc").write_text("", encoding="utf-8")
    (tmp_path / "flow.tdis").write_text(
        f"BEGIN OPTIONS\n  TIME_UNITS {time_units}\nEND OPTIONS\n", encoding="utf-8"
    )
    store = _FakeStore(tmp_path)
    Modflow6OutputAdapter().extract(solved_run(tmp_path), store, retention(BudgetKeep.of_terms(())))
    return store


def test_mf6_budget_flux_scaled_to_m3_per_s_under_days(tmp_path, monkeypatch) -> None:
    records = {
        "RCHA": np.array([86400.0, 0.0, 0.0]),
        "DRN": np.array([-86400.0, 0.0, 0.0]),
    }
    store = _run_extract(tmp_path, monkeypatch, "DAYS", records)
    by = {r["component"]: r for r in store.budgets}
    assert by["recharge"]["flux_in"] == pytest.approx(1.0)
    assert by["drain"]["flux_out"] == pytest.approx(1.0)

    store_s = _run_extract(tmp_path, monkeypatch, "SECONDS", records)
    by_s = {r["component"]: r for r in store_s.budgets}
    assert by_s["recharge"]["flux_in"] == pytest.approx(86400.0)


def test_mf6_budget_flux_seconds_is_identity(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.extractors.cbc_reader.Mf6CellBudgetReader",
        _fake_cbc_factory({"DRN": np.array([5.0, -5.0])}),
        raising=True,
    )
    store = _FakeStore(tmp_path)
    extract_budget(
        "sim",
        store,
        tmp_path / "flow.cbc",
        [1.0],
        [(0, 0)],
        budget_terms=BudgetKeep.of_terms(()),
        nlay=1,
        n_cells=2,
        seconds_per_time_unit=1.0,
    )
    assert store.budgets[0]["flux_in"] == pytest.approx(5.0)
    assert store.budgets[0]["flux_out"] == pytest.approx(5.0)


def test_mf6_mass_balance_extracts_storage_components(tmp_path, monkeypatch) -> None:
    dtype = np.dtype(
        [
            ("time_step", "<i4"),
            ("stress_period", "<i4"),
            ("tslen", "<f8"),
            ("TOTAL_IN", "<f8"),
            ("TOTAL_OUT", "<f8"),
            ("IN-OUT", "<f8"),
            ("PERCENT_DISCREPANCY", "<f8"),
            ("STO-SS_IN", "<f8"),
            ("STO-SY_IN", "<f8"),
            ("STO-SS_OUT", "<f8"),
            ("STO-SY_OUT", "<f8"),
        ]
    )
    inc = np.array(
        [(0, 0, 1.0, 174240.0, 174240.0, 0.0, 0.01, 864.0, 86400.0, 0.0, 43200.0)], dtype=dtype
    )

    class _FakeListBudget:
        def __init__(self, path, precision: str = "double") -> None:
            del path

        def get_budget(self):
            return inc, None

    monkeypatch.setattr("flopy.utils.Mf6ListBudget", _FakeListBudget, raising=True)
    store = _FakeStore(tmp_path)
    Modflow6OutputAdapter()._extract_mass_balance(
        "sim", store, tmp_path / "flow.lst", stamp_keys=[(0, 0)], seconds_per_time_unit=86400.0
    )
    rec = store.mass[0]
    assert rec["storage_in"] == pytest.approx(1.01)
    assert rec["storage_out"] == pytest.approx(0.5)
    assert rec["total_in"] == pytest.approx(2.0166667, rel=1e-6)
    # PERCENT_DISCREPANCY is unitless and must not be scaled.
    assert rec["percent_error"] == pytest.approx(0.01)


def _write_drain_cbc_fixtures(tmp_path: Path, monkeypatch) -> None:
    """A budget file read the way the real one is: by POSITION in the index.

    The extractor walks ``records`` once and calls ``read_record(idx)``. A
    stand-in offering only ``get_data(text=, kstpkper=, full3D=)`` would let the
    quadratic per-record lookup come back unnoticed, and that lookup is exactly
    what this path exists to avoid on a chronicle of a thousand steps.
    """

    class _FakeCBC:
        def __init__(self, path, precision: str = "double") -> None:
            del path
            # kstp / kper are 1-based on a record, 0-based from get_kstpkper().
            self.recordarray = np.array(
                [(1, 1, b"             DRN", 6, 1.0, 1.0)],
                dtype=[
                    ("kstp", "<i4"),
                    ("kper", "<i4"),
                    ("text", "S16"),
                    ("imeth", "<i4"),
                    ("delt", "<f8"),
                    ("totim", "<f8"),
                ],
            )

        def get_unique_record_names(self):
            return [b"DRN"]

        def get_times(self):
            return [1.0]

        def get_kstpkper(self):
            return [(0, 0)]

        def get_indices(self, text=None):
            del text
            # An ARRAY, like flopy: a tuple here would hide that `or ()` on the
            # result raises "truth value of an array is ambiguous".
            return np.array([0], dtype=np.int64)

        def get_record(self, idx, full3D=False):
            assert idx == 0 and not full3D
            return np.array([[-86400.0, 0.0, 0.0]], dtype=float)

        def close(self) -> None:
            pass

    monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", _FakeCBC, raising=True)
    (tmp_path / "flow.cbc").write_text("", encoding="utf-8")


def test_mf6_calibration_discharge_reads_time_unit_from_tdis(tmp_path, monkeypatch) -> None:
    _write_drain_cbc_fixtures(tmp_path, monkeypatch)
    # MF6: TDIS file with a different stem, DAYS, and NO .dis file.
    (tmp_path / "flow_gwf.tdis").write_text(
        "BEGIN OPTIONS\n  TIME_UNITS DAYS\nEND OPTIONS\n", encoding="utf-8"
    )
    series = cal.extract_discharge_from_cbc(tmp_path, "flow", catchment_mask=np.ones(3, dtype=bool))
    assert float(series.iloc[0]) == pytest.approx(1.0)


def test_mf6_calibration_tdis_takes_precedence_over_dis(tmp_path, monkeypatch) -> None:
    _write_drain_cbc_fixtures(tmp_path, monkeypatch)
    # TDIS says DAYS; the legacy .dis would say seconds. TDIS must win.
    (tmp_path / "flow.tdis").write_text(
        "BEGIN OPTIONS\n  TIME_UNITS DAYS\nEND OPTIONS\n", encoding="utf-8"
    )
    # NLAY NROW NCOL NPER ITMUNI LENUNI, then LAYCBD. ITMUNI=1, SECONDS.
    (tmp_path / "flow.dis").write_text("# DIS\n1 1 1 1 1 2\n0\n", encoding="utf-8")
    series = cal.extract_discharge_from_cbc(tmp_path, "flow", catchment_mask=np.ones(3, dtype=bool))
    assert float(series.iloc[0]) == pytest.approx(1.0)


def test_nwt_calibration_discharge_still_uses_dis_itmuni(tmp_path, monkeypatch) -> None:
    _write_drain_cbc_fixtures(tmp_path, monkeypatch)
    # NWT: ITMUNI=4 (DAYS) in .dis, NO .tdis file.
    (tmp_path / "model.cbc").write_text("", encoding="utf-8")
    # NLAY NROW NCOL NPER ITMUNI LENUNI, then LAYCBD. ITMUNI=4, DAYS.
    (tmp_path / "model.dis").write_text("# DIS\n1 1 1 1 4 2\n0\n", encoding="utf-8")

    class _FakeCBC:
        def __init__(self, path, precision: str = "double") -> None:
            del path
            self.recordarray = np.array(
                [(1, 1, b"             DRN", 6, 1.0, 1.0)],
                dtype=[
                    ("kstp", "<i4"),
                    ("kper", "<i4"),
                    ("text", "S16"),
                    ("imeth", "<i4"),
                    ("delt", "<f8"),
                    ("totim", "<f8"),
                ],
            )

        def get_unique_record_names(self):
            return [b"DRN"]

        def get_times(self):
            return [1.0]

        def get_kstpkper(self):
            return [(0, 0)]

        def get_indices(self, text=None):
            del text
            # An ARRAY, like flopy: a tuple here would hide that `or ()` on the
            # result raises "truth value of an array is ambiguous".
            return np.array([0], dtype=np.int64)

        def get_record(self, idx, full3D=False):
            assert idx == 0 and not full3D
            return np.array([[-86400.0, 0.0, 0.0]], dtype=float)

        def close(self) -> None:
            pass

    monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", _FakeCBC, raising=True)
    series = cal.extract_discharge_from_cbc(
        tmp_path, "model", catchment_mask=np.ones(3, dtype=bool)
    )
    assert float(series.iloc[0]) == pytest.approx(1.0)


def test_mf6_tdis_built_with_config_time_unit_and_start_date(tmp_path) -> None:
    # Mirror build.py: SECONDS time unit, perlen in seconds, calendar start.
    start = datetime(2020, 1, 1)
    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name="mf6")
    flopy.mf6.ModflowTdis(
        sim,
        nper=1,
        perioddata=[(86400.0, 2, 1.0)],
        time_units="seconds",
        start_date_time=start.isoformat(),
    )
    sim.write_simulation(silent=True)
    tdis_text = next(tmp_path.glob("*.tdis")).read_text(encoding="utf-8").upper()
    normalized = " ".join(tdis_text.split())
    assert "TIME_UNITS SECONDS" in normalized
    assert "START_DATE_TIME" in normalized
    assert "2020-01-01" in normalized


@pytest.mark.regression
@pytest.mark.slow
@pytest.mark.mf6
@pytest.mark.allow_subprocess
def test_mf6_transient_recharge_reads_back_m3_per_s(tmp_path) -> None:
    exe = str(ensure_solver_binary("mf6"))
    rate = 1.0e-7  # m/s
    cell_area = 100.0  # m2 (10 m x 10 m)
    ncol = 3
    # MF6 applies no recharge to the constant-head cell, so only ncol-1 cells
    # contribute to the RCHA budget inflow.
    expected_recharge_m3_s = rate * cell_area * (ncol - 1)

    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name=exe)
    flopy.mf6.ModflowTdis(
        sim,
        nper=2,
        perioddata=[(1.0, 1, 1.0), (8.64e4, 1, 1.0)],
        time_units="seconds",
        start_date_time=datetime(2020, 1, 1).isoformat(),
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True, newtonoptions=["NEWTON"])
    ims = flopy.mf6.ModflowIms(sim, complexity="MODERATE")
    sim.register_ims_package(ims, [gwf.name])
    flopy.mf6.ModflowGwfdis(
        gwf, nlay=1, nrow=1, ncol=ncol, delr=10.0, delc=10.0, top=10.0, botm=0.0
    )
    flopy.mf6.ModflowGwfic(gwf, strt=8.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0)
    flopy.mf6.ModflowGwfsto(
        gwf, sy=0.2, ss=1e-5, iconvert=1, steady_state={0: True}, transient={1: True}
    )
    flopy.mf6.ModflowGwfrcha(gwf, recharge=rate)
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: [[(0, 0, 0), 7.0]]})
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="flow.hds",
        budget_filerecord="flow.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    success, _ = sim.run_simulation(silent=True)
    assert success

    # The .tdis the extractor consumes declares SECONDS and the calendar start.
    tdis_text = " ".join(next(tmp_path.glob("*.tdis")).read_text(encoding="utf-8").upper().split())
    assert "TIME_UNITS SECONDS" in tdis_text
    assert "2020-01-01" in tdis_text

    # Drop the GRB so surface-elevation export stays out of this budget check.
    for grb in tmp_path.glob("*.grb"):
        grb.unlink()

    store = _FakeStore(tmp_path)
    Modflow6OutputAdapter().extract(solved_run(tmp_path), store, keep_all)

    by_component_inflow: dict[str, float] = {}
    for rec in store.budgets:
        by_component_inflow[rec["component"]] = max(
            by_component_inflow.get(rec["component"], 0.0), rec["flux_in"]
        )
    assert by_component_inflow["recharge"] == pytest.approx(expected_recharge_m3_s, rel=1e-6)

    # Storage exchanges water during the transient period (m3/s, non-zero).
    assert any(abs(r["storage_in"]) + abs(r["storage_out"]) > 0.0 for r in store.mass)


class TestTheDischargeSeriesIsTheCatchmentAndNotTheDomain:
    """A gauge closes a catchment. A buffered model domain is not one.

    Measured on the Nancon at 25 m on MODFLOW 6: 152.2 km2 of domain against
    64.6 km2 of catchment, 2.119 m3/s of drain outflow against 0.888 m3/s
    inside the basin. Scored unmasked, every discharge metric would be computed
    on 2.4 times the water the gauge sees, and it would look healthy.
    """

    def test_only_the_masked_cells_are_summed(self, tmp_path, monkeypatch) -> None:
        _write_drain_cbc_fixtures(tmp_path, monkeypatch)
        (tmp_path / "flow_gwf.tdis").write_text(
            "BEGIN OPTIONS\n  TIME_UNITS DAYS\nEND OPTIONS\n", encoding="utf-8"
        )
        # The fixture puts all the outflow on cell 0. Masking it out leaves zero.
        whole = cal.extract_discharge_from_cbc(
            tmp_path, "flow", catchment_mask=np.ones(3, dtype=bool)
        )
        without = cal.extract_discharge_from_cbc(
            tmp_path, "flow", catchment_mask=np.array([False, True, True])
        )

        assert float(whole.iloc[0]) == pytest.approx(1.0)
        assert float(without.iloc[0]) == pytest.approx(0.0)

    def test_a_mask_of_the_wrong_size_is_refused_by_name(self, tmp_path, monkeypatch) -> None:
        _write_drain_cbc_fixtures(tmp_path, monkeypatch)
        (tmp_path / "flow_gwf.tdis").write_text(
            "BEGIN OPTIONS\n  TIME_UNITS DAYS\nEND OPTIONS\n", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="not built for the same mesh"):
            cal.extract_discharge_from_cbc(tmp_path, "flow", catchment_mask=np.ones(7, dtype=bool))

    def test_an_empty_mask_is_refused_before_the_file_is_opened(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="holds no cell"):
            cal.extract_discharge_from_cbc(tmp_path, "flow", catchment_mask=np.zeros(3, dtype=bool))

    def test_a_model_without_basin_or_catchment_is_refused_by_name(self) -> None:

        from hydromodpy.solver.modflow_common.catchment_basin import catchment_cell_mask

        catchment = CatchmentGeometry.from_geographic(SimpleNamespace(watershed_shp=None), crs=None)
        model = SimpleNamespace(
            model_name="flow",
            descent_basin=None,
            inputs=make_model(geometry=Geometry(cells=None, domain=None, catchment=catchment)),
            solver_mesh=None,
        )
        with pytest.raises(ValueError, match="which water the gauge closes on"):
            catchment_cell_mask(model)


# Audit P0 - MF6 Zarr /time coordinate is absolute calendar time.
#
# The extractor must anchor the relative MF6 ``totim`` to the TDIS
# ``START_DATE_TIME`` so the CF ``/time`` axis decodes to real dates. Writing the
# relative totim under a 'seconds since 1970' label decodes ~33 years too early.


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


def _model_bound_to(regime: str) -> Modflow6:
    """A ``Modflow6`` holding a model with a mesh and a domain, and no time grid."""
    model = Modflow6(model_folder=".")
    model.inputs = make_model(
        geometry=replace(small_geometry(), domain=object()),
        time=ModelTime(grid=None, regime=regime, first_period_steady=True),
    )
    model._apply_preprocess_options(model.preprocess_options)
    return model


def test_modflow6_requires_canonical_time_grid_for_launcher_flow_preprocessing():
    model = _model_bound_to("transient")

    with pytest.raises(
        ValueError,
        match=r"preprocess_options\.time_grid derived from \[simulation\.time\] for transient flow runs",
    ):
        model._validate_pre_processing_inputs()


def test_modflow6_accepts_missing_time_grid_for_steady_launcher_flow_preprocessing():
    model = _model_bound_to("steady")

    # Steady flow should not require a time_grid; method must return None.
    assert model._validate_pre_processing_inputs() is None


# Adaptive time stepping must target the right period and respect NSTP.
#
# Two things go wrong silently here. FloPy converts the ``iper`` of an ATS record
# to 1-based when it writes the file, so a record built 1-based lands one period
# late and the last one falls off the end of the simulation. And MF6 ignores the
# TDIS NSTP of a period ATS covers, so an unbounded ``dtmax`` lets it grow the
# step back to the whole period, undoing the sub-stepping the run asked for.


def _records(*, nstp: list[int], steady: list[bool], perlen: float = 2678400.0):
    return build_ats_perioddata(
        perlen=np.full(len(nstp), perlen, dtype=float),
        nstp=np.asarray(nstp, dtype=int),
        steady=np.asarray(steady, dtype=bool),
        dtmin_s=1.0,
    )


def test_steady_periods_carry_no_record() -> None:
    records = _records(nstp=[1, 10, 10], steady=[True, False, False])

    assert [record[0] for record in records] == [1, 2]


def test_indices_are_zero_based_for_flopy(tmp_path: Path) -> None:
    """FloPy adds one; a 1-based record would shift every period and drop the last."""
    perlen = 2678400.0
    records = _records(nstp=[10, 10], steady=[False, False], perlen=perlen)
    assert [record[0] for record in records] == [0, 1]

    sim = flopy.mf6.MFSimulation(sim_name="s", sim_ws=str(tmp_path), exe_name="mf6")
    tdis = flopy.mf6.ModflowTdis(
        sim,
        nper=2,
        perioddata=[(perlen, 10, 1.0), (perlen, 10, 1.0)],
        time_units="seconds",
    )
    flopy.mf6.ModflowUtlats(tdis, maxats=len(records), perioddata=records)
    sim.write_simulation(silent=True)

    written = (tmp_path / "s.ats").read_text(encoding="utf-8").splitlines()
    start = written.index("BEGIN perioddata")
    ipers = [int(written[start + 1 + i].split()[0]) for i in range(len(records))]

    # The file MF6 reads is 1-based, and it names every declared period exactly once.
    assert ipers == [1, 2]


def test_ats_may_only_go_below_the_declared_step() -> None:
    perlen = 2678400.0
    (record,) = _records(nstp=[10], steady=[False], perlen=perlen)
    _iper, dt0, dtmin, dtmax, dtadj, dtfailadj = record

    declared = perlen / 10
    assert dt0 == pytest.approx(declared)
    # dtmax at perlen would let ATS grow back to a single step per period and
    # discard the sub-stepping the run declared.
    assert dtmax == pytest.approx(declared)
    assert dtmin == 1.0
    # No growth, but a failed solve is still cut.
    assert dtadj == 1.0
    assert dtfailadj > 1.0


def test_a_single_step_period_keeps_the_whole_period_as_its_step() -> None:
    perlen = 2678400.0
    (record,) = _records(nstp=[1], steady=[False], perlen=perlen)

    assert record[1] == pytest.approx(perlen)
    assert record[3] == pytest.approx(perlen)


# Sparse stress-period emission: MF6 repeats the last PERIOD block.
#
# Long daily chronicles pay FloPy's per-period block-header bookkeeping
# (quadratic in the number of provided periods), so the builders emit only
# change points: deduplicated recharge/EVT payloads, a single zero AUX block,
# and STO settings at steady/transient transitions.


def test_collapse_drops_consecutive_identical_arrays() -> None:
    a = np.full(4, 1.0)
    b = np.full(4, 2.0)
    spd = {0: a, 1: a.copy(), 2: b, 3: b.copy(), 4: a.copy()}
    collapsed = collapse_identical_periods(spd)
    assert sorted(collapsed) == [0, 2, 4]
    np.testing.assert_allclose(collapsed[4], a)


def test_collapse_keeps_list_payload_change_points() -> None:
    rows_a = [[0, 1, 2.0]]
    rows_b = [[0, 1, 3.0]]
    spd = {0: rows_a, 1: list(rows_a), 2: [], 3: [], 4: rows_b}
    collapsed = collapse_identical_periods(spd)
    assert sorted(collapsed) == [0, 2, 4]
    assert collapsed[2] == []


def test_collapse_always_keeps_first_period() -> None:
    spd = {0: np.zeros(3)}
    assert sorted(collapse_identical_periods(spd)) == [0]


def test_empty_recharge_aux_emits_single_period_block() -> None:
    model = SimpleNamespace(ncpl=5, nper=100)
    aux = empty_recharge_aux(model)
    assert sorted(aux) == [0]
    np.testing.assert_allclose(aux[0][0], np.zeros(5))


def test_sto_period_settings_emits_change_points_only() -> None:
    steady_state, transient = sto_period_settings([True, False, False, False])
    assert steady_state == {0: True}
    assert transient == {1: True}


def test_sto_period_settings_all_transient() -> None:
    steady_state, transient = sto_period_settings([False, False, False])
    assert steady_state == {}
    assert transient == {0: True}


def test_sto_period_settings_alternating_flags() -> None:
    steady_state, transient = sto_period_settings([False, True, True, False])
    assert steady_state == {1: True}
    assert transient == {0: True, 3: True}


# The time unit a run declares must be the one it was built in.
#
# A launcher run is built in SI seconds. If the MODFLOW declaration, the value
# the extractors read back, or the tracking clock disagrees with that by one
# step, every flux or travel time it touches is off by a factor 86400 and
# nothing raises. These tests pin the three places that could drift.


class _ZarrHandle:
    def __init__(self, path: Path):
        self.root = zarr.open_group(str(path), mode="a")

    def close(self) -> None:
        pass


class _Store:
    sim_id = "sim_mp"

    def __init__(self, root: Path):
        self.root = root

    def open_zarr(self, sim_id: str) -> _ZarrHandle:
        return _ZarrHandle(self.root / f"{sim_id}.zarr")


class _TimeGrid:
    period_lengths_seconds = (86400.0, 86400.0)
    nstp_per_period = 1
    window = None


def _write_tdis(directory: Path, token: str) -> None:
    (directory / "case.tdis").write_text(
        f"BEGIN options\n  TIME_UNITS  {token}\nEND options\n", encoding="utf-8"
    )


def _write_dis(directory: Path, model_name: str, itmuni: int) -> None:
    """Write the header FloPy emits: a comment, NLAY NROW NCOL NPER ITMUNI LENUNI, LAYCBD."""
    (directory / f"{model_name}.dis").write_text(
        f"# DIS package for MODFLOW-2005 generated by Flopy\n"
        f"         1         2         2         1         {itmuni}         2\n"
        f"  0\n",
        encoding="utf-8",
    )


def test_temporal_result_states_one_unit_in_both_forms() -> None:
    result = build_temporal_discretization_from_time_grid(
        time_grid=_TimeGrid(), flow_regime="transient"
    )

    assert result.time_units == SIMULATION_TIME_UNIT
    assert result.itmuni == to_modflow_itmuni(result.time_units)


def test_undeclared_unit_resolves_to_the_launcher_unit(tmp_path: Path) -> None:
    # No TDIS, no DIS: the caller must not silently get days.
    assert resolve_solver_time_unit(tmp_path, "case") == SIMULATION_TIME_UNIT
    assert seconds_per_solver_time_unit(tmp_path, "case") == 1.0


def test_unknown_tdis_token_resolves_to_the_launcher_unit(tmp_path: Path) -> None:
    _write_tdis(tmp_path, "UNKNOWN")

    assert resolve_solver_time_unit(tmp_path, "case") == SIMULATION_TIME_UNIT


@pytest.mark.parametrize(("token", "expected"), [("SECONDS", 1.0), ("DAYS", 86400.0)])
def test_tdis_declaration_wins(tmp_path: Path, token: str, expected: float) -> None:
    _write_tdis(tmp_path, token)

    assert read_time_units_from_tdis(tmp_path / "case.tdis") == token
    assert seconds_per_solver_time_unit(tmp_path, "case") == expected


def test_nwt_falls_back_to_the_dis_itmuni(tmp_path: Path) -> None:
    _write_dis(tmp_path, "flow", itmuni=4)

    assert read_itmuni_from_dis(tmp_path / "flow.dis") == 4
    assert resolve_solver_time_unit(tmp_path, "flow") == "days"


def test_modpath_stores_the_tracking_unit_it_declares(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    _write_dis(output_dir, "flow", itmuni=to_modflow_itmuni(SIMULATION_TIME_UNIT))
    (output_dir / "flow.mppth").write_text("", encoding="utf-8")

    particle = np.zeros(2, dtype=[("x", "f8"), ("y", "f8"), ("z", "f8"), ("time", "f8")])
    particle["time"] = [0.0, 172800.0]

    class _FakePathlineFile:
        def __init__(self, path: str) -> None:
            del path

        def get_alldata(self):
            return [particle]

    monkeypatch.setattr("flopy.utils.PathlineFile", _FakePathlineFile)
    store = _Store(tmp_path / "catalog")

    ModpathOutputAdapter().extract(solved_run(output_dir), store, keep_all)

    handle = store.open_zarr("sim_mp")
    try:
        time = np.asarray(handle.root["particles/time"])
        attrs = dict(handle.root["particles"].attrs)
    finally:
        handle.close()

    # A MODFLOW-NWT run built in seconds: 172800 s is 2 days, not 172800 days.
    assert attrs["time_units"] == TRACKING_TIME_UNIT
    assert np.allclose(time[0], [0.0, 2.0])


def test_tracking_factor_is_the_inverse_of_a_day() -> None:
    assert factor_to_tracking_unit(SIMULATION_TIME_UNIT) == pytest.approx(1.0 / 86400.0)
    assert factor_to_tracking_unit(TRACKING_TIME_UNIT) == 1.0
