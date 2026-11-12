"""Declared observation points are run artifacts, so a rebuilt index keeps them."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
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


def _points(root):
    with Catalog(root) as catalog:
        return catalog.backend.query(
            "SELECT station_id, cell_id, layer FROM observation_points ORDER BY station_id"
        )


def _series(root):
    with Catalog(root) as catalog:
        return catalog.backend.query(
            "SELECT station_id, variable, timestep, value FROM timeseries "
            "WHERE station_id LIKE 'obs:%' ORDER BY station_id, variable, timestep"
        )


class TestSampling:
    def test_the_run_exposes_its_points(self, project):
        root, sid = project
        with Catalog(root) as catalog:
            frame = catalog[sid].probe.declared
        assert frame["station_id"].tolist() == ["piezo_a", "piezo_b"]

    def test_a_point_outside_the_mesh_is_skipped_not_fatal(self, tmp_path):
        root = tmp_path / "outside"
        with _open_run(root, "probe_run") as store:
            written = sample_observation_points(
                store,
                store.sim_id,
                [
                    {
                        "id": "far",
                        "x": 99.0,
                        "y": 99.0,
                        "layer": None,
                        "depth": None,
                        "variables": ["head"],
                    }
                ],
            )
        assert written == 0

    @pytest.mark.parametrize(
        ("unnamed_first", "expected"),
        [(True, {"obs:piezo_b"}), (False, {"obs:piezo_a", "obs:piezo_b"})],
        ids=["first point has no descriptor", "every point has one"],
    )
    def test_a_variable_without_descriptor_skips_only_its_point(
        self, tmp_path, monkeypatch, unnamed_first, expected
    ):
        import hydromodpy.results.run.observation_points as module

        real = module.read_point

        def read(run, variables, request):
            frame = real(run, variables, request)
            if unnamed_first and request.label == "piezo_a":
                frame["variable"] = "a_name_no_descriptor_holds"
            return frame

        monkeypatch.setattr(module, "read_point", read)
        root = tmp_path / "unnamed"
        store = _open_run(root, "probe_run")
        sample_observation_points(store, store.sim_id, DECLARATIONS)
        seal_completed(store)
        rebuild_index(root)
        assert set(_series(root)["station_id"]) == expected

    def test_no_declaration_writes_nothing(self, tmp_path):
        root = tmp_path / "empty"
        with _open_run(root, "probe_run") as store:
            assert sample_observation_points(store, store.sim_id, []) == 0


class TestConfigSection:
    def test_layer_and_depth_are_exclusive(self):
        with pytest.raises(ValueError, match="keep one"):
            ObservationConfig.model_validate(
                {"points": [{"id": "p", "x": 1.0, "y": 2.0, "layer": 0, "depth": 3.0}]}
            )

    def test_duplicate_ids_are_refused(self):
        with pytest.raises(ValueError, match="Duplicate"):
            ObservationConfig.model_validate(
                {"points": [{"id": "p", "x": 1.0, "y": 2.0}, {"id": "p", "x": 3.0, "y": 4.0}]}
            )
