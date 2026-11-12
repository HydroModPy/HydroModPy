"""Constant-head (CHD) cells of the side and stream boundaries of a MODFLOW 6 grid.

Heads are in m. A side boundary picks the cells along one edge of the grid, a
stream boundary the cells of the river chain, and a support label picks either by
name. A head below the cell bottom is refused.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.boundaries.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.model.initial.state import HeadRule
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    DRAIN_AREA_SPREAD_REPORT_RATIO,
    _sink_mask_flat,
    apply_side_boundary_start_heads,
    boundary_attr,
    boundary_period_series,
    build_ocean_boundary_chd_spd,
    build_side_boundary_chd_spd,
    build_stream_boundary_chd_spd,
    iter_side_boundary_cells,
    ocean_chd_support_mask,
    refuse_constant_heads_below_bottom,
    report_per_cell_conductance_spread,
    resolve_drainage_conductance_series,
    resolve_ocean_boundary_series,
    resolve_stream_boundary_series,
    side_boundary_owner_by_cell,
)
from hydromodpy.solver.modflow6.builders.initial_conditions import build_start_heads
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.mf6_toy_models import (
    regular_solver_mesh,
    toy_model,
    two_triangle_model,
)


def bound(model, conditions: dict, active: tuple[str, ...] | None = None, **inputs):
    """Give the model these boundary conditions, all active unless told otherwise."""
    bundle = BoundaryConditionBundle(
        conditions=conditions, active_ids=tuple(conditions) if active is None else active
    )
    model.inputs = replace(model.inputs, boundaries=bundle, **inputs)
    return model


def head(value, **kwargs) -> SimpleNamespace:
    return SimpleNamespace(value=value, **kwargs)


def side_model_with_heads(west: float, east: float):
    # On the 2 x 3 toy grid the west cells are 0 and 3, the east cells 2 and 5.
    return bound(toy_model(), {"west_side": head(west), "east_side": head(east)})


def refuse(model, *, side=None, stream=None, idomain=None, **kwargs) -> None:
    refuse_constant_heads_below_bottom(
        model,
        botm=np.zeros((1, 6)),
        idomain=np.ones((1, 6), dtype=int) if idomain is None else idomain,
        ocean_spd={},
        stream_spd=stream or {},
        side_spd=side or {},
        **kwargs,
    )


def test_side_chd_from_scalar_and_transient_heads() -> None:
    model = bound(toy_model(), {"west_side": head(10.0), "east_side": head([20.0, 21.0])})

    chd_spd = build_side_boundary_chd_spd(model)

    # DISV record is [layer, cell, head]. The last cell of east_side is 2 + 3 = 5.
    assert chd_spd[0][0] == [0, 0, pytest.approx(10.0)]
    assert chd_spd[0][-1] == [0, 5, pytest.approx(20.0)]
    assert chd_spd[1][-1] == [0, 5, pytest.approx(21.0)]


def test_boundary_forcing_needs_no_runtime_binding() -> None:
    east = FlowBoundaryConditionConfig(
        id="east_side",
        kind="dirichlet",
        units="cm",
        application_domain="east side",
        forcing={"kind": "constant", "value": 20.0},
    )

    chd_spd = build_side_boundary_chd_spd(bound(toy_model(), {"east_side": east}))

    assert chd_spd[0][-1] == [0, 5, pytest.approx(0.2)]
    assert chd_spd[1][-1] == [0, 5, pytest.approx(0.2)]


def test_side_chd_on_two_triangles() -> None:
    model = bound(two_triangle_model(), {"west_side": head(10.0), "east_side": head([20.0, 21.0])})

    chd_spd = build_side_boundary_chd_spd(model)

    period0 = sorted(chd_spd[0], key=lambda item: item[1])
    period1 = sorted(chd_spd[1], key=lambda item: item[1])
    assert period0 == [[0, 0, pytest.approx(20.0)], [0, 1, pytest.approx(10.0)]]
    assert period1 == [[0, 0, pytest.approx(21.0)], [0, 1, pytest.approx(10.0)]]


def test_side_start_heads_on_two_triangles() -> None:
    model = bound(two_triangle_model(), {"west_side": head([7.0, 8.0])})

    updated = apply_side_boundary_start_heads(model, np.zeros((1, 2)))

    assert updated[0, 0] == pytest.approx(0.0)
    assert updated[0, 1] == pytest.approx(7.0)


def test_stream_chd_on_two_triangles() -> None:
    model = bound(two_triangle_model(river_internal_edge=True), {"stream": head(7.0)})

    chd_spd, stream_mask = build_stream_boundary_chd_spd(model)

    assert stream_mask.tolist() == [True, True]
    assert chd_spd[0] == [[0, 0, pytest.approx(7.0)], [0, 1, pytest.approx(7.0)]]
    assert chd_spd[1] == [[0, 0, pytest.approx(7.0)], [0, 1, pytest.approx(7.0)]]


def test_stream_start_heads_on_two_triangles() -> None:
    model = bound(
        two_triangle_model(river_internal_edge=True),
        {"stream": head(7.0)},
        initial=HeadRule("custom", 2.0),
    )

    strt = build_start_heads(model, model.solver_mesh)

    assert np.allclose(strt[0], [7.0, 7.0])


def test_support_label_picks_the_side_cells() -> None:
    east = FlowBoundaryConditionConfig(
        id="east_side",
        value=6.0,
        units="m",
        kind="dirichlet",
        application_domain="east side",
        support_label="east_custom",
    )
    model = bound(
        two_triangle_model(boundary_labels_by_edge_id={1: "east_custom"}),
        {"west_side": head(10.0), "east_side": east},
        active=("east_side",),
    )

    chd_spd = build_side_boundary_chd_spd(model)

    assert chd_spd[0] == [[0, 0, pytest.approx(6.0)]]
    assert chd_spd[1] == [[0, 0, pytest.approx(6.0)]]


def test_support_label_picks_the_stream_cells() -> None:
    stream = FlowBoundaryConditionConfig(
        id="stream",
        value=5.0,
        units="m",
        kind="dirichlet",
        application_domain="top",
        support_label="ditch_custom",
    )
    model = bound(
        two_triangle_model(boundary_labels_by_edge_id={0: "ditch_custom"}), {"stream": stream}
    )

    chd_spd, stream_mask = build_stream_boundary_chd_spd(model)

    assert stream_mask.tolist() == [True, False]
    assert chd_spd[0] == [[0, 0, pytest.approx(5.0)]]
    assert chd_spd[1] == [[0, 0, pytest.approx(5.0)]]


@pytest.mark.parametrize("support_label", ["east_custom", "boundary:east_custom"])
def test_a_group_is_read_by_its_family_name_or_its_bare_name(support_label) -> None:
    model = bound(
        two_triangle_model(boundary_labels_by_edge_id={1: "east_custom"}),
        {"east_side": head(6.0, units="m", support_label=support_label)},
    )

    assert build_side_boundary_chd_spd(model)[0] == [[0, 0, pytest.approx(6.0)]]


def test_a_label_wins_over_the_side_on_a_regular_grid() -> None:
    model = bound(
        toy_model(),
        {"west_side": head(3.0, units="m", support_label="boundary:south")},
    )

    # The south row of the 2 x 3 grid, not the west column.
    assert [row[1] for row in build_side_boundary_chd_spd(model)[0]] == [3, 4, 5]


def test_stream_chd_on_the_river_chain_of_a_regular_grid() -> None:
    model = bound(toy_model(), {"stream": head(7.0)})
    model.solver_mesh = regular_solver_mesh(2, 3, river=LineString([(0.5, 1.5), (1.5, 0.5)]))

    chd_spd, stream_mask = build_stream_boundary_chd_spd(model)

    chain_cells = np.concatenate(
        [chain.cell_ids for chain in model.solver_mesh.cell_mesh.chains("rivers")]
    )
    assert np.flatnonzero(stream_mask).tolist() == sorted(set(chain_cells.tolist()))
    assert stream_mask.sum() >= 2
    assert [row[1] for row in chd_spd[0]] == np.flatnonzero(stream_mask).tolist()


def test_a_head_below_the_bottom_names_boundary_and_cell() -> None:
    model = side_model_with_heads(west=-5.0, east=5.0)

    with pytest.raises(SolverInputError) as excinfo:
        refuse(model, side=build_side_boundary_chd_spd(model), structured_shape=(2, 3))

    message = str(excinfo.value)
    assert "flow.bc.west_side: 2 cell(s)" in message
    assert "layer 0 row 0 column 0 (head -5.00 m, bottom 0.00 m, period 1)" in message
    assert "layer 0 row 1 column 0" in message
    assert "east_side" not in message


def test_a_head_on_an_inactive_cell_passes() -> None:
    model = side_model_with_heads(west=-5.0, east=5.0)
    idomain = np.ones((1, 6), dtype=int)
    idomain[0, [0, 3]] = 0  # the two west cells

    refuse(model, side=build_side_boundary_chd_spd(model), idomain=idomain)


def test_a_stream_head_overwritten_by_a_side_head_is_not_checked() -> None:
    model = side_model_with_heads(west=5.0, east=5.0)
    side = build_side_boundary_chd_spd(model)
    # The stream claims west cell 0 with a head below the bottom and the side
    # writes over it, so MODFLOW 6 receives the side head only.
    refuse(model, side=side, stream={0: [[0, 0, -1.0]], 1: [[0, 0, -1.0]]})

    with pytest.raises(SolverInputError, match=r"flow\.bc\.stream: 1 cell\(s\): layer 0 cell 1"):
        refuse(model, side=side, stream={0: [[0, 1, -1.0]], 1: [[0, 1, -1.0]]})


def test_a_constant_head_is_written_only_on_the_active_cells_of_its_column() -> None:
    model = side_model_with_heads(west=8.0, east=8.0)
    base = model.solver_mesh
    idomain = np.ones((2, 6), dtype=int)
    idomain[0, 0] = 0  # the top cell of the first west column is inactive
    idomain[1, 3] = -1  # the lower cell of the second west column is a pass-through
    model.solver_mesh = SolverMesh(
        cell_mesh=base.cell_mesh,
        top=base.top,
        botm=np.vstack([base.top - 4.0, base.top - 9.0]),
        idomain=idomain,
    )
    model.nlay = 2

    rows = build_side_boundary_chd_spd(model)[0]

    west = sorted((row[0], row[1]) for row in rows if row[1] in (0, 3))
    assert west == [(0, 3), (1, 0)]


def test_boundary_attr_reads_a_mapping_or_an_object() -> None:
    assert boundary_attr({"units": "cm"}, "units", "m") == "cm"
    assert boundary_attr({}, "units", "m") == "m"
    assert boundary_attr(head(1.0, units="cm"), "units", "m") == "cm"
    assert boundary_attr(head(1.0), "units", "m") == "m"


PERIOD_SERIES = [
    pytest.param(5.0, 2, [5.0, 5.0], id="scalar repeated"),
    pytest.param([3.0], 2, [3.0, 3.0], id="one value repeated"),
    pytest.param([3.0, 4.0], 2, [3.0, 4.0], id="one value per period"),
    pytest.param([3.0, 4.0, 5.0], 1, [3.0], id="steady model keeps the first"),
]


@pytest.mark.parametrize(("value", "nper", "expected"), PERIOD_SERIES)
def test_period_series(value, nper, expected) -> None:
    model = SimpleNamespace(nper=nper)

    series = boundary_period_series(model, value=value, label="x")

    np.testing.assert_allclose(series, expected)


PERIOD_SERIES_REFUSALS = [
    pytest.param("high", 2, TypeError, "must be numeric", id="text"),
    pytest.param([], 2, ValueError, "cannot be empty", id="empty"),
    pytest.param(
        [1.0, 2.0, 3.0],
        2,
        ValueError,
        r"length \(3\) must be 1 or match nper \(2\)",
        id="wrong length",
    ),
]


@pytest.mark.parametrize(("value", "nper", "error", "match"), PERIOD_SERIES_REFUSALS)
def test_period_series_refusals(value, nper, error, match) -> None:
    with pytest.raises(error, match=match):
        boundary_period_series(SimpleNamespace(nper=nper), value=value, label="x")


def test_iter_side_boundary_cells_lists_each_layer() -> None:
    model = toy_model()
    model.nlay = 2

    # West cells of the 2 x 3 grid are 0 and 3, on each of the two layers.
    assert list(iter_side_boundary_cells(model, "west_side")) == [(0, 0), (0, 3), (1, 0), (1, 3)]


def test_inactive_or_missing_side_boundaries_are_skipped() -> None:
    model = bound(
        toy_model(),
        {"west_side": head(10.0), "east_side": head(20.0)},
        active=("east_side", "north_side"),
    )

    strt = apply_side_boundary_start_heads(model, np.zeros((1, 6)))
    chd_spd = build_side_boundary_chd_spd(model)
    owners = side_boundary_owner_by_cell(model)

    # Only east_side is both active and defined, so only cells 2 and 5 are set.
    np.testing.assert_allclose(strt[0], [0, 0, 20, 0, 0, 20])
    assert [row[1] for row in chd_spd[0]] == [2, 5]
    assert owners == {2: "east_side", 5: "east_side"}


def test_ocean_head_from_a_value_or_a_forcing() -> None:
    by_value = bound(toy_model(), {"ocean": head([1.0, 2.0], units="cm")})
    by_forcing = bound(
        toy_model(),
        {"ocean": head(None, forcing={"kind": "constant", "value": 50.0, "units": "cm"})},
    )

    np.testing.assert_allclose(resolve_ocean_boundary_series(by_value), [0.01, 0.02])  # cm to m
    np.testing.assert_allclose(resolve_ocean_boundary_series(by_forcing), [0.5, 0.5])


def test_stream_head_from_a_forcing() -> None:
    model = bound(toy_model(), {"stream": head(None, forcing={"kind": "constant", "value": 2.0})})

    np.testing.assert_allclose(resolve_stream_boundary_series(model), [2.0, 2.0])


def test_no_ocean_or_stream_head_without_a_boundary() -> None:
    inactive = bound(toy_model(), {"ocean": head(1.0), "stream": head(1.0)}, active=())
    undefined = bound(toy_model(), {}, active=("ocean", "stream"))

    assert resolve_ocean_boundary_series(inactive) is None
    assert resolve_ocean_boundary_series(undefined) is None
    assert resolve_stream_boundary_series(undefined) is None


def sea_level_model(sea_m: float):
    model = bound(toy_model(), {"ocean": head([sea_m, sea_m + 1.0])})
    model.dem = np.array([[0.5, 5.0, 5.0], [2.0, 5.0, 5.0]])
    return model


def test_ocean_cells_lie_at_or_below_the_highest_sea_level() -> None:
    model = sea_level_model(1.0)
    model.dem_mask = np.array([False, False, False, True, False, False])

    series = resolve_ocean_boundary_series(model)
    mask = ocean_chd_support_mask(model, series)
    spd, spd_mask = build_ocean_boundary_chd_spd(model)

    # Highest sea level 2 m: cells 0 (0.5 m) and 3 (2.0 m) qualify, but cell 3 is masked.
    assert np.flatnonzero(mask).tolist() == [0]
    assert np.flatnonzero(spd_mask).tolist() == [0]
    assert spd == {0: [[0, 0, 1.0]], 1: [[0, 0, 2.0]]}


def test_no_ocean_cell_below_the_sea() -> None:
    model = sea_level_model(-3.0)

    spd, mask = build_ocean_boundary_chd_spd(model)

    assert not mask.any()
    assert spd == {0: [], 1: []}
    assert not ocean_chd_support_mask(model, None).any()
    assert not ocean_chd_support_mask(model, np.array([])).any()


def test_drainage_conductance_from_a_value_or_a_forcing() -> None:
    by_value = bound(toy_model(), {"drainage": head([1e-4, 2e-4], units="m2/s")})
    by_forcing = bound(
        toy_model(),
        {"drainage": head(None, forcing={"kind": "constant", "value": 1e-4, "units": "m2/s"})},
    )
    absent = bound(toy_model(), {}, active=("drainage",))

    np.testing.assert_allclose(resolve_drainage_conductance_series(by_value), [1e-4, 2e-4])
    np.testing.assert_allclose(resolve_drainage_conductance_series(by_forcing), [1e-4, 1e-4])
    assert resolve_drainage_conductance_series(absent) is None


def spread_model(**members) -> SimpleNamespace:
    return SimpleNamespace(**members)


SPREAD_SILENT = [
    pytest.param({"auxiliary": True}, [1e-4], [1.0, 9.0], id="auxiliary model"),
    pytest.param({"_drain_area_spread_reported": True}, [1e-4], [1.0, 9.0], id="already said"),
    pytest.param({}, [0.0], [1.0, 9.0], id="no positive conductance"),
    pytest.param({}, [1e-4], [1.0, float("nan")], id="one finite area"),
    pytest.param({}, [1e-4], [1.0, 2.0], id="areas within twofold"),
]


@pytest.mark.parametrize(("members", "series", "areas"), SPREAD_SILENT)
def test_equal_enough_areas_stay_silent(members, series, areas, caplog) -> None:
    model = spread_model(**members)

    report_per_cell_conductance_spread(
        model,
        drainage_cond_series=np.array(series),
        cell_areas=np.array(areas),
        drained=np.ones(len(areas), dtype=bool),
    )

    assert "varies" not in caplog.text
    assert DRAIN_AREA_SPREAD_REPORT_RATIO == 2.0


def test_unequal_areas_are_reported_once(caplog) -> None:
    model = spread_model()
    kwargs = dict(
        drainage_cond_series=np.array([1e-4]),
        cell_areas=np.array([100.0, 900.0, 5000.0]),
        drained=np.array([True, True, False]),
    )

    report_per_cell_conductance_spread(model, **kwargs)
    report_per_cell_conductance_spread(model, **kwargs)

    # The undrained 5000 m2 cell is left out, so the spread is 900 / 100 = 9.
    assert caplog.text.count("varies 9.0-fold") == 1
    assert model._drain_area_spread_reported is True


def test_sink_mask_must_match_the_mesh() -> None:
    mask = _sink_mask_flat(SimpleNamespace(sink=np.array([[True, False, False]])), n_cells=3)

    assert mask.tolist() == [True, False, False]
    with pytest.raises(ValueError, match="holds 3 cells, the mesh 6"):
        _sink_mask_flat(SimpleNamespace(sink=np.zeros(3)), n_cells=6)


def mesh_free_model() -> SimpleNamespace:
    model = bound(toy_model(), {"west_side": head(1.0)})
    model.solver_mesh = None
    return model


REFUSALS = [
    pytest.param(
        bound(two_triangle_model(), {"east_side": head(6.0, units="m", support_label="nowhere")}),
        build_side_boundary_chd_spd,
        "support_label='nowhere' did not match",
        id="label matches no cell",
    ),
    pytest.param(
        bound(toy_model(), {"stream": head(7.0)}),
        build_stream_boundary_chd_spd,
        "selected runtime mesh support is empty",
        id="no river cells",
    ),
    pytest.param(
        mesh_free_model(),
        build_side_boundary_chd_spd,
        "reads the cells of the solver mesh",
        id="no solver mesh",
    ),
]


@pytest.mark.parametrize(("model", "build", "match"), REFUSALS)
def test_refusals(model, build, match) -> None:
    with pytest.raises(ValueError, match=match):
        build(model)
