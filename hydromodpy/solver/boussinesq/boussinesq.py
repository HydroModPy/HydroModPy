"""High-level driver for the standalone Boussinesq flow backend.

This module does not assemble the nonlinear equations itself. Instead it:

- builds the runtime mesh and initial state from launcher objects,
- delegates each nonlinear solve to a runtime backend,
- stores the accepted state in the shape expected by the rest of HydroModPy.

Forcing resolution lives in ``forcing_resolution.py`` and the per-regime
drivers live in ``drivers/``. Diagnostics emitted around the solve live in
``runtime_summary.py``. This file only contains the lifecycle facade.

The easiest way to read the package is:

1. ``mesh.py`` for geometry and properties,
2. ``assembly.py`` for the residual,
3. ``local_runtime.py``, ``scipy_runtime.py`` or ``scipy_sparse_runtime.py``
   for the nonlinear solve,
4. this module for orchestration.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.physics.flow.boundary_conditions import SIDE_DIRICHLET_BC_IDS
from hydromodpy.physics.flow.initial_conditions import FlowInitialConditions
from hydromodpy.solver.base.solver import Solver
from hydromodpy.solver.boussinesq.assembly import (
    saturated_thickness_from_head,
)
from hydromodpy.solver.boussinesq.core.state import BoussinesqState
from hydromodpy.solver.boussinesq.drivers import (
    run_steady_runtime,
    run_transient_runtime,
)
from hydromodpy.solver.boussinesq.export_payload import (
    build_state_history_export_payload,
)
from hydromodpy.solver.boussinesq.forcing_resolution import BoussinesqForcingResolver
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.methods import (
    resolve_surface_interaction_model_token,
)
from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
)
from hydromodpy.solver.boussinesq.runtime_selection import (
    BoussinesqRuntimeBackend,
    resolve_runtime_backend,
)
from hydromodpy.solver.boussinesq.runtime_summary import (
    record_surface_threshold_summary,
)
from hydromodpy.solver.boussinesq.solver_contract import (
    BoussinesqSolverContract,
    resolve_solver_contract,
)
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
)

_SUPPORTED_BC_IDS = frozenset(set(SIDE_DIRICHLET_BC_IDS) | {"stream", "ocean", "drainage"})
_SUPPORTED_SINK_SOURCE_IDS = frozenset({"recharge", "wells"})
_DEFAULT_SATURATION_EXCESS_REGULARIZATION = 0.05


class Boussinesq(Solver):
    """Boussinesq solver driver compatible with the HydroModPy solver contract.

    The class acts as a translator between high-level HydroModPy objects
    (`flow`, `time_grid`, `domain`, gmsh bundle) and the low-level residual
    assembly / nonlinear runtime APIs used inside this package.
    """

    def __init__(
        self,
        *,
        mesh_bundle: CatchmentMeshBundle | None,
        mesh: BoussinesqMesh | None = None,
        flow: object,
        domain: object,
        time_grid: object,
        model_folder: str | Path,
        model_name: str,
    ) -> None:
        if mesh_bundle is None and mesh is None:
            raise ValueError("Boussinesq requires either mesh_bundle or a prebuilt mesh")
        self.mesh_bundle = mesh_bundle
        self.flow = flow
        self.domain = domain
        self.time_grid = time_grid
        self.model_folder = Path(model_folder)
        self.model_name = str(model_name).strip() or "boussinesq"
        self.full_path = self.model_folder / self.model_name
        self.mesh: BoussinesqMesh | None = mesh
        self.state: BoussinesqState | None = None
        self.runtime_summary: dict[str, Any] = {}
        self.has_numerical_solution = False
        self.solve_stage = "created"
        self.saturation_excess_regularization_radius = _DEFAULT_SATURATION_EXCESS_REGULARIZATION

    def pre_processing(self):
        """Build the compact solver mesh and initialize static run metadata."""
        self.full_path.mkdir(parents=True, exist_ok=True)
        if self.mesh is None:
            if self.mesh_bundle is None:
                raise ValueError(
                    "Boussinesq pre_processing requires mesh_bundle when no prebuilt mesh "
                    "was provided."
                )
            self.mesh = BoussinesqMesh.from_bundle(self.mesh_bundle)
        self.runtime_summary = {
            "n_cells": self.mesh.n_cells,
            "n_edges": self.mesh.n_edges,
            "n_nodes": self.mesh.n_nodes,
            "saturation_excess_regularization_radius": float(
                self.saturation_excess_regularization_radius
            ),
        }
        if self.mesh_bundle is not None:
            self.runtime_summary["bundle_dir"] = str(self.mesh.bundle_dir)
        else:
            self.runtime_summary["mesh_source_dir"] = str(self.mesh.bundle_dir)
        self.solve_stage = "pre_processed"

    def processing(self, write_model: bool = True, run_model: bool = False, **kwargs):
        """Initialize the state and optionally run the steady or transient solve.

        In contrast with file-based MODFLOW launchers, ``write_model`` is mostly
        irrelevant here because the Boussinesq backend runs in-process. The
        method still keeps the legacy signature so the wider launcher layer can
        treat it like any other solver.

        Diagnostic files (``_boussinesq_state_history.npz``,
        ``_boussinesq_summary.json``) are written here at the end of the run
        so the ``BoussinesqOutputAdapter`` can ingest them, mirroring the
        MODFLOW lifecycle where ``processing()`` is the only step that writes
        solver outputs to disk.
        """
        _ = write_model
        _ = kwargs
        if self.mesh is None:
            self.pre_processing()

        self.state = self._build_initial_state()
        self.has_numerical_solution = False
        self.solve_stage = "initialized"

        if not run_model:
            return True

        self._assert_supported_runtime_subset()
        if str(getattr(self.flow, "flow_regime", "transient")).strip().lower() == "steady":
            success = self._run_steady_runtime()
        elif self.time_grid is None:
            return True
        else:
            success = self._run_transient_runtime()

        self.has_numerical_solution = bool(success)
        self.solve_stage = "solved" if success else "failed"
        try:
            self.post_processing()
        except Exception as exc:
            self.solve_stage = "post_processing_failed"
            raise RuntimeError("Boussinesq post-processing failed") from exc
        return bool(success)

    def post_processing(self, *args, **kwargs):
        """Persist lightweight diagnostics and state histories for inspection."""
        _ = args
        _ = kwargs
        if self.state is not None:
            state_history_path = self.full_path / "_boussinesq_state_history.npz"
            state_payload = build_state_history_export_payload(self.state)
            if self.mesh is not None:
                state_payload["z_top_m"] = np.asarray(self.mesh.z_top_m, dtype=float)
                state_payload["z_bottom_m"] = np.asarray(self.mesh.z_bottom_m, dtype=float)
                state_payload["cell_area_m2"] = np.asarray(self.mesh.cell_area_m2, dtype=float)
            np.savez(
                state_history_path,
                **state_payload,
            )
            record_surface_threshold_summary(self)

        summary_payload = dict(self.runtime_summary)
        summary_payload["model_name"] = self.model_name
        summary_payload["has_numerical_solution"] = bool(self.has_numerical_solution)
        summary_payload["solve_stage"] = str(self.solve_stage)
        if self.mesh is not None and hasattr(self.mesh, "z_top_m"):
            summary_payload["z_top_m"] = np.asarray(self.mesh.z_top_m, dtype=float).tolist()
            summary_payload["z_bottom_m"] = np.asarray(self.mesh.z_bottom_m, dtype=float).tolist()
        if self.state is not None:
            summary_payload["period_lengths_seconds"] = list(self.state.period_lengths_seconds)
            summary_payload["nonlinear_iterations"] = list(self.state.nonlinear_iterations)
            summary_payload["converged_by_period"] = list(self.state.converged_by_period)
        summary_path = self.full_path / "_boussinesq_summary.json"
        summary_path.write_text(
            json.dumps(summary_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        self.solve_stage = "post_processed"

    def _record_surface_threshold_summary(self) -> None:
        """Record compact diagnostics about surface-threshold activation.

        These metrics are backend-agnostic and describe when/where the
        saturation-excess term becomes active. When the selected surface model
        is the mixed complementarity formulation, the same summary also records
        simple feasibility indicators on the ``(q_ex, z_top - h)`` pair.
        """
        if self.state is None or self.mesh is None:
            return

        n_cells = int(self.mesh.n_cells)
        head_history = self._history_or_current(
            self.state.head_history_m,
            self.state.head_m,
            n_columns=n_cells,
            default_value=0.0,
        )
        saturation_excess_history = self._history_or_current(
            self.state.saturation_excess_history_m_s,
            self.state.saturation_excess_rate_m_s,
            n_columns=n_cells,
            default_value=0.0,
        )
        dry_deficit_history = self._history_or_current(
            self.state.dry_deficit_history_m_s,
            self.state.dry_deficit_rate_m_s,
            n_columns=n_cells,
            default_value=0.0,
        )

        n_snapshots = min(
            head_history.shape[0],
            saturation_excess_history.shape[0],
            dry_deficit_history.shape[0],
        )
        head_history = np.asarray(head_history[:n_snapshots], dtype=float)
        saturation_excess_history = np.asarray(
            saturation_excess_history[:n_snapshots],
            dtype=float,
        )
        dry_deficit_history = np.asarray(dry_deficit_history[:n_snapshots], dtype=float)
        period_lengths = tuple(
            float(value) for value in (getattr(self.state, "period_lengths_seconds", ()) or ())
        )
        evaluation_start = 1 if (n_snapshots > 1 and len(period_lengths) > 0) else 0
        evaluated_head_history = np.asarray(
            head_history[evaluation_start:],
            dtype=float,
        )
        evaluated_saturation_excess_history = np.asarray(
            saturation_excess_history[evaluation_start:],
            dtype=float,
        )
        elapsed_days = self._elapsed_days_for_snapshots(n_snapshots=n_snapshots)
        z_top = np.asarray(self.mesh.z_top_m, dtype=float).reshape(1, -1)
        z_bottom = np.asarray(self.mesh.z_bottom_m, dtype=float).reshape(1, -1)
        cell_area = np.asarray(self.mesh.cell_area_m2, dtype=float)[None, :]
        positive_saturation_excess = np.maximum(saturation_excess_history, 0.0)
        positive_dry_deficit = np.maximum(dry_deficit_history, 0.0)
        active_mask = positive_saturation_excess > _SURFACE_THRESHOLD_ACTIVE_RATE_EPS_M_S
        active_counts = np.sum(active_mask, axis=1, dtype=int)
        dry_deficit_mask = positive_dry_deficit > _SURFACE_THRESHOLD_ACTIVE_RATE_EPS_M_S
        dry_deficit_counts = np.sum(dry_deficit_mask, axis=1, dtype=int)
        active_any_by_snapshot = active_counts > 0
        activation_transitions = int(
            np.count_nonzero(
                active_any_by_snapshot & np.concatenate(([True], ~active_any_by_snapshot[:-1]))
            )
        )
        deactivation_transitions = int(
            np.count_nonzero(
                (~active_any_by_snapshot) & np.concatenate(([False], active_any_by_snapshot[:-1]))
            )
        )
        state_transitions = int(
            np.count_nonzero(active_any_by_snapshot[1:] != active_any_by_snapshot[:-1])
        )
        total_surface_flux_m3_day = (
            np.sum(
                positive_saturation_excess * cell_area,
                axis=1,
            )
            * _SECONDS_PER_DAY
        )
        total_dry_deficit_m3_day = (
            np.sum(positive_dry_deficit * cell_area, axis=1) * _SECONDS_PER_DAY
        )
        used_dry_steps = min(len(period_lengths), max(positive_dry_deficit.shape[0] - 1, 0))
        integrated_dry_deficit_m3 = (
            float(
                np.sum(
                    positive_dry_deficit[1 : used_dry_steps + 1]
                    * cell_area
                    * np.asarray(period_lengths[:used_dry_steps], dtype=float).reshape(-1, 1)
                )
            )
            if used_dry_steps > 0
            else 0.0
        )
        peak_active_cells = int(np.max(active_counts)) if active_counts.size else 0
        final_active_cells = int(active_counts[-1]) if active_counts.size else 0
        peak_dry_deficit_cells = (
            int(np.max(dry_deficit_counts)) if dry_deficit_counts.size else 0
        )
        final_dry_deficit_cells = int(dry_deficit_counts[-1]) if dry_deficit_counts.size else 0
        peak_head_above_top_m = float(
            np.max(evaluated_head_history - z_top) if evaluated_head_history.size else 0.0
        )
        bottom_gap_history_m = evaluated_head_history - z_bottom
        bottom_violation_m = np.maximum(-bottom_gap_history_m, 0.0)
        bottom_violation_counts = np.sum(bottom_violation_m > 0.0, axis=1, dtype=int)
        negative_storage_volume_m3 = np.sum(
            np.asarray(self.mesh.cell_area_m2, dtype=float)[None, :]
            * np.asarray(self.mesh.storage_coefficient, dtype=float)[None, :]
            * bottom_violation_m,
            axis=1,
        )
        peak_bottom_violation_cells = (
            int(np.max(bottom_violation_counts)) if bottom_violation_counts.size else 0
        )
        final_bottom_violation_cells = (
            int(bottom_violation_counts[-1]) if bottom_violation_counts.size else 0
        )
        active_indices = np.flatnonzero(active_counts > 0)
        first_active_index = int(active_indices[0]) if active_indices.size else None

        self.runtime_summary["surface_threshold_active_rate_eps_m_s"] = float(
            _SURFACE_THRESHOLD_ACTIVE_RATE_EPS_M_S
        )
        self.runtime_summary["surface_threshold_active_any"] = bool(active_indices.size > 0)
        self.runtime_summary["surface_threshold_available_snapshots"] = int(n_snapshots)
        self.runtime_summary["surface_threshold_evaluated_snapshots"] = int(
            evaluated_head_history.shape[0]
        )
        self.runtime_summary["surface_threshold_last_snapshot_day"] = float(
            elapsed_days[-1] if elapsed_days.size else 0.0
        )
        self.runtime_summary["surface_threshold_first_active_step"] = first_active_index
        self.runtime_summary["surface_threshold_first_active_day"] = (
            None if first_active_index is None else float(elapsed_days[first_active_index])
        )
        self.runtime_summary["surface_threshold_active_steps"] = int(
            np.count_nonzero(active_any_by_snapshot)
        )
        self.runtime_summary["surface_threshold_activation_windows"] = int(activation_transitions)
        self.runtime_summary["surface_threshold_deactivation_windows"] = int(
            deactivation_transitions
        )
        self.runtime_summary["surface_threshold_state_transitions"] = int(state_transitions)
        self.runtime_summary["surface_threshold_peak_active_cells"] = peak_active_cells
        self.runtime_summary["surface_threshold_peak_active_fraction"] = float(
            peak_active_cells / max(n_cells, 1)
        )
        self.runtime_summary["surface_threshold_final_active_cells"] = final_active_cells
        self.runtime_summary["surface_threshold_final_active_fraction"] = float(
            final_active_cells / max(n_cells, 1)
        )
        self.runtime_summary["surface_threshold_peak_cell_rate_mm_day"] = float(
            np.max(positive_saturation_excess) * _SECONDS_PER_DAY * 1_000.0
        )
        self.runtime_summary["surface_threshold_peak_total_m3_day"] = float(
            np.max(total_surface_flux_m3_day) if total_surface_flux_m3_day.size else 0.0
        )
        self.runtime_summary["surface_threshold_final_total_m3_day"] = float(
            total_surface_flux_m3_day[-1] if total_surface_flux_m3_day.size else 0.0
        )
        self.runtime_summary["surface_threshold_peak_head_above_top_m"] = peak_head_above_top_m
        self.runtime_summary["surface_threshold_any_head_above_top"] = bool(
            peak_head_above_top_m > 0.0
        )
        self.runtime_summary["bottom_threshold_min_head_above_bottom_m"] = float(
            np.min(bottom_gap_history_m) if bottom_gap_history_m.size else 0.0
        )
        self.runtime_summary["bottom_threshold_peak_head_below_bottom_m"] = float(
            np.max(bottom_violation_m) if bottom_violation_m.size else 0.0
        )
        self.runtime_summary["bottom_threshold_any_head_below_bottom"] = bool(
            np.any(bottom_violation_m > 0.0)
        )
        self.runtime_summary["bottom_threshold_peak_violation_cells"] = (
            peak_bottom_violation_cells
        )
        self.runtime_summary["bottom_threshold_peak_violation_fraction"] = float(
            peak_bottom_violation_cells / max(n_cells, 1)
        )
        self.runtime_summary["bottom_threshold_final_violation_cells"] = (
            final_bottom_violation_cells
        )
        self.runtime_summary["bottom_threshold_final_violation_fraction"] = float(
            final_bottom_violation_cells / max(n_cells, 1)
        )
        self.runtime_summary["bottom_threshold_peak_negative_storage_volume_m3"] = float(
            np.max(negative_storage_volume_m3) if negative_storage_volume_m3.size else 0.0
        )
        self.runtime_summary["bottom_threshold_final_negative_storage_volume_m3"] = float(
            negative_storage_volume_m3[-1] if negative_storage_volume_m3.size else 0.0
        )
        self.runtime_summary["bottom_constraint_dry_deficit_active_any"] = bool(
            np.any(dry_deficit_counts > 0)
        )
        self.runtime_summary["bottom_constraint_peak_active_cells"] = peak_dry_deficit_cells
        self.runtime_summary["bottom_constraint_peak_active_fraction"] = float(
            peak_dry_deficit_cells / max(n_cells, 1)
        )
        self.runtime_summary["bottom_constraint_final_active_cells"] = final_dry_deficit_cells
        self.runtime_summary["bottom_constraint_final_active_fraction"] = float(
            final_dry_deficit_cells / max(n_cells, 1)
        )
        self.runtime_summary["bottom_constraint_peak_cell_rate_mm_day"] = float(
            np.max(positive_dry_deficit) * _SECONDS_PER_DAY * 1_000.0
        )
        self.runtime_summary["bottom_constraint_peak_total_m3_day"] = float(
            np.max(total_dry_deficit_m3_day) if total_dry_deficit_m3_day.size else 0.0
        )
        self.runtime_summary["bottom_constraint_final_total_m3_day"] = float(
            total_dry_deficit_m3_day[-1] if total_dry_deficit_m3_day.size else 0.0
        )
        self.runtime_summary["bottom_constraint_integrated_volume_m3"] = (
            integrated_dry_deficit_m3
        )

        if self._surface_interaction_model() != "complementarity":
            return

        top_gap_history_m = z_top - evaluated_head_history
        positive_gap = np.maximum(top_gap_history_m, 0.0)
        overlap = np.maximum(evaluated_saturation_excess_history, 0.0) * positive_gap
        self.runtime_summary["surface_complementarity_min_gap_m"] = float(
            np.min(top_gap_history_m) if top_gap_history_m.size else 0.0
        )
        self.runtime_summary["surface_complementarity_min_rate_m_s"] = float(
            np.min(evaluated_saturation_excess_history)
            if evaluated_saturation_excess_history.size
            else 0.0
        )
        self.runtime_summary["surface_complementarity_peak_overlap_m2_s"] = float(
            np.max(overlap) if overlap.size else 0.0
        )
        self.runtime_summary["surface_complementarity_final_overlap_m2_s"] = float(
            np.max(overlap[-1]) if overlap.size else 0.0
        )

    def _elapsed_days_for_snapshots(self, *, n_snapshots: int) -> np.ndarray:
        """Return one elapsed-time axis aligned with exported state snapshots."""
        count = max(int(n_snapshots), 1)
        elapsed_days = np.zeros(count, dtype=float)
        if self.state is None:
            return elapsed_days
        period_lengths_seconds = np.asarray(
            self.state.period_lengths_seconds,
            dtype=float,
        ).reshape(-1)
        used_periods = min(period_lengths_seconds.size, max(count - 1, 0))
        if used_periods > 0:
            elapsed_days[1 : used_periods + 1] = (
                np.cumsum(period_lengths_seconds[:used_periods], dtype=float) / _SECONDS_PER_DAY
            )
            if used_periods + 1 < count:
                elapsed_days[used_periods + 1 :] = elapsed_days[used_periods]
        return elapsed_days

    @staticmethod
    def _history_or_current(
        history_values: np.ndarray | None,
        current_values: np.ndarray | None,
        *,
        n_columns: int,
        default_value: float,
    ) -> np.ndarray:
        """Return one 2D history array from an optional history/current pair."""
        if history_values is not None:
            history = np.asarray(history_values, dtype=float)
            if history.ndim == 1:
                history = history.reshape(1, -1)
            if history.size != 0:
                return history
        if current_values is not None:
            current = np.asarray(current_values, dtype=float).reshape(1, -1)
            if current.size != 0:
                return current
        return np.full((1, int(n_columns)), float(default_value), dtype=float)

    def _assert_supported_runtime_subset(self) -> None:
        """Fail fast when the requested problem exceeds the implemented slice."""
        active_bc = tuple(getattr(self.flow, "active_bc", ()) or ())
        active_sinks_sources = tuple(getattr(self.flow, "active_sinks_sources", ()) or ())
        unsupported_bc = sorted(
            str(item) for item in active_bc if str(item) not in _SUPPORTED_BC_IDS
        )
        unsupported_sinks_sources = sorted(
            str(item)
            for item in active_sinks_sources
            if str(item) not in _SUPPORTED_SINK_SOURCE_IDS
        )
        unsupported: list[str] = []
        if unsupported_bc:
            unsupported.append("active_bc=" + ",".join(unsupported_bc))
        if unsupported_sinks_sources:
            unsupported.append("active_sinks_sources=" + ",".join(unsupported_sinks_sources))

        if unsupported:
            raise NotImplementedError(
                "The current boussinesq backend slice supports recharge, XY "
                "wells, side Dirichlet boundaries, stream, ocean, "
                "top drainage, and default no-flow on other outer edges. The "
                "following runtime features are not implemented yet: "
                + "; ".join(unsupported)
                + "."
            )

    def _runtime_backend_name(self) -> str:
        """Return the selected nonlinear runtime backend name."""
        return (
            str(getattr(self.flow, "runtime_backend", "local") or "local").strip().lower()
            or "local"
        )

    def _surface_interaction_model(self) -> str:
        """Return the selected groundwater/surface interaction closure."""
        return resolve_surface_interaction_model_token(
            runtime_backend_name=self._runtime_backend_name(),
            surface_interaction_model=getattr(
                self.flow,
                "surface_interaction_model",
                "auto",
            ),
        )

    def _runtime_backend(self) -> BoussinesqRuntimeBackend:
        """Resolve the selected nonlinear runtime backend implementation."""
        return resolve_runtime_backend(
            self._runtime_backend_name(),
            surface_interaction_model=self._surface_interaction_model(),
        )

    def _runtime_options(self) -> NonlinearRuntimeOptions:
        """Build backend-neutral nonlinear options for the selected runtime."""
        runtime_backend_name = self._runtime_backend_name()
        max_iterations = 20
        if runtime_backend_name == "scipy_sparse":
            max_iterations = 30
        runtime_max_iterations = getattr(self.flow, "runtime_max_iterations", None)
        if runtime_max_iterations is not None:
            max_iterations = int(runtime_max_iterations)
        tol_residual_inf = float(getattr(self.flow, "runtime_tol_residual_inf", 1.0e-9) or 1.0e-9)
        tol_state_update_inf = float(
            getattr(self.flow, "runtime_tol_state_update_inf", 1.0e-9) or 1.0e-9
        )
        return NonlinearRuntimeOptions(
            regularization_radius=float(self.saturation_excess_regularization_radius),
            max_iterations=int(max_iterations),
            tol_residual_inf=tol_residual_inf,
            tol_state_update_inf=tol_state_update_inf,
        )

    def _resolve_solver_contract(self) -> BoussinesqSolverContract:
        """Resolve the explicit solver contract from the current ``Flow``."""
        return resolve_solver_contract(self.flow)

    def _forcing_resolver(self) -> BoussinesqForcingResolver:
        """Build one forcing resolver bound to the current solver state."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving forcings.")
        return BoussinesqForcingResolver(
            mesh=self.mesh,
            flow=self.flow,
            time_grid=self.time_grid,
            mesh_bundle=self.mesh_bundle,
        )

    def _run_transient_runtime(self) -> bool:
        """Advance the head state over all launcher stress periods."""
        return run_transient_runtime(self)

    def _run_steady_runtime(self) -> bool:
        """Solve one steady nonlinear balance on the selected backend."""
        return run_steady_runtime(self)

    def _build_initial_state(self) -> BoussinesqState:
        """Create the initial state from the ``Flow`` initial-condition contract."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before initializing the state.")
        head_m = self._resolve_initial_head_field()
        saturated_thickness_m = saturated_thickness_from_head(self.mesh, head_m)
        return BoussinesqState(
            head_m=head_m,
            saturated_thickness_m=saturated_thickness_m,
        )

    def _assert_runtime_mesh_size_supported(
        self,
        runtime_backend: BoussinesqRuntimeBackend,
    ) -> None:
        """Fail fast when the selected runtime still relies on dense Jacobians."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before checking runtime limits.")
        if runtime_backend.linear_system_layout != "dense":
            return
        max_cells_dense = 400
        if self.mesh.n_cells > max_cells_dense:
            raise NotImplementedError(
                f"The current {runtime_backend.name} boussinesq runtime still "
                "assembles a dense Jacobian and is limited to "
                f"small meshes (<= {max_cells_dense} cells). "
                "Use a reduced test mesh for now. A future sparse Jacobian path "
                "should lift this limitation without changing the runtime contract."
            )

    def _resolve_initial_head_field(self) -> np.ndarray:
        """Resolve the canonical ``Flow`` initial condition into cell heads."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving initial heads.")

        initial_conditions = getattr(self.flow, "initial_conditions", None)
        if not isinstance(initial_conditions, FlowInitialConditions):
            raise TypeError(
                "Boussinesq expects flow.initial_conditions to be one "
                "FlowInitialConditions instance."
            )

        head_ic = initial_conditions.h
        ic_type = str(head_ic.type).strip().lower()
        if ic_type == "top":
            return np.asarray(self.mesh.z_top_m, dtype=float)
        if ic_type == "bottom":
            return np.asarray(self.mesh.z_bottom_m, dtype=float)
        if ic_type == "custom":
            if head_ic.value is None:
                raise ValueError("flow.ic.value is required when flow.ic.type='custom'.")
            head_magnitude = getattr(head_ic.value, "magnitude", head_ic.value)
            return np.full(self.mesh.n_cells, float(head_magnitude), dtype=float)
        raise ValueError(f"Unsupported flow.ic.type for boussinesq: '{head_ic.type}'.")

    def _boundary_conditions_mapping(self) -> Mapping[str, object]:
        """Return the boundary-condition mapping from the flow contract."""
        boundary_conditions = getattr(self.flow, "boundary_conditions", {})
        if not isinstance(boundary_conditions, Mapping):
            raise TypeError("flow.boundary_conditions must be a mapping")
        return boundary_conditions

    def _is_bc_active(self, bc_id: str) -> bool:
        """Return whether one boundary id is active in the current flow setup."""
        active = getattr(self.flow, "active_bc", ())
        return bc_id in active


__all__ = ["Boussinesq", "BoussinesqState"]
