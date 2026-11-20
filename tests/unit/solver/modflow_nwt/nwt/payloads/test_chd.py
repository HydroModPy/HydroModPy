"""Constant-head payloads of the NWT adapter: side faces, ocean cells and the BAS arrays.

Heads and bottoms are in m. A side face is a constant head in the IBOUND, the ocean is a set of
constant-head rows, and the arrays given to BAS must be finite and have the grid shape.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.initial.state import HeadRule
from hydromodpy.model.model import ModelTime
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter
from hydromodpy.solver.modflow_nwt.nwt.payloads.chd import (
    build_initial_heads_and_sides,
    build_ocean_chd,
    build_side_chd,
    iter_side_boundary_cells,
    normalize_boundary_series,
    refuse_constant_heads_below_bottom,
    validate_ibound_strt_contract,
)
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

DEM = np.array([[12.0, 14.0, 16.0], [11.0, 13.0, 15.0]])  # m, 2 rows x 3 columns


def two_layer_adapter(conditions: dict, active=None, nper: int = 1) -> FlowToModflowAdapter:
    """Two layers 10 m and 20 m thick under a DEM of 5 m cells."""
    mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=3,
        top=DEM,
        botm=np.stack([DEM - 10.0, DEM - 20.0]),
        dx=5.0,
        dy=5.0,
    )
    bundle = BoundaryConditionBundle(
        conditions=conditions, active_ids=tuple(conditions if active is None else active)
    )
    model = make_model(
        boundaries=bundle,
        initial=HeadRule("top"),
        time=ModelTime(grid=None, regime="transient", first_period_steady=True),
    )
    return FlowToModflowAdapter(model=model, solver_mesh=mesh, nper=nper, sink_fill=False)


# Boundary values given as a sequence become one value per stress period.

SERIES = [
    pytest.param([5.0], 3, [5.0, 5.0, 5.0], id="one value goes to every period"),
    pytest.param([5.0, 6.0], 1, [5.0], id="one period keeps the first value"),
    pytest.param([1.0, 2.0, 3.0], 3, [1.0, 2.0, 3.0], id="one value per period"),
]


@pytest.mark.parametrize(("value", "nper", "expected"), SERIES)
def test_boundary_series(value, nper, expected):
    series = normalize_boundary_series(value=value, label="x", nper=nper)

    np.testing.assert_allclose(series, expected)


def test_scalar_needs_no_series():
    assert normalize_boundary_series(value=5.0, label="x", nper=3) is None


# The face of the grid a lateral boundary id names, as (layer, row, column) on 2 layers.

FACES = [
    pytest.param(
        "east_side",
        [(0, 0, 2), (0, 1, 2), (1, 0, 2), (1, 1, 2)],
        id="east is the last column",
    ),
    pytest.param(
        "north_side",
        [(0, 0, 0), (0, 0, 1), (0, 0, 2), (1, 0, 0), (1, 0, 1), (1, 0, 2)],
        id="north is the first row",
    ),
    pytest.param(
        "south_side",
        [(0, 1, 0), (0, 1, 1), (0, 1, 2), (1, 1, 0), (1, 1, 1), (1, 1, 2)],
        id="south is the last row",
    ),
]


@pytest.mark.parametrize(("bc_id", "cells"), FACES)
def test_side_face_cells(bc_id, cells):
    adapter = two_layer_adapter({})

    assert list(iter_side_boundary_cells(adapter, bc_id)) == cells


FACE_SLICES = [
    pytest.param("east_side", (slice(None), slice(None), -1), id="east"),
    pytest.param("north_side", (slice(None), 0, slice(None)), id="north"),
    pytest.param("south_side", (slice(None), -1, slice(None)), id="south"),
]


@pytest.mark.parametrize(("bc_id", "face"), FACE_SLICES)
def test_static_side_is_constant_head(bc_id, face):
    adapter = two_layer_adapter({bc_id: SimpleNamespace(value=9.5)})

    ibound, strt, _ = build_initial_heads_and_sides(adapter)

    expected = np.ones((2, 2, 3))
    expected[face] = -1
    np.testing.assert_array_equal(ibound, expected)
    assert np.all(strt[face] == 9.5)


def test_side_without_payload_is_skipped():
    adapter = two_layer_adapter({}, active=("west_side",))

    ibound, _, _ = build_initial_heads_and_sides(adapter)

    assert np.all(ibound == 1.0)
    assert build_side_chd(adapter) is None
    refuse_constant_heads_below_bottom(
        adapter, ibound=ibound, strt=np.zeros((2, 2, 3)), chd_spd=None
    )


# Ocean: a scalar head fixes the cells at or under it, a series gives CHD rows in each period.


def ocean_arrays():
    return np.ones((2, 2, 3)), np.zeros((2, 2, 3)), np.ones((2, 3))


def test_ocean_off_or_unset():
    adapter = two_layer_adapter({}, active=("ocean",))
    ibound, strt, drain = ocean_arrays()

    assert build_ocean_chd(adapter, ibound=ibound, strt=strt, drain_array=drain) is None
    assert np.all(ibound == 1.0)


def test_scalar_ocean_fixes_low_cells():
    adapter = two_layer_adapter({"ocean": SimpleNamespace(value=12.5)})
    ibound, strt, drain = ocean_arrays()

    chd_spd = build_ocean_chd(adapter, ibound=ibound, strt=strt, drain_array=drain)

    assert chd_spd is None
    # DEM cells 12 m and 11 m lie under the 12.5 m sea level, in both layers.
    low = np.zeros((2, 3), dtype=bool)
    low[0, 0] = low[1, 0] = True
    assert np.all(ibound[:, low] == -1)
    assert np.all(ibound[:, ~low] == 1)
    assert np.all(strt[:, low] == 12.5)


def test_ocean_series_rows():
    adapter = two_layer_adapter({"ocean": SimpleNamespace(value=[12.5, 13.5])}, nper=2)
    ibound, strt, drain = ocean_arrays()

    chd_spd = build_ocean_chd(adapter, ibound=ibound, strt=strt, drain_array=drain)

    # The highest head, 13.5 m, sets the cells: DEM 12, 11 and 13 m lie under it.
    cells = [(0, 0), (1, 0), (1, 1)]
    for kper, head in enumerate([12.5, 13.5]):
        assert chd_spd[kper] == [[0, i, j, head, head] for i, j in cells]
    np.testing.assert_array_equal(drain, [[0, 1, 1], [0, 0, 1]])


# The arrays given to BAS.


def valid_arrays():
    return {
        "ibound": np.ones((1, 2, 3)),
        "strt": np.zeros((1, 2, 3)),
        "drain_array": np.ones((2, 3)),
    }


def with_array(name, array):
    return valid_arrays() | {name: array}


def nan_array(shape):
    array = np.ones(shape)
    array[0] = np.nan
    return array


CONTRACT_REFUSALS = [
    pytest.param(with_array("strt", np.zeros((2, 2, 3))), "strt shape mismatch", id="strt shape"),
    pytest.param(with_array("drain_array", np.ones((3, 2))), "drain_array shape", id="drain shape"),
    pytest.param(
        with_array("ibound", nan_array((1, 2, 3))), "ibound contains non-finite", id="ibound nan"
    ),
    pytest.param(
        with_array("drain_array", nan_array((2, 3))),
        "drain_array contains non-finite",
        id="drain nan",
    ),
]


@pytest.mark.parametrize(("arrays", "match"), CONTRACT_REFUSALS)
def test_contract_refusals(arrays, match):
    with pytest.raises(ValueError, match=match):
        validate_ibound_strt_contract(nlay=1, nrow=2, ncol=3, **arrays)


REFUSALS = [
    pytest.param("abc", "must be numeric or a sequence", TypeError, id="a string"),
    pytest.param([], "cannot be empty", ValueError, id="an empty list"),
    pytest.param(
        [1.0, 2.0], r"length \(2\) must be 1 or match nper \(3\)", ValueError, id="length"
    ),
]


@pytest.mark.parametrize(("value", "match", "error"), REFUSALS)
def test_refusals(value, match, error):
    with pytest.raises(error, match=match):
        normalize_boundary_series(value=value, label="flow.bc.x.value", nper=3)


def test_unknown_face_refused():
    with pytest.raises(ValueError, match="Unsupported side boundary id: top_side"):
        list(iter_side_boundary_cells(two_layer_adapter({}), "top_side"))
