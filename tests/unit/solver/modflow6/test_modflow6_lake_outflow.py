"""Lake outlets (weir, Manning, specified) and the lake-to-lake MVR cascade.

An outlet row follows the FloPy layout [outletno, lakein, lakeout, kind, invert,
width, rough, slope] with invert in m, width in m and slope in m/m. In the config
lakeout = 0 means outside the model and n means the n-th lake, in FloPy lakeout
is -1 and the 0-based lake index. A controlled transfer (a fraction, a cap, a
threshold) goes through MVR instead, with records [pname1, id1, pname2, id2,
mvrtype, value] where id1 is the outlet number and id2 the receiver lake index.
"""

from __future__ import annotations

import csv
import logging
import math
from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
import pytest
from shapely.geometry import Polygon

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.solver.modflow6.builders.lake import _emit_outlet_rate_rows, build_lak_package_args
from hydromodpy.solver.modflow6.builders.lake_cells import apply_lake_idomain_mask
from hydromodpy.solver.modflow6.builders.lake_outflow import (
    build_lake_mover_records,
    build_lake_outlets,
    own_lake_upstream_ifnos,
    resolve_downstream_spillway_reaches,
)
from hydromodpy.solver.modflow6.builders.mvr import build_mvr_period_records, mover_package_count
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

CREST = 87.0  # m, concrete sill shared by the preretenue spill and the crossed weirs
LAKE_CELLS = [5, 6, 9, 10]
TWO_LAKE_CELLS = {"lac0": [0, 1], "lac1": [10, 11]}


def grid_4x4(top=100.0, step=50.0, dx=1.0) -> SolverMesh:
    botm = np.stack([np.full((4, 4), top - (lay + 1) * step) for lay in range(2)])
    return solver_mesh_from_structured_arrays(
        nrow=4, ncol=4, top=np.full((4, 4), top), botm=botm, dx=dx, dy=dx
    )


def weir(**changes) -> dict:
    return {"kind": "WEIR", "invert": CREST, "width": 30.0, "lakeout": 0} | changes


def two_lake_model(*, lac0_outlets: list[dict], lac1_outlets: list[dict]) -> SimpleNamespace:
    """lac0 (preretenue, upstream) in the lower-left quad, lac1 (retenue) in the upper-right."""
    return SimpleNamespace(
        model_output_name="preretenue_test",
        time_units="seconds",
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes={
                "lac0": {
                    "polygon": Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]),
                    "bedleak": 0.2,
                    "abacus": [(50.0, 0.0, 4.0), (90.0, 160.0, 4.0)],
                    "initial_stage": 60.0,
                    "outlets": lac0_outlets,
                },
                "lac1": {
                    "polygon": Polygon([(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)]),
                    "bedleak": 0.2,
                    "abacus": [(50.0, 0.0, 9.0), (90.0, 360.0, 9.0)],
                    "initial_stage": 70.0,
                    "outlets": lac1_outlets,
                },
            },
        ),
    )


def cascade_model() -> SimpleNamespace:
    """lac0 sends its weir outlet to lac1 through MVR, FACTOR 1.0."""
    mover = {"lake": 2, "mvrtype": "FACTOR", "value": 1.0}
    return two_lake_model(lac0_outlets=[weir(mover=mover)], lac1_outlets=[])


def lak_args(model: SimpleNamespace) -> dict:
    masked = apply_lake_idomain_mask(grid_4x4(), lake_cell_ids_by_lake=TWO_LAKE_CELLS)
    return build_lak_package_args(model, solver_mesh=masked, lake_cell_ids_by_lake=TWO_LAKE_CELLS)


OUTLET_ROWS = [
    pytest.param(
        {"kind": "WEIR", "invert": 87.0, "width": 12.0, "lakeout": 0},
        [0, 0, -1, "WEIR", 87.0, 12.0, 0.0, 0.0],
        id="weir ignores rough and slope",
    ),
    pytest.param(
        {"kind": "MANNING", "invert": 90.0, "width": 5.0, "rough": 0.03, "slope": 1.0e-3},
        [0, 0, -1, "MANNING", 90.0, 5.0, 0.03, 1.0e-3],
        id="manning carries rough and slope",
    ),
    pytest.param(
        {"kind": "SPECIFIED", "lakeout": 0},
        [0, 0, -1, "SPECIFIED", 0.0, 0.0, 0.0, 0.0],
        id="specified has no geometry",
    ),
]


