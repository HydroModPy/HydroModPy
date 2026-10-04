"""Under the heads rule the maximal map is traced from the heads of both maps.

The maximal map contains the minimal one by definition. Two files that
disagree are scored on their union, and the gap is published. On the V-valley
bench the full network starts on row 12 and the permanent one on row 4, which
the full network does not draw: the maximal map is then the axis from row 4,
and ``frac_minimal_outside_maximal`` is the share of the permanent trace the
full network's own heads miss, rows 4 to 11.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.observations.network_geometry import network_maps_from_run
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


def _run_ctx(bench):
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
        model=SimpleNamespace(solver_mesh=solver_mesh, recharge=1.0e-8, lake_cell_ids_by_lake={}),
    )


def _axis(first_row: int) -> np.ndarray:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[[cell_id(row, AXIS_COL) for row in range(first_row, N_ROWS)]] = True
    return mask


def test_the_maximal_heads_map_contains_the_minimal_trace() -> None:
    output = validate_calib_output(
        {
            "support": "network",
            "observed_network": "data.hydrography",
            "minimal_observed_network": "data.hydrography",
            "diagonal_neighbors": True,
            "tau_specific_ratio": 0.0,
            "observed_rasterization": "heads",
            "heads_min_drained_area_km2": 0.0,
        }
    )

    maps = network_maps_from_run(_run_ctx(build_bench()), output)

    assert maps.minimal is not None
    np.testing.assert_array_equal(maps.minimal.observed, _axis(PERMANENT_FIRST_ROW))
    np.testing.assert_array_equal(maps.maximal.observed, _axis(PERMANENT_FIRST_ROW))
    assert maps.frac_minimal_outside_maximal == pytest.approx(
        (FIRST_OBSERVED_ROW - PERMANENT_FIRST_ROW) / (N_ROWS - PERMANENT_FIRST_ROW)
    )
