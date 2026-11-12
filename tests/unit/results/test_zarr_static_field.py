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
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

N_CELLS = 12
N_LAYERS = 3

STATIC_PARAMETERS = ("hydraulic_conductivity", "specific_yield", "specific_storage")


@pytest.fixture
def store(tmp_path: Path) -> SimulationZarr:
    sz = SimulationZarr.create(tmp_path / "sim.zarr", n_cells=N_CELLS, n_layers=N_LAYERS)
    yield sz
    sz.close()


def test_the_written_field_carries_the_units_the_registry_declares(
    store: SimulationZarr,
) -> None:
    store.write_static_field(
        "specific_yield", np.full((N_LAYERS, N_CELLS), 0.05), subgroup="derived"
    )
    attrs = dict(store.root["derived"]["specific_yield"].attrs)
    assert attrs["units"] == field_registry.get("specific_yield").units
