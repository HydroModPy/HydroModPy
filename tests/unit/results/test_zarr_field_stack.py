"""Unit tests for the batched ``write_field_stack`` Zarr write path."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.results.zarr_store import SimulationZarr


@pytest.fixture
def fresh_store(tmp_path: Path) -> SimulationZarr:
    sz = SimulationZarr.create(
        tmp_path / "sim.zarr",
        n_cells=50,
        n_layers=2,
    )
    yield sz
    sz.close()


def test_stack_write_matches_per_timestep_writes(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    values = rng.normal(size=(12, 2, 50))

    sz_loop = SimulationZarr.create(tmp_path / "loop.zarr", n_cells=50, n_layers=2)
    for t in range(values.shape[0]):
        sz_loop.write_field("head", t, values[t], n_timesteps=values.shape[0])
    loop_data = np.asarray(sz_loop.root["head"][:])
    loop_chunks = sz_loop.root["head"].chunks
    sz_loop.close()

    sz_stack = SimulationZarr.create(tmp_path / "stack.zarr", n_cells=50, n_layers=2)
    sz_stack.write_field_stack("head", values)
    stack_data = np.asarray(sz_stack.root["head"][:])
    stack_chunks = sz_stack.root["head"].chunks
    sz_stack.close()

    assert np.allclose(loop_data, stack_data, equal_nan=True)
    assert loop_chunks == stack_chunks


def test_stack_write_1d_per_step_under_subgroup(fresh_store: SimulationZarr) -> None:
    values = np.arange(8 * 50, dtype="float64").reshape(8, 50)
    fresh_store.write_field_stack("release_flux", values, subgroup="derived")
    arr = fresh_store.root["derived"]["release_flux"]
    assert arr.shape == (8, 50)
    assert np.allclose(arr[:], values)


def test_stack_write_slabs_assemble_full_array(fresh_store: SimulationZarr) -> None:
    rng = np.random.default_rng(11)
    values = rng.normal(size=(10, 2, 50))
    fresh_store.write_field_stack("head", values[:4], n_timesteps=10)
    fresh_store.write_field_stack("head", values[4:], n_timesteps=10, timestep_offset=4)
    assert np.allclose(fresh_store.root["head"][:], values)


def test_stack_write_recreates_on_shape_mismatch(fresh_store: SimulationZarr) -> None:
    fresh_store.write_field_stack("head", np.zeros((4, 2, 50)))
    fresh_store.write_field_stack("head", np.ones((6, 2, 50)))
    arr = fresh_store.root["head"]
    assert arr.shape == (6, 2, 50)
    assert np.allclose(arr[:], 1.0)


def test_stack_write_rejects_slab_beyond_total(fresh_store: SimulationZarr) -> None:
    with pytest.raises(ValueError, match="exceeds"):
        fresh_store.write_field_stack("head", np.zeros((5, 2, 50)), n_timesteps=4)


def test_stack_write_rejects_offset_on_missing_array(fresh_store: SimulationZarr) -> None:
    with pytest.raises(ValueError, match="timestep_offset=0"):
        fresh_store.write_field_stack(
            "head", np.zeros((2, 2, 50)), n_timesteps=10, timestep_offset=2
        )


def test_stack_write_rejects_non_stack_input(fresh_store: SimulationZarr) -> None:
    with pytest.raises(ValueError, match="stack"):
        fresh_store.write_field_stack("head", np.zeros(50))


def test_stack_write_attaches_cf_attrs(fresh_store: SimulationZarr) -> None:
    fresh_store.write_field_stack("head", np.zeros((3, 2, 50)))
    attrs = dict(fresh_store.root["head"].attrs)
    assert "_FillValue" in attrs
