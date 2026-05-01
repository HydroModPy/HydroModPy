from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.solver.boussinesq.assembly import assemble_steady_residual
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


def test_boussinesq_extractor_writes_cellwise_interfaces_and_volumetric_budgets(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    state_payload = {
        "head_history_m": np.asarray([[5.0, 6.0], [5.5, 6.5]], dtype=float),
        "snapshot_elapsed_seconds": np.asarray([0.0, 86400.0], dtype=float),
        "recharge_rate_history_m_s": np.asarray(
            [[1.0e-8, 2.0e-8], [3.0e-8, 4.0e-8]],
            dtype=float,
        ),
        "drainage_flux_history_m3_s": np.asarray([[0.1, 0.2], [0.3, 0.4]], dtype=float),
        "well_flux_history_m3_s": np.asarray([[-0.01, 0.0], [-0.02, 0.01]], dtype=float),
        "saturation_excess_history_m_s": np.asarray(
            [[1.0e-9, 0.0], [0.0, 2.0e-9]],
            dtype=float,
        ),
        "z_top_m": np.asarray([10.0, 12.0], dtype=float),
        "z_bottom_m": np.asarray([0.0, 1.0], dtype=float),
        "cell_area_m2": np.asarray([100.0, 200.0], dtype=float),
    }
    np.savez(output_dir / "_boussinesq_state_history.npz", **state_payload)
    (output_dir / "_boussinesq_summary.json").write_text(
        json.dumps(
            {
                "z_top_m": [10.0, 12.0],
                "z_bottom_m": [0.0, 1.0],
            }
        ),
        encoding="utf-8",
    )

    catalog = SimulationCatalog(tmp_path / "workspace")
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
        BoussinesqOutputAdapter().extract(sim_id, output_dir, catalog)
        zarr_store = catalog.open_zarr(sim_id)
        try:
            mesh = zarr_store.root["mesh"]
            np.testing.assert_allclose(mesh["surface_top"][:], np.asarray([10.0, 12.0]))
            np.testing.assert_allclose(
                mesh["z_interfaces"][:],
                np.asarray([[10.0, 12.0], [0.0, 1.0]], dtype=float),
            )
            budget = zarr_store.root["budget"]
            np.testing.assert_allclose(
                budget["recharge"][0],
                np.asarray([1.0e-6, 4.0e-6], dtype=float),
            )
            np.testing.assert_allclose(
                budget["surface_excess"][1],
                np.asarray([0.0, 4.0e-7], dtype=float),
            )
        finally:
            zarr_store.close()
    finally:
        catalog.close()


def test_boussinesq_extractor_raises_on_invalid_surface_metadata(tmp_path: Path) -> None:
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    np.savez(
        output_dir / "_boussinesq_state_history.npz",
        head_history_m=np.asarray([[5.0, 6.0]], dtype=float),
        snapshot_elapsed_seconds=np.asarray([0.0], dtype=float),
    )
    (output_dir / "_boussinesq_summary.json").write_text("{invalid", encoding="utf-8")

    catalog = SimulationCatalog(tmp_path / "workspace")
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


def test_boussinesq_derive_propagates_derived_failures(monkeypatch) -> None:
    from hydromodpy.simulation.extraction.extractors import derived as derived_module

    def fail_compute_derived(_sim_id: str, _store: object, _config: dict) -> None:
        raise RuntimeError("derived failed")

    monkeypatch.setattr(derived_module, "compute_derived", fail_compute_derived)

    with pytest.raises(RuntimeError, match="derived failed"):
        BoussinesqOutputAdapter().derive("sim-1", object(), {"seepage_areas": True})
