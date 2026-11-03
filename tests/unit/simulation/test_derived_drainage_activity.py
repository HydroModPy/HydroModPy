"""Drain, release and seepage fields of a store with no array of their own.

Each field is read from the per-cell budget the run kept: nothing is computed
and written after the run.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.field_routing import (
    accumulate_on_downhill_graph,
    active_surface_mask,
    budget_outflow,
    build_downhill_graph,
)

from ._test_simulation_api_builders import RunBuilder, runs

__all__ = ["runs"]


def _open_run(
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
        sim_id,
        "head",
        0,
        np.full((n_layers, n_cells), 10.0),
        n_timesteps=n_timesteps,
    )
    return sim_id


def test_drain_budget_to_positive_outflow_sums_negative_layer_fluxes() -> None:
    drn = np.array([[-2.0, 1.0, -0.5], [-3.0, -4.0, 2.0]], dtype="float64")

    outflow = budget_outflow(drn, n_cells=3)

    np.testing.assert_allclose(outflow, np.array([5.0, 4.0, 0.5]))


def test_active_surface_mask_keeps_negative_valid_elevations() -> None:
    surface = np.array([-25.0, 0.0, -99999.0, np.nan], dtype="float64")

    mask = active_surface_mask(surface)

    np.testing.assert_array_equal(mask, np.array([True, True, False, False]))


def test_accumulate_downhill_on_mesh_routes_to_lower_neighbor() -> None:
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
            [2.0, 1.0, 0.0],
        ],
        dtype="float64",
    )
    face_node_connectivity = np.array(
        [
            [0, 1, 4, 3],
            [1, 2, 5, 4],
        ],
        dtype="int32",
    )

    graph = build_downhill_graph(
        np.array([10.0, 5.0]),
        face_node_connectivity,
        vertices=vertices,
    )
    accumulated = accumulate_on_downhill_graph(graph, np.array([2.5, 0.0]))

    np.testing.assert_allclose(accumulated, np.array([2.5, 2.5]))


def test_the_outflow_drain_is_read_as_the_positive_outflow_of_the_cell(
    runs: RunBuilder,
) -> None:
    sim_id = _open_run(runs, n_cells=3, n_layers=2)
    runs.store(sim_id).write_field(
        sim_id,
        "drain",
        0,
        np.array([[-2.0, 1.0, -0.5], [-3.0, -4.0, 2.0]]),
        n_timesteps=1,
        subgroup="budget",
    )

    expected = np.array([5.0, 4.0, 0.5])
    np.testing.assert_allclose(runs.reader().query_field(sim_id, "outflow_drain", 0), expected)
    # No mesh topology and no stored descent: nothing to route on, so the field
    # is unavailable rather than served as the local flux.
    with pytest.raises(KeyError):
        runs.reader().query_field(sim_id, "drain_accumulation_flux", 0)


def test_the_seepage_mask_is_read_from_the_surface_excess(
    runs: RunBuilder,
) -> None:
    sim_id = _open_run(runs, n_cells=3)
    sz = runs.store(sim_id).open_zarr(sim_id)
    try:
        mesh = sz.root.require_group("mesh")
        mesh.create_array("topography", data=np.array([0.0, 0.0, 0.0]), overwrite=True)
    finally:
        sz.close()
    runs.store(sim_id).write_field(
        sim_id,
        "head",
        0,
        np.array([[5.0, 5.0, 5.0]]),
        n_timesteps=1,
    )
    runs.store(sim_id).write_field(
        sim_id,
        "surface_excess",
        0,
        np.array([0.0, -2.0, 1.0]),
        n_timesteps=1,
        subgroup="budget",
    )

    np.testing.assert_allclose(
        runs.reader().query_field(sim_id, "seepage_mask", 0),
        np.array([0.0, 1.0, 0.0]),
    )


def test_the_release_flux_is_read_from_the_drain_and_the_surface_excess(
    runs: RunBuilder,
) -> None:
    sim_id = _open_run(runs, n_cells=3, n_layers=1)
    runs.store(sim_id).write_field(
        sim_id,
        "drain",
        0,
        np.array([[0.5, -2.0, 1.0]], dtype="float64"),
        n_timesteps=1,
        subgroup="budget",
    )
    runs.store(sim_id).write_field(
        sim_id,
        "surface_excess",
        0,
        np.array([-1.0, 3.0, -4.0], dtype="float64"),
        n_timesteps=1,
        subgroup="budget",
    )

    np.testing.assert_allclose(
        runs.reader().query_field(sim_id, "release_flux", 0),
        np.array([1.0, 2.0, 4.0], dtype="float64"),
    )


def test_the_release_accumulation_is_routed_on_an_unstructured_mesh_on_read(
    runs: RunBuilder,
) -> None:
    sim_id = _open_run(runs, n_cells=2, mesh_topology="unstructured_2d")
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
            [2.0, 1.0, 0.0],
        ],
        dtype="float64",
    )
    face_node_connectivity = np.array(
        [
            [0, 1, 4, 3],
            [1, 2, 5, 4],
        ],
        dtype="int32",
    )
    runs.store(sim_id).write_mesh(
        sim_id,
        vertices,
        face_node_connectivity,
        np.array([10.0, 0.0], dtype="float64"),
    )
    sz = runs.store(sim_id).open_zarr(sim_id)
    try:
        mesh = sz.root["mesh"]
        mesh.create_array(
            "topography",
            data=np.array([10.0, 5.0], dtype="float64"),
            overwrite=True,
        )
    finally:
        sz.close()
    runs.store(sim_id).write_field(
        sim_id,
        "surface_excess",
        0,
        np.array([-2.5, 0.0], dtype="float64"),
        n_timesteps=1,
        subgroup="budget",
    )

    np.testing.assert_allclose(
        runs.reader().query_field(sim_id, "release_flux", 0),
        np.array([2.5, 0.0]),
    )
    np.testing.assert_allclose(
        runs.reader().query_field(sim_id, "release_accumulation_flux", 0),
        np.array([2.5, 2.5]),
    )


def test_the_accumulation_is_routed_on_an_unstructured_mesh_on_read(
    runs: RunBuilder,
) -> None:
    sim_id = _open_run(runs, n_cells=2, mesh_topology="unstructured_2d")
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
            [2.0, 1.0, 0.0],
        ],
        dtype="float64",
    )
    face_node_connectivity = np.array(
        [
            [0, 1, 4, 3],
            [1, 2, 5, 4],
        ],
        dtype="int32",
    )
    runs.store(sim_id).write_mesh(
        sim_id,
        vertices,
        face_node_connectivity,
        np.array([10.0, 0.0], dtype="float64"),
    )
    sz = runs.store(sim_id).open_zarr(sim_id)
    try:
        mesh = sz.root["mesh"]
        mesh.create_array(
            "topography",
            data=np.array([10.0, 5.0], dtype="float64"),
            overwrite=True,
        )
    finally:
        sz.close()
    runs.store(sim_id).write_field(
        sim_id,
        "drain",
        0,
        np.array([[-2.5, 0.0]], dtype="float64"),
        n_timesteps=1,
        subgroup="budget",
    )

    np.testing.assert_allclose(
        runs.reader().query_field(sim_id, "drain_accumulation_flux", 0),
        np.array([2.5, 2.5]),
    )
