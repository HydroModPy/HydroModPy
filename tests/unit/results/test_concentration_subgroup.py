"""A store written by a pre-release and one written in species subgroups read back the same.

The extractor of a transport run writes one solute, named by its ``spc_name``,
under the ``concentration`` group: ``concentration/NO3``. A run written by a
pre-release had the array straight under ``concentration``, with no name. The readers
of the public name ``concentration`` see the same thing in both: the family is
resolved once, in ``results``, from the store, and a store that holds several
named solutes is refused with their names.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import zarr

from hydromodpy.results.derive.virtual_fields import read_field_or_virtual
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.results.zarr_store.zarr_reader import (
    concentration_array,
    field_array_view,
    has_concentration,
    stored_field_array,
)


@pytest.fixture
def subgroup_store(tmp_path: Path) -> SimulationZarr:
    """A store of today's form: the solute of one transport run, under its species name."""
    sz = SimulationZarr.create(tmp_path / "subgroup.zarr", n_cells=4, n_layers=1)
    sz.write_field_stack(
        "NO3", np.arange(3 * 4, dtype="float64").reshape(3, 4), subgroup="concentration"
    )
    return sz


@pytest.fixture
def flat_store(tmp_path: Path) -> SimulationZarr:
    """A store written by a pre-release: the concentration array at the root of the fields."""
    sz = SimulationZarr.create(tmp_path / "flat.zarr", n_cells=4, n_layers=1)
    sz.write_field_stack("concentration", np.arange(3 * 4, dtype="float64").reshape(3, 4))
    return sz


def _source_of(sz: SimulationZarr) -> Any:
    return SimpleNamespace(open_zarr=lambda _sim_id: sz)


def test_the_two_forms_read_the_same_public_name(
    subgroup_store: SimulationZarr, flat_store: SimulationZarr
) -> None:
    expected = np.arange(3 * 4, dtype="float64").reshape(3, 4)

    from_subgroup = read_field_or_virtual(_source_of(subgroup_store), "one", "concentration", 1)
    from_flat = read_field_or_virtual(_source_of(flat_store), "one", "concentration", 1)

    assert np.array_equal(from_subgroup, expected[1])
    assert np.array_equal(from_flat, expected[1])
    assert from_subgroup.dtype == np.dtype("float64") == from_flat.dtype


def test_a_store_with_several_named_solutes_is_refused_with_their_names(tmp_path: Path) -> None:
    sz = SimulationZarr.create(tmp_path / "two.zarr", n_cells=4, n_layers=1)
    sz.write_field_stack("NO3", np.zeros((2, 4)), subgroup="concentration")
    sz.write_field_stack("Cl", np.zeros((2, 4)), subgroup="concentration")

    with pytest.raises(KeyError, match="Cl"):
        concentration_array(sz.root)
    sz.close()


def test_the_solute_written_under_its_name_answers_that_array(tmp_path: Path) -> None:
    """``concentration/<spc_name>`` is the form written today: the solute is the array."""
    sz = SimulationZarr.create(tmp_path / "mixed.zarr", n_cells=4, n_layers=1)
    sz.write_field_stack("NO3", np.array([[1.0, 2.0]]), subgroup="concentration")

    array = concentration_array(sz.root)
    assert np.allclose(np.asarray(array), [[1.0, 2.0]])
    assert has_concentration(sz.root)
    sz.close()


def test_the_path_resolver_reads_the_solute_and_not_its_group(
    subgroup_store: SimulationZarr, flat_store: SimulationZarr, tmp_path: Path
) -> None:
    """``run.read`` and the exporters resolve ``concentration`` to the array of the solute."""
    expected = np.arange(3 * 4, dtype="float64").reshape(3, 4)
    for sz in (subgroup_store, flat_store):
        array = stored_field_array(sz.root, "concentration")
        assert np.array_equal(np.asarray(field_array_view(array, None)), expected)
    empty = SimulationZarr.create(tmp_path / "empty.zarr", n_cells=4, n_layers=1)
    assert stored_field_array(empty.root, "concentration") is None
    assert stored_field_array(empty.root, "budget/recharge") is None
