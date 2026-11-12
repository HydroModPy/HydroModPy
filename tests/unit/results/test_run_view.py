"""What a Run reads from the index of a sealed simulation.

Identity facts (name, project, solver), the parameter, budget and mass balance
tables, one stored field, and the figures a run can render.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.results.run.view import Run
from tests._helpers.run_builders import MISSING_SIM_ID, populate, runs

__all__ = ["runs"]


def test_identity_properties(runs):
    sid = runs.open("run1", flow_regime="transient").sim_id
    sim = Run(sid, runs.catalog())

    assert sim.sim_id == sid
    assert sim.name == "run1"
    assert sim.project == "test"
    assert sim.solver == "modflow6"
    assert sim.flow_regime == "transient"
    assert sim.status == "completed"


def test_repr_names_project_and_solver(runs):
    sid = runs.open().sim_id

    text = repr(Run(sid, runs.catalog()))

    assert "test" in text
    assert "modflow6" in text


def test_repr_of_a_missing_run(runs):
    runs.open()

    assert "not found" in repr(Run(MISSING_SIM_ID, runs.catalog()))


def test_parameters(runs):
    store = runs.open()
    populate(store)
    sim = Run(store.sim_id, runs.catalog())

    # Homogeneous-only payload: simple index by param_name, no zone_id.
    assert set(sim.parameters.index) == {"K", "Sy"}
    assert "value" in sim.parameters.columns
    assert sim.parameters.loc["K", "value"] == pytest.approx(1.5)


def test_budget_and_mass_balance(runs):
    store = runs.open()
    populate(store)
    sim = Run(store.sim_id, runs.catalog())

    assert len(sim.budget(component="recharge")) == 1
    assert len(sim.mass_balance) == 1


def test_field_shape(runs):
    store = runs.open(n_cells=20, n_layers=2, n_timesteps=3)
    sid = store.sim_id
    for t in range(3):
        store.write_field(sid, "head", t, np.ones((2, 20)), n_timesteps=3 if t == 0 else None)

    result = Run(sid, runs.catalog()).field("head", time=1)

    assert result.shape == (2, 20)


def test_a_figure_needing_a_missing_table_is_unavailable(runs):
    # A figure is available when the run meets its declared requirements.
    sid = runs.open(n_cells=10, n_layers=1, flow_regime="steady").sim_id
    sim = Run(sid, runs.catalog())

    reason = get_figure("water_budget").unavailable_reason(sim)

    assert reason is not None
    assert "budgets" in reason


def test_the_name_of_a_missing_run_is_refused(runs):
    runs.open()
    sim = Run(MISSING_SIM_ID, runs.catalog())

    with pytest.raises(KeyError):
        _ = sim.name


def test_an_unknown_station_is_refused(runs):
    sim = Run(runs.open().sim_id, runs.catalog())

    with pytest.raises(KeyError):
        sim.timeseries("head", station="NOPE")
