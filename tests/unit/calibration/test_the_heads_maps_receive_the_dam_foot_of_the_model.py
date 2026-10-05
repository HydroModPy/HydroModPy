"""The heads maps of a calibration take the dam foot of the built model as a head.

The build leaves ``{lake id: cell}`` on the model: the cell below each dam, where
the stream under the reservoir starts. Both maps of a heads output (the maximal
and the minimal) are traced from it as well as from the free ends of their
files. A model without lakes, or a backend that sets none, draws as before.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.observations.network_geometry import (
    dam_foot_cells_of_model,
    network_maps_from_run,
)
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    FIRST_OBSERVED_ROW,
    N_CELLS,
    N_COLS,
    N_ROWS,
    build_bench,
    cell_id,
)

gpd = pytest.importorskip("geopandas")

from shapely.geometry import LineString  # noqa: E402

CRS = "EPSG:2154"
PERMANENT_FIRST_ROW = 4
DAM_FOOT = cell_id(40, AXIS_COL - 6)


def _axis_network(first_row: int):
    talweg = LineString(
        [
            ((AXIS_COL + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)
            for row in range(first_row, N_ROWS)
        ]
    )
    lines = gpd.GeoDataFrame(geometry=[talweg], crs=CRS)
    return SimpleNamespace(
        vector_path=f"/fake/axis_{first_row}.gpkg", crs=CRS, read_vector=lambda: lines
    )


def _run_ctx(bench, dam_foot_cells=None):
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
    rows, cols = np.divmod(np.arange(N_CELLS), N_COLS)
    centroids = np.column_stack([(cols + 0.5) * CELL_SIZE, (rows + 0.5) * CELL_SIZE])
    solver_mesh = SimpleNamespace(
        top=bench.elevation,
        planar_mesh=SimpleNamespace(
            vertices=vertices, flat_connectivity=connectivity, n_cells=N_CELLS
        ),
        n_cells=N_CELLS,
        cell_areas=lambda: np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
        cell_centroids=lambda: centroids,
    )
    networks = SimpleNamespace(
        reference=_axis_network(FIRST_OBSERVED_ROW),
        reference_permanent=_axis_network(PERMANENT_FIRST_ROW),
        generated=None,
    )
    return SimpleNamespace(
        run=SimpleNamespace(id="r1", solver="modflow6"),
        state=SimpleNamespace(
            setup=SimpleNamespace(
                geographic=SimpleNamespace(crs_project=CRS),
                geographic_features=SimpleNamespace(hydrographic_networks=networks),
            ),
        ),
        model=SimpleNamespace(
            solver_mesh=solver_mesh,
            recharge=1.0e-8,
            lake_cell_ids_by_lake={},
            dam_foot_cells={} if dam_foot_cells is None else dam_foot_cells,
        ),
    )


def _output(**extra):
    return validate_calib_output(
        {
            "support": "network",
            "observed_network": "data.hydrography",
            "diagonal_neighbors": True,
            "tau_specific_ratio": 0.0,
            "observed_rasterization": "heads",
            "heads_min_drained_area_km2": 0.0,
            **extra,
        }
    )


def _descent_of(cells, downstream):
    walk = []
    cell = int(cells)
    while cell >= 0:
        walk.append(cell)
        cell = int(downstream[cell])
    return walk


def test_the_maximal_map_is_traced_from_the_dam_foot_of_the_model() -> None:
    bench = build_bench()
    plain = network_maps_from_run(_run_ctx(bench), _output())
    forced = network_maps_from_run(
        _run_ctx(bench, dam_foot_cells={"reservoir": DAM_FOOT}), _output()
    )

    assert not plain.maximal.observed[DAM_FOOT]
    assert forced.maximal.observed[DAM_FOOT]
    for cell in _descent_of(DAM_FOOT, forced.maximal.metric.graph.downstream):
        assert forced.maximal.observed[cell]
    assert forced.maximal.heads is not None
    assert forced.maximal.heads.forced_cell.tolist() == [DAM_FOOT]
    assert forced.maximal.diagnostics["n_forced_heads"] == 1.0
    assert plain.maximal.diagnostics["n_forced_heads"] == 0.0


def test_the_minimal_map_receives_it_too_and_the_maximal_trace_still_contains_it() -> None:
    maps = network_maps_from_run(
        _run_ctx(build_bench(), dam_foot_cells={"reservoir": DAM_FOOT}),
        _output(minimal_observed_network="data.hydrography"),
    )

    assert maps.minimal is not None and maps.minimal.heads is not None
    assert maps.minimal.heads.forced_cell.tolist() == [DAM_FOOT]
    assert maps.minimal.observed[DAM_FOOT]
    assert not (maps.minimal.observed & ~maps.maximal.observed).any()


def test_a_model_without_a_dam_foot_draws_as_before() -> None:
    assert dam_foot_cells_of_model(SimpleNamespace(dam_foot_cells={})).size == 0
    assert dam_foot_cells_of_model(
        SimpleNamespace(dam_foot_cells={"b": 9, "a": 4, "c": 9})
    ).tolist() == [4, 9]
