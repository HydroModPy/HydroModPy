"""Tests of `observations.observed_network`."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, box

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.metrics.solver_extract import catchment_area_the_discharge_sums
from hydromodpy.calibration.observations import observed_network
from hydromodpy.calibration.observations import observed_network as observed_module
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

# From test_the_cell_projection_refuses_the_heads_rule.py
# The cell projection of a mapped network refuses the heads rule by name.
#
# Under ``"heads"`` the map is drawn on the criterion graph from the free ends of
# the lines, so no cell projection exists to hand back; a caller asking for one
# would score a map the trial never drew.


def test_the_cell_projection_refuses_the_heads_rule() -> None:
    with pytest.raises(ValueError, match="criterion graph"):
        observed_network_mask(
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            np.zeros((1, 4), dtype=int),
            rasterization="heads",
        )


# From test_the_criterion_reads_the_basin_of_d.py
# The catchment the criterion is compared with is the basin of D the model kept.
#
# The criterion closes its own catchment on its own graph and publishes how far it
# sits from two references. ``basin_mismatch`` reads the basin of D of the build, the
# cells the budget zone and the discharge observable also sum. ``catchment_mismatch``
# reads the delineated outline. A model without a basin keeps the delineated polygon
# and says so.


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
    monkeypatch.setattr(observed_network, "catchment_outline_mask", lambda *_args: POLYGON.copy())


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
    monkeypatch.setattr(observed_network, "catchment_outline_mask", lambda *_args: None)

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
            "map": {"complete": str(path)},
            "model": {"neighbours": "D8", "seepage_threshold": 0.0},
        }
    )


OUTLET_XY = ((AXIS_COL + 0.5) * CELL_SIZE, (N_ROWS - 0.5) * CELL_SIZE)


def test_a_basin_that_is_the_graph_catchment_leaves_no_gap(output) -> None:
    ctx = _bench_ctx(_basin(np.ones(N_CELLS, dtype=bool)), OUTLET_XY)

    geometry = network_maps_from_run(ctx, output).maximal

    assert geometry.catchment.all()
    assert geometry.diagnostics["catchment_mismatch"] == pytest.approx(0.0)


def test_the_gap_reads_the_delineated_outline_and_the_basin_has_its_own(
    output, monkeypatch
) -> None:
    # An outlet on another branch closes the basin of D on that branch too, so the
    # basin cannot tell. The outline can, and the veto reads the gap to it.
    half = np.zeros(N_CELLS, dtype=bool)
    half[: N_CELLS // 2] = True
    monkeypatch.setattr(observed_network, "catchment_outline_mask", lambda *_args: half.copy())
    ctx = _bench_ctx(_basin(np.ones(N_CELLS, dtype=bool)), OUTLET_XY)

    diagnostics = network_maps_from_run(ctx, output).maximal.diagnostics

    assert diagnostics["catchment_mismatch"] == pytest.approx((N_CELLS - half.sum()) / half.sum())
    assert diagnostics["basin_mismatch"] == pytest.approx(0.0)


def test_a_smaller_basin_is_published_as_the_gap(output) -> None:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[: N_CELLS // 2] = True
    ctx = _bench_ctx(_basin(mask), OUTLET_XY)

    geometry = network_maps_from_run(ctx, output).maximal

    assert geometry.diagnostics["catchment_mismatch"] == pytest.approx(
        (N_CELLS - mask.sum()) / mask.sum()
    )


# From test_the_mapped_network_is_drawn_thin.py
# The criterion draws the mapped network with the crossing rule unless told otherwise.
#
# ``observed_network_mask`` picks between ``"crossing"``, the thin line of
# WhiteboxTools VectorLinesToRaster that the paper used, and ``"touch"``, the
# rule before 2026-09, kept to replay an old session. The crossing rule joins
# the centers the solver mesh sampled its top at, so it reads them from the run.


N = 12
CELL = 75.0


@pytest.fixture()
def _fresh_unplaced_reports():
    """Each test sees its placement for the first time."""
    observed_module._UNPLACED_REPORTS.clear()
    yield
    observed_module._UNPLACED_REPORTS.clear()


def _centre(row: int, col: int) -> tuple[float, float]:
    return ((col + 0.5) * CELL, (row + 0.5) * CELL)


def _run_ctx(*, with_centres: bool = True):
    rows, cols = np.divmod(np.arange(N * N), N)
    centres = np.column_stack([(cols + 0.5) * CELL, (rows + 0.5) * CELL])
    solver_mesh = SimpleNamespace(cell_centers=lambda: centres) if with_centres else None
    return SimpleNamespace(
        state=SimpleNamespace(setup=SimpleNamespace(geographic=SimpleNamespace(crs_project=CRS))),
        model=SimpleNamespace(solver_mesh=solver_mesh),
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
def test_the_default_rule_draws_the_diagonal_one_cell_per_step() -> None:
    mask = _mask(_run_ctx())

    assert np.flatnonzero(mask).tolist() == [k * N + k for k in range(2, 10)]


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_touch_is_accepted_and_adds_the_corner_pairs() -> None:
    mask = _mask(_run_ctx(), rasterization="touch")

    assert int(mask.sum()) == 8 + 2 * 7


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_an_unknown_rule_is_refused() -> None:
    with pytest.raises(ValueError, match="map.drawn_by"):
        _mask(_run_ctx(), rasterization="centroid")


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_explicit_centres_win_over_the_run() -> None:
    rows, cols = np.divmod(np.arange(N * N), N)
    centres = np.column_stack([(cols + 0.5) * CELL, (rows + 0.5) * CELL])

    mask = _mask(_run_ctx(with_centres=False), cell_centres=centres)

    assert int(mask.sum()) == 8


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_a_run_without_centres_is_refused_by_the_crossing_rule() -> None:
    with pytest.raises(ValueError, match="cell_centers"):
        _mask(_run_ctx(with_centres=False))


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_the_log_names_the_rule(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=observed_module.__name__):
        _mask(_run_ctx())

    assert "by the crossing rule" in caplog.text


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_a_reach_off_the_mesh_is_reported_as_left_out(caplog) -> None:
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

    with caplog.at_level(logging.WARNING, logger=observed_module.__name__):
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
def test_a_map_wider_than_the_catchment_only_informs(tmp_path, caplog) -> None:
    # A reach 5 km off the grid: the map is wider than the catchment, as the
    # BD Topage extract of a department is.
    far = LineString([(5000.0, 5000.0), (5100.0, 5000.0)])
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)

    with caplog.at_level(logging.INFO, logger=observed_module.__name__):
        drawn = observed_network_mask(
            _run_ctx_with_catchment(tmp_path, margin=40.0),
            _unclipped(far),
            SimpleNamespace(vertices=vertices),
            connectivity,
        )

    assert drawn.n_outside_parts == 1
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == []
    assert "1 reach(es) lie outside the model domain" in caplog.text


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_a_reach_inside_the_catchment_that_enters_no_cell_warns(tmp_path, caplog) -> None:
    far = LineString([(5000.0, 5000.0), (5100.0, 5000.0)])
    sliver = LineString([(300.0, -30.0), (310.0, -30.0)])
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)

    with caplog.at_level(logging.INFO, logger=observed_module.__name__):
        drawn = observed_network_mask(
            _run_ctx_with_catchment(tmp_path, margin=40.0),
            _unclipped(far, sliver),
            SimpleNamespace(vertices=vertices),
            connectivity,
        )

    assert drawn.n_outside_parts == 2
    (warning,) = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert "1 reach(es) inside the model domain, 10 m in all, enter no mesh cell" in warning
    assert "1 reach(es) lie outside the model domain" in caplog.text


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_an_unclipped_map_without_a_catchment_only_informs(caplog) -> None:
    far = LineString([(5000.0, 5000.0), (5100.0, 5000.0)])
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)

    with caplog.at_level(logging.INFO, logger=observed_module.__name__):
        observed_network_mask(
            _run_ctx(), _unclipped(far), SimpleNamespace(vertices=vertices), connectivity
        )

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_the_count_and_the_length_describe_the_same_reaches(tmp_path, caplog) -> None:
    # One feature of two sliver parts, 10 m and 20 m, inside the catchment.

    split = MultiLineString([[(300.0, -30.0), (310.0, -30.0)], [(500.0, -20.0), (520.0, -20.0)]])
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)

    with caplog.at_level(logging.WARNING, logger=observed_module.__name__):
        drawn = observed_network_mask(
            _run_ctx_with_catchment(tmp_path, margin=40.0),
            _unclipped(split),
            SimpleNamespace(vertices=vertices),
            connectivity,
        )

    assert drawn.n_outside_parts == 2
    (warning,) = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert "2 reach(es) inside the model domain, 30 m in all, enter no mesh cell" in warning


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_a_second_build_of_the_same_placement_skips_the_geometry_work(
    tmp_path, caplog, monkeypatch
) -> None:
    sliver = LineString([(300.0, -30.0), (310.0, -30.0)])
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)
    run_ctx = _run_ctx_with_catchment(tmp_path, margin=40.0)
    calls: list[int] = []
    measured = observed_module._unplaced_parts

    def _counting(*args, **kwargs):
        calls.append(1)
        return measured(*args, **kwargs)

    monkeypatch.setattr(observed_module, "_unplaced_parts", _counting)

    with caplog.at_level(logging.INFO, logger=observed_module.__name__):
        for _ in range(3):
            drawn = observed_network_mask(
                run_ctx, _unclipped(sliver), SimpleNamespace(vertices=vertices), connectivity
            )

    assert drawn.n_outside_parts == 1
    assert len(calls) == 1
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_a_new_placement_is_measured_again(tmp_path, caplog) -> None:
    sliver = LineString([(300.0, -30.0), (310.0, -30.0)])
    other = LineString([(500.0, -20.0), (540.0, -20.0)])
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)
    run_ctx = _run_ctx_with_catchment(tmp_path, margin=40.0)

    with caplog.at_level(logging.WARNING, logger=observed_module.__name__):
        for reach in (sliver, other):
            observed_network_mask(
                run_ctx, _unclipped(reach), SimpleNamespace(vertices=vertices), connectivity
            )

    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(messages) == 2
    assert "10 m in all" in messages[0]
    assert "40 m in all" in messages[1]


# From test_the_minimal_map_reads_the_permanent_network.py
# The minimal map resolves from the run's permanent hydrographic network, or refuses by name.
#
# ``minimal_observed_network = "data.hydrography"`` reads the network the
# geographic pipeline attached under the ``reference_permanent`` role
# (:class:`hydromodpy.spatial.geographic.core.hydrographic_network.HydrographicNetworks`),
# never the full ``reference`` one: a source that does not say which reaches are
# permanent (a custom file with no permanence column, OSM) leaves that role
# ``None``, and the output is refused by name rather than silently scored on the
# maximal map.


def _output(map=None, **overrides):
    return validate_calib_output(
        {"support": "network", "map": {"complete": "data.hydrography", **(map or {})}, **overrides}
    )


def _permanent_network(vector_path="/data/streams_permanent.shp", crs=CRS):
    gdf = gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 2)])], crs=crs
    )
    return SimpleNamespace(vector_path=vector_path, crs=crs, read_vector=lambda: gdf)


def _run_ctx__minimal_map(*, reference_permanent=None):
    networks = SimpleNamespace(reference_permanent=reference_permanent)
    geographic_features = SimpleNamespace(hydrographic_networks=networks)
    setup = SimpleNamespace(geographic_features=geographic_features)
    return SimpleNamespace(state=SimpleNamespace(setup=setup))


class TestAReferencePermanentNetworkIsScored:
    def test_the_run_s_reference_permanent_network_resolves_the_minimal_map(self) -> None:
        run_ctx = _run_ctx__minimal_map(reference_permanent=_permanent_network())
        output = _output(map={"permanent": "data.hydrography", "calibrate_on": "permanent"})

        resolved = resolve_minimal_network(run_ctx, output)

        assert resolved is not None
        assert resolved.source == "data.hydrography"
        assert resolved.clipped is True
        assert resolved.path == "/data/streams_permanent.shp"
        assert resolved.crs == CRS
        assert len(resolved.geometry) == 2

    def test_it_never_reads_the_full_reference_network(self) -> None:
        # A run carrying only the maximal network (no permanence in its source)
        # must not be silently scored on it under the minimal role.
        run_ctx = SimpleNamespace(
            state=SimpleNamespace(
                setup=SimpleNamespace(
                    geographic_features=SimpleNamespace(
                        hydrographic_networks=SimpleNamespace(
                            reference=_permanent_network(vector_path="/data/streams.shp"),
                            reference_permanent=None,
                        )
                    )
                )
            )
        )
        output = _output(map={"permanent": "data.hydrography", "calibrate_on": "permanent"})

        with pytest.raises(UnresolvedObservedNetwork):
            resolve_minimal_network(run_ctx, output)


class TestARunWithoutAPermanentNetworkIsRefusedByName:
    def test_a_run_without_reference_permanent_is_refused_by_name(self) -> None:
        run_ctx = _run_ctx__minimal_map(reference_permanent=None)
        output = _output(map={"permanent": "data.hydrography", "calibrate_on": "permanent"})

        with pytest.raises(UnresolvedObservedNetwork) as excinfo:
            resolve_minimal_network(run_ctx, output)
        message = str(excinfo.value)
        assert "map.permanent = 'data.hydrography'" in message
        assert "as a file in 'map.permanent'" in message

    def test_no_minimal_source_declared_resolves_to_none(self) -> None:
        run_ctx = _run_ctx__minimal_map(reference_permanent=_permanent_network())
        output = _output()

        assert resolve_minimal_network(run_ctx, output) is None


class TestTheExplicitFileStillResolves:
    def test_a_declared_file_is_read_regardless_of_the_run_s_permanent_network(
        self, tmp_path
    ) -> None:
        path = tmp_path / "permanent.gpkg"
        gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 1)])], crs=CRS).to_file(
            path, driver="GPKG"
        )
        run_ctx = _run_ctx__minimal_map(reference_permanent=None)
        output = _output(map={"permanent": str(path), "calibrate_on": "permanent"})

        resolved = resolve_minimal_network(run_ctx, output)

        assert resolved is not None
        assert resolved.source == "path"
        assert resolved.clipped is False
        assert resolved.path == str(path)


# The refusals and the readers of the placement, on the shapes a trial leaves aside.


def test_a_map_cannot_be_placed_on_a_run_with_no_projected_crs() -> None:
    run_ctx = _run_ctx()
    run_ctx.state.setup.geographic = SimpleNamespace()

    with pytest.raises(ValueError, match="declares no projected CRS"):
        observed_module._placeable(run_ctx, _diagonal())


@pytest.mark.usefixtures("_fresh_unplaced_reports")
def test_the_placement_memory_is_emptied_when_it_is_full(monkeypatch) -> None:
    observed_module._UNPLACED_REPORTS["old"] = (0, 0, 0.0)
    monkeypatch.setattr(observed_module, "_UNPLACED_REPORTS_MAX", 1)

    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)
    network = _unclipped(LineString([(300.0, -30.0), (310.0, -30.0)]))
    observed_network_mask(_run_ctx(), network, SimpleNamespace(vertices=vertices), connectivity)

    assert "old" not in observed_module._UNPLACED_REPORTS
    assert len(observed_module._UNPLACED_REPORTS) == 1


def test_the_parts_no_cell_touches_are_every_line_of_a_nested_collection() -> None:
    nested = GeometryCollection(
        [Point(0, 0), MultiLineString([[(0, 0), (1, 0)], [(0, 1), (1, 1)]])]
    )
    observed = SimpleNamespace(crs=CRS, geometry=gpd.GeoDataFrame(geometry=[nested], crs=CRS))

    parts = observed_module._unplaced_parts(observed, np.array([None]), CRS)

    assert [part.wkt for part in parts] == ["LINESTRING (0 0, 1 0)", "LINESTRING (0 1, 1 1)"]


def test_a_domain_outline_needs_a_file_with_a_crs(tmp_path) -> None:
    shp = tmp_path / "outline.gpkg"
    gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)]).to_file(shp)
    run_ctx = SimpleNamespace(
        state=SimpleNamespace(setup=SimpleNamespace(geographic=SimpleNamespace(watershed_shp=shp)))
    )

    assert observed_module._domain_outline(run_ctx, CRS) is None


def test_the_catchment_outline_marks_the_cells_whose_centre_it_holds(tmp_path) -> None:
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)
    planar_mesh = SimpleNamespace(vertices=vertices)
    delineated = _run_ctx_with_catchment(tmp_path, margin=0.0)
    no_crs = _run_ctx_with_catchment(tmp_path, margin=0.0)
    no_crs.state.setup.geographic.crs_project = None

    assert catchment_outline_mask(delineated, planar_mesh, connectivity).all()
    assert catchment_outline_mask(no_crs, planar_mesh, connectivity) is None
    assert catchment_outline_mask(_run_ctx(), planar_mesh, connectivity) is None
