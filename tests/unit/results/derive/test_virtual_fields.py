"""Drain, release and seepage fields (m3/s per cell) of a store with no array of their own.

Each field is read from the per-cell budget the run kept. Nothing is computed
and written after the run.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.catchment.drainage.graph import accumulate_on_downhill_graph, build_downhill_graph
from hydromodpy.core.budget.flux import budget_outflow
from tests._helpers.run_builders import RunBuilder, runs

__all__ = ["runs"]

# Two square cells side by side, the left one higher.
VERTICES = np.array(
    [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [1.0, 1.0, 0.0],
        [2.0, 1.0, 0.0],
    ]
)
TWO_CELLS = np.array([[0, 1, 4, 3], [1, 2, 5, 4]], dtype="int32")
TOPOGRAPHY = np.array([10.0, 5.0])


def open_run(
    runs: RunBuilder,
    *,
    n_cells: int,
    n_layers: int = 1,
    n_timesteps: int = 1,
    mesh_topology: str | None = None,
) -> str:
    sim_id = runs.open(
        n_cells=n_cells, n_layers=n_layers, n_timesteps=n_timesteps, mesh_topology=mesh_topology
    ).sim_id
    runs.store(sim_id).write_field(
        sim_id, "head", 0, np.full((n_layers, n_cells), 10.0), n_timesteps=n_timesteps
    )
    return sim_id


def write_budget(runs: RunBuilder, sim_id: str, name: str, values) -> None:
    runs.store(sim_id).write_field(
        sim_id, name, 0, np.asarray(values, dtype="float64"), n_timesteps=1, subgroup="budget"
    )


def write_topography(runs: RunBuilder, sim_id: str, values) -> None:
    sz = runs.store(sim_id).open_zarr(sim_id)
    try:
        mesh = sz.root.require_group("mesh")
        mesh.create_array("topography", data=np.asarray(values, dtype="float64"), overwrite=True)
    finally:
        sz.close()


def two_cell_run(runs: RunBuilder) -> str:
    sim_id = open_run(runs, n_cells=2, mesh_topology="unstructured_2d")
    runs.store(sim_id).write_mesh(sim_id, VERTICES, TWO_CELLS, np.array([10.0, 0.0]))
    write_topography(runs, sim_id, TOPOGRAPHY)
    return sim_id


def test_outflow_sums_the_negative_layer_fluxes() -> None:
    drn = np.array([[-2.0, 1.0, -0.5], [-3.0, -4.0, 2.0]], dtype="float64")

    outflow = budget_outflow(drn, n_cells=3)

    np.testing.assert_allclose(outflow, np.array([5.0, 4.0, 0.5]))


def test_accumulation_routes_to_the_lower_neighbor() -> None:
    graph = build_downhill_graph(TOPOGRAPHY, TWO_CELLS, vertices=VERTICES)

    accumulated = accumulate_on_downhill_graph(graph, np.array([2.5, 0.0]))

    np.testing.assert_allclose(accumulated, np.array([2.5, 2.5]))


def test_outflow_drain_is_the_positive_outflow(runs: RunBuilder) -> None:
    sim_id = open_run(runs, n_cells=3, n_layers=2)
    write_budget(runs, sim_id, "drain", [[-2.0, 1.0, -0.5], [-3.0, -4.0, 2.0]])

    expected = np.array([5.0, 4.0, 0.5])
    np.testing.assert_allclose(runs.reader().query_field(sim_id, "outflow_drain", 0), expected)
    # No mesh topology and no stored descent: nothing to route on, so the field
    # is unavailable rather than served as the local flux.
    with pytest.raises(KeyError):
        runs.reader().query_field(sim_id, "drain_accumulation_flux", 0)


def test_seepage_mask_comes_from_the_surface_excess(runs: RunBuilder) -> None:
    sim_id = open_run(runs, n_cells=3)
    write_topography(runs, sim_id, [0.0, 0.0, 0.0])
    runs.store(sim_id).write_field(sim_id, "head", 0, np.array([[5.0, 5.0, 5.0]]), n_timesteps=1)
    write_budget(runs, sim_id, "surface_excess", [0.0, -2.0, 1.0])

    np.testing.assert_allclose(
        runs.reader().query_field(sim_id, "seepage_mask", 0), np.array([0.0, 1.0, 0.0])
    )


def test_release_flux_adds_drain_and_surface_excess(runs: RunBuilder) -> None:
    sim_id = open_run(runs, n_cells=3)
    write_budget(runs, sim_id, "drain", [[0.5, -2.0, 1.0]])
    write_budget(runs, sim_id, "surface_excess", [-1.0, 3.0, -4.0])

    np.testing.assert_allclose(
        runs.reader().query_field(sim_id, "release_flux", 0), np.array([1.0, 2.0, 4.0])
    )


ROUTED_ON_READ = [
    pytest.param("surface_excess", [-2.5, 0.0], "release_flux", [2.5, 0.0], id="release flux"),
    pytest.param(
        "surface_excess", [-2.5, 0.0], "release_accumulation_flux", [2.5, 2.5], id="release routed"
    ),
    pytest.param("drain", [[-2.5, 0.0]], "drain_accumulation_flux", [2.5, 2.5], id="drain routed"),
]


@pytest.mark.parametrize(("written", "values", "queried", "expected"), ROUTED_ON_READ)
def test_accumulation_is_routed_on_read(runs: RunBuilder, written, values, queried, expected):
    sim_id = two_cell_run(runs)
    write_budget(runs, sim_id, written, values)

    np.testing.assert_allclose(runs.reader().query_field(sim_id, queried, 0), expected)


def test_field_of_a_store_without_head_is_read_by_step(runs: RunBuilder) -> None:
    # No head and no concentration: the time axis is unknown, so the step is read as given.
    sim_id = runs.open(n_cells=3, n_layers=2, n_timesteps=1).sim_id
    write_budget(runs, sim_id, "drain", [[-2.0, 1.0, -0.5], [-3.0, -4.0, 2.0]])

    np.testing.assert_allclose(
        runs.reader().query_field(sim_id, "outflow_drain", 0), [5.0, 4.0, 0.5]
    )
