"""The criterion draws the mapped network with the crossing rule unless told otherwise.

``observed_network_mask`` picks between ``"crossing"``, the thin line of
WhiteboxTools VectorLinesToRaster that the paper used, and ``"touch"``, the
rule before 2026-09, kept to replay an old session. The crossing rule joins
the centres the solver mesh sampled its top at, so it reads them from the run.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

gpd = pytest.importorskip("geopandas")

from shapely.geometry import LineString  # noqa: E402

from hydromodpy.calibration.observations import observed_network as observed_module  # noqa: E402
from hydromodpy.calibration.observations.network_source import ObservedNetwork  # noqa: E402
from hydromodpy.calibration.observations.observed_network import (  # noqa: E402
    observed_network_mask,
)
from tests._helpers.ugrid_meshes import quad_mesh  # noqa: E402

CRS = "EPSG:2154"
N = 12
CELL = 75.0


@pytest.fixture(autouse=True)
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
    solver_mesh = SimpleNamespace(cell_centroids=lambda: centres) if with_centres else None
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
        dem_derived=False,
        path="map.gpkg",
    )


def _mask(run_ctx, **kwargs) -> np.ndarray:
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)
    return observed_network_mask(
        run_ctx, _diagonal(), SimpleNamespace(vertices=vertices), connectivity, **kwargs
    ).mask


def test_the_default_rule_draws_the_diagonal_one_cell_per_step() -> None:
    mask = _mask(_run_ctx())

    assert np.flatnonzero(mask).tolist() == [k * N + k for k in range(2, 10)]


def test_touch_is_accepted_and_adds_the_corner_pairs() -> None:
    mask = _mask(_run_ctx(), rasterization="touch")

    assert int(mask.sum()) == 8 + 2 * 7


def test_an_unknown_rule_is_refused() -> None:
    with pytest.raises(ValueError, match="observed_rasterization"):
        _mask(_run_ctx(), rasterization="centroid")


def test_explicit_centres_win_over_the_run() -> None:
    rows, cols = np.divmod(np.arange(N * N), N)
    centres = np.column_stack([(cols + 0.5) * CELL, (rows + 0.5) * CELL])

    mask = _mask(_run_ctx(with_centres=False), cell_centres=centres)

    assert int(mask.sum()) == 8


def test_a_run_without_centres_is_refused_by_the_crossing_rule() -> None:
    with pytest.raises(ValueError, match="cell_centroids"):
        _mask(_run_ctx(with_centres=False))


def test_the_log_names_the_rule(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=observed_module.__name__):
        _mask(_run_ctx())

    assert "by the crossing rule" in caplog.text


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
        dem_derived=False,
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
        dem_derived=False,
        path="map.gpkg",
    )


def _run_ctx_with_catchment(tmp_path, *, margin: float):
    """A run whose delineated catchment overhangs the grid by ``margin`` metres."""
    from shapely.geometry import box

    shp = tmp_path / "watershed.shp"
    side = N * CELL
    gpd.GeoDataFrame(
        geometry=[box(-margin, -margin, side + margin, side + margin)], crs=CRS
    ).to_file(shp)
    ctx = _run_ctx()
    ctx.state.setup.geographic.watershed_shp = str(shp)
    return ctx


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


def test_an_unclipped_map_without_a_catchment_only_informs(caplog) -> None:
    far = LineString([(5000.0, 5000.0), (5100.0, 5000.0)])
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)

    with caplog.at_level(logging.INFO, logger=observed_module.__name__):
        observed_network_mask(
            _run_ctx(), _unclipped(far), SimpleNamespace(vertices=vertices), connectivity
        )

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_the_count_and_the_length_describe_the_same_reaches(tmp_path, caplog) -> None:
    # One feature of two sliver parts, 10 m and 20 m, inside the catchment.
    from shapely.geometry import MultiLineString

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
