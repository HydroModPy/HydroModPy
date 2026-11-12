"""Cell projection of a mapped stream network on the solver mesh (cell size in m).

The map is drawn with the crossing rule (thin line through cell centres) or the heads
rule (free ends, on the criterion graph). Reaches that enter no cell are reported once.
The catchment the criterion closes is compared with the basin of D and the outline.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, box

from hydromodpy.calibration.config_outputs import validate_calib_output
from hydromodpy.calibration.metrics.solver_extract import catchment_area_the_discharge_sums
from hydromodpy.calibration.observations import observed_network
from hydromodpy.calibration.observations.network_geometry import network_maps_from_run
from hydromodpy.calibration.observations.network_source import (
    ObservedNetwork,
    UnresolvedObservedNetwork,
)
from hydromodpy.calibration.observations.observed_network import (
    catchment_outline_mask,
    delineated_catchment_mask,
    observed_network_mask,
    resolve_minimal_network,
)
from hydromodpy.catchment.drainage import descent as core_descent
from hydromodpy.catchment.drainage.descent import DescentBasin
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


def test_cell_projection_refuses_the_heads_rule() -> None:
    run_ctx = SimpleNamespace(
        state=SimpleNamespace(
            setup=SimpleNamespace(geographic=SimpleNamespace(crs_project="EPSG:2154"))
        )
    )
    observed = SimpleNamespace(
        geometry=gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 1)])], crs="EPSG:2154"),
        crs="EPSG:2154",
        source="file",
    )
    planar_mesh = SimpleNamespace(vertices=np.zeros((4, 3)))

    with pytest.raises(ValueError, match="criterion graph"):
        observed_network_mask(
            run_ctx,
            observed,
            planar_mesh,
            np.zeros((1, 4), dtype=int),
            rasterization="heads",
        )


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
    return SimpleNamespace(
        solver_run=SimpleNamespace(solver_model=SimpleNamespace(descent_basin=basin)), state=None
    )


POLYGON = np.array([False, True, True, True, False, False])


def test_basin_of_d_is_read_never_recomputed(monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("a consumer recomputed the basin of D instead of reading it")

    monkeypatch.setattr(core_descent, "descent_basin", refuse)
    monkeypatch.setattr(catchment_basin, "descent_basin", refuse)
    ctx = _ctx(_basin(_half()))

    delineated_catchment_mask(ctx, None, None)
    area = catchment_area_the_discharge_sums(ctx, SimpleNamespace())

    assert area == pytest.approx(ctx.solver_run.solver_model.descent_basin.area_m2)


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
        solver_run=SimpleNamespace(
            solver_model=SimpleNamespace(
                solver_mesh=solver_mesh, recharge=1.0e-8, dam_foot_cells={}, descent_basin=basin
            )
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
            "map": {"complete": str(path)},
            "model": {"neighbours": "D8", "seepage_threshold": 0.0},
        }
    )


OUTLET_XY = ((AXIS_COL + 0.5) * CELL_SIZE, (N_ROWS - 0.5) * CELL_SIZE)


def test_basin_equal_to_the_graph_catchment_leaves_no_gap(output) -> None:
    ctx = _bench_ctx(_basin(np.ones(N_CELLS, dtype=bool)), OUTLET_XY)

    geometry = network_maps_from_run(ctx, output).maximal

    assert geometry.catchment.all()
    assert geometry.diagnostics["catchment_mismatch"] == pytest.approx(0.0)


def test_gap_reads_the_outline_and_the_basin_has_its_own(output, monkeypatch) -> None:
    # An outlet on another branch closes the basin of D on that branch too, so the
    # basin cannot tell. The outline can, and the veto reads the gap to it.
    half = np.zeros(N_CELLS, dtype=bool)
    half[: N_CELLS // 2] = True
    monkeypatch.setattr(observed_network, "catchment_outline_mask", lambda *_args: half.copy())
    ctx = _bench_ctx(_basin(np.ones(N_CELLS, dtype=bool)), OUTLET_XY)

    diagnostics = network_maps_from_run(ctx, output).maximal.diagnostics

    assert diagnostics["catchment_mismatch"] == pytest.approx((N_CELLS - half.sum()) / half.sum())
    assert diagnostics["basin_mismatch"] == pytest.approx(0.0)


def test_smaller_basin_is_published_as_the_gap(output) -> None:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[: N_CELLS // 2] = True
    ctx = _bench_ctx(_basin(mask), OUTLET_XY)

    geometry = network_maps_from_run(ctx, output).maximal

    assert geometry.diagnostics["catchment_mismatch"] == pytest.approx(
        (N_CELLS - mask.sum()) / mask.sum()
    )


N = 12
CELL = 75.0


@pytest.fixture()
def _fresh_unplaced_reports():
    """Each test sees its placement for the first time."""
    observed_network._UNPLACED_REPORTS.clear()
    yield
    observed_network._UNPLACED_REPORTS.clear()


def _centre(row: int, col: int) -> tuple[float, float]:
    return ((col + 0.5) * CELL, (row + 0.5) * CELL)


def _run_ctx(*, with_centres: bool = True):
    rows, cols = np.divmod(np.arange(N * N), N)
    centres = np.column_stack([(cols + 0.5) * CELL, (rows + 0.5) * CELL])
    solver_mesh = SimpleNamespace(cell_centers=lambda: centres) if with_centres else None
    return SimpleNamespace(
        state=SimpleNamespace(setup=SimpleNamespace(geographic=SimpleNamespace(crs_project=CRS))),
        solver_run=SimpleNamespace(solver_model=SimpleNamespace(solver_mesh=solver_mesh)),
    )


def _diagonal() -> ObservedNetwork:
    line = LineString([_centre(k, k) for k in range(2, 10)])
    return ObservedNetwork(
        source="path",
        geometry=gpd.GeoDataFrame(geometry=[line], crs=CRS),
        crs=CRS,
        clipped=False,
        path="map.gpkg",
    )


def _mask(run_ctx, **kwargs) -> np.ndarray:
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)
    return observed_network_mask(
        run_ctx, _diagonal(), SimpleNamespace(vertices=vertices), connectivity, **kwargs
    ).mask


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_unknown_rule_is_refused() -> None:
    with pytest.raises(ValueError, match="map.drawn_by"):
        _mask(_run_ctx(), rasterization="centroid")


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_crossing_rule_needs_cell_centres() -> None:
    with pytest.raises(ValueError, match="cell_centers"):
        _mask(_run_ctx(with_centres=False))


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_reach_off_the_mesh_is_reported(caplog) -> None:
    # A 10 m reach 30 m below the grid, in the sliver outside every cell.
    off_mesh = LineString([(300.0, -30.0), (310.0, -30.0)])
    network = ObservedNetwork(
        source="path",
        geometry=gpd.GeoDataFrame(
            geometry=[LineString([_centre(k, k) for k in range(2, 10)]), off_mesh], crs=CRS
        ),
        crs=CRS,
        clipped=True,
        path="map.gpkg",
    )
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)

    with caplog.at_level(logging.WARNING, logger=observed_network.__name__):
        drawn = observed_network_mask(
            _run_ctx(), network, SimpleNamespace(vertices=vertices), connectivity
        )

    assert int(drawn.mask.sum()) == 8
    assert drawn.n_outside_parts == 1
    # A clipped map lies inside the catchment, so its reach is in the domain.
    assert "1 reach(es) inside the model domain, 10 m in all, enter no mesh cell" in (caplog.text)


def _unclipped(*extra: LineString) -> ObservedNetwork:
    return ObservedNetwork(
        source="path",
        geometry=gpd.GeoDataFrame(
            geometry=[LineString([_centre(k, k) for k in range(2, 10)]), *extra], crs=CRS
        ),
        crs=CRS,
        clipped=False,
        path="map.gpkg",
    )


def _run_ctx_with_catchment(tmp_path, *, margin: float):
    """A run whose delineated catchment overhangs the grid by ``margin`` meters."""

    shp = tmp_path / "watershed.shp"
    side = N * CELL
    gpd.GeoDataFrame(
        geometry=[box(-margin, -margin, side + margin, side + margin)], crs=CRS
    ).to_file(shp)
    ctx = _run_ctx()
    ctx.state.setup.geographic.watershed_shp = str(shp)
    return ctx


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_unclipped_map_without_a_catchment_only_informs(caplog) -> None:
    far = LineString([(5000.0, 5000.0), (5100.0, 5000.0)])
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)

    with caplog.at_level(logging.INFO, logger=observed_network.__name__):
        observed_network_mask(
            _run_ctx(), _unclipped(far), SimpleNamespace(vertices=vertices), connectivity
        )

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_same_placement_is_measured_once(tmp_path, caplog, monkeypatch) -> None:
    sliver = LineString([(300.0, -30.0), (310.0, -30.0)])
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)
    run_ctx = _run_ctx_with_catchment(tmp_path, margin=40.0)
    calls: list[int] = []
    measured = observed_network._unplaced_parts

    def _counting(*args, **kwargs):
        calls.append(1)
        return measured(*args, **kwargs)

    monkeypatch.setattr(observed_network, "_unplaced_parts", _counting)

    with caplog.at_level(logging.INFO, logger=observed_network.__name__):
        for _ in range(3):
            drawn = observed_network_mask(
                run_ctx, _unclipped(sliver), SimpleNamespace(vertices=vertices), connectivity
            )

    assert drawn.n_outside_parts == 1
    assert len(calls) == 1
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_new_placement_is_measured_again(tmp_path, caplog) -> None:
    sliver = LineString([(300.0, -30.0), (310.0, -30.0)])
    other = LineString([(500.0, -20.0), (540.0, -20.0)])
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)
    run_ctx = _run_ctx_with_catchment(tmp_path, margin=40.0)

    with caplog.at_level(logging.WARNING, logger=observed_network.__name__):
        for reach in (sliver, other):
            observed_network_mask(
                run_ctx, _unclipped(reach), SimpleNamespace(vertices=vertices), connectivity
            )

    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(messages) == 2
    assert "10 m in all" in messages[0]
    assert "40 m in all" in messages[1]


def _output(map=None, **overrides):
    return validate_calib_output(
        {"support": "network", "map": {"complete": "data.hydrography", **(map or {})}, **overrides}
    )


def _run_ctx__minimal_map(*, reference_permanent=None):
    networks = SimpleNamespace(reference_permanent=reference_permanent)
    geographic_features = SimpleNamespace(hydrographic_networks=networks)
    setup = SimpleNamespace(geographic_features=geographic_features)
    return SimpleNamespace(state=SimpleNamespace(setup=setup))


def test_run_without_a_permanent_network_is_refused():
    run_ctx = _run_ctx__minimal_map(reference_permanent=None)
    output = _output(map={"permanent": "data.hydrography", "calibrate_on": "permanent"})

    with pytest.raises(UnresolvedObservedNetwork) as excinfo:
        resolve_minimal_network(run_ctx, output)
    message = str(excinfo.value)
    assert "map.permanent = 'data.hydrography'" in message
    assert "as a file in 'map.permanent'" in message


def test_map_needs_a_projected_crs() -> None:
    run_ctx = _run_ctx()
    run_ctx.state.setup.geographic = SimpleNamespace()

    with pytest.raises(ValueError, match="declares no projected CRS"):
        observed_network._placeable(run_ctx, _diagonal())


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_placement_memory_is_emptied_when_full(monkeypatch) -> None:
    observed_network._UNPLACED_REPORTS["old"] = (0, 0, 0.0)
    monkeypatch.setattr(observed_network, "_UNPLACED_REPORTS_MAX", 1)

    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)
    network = _unclipped(LineString([(300.0, -30.0), (310.0, -30.0)]))
    observed_network_mask(_run_ctx(), network, SimpleNamespace(vertices=vertices), connectivity)

    assert "old" not in observed_network._UNPLACED_REPORTS
    assert len(observed_network._UNPLACED_REPORTS) == 1


def test_unplaced_parts_are_every_line_of_a_collection() -> None:
    nested = GeometryCollection(
        [Point(0, 0), MultiLineString([[(0, 0), (1, 0)], [(0, 1), (1, 1)]])]
    )
    observed = SimpleNamespace(crs=CRS, geometry=gpd.GeoDataFrame(geometry=[nested], crs=CRS))

    parts = observed_network._unplaced_parts(observed, np.array([None]), CRS)

    assert [part.wkt for part in parts] == ["LINESTRING (0 0, 1 0)", "LINESTRING (0 1, 1 1)"]


def test_domain_outline_needs_a_crs(tmp_path) -> None:
    shp = tmp_path / "outline.gpkg"
    gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)]).to_file(shp)
    run_ctx = SimpleNamespace(
        state=SimpleNamespace(setup=SimpleNamespace(geographic=SimpleNamespace(watershed_shp=shp)))
    )

    assert observed_network._domain_outline(run_ctx, CRS) is None


def test_outline_marks_the_cells_whose_centre_it_holds(tmp_path) -> None:
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)
    planar_mesh = SimpleNamespace(vertices=vertices)
    delineated = _run_ctx_with_catchment(tmp_path, margin=0.0)
    no_crs = _run_ctx_with_catchment(tmp_path, margin=0.0)
    no_crs.state.setup.geographic.crs_project = None

    assert catchment_outline_mask(delineated, planar_mesh, connectivity).all()
    assert catchment_outline_mask(no_crs, planar_mesh, connectivity) is None
    assert catchment_outline_mask(_run_ctx(), planar_mesh, connectivity) is None
