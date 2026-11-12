"""A run written through its store reads back through the catalog.

Fields are written in the compact precision, so they come back within
``MAX_RELATIVE_ERROR``. The mass balance error is in percent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.fields.precision import MAX_RELATIVE_ERROR
from hydromodpy.results.storage.array_fingerprint import fingerprint
from tests._helpers.run_builders import runs

__all__ = ["runs"]


def _make_mesh():
    vertices = np.array(
        [
            [0.0, 0.0],
            [2.0, 0.0],
            [1.0, 1.0],
            [0.0, 2.0],
            [2.0, 2.0],
        ]
    )
    connectivity = np.array(
        [
            [0, 1, 2],
            [1, 4, 2],
            [2, 4, 3],
            [0, 2, 3],
        ],
        dtype="int32",
    )
    z_interfaces = np.array([0.0, -5.0, -15.0])
    return vertices, connectivity, z_interfaces


def test_field_roundtrip(runs):
    n_cells, n_layers, n_steps = 4, 2, 5
    vertices, connectivity, interfaces = _make_mesh()
    store = runs.open(
        "test_run", solver="modflow_nwt", n_cells=n_cells, n_layers=n_layers, n_timesteps=n_steps
    )
    sid = store.sim_id
    store.write_mesh(sid, vertices, connectivity, interfaces)
    values = np.random.default_rng(42).random((n_steps, n_layers, n_cells))
    for step in range(n_steps):
        store.write_field(
            sid, "head", step, values[step], n_timesteps=n_steps if step == 0 else None
        )

    catalog = runs.catalog()

    # Stored in the compact precision: equal within its relative bound.
    result = catalog.query_field(sid, "head", 2)
    np.testing.assert_allclose(result, values[2], rtol=MAX_RELATIVE_ERROR, atol=0.0)
    top_layer = catalog.query_field(sid, "head", 2, layer=0)
    np.testing.assert_allclose(top_layer, values[2, 0], rtol=MAX_RELATIVE_ERROR, atol=0.0)


def test_list_simulations(runs):
    runs.open("run_a")

    frame = runs.catalog().list_simulations()

    assert list(frame["name"]) == ["run_a"]
    assert runs.catalog().list_simulations(solver="gr4j").empty


def test_timeseries_roundtrip(runs):
    store = runs.open(solver="gr4j")
    index = pd.date_range("2020-01-01", periods=30, freq="D")
    series = pd.Series(np.random.default_rng(7).random(30), index=index, name="discharge")
    store.write_timeseries(store.sim_id, "EXU", "discharge", series, unit="m3/s")

    result = runs.catalog().query_timeseries(store.sim_id, "EXU", "discharge")

    assert len(result) == 30
    np.testing.assert_array_almost_equal(result.values, series.values)


def test_budget_roundtrip(runs):
    store = runs.open(solver="modflow_nwt")
    for step in range(5):
        store.write_budget(store.sim_id, step, "domain", "recharge", 100.0 + step, 0.0)
        store.write_budget(store.sim_id, step, "domain", "drain", 0.0, 80.0 + step)

    catalog = runs.catalog()

    assert len(catalog.query_budget(store.sim_id)) == 10
    assert len(catalog.query_budget(store.sim_id, zone_id="domain", steps=(1, 3))) == 6


def test_mass_balance_roundtrip(runs):
    store = runs.open(solver="modflow_nwt")
    for step in range(3):
        store.write_mass_balance(store.sim_id, step, 1000.0, 995.0, 0.5)

    frame = runs.catalog().query_mass_balance(store.sim_id)

    assert len(frame) == 3
    assert frame.iloc[0]["percent_error"] == pytest.approx(0.5)


def test_provenance_roundtrip_and_verify(runs):
    store = runs.open(solver="modflow_nwt")
    data = np.random.default_rng(99).random((365, 100))
    store.write_provenance(store.sim_id, "recharge", "recharge/sim2", data)

    frame = runs.catalog().get_provenance(store.sim_id, "recharge")

    assert len(frame) == 1
    assert frame.iloc[0]["source_ref"] == "recharge/sim2"
    # The stored checksum tells an altered array from the original.
    stored_checksum = frame.iloc[0]["payload_sha256"]
    assert fingerprint(data)["checksum"] == stored_checksum
    altered = data.copy()
    altered[0, 0] += 0.001
    assert fingerprint(altered)["checksum"] != stored_checksum


def test_two_runs_differ_by_their_heads(runs):
    n_cells, n_layers = 10, 1
    first = runs.open(n_cells=n_cells, n_layers=n_layers, n_timesteps=1)
    second = runs.open(n_cells=n_cells, n_layers=n_layers, n_timesteps=1)
    first.write_field(first.sim_id, "head", 0, np.ones((n_layers, n_cells)), n_timesteps=1)
    second.write_field(second.sim_id, "head", 0, np.full((n_layers, n_cells), 2.0), n_timesteps=1)

    catalog = runs.catalog()
    diff = (
        catalog.query_field(first.sim_id, "head", 0).ravel()
        - catalog.query_field(second.sim_id, "head", 0).ravel()
    )

    assert float(diff.mean()) == pytest.approx(-1.0)
    assert float(np.sqrt((diff**2).mean())) == pytest.approx(1.0)