@pytest.mark.parametrize(("outlet", "row"), OUTLET_ROWS)
def test_outlet_row(outlet, row) -> None:
    rows = build_lake_outlets(None, lakes={"lac0": {"outlets": [outlet]}})

    assert [list(r) for r in rows] == [row]


def test_specified_outlet_emits_a_period_rate_row() -> None:
    # Without a PERIOD rate row keyed by the global outlet number, MF6 starts the
    # rate at zero and the outlet releases nothing.
    lakes = {
        "lac0": {
            "outlets": [
                {"kind": "WEIR", "lakeout": 0},  # global outlet 0
                {"kind": "SPECIFIED", "lakeout": 0, "rate": -2.5},  # global outlet 1
            ]
        }
    }
    period_rows: dict[int, list[list[object]]] = {}

    _emit_outlet_rate_rows(
        None,
        lakes=lakes,
        mode="inline",
        min_periods=64,
        nper=1,
        period_rows=period_rows,
        ts_series=[],
    )

    assert [1, "rate", -2.5] in period_rows[0]


OUTLET_REFUSALS = [
    pytest.param(
        {"lac0": {"outlets": [weir(width=30.0, lakeout=2)]}},
        "no matching downstream lake",
        id="lakeout beyond the lake count",
    ),
    pytest.param(
        {"lac0": {"outlets": [weir(lakeout=1)]}, "lac1": {"outlets": []}},
        "routes the lake to itself",
        id="lake routed to itself",
    ),
    pytest.param(
        {"lac0": {"outlets": [{"kind": "MANNING", "invert": 90.0, "width": 5.0, "rough": 0.03}]}},
        "positive slope",
        id="manning without slope",
    ),
    pytest.param(
        {"lac0": {"outlets": [{"kind": "WEIR", "width": 5.0}]}},
        "requires an invert",
        id="weir without invert",
    ),
    pytest.param(
        {"lac0": {"outlets": [{"kind": "SIPHON", "invert": 1.0, "width": 1.0}]}},
        "kind must be one of",
        id="unknown kind",
    ),
]


@pytest.mark.parametrize(("lakes", "message"), OUTLET_REFUSALS)
def test_outlet_refusals(lakes, message) -> None:
    with pytest.raises(ValueError, match=message):
        build_lake_outlets(None, lakes=lakes)


def test_reciprocal_weirs_name_both_outlets() -> None:
    # Two lakes spilling into each other over one crest circulate water around the
    # loop, 17.6 m3/s each way for a 0.04 m3/s net on the Cheze.
    lakes = {
        "reservoir": {
            "outlets": [weir(invert=87.57, width=35.0), weir(invert=86.93, width=24.0, lakeout=2)]
        },
        "preretenue": {"outlets": [weir(invert=86.93, width=24.0, lakeout=1)]},
    }

    with pytest.raises(ValueError, match="Reciprocal") as err:
        build_lake_outlets(None, lakes=lakes)

    text = str(err.value)
    assert "reservoir" in text and "preretenue" in text
    assert "outlet 1" in text and "outlet 2" in text


def test_reciprocal_outlets_at_different_crests_only_warn(caplog) -> None:
    lakes = {
        "reservoir": {"outlets": [weir(invert=90.0, width=24.0, lakeout=2)]},
        "preretenue": {"outlets": [weir(invert=86.93, width=24.0, lakeout=1)]},
    }

    with caplog.at_level(logging.WARNING):
        rows = build_lake_outlets(None, lakes=lakes)

    assert len(rows) == 2
    assert "outlet loop" in caplog.text


