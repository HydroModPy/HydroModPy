"""A store keeps its time-varying fields in the precision the run asked for.

``compact`` (the default) writes float32 rounded at 16 mantissa bits and says
so with the CF-1.11 quantization attributes. ``exact`` writes float64, bit for
bit. Geometry, static fields, indices and timestamps are never rounded, and
every reader returns float64 whatever the store holds.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.field_precision import (
    KEPT_MANTISSA_BITS,
    MAX_RELATIVE_ERROR,
    round_mantissa,
)
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.results.zarr_store.zarr_writer import QUANTIZATION_VARIABLE

N_CELLS = 6
DROPPED_MASK = np.uint32((1 << (23 - KEPT_MANTISSA_BITS)) - 1)


def _values(n_steps: int = 4) -> np.ndarray:
    rng = np.random.default_rng(29)
    return 100.0 + rng.normal(size=(n_steps, 1, N_CELLS)) * 30.0


@pytest.fixture
def compact(tmp_path: Path):
    store = SimulationZarr.create(tmp_path / "compact.zarr", n_cells=N_CELLS, n_layers=1)
    yield store
    store.close()


@pytest.fixture
def exact(tmp_path: Path):
    store = SimulationZarr.create(
        tmp_path / "exact.zarr", n_cells=N_CELLS, n_layers=1, field_precision="exact"
    )
    yield store
    store.close()


def test_the_default_precision_is_compact() -> None:
    assert PersistenceConfig().field_precision == "compact"
    assert PersistenceConfig(field_precision="exact").field_precision == "exact"
    with pytest.raises(ValidationError):
        PersistenceConfig(field_precision="float16")


def test_a_compact_stack_is_float32_on_the_rounded_grid(compact: SimulationZarr) -> None:
    values = _values()

    compact.write_field_stack("head", values)

    stored = np.asarray(compact.root["head"][:])
    assert stored.dtype == np.float32
    assert not np.any(stored.view(np.uint32) & DROPPED_MASK)
    np.testing.assert_array_equal(stored, round_mantissa(values))
    np.testing.assert_allclose(stored, values, rtol=MAX_RELATIVE_ERROR, atol=0.0)


def test_a_compact_step_write_rounds_the_same_way(compact: SimulationZarr) -> None:
    values = _values()

    for step in range(values.shape[0]):
        compact.write_field("drain", step, values[step], n_timesteps=4, subgroup="budget")

    stored = np.asarray(compact.root["budget"]["drain"][:])
    assert stored.dtype == np.float32
    np.testing.assert_array_equal(stored, round_mantissa(values))


def test_a_compact_field_says_how_it_was_rounded(compact: SimulationZarr) -> None:
    compact.write_field_stack("head", _values())

    attrs = dict(compact.root["head"].attrs)
    assert attrs["quantization"] == QUANTIZATION_VARIABLE
    assert attrs["quantization_nsb"] == KEPT_MANTISSA_BITS
    container = compact.root[QUANTIZATION_VARIABLE]
    assert container.shape == ()
    assert dict(container.attrs)["algorithm"] == "bitround"


def test_an_exact_field_is_float64_bit_for_bit(exact: SimulationZarr) -> None:
    values = _values()

    exact.write_field_stack("head", values)

    stored = np.asarray(exact.root["head"][:])
    assert stored.dtype == np.float64
    np.testing.assert_array_equal(stored, values)
    assert "quantization" not in dict(exact.root["head"].attrs)
    assert QUANTIZATION_VARIABLE not in exact.root


def test_an_integer_field_is_never_rounded(compact: SimulationZarr) -> None:
    mask = np.array([[0, 1, 1, 0, 1, 0]], dtype="int8")

    compact.write_field_stack("seepage_mask", mask, subgroup="derived")

    stored = np.asarray(compact.root["derived"]["seepage_mask"][:])
    assert stored.dtype == np.int8
    assert "quantization" not in dict(compact.root["derived"]["seepage_mask"].attrs)


def test_geometry_static_fields_and_time_keep_their_precision(compact: SimulationZarr) -> None:
    vertices = np.column_stack([np.linspace(0.1234567891, 7.0, 14), np.zeros(14), np.zeros(14)])
    connectivity = np.array([[2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2] for i in range(N_CELLS)])
    topography = np.linspace(101.123456789, 150.987654321, N_CELLS)
    thickness = np.full((1, N_CELLS), 12.3456789012)
    conductivity = np.full((1, N_CELLS), 1.23456789e-5)

    compact.write_mesh(
        vertices,
        connectivity,
        np.array([150.0, 50.0]),
        topography=topography,
        layer_thickness=thickness,
    )
    compact.write_static_field("hydraulic_conductivity", conductivity, subgroup="derived")
    compact.write_time(np.array([0, 86_400], dtype="int64"))

    mesh = compact.root["mesh"]
    np.testing.assert_array_equal(mesh["vertices"][:], vertices)
    np.testing.assert_array_equal(mesh["topography"][:], topography)
    np.testing.assert_array_equal(mesh["layer_thickness"][:], thickness)
    np.testing.assert_array_equal(
        compact.root["derived"]["hydraulic_conductivity"][:], conductivity
    )
    assert mesh["vertices"].dtype == np.float64
    assert compact.root["time"].dtype == np.int64


def test_a_reader_gets_float64_from_a_compact_store(compact: SimulationZarr) -> None:
    values = _values()
    compact.write_field_stack("head", values)

    step = compact.read_field("head", 2)

    assert step.dtype == np.float64
    np.testing.assert_array_equal(step, round_mantissa(values[2]).astype(np.float64))


def test_the_catalog_writes_in_the_precision_of_its_persistence(tmp_path: Path) -> None:
    values = _values(2)
    for precision, dtype in (("compact", np.float32), ("exact", np.float64)):
        workspace = tmp_path / precision
        persistence = PersistenceConfig(field_precision=precision)
        with Catalog(workspace, persistence=persistence) as catalog:
            sid = str(uuid.uuid4())
            reg = catalog.register_simulation(
                sid, project="p", solver="modflow6", n_cells=N_CELLS, n_layers=1, n_timesteps=2
            )
            reg.zarr.close()
            catalog.write_field_stack(sid, "head", values)
            sz = catalog.open_zarr(sid)
            try:
                assert sz.field_precision == precision
                assert sz.root["head"].dtype == dtype
            finally:
                sz.close()
            read = catalog.query_field(sid, "head", 1)
            assert read.dtype == np.float64
            np.testing.assert_allclose(read, values[1], rtol=MAX_RELATIVE_ERROR, atol=0.0)
