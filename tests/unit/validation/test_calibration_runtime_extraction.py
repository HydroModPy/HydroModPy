"""Reading simulated values back in the twin experiment runtime.

Cells are found from the solver model or from a cell mesh, on a structured grid of
10 m x 5 m cells (m). Heads (m) are read at a (layer, row, column) index. A missing
output comes back as NaN, and the discharge of the truth run is read from its budget.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from validation_cases.calibration.shared.runtime import (
    _extract_head_at_point_from_dir,
    _extract_outlet_discharge_from_run,
    _extract_outputs_from_trial_ctx,
    _model_cell_centroids,
    _read_head_at_cell,
    _resolve_cell_index_from_cell_mesh,
    _resolve_cell_index_from_model,
)


def structured_centroids(nrow, ncol, dx=10.0, dy=5.0):
    """Flat (n_cells, 2) centroids of an nrow x ncol grid, row by row."""
    coords = np.empty((nrow * ncol, 2), dtype=float)
    for r in range(nrow):
        for c in range(ncol):
            coords[r * ncol + c] = ((c + 0.5) * dx, (r + 0.5) * dy)
    return coords


def solver_model(nrow, ncol):
    centroids = structured_centroids(nrow, ncol)
    return SimpleNamespace(
        solver_mesh=SimpleNamespace(cell_centers=lambda: centroids), nrow=nrow, ncol=ncol
    )


ROW_OF_FOUR = structured_centroids(1, 4)
LAYOUT_UNKNOWN = SimpleNamespace(solver_mesh=SimpleNamespace(cell_centers=lambda: ROW_OF_FOUR))

CENTROIDS = [
    pytest.param(solver_model(2, 3), structured_centroids(2, 3), id="solver mesh callable"),
    pytest.param(
        SimpleNamespace(solver_mesh=None, cell_mesh=SimpleNamespace(centers=ROW_OF_FOUR)),
        ROW_OF_FOUR,
        id="cell mesh of the model",
    ),
    pytest.param(SimpleNamespace(), None, id="model exposes nothing"),
]


@pytest.mark.parametrize(("model", "expected"), CENTROIDS)
def test_model_cell_centroids(model, expected):
    np.testing.assert_array_equal(_model_cell_centroids(model), expected)


# Each cell is (layer, row, column, flat index).
CELLS_FROM_MODEL = [
    # Cell (row 1, col 2) has its centroid at (25.0, 7.5), flat index 5.
    pytest.param(solver_model(2, 3), 24.0, 8.0, (0, 1, 2, 5), id="nearest cell, structured grid"),
    pytest.param(None, 0.0, 0.0, None, id="missing model"),
    pytest.param(LAYOUT_UNKNOWN, 25.0, 2.5, (0, 0, 2, 2), id="layout unknown gives flat index"),
]


@pytest.mark.parametrize(("model", "x", "y", "expected"), CELLS_FROM_MODEL)
def test_cell_index_from_model(model, x, y, expected):
    assert _resolve_cell_index_from_model(model, x=x, y=y) == expected


CELLS_FROM_MESH = [
    pytest.param(None, 0.0, 0.0, None, id="no mesh"),
    pytest.param(
        SimpleNamespace(centers=structured_centroids(2, 3), structured_shape=(2, 3)),
        14.0,
        2.0,
        (0, 0, 1, 1),
        id="centers and structured shape",
    ),
    pytest.param(
        SimpleNamespace(centers=ROW_OF_FOUR, structured_shape=None),
        25.0,
        2.5,
        (0, 0, 2, 2),
        id="unstructured mesh gives flat index alone",
    ),
]


@pytest.mark.parametrize(("mesh", "x", "y", "expected"), CELLS_FROM_MESH)
def test_cell_index_from_cell_mesh(mesh, x, y, expected):
    assert _resolve_cell_index_from_cell_mesh(mesh, x=x, y=y) == expected


HEADS = [
    # head[1, 2, 3] is 23. The flat index is not used on a DIS array.
    pytest.param(
        np.arange(24.0).reshape(2, 3, 4),
        dict(layer=1, row=2, col=3, flat_index=0),
        23.0,
        id="dis 3d",
    ),
    # DISV has shape (nlay, 1, ncpl). Cell (row 2, col 3) on a 3 x 4 grid is flat 11.
    pytest.param(
        np.arange(12.0).reshape(1, 1, 12),
        dict(layer=0, row=2, col=3, flat_index=11),
        11.0,
        id="disv 3d via flat index",
    ),
    pytest.param(
        np.arange(12.0).reshape(1, 12),
        dict(layer=0, row=0, col=0, flat_index=7),
        7.0,
        id="2d falls back to flat index",
    ),
]


@pytest.mark.parametrize(("head", "cell", "expected"), HEADS)
def test_read_head_at_cell(head, cell, expected):
    assert _read_head_at_cell(head, ncol_hint=4, **cell) == expected


def head_decl(x, y, observed_values):
    return SimpleNamespace(
        variable="head", support="point", x=x, y=y, observed_values=observed_values
    )


NAN_OUTPUTS = [
    # No execution registry: every declaration collapses to NaN of the observed length.
    pytest.param(
        SimpleNamespace(execution=None, setup=SimpleNamespace()),
        "head_mid",
        head_decl(100.0, 20.0, (1.0, 2.0, 3.0)),
        3,
        id="no execution registry",
    ),
    # Empty registry: no flow run is mapped.
    pytest.param(
        SimpleNamespace(
            execution=SimpleNamespace(solver_runs={}, simulation_plan=None),
            setup=SimpleNamespace(),
        ),
        "head",
        head_decl(0.0, 0.0, (0.0, 0.0)),
        2,
        id="no flow run in the plan",
    ),
]


@pytest.mark.parametrize(("trial_ctx", "name", "decl", "length"), NAN_OUTPUTS)
def test_unknown_outputs_are_nan_padded(trial_ctx, name, decl, length):
    out = _extract_outputs_from_trial_ctx(trial_ctx=trial_ctx, output_decls=((name, decl),))

    assert len(out[name]) == length
    assert np.isnan(out[name]).all()


def test_head_is_none_when_hds_file_is_missing(tmp_path):
    result = _extract_head_at_point_from_dir(
        tmp_path, "missing_model", x=24.0, y=8.0, model=solver_model(2, 3), cell_mesh=None
    )

    assert result is None


def test_head_is_none_when_no_cell_is_found(tmp_path):
    # The file exists, but with no model and no cell mesh there is no (k, i, j) to read.
    (tmp_path / "stub_model.hds").write_bytes(b"")

    result = _extract_head_at_point_from_dir(
        tmp_path, "stub_model", x=24.0, y=8.0, model=None, cell_mesh=None
    )

    assert result is None


def test_truth_discharge_leaves_the_catchment_row_out():
    # The catchment cells lie in the domain, so adding their row counts them twice.
    budget = pd.DataFrame(
        [
            {"timestep": 0, "zone_id": "domain", "component": "constant_head", "flux_out": 3.0},
            {"timestep": 0, "zone_id": "catchment", "component": "constant_head", "flux_out": 1.0},
            {"timestep": 1, "zone_id": "domain", "component": "constant_head", "flux_out": 2.0},
            {"timestep": 1, "zone_id": "catchment", "component": "constant_head", "flux_out": 0.5},
        ]
    )

    values = _extract_outlet_discharge_from_run(SimpleNamespace(budget=lambda: budget))

    assert values.tolist() == [3.0, 2.0]