def test_lak_args_attach_outlets_and_seconds_conversions() -> None:
    model = SimpleNamespace(
        model_output_name="lac_test",
        time_units="seconds",
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes={
                "lac0": {
                    "polygon": Polygon([(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)]),
                    "bedleak": 0.3,
                    "abacus": [(50.0, 0.0, 4.0), (100.0, 200.0, 4.0)],
                    "initial_stage": 80.0,
                    "outlets": [weir(invert=95.0, width=8.0)],
                    "rainfall": {"value": 4.0, "units": "mm/day"},
                }
            },
        ),
    )
    masked = apply_lake_idomain_mask(grid_4x4(), lake_cell_ids_by_lake={"lac0": LAKE_CELLS})

    args = build_lak_package_args(
        model, solver_mesh=masked, lake_cell_ids_by_lake={"lac0": LAKE_CELLS}
    )

    assert args["noutlets"] == 1
    assert args["outlets"][0][3] == "WEIR"
    rainfall = [r for r in args["perioddata"][0] if r[1] == "rainfall"]
    assert rainfall[0][2] == pytest.approx(4.0e-3 / 86400.0)  # mm/day to m/s
    # The model runs in seconds, so the conversions stay 1.0 (not 86400).
    assert args["time_conversion"] == 1.0
    assert args["length_conversion"] == 1.0


# Two lakes in one LAK package, a concrete weir between them.


def test_two_lake_build() -> None:
    model = two_lake_model(lac0_outlets=[weir(width=30.0, lakeout=2)], lac1_outlets=[])

    args = lak_args(model)

    assert args["nlakes"] == 2
    assert len(args["packagedata"]) == 2
    assert args["ntables"] == len(args["laktab_specs"]) == 2
    assert {row[3] for row in args["packagedata"]} == {"lac0", "lac1"}
    assert {row[0] for row in args["connectiondata"]} == {0, 1}
    # Each lake starts from its own initial stage.
    assert {row[3]: row[1] for row in args["packagedata"]} == pytest.approx(
        {"lac0": 60.0, "lac1": 70.0}
    )


def test_concrete_weir_routes_the_preretenue_to_the_retenue() -> None:
    model = two_lake_model(lac0_outlets=[weir(width=30.0, lakeout=2)], lac1_outlets=[])

    rows = build_lake_outlets(model, lakes=model.inputs.lakes)

    # Spills from lac0 straight into lac1 (index 1), not outside (-1), at the crest.
    assert [list(r) for r in rows] == [[0, 0, 1, "WEIR", CREST, 30.0, 0.0, 0.0]]


def test_crossed_weirs_at_the_same_crest_are_refused() -> None:
    # Direct weirs in both ways at one invert circulate water above the crest
    # (19 of 19 minimal Cheze cases fail to converge). Both outlets are named.
    model = two_lake_model(
        lac0_outlets=[weir(width=100.0, lakeout=2)], lac1_outlets=[weir(width=100.0, lakeout=1)]
    )

    with pytest.raises(ValueError, match="Reciprocal WEIR") as err:
        build_lake_outlets(model, lakes=model.inputs.lakes)

    assert "outlet 0" in str(err.value) and "outlet 1" in str(err.value)


def crossed_weirs_with_a_mover_back() -> SimpleNamespace:
    """lac0 spills to lac1 directly, lac1 sends its weir back to lac0 through MVR."""
    back = weir(width=100.0, mover={"lake": 1, "mvrtype": "FACTOR", "value": 1.0})
    return two_lake_model(lac0_outlets=[weir(width=100.0, lakeout=2)], lac1_outlets=[back])


def test_crossed_weirs_with_a_mover_emit_two_outlets_at_one_crest() -> None:
    model = crossed_weirs_with_a_mover_back()

    rows = build_lake_outlets(model, lakes=model.inputs.lakes)

    assert all(row[4] == pytest.approx(CREST) for row in rows)
    assert sorted(row[1] for row in rows) == [0, 1]


def test_crossed_weir_back_route_is_an_mvr_record() -> None:
    args = lak_args(crossed_weirs_with_a_mover_back())

    assert args["mover"] is True
    # lac1's outlet is number 1 and it moves to lac0 (receiver index 0).
    assert args["mover_records"] == [["LAK", 1, "LAK", 0, "FACTOR", 1.0]]


