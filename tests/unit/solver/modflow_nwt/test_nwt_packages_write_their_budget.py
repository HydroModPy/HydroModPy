"""Every NWT package an extractor reads writes its cell-by-cell budget.

The discharge observable sums the DRAINS record of the ``.cbc`` and the
recharge map reads RECHARGE. DRN and RCH are built without ``ipakcb``; they
reach the budget file only because ``ModflowOc.reset_budgetunit`` rewrites the
unit of every package that carries one. This test pins that contract on the
real package builder, so a change of build order or of OC setup cannot drop
the records silently.
"""

from __future__ import annotations

from types import SimpleNamespace

import flopy
import numpy as np
import pytest

from hydromodpy.solver.modflow_nwt.nwt._pre_processing import assemble_flopy_packages
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowSpecifParams

NLAY, NROW, NCOL, NPER = 2, 3, 4, 2


def _solver(tmp_path) -> SimpleNamespace:
    mf = flopy.modflow.Modflow("tiny", version="mfnwt", model_ws=str(tmp_path))
    top = np.full((NROW, NCOL), 10.0)
    flopy.modflow.ModflowDis(
        mf,
        nlay=NLAY,
        nrow=NROW,
        ncol=NCOL,
        nper=NPER,
        top=top,
        botm=[5.0, 0.0],
        perlen=[1.0, 1.0],
        nstp=[1, 1],
        steady=[True, False],
        itmuni=1,
    )
    return SimpleNamespace(
        mf=mf,
        dis_itmuni=1,
        nlay=NLAY,
        nper=NPER,
        nstp=np.array([1, 1]),
        top_elevation=top,
        model_name="tiny",
        _params=ModflowSpecifParams(),
    )


def _flow_inputs() -> SimpleNamespace:
    shape = (NLAY, NROW, NCOL)
    drn_rows = np.array(
        [[0, i, j, 10.0, 1.0] for i in range(NROW) for j in range(NCOL)], dtype=float
    )
    return SimpleNamespace(
        drain_array=np.ones((NROW, NCOL)),
        chd_spd=None,
        ibound=np.ones(shape, dtype=int),
        strt=np.full(shape, 10.0),
        hk=np.full(shape, 1e-5),
        hk_value=1e-5,
        sy=np.full(shape, 0.05),
        sy_value=0.05,
        ss=np.full(shape, 1e-5),
        ss_value=1e-5,
        rch_data={0: 1e-8, 1: 2e-8},
        evt_spd=None,
        drn_spd={0: drn_rows},
        wel_spd=None,
    )


@pytest.mark.parametrize("package", ["drn", "rch", "upw"])
def test_package_writes_to_the_oc_budget_unit(tmp_path, package: str) -> None:
    solver = _solver(tmp_path)
    assemble_flopy_packages(solver, _flow_inputs(), SimpleNamespace(check_grid=False))

    budget_unit = solver.oc.iubud
    assert budget_unit > 0
    assert getattr(solver, package).ipakcb == budget_unit


def test_written_deck_routes_drn_and_rch_to_the_cbc_file(tmp_path) -> None:
    solver = _solver(tmp_path)
    assemble_flopy_packages(solver, _flow_inputs(), SimpleNamespace(check_grid=False))
    solver.mf.write_input()

    budget_unit = solver.oc.iubud
    name_lines = (tmp_path / "tiny.nam").read_text().splitlines()
    cbc_units = {int(line.split()[1]) for line in name_lines if "tiny.cbc" in line.split()}
    assert cbc_units == {budget_unit}

    # Item 2 of DRN and RCH carries IPAKCB: it must name the cbc unit, not 0.
    drn_item2 = (tmp_path / "tiny.drn").read_text().splitlines()[1].split()
    rch_item2 = (tmp_path / "tiny.rch").read_text().splitlines()[1].split()
    assert int(drn_item2[1]) == budget_unit
    assert int(rch_item2[1]) == budget_unit
