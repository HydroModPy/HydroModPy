"""Rebuilt fields, table columns, trial columns and ``against = <run>`` through ``render``."""

from __future__ import annotations

import numpy as np
import pytest

import hydromodpy as hmp
from hydromodpy.core.exceptions import DisplayError
from hydromodpy.display import render as door
from hydromodpy.display import subject
from hydromodpy.display.request import FigureRequest, expand
from hydromodpy.display.subject import FigureNotApplicable, read_table
from hydromodpy.results.derive.stream_network import cell_fields
from hydromodpy.results.run.geographic import field_range
from hydromodpy.results.session.descriptor import ParameterBound
from tests.unit.display._calibration_journal import journal_session
from tests.unit.display._stored_run import AREAS, N_CELLS, N_PERIODS, write_run

NETWORK = ("simulated_active_network", "network_agreement", "downslope_distance")
ROWS = np.zeros((N_PERIODS, N_CELLS))
ROWS[:, :3] = 1.0  # cells 0 to 2 flow at every step
ROWS[2:, 3] = 1.0  # cell 3 flows from step 2 on, and its area is 500,000 m2
AGREEMENT = np.zeros((N_PERIODS, N_CELLS))
AGREEMENT[:, 0], AGREEMENT[2:, 3] = 1.0, 3.0  # valid at cell 0, mapped only at cell 3 from step 2
DISTANCE = np.full((N_PERIODS, N_CELLS), np.nan)
DISTANCE[:, 0], DISTANCE[2:, 3] = 250.0, 80.0
ROWS_OF = {
    "simulated_active_network": ROWS,
    "network_agreement": AGREEMENT,
    "downslope_distance": DISTANCE,
}


def draw(subject_, data=True, **fields):
    return door.render(FigureRequest(**fields), subject_, data=data)


@pytest.fixture
def rebuilt(monkeypatch):
    real = cell_fields.rebuilt_rows
    monkeypatch.setattr(cell_fields, "rebuilt_unavailable", lambda run, name: None)
    monkeypatch.setattr(
        cell_fields,
        "rebuilt_rows",
        lambda run, name, steps: (
            ROWS_OF[name][list(steps)] if name in NETWORK else real(run, name, steps)
        ),
    )


@pytest.mark.parametrize(
    ("variable", "panel", "expected"),
    [
        ("simulated_active_network", {"time": 3}, [1, 1, 0]),
        ("simulated_active_network", {"reduce": "frequency"}, [1.0, 0.5, 0.0]),
        ("network_agreement", {"time": 3}, [1, 3, 0]),
        ("downslope_distance", {"reduce": "max"}, [250.0, 80.0, np.nan]),
        ("package_cells", {"reduce": "max"}, [2, 2, 2]),  # the drain acts, recharge is no package
        ("depression_fill_depth", {"time": 0}, [0, 0, 0]),  # the slope never holds water
        ("depression_fill_depth", {"time": "last", "reduce": "mean"}, [0, 0, 0]),
    ],
)
def test_a_rebuilt_field_is_drawn_like_a_registered_one(
    stored_run, rebuilt, variable, panel, expected
):
    values = draw(stored_run, variable=variable, **panel)["a"]["value"].to_numpy()
    np.testing.assert_allclose(values[[0, 3, 4]], expected)


def test_the_share_of_the_catchment_that_flows_and_its_distribution(stored_run, rebuilt):
    series = draw(
        stored_run, variable="simulated_active_network", type="series", station="zone:catchment"
    )
    catchment = AREAS[:8].sum()
    flowing = AREAS[:3].sum(), AREAS[:4].sum()
    np.testing.assert_allclose(
        series["a"]["simulated"], [flowing[0] / catchment] * 2 + [flowing[1] / catchment] * 2
    )
    shares = draw(stored_run, variable="downslope_distance", type="distribution", time=3)["a"]
    assert shares["share"].sum() == pytest.approx(1.0)


def test_the_identity_table_prints_registry_labels_and_a_missing_row_is_refused(stored_run):
    names = ["simulation.n_cells", "simulation.n_layers", "simulation.period_start"]
    table = draw(stored_run, variable=names, type="table")["a"]
    assert table["label"].tolist() == ["Model cells", "Layers", "Start"]
    assert table["text"].tolist() == ["12", "2", "2001-01-01"]
    with pytest.raises(ValueError, match="Add a row 'simulation.nse'"):
        expand(FigureRequest(variable="simulation.nse", type="table"), {})
    with pytest.raises(DisplayError, match="trials of a session"):
        door.render(FigureRequest(variable="trials.cost", type="series"), stored_run)


@pytest.fixture
def session(tmp_path):
    bounds = {
        "K": ParameterBound(lower=1e-6, upper=1e-4, search_space="log", units="m/s"),
        "Sy": ParameterBound(lower=0.01, upper=0.3, search_space="identity", units="-"),
    }
    rows = [
        {"trial": i + 1, "cost": c, "parameters": {"K": {"value": k}, "Sy": {"value": sy}}}
        for i, (c, k, sy) in enumerate(zip([4.0, 1.0, 2.0], [1e-5, 2e-5, 4e-5], [0.1, 0.2, 0.3]))
    ]
    return journal_session(tmp_path, rows, bounds=bounds, cost_name="nse_log")


