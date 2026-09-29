"""``release_flux`` and ``fluxes_from_budget`` are rebuilt on read, not stored.

A new run keeps the per-cell budget terms and every reader rebuilds the two
fields from them with the function that used to compute them before writing.
A run written before still holds them under ``derived/``, and the stored array
is what every reader returns, so such a store reads exactly as it did.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.exceptions import ExtractError
from hydromodpy.core.field_routing import release_flux_stack
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.derive.views import _stack_field
from hydromodpy.results.derive.virtual_fields import (
    available_virtual_fields,
    derive_field_stack,
)
from hydromodpy.results.run import Run
from hydromodpy.simulation.extraction.derivation.derived import compute_derived

N_STEPS = 5
AREAS = np.array([10.0, 20.0, 40.0, 80.0])
N_CELLS = AREAS.size


def _row_of_rectangles() -> tuple[np.ndarray, np.ndarray]:
    """Unit-height rectangles whose width is the area: the mesh gives AREAS back."""
    x = np.concatenate([[0.0], np.cumsum(AREAS)])
    vertices = np.array([[xi, 0.0, 0.0] for xi in x] + [[xi, 1.0, 0.0] for xi in x])
    n_x = x.size
    connectivity = np.array([[i, i + 1, n_x + i + 1, n_x + i] for i in range(N_CELLS)])
    return vertices, connectivity.astype("int32")


def _budget() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(7)
    drain = -rng.uniform(0.0, 2e-3, (N_STEPS, 1, N_CELLS))
    drain[:, :, 0] = 0.0
    stream = rng.uniform(-3e-3, 1e-3, (N_STEPS, 1, N_CELLS))
    recharge = rng.uniform(0.0, 1e-4, (N_STEPS, 1, N_CELLS))
    return {"drain": drain, "stream": stream, "recharge": recharge}


def _seed(catalog: Catalog, budget: dict[str, np.ndarray]) -> str:
    sid = str(uuid.uuid4())
    reg = catalog.register_simulation(
        sid, project="p", solver="modflow6", n_cells=N_CELLS, n_layers=1, n_timesteps=N_STEPS
    )
    reg.zarr.close()
    vertices, connectivity = _row_of_rectangles()
    sz = catalog.open_zarr(sid)
    try:
        sz.write_mesh(vertices, connectivity, np.array([150.0, 50.0]))
        sz.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 120.0))
        for name, values in budget.items():
            sz.write_field_stack(name, values, subgroup="budget")
    finally:
        sz.close()
    return sid


def _stored_budget(catalog: Catalog, sid: str) -> dict[str, np.ndarray]:
    sz = catalog.open_zarr(sid)
    try:
        group = sz.root["budget"]
        return {name: np.asarray(group[name][:], dtype="float64") for name in group.array_keys()}
    finally:
        sz.close()


@pytest.fixture
def catalog(tmp_path: Path):
    with Catalog(tmp_path / "workspace") as cat:
        yield cat


def test_the_release_flux_flag_writes_nothing_and_the_field_is_served(catalog) -> None:
    sid = _seed(catalog, _budget())

    compute_derived(sid, catalog, {"release_flux": True})

    sz = catalog.open_zarr(sid)
    try:
        derived = sz.root.get("derived")
        assert derived is None or "release_flux" not in derived
        assert "release_flux" in available_virtual_fields(sz.root)
    finally:
        sz.close()
    run = Run(sid, catalog)
    assert run.has_field("release_flux")
    assert "release_flux" in run.array.list_fields()


def test_a_release_step_is_the_union_of_every_path_out(catalog) -> None:
    sid = _seed(catalog, _budget())
    stored = _stored_budget(catalog, sid)
    expected = np.maximum(-stored["drain"][:, 0], 0.0) + np.maximum(-stored["stream"][:, 0], 0.0)

    run = Run(sid, catalog)
    rows = np.stack([run.field("release_flux", timestep=t) for t in range(N_STEPS)])

    np.testing.assert_allclose(rows, expected, rtol=1e-12, atol=0.0)


def test_every_reader_rebuilds_the_same_values_as_the_derivation_computes(catalog) -> None:
    sid = _seed(catalog, _budget())
    sz = catalog.open_zarr(sid)
    try:
        reference = release_flux_stack(sz.root["budget"], n_cells=N_CELLS, start=0, stop=N_STEPS)
        whole = derive_field_stack(sz, sid, "release_flux", range(N_STEPS))
        picked = derive_field_stack(sz, sid, "release_flux", [3, 1])
    finally:
        sz.close()
    run = Run(sid, catalog)
    per_step = np.stack([run.field("release_flux", timestep=t) for t in range(N_STEPS)])

    np.testing.assert_array_equal(whole, reference)
    np.testing.assert_array_equal(per_step, reference)
    np.testing.assert_array_equal(picked, reference[[3, 1]])
    np.testing.assert_array_equal(_stack_field(run, "release_flux"), reference)


def test_a_run_whose_budget_has_no_path_out_is_refused(catalog) -> None:
    sid = _seed(catalog, {"recharge": _budget()["recharge"]})

    with pytest.raises(ExtractError, match="spatial_fields"):
        compute_derived(sid, catalog, {"release_flux": True})
    assert not Run(sid, catalog).has_field("release_flux")


def test_the_unit_budget_flux_is_the_drain_over_the_cell_area(catalog) -> None:
    sid = _seed(catalog, _budget())
    drain = _stored_budget(catalog, sid)["drain"][:, 0]

    run = Run(sid, catalog)

    assert run.has_field("fluxes_from_budget")
    for step in range(N_STEPS):
        np.testing.assert_allclose(
            run.field("fluxes_from_budget", timestep=step), drain[step] / AREAS, rtol=1e-12
        )
    sz = catalog.open_zarr(sid)
    try:
        stack = derive_field_stack(sz, sid, "fluxes_from_budget", range(N_STEPS))
    finally:
        sz.close()
    np.testing.assert_allclose(stack, drain / AREAS, rtol=1e-12)


def test_the_unit_budget_flux_needs_the_mesh_geometry(catalog, tmp_path: Path) -> None:
    sid = str(uuid.uuid4())
    reg = catalog.register_simulation(
        sid, project="p", solver="modflow6", n_cells=N_CELLS, n_layers=1, n_timesteps=N_STEPS
    )
    reg.zarr.close()
    catalog.write_field_stack(sid, "head", np.full((N_STEPS, 1, N_CELLS), 120.0))
    catalog.write_field_stack(sid, "drain", _budget()["drain"], subgroup="budget")

    run = Run(sid, catalog)

    assert not run.has_field("fluxes_from_budget")
    assert run.has_field("release_flux")


def test_a_store_written_before_reads_its_stored_arrays(tmp_path: Path) -> None:
    """Old runs are float64 with the two fields stored; the stored array wins."""
    persistence = PersistenceConfig(field_precision="exact")
    with Catalog(tmp_path / "old", persistence=persistence) as catalog:
        budget = _budget()
        sid = _seed(catalog, budget)
        # Deliberately not what the budget rebuilds, so a recomputation is caught.
        stored_release = np.arange(N_STEPS * N_CELLS, dtype="float64").reshape(N_STEPS, N_CELLS)
        stored_unit = stored_release / 7.0 + 0.1
        catalog.write_field_stack(sid, "release_flux", stored_release, subgroup="derived")
        catalog.write_field_stack(sid, "fluxes_from_budget", stored_unit, subgroup="derived")

        sz = catalog.open_zarr(sid)
        try:
            assert sz.root["derived"]["release_flux"].dtype == np.float64
            assert sz.root["head"].dtype == np.float64
            np.testing.assert_array_equal(sz.root["budget"]["drain"][:], budget["drain"])
        finally:
            sz.close()

        run = Run(sid, catalog)
        for step in range(N_STEPS):
            np.testing.assert_array_equal(
                run.field("release_flux", timestep=step), stored_release[step]
            )
            np.testing.assert_array_equal(
                run.field("fluxes_from_budget", timestep=step), stored_unit[step]
            )
        np.testing.assert_array_equal(_stack_field(run, "release_flux"), stored_release)
        np.testing.assert_array_equal(
            run.array.to_xarray_batch(("release_flux",))["release_flux"].values, stored_release
        )
