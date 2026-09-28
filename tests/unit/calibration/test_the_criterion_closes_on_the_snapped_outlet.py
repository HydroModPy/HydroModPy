"""A trial places its outlet from the pour point the geographic step snapped.

The delineation closed the catchment on the snapped outlet, not on the declared
one. The criterion reads that point off the geographic runtime object and
moves it within two cells onto the most accumulated cell of its own graph.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.observations.network_geometry import geometry_from_run
from hydromodpy.calibration.observations.observed_network import delineated_outlet_xy
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


def _centre(row: int, col: int) -> tuple[float, float]:
    return ((col + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)


def _run_ctx(**geographic):
    bench = build_bench()
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
    return SimpleNamespace(
        run=SimpleNamespace(id="r1", solver="modflow6"),
        state=SimpleNamespace(
            setup=SimpleNamespace(geographic=SimpleNamespace(crs_project=CRS, **geographic))
        ),
        model=SimpleNamespace(solver_mesh=solver_mesh, recharge=1.0e-8),
    )


@pytest.fixture(scope="module")
def output(tmp_path_factory):
    line = LineString([_centre(row, AXIS_COL) for row in range(FIRST_OBSERVED_ROW, N_ROWS)])
    path = tmp_path_factory.mktemp("network") / "streams.gpkg"
    gpd.GeoDataFrame(geometry=[line], crs=CRS).to_file(path, driver="GPKG")
    return validate_calib_output(
        {
            "support": "network",
            "stream_geometry_path": str(path),
            "diagonal_neighbors": True,
            "tau_specific_ratio": 0.0,
        }
    )


class TestTheSnappedPointIsRead:
    def test_it_is_the_snapped_point_not_the_declared_one(self) -> None:
        ctx = _run_ctx(x_outlet=1.0, y_outlet=2.0, x_outlet_snapped=3.0, y_outlet_snapped=4.0)

        assert delineated_outlet_xy(ctx) == (3.0, 4.0)

    @pytest.mark.parametrize(
        "geographic",
        [{}, {"x_outlet_snapped": None, "y_outlet_snapped": None}, {"x_outlet_snapped": 3.0}],
    )
    def test_a_catchment_drawn_as_a_polygon_has_none(self, geographic) -> None:
        assert delineated_outlet_xy(_run_ctx(**geographic)) is None


class TestTheTrialClosesOnIt:
    def test_a_point_one_cell_off_the_outlet_lands_on_it(self, output) -> None:
        x, y = _centre(N_ROWS - 2, AXIS_COL + 1)
        geometry, _, _ = geometry_from_run(_run_ctx(x_outlet_snapped=x, y_outlet_snapped=y), output)

        assert geometry.outlet == cell_id(N_ROWS - 1, AXIS_COL)
        assert geometry.catchment.all()

    def test_a_point_on_a_hillslope_closes_a_smaller_catchment(self, output) -> None:
        x, y = _centre(N_ROWS - 1, 2)
        geometry, _, _ = geometry_from_run(_run_ctx(x_outlet_snapped=x, y_outlet_snapped=y), output)

        assert geometry.outlet != cell_id(N_ROWS - 1, AXIS_COL)
        assert 0 < int(geometry.catchment.sum()) < N_CELLS
        # No watershed polygon on this run, so there is no gap to publish.
        assert np.isnan(geometry.diagnostics["catchment_mismatch"])
