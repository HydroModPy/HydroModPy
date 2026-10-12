"""A stamp closes its period: the state at its end, every flux its mean.

A stress period cut into time steps (``simulation.time.substeps_per_period``,
NSTP, ATS) makes MODFLOW write one record per step. Every solver stores one
slice per stress period: the head of the last step, and every flux as the
mean of the steps weighted by their length. These tests run a tiny transient
model whose periods hold four steps, one of them of growing length, and
recompute each stored value from the raw output of the solver.

The Boussinesq driver is checked in ``test_boussinesq_first_period_steady.py``,
where four one-day periods are the four steps of one four-day period.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from hydromodpy.core.budget_terms import BudgetKeep
from hydromodpy.solver.modflow6.build import output_control_records
from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter
from hydromodpy.solver.modflow_common import calibration_extractors as cal
from hydromodpy.solver.modflow_common.period_steps import (
    group_ends_by_stamp,
    group_steps_by_stamp,
    period_end_positions,
    period_mean_balance,
    weighted_period_mean,
)
from hydromodpy.solver.modflow_nwt.extractors.flow import ModflowNwtOutputAdapter
from hydromodpy.solver.modflow_nwt.nwt._pre_processing import output_control_words
from tests._helpers.mf6_ground import leave_ground_beside

DAY_S = 86400.0
NCOL = 6
# Period lengths (days), steps and step growth. Period 0 is steady.
PERLEN = (1.0, 4.0, 2.0)
NSTP = (1, 4, 4)
TSMULT = (1.0, 1.0, 2.0)
RECHARGE_M_D = (2.0e-3, 1.0e-2, 0.0)
HDRY = -1.0e30
HNOFLO = -999.99


# ---------------------------------------------------------------------------
# The helpers that put the saved steps on the stamps
# ---------------------------------------------------------------------------


def test_a_stamp_takes_the_steps_since_the_previous_one_weighted_by_length() -> None:
    keys = [(0, 0), (0, 1), (1, 1), (2, 1), (0, 2), (1, 2)]
    lengths = [1.0, 1.0, 1.0, 2.0, 0.5, 1.5]
    groups = group_steps_by_stamp(keys, lengths, [(0, 0), (2, 1), (1, 2)])

    assert [group.positions for group in groups] == [(0,), (1, 2, 3), (4, 5)]
    assert groups[0].weights == (1.0,)
    assert groups[1].weights == pytest.approx((0.25, 0.25, 0.5))
    assert groups[2].weights == pytest.approx((0.25, 0.75))
    assert period_end_positions(keys) == [0, 3, 5]


def test_a_stamp_of_one_step_keeps_that_step_bit_for_bit() -> None:
    value = np.array([0.1, -0.0, 3.0e-17])
    mean = weighted_period_mean([value], (1.0,))
    assert mean.tobytes() == value.tobytes()
    row = {
        "total_in": 0.3,
        "total_out": 0.1,
        "storage_in": 0.0,
        "storage_out": 0.05,
        "in_minus_out": 0.2,
        "percent_error": 1.234,
    }
    assert period_mean_balance([row], (1.0,))["percent_error"] == 1.234


def test_a_stamp_over_steps_of_unknown_length_is_refused() -> None:
    # A non-compact MODFLOW budget file carries no step length.
    nan = float("nan")
    single = group_steps_by_stamp([(0, 0)], [nan], [(0, 0)])
    assert single[0].weights == (1.0,)
    with pytest.raises(ValueError, match="length of each step"):
        group_steps_by_stamp([(0, 0), (1, 0)], [nan, nan], [(1, 0)])


def test_observation_times_are_put_on_the_stamps_they_close() -> None:
    groups = group_ends_by_stamp([1.0, 2.0, 3.0, 5.0, 6.0, 7.0], [1.0, 5.0, 7.0])
    assert [group.positions for group in groups] == [(0,), (1, 2, 3), (4, 5)]
    assert groups[1].weights == pytest.approx((0.25, 0.25, 0.5))


# ---------------------------------------------------------------------------
# Tiny models
# ---------------------------------------------------------------------------


class _RecordingStore:
    """Keep every write an extractor asks for; refuse the geographic reads."""

    def __init__(self) -> None:
        self.time: np.ndarray | None = None
        self.fields: dict[str, np.ndarray] = {}
        self.budgets: list[dict] = []
        self.mass_balances: list[dict] = []

    def write_time(self, sim_id: str, values: Any, **_: Any) -> None:
        self.time = np.asarray(values, dtype=float)

    def write_field_stack(
        self,
        sim_id: str,
        name: str,
        values: np.ndarray,
        *,
        n_timesteps: int | None = None,
        timestep_offset: int = 0,
        subgroup: str | None = None,
    ) -> None:
        key = name if subgroup is None else f"{subgroup}/{name}"
        values = np.asarray(values, dtype=float)
        if key not in self.fields:
            total = values.shape[0] if n_timesteps is None else int(n_timesteps)
            self.fields[key] = np.full((total, *values.shape[1:]), np.nan)
        self.fields[key][timestep_offset : timestep_offset + values.shape[0]] = values

    def write_budgets(self, sim_id: str, records: list[dict]) -> None:
        self.budgets.extend(records)

    def write_mass_balances(self, sim_id: str, records: list[dict]) -> None:
        self.mass_balances = list(records)

    def read_geographic_feature(self, sim_id: str, name: str) -> None:
        raise LookupError("no geography in a unit test")

    # No field store: the extractor records no budget policy.
    save_zarr = False

    def open_zarr(self, sim_id: str) -> None:
        raise LookupError("no Zarr in a unit test")


def _step_lengths(perlen: float, nstp: int, tsmult: float) -> np.ndarray:
    """Step lengths MODFLOW gives a period, from PERLEN, NSTP and TSMULT."""
    if tsmult == 1.0:
        return np.full(nstp, perlen / nstp)
    first = perlen * (tsmult - 1.0) / (tsmult**nstp - 1.0)
    return first * tsmult ** np.arange(nstp)


def _run_mf6(workspace: Path, *, oc: dict, nstp: tuple[int, ...] = NSTP) -> Path:
    import flopy

    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    sim = flopy.mf6.MFSimulation(
        sim_name="flow", sim_ws=str(workspace), exe_name=str(ensure_solver_binary("mf6"))
    )
    flopy.mf6.ModflowTdis(
        sim,
        nper=len(PERLEN),
        perioddata=list(zip(PERLEN, nstp, TSMULT, strict=True)),
        time_units="days",
    )
    flopy.mf6.ModflowIms(
        sim, complexity="SIMPLE", outer_dvclose=1e-10, inner_dvclose=1e-12, rcloserecord=1e-10
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    flopy.mf6.ModflowGwfdis(
        gwf, nlay=1, nrow=1, ncol=NCOL, delr=10.0, delc=10.0, top=50.0, botm=0.0
    )
    flopy.mf6.ModflowGwfic(gwf, strt=30.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=1.0)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=0, ss=1.0e-3, steady_state={0: True}, transient={1: True})
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=[((0, 0, 0), 20.0)])
    flopy.mf6.ModflowGwfrcha(gwf, recharge=dict(enumerate(RECHARGE_M_D)))
    flopy.mf6.ModflowGwfwel(gwf, stress_period_data={1: [((0, 0, 3), -0.5)], 2: []})
    flopy.mf6.ModflowGwfdrn(gwf, stress_period_data=[((0, 0, 5), 20.05, 5.0)])
    flopy.mf6.ModflowGwfoc(gwf, head_filerecord="flow.hds", budget_filerecord="flow.cbc", **oc)
    sim.write_simulation(silent=True)
    leave_ground_beside(gwf)
    success, buff = sim.run_simulation(silent=True)
    assert success, buff
    return workspace


def _run_nwt(workspace: Path, *, nstp: tuple[int, ...] = NSTP) -> Path:
    import flopy

    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    model = flopy.modflow.Modflow(
        "flow",
        model_ws=str(workspace),
        exe_name=str(ensure_solver_binary("mfnwt")),
        version="mfnwt",
    )
    flopy.modflow.ModflowDis(
        model,
        nlay=1,
        nrow=1,
        ncol=NCOL,
        delr=10.0,
        delc=10.0,
        top=50.0,
        botm=0.0,
        nper=len(PERLEN),
        perlen=list(PERLEN),
        nstp=list(nstp),
        tsmult=list(TSMULT),
        steady=[True, False, False],
        itmuni=4,
    )
    ibound = np.ones((1, 1, NCOL), dtype=int)
    ibound[0, 0, 0] = -1
    strt = np.full((1, 1, NCOL), 30.0)
    strt[0, 0, 0] = 20.0
    flopy.modflow.ModflowBas(model, ibound=ibound, strt=strt, hnoflo=HNOFLO)
    flopy.modflow.ModflowUpw(model, laytyp=0, hk=1.0, ss=1.0e-3, ipakcb=53, hdry=HDRY)
    flopy.modflow.ModflowRch(model, rech=dict(enumerate(RECHARGE_M_D)), ipakcb=53)
    flopy.modflow.ModflowWel(
        model, stress_period_data={1: [[0, 0, 3, -0.5]], 2: [[0, 0, 3, 0.0]]}, ipakcb=53
    )
    flopy.modflow.ModflowDrn(model, stress_period_data={0: [[0, 0, 5, 20.05, 5.0]]}, ipakcb=53)
    flopy.modflow.ModflowNwt(model, headtol=1e-9, fluxtol=1e-8)
    flopy.modflow.ModflowOc(model, stress_period_data=output_control_words(nstp), compact=True)
    model.write_input()
    success, buff = model.run_model(silent=True)
    assert success, buff
    return workspace


def _raw_step_budgets(cbc_path: Path) -> tuple[list[tuple[int, int]], np.ndarray, dict]:
    """Per-step budget arrays straight from the file, with each step length."""
    import flopy

    cbb = flopy.utils.CellBudgetFile(str(cbc_path))
    try:
        keys = [(int(kstp), int(kper)) for kstp, kper in cbb.get_kstpkper()]
        lengths = []
        for kstp, kper in keys:
            rows = cbb.recordarray[
                (cbb.recordarray["kstp"] == kstp + 1) & (cbb.recordarray["kper"] == kper + 1)
            ]
            lengths.append(float(rows["delt"][0]))
        names = [name.decode().strip() for name in cbb.get_unique_record_names()]
        arrays: dict[str, list[np.ndarray | None]] = {}
        for name in names:
            if name in {"FLOW-JA-FACE", "FLOW RIGHT FACE", "FLOW FRONT FACE"}:
                continue
            steps: list[np.ndarray | None] = []
            for key in keys:
                # MODFLOW-NWT writes no STORAGE record in a steady period.
                data = cbb.get_data(text=name, kstpkper=key, full3D=True)
                steps.append(np.asarray(data[0], dtype=float).reshape(-1) if data else None)
            arrays[name] = steps
    finally:
        cbb.close()
    return keys, np.asarray(lengths), arrays


def _expected_period_means(keys, lengths, arrays) -> dict[str, list[dict[str, Any]]]:
    """Weight each step by its length over the period, from the raw file."""
    expected: dict[str, list[dict[str, Any]]] = {}
    for name, steps in arrays.items():
        rows = []
        for kper in range(len(PERLEN)):
            idx = [i for i, (_kstp, k) in enumerate(keys) if k == kper]
            weights = lengths[idx] / lengths[idx].sum()
            assert weights.sum() == pytest.approx(1.0)
            assert lengths[idx].sum() == pytest.approx(PERLEN[kper], rel=1e-6)
            present = [steps[i] for i in idx if steps[i] is not None]
            if not present:
                rows.append(None)
                continue
            size = present[0].size
            # A step without the record counts zero over its length.
            stack = np.vstack([np.zeros(size) if steps[i] is None else steps[i] for i in idx])
            rows.append(
                {
                    "field": weights @ stack,
                    "flux_in": float(weights @ np.maximum(stack, 0.0).sum(axis=1)),
                    "flux_out": float(-(weights @ np.minimum(stack, 0.0).sum(axis=1))),
                    "last": stack[-1],
                }
            )
        expected[name] = rows
    return expected


def _budget_rows(store: _RecordingStore, component: str) -> list[dict]:
    rows = [r for r in store.budgets if r["component"] == component and r["zone_id"] == "0"]
    return sorted(rows, key=lambda row: row["timestep"])


# ---------------------------------------------------------------------------
# MODFLOW 6
# ---------------------------------------------------------------------------

_MF6_COMPONENTS = {
    "CHD": "constant_head",
    "RCHA": "recharge",
    "WEL": "well",
    "DRN": "drain",
    "STO-SS": "storage_ss",
}


@pytest.mark.mf6
@pytest.mark.allow_subprocess
def test_mf6_stores_the_last_head_and_the_mean_flux_of_each_period(tmp_path: Path) -> None:
    from hydromodpy.solver.modflow_common.budget_components import canonical_budget_component

    stored = _run_mf6(tmp_path / "stored", oc=output_control_records(print_head=False))
    raw = _run_mf6(tmp_path / "raw", oc={"saverecord": [("HEAD", "ALL"), ("BUDGET", "ALL")]})
    store = _RecordingStore()
    Modflow6OutputAdapter().extract(
        "sim", stored, store, model_name="flow", budget_terms=BudgetKeep.everything()
    )

    # One slice per stress period, stamped at its end.
    assert store.time is not None
    np.testing.assert_allclose(store.time, np.cumsum(PERLEN) * DAY_S)
    assert store.fields["head"].shape == (len(PERLEN), 1, NCOL)

    import flopy

    heads = flopy.utils.HeadFile(str(raw / "flow.hds"))
    try:
        for kper, nstp in enumerate(NSTP):
            last = heads.get_data(kstpkper=(nstp - 1, kper)).reshape(-1)
            np.testing.assert_array_equal(store.fields["head"][kper, 0], last)
    finally:
        heads.close()

    keys, lengths, arrays = _raw_step_budgets(raw / "flow.cbc")
    expected = _expected_period_means(keys, lengths, arrays)
    for record, _label in _MF6_COMPONENTS.items():
        component = canonical_budget_component(record)
        rows = _budget_rows(store, component)
        assert [row["timestep"] for row in rows] == [0, 1, 2], component
        field = store.fields[f"budget/{component}"]
        for kper, row in enumerate(rows):
            want = expected[record][kper]
            assert row["flux_in"] == pytest.approx(want["flux_in"] / DAY_S, rel=1e-12, abs=1e-20)
            assert row["flux_out"] == pytest.approx(want["flux_out"] / DAY_S, rel=1e-12, abs=1e-20)
            np.testing.assert_allclose(
                field[kper].reshape(-1), want["field"] / DAY_S, rtol=1e-12, atol=1e-20
            )

    # The test discriminates: over period 1 the outflow at the fixed head falls
    # well away from its last step.
    chd = expected["CHD"][1]
    assert abs(chd["flux_out"] - float(-np.minimum(chd["last"], 0).sum())) > 0.02 * chd["flux_out"]

    # The listing budget of every step, averaged the same way.
    listing = flopy.utils.Mf6ListBudget(str(stored / "flow.lst"))
    inc, _cum = listing.get_budget()
    assert len(store.mass_balances) == len(PERLEN)
    for kper, record in enumerate(store.mass_balances):
        rows = inc[inc["stress_period"] == kper]
        weights = rows["tslen"] / rows["tslen"].sum()
        assert record["timestep"] == kper
        assert record["total_in"] == pytest.approx(float(weights @ rows["TOTAL_IN"]) / DAY_S)
        assert record["total_out"] == pytest.approx(float(weights @ rows["TOTAL_OUT"]) / DAY_S)


@pytest.mark.mf6
@pytest.mark.allow_subprocess
def test_mf6_one_step_per_period_stores_what_it_always_stored(tmp_path: Path) -> None:
    one_step = (1, 1, 1)
    before = _run_mf6(
        tmp_path / "before",
        oc={"saverecord": [("HEAD", "LAST"), ("BUDGET", "LAST")]},
        nstp=one_step,
    )
    after = _run_mf6(tmp_path / "after", oc=output_control_records(print_head=False), nstp=one_step)
    stores = []
    for workspace in (before, after):
        store = _RecordingStore()
        Modflow6OutputAdapter().extract(
            "sim", workspace, store, model_name="flow", budget_terms=BudgetKeep.everything()
        )
        stores.append(store)

    assert stores[0].budgets == stores[1].budgets
    assert stores[0].mass_balances == stores[1].mass_balances
    assert stores[0].fields.keys() == stores[1].fields.keys()
    for name, values in stores[0].fields.items():
        assert values.tobytes() == stores[1].fields[name].tobytes(), name


# ---------------------------------------------------------------------------
# MODFLOW-NWT
# ---------------------------------------------------------------------------

_NWT_COMPONENTS = ("CONSTANT HEAD", "RECHARGE", "WELLS", "DRAINS", "STORAGE")


@pytest.mark.nwt
@pytest.mark.allow_subprocess
def test_nwt_stores_one_slice_per_period_with_the_mean_flux(tmp_path: Path) -> None:
    from hydromodpy.solver.modflow_common.budget_components import canonical_budget_component

    workspace = _run_nwt(tmp_path / "nwt")
    store = _RecordingStore()
    ModflowNwtOutputAdapter().extract(
        "sim",
        workspace,
        store,
        hdry=HDRY,
        hnoflo=HNOFLO,
        model_name="flow",
        budget_terms=BudgetKeep.everything(),
    )

    # The OC saves every step (the particle tracking reads them); the store
    # keeps one slice per period.
    assert store.time is not None
    np.testing.assert_allclose(store.time, np.cumsum(PERLEN) * DAY_S)
    assert store.fields["head"].shape == (len(PERLEN), 1, NCOL)

    import flopy

    heads = flopy.utils.HeadFile(str(workspace / "flow.hds"))
    try:
        assert len(heads.get_times()) == sum(NSTP)
        for kper, nstp in enumerate(NSTP):
            last = heads.get_data(kstpkper=(nstp - 1, kper)).reshape(-1)
            np.testing.assert_array_equal(store.fields["head"][kper, 0], last)
    finally:
        heads.close()

    keys, lengths, arrays = _raw_step_budgets(workspace / "flow.cbc")
    # The step lengths of the file are the ones MODFLOW derives from TSMULT.
    for kper in range(len(PERLEN)):
        idx = [i for i, (_kstp, k) in enumerate(keys) if k == kper]
        np.testing.assert_allclose(
            lengths[idx], _step_lengths(PERLEN[kper], NSTP[kper], TSMULT[kper]), rtol=1e-6
        )
    expected = _expected_period_means(keys, lengths, arrays)
    for record in _NWT_COMPONENTS:
        component = canonical_budget_component(record)
        rows = _budget_rows(store, component)
        periods = [kper for kper, want in enumerate(expected[record]) if want is not None]
        assert [row["timestep"] for row in rows] == periods, component
        field = store.fields[f"budget/{component}"]
        for kper, row in zip(periods, rows, strict=True):
            want = expected[record][kper]
            assert row["flux_in"] == pytest.approx(want["flux_in"] / DAY_S, rel=1e-6, abs=1e-15)
            assert row["flux_out"] == pytest.approx(want["flux_out"] / DAY_S, rel=1e-6, abs=1e-15)
            np.testing.assert_allclose(
                field[kper].reshape(-1), want["field"] / DAY_S, rtol=1e-6, atol=1e-15
            )

    assert [row["timestep"] for row in store.mass_balances] == [0, 1, 2]
    listing = flopy.utils.MfListBudget(str(workspace / "flow.list"))
    inc, _cum = listing.get_budget()
    assert len(inc) == sum(NSTP)
    rows = inc[inc["stress_period"] == 2]
    weights = rows["tslen"] / rows["tslen"].sum()
    assert store.mass_balances[2]["total_out"] == pytest.approx(
        float(weights @ rows["TOTAL_OUT"]) / DAY_S, rel=1e-9
    )


# ---------------------------------------------------------------------------
# The calibration readers and the two MODFLOW backends side by side
# ---------------------------------------------------------------------------


@pytest.mark.mf6
@pytest.mark.nwt
@pytest.mark.allow_subprocess
def test_the_calibration_readers_and_both_backends_give_the_period_means(
    tmp_path: Path,
) -> None:
    mf6 = _run_mf6(tmp_path / "mf6", oc=output_control_records(print_head=False))
    nwt = _run_nwt(tmp_path / "nwt")
    mask = np.ones(NCOL, dtype=bool)

    discharge = {}
    heads = {}
    for name, workspace in (("mf6", mf6), ("nwt", nwt)):
        store = _RecordingStore()
        if name == "mf6":
            Modflow6OutputAdapter().extract("sim", workspace, store, model_name="flow")
        else:
            ModflowNwtOutputAdapter().extract(
                "sim", workspace, store, hdry=HDRY, hnoflo=HNOFLO, model_name="flow"
            )
        series = cal.extract_discharge_from_cbc(workspace, "flow", catchment_mask=mask)
        drain = _budget_rows(store, "drain")
        expected = _expected_period_means(*_raw_step_budgets(workspace / "flow.cbc"))
        record = "DRN" if name == "mf6" else "DRAINS"
        np.testing.assert_allclose(
            series.to_numpy(),
            [want["flux_out"] / DAY_S for want in expected[record]],
            rtol=1e-6,
        )
        # A trial scores the series the store holds.
        assert series.size == len(PERLEN)
        np.testing.assert_allclose(
            series.to_numpy(), [row["flux_out"] for row in drain], rtol=1e-6, atol=0.0
        )
        station = cal.extract_head_from_hds(workspace, "flow", station_cells={"p": (0, 0, 3)})["p"]
        np.testing.assert_allclose(station.to_numpy(), store.fields["head"][:, 0, 3])
        release = cal.extract_release_flux_by_cell_from_cbc(
            workspace,
            "flow",
            packages=[cal.ReleasePackage(name="DRN", record_aliases=("DRN", "DRAINS"))],
            excluded_records={"CHD": "a side boundary", "CONSTANT HEAD": "a side boundary"},
            n_cells=NCOL,
        )
        np.testing.assert_allclose(
            release.to_numpy(),
            [np.maximum(-want["field"], 0.0) / DAY_S for want in expected[record]],
            rtol=1e-6,
            atol=1e-15,
        )
        discharge[name] = series.to_numpy()
        heads[name] = station.to_numpy()

    # The same confined model on both backends: the period means agree to the
    # closure of the two solvers.
    np.testing.assert_allclose(discharge["mf6"], discharge["nwt"], rtol=1e-4)
    np.testing.assert_allclose(heads["mf6"], heads["nwt"], rtol=0.0, atol=1e-4)


# ---------------------------------------------------------------------------
# MODFLOW 6 observation files: lakes and streams
# ---------------------------------------------------------------------------


def _run_mf6_lake(workspace: Path) -> Path:
    """A 3x3 lake on a 5x5 two-layer grid, draining to a fixed-head rim.

    Two periods of four steps each, the second of growing length, saved with
    the output control of the build.
    """
    import json

    import flopy

    from hydromodpy.solver.modflow6.builders import build_lake_obs_spec
    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    n = 5
    cell = {(r, c): r * n + c for r in range(n) for c in range(n)}
    lake_cells = [cell[(r, c)] for r in (1, 2, 3) for c in (1, 2, 3)]
    idomain = np.ones((2, n, n), dtype=int)
    for r in (1, 2, 3):
        for c in (1, 2, 3):
            idomain[0, r, c] = 0
    sim = flopy.mf6.MFSimulation(
        sim_name="lake", sim_ws=str(workspace), exe_name=str(ensure_solver_binary("mf6"))
    )
    flopy.mf6.ModflowTdis(
        sim, time_units="seconds", nper=2, perioddata=[(4 * DAY_S, 4, 1.0), (4 * DAY_S, 4, 1.5)]
    )
    flopy.mf6.ModflowIms(
        sim,
        complexity="MODERATE",
        linear_acceleration="BICGSTAB",
        outer_maximum=200,
        inner_maximum=200,
    )
    gwf = flopy.mf6.ModflowGwf(
        sim, modelname="lake", save_flows=True, newtonoptions="NEWTON UNDER_RELAXATION"
    )
    flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=2,
        nrow=n,
        ncol=n,
        delr=10.0,
        delc=10.0,
        top=100.0,
        botm=[90.0, 50.0],
        idomain=idomain,
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0e-5, k33=1.0e-6)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=0.2, ss=1e-5, transient={0: True})
    flopy.mf6.ModflowGwfic(gwf, strt=95.0)
    rim = [
        ((1, r, c), 80.0) for r in range(n) for c in range(n) if r in (0, n - 1) or c in (0, n - 1)
    ]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: rim})
    connections = [
        [0, iconn, (1, divmod(cell_id, n)[0], divmod(cell_id, n)[1]), "VERTICAL", 1.0, 0, 0, 0, 0]
        for iconn, cell_id in enumerate(lake_cells)
    ]
    outlets = [[0, 0, -1, "WEIR", 95.5, 5.0, 0.0, 0.0]]
    obs, meta = build_lake_obs_spec(
        stem="lake",
        lake_conn_info=[
            {
                "lake_index": 0,
                "lake_id": "lac0",
                "n_conn": len(connections),
                "vertical_iconns": list(range(len(connections))),
            }
        ],
        outlets=outlets,
    )
    lak = flopy.mf6.ModflowGwflak(
        gwf,
        pname="LAK",
        boundnames=True,
        save_flows=True,
        nlakes=1,
        noutlets=1,
        ntables=1,
        packagedata=[[0, 96.0, len(connections), "lac0"]],
        connectiondata=connections,
        tables=[[0, "lac0.laktab"]],
        outlets=outlets,
        perioddata={0: [[0, "RAINFALL", 0.0]], 1: [[0, "RAINFALL", 1.0e-6]]},
        budget_filerecord="lake.lak.cbc",
        surfdep=0.1,
    )
    flopy.mf6.ModflowUtllaktab(
        gwf,
        nrow=3,
        ncol=3,
        table=[(90.0, 0.0, 0.0), (95.0, 450.0, 90.0), (100.0, 900.0, 90.0)],
        filename="lac0.laktab",
        parent_file=lak,
    )
    lak.obs.initialize(filename="lake.lak.obs", digits=10, continuous=obs)
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="lake.hds",
        budget_filerecord="lake.cbc",
        **output_control_records(print_head=False),
    )
    sim.write_simulation(silent=True)
    leave_ground_beside(gwf)
    meta["budget_bin"] = "lake.lak.cbc"
    (workspace / "lake.lak.meta.json").write_text(json.dumps(meta))
    success, buff = sim.run_simulation(silent=True)
    assert success, buff
    return workspace


class _LakeStore(_RecordingStore):
    save_zarr = False

    def __init__(self) -> None:
        super().__init__()
        self.timeseries: list[dict] = []

    def write_timeseries_batch(self, sim_id: str, records: list[dict]) -> None:
        self.timeseries.extend(records)


def _stored(series: Any, quantity: str, period: int) -> float:
    rows = series[(series["variable"] == quantity) & (series["timestep"] == period)]
    assert len(rows) == 1, quantity
    return float(rows["value"].iloc[0])


@pytest.mark.mf6
@pytest.mark.allow_subprocess
def test_mf6_lake_series_take_the_period_mean_rate_and_the_end_stage(tmp_path: Path) -> None:
    import pandas as pd

    from hydromodpy.solver.modflow6.extractors.cbc_reader import Mf6CellBudgetReader

    workspace = _run_mf6_lake(tmp_path)
    store = _LakeStore()
    Modflow6OutputAdapter().extract("sim", workspace, store, model_name="lake")
    series = pd.DataFrame(store.timeseries)

    obs = pd.read_csv(workspace / "lake.lak.obs.csv")
    obs.columns = [name.upper() for name in obs.columns]
    stamps = (4 * DAY_S, 8 * DAY_S)
    ends = obs["TIME"].to_numpy()
    lengths = np.diff(np.concatenate([[0.0], ends]))
    with Mf6CellBudgetReader(workspace / "lake.lak.cbc") as budget:
        gwf = [
            budget.read_record(i)["q"].sum()
            for i, r in enumerate(budget.records)
            if r.text == "GWF"
        ]

    for period, (start, end) in enumerate(zip((0.0, *stamps[:-1]), stamps, strict=True)):
        steps = (ends > start + 1.0) & (ends <= end + 1.0)
        assert steps.sum() == 4
        weights = lengths[steps] / lengths[steps].sum()

        stage = next(name for name in obs.columns if name.endswith("STAGE"))
        assert _stored(series, "stage", period) == pytest.approx(
            float(obs[stage].to_numpy()[steps][-1])
        )
        outflow = next(name for name in obs.columns if "EXT" in name and "OUT" in name)
        assert _stored(series, "ext_outflow", period) == pytest.approx(
            -float(weights @ obs[outflow].to_numpy()[steps]), rel=1e-9, abs=1e-15
        )
        assert _stored(series, "gwf_exchange", period) == pytest.approx(
            float(weights @ np.asarray(gwf)[steps]), rel=1e-9
        )
    # The exchange changes within each period: a last-step value would differ.
    first = np.asarray(gwf)[:4]
    assert abs(first[-1] - first.mean()) > 1e-3 * abs(first.mean())


def test_mf6_stream_observations_average_the_rates_and_keep_the_stage_at_the_end(
    tmp_path: Path,
) -> None:
    from hydromodpy.solver.modflow6.extractors.sfr import SfrObsSpec, build_sfr_columns

    spec = SfrObsSpec.from_mapping(
        {
            "obs_csv": "m.sfr.obs.csv",
            "network_id": "net0",
            "reach_count": 1,
            "entries": [
                {"obsname": "r0_stage", "network_id": "net0", "reach": 0, "quantity": "stage"},
                {
                    "obsname": "r0_downstream_flow",
                    "network_id": "net0",
                    "reach": 0,
                    "quantity": "downstream_flow",
                },
            ],
        }
    )
    obs_path = tmp_path / "m.sfr.obs.csv"
    # Period 0 is one step to t = 1; period 1 holds steps of 1, 1 and 2 to t = 5.
    obs_path.write_text(
        "time,R0_STAGE,R0_DOWNSTREAM_FLOW\n1.0,10.0,-1.0\n2.0,11.0,-2.0\n3.0,12.0,-4.0\n"
        "5.0,13.0,-8.0\n",
        encoding="utf-8",
    )
    columns, _budgets = build_sfr_columns(
        spec, obs_path, times=[1.0, 5.0], seconds_per_time_unit=1.0
    )
    values = {
        (str(variable), int(step)): float(value)
        for variable, step, value in zip(
            columns["variable"], columns["timestep"], columns["value"], strict=True
        )
    }
    assert values[("stage", 0)] == 10.0
    assert values[("downstream_flow", 0)] == 1.0
    assert values[("stage", 1)] == 13.0
    assert values[("downstream_flow", 1)] == pytest.approx(0.25 * 2.0 + 0.25 * 4.0 + 0.5 * 8.0)
