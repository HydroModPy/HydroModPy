"""Route the per-cell release downstream, so a gauge is scored where it sits.

The contract this file exists for: at the outlet cell the routed value IS the
domain sum. A per-cell discharge that does not reproduce the series the whole
catchment already produces is wrong, whatever else it gets right.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.solver.modflow6.extractors.sfr import routed_outflow_series
from hydromodpy.solver.modflow_common import observable_extraction as extraction
from hydromodpy.solver.modflow_common.discharge_routing import (
    flat_cell_index,
    route_release_to_discharge,
    routing_graph_for_model,
    upstream_area_m2,
)
from hydromodpy.solver.modflow_common.flow_directions import build_solver_mesh_descent
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

_NROW, _NCOL = 3, 3


def _model(top: np.ndarray) -> SimpleNamespace:
    """A 3x3 structured model whose top D is built on, as the build does."""
    botm = np.full((_NROW, _NCOL), -10.0, dtype=float)
    mesh = solver_mesh_from_structured_arrays(
        nrow=_NROW,
        ncol=_NCOL,
        top=top,
        botm=np.stack([botm]),
    )
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    return SimpleNamespace(solver_mesh=mesh, descent=descent)


def _south_sloping_top() -> np.ndarray:
    """Every row drains to the row below, so cell (2, 1) collects the grid."""
    return np.array(
        [
            [30.0, 29.0, 30.0],
            [20.0, 19.0, 20.0],
            [10.0, 1.0, 10.0],
        ],
        dtype=float,
    )


def _outlet_index(model: SimpleNamespace, accumulated: np.ndarray) -> int:
    del model
    return int(np.argmax(accumulated))


def test_the_outlet_collects_every_release_of_the_catchment():
    """routed(outlet) == the catchment sum, when the graph has ONE sink.

    A catchment whose routing graph terminates in several cells splits the sum
    between them; the general statement is the mass conservation below, and this
    fixture is the single-sink special case.
    """
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    release = np.arange(1.0, _NROW * _NCOL + 1.0)
    mask = np.ones(_NROW * _NCOL, dtype=bool)

    accumulated = route_release_to_discharge(release, graph, catchment_mask=mask)

    assert accumulated[_outlet_index(model, accumulated)] == pytest.approx(release.sum())


def test_an_interior_cell_carries_only_what_is_upstream_of_it():
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    release = np.ones(_NROW * _NCOL)
    mask = np.ones(_NROW * _NCOL, dtype=bool)

    accumulated = route_release_to_discharge(release, graph, catchment_mask=mask)

    outlet = accumulated[_outlet_index(model, accumulated)]
    assert outlet == pytest.approx(release.sum())
    # No cell can carry more than the outlet, and at least one carries less.
    assert accumulated.max() == pytest.approx(outlet)
    assert accumulated.min() < outlet


def test_cells_outside_the_catchment_release_nothing_into_it():
    """The mesh is a buffered box; the neighboring basins must not be counted."""
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    release = np.ones(_NROW * _NCOL)
    mask = np.ones(_NROW * _NCOL, dtype=bool)
    mask[:_NCOL] = False  # drop the northern row from the catchment

    accumulated = route_release_to_discharge(release, graph, catchment_mask=mask)

    assert accumulated.max() == pytest.approx(float(mask.sum()))


def test_a_transient_stack_routes_every_timestep():
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    stack = np.stack([np.ones(_NROW * _NCOL), 2.0 * np.ones(_NROW * _NCOL)])
    mask = np.ones(_NROW * _NCOL, dtype=bool)

    accumulated = route_release_to_discharge(stack, graph, catchment_mask=mask)

    assert accumulated.shape == stack.shape
    assert accumulated.max(axis=1) == pytest.approx([9.0, 18.0])


def test_the_upstream_area_of_the_outlet_is_the_catchment_area():
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    mask = np.ones(_NROW * _NCOL, dtype=bool)

    areas = upstream_area_m2(model, graph, catchment_mask=mask)

    assert areas.max() == pytest.approx(float(model.solver_mesh.cell_areas().sum()))


def test_the_upstream_area_follows_the_same_graph_as_the_release():
    """Runoff a gauge sees must be the runoff over the cells whose release it sees."""
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    mask = np.ones(_NROW * _NCOL, dtype=bool)
    cell_areas = model.solver_mesh.cell_areas()

    areas = upstream_area_m2(model, graph, catchment_mask=mask)
    counts = route_release_to_discharge(np.ones(_NROW * _NCOL), graph, catchment_mask=mask)

    assert areas == pytest.approx(counts * float(cell_areas[0]))


def test_a_mask_that_holds_no_cell_is_refused():
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)

    with pytest.raises(ValueError, match="holds no cell"):
        route_release_to_discharge(
            np.ones(_NROW * _NCOL), graph, catchment_mask=np.zeros(_NROW * _NCOL, dtype=bool)
        )


def test_a_mask_of_the_wrong_size_is_refused():
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)

    with pytest.raises(ValueError, match="holds 4 cells and the release 9"):
        route_release_to_discharge(
            np.ones(_NROW * _NCOL), graph, catchment_mask=np.ones(4, dtype=bool)
        )


def test_a_structured_cell_maps_to_its_flat_index():
    model = _model(_south_sloping_top())

    assert flat_cell_index(model, (0, 2, 1)) == 2 * _NCOL + 1


def test_a_cell_outside_the_mesh_is_refused():
    model = _model(_south_sloping_top())

    with pytest.raises(ValueError, match="outside the 9 cells"):
        flat_cell_index(model, (0, 9, 9))


def test_a_model_without_a_descent_says_so():
    with pytest.raises(ValueError, match="carries none"):
        routing_graph_for_model(SimpleNamespace(solver_mesh=None))


def test_what_leaves_through_the_sinks_is_everything_released():
    """The general identity, whatever the number of terminal cells."""
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    release = np.arange(1.0, _NROW * _NCOL + 1.0)
    mask = np.ones(_NROW * _NCOL, dtype=bool)

    accumulated = route_release_to_discharge(release, graph, catchment_mask=mask)

    sinks = np.flatnonzero(np.asarray(graph.downstream) < 0)
    assert sinks.size
    assert float(accumulated[sinks].sum()) == pytest.approx(release.sum())


def test_no_cell_carries_more_than_the_catchment_released():
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    release = np.arange(1.0, _NROW * _NCOL + 1.0)
    mask = np.ones(_NROW * _NCOL, dtype=bool)

    accumulated = route_release_to_discharge(release, graph, catchment_mask=mask)

    assert float(accumulated.max()) <= release.sum() + 1e-12


# The per-cell discharge is routed on the descent D of the build, nothing else.
#
# The graph was once the steepest descent of the unfilled top, rebuilt per
# extraction with a per-output neighborhood. It is now D's receivers: a pit of
# the top no longer holds the water above it, a diagonal talweg is followed on a
# quad mesh, and a river CHD passes the water on, so the outlet keeps the
# domain sum.


def _model_1(top: np.ndarray, base_level: np.ndarray | None = None) -> SimpleNamespace:
    nrow, ncol = top.shape
    mesh = solver_mesh_from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=top,
        botm=np.full((1, nrow, ncol), -10.0),
    )
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=base_level)
    return SimpleNamespace(solver_mesh=mesh, descent=descent)


def _receiver_pairs(graph) -> set[tuple[int, int]]:
    return {
        tuple(sorted((cell, int(receiver))))
        for cell, receiver in enumerate(graph.downstream)
        if receiver >= 0
    }


def test_the_graph_is_the_receivers_of_d() -> None:
    model = _model_1(np.arange(25, dtype=float).reshape(5, 5))

    graph = routing_graph_for_model(model)

    assert graph is model.descent.metric.graph


def test_a_pit_of_the_top_does_not_hold_the_release_above_it() -> None:
    # A valley sloping to the south edge with a closed pit in its middle.
    rows, cols = np.mgrid[0:7, 0:7]
    top = 10.0 + 2.0 * (6 - rows) + np.abs(cols - 3)
    top[3, 3] = 0.0
    model = _model_1(top.astype(float))
    graph = routing_graph_for_model(model)
    release = np.ones(49)

    accumulated = route_release_to_discharge(release, graph, catchment_mask=np.ones(49, bool))

    pit = 3 * 7 + 3
    assert graph.downstream[pit] >= 0
    sinks = np.flatnonzero(np.asarray(graph.downstream) < 0)
    assert float(accumulated[sinks].sum()) == pytest.approx(release.sum())
    assert float(accumulated.max()) > float(accumulated[pit])


def test_a_diagonal_talweg_is_followed_on_a_quad_mesh() -> None:
    n = 30
    rows, cols = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    top = 100.0 + 0.5 * np.abs(rows - cols) + 0.01 * (rows + cols)
    model = _model_1(top)

    graph = routing_graph_for_model(model)

    diagonal = {
        tuple(sorted((r * n + c, (r + 1) * n + (c + 1))))
        for r in range(n - 1)
        for c in range(n - 1)
    }
    assert _receiver_pairs(graph) & diagonal
    assert model.descent.diagonal_neighbors


def test_a_stream_chd_inside_the_catchment_passes_the_water_to_the_outlet() -> None:
    # A valley sloping south, its river column held by a stream-role CHD that
    # carries all the release, as the release union counts it.
    n = 11
    rows, cols = np.mgrid[0:n, 0:n]
    top = 50.0 + 2.0 * np.abs(cols - 5) + 1.0 * (n - 1 - rows)
    river = (cols == 5).reshape(-1)
    model = _model_1(top.astype(float), base_level=river)
    graph = routing_graph_for_model(model)
    release = np.where(river, 1.0, 0.0)

    accumulated = route_release_to_discharge(release, graph, catchment_mask=np.ones(n * n, bool))

    outlet = int(np.argmax(accumulated))
    assert model.descent.constant_head[river].all()
    assert float(accumulated[outlet]) == pytest.approx(float(release.sum()))
    assert np.all(graph.downstream[river & (np.arange(n * n) != outlet)] >= 0)


# The routed discharge takes the drain budget only when the network does not route the drainage.
#
# With ``route_drainage`` the hillslope drainage reaches the network, so the routed
# series is the catchment discharge and already holds the runoff. Without it the
# drainage stays in DRAIN, the routed series would leave it out, and the discharge
# is the routed series plus the drain budget of the catchment.

_INDEX = pd.date_range("2000-01-01", periods=3, freq="D")


_ROUTED = pd.Series([1.0, 1.0, 1.0], index=_INDEX)


_DRAIN = pd.Series([0.25, 0.25, 0.25], index=_INDEX)


def _model_2(*, route_drainage: bool | None) -> SimpleNamespace:
    payload = {} if route_drainage is None else {"route_drainage": route_drainage}
    flow = SimpleNamespace(active_bc=["sfr"], sinks_sources={"sfr": {"net": payload}})
    return SimpleNamespace(flow=flow)


def _serve(model: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> tuple[object, list[str]]:
    calls: list[str] = []

    def routed_reader(output_dir, model_name, time_index):
        calls.append("routed")
        return _ROUTED

    def drain_sum(output_dir, model_name, time_index, *, catchment_mask):
        calls.append("drain")
        return _DRAIN

    monkeypatch.setattr(extraction, "extract_discharge_from_cbc", drain_sum)
    monkeypatch.setattr(extraction, "catchment_cell_mask", lambda model: np.ones(4, dtype=bool))
    request = ObservableRequest(id="catchment", name="discharge", support="domain")
    served, unserved = extraction.extract_common_modflow_observables(
        Path("."),
        "m",
        model,
        [request],
        time_index=_INDEX,
        routed_discharge_reader=routed_reader,
    )
    assert unserved == []
    return served["catchment"], calls


def test_a_network_that_routes_the_drainage_serves_the_routed_series(monkeypatch) -> None:
    result, calls = _serve(_model_2(route_drainage=True), monkeypatch)

    assert calls == ["routed"]
    assert result.includes_runoff is True
    np.testing.assert_allclose(result.values, _ROUTED.to_numpy())


def test_a_network_that_does_not_say_routes_the_drainage(monkeypatch) -> None:
    result, calls = _serve(_model_2(route_drainage=None), monkeypatch)

    assert calls == ["routed"]
    assert result.includes_runoff is True


def test_a_network_that_keeps_the_drainage_out_adds_the_drain_budget(monkeypatch) -> None:
    result, calls = _serve(_model_2(route_drainage=False), monkeypatch)

    assert calls == ["routed", "drain"]
    assert result.includes_runoff is True
    np.testing.assert_allclose(result.values, (_ROUTED + _DRAIN).to_numpy())


@pytest.mark.parametrize(
    "flow",
    [
        SimpleNamespace(active_bc=["lake"], sinks_sources={"lake": {}}),
        SimpleNamespace(active_bc=["lake"], sinks_sources={"sfr": {"net": {}}}),
    ],
    ids=["no_network", "a_network_not_active"],
)
def test_a_lake_without_a_network_adds_the_drain_budget(monkeypatch, flow) -> None:
    result, calls = _serve(SimpleNamespace(flow=flow), monkeypatch)

    assert calls == ["routed", "drain"]
    assert result.includes_runoff is True
    np.testing.assert_allclose(result.values, (_ROUTED + _DRAIN).to_numpy())


def test_a_drain_budget_that_cannot_be_read_leaves_the_routed_series(monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise NotImplementedError("a mover record is in the budget")

    monkeypatch.setattr(extraction, "extract_discharge_from_cbc", refuse)
    monkeypatch.setattr(extraction, "catchment_cell_mask", lambda model: np.ones(4, dtype=bool))
    request = ObservableRequest(id="catchment", name="discharge", support="domain")
    served, _ = extraction.extract_common_modflow_observables(
        Path("."),
        "m",
        _model_2(route_drainage=False),
        [request],
        time_index=_INDEX,
        routed_discharge_reader=lambda *args: _ROUTED,
    )

    np.testing.assert_allclose(served["catchment"].values, _ROUTED.to_numpy())


# The routed outflow is one definition: reach ext-outflow plus lake ext-outflow.
#
# A network whose reaches end in a lake has no ext-outflow of its own: the water
# leaves through the lake outlet. A series of zeros must never pass for a flow.

TIMES = [86400.0, 172800.0, 259200.0]


def _write_run(root: Path, *, reach_out: list[float], lake_out: list[float] | None) -> None:
    """Write the SFR (and optional LAK) sidecars and obs CSVs of a tiny run."""
    sfr_meta = {
        "obs_csv": "m.sfr.obs.csv",
        "network_id": "n",
        "reach_count": 1,
        "entries": [
            {"obsname": "R1_EXT", "network_id": "n", "reach": 1, "quantity": "ext_outflow"}
        ],
        "reaches": [],
    }
    (root / "m.sfr.meta.json").write_text(json.dumps(sfr_meta), encoding="utf-8")
    lines = ["time,R1_EXT"] + [f"{t},{-v}" for t, v in zip(TIMES, reach_out, strict=True)]
    (root / "m.sfr.obs.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if lake_out is None:
        return
    lak_meta = {
        "obs_csv": "m.lak.obs.csv",
        "entries": [{"obsname": "L1_EXT_1", "lake_id": "l1", "quantity": "ext_outflow"}],
    }
    (root / "m.lak.meta.json").write_text(json.dumps(lak_meta), encoding="utf-8")
    lines = ["time,L1_EXT_1"] + [f"{t},{-v}" for t, v in zip(TIMES, lake_out, strict=True)]
    (root / "m.lak.obs.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_reaches_ending_in_a_lake_count_the_lake_outlet(tmp_path: Path) -> None:
    _write_run(tmp_path, reach_out=[0.0, 0.0, 0.0], lake_out=[0.042, 0.045, 0.047])
    series = routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0)
    assert series is not None
    np.testing.assert_allclose(series, [0.042, 0.045, 0.047])


def test_reach_and_lake_outflows_add_up(tmp_path: Path) -> None:
    _write_run(tmp_path, reach_out=[0.5, 0.5, 0.5], lake_out=[0.1, 0.2, 0.3])
    series = routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0)
    np.testing.assert_allclose(series, [0.6, 0.7, 0.8])


def _lake_alone(root: Path, lake_out: list[float]) -> None:
    """Write the sidecars of a lake with an outlet and no network."""
    _write_run(root, reach_out=[0.0, 0.0, 0.0], lake_out=lake_out)
    (root / "m.sfr.meta.json").unlink()
    (root / "m.sfr.obs.csv").unlink()


def test_a_lake_without_a_network_serves_its_outlet(tmp_path: Path) -> None:
    _lake_alone(tmp_path, [0.1, 0.2, 0.3])
    series = routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0)
    np.testing.assert_allclose(series, [0.1, 0.2, 0.3])


def test_a_lake_whose_outlet_stays_dry_is_a_routed_zero_the_drains_add_to(tmp_path: Path) -> None:
    _lake_alone(tmp_path, [0.0, 0.0, 0.0])
    series = routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0)
    np.testing.assert_allclose(series, [0.0, 0.0, 0.0])


def test_a_run_without_network_nor_lake_has_no_routed_series(tmp_path: Path) -> None:
    assert routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0) is None


def test_a_series_of_zeros_is_refused(tmp_path: Path) -> None:
    _write_run(tmp_path, reach_out=[0.0, 0.0, 0.0], lake_out=None)
    with pytest.raises(ObservableNotAvailableError, match="zero"):
        routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0)
