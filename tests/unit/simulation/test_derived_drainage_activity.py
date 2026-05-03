from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.derived import (
    accumulate_downhill_on_mesh,
    drain_budget_to_positive_outflow,
)
from hydromodpy.simulation.extraction.extractors.derived import (
    DERIVED_VARIABLES,
    compute_derived,
)


@pytest.fixture
def catalog(tmp_path):
    cat = SimulationCatalog(tmp_path / "workspace")
    yield cat
    cat.close()


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
    sid = str(uuid4())
    registration = catalog.register_simulation(
        sid,
        project="test",
        solver="modflow6",
        name=f"drainage_{sid[:8]}",
        n_cells=n_cells,
        n_layers=n_layers,
        n_timesteps=n_timesteps,
        mesh_topology=mesh_topology,
    )
    if registration.zarr is not None:
        registration.zarr.close()
    catalog.write_field(
        sid,
        "head",
        0,
        np.full((n_layers, n_cells), 10.0, dtype="float64"),
        n_timesteps=n_timesteps,
    )
    return sid


def test_drain_budget_to_positive_outflow_sums_negative_layer_fluxes() -> None:
    drn = np.array(
        [
            [-2.0, 1.0, -0.5],
            [-3.0, -4.0, 2.0],
        ],
        dtype="float64",
    )

    outflow = drain_budget_to_positive_outflow(drn, n_cells=3)

    np.testing.assert_allclose(outflow, np.array([5.0, 4.0, 0.5], dtype="float64"))


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
        np.array([2.5, 0.0], dtype="float64"),
        np.array([10.0, 5.0], dtype="float64"),
        face_node_connectivity,
        vertices=vertices,
    )

    np.testing.assert_allclose(accumulated, np.array([2.5, 2.5], dtype="float64"))


def test_compute_derived_writes_positive_outflow_and_local_accumulation(
    catalog: SimulationCatalog,
) -> None:
    sid = _register_catalog_run(catalog, n_cells=3, n_layers=2)
    catalog.write_field(
        sid,
        "drn",
        0,
        np.array(
            [
                [-2.0, 1.0, -0.5],
                [-3.0, -4.0, 2.0],
            ],
            dtype="float64",
        ),
        n_timesteps=1,
        subgroup="budget",
    )

    compute_derived(
        sid,
        catalog,
        _disabled_derived_flags(outflow_drain=True, accumulation_flux=True),
    )

    expected = np.array([5.0, 4.0, 0.5], dtype="float64")
    np.testing.assert_allclose(catalog.query_field(sid, "outflow_drain", 0), expected)
    np.testing.assert_allclose(catalog.query_field(sid, "accumulation_flux", 0), expected)


def test_compute_derived_routes_accumulation_on_unstructured_mesh(
    catalog: SimulationCatalog,
) -> None:
    sid = _register_catalog_run(catalog, n_cells=2, mesh_topology="disv")
    catalog.write_mesh(
        sid,
        np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [2.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [1.0, 1.0, 0.0],
                [2.0, 1.0, 0.0],
            ],
            dtype="float64",
        ),
        np.array(
            [
                [0, 1, 4, 3],
                [1, 2, 5, 4],
            ],
            dtype="int32",
        ),
        np.array([10.0, 0.0], dtype="float64"),
    )
    mesh = catalog.open_zarr_group(sid, mode="a")["mesh"]
    mesh.create_array(
        "surface_top",
        data=np.array([10.0, 5.0], dtype="float64"),
        overwrite=True,
    )
    catalog.write_field(
        sid,
        "drn",
        0,
        np.array([[-2.5, 0.0]], dtype="float64"),
        n_timesteps=1,
        subgroup="budget",
    )

    compute_derived(
        sid,
        catalog,
        _disabled_derived_flags(accumulation_flux=True),
    )

    np.testing.assert_allclose(
        catalog.query_field(sid, "accumulation_flux", 0),
        np.array([2.5, 2.5], dtype="float64"),
    )
