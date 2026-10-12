"""Every derived field is rebuilt on read, not stored.

A new run keeps the per-cell budget terms and every reader rebuilds the fields
from them, over a whole range or for one step, the step being one row of the
range. ``fixtures/derived_at_d5f485f88`` holds what the code before the
rebuild, which computed and stored them, derived on synthetic stores: the
rebuilt fields equal it bit for bit. A run written before still holds some
fields under ``derived/``, and the stored array is what every reader returns,
so such a store reads exactly as it did.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.field_routing import release_flux_stack
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.derive import virtual_fields
from hydromodpy.results.derive.views import _stack_field
from hydromodpy.results.derive.virtual_fields import (
    VIRTUAL_FIELD_ROWS,
    available_virtual_fields,
    derive_field_stack,
    read_field_or_virtual,
    read_field_range_or_virtual,
)
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run import Run
from tests.regression.golden_utils import store_field_signature
from tests.unit.results import _derived_reference_stores as reference

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


def test_a_run_stores_no_release_flux_and_the_field_is_served(catalog) -> None:
    sid = _seed(catalog, _budget())

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


def test_a_run_whose_budget_has_no_path_out_serves_no_release_flux(catalog) -> None:
    sid = _seed(catalog, {"recharge": _budget()["recharge"]})

    run = Run(sid, catalog)

    assert not run.has_field("release_flux")
    with pytest.raises(FieldNotFoundError):
        run.field("release_flux", timestep=0)


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


# -- Every field, against what the code before the rebuild derived ------------

NO_ROUTE_FIELDS = ("accumulation_flux", "release_accumulation_flux")


@pytest.fixture
def exact_catalog(tmp_path: Path):
    """The precision the reference stores were written and derived in."""
    persistence = PersistenceConfig(field_precision="exact")
    with Catalog(tmp_path / "exact", persistence=persistence) as cat:
        yield cat


@pytest.fixture(autouse=True)
def _fresh_descent_cache():
    from hydromodpy.results.derive import accumulation

    accumulation._graphs.clear()
    yield
    accumulation._graphs.clear()


def _reference_cases() -> list[tuple[str, str]]:
    """Return (store, array name) for each stack the base code derived and a reader rebuilds.

    ``virtual__outflow_drain`` is the base per-step read, which took the drain
    term alone; it is checked apart. The base wrote an unrouted local flux for
    a store with no descent, which a reader never serves.
    """
    cases = []
    for kind in reference.STORE_KINDS:
        with np.load(reference.fixture_path(kind)) as archive:
            for key in archive.files:
                if key.startswith("route__") or key == "virtual__outflow_drain":
                    continue
                if kind == "no_route" and key.removeprefix("base__") in NO_ROUTE_FIELDS:
                    continue
                cases.append((kind, key))
    return cases


def _reference(kind: str, key: str) -> np.ndarray:
    with np.load(reference.fixture_path(kind)) as archive:
        return archive[key]


def _built(kind: str, catalog: Catalog) -> str:
    return reference.build_store(kind, catalog)


@pytest.mark.parametrize(("kind", "key"), _reference_cases())
def test_a_range_equals_what_the_base_derived_bit_for_bit(exact_catalog, kind, key) -> None:
    sid = _built(kind, exact_catalog)
    field = key.split("__", 1)[1]

    rebuilt = read_field_range_or_virtual(exact_catalog, sid, field, 0, reference.N_STEPS)

    np.testing.assert_array_equal(rebuilt, _reference(kind, key))


@pytest.mark.parametrize(("kind", "key"), _reference_cases())
def test_a_step_read_alone_equals_the_row_of_the_range(exact_catalog, kind, key) -> None:
    sid = _built(kind, exact_catalog)
    field = key.split("__", 1)[1]
    expected = _reference(kind, key)

    for step in range(reference.N_STEPS):
        np.testing.assert_array_equal(
            read_field_or_virtual(exact_catalog, sid, field, step), expected[step]
        )
    np.testing.assert_array_equal(
        read_field_or_virtual(exact_catalog, sid, field, -1), expected[-1]
    )


@pytest.mark.parametrize(("kind", "key"), _reference_cases())
def test_a_sub_range_is_the_rows_of_the_whole_range(exact_catalog, kind, key) -> None:
    sid = _built(kind, exact_catalog)
    field = key.split("__", 1)[1]

    part = read_field_range_or_virtual(exact_catalog, sid, field, 2, 5)

    np.testing.assert_array_equal(part, _reference(kind, key)[2:5])


@pytest.mark.parametrize(("kind", "key"), _reference_cases())
def test_passes_of_one_step_join_into_the_whole_range(
    exact_catalog, monkeypatch: pytest.MonkeyPatch, kind, key
) -> None:
    """The running sum of mass_accumulated carries over from one pass to the next."""
    sid = _built(kind, exact_catalog)
    field = key.split("__", 1)[1]
    monkeypatch.setattr(virtual_fields, "ROWS_PER_PASS_ELEMENTS", reference.N_CELLS)

    rebuilt = read_field_range_or_virtual(exact_catalog, sid, field, 0, reference.N_STEPS)

    np.testing.assert_array_equal(rebuilt, _reference(kind, key))


def test_every_field_has_a_range_path_and_a_step_that_is_a_row_of_it() -> None:
    assert set(VIRTUAL_FIELD_ROWS) <= set(virtual_fields.VIRTUAL_FIELDS)
    assert set(VIRTUAL_FIELD_ROWS) == {
        "watertable_elevation",
        "watertable_depth",
        "seepage_mask",
        "outflow_drain",
        "release_flux",
        "fluxes_from_budget",
        "accumulation_flux",
        "release_accumulation_flux",
        "concentration_seepage",
        "mass_seepage",
        "mass_accumulated",
    }


def test_the_outflow_drain_adds_the_mover_the_base_step_read_left_out(exact_catalog) -> None:
    sid = _built("mf6", exact_catalog)

    rebuilt = read_field_range_or_virtual(exact_catalog, sid, "outflow_drain", 0, reference.N_STEPS)

    np.testing.assert_array_equal(rebuilt, _reference("mf6", "base__outflow_drain"))
    drain_alone = _reference("mf6", "virtual__outflow_drain")
    # Step 4 holds only positive drain values: with the mover added the sign
    # fallback no longer applies there, so that step is left out.
    steps = [0, 1, 2, 3, 5]
    assert np.all(rebuilt[steps] >= drain_alone[steps])
    assert np.any(rebuilt[steps] > drain_alone[steps])


def test_a_store_with_no_mover_reads_the_drain_as_the_base_step_read_did(exact_catalog) -> None:
    sid = _built("boussinesq", exact_catalog)

    rebuilt = read_field_range_or_virtual(exact_catalog, sid, "outflow_drain", 0, reference.N_STEPS)

    np.testing.assert_array_equal(rebuilt, _reference("boussinesq", "virtual__outflow_drain"))


def test_the_solute_chain_keeps_nan_outside_the_seepage_and_where_the_concentration_is(
    exact_catalog,
) -> None:
    sid = _built("transport", exact_catalog)
    seepage = _reference("transport", "base__seepage_mask")

    conc = read_field_range_or_virtual(
        exact_catalog, sid, "concentration_seepage", 0, reference.N_STEPS
    )
    mass = read_field_range_or_virtual(exact_catalog, sid, "mass_seepage", 0, reference.N_STEPS)
    total = read_field_range_or_virtual(
        exact_catalog, sid, "mass_accumulated", 0, reference.N_STEPS
    )

    assert np.all(np.isnan(conc[seepage == 0]))
    assert np.all(np.isnan(mass[seepage == 0]))
    assert np.isnan(conc[:, 2]).all()
    # A NaN stays NaN from its step on, so a cell that seeps only sometimes is NaN afterwards.
    first_nan = np.isnan(total).argmax(axis=0)
    for cell in np.flatnonzero(np.isnan(total).any(axis=0)):
        assert np.isnan(total[first_nan[cell] :, cell]).all()


# -- A store that can route nothing ------------------------------------------


def test_a_store_with_no_descent_and_no_topology_does_not_list_the_accumulation(
    exact_catalog,
) -> None:
    sid = _built("no_route", exact_catalog)
    sz = exact_catalog.open_zarr(sid)
    try:
        listed = available_virtual_fields(sz.root)
    finally:
        sz.close()

    for field in NO_ROUTE_FIELDS:
        assert field not in listed
        with pytest.raises(KeyError):
            read_field_or_virtual(exact_catalog, sid, field, 0)
        with pytest.raises(KeyError):
            read_field_range_or_virtual(exact_catalog, sid, field, 0, 2)
    assert {"release_flux", "outflow_drain", "seepage_mask"} <= set(listed)


def test_the_stores_list_the_fields_they_can_serve(exact_catalog) -> None:
    listed = {}
    for kind in reference.STORE_KINDS:
        sid = _built(kind, exact_catalog)
        sz = exact_catalog.open_zarr(sid)
        try:
            listed[kind] = set(available_virtual_fields(sz.root))
        finally:
            sz.close()

    chain = {"concentration_seepage", "mass_seepage", "mass_accumulated"}
    assert chain <= listed["transport"]
    for kind in set(reference.STORE_KINDS) - {"transport"}:
        assert not chain & listed[kind]
    for kind in ("mf6", "mf6_no_descent", "boussinesq", "boussinesq_no_excess", "transport"):
        assert set(NO_ROUTE_FIELDS) <= listed[kind]
    assert "fluxes_from_budget" not in listed["boussinesq"]


def test_a_step_outside_the_time_axis_is_refused(exact_catalog) -> None:
    sid = _built("mf6", exact_catalog)

    for field in ("watertable_elevation", "seepage_mask", "accumulation_flux", "outflow_drain"):
        with pytest.raises(IndexError):
            read_field_or_virtual(exact_catalog, sid, field, reference.N_STEPS)
        with pytest.raises(IndexError):
            read_field_range_or_virtual(exact_catalog, sid, field, 0, reference.N_STEPS + 1)


# -- The geometric fallback warns once per read ------------------------------


def _fallback_warnings(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if "geometric criterion" in record.getMessage()]


def test_the_geometric_fallback_warns_once_for_a_whole_range(
    exact_catalog, caplog, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _built("boussinesq_no_excess", exact_catalog)
    monkeypatch.setattr(virtual_fields, "ROWS_PER_PASS_ELEMENTS", reference.N_CELLS)

    with caplog.at_level(logging.WARNING, logger="hydromodpy.core.field_routing"):
        read_field_range_or_virtual(exact_catalog, sid, "seepage_mask", 0, reference.N_STEPS)

    assert len(_fallback_warnings(caplog)) == 1


def test_the_geometric_fallback_warns_once_for_each_step_read_alone(exact_catalog, caplog) -> None:
    sid = _built("boussinesq_no_excess", exact_catalog)

    with caplog.at_level(logging.WARNING, logger="hydromodpy.core.field_routing"):
        read_field_or_virtual(exact_catalog, sid, "seepage_mask", 1)
        read_field_or_virtual(exact_catalog, sid, "seepage_mask", 2)

    assert len(_fallback_warnings(caplog)) == 2


def test_a_modflow_store_stays_quiet_and_so_does_a_surface_excess_store(
    exact_catalog, caplog
) -> None:
    with caplog.at_level(logging.WARNING, logger="hydromodpy.core.field_routing"):
        for kind in ("mf6", "boussinesq"):
            sid = _built(kind, exact_catalog)
            read_field_range_or_virtual(exact_catalog, sid, "seepage_mask", 0, reference.N_STEPS)

    assert _fallback_warnings(caplog) == []


def test_the_solute_chain_warns_once_when_it_falls_back_to_the_geometric_mask(
    exact_catalog, caplog, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _built("boussinesq_no_excess", exact_catalog)
    sz = exact_catalog.open_zarr(sid)
    try:
        sz.write_field_stack("concentration", np.ones((reference.N_STEPS, reference.N_CELLS)))
    finally:
        sz.close()
    monkeypatch.setattr(virtual_fields, "ROWS_PER_PASS_ELEMENTS", reference.N_CELLS)

    with caplog.at_level(logging.WARNING, logger="hydromodpy.core.field_routing"):
        read_field_range_or_virtual(exact_catalog, sid, "mass_accumulated", 0, reference.N_STEPS)

    assert len(_fallback_warnings(caplog)) == 1


# -- A run written before: the stored array is read first, upstream too ------


def _write_derived(catalog: Catalog, sid: str, name: str, values: np.ndarray) -> None:
    sz = catalog.open_zarr(sid)
    try:
        sz.write_field_stack(name, values, subgroup="derived")
    finally:
        sz.close()


def _budget_of(catalog: Catalog, sid: str, name: str) -> np.ndarray:
    sz = catalog.open_zarr(sid)
    try:
        return np.asarray(sz.root["budget"][name][:], dtype="float64")
    finally:
        sz.close()


def test_an_old_stored_water_table_feeds_the_depth_and_the_geometric_seepage(
    exact_catalog,
) -> None:
    sid = _built("mf6", exact_catalog)
    stored = np.linspace(15.0, 30.0, reference.N_STEPS * reference.N_CELLS).reshape(
        reference.N_STEPS, reference.N_CELLS
    )
    _write_derived(exact_catalog, sid, "watertable_elevation", stored)
    sz = exact_catalog.open_zarr(sid)
    try:
        top = np.asarray(sz.root["mesh"]["topography"][:], dtype="float64")
    finally:
        sz.close()
    expected_depth = np.maximum(top - stored, 0.0)
    expected_seepage = (stored >= top - 0.5 * reference.BAND_DEPTH_M).astype("float64")

    depth = read_field_range_or_virtual(
        exact_catalog, sid, "watertable_depth", 0, reference.N_STEPS
    )
    seepage = read_field_range_or_virtual(exact_catalog, sid, "seepage_mask", 0, reference.N_STEPS)

    np.testing.assert_array_equal(depth, expected_depth)
    np.testing.assert_array_equal(seepage, expected_seepage)
    np.testing.assert_array_equal(
        read_field_or_virtual(exact_catalog, sid, "watertable_depth", 3), expected_depth[3]
    )


def test_an_old_stored_seepage_mask_decides_the_concentration_at_seepage(exact_catalog) -> None:
    sid = _built("transport", exact_catalog)
    mask = np.zeros((reference.N_STEPS, reference.N_CELLS))
    mask[:, ::2] = 1.0
    _write_derived(exact_catalog, sid, "seepage_mask", mask)
    sz = exact_catalog.open_zarr(sid)
    try:
        conc = np.asarray(sz.root["concentration"][:, 0], dtype="float64")
    finally:
        sz.close()

    rebuilt = read_field_range_or_virtual(
        exact_catalog, sid, "concentration_seepage", 0, reference.N_STEPS
    )

    np.testing.assert_array_equal(rebuilt, np.where(mask > 0, conc * mask, np.nan))


def test_an_old_stored_concentration_and_mass_feed_the_next_field(exact_catalog) -> None:
    sid = _built("transport", exact_catalog)
    shape = (reference.N_STEPS, reference.N_CELLS)
    stored_concentration = np.arange(np.prod(shape), dtype="float64").reshape(shape) / 7.0
    _write_derived(exact_catalog, sid, "concentration_seepage", stored_concentration)
    drain = _budget_of(exact_catalog, sid, "drain")
    from hydromodpy.core.field_routing import drain_budget_stack_to_positive_outflow

    flux = drain_budget_stack_to_positive_outflow(drain, n_cells=reference.N_CELLS)

    mass = read_field_range_or_virtual(exact_catalog, sid, "mass_seepage", 0, reference.N_STEPS)

    np.testing.assert_array_equal(mass, stored_concentration * flux)

    stored_mass = np.arange(np.prod(shape), dtype="float64").reshape(shape) * 0.1
    _write_derived(exact_catalog, sid, "mass_seepage", stored_mass)

    total = read_field_range_or_virtual(
        exact_catalog, sid, "mass_accumulated", 0, reference.N_STEPS
    )

    np.testing.assert_array_equal(total, np.cumsum(stored_mass, axis=0))
    np.testing.assert_array_equal(
        read_field_or_virtual(exact_catalog, sid, "mass_accumulated", 4), total[4]
    )


def test_the_mass_flux_multiplies_by_one_when_the_run_has_no_drain_term(exact_catalog) -> None:
    sid = str(uuid.uuid4())
    exact_catalog.register_simulation(
        sid, project="p", solver="modflow6", n_cells=N_CELLS, n_layers=1, n_timesteps=N_STEPS
    ).zarr.close()
    concentration = np.full((N_STEPS, 1, N_CELLS), 2.0)
    sz = exact_catalog.open_zarr(sid)
    try:
        sz.write_topography(np.full(N_CELLS, 100.0))
        sz.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 101.0))
        sz.write_field_stack("concentration", concentration)
        sz.write_field_stack("recharge", np.full((N_STEPS, 1, N_CELLS), 1e-4), subgroup="budget")
    finally:
        sz.close()

    mass = read_field_range_or_virtual(exact_catalog, sid, "mass_seepage", 0, N_STEPS)

    np.testing.assert_array_equal(mass, np.full((N_STEPS, N_CELLS), 2.0))


def test_the_mass_chain_needs_a_budget_group(exact_catalog) -> None:
    sid = str(uuid.uuid4())
    exact_catalog.register_simulation(
        sid, project="p", solver="modflow6", n_cells=N_CELLS, n_layers=1, n_timesteps=N_STEPS
    ).zarr.close()
    sz = exact_catalog.open_zarr(sid)
    try:
        sz.write_topography(np.full(N_CELLS, 100.0))
        sz.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 101.0))
        sz.write_field_stack("concentration", np.ones((N_STEPS, 1, N_CELLS)))
        listed = available_virtual_fields(sz.root)
    finally:
        sz.close()

    assert "concentration_seepage" in listed
    assert "mass_seepage" not in listed
    assert "mass_accumulated" not in listed
    with pytest.raises(KeyError):
        read_field_range_or_virtual(exact_catalog, sid, "mass_seepage", 0, N_STEPS)


# -- Readers that walk the steps read the range ------------------------------


def test_a_comparison_series_of_a_rebuilt_field_is_read_over_the_range(
    exact_catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.analysis.comparison.runtime.series import _virtual_field_slices

    sid = _built("transport", exact_catalog)
    reads: list[tuple[int, int]] = []
    original = virtual_fields.read_field_range_or_virtual

    def spy(source, sim_id, variable, start, stop, layer=None):
        reads.append((start, stop))
        return original(source, sim_id, variable, start, stop, layer=layer)

    monkeypatch.setattr(virtual_fields, "read_field_range_or_virtual", spy)
    slices = _virtual_field_slices(
        exact_catalog, sid, "mass_accumulated", reference.N_STEPS, [], False
    )

    assert reads == [(0, reference.N_STEPS)]
    expected = _reference("transport", "base__mass_accumulated")
    assert len(slices) == reference.N_STEPS
    for step, time_slice in enumerate(slices):
        np.testing.assert_array_equal(time_slice.values, expected[step])


def test_the_golden_signature_reads_the_time_axis_not_a_probe(exact_catalog) -> None:
    sid = _built("transport", exact_catalog)

    stored = store_field_signature(exact_catalog, sid, "head")
    rebuilt = store_field_signature(exact_catalog, sid, "mass_accumulated")

    assert stored["available_timesteps"] == reference.N_STEPS
    assert stored["timestep"] == reference.N_STEPS - 1
    assert stored["shape"] == [2 * reference.N_CELLS]
    assert rebuilt["available_timesteps"] == reference.N_STEPS
    last = _reference("transport", "base__mass_accumulated")[-1]
    assert rebuilt["count"] == int(np.isfinite(last).sum())
    with pytest.raises(KeyError):
        store_field_signature(exact_catalog, sid, "seepage_areas")