# The MVR cascade.

MOVER_RECORDS = [
    pytest.param(
        {
            "lac0": {"outlets": [weir(mover={"lake": 2, "mvrtype": "FACTOR", "value": 1.0})]},
            "lac1": {"outlets": []},
        },
        [["LAK", 0, "LAK", 1, "FACTOR", 1.0]],
        id="factor to the receiver lake",
    ),
    pytest.param(
        {"lac0": {"outlets": [weir(lakeout=1)]}, "lac1": {"outlets": []}},
        [],
        id="direct lakeout makes no record",
    ),
    pytest.param(
        {
            "lac0": {
                "outlets": [
                    weir(invert=95.0, width=8.0),
                    weir(mover={"lake": 2, "mvrtype": "UPTO", "value": 12.0}),
                ]
            },
            "lac1": {"outlets": []},
        },
        [["LAK", 1, "LAK", 1, "UPTO", 12.0]],
        id="numbering follows the outlets builder",
    ),
]


@pytest.mark.parametrize(("lakes", "records"), MOVER_RECORDS)
def test_lake_mover_records(lakes, records) -> None:
    assert build_mvr_period_records(build_lake_mover_records(None, lakes=lakes)) == records


MOVER_REFUSALS = [
    pytest.param({"lake": 3}, "no matching downstream lake", id="lake out of range"),
    pytest.param({"lake": 2, "mvrtype": "SIPHON"}, "mvrtype must be one of", id="unknown mvrtype"),
]


@pytest.mark.parametrize(("mover", "message"), MOVER_REFUSALS)
def test_lake_mover_refusals(mover, message) -> None:
    lakes = {"lac0": {"outlets": [weir(mover=mover)]}, "lac1": {"outlets": []}}

    with pytest.raises(ValueError, match=message):
        build_mvr_period_records(build_lake_mover_records(None, lakes=lakes))


def test_one_package_for_lak_to_lak() -> None:
    records = [["LAK", 0, "LAK", 1, "FACTOR", 1.0], ["LAK", 1, "LAK", 0, "FACTOR", 1.0]]

    assert mover_package_count(records) == 1


def test_lak_args_enable_mover_and_carry_records() -> None:
    args = lak_args(cascade_model())

    assert args["nlakes"] == 2
    assert args["mover"] is True
    assert args["mover_records"] == [["LAK", 0, "LAK", 1, "FACTOR", 1.0]]
    assert args["mover_maxpackages"] == 1


def test_lak_args_omit_mover_without_transfer() -> None:
    # A direct lakeout weir keeps the LAK args free of mover keys.
    model = two_lake_model(lac0_outlets=[weir(lakeout=2)], lac1_outlets=[])

    args = lak_args(model)

    assert not {"mover", "mover_records", "mover_maxpackages"} & set(args)


def wire_lak_and_mvr_through_flopy(gwf, lak_args: dict) -> None:
    """Instantiate LAK, its tables, then MVR, as hydromodpy/solver/modflow6/build.py does."""
    laktab_specs = lak_args.pop("laktab_specs")
    mover_records = lak_args.pop("mover_records", None)
    mover_maxpackages = lak_args.pop("mover_maxpackages", 0)
    obs_continuous = lak_args.pop("obs_continuous", None)
    lak_args.pop("lake_obs_meta", None)
    lak = flopy.mf6.ModflowGwflak(gwf, pname="LAK", **lak_args)
    for spec in laktab_specs:
        flopy.mf6.ModflowUtllaktab(
            gwf,
            nrow=len(spec["table"]),
            ncol=3,
            table=spec["table"],
            filename=spec["filename"],
            parent_file=lak,
        )
    if obs_continuous:
        lak.obs.initialize(
            filename="flow.lak.obs", digits=10, print_input=False, continuous=obs_continuous
        )
    if mover_records:
        flopy.mf6.ModflowGwfmvr(
            gwf,
            pname="MVR",
            maxmvr=len(mover_records),
            maxpackages=int(mover_maxpackages),
            packages=[("LAK",)],
            perioddata={0: mover_records},
        )


