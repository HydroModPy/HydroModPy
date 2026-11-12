"""The MVR record builder, which knows nothing about LAK.

It formats and validates transfers between any two named packages (SFR, LAK, MAW).
A record is [provider package, provider id, receiver package, receiver id, mvrtype,
value], with value a fraction or a rate depending on mvrtype.
"""

from __future__ import annotations

from types import SimpleNamespace

import flopy
import pytest

from hydromodpy.solver.modflow6.builders.mvr import (
    MoverRecord,
    build_mover_and_output,
    build_mvr_period_records,
    mover_package_count,
)


def test_records_keep_their_packages_and_ids() -> None:
    moves = [
        MoverRecord("SFR-1", 2, "LAK-1", 0, "FACTOR", 1.0),
        MoverRecord("MAW-1", 1, "SFR-1", 5, "UPTO", 3.0),
    ]

    records = build_mvr_period_records(moves)

    assert records == [
        ["SFR-1", 2, "LAK-1", 0, "FACTOR", 1.0],
        ["MAW-1", 1, "SFR-1", 5, "UPTO", 3.0],
    ]
    assert mover_package_count(records) == 3  # SFR-1, LAK-1 and MAW-1


REFUSALS = [
    pytest.param(
        MoverRecord("SFR-1", 0, "LAK-1", 0, "SIPHON", 1.0),
        "mvrtype must be one of",
        id="unknown mvrtype",
    ),
    pytest.param(
        MoverRecord("SFR-1", 0, "LAK-1", 0, "FACTOR", -1.0),
        "value must be >= 0",
        id="negative value",
    ),
]


@pytest.mark.parametrize(("move", "message"), REFUSALS)
def test_refusals(move, message) -> None:
    with pytest.raises(ValueError, match=message):
        build_mvr_period_records([move])


def flow_model(tmp_path) -> SimpleNamespace:
    sim = flopy.mf6.MFSimulation(sim_name="mvr", sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow")
    runtime = SimpleNamespace(print_head=False)
    return SimpleNamespace(
        gwf=gwf, model_output_name="flow", modflow_config=SimpleNamespace(runtime=runtime)
    )


def test_mover_package_lists_every_named_package(tmp_path) -> None:
    model = flow_model(tmp_path)
    rows = [["SFR-1", 2, "LAK-1", 0, "FACTOR", 1.0], ["LAK-1", 0, "SFR-1", 5, "UPTO", 3.0]]

    build_mover_and_output(model, rows)

    assert model.mvr.maxmvr.get_data() == 2
    assert model.mvr.maxpackages.get_data() == 2  # SFR-1 and LAK-1
    assert [tuple(p) for p in model.mvr.packages.get_data()] == [("LAK-1",), ("SFR-1",)]
    assert model.oc.head_filerecord.get_data()[0][0] == "flow.hds"


def test_no_mover_package_without_a_transfer(tmp_path) -> None:
    model = flow_model(tmp_path)

    build_mover_and_output(model, [])

    assert not hasattr(model, "mvr")
    assert model.oc.budget_filerecord.get_data()[0][0] == "flow.cbc"
