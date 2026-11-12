"""Time unit of MODFLOW 6 and MODFLOW-NWT runs, and the flux scaling it drives.

A launcher run is built in seconds. MF6 writes fluxes per TDIS time unit, so the
extractors divide by seconds per unit (1 for SECONDS, 86400 for DAYS) to get
m3/s. NWT declares its unit in the DIS file (ITMUNI, 4 is days). The tracking
clock is in days, so a pathline time of 172800 s reads 2 days.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
import pandas as pd
import pytest
import zarr

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.time.window import SIMULATION_TIME_UNIT
from hydromodpy.core.units.time import to_modflow_itmuni
from hydromodpy.model.domain.geometry import CatchmentGeometry
from hydromodpy.model.model import Geometry
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
from tests._helpers.model_factory import make_model
from tests.unit.solver.modflow_common.solver_runs import keep_all, retention, solved_run

MASK_ALL = np.ones(3, dtype=bool)
START_2003_S = int(pd.Timestamp("2003-01-01T00:00:00Z").timestamp())
TOTIM_S = [2592000.0, 5184000.0, 7776000.0]  # 30, 60 and 90 days


def tdis_text(options):
    return f"BEGIN OPTIONS\n{options}END OPTIONS\n"


def dis_text(itmuni):
    """The FloPy header: a comment, NLAY NROW NCOL NPER ITMUNI LENUNI, then LAYCBD."""
    return f"# DIS\n1 1 1 1 {itmuni} 2\n0\n"


class FakeStore:
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


class FakeHeadFile:
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


def fake_cbc_factory(records: dict[str, np.ndarray]):
    # This stand-in imitates hydromodpy's OWN cbc reader, which does expose
    # `records` / `read_record`. The drain fixture further down imitates
    # flopy's CellBudgetFile instead, which exposes `get_indices` /
    # `get_record`: the two readers have different APIs and a stand-in that
    # blurs them is how an invented method reaches production.
    from hydromodpy.solver.modflow6.extractors.cbc_reader import CbcRecord

    flat = list(records.items())

    class FakeCBC:
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

    return FakeCBC


def run_extract(tmp_path, monkeypatch, time_units, records):
    monkeypatch.setattr("flopy.utils.binaryfile.HeadFile", FakeHeadFile, raising=True)
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.extractors.cbc_reader.Mf6CellBudgetReader",
        fake_cbc_factory(records),
        raising=True,
    )
    # The extractor finds the run by its .hds; the fake HeadFile never reads it.
    (tmp_path / "flow.hds").write_text("", encoding="utf-8")
    (tmp_path / "flow.cbc").write_text("", encoding="utf-8")
    (tmp_path / "flow.tdis").write_text(tdis_text(f"  TIME_UNITS {time_units}\n"), encoding="utf-8")
    store = FakeStore(tmp_path)
    Modflow6OutputAdapter().extract(solved_run(tmp_path), store, retention(BudgetKeep.of_terms(())))
    return store


def write_drain_cbc(tmp_path: Path, monkeypatch) -> None:
    """A budget file read the way the real one is: by POSITION in the index.

    The extractor walks ``records`` once and calls ``read_record(idx)``. A
    stand-in offering only ``get_data(text=, kstpkper=, full3D=)`` would let the
    quadratic per-record lookup come back unnoticed, and that lookup is exactly
    what this path exists to avoid on a chronicle of a thousand steps.
    """

    class FakeCBC:
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

    monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", FakeCBC, raising=True)
    (tmp_path / "flow.cbc").write_text("", encoding="utf-8")


class CaptureStore:
    def __init__(self):
        self.calls = []

    def write_time(self, sim_id, values, *, epoch=None, calendar=None, units=None):
        self.calls.append({"values": np.asarray(values, dtype="int64"), "units": units})


class ZarrHandle:
    def __init__(self, path):
        self.root = zarr.open_group(str(path), mode="a")

    def close(self):
        pass


class ZarrStore:
    sim_id = "sim_mp"

    def __init__(self, root):
        self.root = root

    def open_zarr(self, sim_id):
        return ZarrHandle(self.root / f"{sim_id}.zarr")


class TwoDayGrid:
    period_lengths_seconds = (86400.0, 86400.0)
    nstp_per_period = 1
    window = None


TDIS_UNITS = [
    pytest.param("  TIME_UNITS SECONDS\n", 1.0, id="seconds"),
    pytest.param("  TIME_UNITS DAYS\n", 86400.0, id="days"),
    pytest.param("  TIME_UNITS UNKNOWN\n", 1.0, id="unknown token"),
    pytest.param("", 1.0, id="no unit"),
]


@pytest.mark.parametrize(("options", "seconds"), TDIS_UNITS)
def test_seconds_per_solver_time_unit(tmp_path, options, seconds):
    (tmp_path / "case.tdis").write_text(tdis_text(options), encoding="utf-8")

    assert seconds_per_solver_time_unit(tmp_path, "case") == seconds


@pytest.mark.parametrize("token", ["SECONDS", "DAYS"])
def test_tdis_declaration_is_read(tmp_path, token):
    (tmp_path / "case.tdis").write_text(tdis_text(f"  TIME_UNITS {token}\n"), encoding="utf-8")

    assert read_time_units_from_tdis(tmp_path / "case.tdis") == token


def test_undeclared_unit_is_launcher_unit(tmp_path):
    # No TDIS and no DIS: the caller must not silently get days.
    assert resolve_solver_time_unit(tmp_path, "case") == SIMULATION_TIME_UNIT
    assert seconds_per_solver_time_unit(tmp_path, "case") == 1.0


def test_unknown_tdis_token_is_launcher_unit(tmp_path):
    (tmp_path / "case.tdis").write_text(tdis_text("  TIME_UNITS UNKNOWN\n"), encoding="utf-8")

    assert resolve_solver_time_unit(tmp_path, "case") == SIMULATION_TIME_UNIT


def test_nwt_unit_comes_from_dis(tmp_path):
    (tmp_path / "flow.dis").write_text(dis_text(4), encoding="utf-8")

    assert read_itmuni_from_dis(tmp_path / "flow.dis") == 4
    assert resolve_solver_time_unit(tmp_path, "flow") == "days"


def test_temporal_result_states_one_unit():
    result = build_temporal_discretization_from_time_grid(
        time_grid=TwoDayGrid(), flow_regime="transient"
    )

    assert result.time_units == SIMULATION_TIME_UNIT
    assert result.itmuni == to_modflow_itmuni(result.time_units)


@pytest.mark.parametrize(
    ("unit", "factor"),
    [(SIMULATION_TIME_UNIT, 1.0 / 86400.0), (TRACKING_TIME_UNIT, 1.0)],
    ids=["seconds to days", "days to days"],
)
def test_factor_to_tracking_unit(unit, factor):
    assert factor_to_tracking_unit(unit) == pytest.approx(factor)


def test_tdis_written_with_unit_and_start(tmp_path):
    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name="mf6")
    flopy.mf6.ModflowTdis(
        sim,
        nper=1,
        perioddata=[(86400.0, 2, 1.0)],
        time_units="seconds",
        start_date_time=datetime(2020, 1, 1).isoformat(),
    )
    sim.write_simulation(silent=True)

    text = " ".join(next(tmp_path.glob("*.tdis")).read_text(encoding="utf-8").upper().split())

    assert "TIME_UNITS SECONDS" in text
    assert "START_DATE_TIME" in text
    assert "2020-01-01" in text


def test_budget_flux_in_m3_per_s(tmp_path, monkeypatch):
    # 86400 m3/day is 1 m3/s.
    records = {"RCHA": np.array([86400.0, 0.0, 0.0]), "DRN": np.array([-86400.0, 0.0, 0.0])}

    days = {r["component"]: r for r in run_extract(tmp_path, monkeypatch, "DAYS", records).budgets}
    seconds = {
        r["component"]: r for r in run_extract(tmp_path, monkeypatch, "SECONDS", records).budgets
    }

    assert days["recharge"]["flux_in"] == pytest.approx(1.0)
    assert days["drain"]["flux_out"] == pytest.approx(1.0)
    assert seconds["recharge"]["flux_in"] == pytest.approx(86400.0)


def test_budget_flux_unchanged_in_seconds(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.extractors.cbc_reader.Mf6CellBudgetReader",
        fake_cbc_factory({"DRN": np.array([5.0, -5.0])}),
        raising=True,
    )
    store = FakeStore(tmp_path)

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


def test_mass_balance_storage(tmp_path, monkeypatch):
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
    # Volumes in m3 over one day, so the factor to m3/s is 1/86400.
    inc = np.array(
        [(0, 0, 1.0, 174240.0, 174240.0, 0.0, 0.01, 864.0, 86400.0, 0.0, 43200.0)], dtype=dtype
    )

    class FakeListBudget:
        def __init__(self, path, precision="double"):
            del path

        def get_budget(self):
            return inc, None

    monkeypatch.setattr("flopy.utils.Mf6ListBudget", FakeListBudget, raising=True)
    store = FakeStore(tmp_path)

    Modflow6OutputAdapter()._extract_mass_balance(
        "sim", store, tmp_path / "flow.lst", stamp_keys=[(0, 0)], seconds_per_time_unit=86400.0
    )

    rec = store.mass[0]
    assert rec["storage_in"] == pytest.approx(1.01)
    assert rec["storage_out"] == pytest.approx(0.5)
    assert rec["total_in"] == pytest.approx(2.0166667, rel=1e-6)
    # PERCENT_DISCREPANCY has no unit and is not scaled.
    assert rec["percent_error"] == pytest.approx(0.01)


# Files written beside the budget file, the model name and the discharge in m3/s.
# The fake budget holds 86400 m3 per time unit on cell 0.
DISCHARGE_FILES = [
    pytest.param(
        {"flow_gwf.tdis": tdis_text("  TIME_UNITS DAYS\n")}, "flow", id="mf6 tdis, no dis"
    ),
    pytest.param(
        {"flow.tdis": tdis_text("  TIME_UNITS DAYS\n"), "flow.dis": dis_text(1)},
        "flow",
        id="tdis days wins over dis seconds",
    ),
    pytest.param({"model.cbc": "", "model.dis": dis_text(4)}, "model", id="nwt dis days"),
]


@pytest.mark.parametrize(("files", "name"), DISCHARGE_FILES)
def test_calibration_discharge_unit(tmp_path, monkeypatch, files, name):
    write_drain_cbc(tmp_path, monkeypatch)
    for filename, text in files.items():
        (tmp_path / filename).write_text(text, encoding="utf-8")

    series = cal.extract_discharge_from_cbc(tmp_path, name, catchment_mask=MASK_ALL)

    assert float(series.iloc[0]) == pytest.approx(1.0)


# A gauge closes a catchment, a buffered model domain is not one. On the Nancon at
# 25 m on MODFLOW 6 the domain is 152.2 km2 and the catchment 64.6 km2, so an unmasked
# discharge would score 2.4 times the water the gauge sees.


def test_discharge_sums_masked_cells(tmp_path, monkeypatch):
    write_drain_cbc(tmp_path, monkeypatch)
    (tmp_path / "flow_gwf.tdis").write_text(tdis_text("  TIME_UNITS DAYS\n"), encoding="utf-8")

    # The fixture puts all the outflow on cell 0. Masking it out leaves zero.
    whole = cal.extract_discharge_from_cbc(tmp_path, "flow", catchment_mask=MASK_ALL)
    without = cal.extract_discharge_from_cbc(
        tmp_path, "flow", catchment_mask=np.array([False, True, True])
    )

    assert float(whole.iloc[0]) == pytest.approx(1.0)
    assert float(without.iloc[0]) == pytest.approx(0.0)


def test_mask_of_wrong_size_refused(tmp_path, monkeypatch):
    write_drain_cbc(tmp_path, monkeypatch)
    (tmp_path / "flow_gwf.tdis").write_text(tdis_text("  TIME_UNITS DAYS\n"), encoding="utf-8")

    with pytest.raises(ValueError, match="not built for the same mesh"):
        cal.extract_discharge_from_cbc(tmp_path, "flow", catchment_mask=np.ones(7, dtype=bool))


def test_empty_mask_refused_before_reading(tmp_path):
    with pytest.raises(ValueError, match="holds no cell"):
        cal.extract_discharge_from_cbc(tmp_path, "flow", catchment_mask=np.zeros(3, dtype=bool))


def test_model_without_catchment_refused():
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


# The relative MF6 totim is anchored to the TDIS START_DATE_TIME, or to the start the
# launcher passes, so the /time axis decodes to real dates. Without any anchor it is
# written relative to the 1970 epoch.
TIME_AXES = [
    pytest.param(
        "  START_DATE_TIME 2003-01-01T00:00:00\n",
        None,
        [START_2003_S + int(t) for t in TOTIM_S],
        id="start in the tdis",
    ),
    pytest.param(
        "",
        "2003-01-01T00:00:00",
        [START_2003_S + int(t) for t in TOTIM_S],
        id="start from the launcher",
    ),
    pytest.param("", None, [int(t) for t in TOTIM_S], id="no anchor"),
]


@pytest.mark.parametrize(("options", "launcher_start", "epoch_s"), TIME_AXES)
def test_time_coordinate_anchor(tmp_path, options, launcher_start, epoch_s):
    tdis = tmp_path / "model.tdis"
    tdis.write_text(tdis_text("  TIME_UNITS SECONDS\n" + options), encoding="utf-8")
    store = CaptureStore()

    _write_time_coordinate(store, "sim", TOTIM_S, "SECONDS", tdis, launcher_start)

    (call,) = store.calls
    np.testing.assert_array_equal(call["values"], epoch_s)
    assert "1970-01-01" in str(call["units"])
    assert (_read_start_datetime(tdis) is None) == (not options)


def test_time_coordinate_decodes_to_2003(tmp_path):
    tdis = tmp_path / "model.tdis"
    tdis.write_text(
        tdis_text("  TIME_UNITS SECONDS\n  START_DATE_TIME 2003-01-01T00:00:00\n"), encoding="utf-8"
    )
    store = CaptureStore()

    _write_time_coordinate(store, "sim", TOTIM_S, "SECONDS", tdis)

    decoded = pd.to_datetime(store.calls[0]["values"], unit="s", utc=True)
    assert decoded[0] == pd.Timestamp("2003-01-31T00:00:00Z")
    assert decoded[-1] == pd.Timestamp("2003-04-01T00:00:00Z")


def test_modpath_stores_tracking_unit(tmp_path, monkeypatch):
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    (output_dir / "flow.dis").write_text(
        dis_text(to_modflow_itmuni(SIMULATION_TIME_UNIT)), encoding="utf-8"
    )
    (output_dir / "flow.mppth").write_text("", encoding="utf-8")

    particle = np.zeros(2, dtype=[("x", "f8"), ("y", "f8"), ("z", "f8"), ("time", "f8")])
    particle["time"] = [0.0, 172800.0]

    class FakePathlineFile:
        def __init__(self, path):
            del path

        def get_alldata(self):
            return [particle]

    monkeypatch.setattr("flopy.utils.PathlineFile", FakePathlineFile)
    store = ZarrStore(tmp_path / "catalog")

    ModpathOutputAdapter().extract(solved_run(output_dir), store, keep_all)

    handle = store.open_zarr("sim_mp")
    time = np.asarray(handle.root["particles/time"])
    attrs = dict(handle.root["particles"].attrs)
    handle.close()

    # A NWT run built in seconds: 172800 s is 2 days, not 172800 days.
    assert attrs["time_units"] == TRACKING_TIME_UNIT
    np.testing.assert_allclose(time[0], [0.0, 2.0])


@pytest.mark.regression
@pytest.mark.slow
@pytest.mark.mf6
@pytest.mark.allow_subprocess
def test_mf6_recharge_reads_back_in_m3_per_s(tmp_path):
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

    store = FakeStore(tmp_path)
    Modflow6OutputAdapter().extract(solved_run(tmp_path), store, keep_all)

    inflow: dict[str, float] = {}
    for rec in store.budgets:
        inflow[rec["component"]] = max(inflow.get(rec["component"], 0.0), rec["flux_in"])
    assert inflow["recharge"] == pytest.approx(expected_recharge_m3_s, rel=1e-6)

    # Storage exchanges water during the transient period (m3/s, non-zero).
    assert any(abs(r["storage_in"]) + abs(r["storage_out"]) > 0.0 for r in store.mass)