def test_flopy_writes_the_lak_mover_option_and_the_mvr_record(tmp_path) -> None:
    # No solver runs here. FloPy's writer is the contract the record lists cannot show.
    masked = apply_lake_idomain_mask(grid_4x4(), lake_cell_ids_by_lake=TWO_LAKE_CELLS)
    lak_package_args = lak_args(cascade_model())
    sim = flopy.mf6.MFSimulation(sim_name="t", sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    flopy.mf6.ModflowIms(sim)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="t", newtonoptions="NEWTON")
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=masked.nlay,
        **masked.to_disv_kwargs(),
        idomain=masked.idomain,
        xorigin=0.0,
        yorigin=0.0,
    )
    flopy.mf6.ModflowGwfnpf(gwf, k=1.0)
    flopy.mf6.ModflowGwfic(gwf, strt=90.0)
    wire_lak_and_mvr_through_flopy(gwf, lak_package_args)

    sim.write_simulation()

    lak_text = (tmp_path / "t.lak").read_text()
    mvr_text = (tmp_path / "t.mvr").read_text()
    assert "MOVER" in lak_text  # without it MF6 ignores the MVR routing
    # The outlet still spills outside on the LAK side (lakeout column 0).
    outlet_line = next(line for line in lak_text.splitlines() if "WEIR" in line)
    assert outlet_line.split()[:4] == ["1", "1", "0", "WEIR"]
    assert "MAXMVR  1" in mvr_text
    assert "MAXPACKAGES  1" in mvr_text
    # The 0-based ids come back 1-based: outlet 0 is 1, lake index 1 is 2.
    period = mvr_text.split("BEGIN period")[1]
    record = next(line.split() for line in period.splitlines() if line.strip().startswith("LAK"))
    assert record[:5] == ["LAK", "1", "LAK", "2", "FACTOR"]
    assert float(record[5]) == pytest.approx(1.0)


def two_lake_mvr_sim(tmp_path, *, exe: str):
    """A runnable 2-lake DISV simulation with a LAK to LAK MVR transfer.

    lac0 has a weir routed to lac1 through MVR (FACTOR 1.0). Constant-head cells
    drain the aquifer so the solve is well posed.
    """
    cells = {"lac0": [0, 1], "lac1": [14, 15]}
    abacus = [(80.0, 0.0, 1.0e4), (90.0, 1.0e5, 1.0e4), (100.0, 2.0e5, 1.0e4)]
    mover = {"lake": 2, "mvrtype": "FACTOR", "value": 1.0}
    model = SimpleNamespace(
        model_output_name="lac_test",
        time_units="seconds",
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes={
                "lac0": {
                    "polygon": None,
                    "bedleak": 0.01,
                    "abacus": abacus,
                    "initial_stage": 87.5,
                    "inflow": 0.5,
                    "outlets": [weir(width=5.0, mover=mover)],
                },
                "lac1": {"polygon": None, "bedleak": 0.01, "abacus": abacus, "initial_stage": 82.0},
            },
        ),
        nper=1,
        perlen=[8.64e6],
        time_grid=None,
        modflow_config=SimpleNamespace(
            process_specific=SimpleNamespace(lak_forcing_mode="inline", ts6_min_periods=120)
        ),
    )
    masked = apply_lake_idomain_mask(grid_4x4(dx=100.0, step=50.0), lake_cell_ids_by_lake=cells)
    lak_package_args = build_lak_package_args(
        model, solver_mesh=masked, lake_cell_ids_by_lake=cells
    )
    assert lak_package_args.get("mover") is True

    sim = flopy.mf6.MFSimulation(sim_name="mvr", sim_ws=str(tmp_path), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=1, perioddata=[(8.64e6, 50, 1.1)])
    flopy.mf6.ModflowIms(
        sim,
        complexity="MODERATE",
        linear_acceleration="BICGSTAB",
        outer_maximum=500,
        inner_maximum=200,
        outer_dvclose=1e-6,
        inner_dvclose=1e-7,
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname="lac_test", newtonoptions="NEWTON UNDER_RELAXATION")
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=masked.nlay,
        **masked.to_disv_kwargs(),
        idomain=masked.idomain,
        xorigin=0.0,
        yorigin=0.0,
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0, k33=0.1)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=0.2, ss=1e-5, transient={0: True})
    flopy.mf6.ModflowGwfic(gwf, strt=83.0)
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: [[(1, c), 78.0] for c in (0, 3, 12, 15)]})
    wire_lak_and_mvr_through_flopy(gwf, lak_package_args)
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="lac_test.hds",
        budget_filerecord="lac_test.cbc",
        saverecord=[("HEAD", "LAST"), ("BUDGET", "LAST")],
    )
    sim.write_simulation(silent=True)
    return sim


