"""Point interrogation of a finished run: cell, layer, virtual fields, caches."""

from __future__ import annotations

import json
import uuid

import numpy as np
import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.run.point import (
    POINT_COLUMNS,
    PointOutsideMeshError,
    PointRequest,
    read_point,
    read_points,
    resolve_point,
    write_point_table,
)
from hydromodpy.results.spatial_index import (
    CellLocator,
    cell_index_cache_dir,
    clear_locator_cache,
    locator_for,
    point_in_cell,
)

# A 2x2 grid of unit squares: cells 0..3, centres at (0.5, 0.5) ... (1.5, 1.5).
VERTICES = np.array(
    [
        [0.0, 0.0],
        [1.0, 0.0],
        [2.0, 0.0],
        [0.0, 1.0],
        [1.0, 1.0],
        [2.0, 1.0],
        [0.0, 2.0],
        [1.0, 2.0],
        [2.0, 2.0],
    ],
    dtype="float64",
)
CONNECTIVITY = np.array(
    [[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]],
    dtype="int32",
)
N_CELLS = 4
N_LAYERS = 2
N_STEPS = 3


def _make_run(root, *, name: str = "probe", offset: float = 0.0) -> tuple[Catalog, str]:
    """Seal one transient two-layer run whose head is a known function."""
    catalog = Catalog(root)
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
        bbox=[0.0, 0.0, 2.0, 2.0],
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
        np.array([1577836800, 1577923200, 1578009600], dtype="int64"),
        units="seconds since 1970-01-01T00:00:00Z",
    )
    for step in range(N_STEPS):
        head = np.array(
            [[cell + 10 * step + offset for cell in range(N_CELLS)] for _ in range(N_LAYERS)],
            dtype="float64",
        )
        head[1] -= 0.5  # a vertical gradient, so the layer choice is observable
        catalog.write_field(sid, "head", step, head, n_timesteps=N_STEPS if step == 0 else None)
    catalog.finalize(sid, status="completed", duration_s=1.0)
    return catalog, sid


@pytest.fixture
def run(tmp_path):
    clear_locator_cache()
    catalog, sid = _make_run(tmp_path / "demo")
    with catalog:
        yield catalog[sid]


# -- locating ---------------------------------------------------------------


class TestRequest:
    def test_coordinates_or_cell_but_not_both(self):
        with pytest.raises(ValueError, match="not both"):
            PointRequest(x=0.5, y=0.5, cell=1)

    def test_one_of_them_is_required(self):
        with pytest.raises(ValueError, match="not both"):
            PointRequest()

    def test_half_a_coordinate_is_refused(self):
        with pytest.raises(ValueError, match="both x and y"):
            PointRequest(x=0.5, cell=None)

    def test_layer_and_depth_are_exclusive(self):
        with pytest.raises(ValueError, match="not both"):
            PointRequest(cell=0, layer=1, depth=2.0)


class TestResolve:
    def test_coordinates_land_in_the_containing_cell(self, run):
        assert resolve_point(run, PointRequest(x=1.5, y=0.5)).cell == 1

    def test_a_point_outside_the_mesh_is_named_as_such(self, run):
        with pytest.raises(PointOutsideMeshError):
            resolve_point(run, PointRequest(x=9.0, y=9.0))

    def test_a_cell_index_reports_its_centroid(self, run):
        point = resolve_point(run, PointRequest(cell=3))
        assert (point.x, point.y) == (1.5, 1.5)

    def test_an_out_of_range_cell_is_refused(self, run):
        with pytest.raises(IndexError, match="out of range"):
            resolve_point(run, PointRequest(cell=99))

    def test_depth_picks_the_layer_from_the_thicknesses(self, run):
        assert resolve_point(run, PointRequest(cell=0, depth=2.0)).layer == 0
        assert resolve_point(run, PointRequest(cell=0, depth=7.0)).layer == 1

    def test_depth_below_the_model_stays_in_the_last_layer(self, run):
        assert resolve_point(run, PointRequest(cell=0, depth=500.0)).layer == 1

    def test_a_negative_layer_counts_from_the_bottom(self, run):
        assert resolve_point(run, PointRequest(cell=0, layer=-1)).layer == 1


# -- reading ----------------------------------------------------------------


class TestReadPoint:
    def test_a_transient_run_answers_one_row_per_timestep(self, run):
        frame = run.probe.series("head", cell=1)
        assert list(frame.columns) == list(POINT_COLUMNS)
        assert len(frame) == N_STEPS
        assert frame["value"].tolist() == [1.0, 11.0, 21.0]

    def test_the_series_carries_the_solver_calendar(self, run):
        frame = run.probe.series("head", cell=1)
        assert str(frame["time"].iloc[0]) == "2020-01-01 00:00:00"

    def test_the_layer_selects_the_vertical_position(self, run):
        assert run.probe.series("head", cell=1, layer=1)["value"].tolist() == [0.5, 10.5, 20.5]

    def test_one_timestep_returns_one_row(self, run):
        frame = run.probe.series("head", cell=1, timestep=-1)
        assert len(frame) == 1
        assert frame["timestep"].iloc[0] == N_STEPS - 1

    def test_an_out_of_range_timestep_is_refused(self, run):
        with pytest.raises(IndexError, match="out of range"):
            run.probe.series("head", cell=1, timestep=9)

    def test_several_variables_stack(self, run):
        frame = run.probe.series(["head", "watertable_depth"], cell=1)
        assert set(frame["variable"]) == {"head", "watertable_depth"}
        assert len(frame) == 2 * N_STEPS

    def test_a_virtual_field_reads_like_a_persisted_one(self, run):
        frame = run.probe.series("watertable_depth", cell=1)
        reference = [float(run.field("watertable_depth", timestep=t)[1]) for t in range(N_STEPS)]
        assert frame["value"].tolist() == reference

    def test_the_point_matches_the_full_field(self, run):
        frame = run.probe.series("head", cell=2, layer=0)
        reference = [float(run.field("head", timestep=t, layer=0)[2]) for t in range(N_STEPS)]
        assert frame["value"].tolist() == reference

    def test_an_unknown_field_is_named(self, run):
        with pytest.raises(KeyError, match="nosuchfield"):
            run.probe.series("nosuchfield", cell=0)

    def test_coordinates_and_cell_index_agree(self, run):
        by_xy = run.probe.series("head", x=1.5, y=0.5)["value"].tolist()
        assert by_xy == run.probe.series("head", cell=1)["value"].tolist()


