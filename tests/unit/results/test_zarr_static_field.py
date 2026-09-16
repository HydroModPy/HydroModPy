"""A model input has no time axis, and must not be given one.

Conductivity and storage are what the solver was handed, not what it
answered. Stored through the time-resolved writers they would be repeated at
every step, and read back through one they would be sliced along a dimension
that carries no information.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.results import field_registry
from hydromodpy.results.zarr_store import SimulationZarr

N_CELLS = 12
N_LAYERS = 3

STATIC_PARAMETERS = ("hydraulic_conductivity", "specific_yield", "specific_storage")


@pytest.fixture
def store(tmp_path: Path) -> SimulationZarr:
    sz = SimulationZarr.create(tmp_path / "sim.zarr", n_cells=N_CELLS, n_layers=N_LAYERS)
    yield sz
    sz.close()


def test_a_static_field_keeps_the_shape_it_was_written_with(store: SimulationZarr) -> None:
    values = np.arange(N_LAYERS * N_CELLS, dtype="float64").reshape(N_LAYERS, N_CELLS)
    store.write_static_field("hydraulic_conductivity", values, subgroup="derived")
    stored = np.asarray(store.root["derived"]["hydraulic_conductivity"][:])
    assert stored.shape == (N_LAYERS, N_CELLS)
    assert np.array_equal(stored, values)


def test_reading_a_static_field_ignores_the_timestep_asked_for(store: SimulationZarr) -> None:
    values = np.full((N_LAYERS, N_CELLS), 2.0e-5)
    store.write_static_field("hydraulic_conductivity", values, subgroup="derived")
    for timestep in (0, 5, -1):
        read = store.read_field("hydraulic_conductivity", timestep, subgroup="derived")
        assert np.array_equal(np.asarray(read), values)


def test_the_written_field_carries_the_units_the_registry_declares(
    store: SimulationZarr,
) -> None:
    store.write_static_field(
        "specific_yield", np.full((N_LAYERS, N_CELLS), 0.05), subgroup="derived"
    )
    attrs = dict(store.root["derived"]["specific_yield"].attrs)
    assert attrs["units"] == field_registry.get("specific_yield").units


@pytest.mark.parametrize("variable", STATIC_PARAMETERS)
def test_every_aquifer_property_is_registered_without_a_time_axis(variable: str) -> None:
    assert not field_registry.get(variable).shape.startswith("time")
