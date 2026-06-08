"""The LAK -> LAK MVR cascade builder.

A controlled transfer (a fraction, a cap, a threshold) between two lakes routes a
LAK outlet through the MVR package instead of the direct ``lakeout`` path. The
tests check:

* :func:`build_lake_mover_records` (compiled through
  :func:`build_mvr_period_records`) emits one record per outlet carrying a
  ``mover`` spec, with the FloPy single-model layout ``[pname1, id1, pname2, id2,
  mvrtype, value]``: provider id1 = outlet number (0-based), receiver id2 = lake
  number (0-based), translated from the 1-based config ``lake``;
* an outlet routed directly via ``lakeout`` (no ``mover``) produces NO record;
* outlet numbering stays aligned with :func:`build_lake_outlets`;
* :func:`build_lak_package_args` sets ``mover=True`` and carries the records plus
  the package count only when a transfer is requested;
* the package count counts the single LAK package once (maxpackages);
* driven through FloPy exactly as :func:`build.build_modflow6_model` wires them,
  the LAK package writes the ``MOVER`` option and the MVR package writes the
  back-translated 1-based ``LAK 1 LAK 2 FACTOR 1.0`` transfer record.
"""

from __future__ import annotations

from types import SimpleNamespace

import flopy
import numpy as np
import pytest
from shapely.geometry import Polygon

from hydromodpy.solver.modflow6.builders import (
    apply_lake_idomain_mask,
    build_lak_package_args,
    build_lake_mover_records,
    build_mvr_period_records,
    mover_package_count,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh


def _grid_4x4(nlay: int = 2) -> SolverMesh:
    top = np.full((4, 4), 100.0)
    botm = np.stack([np.full((4, 4), 100.0 - (lay + 1) * 50.0) for lay in range(nlay)])
    return SolverMesh.from_structured_arrays(nrow=4, ncol=4, top=top, botm=botm, dx=1.0, dy=1.0)


def test_factor_mover_record_routes_outlet_to_receiver_lake() -> None:
    # lac0 outlet 0 -> lac1 (1-based lake 2 -> receiver index 1) via FACTOR 1.0.
    lakes = {
        "lac0": {
            "outlets": [
                {
                    "couttype": "WEIR",
                    "invert": 87.0,
                    "width": 30.0,
                    "lakeout": 0,  # external on the LAK side; MVR takes it onward
                    "mover": {"lake": 2, "mvrtype": "FACTOR", "value": 1.0},
                }
            ]
        },
        "lac1": {"outlets": []},
    }
    records = build_mvr_period_records(build_lake_mover_records(None, lakes=lakes))
    assert len(records) == 1
    pname1, id1, pname2, id2, mvrtype, value = records[0]
    assert pname1 == "LAK"
    assert id1 == 0  # outlet number of lac0's first outlet
    assert pname2 == "LAK"
    assert id2 == 1  # config lake=2 (1-based) -> receiver index 1 (0-based)
    assert mvrtype == "FACTOR"
    assert value == pytest.approx(1.0)


def test_direct_lakeout_outlet_emits_no_mover_record() -> None:
    # A direct LAK -> LAK weir (lakeout=1, no mover) must NOT create an MVR record.
    lakes = {
        "lac0": {"outlets": [{"couttype": "WEIR", "invert": 87.0, "width": 30.0, "lakeout": 1}]},
        "lac1": {"outlets": []},
    }
    assert build_mvr_period_records(build_lake_mover_records(None, lakes=lakes)) == []


def test_outlet_numbering_is_shared_with_outlets_builder() -> None:
    # lac0 has two outlets; only the second carries a mover -> id1 must be 1.
    lakes = {
        "lac0": {
            "outlets": [
                {"couttype": "WEIR", "invert": 95.0, "width": 8.0, "lakeout": 0},
                {
                    "couttype": "WEIR",
                    "invert": 87.0,
                    "width": 30.0,
                    "lakeout": 0,
                    "mover": {"lake": 2, "mvrtype": "UPTO", "value": 12.0},
                },
            ]
        },
        "lac1": {"outlets": []},
    }
    records = build_mvr_period_records(build_lake_mover_records(None, lakes=lakes))
    assert len(records) == 1
    _, id1, _, id2, mvrtype, value = records[0]
    assert id1 == 1  # second outlet of lac0
    assert id2 == 1
    assert mvrtype == "UPTO"
    assert value == pytest.approx(12.0)


def test_mover_lake_out_of_range_is_rejected() -> None:
    lakes = {
        "lac0": {
            "outlets": [
                {
                    "couttype": "WEIR",
                    "invert": 87.0,
                    "width": 30.0,
                    "lakeout": 0,
                    "mover": {"lake": 3},  # only 2 lakes declared
                }
            ]
        },
        "lac1": {"outlets": []},
    }
    with pytest.raises(ValueError, match="no matching downstream lake"):
        build_mvr_period_records(build_lake_mover_records(None, lakes=lakes))


def test_unknown_mvrtype_is_rejected() -> None:
    lakes = {
        "lac0": {
            "outlets": [
                {
                    "couttype": "WEIR",
                    "invert": 87.0,
                    "width": 30.0,
                    "lakeout": 0,
                    "mover": {"lake": 2, "mvrtype": "SIPHON"},
                }
            ]
        },
        "lac1": {"outlets": []},
    }
    with pytest.raises(ValueError, match="mvrtype must be one of"):
        build_mvr_period_records(build_lake_mover_records(None, lakes=lakes))


def test_mover_package_count_is_one_for_lak_to_lak() -> None:
    records = [["LAK", 0, "LAK", 1, "FACTOR", 1.0], ["LAK", 1, "LAK", 0, "FACTOR", 1.0]]
    assert mover_package_count(records) == 1


def _two_lake_model_with_mover() -> SimpleNamespace:
    poly0 = Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)])
    poly1 = Polygon([(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)])
    abacus = [(50.0, 0.0, 4.0), (100.0, 200.0, 4.0)]
    return SimpleNamespace(
        model_output_name="lac_test",
        time_units="seconds",
        flow=SimpleNamespace(
            active_bc=["lake"],
            sinks_sources={
                "lakes": {
                    "lac0": {
                        "polygon": poly0,
                        "bedleak": 0.3,
                        "abacus": abacus,
                        "stageinit": 80.0,
                        "outlets": [
                            {
                                "couttype": "WEIR",
                                "invert": 87.0,
                                "width": 30.0,
                                "lakeout": 0,
                                "mover": {"lake": 2, "mvrtype": "FACTOR", "value": 1.0},
                            }
                        ],
                    },
                    "lac1": {
                        "polygon": poly1,
                        "bedleak": 0.3,
                        "abacus": abacus,
                        "stageinit": 80.0,
                    },
                }
            },
        ),
    )


