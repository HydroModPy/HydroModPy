from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from hydromodpy.core.budget_terms import BudgetKeep, kept_budget
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.results.catalog import Catalog
from hydromodpy.solver.boussinesq.assembly import assemble_steady_residual
from hydromodpy.solver.boussinesq.extractors.descent import decode_d8_pointer, raster_grid_shape
from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


def _two_cell_mesh() -> BoussinesqMesh:
    return BoussinesqMesh(
        bundle_dir=Path("."),
        cell_ids=np.asarray([0, 1], dtype=int),
        node_ids=np.asarray([0, 1, 2, 3], dtype=int),
        node_x_m=np.asarray([0.0, 1.0, 0.0, 1.0], dtype=float),
        node_y_m=np.asarray([0.0, 0.0, 1.0, 1.0], dtype=float),
        cell_node_ids=((0, 1, 2), (1, 3, 2)),
        cell_centroid_x_m=np.asarray([0.33, 0.67], dtype=float),
        cell_centroid_y_m=np.asarray([0.33, 0.67], dtype=float),
        cell_area_m2=np.asarray([100.0, 200.0], dtype=float),
        z_top_m=np.asarray([10.0, 12.0], dtype=float),
        z_bottom_m=np.asarray([0.0, 1.0], dtype=float),
        hydraulic_conductivity_m_s=np.asarray([1.0e-4, 2.0e-4], dtype=float),
        storage_coefficient=np.asarray([0.1, 0.1], dtype=float),
        edge_ids=np.asarray([0], dtype=int),
        edge_node_a=np.asarray([1], dtype=int),
        edge_node_b=np.asarray([2], dtype=int),
        edge_cell_a=np.asarray([0], dtype=int),
        edge_cell_b=np.asarray([1], dtype=int),
        edge_length_m=np.asarray([1.0], dtype=float),
        edge_distance_m=np.asarray([1.0], dtype=float),
        edge_midpoint_distance_to_cell_a_m=np.asarray([0.5], dtype=float),
        edge_midpoint_distance_to_cell_b_m=np.asarray([0.5], dtype=float),
        edge_midpoint_x_m=np.asarray([0.5], dtype=float),
        edge_midpoint_y_m=np.asarray([0.5], dtype=float),
        edge_kind=("internal",),
        edge_is_river=np.asarray([False], dtype=bool),
        cell_index_by_id={0: 0, 1: 1},
        node_index_by_id={0: 0, 1: 1, 2: 2, 3: 3},
    )


def test_prescribed_head_residual_keeps_head_and_flux_units_separate() -> None:
    mesh = _two_cell_mesh()
    assembly = assemble_steady_residual(
        mesh,
        head_m=np.asarray([5.0, 7.0], dtype=float),
        recharge_rate_m_s=np.asarray([1.0e-8, 2.0e-8], dtype=float),
        prescribed_head_m_by_cell=np.asarray([4.0, np.nan], dtype=float),
    )

    assert assembly.head_constraint_residual_m[0] == pytest.approx(1.0)
    assert assembly.solver_residual[0] == pytest.approx(1.0)
    assert assembly.residual_m3_s[0] == pytest.approx(assembly.flow_residual_m3_s[0])
    assert assembly.residual_m3_s[0] != pytest.approx(assembly.solver_residual[0])
    assert assembly.solver_residual[1] == pytest.approx(assembly.flow_residual_m3_s[1])


def _write_transient_payload(output_dir: Path) -> None:
    output_dir.mkdir()
    # A transient history: the initial state at 0 s, then the end of two periods.
    state_payload = {
        "head_history_m": np.asarray([[5.0, 6.0], [5.5, 6.5], [5.7, 6.7]], dtype=float),
        "snapshot_elapsed_seconds": np.asarray([0.0, 86400.0, 172800.0], dtype=float),
        "period_lengths_seconds": np.asarray([86400.0, 86400.0], dtype=float),
        "recharge_rate_history_m_s": np.asarray(
            [[0.0, 0.0], [1.0e-8, 2.0e-8], [3.0e-8, 4.0e-8]],
            dtype=float,
        ),
        "drainage_flux_history_m3_s": np.asarray([[0.0, 0.0], [0.1, 0.2], [0.3, 0.4]], dtype=float),
        "well_flux_history_m3_s": np.asarray(
            [[0.0, 0.0], [-0.01, 0.0], [-0.02, 0.01]], dtype=float
        ),
        # The solver signs the prescribed-head flux positive out of the aquifer.
        "prescribed_head_flux_history_m3_s": np.asarray(
            [[0.0, 0.0], [0.05, 0.0], [-0.02, 0.0]], dtype=float
        ),
        "saturation_excess_history_m_s": np.asarray(
            [[0.0, 0.0], [1.0e-9, 0.0], [0.0, 2.0e-9]],
            dtype=float,
        ),
        "z_top_m": np.asarray([10.0, 12.0], dtype=float),
        "z_bottom_m": np.asarray([0.0, 1.0], dtype=float),
        "cell_area_m2": np.asarray([100.0, 200.0], dtype=float),
    }
    np.savez(output_dir / "_boussinesq_state_history.npz", **state_payload)
    (output_dir / "_boussinesq_summary.json").write_text(
        json.dumps({"z_top_m": [10.0, 12.0], "z_bottom_m": [0.0, 1.0]}),
        encoding="utf-8",
    )