def test_the_trials_are_numbers_one_row_per_trial_and_each_parameter_gets_a_panel(session):
    trials = read_table(session, "trials")
    assert trials.columns.tolist() == ["trial", "phase", "status", "cost", "K", "Sy"]
    np.testing.assert_allclose(trials["K"], [1e-5, 2e-5, 4e-5])
    assert read_table(session, "bounds").index.tolist() == ["K", "Sy"]
    cost = draw(session, variable="trials.cost", type="series")["a"]
    assert cost["trial"].tolist() == [1, 2, 3] and cost["simulated"].tolist() == [4.0, 1.0, 2.0]
    request = {"variable": ["trials.parameter", "trials.cost"], "type": "xy", "facet": "parameter"}
    assert list(draw(session, **request)) == ["a:K", "a:Sy"]
    fig = draw(session, data=False, **request)
    assert [ax.get_xscale() for ax in fig.axes] == ["log", "linear"]
    assert fig.axes[0].get_xlabel().startswith("K (") and fig.axes[1].get_xlabel() == "Sy"
    with pytest.raises(DisplayError, match="session"):
        draw(session, variable="head")


@pytest.fixture
def pair(tmp_path):
    write_run(tmp_path / "proj", "stored")
    write_run(tmp_path / "proj", "other", head_shift=5.0)
    runs = hmp.open(tmp_path / "proj").runs()
    return runs, {run.name: run for run in runs}


def test_a_map_against_a_run_holds_the_difference(pair):
    runset, named = pair
    request = {"variable": "head", "layer": 0, "time": 0, "against": "stored"}
    out = draw(runset, facet="run", **request)
    assert list(out) == ["a:other"]
    np.testing.assert_allclose(out["a:other"]["value"], 5.0)
    single = door.render(FigureRequest(**request), named["other"], data=True, runs=named)
    np.testing.assert_allclose(single["a"]["value"], 5.0)
    fig = door.render(FigureRequest(**request), named["other"], runs=named)
    assert fig.axes[-1].get_ylabel().startswith("Difference in")


def test_against_a_run_is_refused_by_name(pair, monkeypatch):
    runset, named = pair
    request = {"variable": "head", "layer": 0, "against": "stored"}
    with pytest.raises(FigureNotApplicable, match="Runs given: none"):
        draw(named["other"], **request)
    with pytest.raises(
        FigureNotApplicable, match="names no run of the set. Runs held: other, stored"
    ):
        draw(runset, facet="run", **{**request, "against": "nope"})
    with pytest.raises(FigureNotApplicable, match="station|observed"):
        draw(named["other"], variable="discharge", station="zone:catchment", against="stored")
    real = subject.read_table

    def wrong(run, name):
        table = real(run, name)
        return table.assign(mesh_hash="x") if run.name == "other" else table

    monkeypatch.setattr(subject, "read_table", wrong)
    with pytest.raises(FigureNotApplicable, match="mesh differs"):
        draw(runset, facet="run", **request)


def test_a_rebuilt_field_reads_the_same_through_every_door_of_the_run(stored_run, rebuilt):
    name = "network_agreement"
    assert stored_run.has_field(name)
    read = stored_run.read(name)
    assert read.shape == (N_PERIODS, N_CELLS) and read.dims == ("time", "cell")
    np.testing.assert_array_equal(stored_run.read(name, time=slice(1, 3)), AGREEMENT[1:3])
    np.testing.assert_array_equal(read[3], stored_run.field(name, time=3))
    np.testing.assert_array_equal(field_range(stored_run, name, 1, 3), AGREEMENT[1:3])
    x, y = stored_run.mesh.cell_centers()[0]
    inside = stored_run.read(name, time=3, bbox=(x - 1, y - 1, x + 1, y + 1))
    assert inside.shape == (1,) and inside.item() == AGREEMENT[3, 0]
    with pytest.raises(IndexError):
        field_range(stored_run, name, 2, N_PERIODS + 1)


def test_a_cost_is_labelled_by_its_phase_and_a_panel_counts_its_trials(tmp_path):
    bounds = {
        "K": ParameterBound(lower=1e-6, upper=1e-4, search_space="log", units="m/s"),
        "Sy": ParameterBound(lower=0.01, upper=0.3, search_space="log", units="-"),
    }
    rows = [
        {"trial": 1, "phase": "steady", "cost": 900.0, "parameters": {"K": {"value": 1e-5}}},
        {"trial": 2, "phase": "steady", "cost": 800.0, "parameters": {"K": {"value": 2e-5}}},
        {"trial": 3, "phase": "storage", "cost": 0.2, "parameters": {"Sy": {"value": 0.1}}},
        {"trial": 4, "phase": "storage", "cost": 0.1, "parameters": {"Sy": {"value": 0.2}}},
        {
            "trial": 5,
            "phase": "storage",
            "status": "failed",
            "cost": 0.05,
            "parameters": {"Sy": {"value": 0.3}},
        },
    ]
    for row in rows[:2]:
        row["components"] = {"network_extension.raw_cost": row["cost"]}
    for row in rows[2:]:
        row["components"] = {"hydrograph.raw_cost": row["cost"]}
    session = journal_session(tmp_path, rows, bounds=bounds, cost_name="nse_log")
    request = {"variable": ["trials.parameter", "trials.cost"], "type": "xy", "facet": "parameter"}
    fig = draw(session, data=False, **request)
    assert [ax.get_title() for ax in fig.axes] == ["K, 2 of 5 trials", "Sy, 2 of 5 trials"]
    assert [ax.get_ylabel() for ax in fig.axes] == ["network_extension cost", "nse_log"]
    fig = draw(session, data=False, variable="trials.cost", type="series")
    assert [ax.get_title() for ax in fig.axes] == [
        "steady, 2 of 5 trials",
        "storage, 2 of 5 trials",
    ]
    assert [ax.get_ylabel() for ax in fig.axes] == ["network_extension cost", "nse_log"]
    with pytest.raises(FigureNotApplicable, match="one output each"):
        subject.read_trial_column(session, "trials.cost")