class TestWriteTable:
    def test_csv_round_trips(self, run, tmp_path):
        import pandas as pd

        dest = write_point_table(run.probe.series("head", cell=1), tmp_path / "p.csv")
        assert pd.read_csv(dest)["value"].tolist() == [1.0, 11.0, 21.0]

    def test_parquet_round_trips(self, run, tmp_path):
        import pandas as pd

        dest = write_point_table(run.probe.series("head", cell=1), tmp_path / "p.parquet")
        assert pd.read_parquet(dest)["value"].tolist() == [1.0, 11.0, 21.0]

    def test_the_output_argument_writes_and_still_returns(self, run, tmp_path):
        dest = tmp_path / "out.csv"
        frame = run.probe.series("head", cell=1, output=dest)
        assert dest.is_file()
        assert len(frame) == N_STEPS

    def test_an_unknown_extension_is_refused(self, run, tmp_path):
        with pytest.raises(ValueError, match="use .csv or .parquet"):
            write_point_table(run.probe.series("head", cell=1), tmp_path / "p.xlsx")


# -- several runs at once ---------------------------------------------------


def test_the_same_point_reads_across_runs(tmp_path):
    clear_locator_cache()
    root = tmp_path / "demo"
    catalog, first = _make_run(root, name="base")
    catalog.close()
    catalog, second = _make_run(root, name="scenario", offset=100.0)
    with catalog:
        frame = read_points([catalog[first], catalog[second]], "head", PointRequest(x=1.5, y=0.5))
    assert set(frame["run"]) == {"base", "scenario"}
    assert frame.loc[frame["run"] == "scenario", "value"].tolist() == [101.0, 111.0, 121.0]


def test_a_runset_reads_the_same_point_on_every_run(tmp_path):
    clear_locator_cache()
    root = tmp_path / "demo"
    catalog, _ = _make_run(root, name="base")
    catalog.close()
    catalog, _ = _make_run(root, name="scenario", offset=100.0)
    with catalog:
        frame = catalog.find(project="demo").probe.series("head", cell=1)
    assert set(frame["run"]) == {"base", "scenario"}


# -- the point-to-cell caches -----------------------------------------------


class TestLocatorCache:
    def test_the_same_fingerprint_returns_the_same_locator(self):
        clear_locator_cache()
        first = locator_for(VERTICES, CONNECTIVITY, fingerprint="abc")
        assert locator_for(VERTICES, CONNECTIVITY, fingerprint="abc") is first

    def test_a_different_fingerprint_builds_another_one(self):
        clear_locator_cache()
        first = locator_for(VERTICES, CONNECTIVITY, fingerprint="abc")
        assert locator_for(VERTICES, CONNECTIVITY, fingerprint="def") is not first

    def test_without_a_fingerprint_nothing_is_shared(self):
        clear_locator_cache()
        first = locator_for(VERTICES, CONNECTIVITY)
        assert locator_for(VERTICES, CONNECTIVITY) is not first

    def test_the_resolution_is_written_to_disk(self, tmp_path):
        locator = CellLocator(
            VERTICES, CONNECTIVITY, fingerprint="abc", cache_dir=tmp_path / "cache"
        )
        locator.locate({"p": (1.5, 0.5)})
        payload = json.loads((tmp_path / "cache" / "abc.json").read_text())
        assert payload["fingerprint"] == "abc"
        assert list(payload["points"].values()) == [1]

    def test_a_cached_point_never_builds_the_tree(self, tmp_path):
        warm = CellLocator(VERTICES, CONNECTIVITY, fingerprint="abc", cache_dir=tmp_path / "c")
        warm.locate({"p": (1.5, 0.5)})
        cold = CellLocator(VERTICES, CONNECTIVITY, fingerprint="abc", cache_dir=tmp_path / "c")
        assert cold.locate({"p": (1.5, 0.5)}) == {"p": 1}
        assert cold._tree is None

    def test_a_point_outside_is_cached_as_outside(self, tmp_path):
        locator = CellLocator(VERTICES, CONNECTIVITY, fingerprint="abc", cache_dir=tmp_path / "c")
        assert locator.locate({"p": (9.0, 9.0)}, warn_outside=False) == {"p": None}
        cold = CellLocator(VERTICES, CONNECTIVITY, fingerprint="abc", cache_dir=tmp_path / "c")
        assert cold.locate({"p": (9.0, 9.0)}, warn_outside=False) == {"p": None}

    def test_a_run_populates_the_project_cache(self, run):
        run.probe.series("head", x=1.5, y=0.5)
        cache_dir = cell_index_cache_dir(run._catalog.project_path)
        assert list(cache_dir.glob("*.json"))

    def test_the_free_function_still_answers(self):
        assert point_in_cell(VERTICES, CONNECTIVITY, {"p": (0.5, 1.5)}) == {"p": 2}

    def test_a_point_outside_warns(self):
        with pytest.warns(UserWarning, match="outside the mesh"):
            point_in_cell(VERTICES, CONNECTIVITY, {"p": (9.0, 9.0)})
