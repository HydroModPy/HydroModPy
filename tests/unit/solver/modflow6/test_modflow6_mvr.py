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


def _with_receivers(model, *, nreaches=None, nlakes=None):
    if nreaches is not None:
        model.sfr = SimpleNamespace(nreaches=SimpleNamespace(get_data=lambda: nreaches))
    if nlakes is not None:
        model.lak = SimpleNamespace(nlakes=SimpleNamespace(get_data=lambda: nlakes))
    return model


MISSING_RECEIVERS = [
    pytest.param({"nlakes": 1}, ["LAK", 0, "SFR", 0, "FACTOR", 1.0], "no SFR package", id="no SFR"),
    pytest.param(
        {"nlakes": 1, "nreaches": 10},
        ["LAK", 0, "SFR", 98, "FACTOR", 1.0],
        "SFR feature 99 .* 10",
        id="reach 99 of 10",
    ),
    pytest.param(
        {"nreaches": 3}, ["SFR", 2, "LAK", 0, "FACTOR", 1.0], "no LAK package", id="no LAK"
    ),
    pytest.param(
        {"nreaches": 3, "nlakes": 1},
        ["SFR", 2, "LAK", 1, "FACTOR", 1.0],
        "LAK feature 2 .* 1",
        id="lake 2 of 1",
    ),
]


@pytest.mark.parametrize(("sizes", "row", "message"), MISSING_RECEIVERS)
def test_a_mover_to_a_missing_receiver_is_refused_by_name(tmp_path, sizes, row, message) -> None:
    # MF6 stops on such a record with a message that names no config key, or
    # moves the water to the wrong reach when the id happens to exist.
    model = _with_receivers(flow_model(tmp_path), **sizes)
    with pytest.raises(ValueError, match=message):
        build_mover_and_output(model, [row])


def test_a_mover_to_an_existing_reach_is_kept(tmp_path) -> None:
    model = _with_receivers(flow_model(tmp_path), nreaches=10, nlakes=1)
    build_mover_and_output(model, [["LAK", 0, "SFR", 9, "FACTOR", 1.0]])
    assert model.mvr.maxmvr.get_data() == 1
