"""End-to-end run of the HMP-built two-lake forebay (pre-retenue + reservoir).

Two LAK lakes are coupled across a sill by TWO reciprocal DIRECT WEIR outlets at
a shared invert (lac0 -> lac1 with ``lakeout = 2`` and lac1 -> lac0 with
``lakeout = 1``, no MVR). lac1 also carries a spillway WEIR to the external
boundary. The LAK package is assembled by the production
``build_lak_package_args`` (so the integration covers the real builder output),
then wired into a tiny 5x11 / 2-layer DISV model exported from a ``SolverMesh``
and run in MF6. The lakebed is sealed (``bedleak = 0``) so the only inter-lake
path is the weir, which isolates the sill behaviour:

* BELOW the sill (both stages < invert) the reciprocal weirs are inert and the
  two lakes stay independent -- no exchange, stages held;
* ABOVE the sill (lac0 > invert) lac0 spills its surplus into lac1 (the
  exploitable-volume transfer) and parks at the invert, while lac1 (still below
  the invert) sends nothing back.

This is the runtime proof behind the reciprocal-direct-weir design: MF6 accepts
and converges with the 2-cycle of direct outlets, and the storage moves the way
the forebay-over-a-sill conceptual model requires.
"""

from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders import (
    apply_lake_idomain_mask,
    build_lak_package_args,
)
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

_CREST = 95.0  # sill crest = both reciprocal weir inverts
_SPILL = 98.0  # spillway crest on lac1 (external)
_NROW, _NCOL = 5, 11


def _two_lake_model(*, strt0: float, strt1: float) -> SimpleNamespace:
    abacus = [(90.0, 0.0, 900.0), (100.0, 9000.0, 900.0)]
    return SimpleNamespace(
        model_output_name="twolake",
        time_units="seconds",
        flow=SimpleNamespace(
            active_bc=["reservoir"],
            sinks_sources={
                "lakes": {
                    "lac0": {
                        "polygon": None,
                        "bedleak": 0.0,  # sealed bed: isolate the weir coupling
                        "abacus": abacus,
                        "stageinit": strt0,
                        "outlets": [
                            {"couttype": "WEIR", "invert": _CREST, "width": 24.0, "lakeout": 2}
                        ],
                    },
                    "lac1": {
                        "polygon": None,
                        "bedleak": 0.0,
                        "abacus": abacus,
                        "stageinit": strt1,
                        "outlets": [
                            {"couttype": "WEIR", "invert": _CREST, "width": 24.0, "lakeout": 1},
                            {"couttype": "WEIR", "invert": _SPILL, "width": 35.0, "lakeout": 0},
                        ],
                    },
                }
            },
        ),
    )


