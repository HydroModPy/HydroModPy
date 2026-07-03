from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest

from hydromodpy.core.field_routing import (
    accumulate_on_downhill_graph,
    active_surface_mask,
    build_downhill_graph,
    drain_budget_to_positive_outflow,
)
from hydromodpy.results.catalog import Catalog
from hydromodpy.simulation.extraction.derivation.derived import (
    DERIVED_VARIABLES,
    compute_derived,
)
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


def _disabled_derived_flags(**enabled: bool) -> dict[str, bool]:
    flags = {key: False for key in DERIVED_VARIABLES}
    flags.update(enabled)
    return flags


def _register_catalog_run(
    catalog: Catalog,
    *,
    n_cells: int,
    n_layers: int = 1,
    n_timesteps: int = 1,
    mesh_topology: str | None = None,
) -> str:
    sim_id = str(uuid4())
    registration = catalog.register_simulation(
        sim_id,
        project="test",
        solver="modflow6",
        name=f"drainage_{sim_id[:8]}",
        n_cells=n_cells,
        n_layers=n_layers,
        n_timesteps=n_timesteps,
        mesh_topology=mesh_topology,
    )
    if registration.zarr is not None:
        registration.zarr.close()
    catalog.write_field(
        sim_id,
        "head",
        0,
        np.full((n_layers, n_cells), 10.0),
        n_timesteps=n_timesteps,
    )
    return sim_id


def test_drain_budget_to_positive_outflow_sums_negative_layer_fluxes() -> None:
    drn = np.array([[-2.0, 1.0, -0.5], [-3.0, -4.0, 2.0]], dtype="float64")

    outflow = drain_budget_to_positive_outflow(drn, n_cells=3)

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


def test_compute_derived_writes_positive_outflow_and_local_accumulation(
    catalog: Catalog,
) -> None:
    sim_id = _register_catalog_run(catalog, n_cells=3, n_layers=2)
    catalog.write_field(
        sim_id,
        "drn",
        0,
        np.array([[-2.0, 1.0, -0.5], [-3.0, -4.0, 2.0]]),
        n_timesteps=1,
        subgroup="budget",
    )

    compute_derived(
        sim_id,
        catalog,
        _disabled_derived_flags(outflow_drain=True, accumulation_flux=True),
    )

    expected = np.array([5.0, 4.0, 0.5])
    np.testing.assert_allclose(catalog.query_field(sim_id, "outflow_drain", 0), expected)
    np.testing.assert_allclose(catalog.query_field(sim_id, "accumulation_flux", 0), expected)


def test_compute_derived_prefers_surface_excess_for_seepage_mask(
    catalog: Catalog,
) -> None:
    sim_id = _register_catalog_run(catalog, n_cells=3)
    sz = catalog.open_zarr(sim_id)
    try:
        mesh = sz.root.require_group("mesh")
        mesh.create_array("topography", data=np.array([0.0, 0.0, 0.0]), overwrite=True)
    finally:
        sz.close()
    catalog.write_field(
        sim_id,
        "head",
        0,
        np.array([[5.0, 5.0, 5.0]]),
        n_timesteps=1,
    )
    catalog.write_field(
        sim_id,
        "surface_excess",
        0,
        np.array([0.0, 2.0, -1.0]),
        n_timesteps=1,
        subgroup="budget",
    )

    compute_derived(sim_id, catalog, _disabled_derived_flags(seepage_areas=True))

    np.testing.assert_allclose(
        catalog.query_field(sim_id, "seepage_mask", 0),
        np.array([0.0, 1.0, 0.0]),
    )


def test_compute_derived_writes_release_flux_from_drain_and_surface_excess(
    catalog: Catalog,
) -> None:
    sim_id = _register_catalog_run(catalog, n_cells=3, n_layers=1)
    catalog.write_field(
        sim_id,
        "drain",
        0,
        np.array([[0.5, -2.0, 1.0]], dtype="float64"),
        n_timesteps=1,
        subgroup="budget",
    )
    catalog.write_field(
        sim_id,
        "surface_excess",
        0,
        np.array([1.0, -3.0, 4.0], dtype="float64"),
        n_timesteps=1,
        subgroup="budget",
    )

    compute_derived(sim_id, catalog, _disabled_derived_flags(release_flux=True))

    np.testing.assert_allclose(
        catalog.query_field(sim_id, "release_flux", 0),
        np.array([1.0, 2.0, 4.0], dtype="float64"),
    )


def test_compute_derived_routes_release_accumulation_on_unstructured_mesh(
    catalog: Catalog,
) -> None:
    sim_id = _register_catalog_run(catalog, n_cells=2, mesh_topology="unstructured_2d")
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
    catalog.write_mesh(
        sim_id,
        vertices,
        face_node_connectivity,
        np.array([10.0, 0.0], dtype="float64"),
    )
    sz = catalog.open_zarr(sim_id)
    try:
        mesh = sz.root["mesh"]
        mesh.create_array(
            "topography",
            data=np.array([10.0, 5.0], dtype="float64"),
            overwrite=True,
        )
    finally:
        sz.close()
    catalog.write_field(
        sim_id,
        "surface_excess",
        0,
        np.array([2.5, 0.0], dtype="float64"),
        n_timesteps=1,
        subgroup="budget",
    )

    compute_derived(
        sim_id,
        catalog,
        _disabled_derived_flags(release_accumulation_flux=True),
    )

    np.testing.assert_allclose(
        catalog.query_field(sim_id, "release_flux", 0),
        np.array([2.5, 0.0]),
    )
    np.testing.assert_allclose(
        catalog.query_field(sim_id, "release_accumulation_flux", 0),
        np.array([2.5, 2.5]),
    )


def test_compute_derived_routes_accumulation_on_unstructured_mesh(
    catalog: Catalog,
) -> None:
    sim_id = _register_catalog_run(catalog, n_cells=2, mesh_topology="unstructured_2d")
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
    catalog.write_mesh(
        sim_id,
        vertices,
        face_node_connectivity,
        np.array([10.0, 0.0], dtype="float64"),
    )
    sz = catalog.open_zarr(sim_id)
    try:
        mesh = sz.root["mesh"]
        mesh.create_array(
            "topography",
            data=np.array([10.0, 5.0], dtype="float64"),
            overwrite=True,
        )
    finally:
        sz.close()
    catalog.write_field(
        sim_id,
        "drn",
        0,
        np.array([[-2.5, 0.0]], dtype="float64"),
        n_timesteps=1,
        subgroup="budget",
    )

    compute_derived(sim_id, catalog, _disabled_derived_flags(accumulation_flux=True))

    np.testing.assert_allclose(
        catalog.query_field(sim_id, "accumulation_flux", 0),
        np.array([2.5, 2.5]),
    )