def _extract_transient(tmp_path: Path, **kwargs: object) -> tuple[Catalog, str]:
    output_dir = tmp_path / "solver"
    _write_transient_payload(output_dir)
    # Exact precision: this checks the extractor numbers, not the storage rounding.
    catalog = Catalog(
        tmp_path / "workspace", persistence=PersistenceConfig(field_precision="exact")
    )
    sim_id = str(uuid4())
    registration = catalog.register_simulation(
        sim_id,
        project="test",
        solver="boussinesq",
        n_cells=2,
        n_layers=1,
        n_timesteps=2,
    )
    if registration.zarr is not None:
        registration.zarr.close()
    try:
        BoussinesqOutputAdapter().extract(sim_id, output_dir, catalog, **kwargs)
    except BaseException:
        catalog.close()
        raise
    return catalog, sim_id


_ALL_COMPONENTS = ["constant_head", "drain", "recharge", "surface_excess", "well"]


def test_boussinesq_extractor_writes_cellwise_interfaces_and_volumetric_budgets(
    tmp_path: Path,
) -> None:
    catalog, sim_id = _extract_transient(tmp_path)
    try:
        zarr_store = catalog.open_zarr(sim_id)
        try:
            # One slice per period, stamped at its end: the initial state closes
            # no period and stays in the state group only.
            np.testing.assert_allclose(
                zarr_store.root["head"][:].reshape(2, 2), [[5.5, 6.5], [5.7, 6.7]]
            )
            assert len(zarr_store.read_time()) == 2
            assert zarr_store.root["boussinesq_state"]["head_history_m"].shape == (3, 2)
            mesh = zarr_store.root["mesh"]
            np.testing.assert_allclose(mesh["topography"][:], np.asarray([10.0, 12.0]))
            np.testing.assert_allclose(
                mesh["z_interfaces"][:],
                np.asarray([[10.0, 12.0], [0.0, 1.0]], dtype=float),
            )
            # The whole per-cell budget by default, every term under its name.
            budget = zarr_store.root["budget"]
            assert sorted(budget.array_keys()) == _ALL_COMPONENTS
            np.testing.assert_allclose(
                budget["recharge"][0],
                np.asarray([1.0e-6, 4.0e-6], dtype=float),
            )
            np.testing.assert_allclose(
                budget["surface_excess"][:],
                np.asarray([[1.0e-7, 0.0], [0.0, 4.0e-7]], dtype=float),
            )
            # Positive into the aquifer, as the registry and MODFLOW sign it.
            np.testing.assert_allclose(
                budget["constant_head"][:],
                np.asarray([[-0.05, 0.0], [0.02, 0.0]], dtype=float),
            )
            kept = kept_budget(zarr_store.root)
            assert kept is not None
            assert kept.policy == "all"
            assert list(kept.terms) == _ALL_COMPONENTS
            # The seepage mask is rebuilt on read from budget/surface_excess.
            derived = zarr_store.root.get("derived")
            assert derived is None or not {"seepage_mask", "seepage_rate"} & set(derived)
            # No grid metadata: the cells are no raster and no descent is stored.
            assert "descent_receiver" not in mesh
        finally:
            zarr_store.close()
    finally:
        catalog.close()


def test_boussinesq_extractor_keeps_only_the_planned_terms(tmp_path: Path) -> None:
    """The consumers policy writes the planned terms and records them, produced or not."""
    keep = BudgetKeep.of_terms({"surface_excess", "drain", "stream"})
    catalog, sim_id = _extract_transient(tmp_path, budget_terms=keep)
    try:
        zarr_store = catalog.open_zarr(sim_id)
        try:
            budget = zarr_store.root["budget"]
            assert sorted(budget.array_keys()) == ["drain", "surface_excess"]
            kept = kept_budget(zarr_store.root)
            assert kept is not None
            assert kept.policy == "consumers"
            # A planned term the model does not produce is still declared kept.
            assert list(kept.terms) == ["drain", "stream", "surface_excess"]
        finally:
            zarr_store.close()
        # The lumped table holds every term, whatever the per-cell policy.
        table = catalog.query_budget(sim_id)
        assert sorted(set(table["component"])) == _ALL_COMPONENTS
    finally:
        catalog.close()


