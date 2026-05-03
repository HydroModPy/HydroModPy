from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest

from hydromodpy.core.field_routing import (
    accumulate_downhill_on_mesh,
    active_surface_mask,
    drain_budget_to_positive_outflow,
)
from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.simulation.extraction.extractors.derived import (
    DERIVED_VARIABLES,
    compute_derived,
)


@pytest.fixture
def catalog(tmp_path):
    catalog = SimulationCatalog(tmp_path / "workspace")
    yield catalog
    catalog.close()


def _disabled_derived_flags(**enabled: bool) -> dict[str, bool]:
    flags = {key: False for key in DERIVED_VARIABLES}
    flags.update(enabled)
    return flags


def _register_catalog_run(
    catalog: SimulationCatalog,
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

    accumulated = accumulate_downhill_on_mesh(
        np.array([2.5, 0.0]),
        np.array([10.0, 5.0]),
        face_node_connectivity,
        vertices=vertices,
    )

    np.testing.assert_allclose(accumulated, np.array([2.5, 2.5]))


def test_compute_derived_writes_positive_outflow_and_local_accumulation(
    catalog: SimulationCatalog,
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


def test_compute_derived_routes_accumulation_on_unstructured_mesh(
    catalog: SimulationCatalog,
) -> None:
    sim_id = _register_catalog_run(catalog, n_cells=2, mesh_topology="disv")
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
            "surface_top",
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
