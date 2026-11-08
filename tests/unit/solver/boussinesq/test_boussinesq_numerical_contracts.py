from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.budget.terms import BudgetKeep, kept_budget
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.solver.boussinesq.assembly import assemble_steady_residual
from hydromodpy.solver.boussinesq.extractors import flow as flow_extractor
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from tests._helpers.boussinesq_cell_meshes import placeholder_cell_mesh
from tests._helpers.run_stores import claim_run, facts_of

from ._solver_runs import extract_run


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
        cell_mesh=placeholder_cell_mesh(2),
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
        "storage_coefficient": np.asarray([0.1, 0.1], dtype=float),
    }
    np.savez(output_dir / "_boussinesq_state_history.npz", **state_payload)
    (output_dir / "_boussinesq_summary.json").write_text(
        json.dumps({"z_top_m": [10.0, 12.0], "z_bottom_m": [0.0, 1.0]}),
        encoding="utf-8",
    )


def _open_store(tmp_path: Path, n_timesteps: int) -> RunStore:
    """Open the store of a fresh two-cell Boussinesq run; fields kept exact."""
    project = tmp_path / "project"
    claim = claim_run(project, "bouss")
    store = RunStore.open(
        claim.run_dir,
        facts=facts_of(
            claim,
            project=project.name,
            solver="boussinesq",
            n_cells=2,
            n_layers=1,
            n_timesteps=n_timesteps,
        ),
        # Exact precision: this checks the extractor numbers, not the storage rounding.
        persistence=PersistenceConfig(field_precision="exact"),
        workspace=project,
    )
    store.create_zarr(n_cells=2, n_layers=1)
    return store


def _extract_transient(tmp_path: Path, *, budget: BudgetKeep | None = None) -> tuple[RunStore, str]:
    output_dir = tmp_path / "solver"
    _write_transient_payload(output_dir)
    store = _open_store(tmp_path, n_timesteps=2)
    try:
        extract_run(store, output_dir, budget=budget)
    except BaseException:
        store.close()
        raise
    return store, store.sim_id


_ALL_COMPONENTS = ["constant_head", "drain", "recharge", "storage", "surface_excess", "well"]


def test_boussinesq_extractor_writes_cellwise_interfaces_and_volumetric_budgets(
    tmp_path: Path,
) -> None:
    store, sim_id = _extract_transient(tmp_path)
    try:
        zarr_store = store.open_zarr(sim_id)
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
            # Every term carries its one layer, as on every solver. A flux at the land
            # surface has none.
            np.testing.assert_allclose(
                budget["recharge"][0],
                np.asarray([[1.0e-6, 4.0e-6]], dtype=float),
            )
            np.testing.assert_allclose(
                budget["surface_excess"][:],
                np.asarray([[-1.0e-7, 0.0], [0.0, -4.0e-7]], dtype=float),
            )
            # Positive into the aquifer, as the registry and MODFLOW sign it.
            np.testing.assert_allclose(
                budget["constant_head"][:],
                np.asarray([[[-0.05, 0.0]], [[0.02, 0.0]]], dtype=float),
            )
            # The heads rise, so the water goes into storage: area * Sy * dh / dt.
            np.testing.assert_allclose(
                budget["storage"][:],
                np.asarray(
                    [
                        [[-100.0 * 0.1 * 0.5 / 86400.0, -200.0 * 0.1 * 0.5 / 86400.0]],
                        [[-100.0 * 0.1 * 0.2 / 86400.0, -200.0 * 0.1 * 0.2 / 86400.0]],
                    ],
                    dtype=float,
                ),
            )
            kept = kept_budget(zarr_store.root)
            assert kept is not None
            assert kept.policy == "all"
            assert list(kept.terms) == _ALL_COMPONENTS
            # The seepage mask is rebuilt on read from budget/surface_excess.
            derived = zarr_store.root.get("derived")
            assert derived is None or not {"seepage_mask", "seepage_rate"} & set(derived)
            # The extractor stores no descent: a reader rebuilds D from the stored top.
            assert "descent_receiver" not in mesh
        finally:
            zarr_store.close()
    finally:
        store.close()


def test_boussinesq_extractor_keeps_only_the_planned_terms(tmp_path: Path) -> None:
    """The consumers policy writes the planned terms and records them, produced or not."""
    keep = BudgetKeep.of_terms({"surface_excess", "drain", "stream"})
    store, sim_id = _extract_transient(tmp_path, budget=keep)
    try:
        zarr_store = store.open_zarr(sim_id)
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
        table = store.read_table("budgets")
        assert sorted(set(table["component"])) == _ALL_COMPONENTS
    finally:
        store.close()


def test_boussinesq_extractor_declares_an_empty_budget_group(tmp_path: Path) -> None:
    """A run that keeps no per-cell term still says so on the budget group."""
    store, sim_id = _extract_transient(tmp_path, budget=BudgetKeep.of_terms(()))
    try:
        zarr_store = store.open_zarr(sim_id)
        try:
            assert "head" in zarr_store.root
            assert list(zarr_store.root["budget"].array_keys()) == []
            assert kept_budget(zarr_store.root) == ("consumers", ())
        finally:
            zarr_store.close()
    finally:
        store.close()


def test_boussinesq_extractor_raises_on_invalid_surface_metadata(tmp_path: Path) -> None:
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    np.savez(
        output_dir / "_boussinesq_state_history.npz",
        head_history_m=np.asarray([[5.0, 6.0]], dtype=float),
        snapshot_elapsed_seconds=np.asarray([0.0], dtype=float),
    )
    (output_dir / "_boussinesq_summary.json").write_text("{invalid", encoding="utf-8")

    store = _open_store(tmp_path, n_timesteps=1)

    try:
        with pytest.raises(RuntimeError, match="Could not parse Boussinesq summary"):
            extract_run(store, output_dir)
    finally:
        store.close()


def test_extract_hands_the_diagnostics_of_the_run_to_the_diagnostics_folder_of_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[Path] = []
    for writer in ("write_vi_obstacle_diagnostic_files", "write_ts_vi_obstacle_diagnostic_files"):
        monkeypatch.setattr(
            flow_extractor, writer, lambda directory, summary: written.append(directory)
        )

    store, _ = _extract_transient(tmp_path)
    try:
        assert written == [store.solver_diagnostics_dir] * 2
    finally:
        store.close()