def test_boussinesq_extractor_declares_an_empty_budget_group(tmp_path: Path) -> None:
    """A run that keeps no per-cell term still says so on the budget group."""
    catalog, sim_id = _extract_transient(tmp_path, budget_terms=BudgetKeep.of_terms(()))
    try:
        zarr_store = catalog.open_zarr(sim_id)
        try:
            assert "head" in zarr_store.root
            assert list(zarr_store.root["budget"].array_keys()) == []
            assert kept_budget(zarr_store.root) == ("consumers", ())
        finally:
            zarr_store.close()
    finally:
        catalog.close()


def test_raster_grid_shape_takes_the_metadata_raster_only() -> None:
    uniform = np.full(6, 25.0)
    assert raster_grid_shape({"nrow": "2", "ncol": "3"}, 6, uniform) == ((2, 3), "")
    assert raster_grid_shape({"nrow": "2", "ncol": "3"}, 6, None)[0] == (2, 3)
    # No metadata, a cell count that is not the raster's, a triangle mesh.
    assert raster_grid_shape({}, 6, uniform)[0] is None
    assert raster_grid_shape({"nrow": "3", "ncol": "3"}, 6, uniform)[0] is None
    triangles = np.asarray([25.0, 24.0, 25.0, 26.0, 25.0, 25.0])
    shape, reason = raster_grid_shape({"nrow": "2", "ncol": "3"}, 6, triangles)
    assert shape is None
    assert "area" in reason


def test_decode_d8_pointer_reads_the_whitebox_codes() -> None:
    # Whitebox's non-ESRI pointer: 1 NE, 2 E, 4 SE, 8 S, 16 SW, 32 W, 64 NW, 128 N.
    pointer = np.asarray([[2, 4, 0], [128, 32, 16], [1, 1, 64]])
    valid = np.ones(pointer.shape, dtype=bool)
    valid[2, 2] = False
    # Row-major ids 0 1 2 / 3 4 5 / 6 7 8. Cell 2 has no receiver, cell 7 (NE)
    # points at 5, cell 8 is nodata.
    np.testing.assert_array_equal(decode_d8_pointer(pointer, valid), [1, 5, -1, 0, 3, 7, 4, 5, -1])
    # A cell pointing off the raster or at a nodata cell is an outlet.
    pointer[0, 0] = 128
    pointer[1, 1] = 4
    receiver = decode_d8_pointer(pointer, valid)
    assert receiver[0] == -1
    assert receiver[4] == -1


def test_boussinesq_extractor_raises_on_invalid_surface_metadata(tmp_path: Path) -> None:
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    np.savez(
        output_dir / "_boussinesq_state_history.npz",
        head_history_m=np.asarray([[5.0, 6.0]], dtype=float),
        snapshot_elapsed_seconds=np.asarray([0.0], dtype=float),
    )
    (output_dir / "_boussinesq_summary.json").write_text("{invalid", encoding="utf-8")

    catalog = Catalog(tmp_path / "workspace")
    sim_id = str(uuid4())
    registration = catalog.register_simulation(
        sim_id,
        project="test",
        solver="boussinesq",
        n_cells=2,
        n_layers=1,
        n_timesteps=1,
    )
    if registration.zarr is not None:
        registration.zarr.close()

    try:
        with pytest.raises(RuntimeError, match="Could not parse Boussinesq summary"):
            BoussinesqOutputAdapter().extract(sim_id, output_dir, catalog)
    finally:
        catalog.close()


def test_boussinesq_extractor_stores_no_descent_when_whitebox_fails(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    """Without a pointer the run stores no D: its accumulation is unavailable, never local."""
    from hydromodpy.solver.boussinesq.extractors import flow as flow_module

    def fail(_top: np.ndarray, _shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        raise RuntimeError("no Whitebox here")

    monkeypatch.setattr(flow_module, "whitebox_d8_descent", fail)
    output_dir = tmp_path / "solver"
    _write_transient_payload(output_dir)
    # Two cells of one area, laid out as a 1 x 2 raster.
    with np.load(output_dir / "_boussinesq_state_history.npz") as payload:
        arrays = dict(payload)
    arrays["cell_area_m2"] = np.asarray([100.0, 100.0])
    np.savez(output_dir / "_boussinesq_state_history.npz", **arrays)
    catalog = Catalog(tmp_path / "workspace")
    sim_id = str(uuid4())
    registration = catalog.register_simulation(
        sim_id, project="test", solver="boussinesq", n_cells=2, n_layers=1, n_timesteps=2
    )
    if registration.zarr is not None:
        registration.zarr.close()
    catalog.write_geographic_metadata(sim_id, {"nrow": 1, "ncol": 2})
    try:
        with caplog.at_level("WARNING"):
            BoussinesqOutputAdapter().extract(sim_id, output_dir, catalog)
        zarr_store = catalog.open_zarr(sim_id)
        try:
            assert "descent_receiver" not in zarr_store.root["mesh"]
            assert "drain" in zarr_store.root["budget"]
        finally:
            zarr_store.close()
        assert "stores no descent" in caplog.text
    finally:
        catalog.close()