def test_lak_package_args_enable_mover_and_carry_records() -> None:
    cells = {"lac0": [0, 1], "lac1": [10, 11]}
    masked = apply_lake_idomain_mask(_grid_4x4(), lake_cell_ids_by_lake=cells)
    args = build_lak_package_args(
        _two_lake_model_with_mover(), solver_mesh=masked, lake_cell_ids_by_lake=cells
    )
    assert args is not None
    assert args["nlakes"] == 2
    assert args["mover"] is True
    assert len(args["mover_records"]) == 1
    assert args["mover_records"][0] == ["LAK", 0, "LAK", 1, "FACTOR", 1.0]
    assert args["mover_maxpackages"] == 1


def test_lak_package_args_omit_mover_without_transfer() -> None:
    # A direct lakeout weir keeps the LAK args free of any mover keys.
    model = _two_lake_model_with_mover()
    outlet = model.flow.sinks_sources["lakes"]["lac0"]["outlets"][0]
    del outlet["mover"]
    outlet["lakeout"] = 2  # direct LAK -> lake 2 routing instead
    cells = {"lac0": [0, 1], "lac1": [10, 11]}
    masked = apply_lake_idomain_mask(_grid_4x4(), lake_cell_ids_by_lake=cells)
    args = build_lak_package_args(model, solver_mesh=masked, lake_cell_ids_by_lake=cells)
    assert args is not None
    assert "mover" not in args
    assert "mover_records" not in args
    assert "mover_maxpackages" not in args


def _wire_lak_and_mvr_through_flopy(gwf, lak_args: dict) -> None:
    """Instantiate LAK + MVR exactly as build.build_modflow6_model does.

    Mirrors the wiring at hydromodpy/solver/modflow6/build.py (the LAK package,
    its laktab tables, then MVR last so it can reference LAK by name). Kept in
    lockstep so a malformed maxpackages or record is caught here, before MF6.
    """
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


def test_flopy_writes_lak_mover_option_and_mvr_record(tmp_path) -> None:
    # End-to-end of the build.py MVR wiring: the 0-based builder records must come
    # back out of MF6 as a valid 1-based 'LAK 1 LAK 2 FACTOR 1.0' transfer, and
    # the LAK package must advertise the MOVER option. No solver binary is run --
    # FloPy's writer is the contract that the unit-level record dicts can't catch.
    model = _two_lake_model_with_mover()
    cells = {"lac0": [0, 1], "lac1": [10, 11]}
    masked = apply_lake_idomain_mask(_grid_4x4(), lake_cell_ids_by_lake=cells)
    lak_args = build_lak_package_args(model, solver_mesh=masked, lake_cell_ids_by_lake=cells)
    assert lak_args is not None

    sim = flopy.mf6.MFSimulation(sim_name="t", sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    flopy.mf6.ModflowIms(sim)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="t", newtonoptions="NEWTON")
    disv_kwargs = masked.to_disv_kwargs()
    flopy.mf6.ModflowGwfdisv(
        gwf, nlay=masked.nlay, **disv_kwargs, idomain=masked.idomain(), xorigin=0.0, yorigin=0.0
    )
    flopy.mf6.ModflowGwfnpf(gwf, k=1.0)
    flopy.mf6.ModflowGwfic(gwf, strt=90.0)
    _wire_lak_and_mvr_through_flopy(gwf, lak_args)
    sim.write_simulation()

    lak_text = (tmp_path / "t.lak").read_text()
    mvr_text = (tmp_path / "t.mvr").read_text()

    # LAK must opt into MOVER (otherwise MF6 ignores the MVR routing).
    assert "MOVER" in lak_text
    # The outlet still spills externally on the LAK side (lakeout column = 0);
    # MVR is what carries it onward to lac1.
    outlet_line = next(line for line in lak_text.splitlines() if "WEIR" in line)
    assert outlet_line.split()[:4] == ["1", "1", "0", "WEIR"]

    # MVR dimensions: one record, one referenced package (the single LAK).
    assert "MAXMVR  1" in mvr_text
    assert "MAXPACKAGES  1" in mvr_text
    # The transfer record, back-translated from 0-based builder ids to MF6's
    # 1-based file convention: provider LAK outlet 1 -> receiver LAK lake 2.
    period = mvr_text.split("BEGIN period")[1]
    record = next(line.split() for line in period.splitlines() if line.strip().startswith("LAK"))
    assert record[0] == "LAK"
    assert record[1] == "1"  # provider id (outlet 0 -> 1-based 1)
    assert record[2] == "LAK"
    assert record[3] == "2"  # receiver id (lake index 1 -> 1-based 2)
    assert record[4] == "FACTOR"
    assert float(record[5]) == pytest.approx(1.0)
