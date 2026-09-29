"""A range read gives, row for row, what a read of each step gives.

``Run.field`` reads one step and opens the store for it. Counting the flowing
cells of a daily run that way opened the store 4 385 times. ``field_range``
opens it once for a whole range. Each of its rows must be the step read, bit
for bit, on a compact store and on a store written before (float64, with
``derived/release_flux`` stored).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.derive.config_flags import config_option_for
from hydromodpy.results.derive.stream_extent import _release_rows
from hydromodpy.results.derive.virtual_fields import read_field_range_or_virtual
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run import Run
from hydromodpy.results.run.geographic import field_range, field_steps

N_STEPS = 7
N_LAYERS = 2
AREAS = np.array([10.0, 20.0, 40.0, 80.0, 20.0])
N_CELLS = AREAS.size
TOP = np.array([130.0, 128.0, 125.0, 121.0, 119.0])


def _row_of_rectangles() -> tuple[np.ndarray, np.ndarray]:
    """Unit-height rectangles whose width is the area."""
    x = np.concatenate([[0.0], np.cumsum(AREAS)])
    vertices = np.array([[xi, 0.0, 0.0] for xi in x] + [[xi, 1.0, 0.0] for xi in x])
    n_x = x.size
    connectivity = np.array([[i, i + 1, n_x + i + 1, n_x + i] for i in range(N_CELLS)])
    return vertices, connectivity.astype("int32")


def _seed(catalog: Catalog) -> str:
    """A two-layer run with its head and a drain, stream and recharge budget."""
    rng = np.random.default_rng(11)
    sid = str(uuid.uuid4())
    reg = catalog.register_simulation(
        sid,
        project="p",
        solver="modflow6",
        n_cells=N_CELLS,
        n_layers=N_LAYERS,
        n_timesteps=N_STEPS,
    )
    reg.zarr.close()
    head = rng.uniform(110.0, 131.0, (N_STEPS, N_LAYERS, N_CELLS))
    head[:, 0, 1] = np.nan
    drain = -rng.uniform(0.0, 2e-3, (N_STEPS, N_LAYERS, N_CELLS))
    stream = rng.uniform(-3e-3, 1e-3, (N_STEPS, N_LAYERS, N_CELLS))
    recharge = rng.uniform(0.0, 1e-4, (N_STEPS, N_LAYERS, N_CELLS))
    vertices, connectivity = _row_of_rectangles()
    sz = catalog.open_zarr(sid)
    try:
        sz.write_mesh(vertices, connectivity, np.array([150.0, 100.0, 50.0]))
        sz.write_topography(TOP)
        sz.write_field_stack("head", head)
        for name, values in (("drain", drain), ("stream", stream), ("recharge", recharge)):
            sz.write_field_stack(name, values, subgroup="budget")
    finally:
        sz.close()
    return sid


def _step_by_step(run: Run, variable: str, steps, layer: int | None = None) -> np.ndarray:
    return np.stack([run.field(variable, timestep=int(t), layer=layer) for t in steps])


class _CountingCatalog:
    """Count the store openings of a catalog, every other call passed through."""

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self.openings = 0

    def open_zarr(self, sim_id):
        self.openings += 1
        return self._catalog.open_zarr(sim_id)

    def query_field(self, sim_id, variable, timestep, layer=None):
        from hydromodpy.results.derive.virtual_fields import read_field_or_virtual

        return read_field_or_virtual(self, str(sim_id), variable, timestep, layer=layer)

    def __getattr__(self, name):
        return getattr(self._catalog, name)


@pytest.fixture
def catalog(tmp_path: Path):
    with Catalog(tmp_path / "workspace") as cat:
        yield cat


@pytest.fixture
def old_catalog(tmp_path: Path):
    with Catalog(tmp_path / "old", persistence=PersistenceConfig(field_precision="exact")) as cat:
        yield cat


class TestAStoredField:
    def test_the_range_is_each_step_read_bit_for_bit(self, catalog) -> None:
        run = Run(_seed(catalog), catalog)

        whole = field_range(run, "head", 0, N_STEPS)

        assert whole.dtype == np.float64
        assert whole.shape == (N_STEPS, N_LAYERS, N_CELLS)
        np.testing.assert_array_equal(whole, _step_by_step(run, "head", range(N_STEPS)))
        np.testing.assert_array_equal(
            field_range(run, "head", 2, 5), _step_by_step(run, "head", range(2, 5))
        )

    def test_a_layer_is_picked_as_a_step_read_picks_it(self, catalog) -> None:
        run = Run(_seed(catalog), catalog)

        lower = field_range(run, "head", 1, 6, layer=1)

        assert lower.shape == (5, N_CELLS)
        np.testing.assert_array_equal(lower, _step_by_step(run, "head", range(1, 6), layer=1))

    def test_negative_bounds_count_from_the_end(self, catalog) -> None:
        sid = _seed(catalog)
        run = Run(sid, catalog)

        np.testing.assert_array_equal(
            field_range(run, "head", -3, N_STEPS), field_range(run, "head", N_STEPS - 3, N_STEPS)
        )
        np.testing.assert_array_equal(
            read_field_range_or_virtual(catalog, sid, "head", -2, -1)[0],
            catalog.query_field(sid, "head", N_STEPS - 2),
        )

    def test_a_static_field_repeats_once_per_step(self, catalog) -> None:
        run = Run(_seed(catalog), catalog)

        np.testing.assert_array_equal(
            field_range(run, "topography", 0, 3), _step_by_step(run, "topography", range(3))
        )

    def test_the_range_opens_the_store_once(self, catalog) -> None:
        counting = _CountingCatalog(catalog)
        run = Run(_seed(catalog), counting)

        field_range(run, "head", 0, N_STEPS)

        assert counting.openings == 1


class TestAFieldRebuiltOnRead:
    @pytest.mark.parametrize("variable", ["release_flux", "fluxes_from_budget"])
    def test_a_range_rebuild_is_each_step_rebuilt(self, catalog, variable) -> None:
        run = Run(_seed(catalog), catalog)

        whole = field_range(run, variable, 0, N_STEPS)

        assert whole.shape == (N_STEPS, N_CELLS)
        np.testing.assert_array_equal(whole, _step_by_step(run, variable, range(N_STEPS)))
        np.testing.assert_array_equal(
            field_range(run, variable, 3, 6), _step_by_step(run, variable, range(3, 6))
        )

    @pytest.mark.parametrize(
        "variable", ["watertable_elevation", "watertable_depth", "seepage_mask", "outflow_drain"]
    )
    def test_any_other_is_rebuilt_step_by_step_on_one_opening(self, catalog, variable) -> None:
        counting = _CountingCatalog(catalog)
        sid = _seed(catalog)
        run = Run(sid, counting)

        whole = field_range(run, variable, 0, N_STEPS)

        assert counting.openings == 1
        np.testing.assert_array_equal(
            whole, _step_by_step(Run(sid, catalog), variable, range(N_STEPS))
        )

    def test_the_simulated_network_builds_its_graph_once_for_the_range(
        self, catalog, monkeypatch
    ) -> None:
        from hydromodpy.results.derive import virtual_fields

        calls: list[list[int]] = []

        def stack(run, timesteps):
            calls.append([int(t) for t in timesteps])
            return np.asarray([[t % 2, 1.0, 0.0, t, 1.0] for t in timesteps], dtype=float)

        monkeypatch.setattr(virtual_fields, "simulated_active_network_stack", stack)
        sid = _seed(catalog)
        name = virtual_fields.SIMULATED_ACTIVE_NETWORK

        whole = read_field_range_or_virtual(catalog, sid, name, 1, 5)

        assert calls == [[1, 2, 3, 4]]
        np.testing.assert_array_equal(
            whole, np.stack([catalog.query_field(sid, name, t) for t in range(1, 5)])
        )

    def test_a_layer_is_ignored_where_a_step_read_ignores_it(self, catalog) -> None:
        run = Run(_seed(catalog), catalog)

        np.testing.assert_array_equal(
            field_range(run, "release_flux", 0, 4, layer=1),
            _step_by_step(run, "release_flux", range(4), layer=1),
        )


class TestTheErrors:
    @pytest.mark.parametrize("variable", ["no_such_field", "accumulation_flux"])
    def test_a_field_nothing_holds_raises_what_a_step_read_raises(self, catalog, variable) -> None:
        sid = _seed(catalog)
        run = Run(sid, catalog)

        with pytest.raises(FieldNotFoundError) as by_step:
            run.field(variable, timestep=0)
        with pytest.raises(FieldNotFoundError) as by_range:
            field_range(run, variable, 0, 2)
        with pytest.raises(KeyError) as by_catalog_step:
            catalog.query_field(sid, variable, 0)
        with pytest.raises(KeyError) as by_reader_range:
            read_field_range_or_virtual(catalog, sid, variable, 0, 2)

        assert str(by_range.value) == str(by_step.value)
        assert str(by_reader_range.value) == str(by_catalog_step.value)
        if config_option_for(variable) is not None:
            assert "run the simulation again" in str(by_range.value)

    @pytest.mark.parametrize("variable", ["head", "release_flux", "watertable_elevation"])
    @pytest.mark.parametrize(
        ("start", "stop"), [(0, N_STEPS + 1), (4, 2), (-N_STEPS - 1, 2), (N_STEPS + 1, N_STEPS + 2)]
    )
    def test_a_range_off_the_time_axis_is_refused(self, catalog, variable, start, stop) -> None:
        """A slice would hand back fewer rows than asked; the range refuses instead."""
        sid = _seed(catalog)

        with pytest.raises(IndexError):
            read_field_range_or_virtual(catalog, sid, variable, start, stop)

    def test_a_stored_step_off_the_time_axis_is_refused_alike(self, catalog) -> None:
        sid = _seed(catalog)

        with pytest.raises(IndexError):
            catalog.query_field(sid, "head", N_STEPS)
        with pytest.raises(IndexError):
            field_range(Run(sid, catalog), "head", N_STEPS - 1, N_STEPS + 1)


class TestAStoreWrittenBefore:
    def test_its_stored_release_is_read_not_rebuilt(self, old_catalog) -> None:
        sid = _seed(old_catalog)
        # Deliberately not what the budget rebuilds, so a recomputation is caught.
        stored = np.arange(N_STEPS * N_CELLS, dtype="float64").reshape(N_STEPS, N_CELLS) / 7.0
        old_catalog.write_field_stack(sid, "release_flux", stored, subgroup="derived")
        run = Run(sid, old_catalog)

        whole = field_range(run, "release_flux", 0, N_STEPS)

        assert whole.dtype == np.float64
        np.testing.assert_array_equal(whole, stored)
        np.testing.assert_array_equal(whole, _step_by_step(run, "release_flux", range(N_STEPS)))

    def test_its_float64_head_reads_as_each_step(self, old_catalog) -> None:
        run = Run(_seed(old_catalog), old_catalog)

        np.testing.assert_array_equal(
            field_range(run, "head", 0, N_STEPS), _step_by_step(run, "head", range(N_STEPS))
        )


class TestTheReleaseRowsOfTheFlowCounts:
    @pytest.mark.parametrize(
        "steps", [[0, 1, 2, 3, 4, 5, 6], [0, 1, 2, 4], [5, 1, 2, 3, 0], [3], [6, 5, 4]]
    )
    def test_they_are_the_step_by_step_read_on_a_compact_store(self, catalog, steps) -> None:
        run = Run(_seed(catalog), catalog)

        rows = _release_rows(run, np.asarray(steps), N_CELLS)

        np.testing.assert_array_equal(rows, _step_by_step(run, "release_flux", steps))

    def test_they_are_the_stored_rows_on_a_store_written_before(self, old_catalog) -> None:
        sid = _seed(old_catalog)
        stored = np.linspace(0.0, 1.0, N_STEPS * N_CELLS).reshape(N_STEPS, N_CELLS)
        old_catalog.write_field_stack(sid, "release_flux", stored, subgroup="derived")
        run = Run(sid, old_catalog)
        steps = [0, 1, 2, 5, 6, 3]

        rows = _release_rows(run, np.asarray(steps), N_CELLS)

        np.testing.assert_array_equal(rows, stored[steps])
        np.testing.assert_array_equal(rows, _step_by_step(run, "release_flux", steps))

    def test_a_block_of_consecutive_steps_opens_the_store_once(self, catalog) -> None:
        counting = _CountingCatalog(catalog)
        run = Run(_seed(catalog), counting)

        _release_rows(run, np.arange(N_STEPS), N_CELLS)

        assert counting.openings == 1

    def test_a_cell_count_other_than_the_mesh_is_refused(self, catalog) -> None:
        run = Run(_seed(catalog), catalog)

        with pytest.raises(ValueError, match="not written for the same run"):
            _release_rows(run, np.arange(3), N_CELLS + 1)


@pytest.mark.parametrize("steps", [[-2, -1], [-1, 0, 1, 2], [6, -1, 4, 5]])
def test_negative_steps_are_read_as_their_step_read(catalog, steps) -> None:
    run = Run(_seed(catalog), catalog)

    np.testing.assert_array_equal(
        field_steps(run, "release_flux", steps), _step_by_step(run, "release_flux", steps)
    )


def test_a_stand_in_without_a_range_reader_is_read_step_by_step() -> None:
    stack = np.arange(12.0).reshape(4, 3)
    stand_in = SimpleNamespace(field=lambda variable, timestep=-1, **_: stack[int(timestep)])

    np.testing.assert_array_equal(
        field_steps(stand_in, "release_flux", [2, 0, 1]), stack[[2, 0, 1]]
    )
