"""WP3 - MODFLOW 6 outputs are converted to m3/s using the TDIS time unit.

MF6 emits fluxes in length^3 per TDIS time unit. HydroModPy observations are
m3/s, so every flux is divided by ``seconds_per_time_unit``. Under TDIS SECONDS
the factor is exactly 1.0 (no double scaling); under DAYS it is 86400.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
import pytest

from hydromodpy.solver.modflow6.extractors.flow import (
    Modflow6OutputAdapter,
    _seconds_per_time_unit,
)
from hydromodpy.solver.modflow_common import calibration_extractors as cal
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary


class _FakeStore:
    def __init__(self) -> None:
        self.times = None
        self.fields: list = []
        self.budgets: list | None = None
        self.mass: list | None = None

    def write_time(self, sim_id, values, *, epoch=None, calendar=None, units=None) -> None:
        self.times = np.asarray(values)
        self.time_units = units

    def write_field(self, sim_id, name, t, values, n_timesteps=None, subgroup=None) -> None:
        self.fields.append((name, t, np.asarray(values)))

    def write_budgets(self, sim_id, records) -> None:
        self.budgets = records

    def write_mass_balances(self, sim_id, records) -> None:
        self.mass = records


class _FakeHeadFile:
    def __init__(self, path) -> None:
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
    class _FakeCBC:
        def __init__(self, path, *args, **kwargs):
            del path, args, kwargs

        def get_unique_record_names(self):
            return [name.encode() for name in records]

        def get_data(self, *, text, kstpkper, totim):
            del kstpkper, totim
            arr = records.get(text.strip())
            return [arr] if arr is not None else []

        def close(self) -> None:
            pass

    return _FakeCBC


def test_seconds_per_time_unit_collapses_to_core_units() -> None:
    assert _seconds_per_time_unit("SECONDS") == 1.0
    assert _seconds_per_time_unit("DAYS") == 86400.0
    assert _seconds_per_time_unit("UNKNOWN") == 1.0
    assert _seconds_per_time_unit("") == 1.0


def _run_extract(tmp_path: Path, monkeypatch, time_units: str, records: dict[str, np.ndarray]):
    monkeypatch.setattr("flopy.utils.binaryfile.HeadFile", _FakeHeadFile, raising=True)
    monkeypatch.setattr(
        "flopy.utils.binaryfile.CellBudgetFile", _fake_cbc_factory(records), raising=True
    )
    (tmp_path / "flow.cbc").write_text("", encoding="utf-8")
    (tmp_path / "flow.tdis").write_text(
        f"BEGIN OPTIONS\n  TIME_UNITS {time_units}\nEND OPTIONS\n", encoding="utf-8"
    )
    store = _FakeStore()
    Modflow6OutputAdapter().extract(
        "sim", tmp_path, store, model_name="flow", budget_spatial_fields=False
    )
    return store


def test_mf6_budget_flux_scaled_to_m3_per_s_under_days(tmp_path, monkeypatch) -> None:
    records = {
        "RCHA": np.array([86400.0, 0.0, 0.0]),
        "DRN": np.array([-86400.0, 0.0, 0.0]),
    }
    store = _run_extract(tmp_path, monkeypatch, "DAYS", records)
    by = {r["component"]: r for r in store.budgets}
    assert by["rcha"]["flux_in"] == pytest.approx(1.0)
    assert by["drn"]["flux_out"] == pytest.approx(1.0)

    store_s = _run_extract(tmp_path, monkeypatch, "SECONDS", records)
    by_s = {r["component"]: r for r in store_s.budgets}
    assert by_s["rcha"]["flux_in"] == pytest.approx(86400.0)


def test_mf6_budget_flux_seconds_is_identity(tmp_path, monkeypatch) -> None:
    adapter = Modflow6OutputAdapter()
    monkeypatch.setattr(
        "flopy.utils.binaryfile.CellBudgetFile",
        _fake_cbc_factory({"DRN": np.array([5.0, -5.0])}),
        raising=True,
    )
    store = _FakeStore()
    adapter._extract_budget(
        "sim",
        store,
        tmp_path / "flow.cbc",
        [1.0],
        [(0, 0)],
        nlay=1,
        n_cells=2,
        seconds_per_time_unit=1.0,
    )
    assert store.budgets[0]["flux_in"] == pytest.approx(5.0)
    assert store.budgets[0]["flux_out"] == pytest.approx(5.0)


def test_mf6_mass_balance_extracts_storage_components(tmp_path, monkeypatch) -> None:
    dtype = np.dtype(
        [
            ("TOTAL_IN", "<f8"),
            ("TOTAL_OUT", "<f8"),
            ("PERCENT_DISCREPANCY", "<f8"),
            ("STO-SS_IN", "<f8"),
            ("STO-SY_IN", "<f8"),
            ("STO-SS_OUT", "<f8"),
            ("STO-SY_OUT", "<f8"),
        ]
    )
    inc = np.array([(174240.0, 174240.0, 0.01, 864.0, 86400.0, 0.0, 43200.0)], dtype=dtype)

    class _FakeListBudget:
        def __init__(self, path) -> None:
            del path

        def get_budget(self):
            return inc, None

    monkeypatch.setattr("flopy.utils.Mf6ListBudget", _FakeListBudget, raising=True)
    store = _FakeStore()
    Modflow6OutputAdapter()._extract_mass_balance(
        "sim", store, tmp_path / "flow.lst", seconds_per_time_unit=86400.0
    )
    rec = store.mass[0]
    assert rec["storage_in"] == pytest.approx(1.01)
    assert rec["storage_out"] == pytest.approx(0.5)
    assert rec["total_in"] == pytest.approx(2.0166667, rel=1e-6)
    # PERCENT_DISCREPANCY is unitless and must not be scaled.
    assert rec["percent_error"] == pytest.approx(0.01)


def _write_drain_cbc_fixtures(tmp_path: Path, monkeypatch) -> None:
    class _FakeCBC:
        def __init__(self, path) -> None:
            del path

        def get_unique_record_names(self):
            return [b"DRN"]

        def get_times(self):
            return [1.0]

        def get_kstpkper(self):
            return [(0, 0)]

        def get_data(self, *, text, kstpkper, totim, full3D):
            del text, kstpkper, totim, full3D
            return [np.array([[-86400.0, 0.0, 0.0]], dtype=float)]

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
    series = cal.extract_discharge_from_cbc(tmp_path, "flow")
    assert float(series.iloc[0]) == pytest.approx(1.0)


def test_mf6_calibration_tdis_takes_precedence_over_dis(tmp_path, monkeypatch) -> None:
    _write_drain_cbc_fixtures(tmp_path, monkeypatch)
    # TDIS says DAYS; the legacy .dis would say seconds. TDIS must win.
    (tmp_path / "flow.tdis").write_text(
        "BEGIN OPTIONS\n  TIME_UNITS DAYS\nEND OPTIONS\n", encoding="utf-8"
    )
    (tmp_path / "flow.dis").write_text("1 1 1\n1 1\n", encoding="utf-8")
    series = cal.extract_discharge_from_cbc(tmp_path, "flow")
    assert float(series.iloc[0]) == pytest.approx(1.0)


def test_nwt_calibration_discharge_still_uses_dis_itmuni(tmp_path, monkeypatch) -> None:
    _write_drain_cbc_fixtures(tmp_path, monkeypatch)
    # NWT: ITMUNI=4 (DAYS) in .dis, NO .tdis file.
    (tmp_path / "model.cbc").write_text("", encoding="utf-8")
    (tmp_path / "model.dis").write_text("1 1 1\n1 4\n", encoding="utf-8")

    class _FakeCBC:
        def __init__(self, path) -> None:
            del path

        def get_unique_record_names(self):
            return [b"DRN"]

        def get_times(self):
            return [1.0]

        def get_kstpkper(self):
            return [(0, 0)]

        def get_data(self, *, text, kstpkper, totim, full3D):
            del text, kstpkper, totim, full3D
            return [np.array([[-86400.0, 0.0, 0.0]], dtype=float)]

        def close(self) -> None:
            pass

    monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", _FakeCBC, raising=True)
    series = cal.extract_discharge_from_cbc(tmp_path, "model")
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

    store = _FakeStore()
    Modflow6OutputAdapter().extract("sim", tmp_path, store, model_name="flow")

    by_component_inflow: dict[str, float] = {}
    for rec in store.budgets:
        by_component_inflow[rec["component"]] = max(
            by_component_inflow.get(rec["component"], 0.0), rec["flux_in"]
        )
    assert by_component_inflow["rcha"] == pytest.approx(expected_recharge_m3_s, rel=1e-6)

    # Storage exchanges water during the transient period (m3/s, non-zero).
    assert any(abs(r["storage_in"]) + abs(r["storage_out"]) > 0.0 for r in store.mass)