def last_obs_row(path) -> dict[str, float]:
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = [h.strip().upper() for h in next(reader)]
        last = None
        for row in reader:
            if row:
                last = row
    assert last is not None, "LAK obs CSV has no data rows"
    return {name: float(value) for name, value in zip(header, last, strict=True)}


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_mvr_cascade_runs_and_extracts_mover_obs(tmp_path) -> None:
    # The to-mvr, from-mvr and ext-outflow obs are keyed by outlet and lake id, so a
    # wrong id makes MF6 reject the obs file and the run fail here.
    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    sim = two_lake_mvr_sim(tmp_path, exe=str(ensure_solver_binary("mf6")))

    ok, _ = sim.run_simulation(silent=True)

    assert ok, "the 2-lake MVR cascade did not converge"
    obs = last_obs_row(Path(tmp_path) / "lac_test.lak.obs.csv")
    to_mvr = obs["LAC0_TO_MVR_0"]  # keyed by the provider outlet
    from_mvr = obs["LAC1_FROM_MVR"]  # keyed by the receiver lake
    assert math.isfinite(to_mvr) and math.isfinite(from_mvr)
    # FACTOR 1.0: what leaves lac0 by the mover is what lac1 receives.
    assert abs(from_mvr) == pytest.approx(abs(to_mvr), rel=1e-6, abs=1e-9)


def spillway_to_the_reach_below_the_dam() -> dict:
    mover = {"to_downstream_reach": True, "mvrtype": "upto", "value": 2.5}
    return {"lac0": {"outlets": [weir(mover=mover)]}, "lac1": {"outlets": []}}


def test_mover_to_the_reach_below_the_dam() -> None:
    records = build_lake_mover_records(
        None, lakes=spillway_to_the_reach_below_the_dam(), downstream_reach_by_lake={"lac0": 7}
    )

    assert build_mvr_period_records(records) == [["LAK", 0, "SFR", 7, "UPTO", 2.5]]


@pytest.mark.parametrize("reaches", [None, {"lac1": 7}], ids=["no reach table", "other lake only"])
def test_mover_without_a_reach_below_the_dam_is_refused(reaches) -> None:
    with pytest.raises(ValueError, match="could not resolve a downstream SFR reach"):
        build_lake_mover_records(
            None, lakes=spillway_to_the_reach_below_the_dam(), downstream_reach_by_lake=reaches
        )


def reach(ifno, upstream, *, lake=None):
    return SimpleNamespace(
        ifno=ifno, upstream=upstream, is_terminal_to_lake=lake is not None, terminal_lake=lake
    )


def test_reaches_that_end_in_each_lake() -> None:
    # Reach 10 ends in lake "a" (number 1). A diamond 11, 12 -> 13 sits upstream of it, and
    # reach 99 is not in the network. Reach 20 ends in lake number 5, which does not exist.
    network = SimpleNamespace(
        reaches=[
            reach(10, [11, 12, 99], lake=1),
            reach(11, [13]),
            reach(12, [13]),
            reach(13, []),
            reach(20, [], lake=5),
        ]
    )

    result = own_lake_upstream_ifnos({"net": network}, lake_ids=["a", "b"])

    assert result == {"a": {10, 11, 12, 13}, "b": set()}


def test_no_reach_to_receive_the_spillway() -> None:
    assert (
        resolve_downstream_spillway_reaches(
            {"lac0": 3}, reach_cell_to_ifno={}, cell_centroids=np.zeros((4, 2))
        )
        == {}
    )