def _run(ws: Path, exe: str, *, strt0: float, strt1: float) -> tuple[dict, dict]:
    import flopy

    top = np.full((_NROW, _NCOL), 100.0)
    botm = np.stack([np.full((_NROW, _NCOL), 90.0), np.full((_NROW, _NCOL), 50.0)])
    mesh = SolverMesh.from_structured_arrays(
        nrow=_NROW, ncol=_NCOL, top=top, botm=botm, dx=10.0, dy=10.0
    )
    # lac0 = west 3x3 block, lac1 = east 3x3 block; the gap (cols 4-6) keeps the
    # footprints cell-disjoint (the sill is a logical weir, no shared cell).
    cells = {
        "lac0": [r * _NCOL + c for r in (1, 2, 3) for c in (1, 2, 3)],
        "lac1": [r * _NCOL + c for r in (1, 2, 3) for c in (7, 8, 9)],
    }
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake=cells)

    model = _two_lake_model(strt0=strt0, strt1=strt1)
    args = build_lak_package_args(model, solver_mesh=masked, lake_cell_ids_by_lake=cells)
    assert args is not None
    # The reciprocal sill weirs route directly (no MVR) and the spillway is external.
    assert args["nlakes"] == 2
    assert args["noutlets"] == 3
    assert "mover" not in args
    assert "mover_records" not in args

    laktab_specs = args.pop("laktab_specs")
    for key in (
        "mover_records",
        "mover_maxpackages",
        "obs_continuous",
        "lake_obs_meta",
        "ts_specs",
    ):
        args.pop(key, None)
    # No lake forcing is declared, so MF6 still needs a (zero) perioddata row.
    args.setdefault("perioddata", {0: [[0, "RAINFALL", 0.0], [1, "RAINFALL", 0.0]]})

    sim = flopy.mf6.MFSimulation(sim_name="twolake", sim_ws=str(ws), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=1, perioddata=[(8.64e6, 10, 1.0)])
    flopy.mf6.ModflowIms(
        sim,
        complexity="MODERATE",
        linear_acceleration="BICGSTAB",
        outer_maximum=200,
        inner_maximum=200,
    )
    gwf = flopy.mf6.ModflowGwf(
        sim, modelname="twolake", save_flows=True, newtonoptions="NEWTON UNDER_RELAXATION"
    )
    flopy.mf6.ModflowGwfdisv(
        gwf, nlay=masked.nlay, idomain=masked.idomain(), **masked.to_disv_kwargs()
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0, k33=0.1, save_flows=True)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=1, sy=0.2, ss=1e-5, transient={0: True})
    flopy.mf6.ModflowGwfic(gwf, strt=95.0)
    chd = [
        [(1, r * _NCOL + c), 80.0]
        for r in range(_NROW)
        for c in range(_NCOL)
        if r in (0, _NROW - 1) or c in (0, _NCOL - 1)
    ]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd})

    lak = flopy.mf6.ModflowGwflak(gwf, pname="LAK", **args)
    for spec in laktab_specs:
        flopy.mf6.ModflowUtllaktab(
            gwf,
            nrow=len(spec["table"]),
            ncol=3,
            table=spec["table"],
            filename=spec["filename"],
            parent_file=lak,
        )
    lak.obs.initialize(
        filename="twolake.lak.obs",
        digits=10,
        print_input=False,
        continuous={
            "twolake.lak.obs.csv": [
                ("stageA", "STAGE", 1),
                ("stageB", "STAGE", 2),
                ("AtoB", "OUTLET", 1),
                ("BtoA", "OUTLET", 2),
                ("Bext", "OUTLET", 3),
            ]
        },
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="twolake.hds",
        budget_filerecord="twolake.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    success, _buff = sim.run_simulation(silent=True)
    assert success, "two-lake reciprocal-weir MF6 run did not converge"

    with open(ws / "twolake.lak.obs.csv") as fh:
        rows = list(csv.reader(fh))
    header = rows[0]
    first = {k: float(v) for k, v in zip(header, rows[1], strict=True)}
    last = {k: float(v) for k, v in zip(header, rows[-1], strict=True)}
    return first, last


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_two_lakes_independent_below_the_sill(tmp_path: Path) -> None:
    # Both lakes start below the sill (92 < 95): the reciprocal weirs are inert
    # and the sealed beds carry no leakage, so the two lakes are fully decoupled.
    first, last = _run(tmp_path, str(ensure_solver_binary("mf6")), strt0=92.0, strt1=92.0)
    for snap in (first, last):
        assert snap["STAGEA"] == pytest.approx(92.0, abs=1e-3)
        assert snap["STAGEB"] == pytest.approx(92.0, abs=1e-3)
        assert snap["ATOB"] == pytest.approx(0.0, abs=1e-9)
        assert snap["BTOA"] == pytest.approx(0.0, abs=1e-9)
        assert snap["BEXT"] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_forebay_spills_its_surplus_over_the_sill(tmp_path: Path) -> None:
    # lac0 starts above the sill (96 > 95), lac1 below (92 < 95): lac0 spills its
    # surplus into lac1 (the exploitable-volume transfer) and parks at the invert,
    # while lac1 -- still below the invert -- sends nothing back.
    first, last = _run(tmp_path, str(ensure_solver_binary("mf6")), strt0=96.0, strt1=92.0)

    # First step: lac0 -> lac1 outflow is active (negative = leaving lac0); the
    # reverse weir stays off because lac1 is below the invert.
    assert first["ATOB"] < 0.0
    assert first["BTOA"] == pytest.approx(0.0, abs=1e-9)

    # The surplus moved from lac0 to lac1: lac0 fell toward the invert, lac1 rose.
    assert last["STAGEA"] < 96.0
    assert last["STAGEA"] == pytest.approx(_CREST, abs=0.05)
    assert last["STAGEB"] > 92.0
    # The spillway never engaged (lac1 stays below its 98 m crest).
    assert last["BEXT"] == pytest.approx(0.0, abs=1e-9)
