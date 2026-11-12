"""Declared observation points are run artifacts, so a rebuilt index keeps them.

The run has 2 cells of 1 m by 1 m, 2 layers of 5 m and 2 time steps. A point is sampled
at its x, y (m) in the layer given or at the depth given (m).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.run import observation_points
from hydromodpy.results.run.observation_points import sample_observation_points
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.solver.base.observation_config import ObservationConfig
from tests._helpers.run_stores import open_run_store

VERTICES = np.array(
    [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [0.0, 1.0], [1.0, 1.0], [2.0, 1.0]],
    dtype="float64",
)
CONNECTIVITY = np.array([[0, 1, 4, 3], [1, 2, 5, 4]], dtype="int32")
N_CELLS = 2
N_LAYERS = 2
N_STEPS = 2

DECLARATIONS = [
    {"id": "piezo_a", "x": 0.5, "y": 0.5, "layer": 0, "depth": None, "variables": ["head"]},
    {
        "id": "piezo_b",
        "x": 1.5,
        "y": 0.5,
        "layer": None,
        "depth": 7.0,
        "variables": ["head", "watertable_depth"],
    },
]


def _open_run(root: Path, name: str) -> RunStore:
    """Open a transient two-layer run with its mesh, its clock and its head."""
    store = open_run_store(
        root,
        name,
        n_cells=N_CELLS,
        n_layers=N_LAYERS,
        n_timesteps=N_STEPS,
        flow_regime="transient",
        bbox=(0.0, 0.0, 2.0, 1.0),
        crs_epsg=2154,
        crs_wkt="EPSG:2154",
    )
    sid = store.sim_id
    store_zarr = store.open_zarr(sid)
    try:
        store_zarr.write_mesh(
            VERTICES,
            CONNECTIVITY,
            np.array([10.0, 5.0, 0.0]),
            topography=np.full(N_CELLS, 10.0),
            layer_thickness=np.full((N_LAYERS, N_CELLS), 5.0),
        )
    finally:
        store_zarr.close()
    store.write_time(
        sid,
        np.array([1577836800, 1577923200], dtype="int64"),
        units="seconds since 1970-01-01T00:00:00Z",
    )
    for step in range(N_STEPS):
        head = np.array([[1.0 + step, 2.0 + step], [0.5 + step, 1.5 + step]], dtype="float64")
        store.write_field(sid, "head", step, head, n_timesteps=N_STEPS if step == 0 else None)
    return store


@pytest.fixture
def project(tmp_path):
    """A project with one sealed run that declared two observation points."""
    root = tmp_path / "demo"
    store = _open_run(root, "probe_run")
    sid = store.sim_id
    sample_observation_points(store, sid, DECLARATIONS)
    seal_completed(store)
    rebuild_index(root)
    return root, sid


def _series(root):
    with Catalog(root) as catalog:
        return catalog.backend.query(
            "SELECT station_id, variable, timestep, value FROM timeseries "
            "WHERE station_id LIKE 'obs:%' ORDER BY station_id, variable, timestep"
        )


def test_run_exposes_its_points(project):
    root, sid = project
    with Catalog(root) as catalog:
        frame = catalog[sid].probe.declared
    assert frame["station_id"].tolist() == ["piezo_a", "piezo_b"]


def test_point_outside_the_mesh_is_skipped(tmp_path):
    far = {"id": "far", "x": 99.0, "y": 99.0, "layer": None, "depth": None, "variables": ["head"]}
    with _open_run(tmp_path / "outside", "probe_run") as store:
        written = sample_observation_points(store, store.sim_id, [far])
    assert written == 0


UNNAMED = [
    pytest.param(True, {"obs:piezo_b"}, id="first point has no descriptor"),
    pytest.param(False, {"obs:piezo_a", "obs:piezo_b"}, id="every point has one"),
]


@pytest.mark.parametrize(("unnamed_first", "expected"), UNNAMED)
def test_variable_without_descriptor_skips_its_point(
    tmp_path, monkeypatch, unnamed_first, expected
):
    real = observation_points.read_point

    def read(run, variables, request):
        frame = real(run, variables, request)
        if unnamed_first and request.label == "piezo_a":
            frame["variable"] = "a_name_no_descriptor_holds"
        return frame

    monkeypatch.setattr(observation_points, "read_point", read)
    root = tmp_path / "unnamed"
    store = _open_run(root, "probe_run")
    sample_observation_points(store, store.sim_id, DECLARATIONS)
    seal_completed(store)
    rebuild_index(root)
    assert set(_series(root)["station_id"]) == expected


def test_no_declaration_writes_nothing(tmp_path):
    with _open_run(tmp_path / "empty", "probe_run") as store:
        assert sample_observation_points(store, store.sim_id, []) == 0


CONFIG_REFUSALS = [
    pytest.param(
        [{"id": "p", "x": 1.0, "y": 2.0, "layer": 0, "depth": 3.0}],
        "keep one",
        id="layer and depth",
    ),
    pytest.param(
        [{"id": "p", "x": 1.0, "y": 2.0}, {"id": "p", "x": 3.0, "y": 4.0}],
        "Duplicate",
        id="duplicate ids",
    ),
]


@pytest.mark.parametrize(("points", "match"), CONFIG_REFUSALS)
def test_config_refusals(points, match):
    with pytest.raises(ValueError, match=match):
        ObservationConfig.model_validate({"points": points})
