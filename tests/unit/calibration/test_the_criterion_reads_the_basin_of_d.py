"""The catchment the criterion is compared with is the basin of D the model kept.

The criterion closes its own catchment on its own graph and publishes how far it
sits from a reference, ``catchment_mismatch``. That reference is the basin of D
of the build, the cells the budget zone and the discharge observable also sum.
A model without a basin keeps the delineated polygon and says so.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.metrics.solver_extract import catchment_area_the_discharge_sums
from hydromodpy.calibration.observations import observed_network
from hydromodpy.calibration.observations.network_geometry import network_maps_from_run
from hydromodpy.calibration.observations.observed_network import delineated_catchment_mask
from hydromodpy.core import descent as core_descent
from hydromodpy.core.descent import DescentBasin
from hydromodpy.solver.modflow_common import catchment_basin
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    FIRST_OBSERVED_ROW,
    N_CELLS,
    N_COLS,
    N_ROWS,
    build_bench,
)

gpd = pytest.importorskip("geopandas")

from shapely.geometry import LineString  # noqa: E402

CRS = "EPSG:2154"
NO_BASIN_WARNING = (
    "Network criterion: the model carries no basin of D, so the catchment mismatch is "
    "measured against the old reference 'polygon_centroid'."
)


def _basin(mask: np.ndarray, rule: str = "near_point") -> DescentBasin:
    return DescentBasin(
        mask=mask,
        outlet=int(np.flatnonzero(mask)[0]),
        rule=rule,
        area_m2=float(mask.sum()) * CELL_SIZE**2,
        seeded_at_outlet=False,
    )


def _half(n_cells: int = 6) -> np.ndarray:
    mask = np.zeros(n_cells, dtype=bool)
    mask[: n_cells // 2] = True
    return mask


def _ctx(basin: DescentBasin | None) -> SimpleNamespace:
    return SimpleNamespace(model=SimpleNamespace(descent_basin=basin), state=None)


POLYGON = np.array([False, True, True, True, False, False])


@pytest.fixture
def polygon(monkeypatch):
    """Serve the polygon projection without a shapefile on disk."""
    monkeypatch.setattr(observed_network, "_polygon_catchment_mask", lambda *_args: POLYGON.copy())


def test_a_model_basin_is_the_reference(polygon, caplog) -> None:
    mask = _half()

    with caplog.at_level(logging.WARNING):
        reference = delineated_catchment_mask(_ctx(_basin(mask)), None, None)

    np.testing.assert_array_equal(reference, mask)
    assert NO_BASIN_WARNING not in caplog.text


def test_the_reference_is_a_copy_the_caller_may_edit(polygon) -> None:
    basin = _basin(_half())

    delineated_catchment_mask(_ctx(basin), None, None)[:] = False

    assert basin.mask.any()


def test_a_model_without_a_basin_keeps_the_polygon_and_says_so(polygon, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        reference = delineated_catchment_mask(_ctx(None), None, None)

    np.testing.assert_array_equal(reference, POLYGON)
    assert NO_BASIN_WARNING in caplog.text


def test_a_model_that_builds_no_d_keeps_the_polygon_with_an_info_line(polygon, caplog) -> None:
    # Boussinesq has no D, so no basin: expected, not an anomaly to warn about at each trial.
    ctx = SimpleNamespace(model=SimpleNamespace(), state=None)

    with caplog.at_level(logging.INFO):
        reference = delineated_catchment_mask(ctx, None, None)

    np.testing.assert_array_equal(reference, POLYGON)
    record = next(r for r in caplog.records if r.getMessage() == NO_BASIN_WARNING)
    assert record.levelno == logging.INFO


def test_the_largest_basin_of_a_synthetic_domain_is_no_catchment(polygon, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        reference = delineated_catchment_mask(
            _ctx(_basin(_half(), rule="largest_basin")), None, None
        )

    np.testing.assert_array_equal(reference, POLYGON)
    assert NO_BASIN_WARNING not in caplog.text


def test_a_domain_with_neither_basin_nor_polygon_gives_none(monkeypatch, caplog) -> None:
    monkeypatch.setattr(observed_network, "_polygon_catchment_mask", lambda *_args: None)

    with caplog.at_level(logging.WARNING):
        reference = delineated_catchment_mask(_ctx(None), None, None)

    assert reference is None
    assert NO_BASIN_WARNING not in caplog.text


def test_no_calibration_reader_computes_the_basin_again(monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("a consumer recomputed the basin of D instead of reading it")

    monkeypatch.setattr(core_descent, "descent_basin", refuse)
    monkeypatch.setattr(catchment_basin, "descent_basin", refuse)
    ctx = _ctx(_basin(_half()))

    delineated_catchment_mask(ctx, None, None)
    area = catchment_area_the_discharge_sums(ctx, SimpleNamespace())

    assert area == pytest.approx(ctx.model.descent_basin.area_m2)


# --- the criterion publishes its gap to that reference --------------------------------


def _bench_ctx(basin: DescentBasin | None, outlet_xy: tuple[float, float]):
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
        cell_centers=lambda: centroids,
    )
    return SimpleNamespace(
        run=SimpleNamespace(id="r1", solver="modflow6"),
        state=SimpleNamespace(
            setup=SimpleNamespace(
                geographic=SimpleNamespace(
                    crs_project=CRS, x_outlet_snapped=outlet_xy[0], y_outlet_snapped=outlet_xy[1]
                )
            )
        ),
        model=SimpleNamespace(
            solver_mesh=solver_mesh, recharge=1.0e-8, dam_foot_cells={}, descent_basin=basin
        ),
    )


@pytest.fixture(scope="module")
def output(tmp_path_factory):
    line = LineString(
        [
            ((AXIS_COL + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)
            for row in range(FIRST_OBSERVED_ROW, N_ROWS)
        ]
    )
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


OUTLET_XY = ((AXIS_COL + 0.5) * CELL_SIZE, (N_ROWS - 0.5) * CELL_SIZE)


def test_a_basin_that_is_the_graph_catchment_leaves_no_gap(output) -> None:
    ctx = _bench_ctx(_basin(np.ones(N_CELLS, dtype=bool)), OUTLET_XY)

    geometry = network_maps_from_run(ctx, output).maximal

    assert geometry.catchment.all()
    assert geometry.diagnostics["catchment_mismatch"] == pytest.approx(0.0)


def test_a_smaller_basin_is_published_as_the_gap(output) -> None:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[: N_CELLS // 2] = True
    ctx = _bench_ctx(_basin(mask), OUTLET_XY)

    geometry = network_maps_from_run(ctx, output).maximal

    assert geometry.diagnostics["catchment_mismatch"] == pytest.approx(
        (N_CELLS - mask.sum()) / mask.sum()
    )
