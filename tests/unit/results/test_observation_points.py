"""Declared observation points are run artefacts, so a rebuilt index keeps them."""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.reindex import rebuild_index
from hydromodpy.results.run.observation_points import station_id_for
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX, TABLES_DIRNAME
from hydromodpy.simulation.planning.observation_config import ObservationConfig

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


def _seal_run(catalog: Catalog, name: str) -> str:
    sid = str(uuid.uuid4())
    registration = catalog.register_simulation(
        sid,
        project="demo",
        solver="modflow6",
        name=name,
        flow_regime="transient",
        n_cells=N_CELLS,
        n_layers=N_LAYERS,
        n_timesteps=N_STEPS,
        bbox=[0.0, 0.0, 2.0, 1.0],
        crs="EPSG:2154",
        config={"flow": {"hk": 1e-5}},
    )
    if registration.zarr is not None:
        registration.zarr.close()
    store_zarr = catalog.open_zarr(sid)
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
    catalog.write_time(
        sid,
        np.array([1577836800, 1577923200], dtype="int64"),
        units="seconds since 1970-01-01T00:00:00Z",
    )
    for step in range(N_STEPS):
        head = np.array([[1.0 + step, 2.0 + step], [0.5 + step, 1.5 + step]], dtype="float64")
        catalog.write_field(sid, "head", step, head, n_timesteps=N_STEPS if step == 0 else None)
    return sid


@pytest.fixture
def project(tmp_path):
    """A project with one sealed run that declared two observation points."""
    root = tmp_path / "demo"
    with Catalog(root) as catalog:
        sid = _seal_run(catalog, "probe_run")
        catalog.sample_observation_points(sid, DECLARATIONS)
        catalog.finalize(sid, status="completed", duration_s=1.0)
    return root, sid


def _points(root):
    with Catalog(root, read_only=True) as catalog:
        return catalog.backend.query(
            "SELECT station_id, cell_id, layer FROM observation_points ORDER BY station_id"
        )


def _series(root):
    with Catalog(root, read_only=True) as catalog:
        return catalog.backend.query(
            "SELECT station_id, variable, timestep, value FROM timeseries "
            "WHERE station_id LIKE 'obs:%' ORDER BY station_id, variable, timestep"
        )


class TestSampling:
    def test_every_declared_point_is_resolved(self, project):
        root, _ = project
        frame = _points(root)
        assert frame["station_id"].tolist() == ["piezo_a", "piezo_b"]
        assert frame["cell_id"].tolist() == [0, 1]

    def test_the_depth_picked_the_layer(self, project):
        root, _ = project
        frame = _points(root)
        assert frame.set_index("station_id").loc["piezo_b", "layer"] == 1

    def test_each_variable_has_its_series(self, project):
        root, _ = project
        frame = _series(root)
        assert set(zip(frame["station_id"], frame["variable"], strict=True)) == {
            ("obs:piezo_a", "head"),
            ("obs:piezo_b", "head"),
            ("obs:piezo_b", "watertable_depth"),
        }

    def test_the_series_holds_the_cell_value(self, project):
        root, _ = project
        frame = _series(root)
        head_a = frame[(frame["station_id"] == "obs:piezo_a") & (frame["variable"] == "head")]
        assert head_a["value"].tolist() == [1.0, 2.0]

    def test_the_station_id_is_prefixed(self, project):
        assert station_id_for("piezo_a") == "obs:piezo_a"

    def test_the_declaration_lands_in_the_run_directory(self, project):
        root, sid = project
        with Catalog(root, read_only=True) as catalog:
            payload = (
                catalog.run_dir_for(sid)
                / TABLES_DIRNAME
                / f"observation_points{PARQUET_FILE_SUFFIX}"
            )
        assert payload.is_file()

    def test_the_run_exposes_its_points(self, project):
        root, sid = project
        with Catalog(root, read_only=True) as catalog:
            frame = catalog[sid].probe.declared
        assert frame["station_id"].tolist() == ["piezo_a", "piezo_b"]

    def test_a_point_outside_the_mesh_is_skipped_not_fatal(self, tmp_path):
        root = tmp_path / "outside"
        with Catalog(root) as catalog:
            sid = _seal_run(catalog, "probe_run")
            written = catalog.sample_observation_points(
                sid,
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

    def test_no_declaration_writes_nothing(self, tmp_path):
        root = tmp_path / "empty"
        with Catalog(root) as catalog:
            sid = _seal_run(catalog, "probe_run")
            assert catalog.sample_observation_points(sid, []) == 0


class TestSurvivesReindex:
    def test_the_points_come_back_after_the_index_is_deleted(self, project):
        root, _ = project
        before = _points(root)
        catalog_path_for(root).unlink()

        rebuild_index(root)

        assert _points(root).equals(before)

    def test_the_series_come_back_after_the_index_is_deleted(self, project):
        root, _ = project
        before = _series(root)
        catalog_path_for(root).unlink()

        rebuild_index(root)

        assert _series(root).equals(before)


class TestConfigSection:
    def test_the_section_defaults_to_no_point(self):
        assert ObservationConfig().points == []

    def test_a_point_inherits_the_section_variables(self):
        cfg = ObservationConfig.model_validate(
            {"variables": ["head", "seepage_mask"], "points": [{"id": "p", "x": 1.0, "y": 2.0}]}
        )
        assert cfg.declarations()[0]["variables"] == ["head", "seepage_mask"]

    def test_a_point_may_name_its_own_variables(self):
        cfg = ObservationConfig.model_validate(
            {"points": [{"id": "p", "x": 1.0, "y": 2.0, "variables": ["watertable_depth"]}]}
        )
        assert cfg.declarations()[0]["variables"] == ["watertable_depth"]

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

    def test_an_unknown_key_is_refused(self):
        with pytest.raises(ValueError):
            ObservationConfig.model_validate({"pointz": []})
