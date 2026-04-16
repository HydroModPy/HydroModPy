"""High-level driver for the standalone Boussinesq flow backend.

This module does not assemble the nonlinear equations itself. Instead it:

- converts launcher and ``Flow`` objects into cell-wise NumPy arrays,
- delegates each nonlinear solve to a runtime backend,
- stores the accepted state in the shape expected by the rest of HydroModPy.

The easiest way to read the package is:

1. ``mesh.py`` for geometry and properties,
2. ``assembly.py`` for the residual,
3. ``local_runtime.py``, ``scipy_runtime.py`` or ``scipy_sparse_runtime.py``
   for the nonlinear solve,
4. this module for orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.process.flow.boundary_conditions import SIDE_DIRICHLET_BC_IDS
from hydromodpy.solver.boussinesq.assembly import (
    saturated_thickness_from_head,
)
from hydromodpy.solver.boussinesq.core.state import BoussinesqState
from hydromodpy.solver.boussinesq.driver_state import (
    TransientRuntimeHistory,
    build_steady_runtime_state,
    build_transient_activity_flags,
)
from hydromodpy.solver.boussinesq.export_payload import (
    build_state_history_export_payload,
    write_standard_postprocess_outputs,
)
from hydromodpy.solver.boussinesq.forcing_resolution import (
    BoussinesqForcingResolver,
)
from hydromodpy.solver.boussinesq.history_contract import (
    build_transient_time_axes,
)
from hydromodpy.solver.boussinesq.methods import (
    resolve_surface_interaction_model_token,
)
from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
    SteadySolveInputs,
    TransientStepInputs,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtime_selection import (
    BoussinesqRuntimeBackend,
    resolve_runtime_backend,
)
from hydromodpy.solver.prototype.solver import Solver
# Test hook kept here while forcing resolution is delegated to the dedicated
# helper module.
from hydromodpy.solver.utils.mesh.gmsh_grid import load_planar_mesh
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
)

_SUPPORTED_BC_IDS = frozenset(set(SIDE_DIRICHLET_BC_IDS) | {"stream", "ocean", "drainage"})
_SUPPORTED_SINK_SOURCE_IDS = frozenset({"recharge", "wells"})
_DEFAULT_SATURATION_EXCESS_REGULARIZATION = 0.05
_SECONDS_PER_DAY = 86_400.0
_SURFACE_THRESHOLD_ACTIVE_RATE_EPS_M_S = 1.0e-12


@dataclass(frozen=True)
class BoussinesqSolverContract:
    """Explicit mapping from `Flow` process settings to one Boussinesq solve path.

    This makes the same idea as the MODFLOW adapters visible in one place:
    process-level choices (`flow_regime`, `runtime_backend`,
    `surface_interaction_model`) are first normalized, then mapped to one
    method family and one execution engine.
    """

    flow_regime: str
    runtime_backend_requested: str
    surface_interaction_model_requested: str
    surface_interaction_model_resolved: str
    runtime_backend: BoussinesqRuntimeBackend


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
        self.saturation_excess_regularization_radius = (
            _DEFAULT_SATURATION_EXCESS_REGULARIZATION
        )
        configured_regularization_radius = getattr(
            flow,
            "saturation_excess_regularization_radius",
            None,
        )
        if configured_regularization_radius is not None:
            self.saturation_excess_regularization_radius = float(
                configured_regularization_radius
            )

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
        method still keeps the shared solver signature so the wider launcher layer can
        treat it like any other solver.
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
            self.has_numerical_solution = bool(success)
            self.solve_stage = "solved" if success else "failed"
            return bool(success)
        if self.time_grid is None:
            return True

        success = self._run_transient_runtime()
        self.has_numerical_solution = bool(success)
        self.solve_stage = "solved" if success else "failed"
        return bool(success)

    def post_processing(self, *args, **kwargs):
        """Persist lightweight diagnostics and state histories for inspection.

        The exported files are intentionally simple:

        - one ``npz`` history for arrays useful in validation,
        - one JSON summary explaining what was solved and how it converged,
        - a minimal ``_postprocess`` directory compatible with existing helpers.
        """
        _ = args
        _ = kwargs
        if self.state is not None:
            self._write_standard_postprocess_outputs()
            state_history_path = self.full_path / "_boussinesq_state_history.npz"
            np.savez(state_history_path, **self._build_state_history_export_payload())
            self._record_surface_threshold_summary()

        summary_payload = dict(self.runtime_summary)
        summary_payload["model_name"] = self.model_name
        summary_payload["has_numerical_solution"] = bool(self.has_numerical_solution)
        summary_payload["solve_stage"] = str(self.solve_stage)
        if self.state is not None:
            summary_payload["period_lengths_seconds"] = list(
                self.state.period_lengths_seconds
            )
            summary_payload["nonlinear_iterations"] = list(
                self.state.nonlinear_iterations
            )
            summary_payload["converged_by_period"] = list(self.state.converged_by_period)
        summary_path = self.full_path / "_boussinesq_summary.json"
        summary_path.write_text(
            json.dumps(summary_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        self.solve_stage = "post_processed"

    def _write_standard_postprocess_outputs(self) -> None:
        """Export the canonical ``_postprocess`` arrays expected by validation helpers.

        This small export adapter lets existing plotting and validation
        utilities consume Boussinesq results without a dedicated downstream path.
        """
        if self.state is None or self.mesh is None:
            return
        write_standard_postprocess_outputs(
            full_path=self.full_path,
            mesh=self.mesh,
            state=self.state,
        )

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

        n_snapshots = min(head_history.shape[0], saturation_excess_history.shape[0])
        head_history = np.asarray(head_history[:n_snapshots], dtype=float)
        saturation_excess_history = np.asarray(
            saturation_excess_history[:n_snapshots],
            dtype=float,
        )
        period_lengths = tuple(
            float(value)
            for value in (getattr(self.state, "period_lengths_seconds", ()) or ())
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
        positive_saturation_excess = np.maximum(saturation_excess_history, 0.0)
        active_mask = positive_saturation_excess > _SURFACE_THRESHOLD_ACTIVE_RATE_EPS_M_S
        active_counts = np.sum(active_mask, axis=1, dtype=int)
        active_any_by_snapshot = active_counts > 0
        activation_transitions = int(
            np.count_nonzero(
                active_any_by_snapshot
                & np.concatenate(([True], ~active_any_by_snapshot[:-1]))
            )
        )
        deactivation_transitions = int(
            np.count_nonzero(
                (~active_any_by_snapshot)
                & np.concatenate(([False], active_any_by_snapshot[:-1]))
            )
        )
        state_transitions = int(
            np.count_nonzero(
                active_any_by_snapshot[1:] != active_any_by_snapshot[:-1]
            )
        )
        total_surface_flux_m3_day = (
            np.sum(
                positive_saturation_excess * np.asarray(self.mesh.cell_area_m2, dtype=float)[None, :],
                axis=1,
            )
            * _SECONDS_PER_DAY
        )
        peak_active_cells = int(np.max(active_counts)) if active_counts.size else 0
        final_active_cells = int(active_counts[-1]) if active_counts.size else 0
        peak_head_above_top_m = float(
            np.max(evaluated_head_history - z_top)
            if evaluated_head_history.size
            else 0.0
        )
        active_indices = np.flatnonzero(active_counts > 0)
        first_active_index = (
            int(active_indices[0]) if active_indices.size else None
        )

        self.runtime_summary["surface_threshold_active_rate_eps_m_s"] = float(
            _SURFACE_THRESHOLD_ACTIVE_RATE_EPS_M_S
        )
        self.runtime_summary["surface_threshold_active_any"] = bool(
            active_indices.size > 0
        )
        self.runtime_summary["surface_threshold_available_snapshots"] = int(
            n_snapshots
        )
        self.runtime_summary["surface_threshold_evaluated_snapshots"] = int(
            evaluated_head_history.shape[0]
        )
        self.runtime_summary["surface_threshold_last_snapshot_day"] = float(
            elapsed_days[-1] if elapsed_days.size else 0.0
        )
        self.runtime_summary["surface_threshold_first_active_step"] = first_active_index
        self.runtime_summary["surface_threshold_first_active_day"] = (
            None
            if first_active_index is None
            else float(elapsed_days[first_active_index])
        )
        self.runtime_summary["surface_threshold_active_steps"] = int(
            np.count_nonzero(active_any_by_snapshot)
        )
        self.runtime_summary["surface_threshold_activation_windows"] = int(
            activation_transitions
        )
        self.runtime_summary["surface_threshold_deactivation_windows"] = int(
            deactivation_transitions
        )
        self.runtime_summary["surface_threshold_state_transitions"] = int(
            state_transitions
        )
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
        self.runtime_summary["surface_threshold_peak_head_above_top_m"] = (
            peak_head_above_top_m
        )
        self.runtime_summary["surface_threshold_any_head_above_top"] = bool(
            peak_head_above_top_m > 0.0
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
        snapshot_elapsed_seconds = build_transient_time_axes(
            self.state.period_lengths_seconds
        ).snapshot_elapsed_seconds
        used_snapshots = min(snapshot_elapsed_seconds.size, count)
        if used_snapshots > 0:
            elapsed_days[:used_snapshots] = (
                snapshot_elapsed_seconds[:used_snapshots] / _SECONDS_PER_DAY
            )
            if used_snapshots < count:
                elapsed_days[used_snapshots:] = elapsed_days[used_snapshots - 1]
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
        """Fail fast when the requested problem exceeds the implemented slice.

        The current backend intentionally supports a narrow, explicit subset of
        HydroModPy flow features. Rejecting unsupported cases early is less
        dangerous than silently ignoring a forcing or boundary condition.
        """
        active_bc = tuple(getattr(self.flow, "active_bc", ()) or ())
        active_sinks_sources = tuple(
            getattr(self.flow, "active_sinks_sources", ()) or ()
        )
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
            unsupported.append(
                "active_sinks_sources=" + ",".join(unsupported_sinks_sources)
            )

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
        return str(getattr(self.flow, "runtime_backend", "local") or "local").strip().lower() or "local"

    def _resolve_flow_regime(self) -> str:
        """Return the normalized flow regime expected by the Boussinesq driver."""
        flow_regime = getattr(self.flow, "flow_regime", None)
        if flow_regime is None:
            raise ValueError("flow.flow_regime must be 'steady' or 'transient'.")
        flow_regime_text = str(flow_regime).strip().lower()
        if flow_regime_text not in {"steady", "transient"}:
            raise ValueError("flow.flow_regime must be 'steady' or 'transient'.")
        return flow_regime_text

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

    def _resolve_solver_contract(self) -> BoussinesqSolverContract:
        """Return the explicit solver contract derived from the current `Flow`.

        Levels made explicit:
        - process regime: steady / transient,
        - requested execution backend,
        - requested surface-interaction model,
        - resolved physical method,
        - resolved nonlinear execution engine.
        """
        runtime_backend_requested = self._runtime_backend_name()
        surface_requested = str(
            getattr(self.flow, "surface_interaction_model", "auto") or "auto"
        ).strip().lower() or "auto"
        surface_resolved = resolve_surface_interaction_model_token(
            runtime_backend_name=runtime_backend_requested,
            surface_interaction_model=surface_requested,
        )
        runtime_backend = resolve_runtime_backend(
            runtime_backend_requested,
            surface_interaction_model=surface_resolved,
        )
        return BoussinesqSolverContract(
            flow_regime=self._resolve_flow_regime(),
            runtime_backend_requested=runtime_backend_requested,
            surface_interaction_model_requested=surface_requested,
            surface_interaction_model_resolved=surface_resolved,
            runtime_backend=runtime_backend,
        )

    def _runtime_options(self) -> NonlinearRuntimeOptions:
        """Build backend-neutral nonlinear options for the selected runtime."""
        runtime_backend_name = self._resolve_solver_contract().runtime_backend_requested
        max_iterations = 20
        if runtime_backend_name == "scipy_sparse":
            # The sparse Newton backend converges reliably on the larger 2-D
            # validation meshes, but it can need a few extra nonlinear
            # iterations beyond the dense prototype defaults.
            max_iterations = 30
        runtime_max_iterations = getattr(self.flow, "runtime_max_iterations", None)
        if runtime_max_iterations is not None:
            max_iterations = int(runtime_max_iterations)
        tol_residual_inf = float(
            getattr(self.flow, "runtime_tol_residual_inf", 1.0e-9) or 1.0e-9
        )
        tol_state_update_inf = float(
            getattr(self.flow, "runtime_tol_state_update_inf", 1.0e-9) or 1.0e-9
        )
        return NonlinearRuntimeOptions(
            regularization_radius=float(
                self.saturation_excess_regularization_radius
            ),
            max_iterations=int(max_iterations),
            tol_residual_inf=tol_residual_inf,
            tol_state_update_inf=tol_state_update_inf,
        )

    def _record_runtime_backend_summary(
        self,
        contract: BoussinesqSolverContract,
    ) -> None:
        """Record which nonlinear strategy was used for this solve.

        These summary fields are meant for humans first: they help explain
        afterwards whether the run used the in-house Newton loop, SciPy root
        finding, dense Jacobians, and which convergence policy applied.
        """
        options = self._runtime_options()
        runtime_backend = contract.runtime_backend
        flow_regime = contract.flow_regime
        time_scheme = runtime_backend.method.time_scheme_for_regime(flow_regime)
        self.runtime_summary["runtime_backend"] = runtime_backend.name
        self.runtime_summary["runtime_engine"] = runtime_backend.name
        self.runtime_summary["runtime_engine_id"] = runtime_backend.engine_id
        self.runtime_summary["flow_regime"] = flow_regime
        self.runtime_summary["runtime_backend_requested"] = (
            contract.runtime_backend_requested
        )
        self.runtime_summary["surface_interaction_model_requested"] = (
            contract.surface_interaction_model_requested
        )
        self.runtime_summary["surface_interaction_model_resolved"] = (
            contract.surface_interaction_model_resolved
        )
        self.runtime_summary["runtime_solver_kind"] = (
            runtime_backend.nonlinear_solver_kind
        )
        self.runtime_summary["runtime_linear_system_layout"] = (
            runtime_backend.linear_system_layout
        )
        self.runtime_summary["runtime_jacobian_strategy"] = (
            runtime_backend.jacobian_strategy
        )
        self.runtime_summary["runtime_linear_solver"] = (
            runtime_backend.linear_solver_kind
        )
        self.runtime_summary["runtime_convergence_policy"] = (
            runtime_backend.convergence_policy
        )
        self.runtime_summary["runtime_iteration_counter"] = (
            runtime_backend.iteration_counter_label
        )
        self.runtime_summary["runtime_tol_residual_inf"] = float(
            options.tol_residual_inf
        )
        self.runtime_summary["runtime_tol_state_update_inf"] = float(
            options.tol_state_update_inf
        )
        self.runtime_summary["runtime_formulation"] = runtime_backend.method.id
        self.runtime_summary["runtime_unknown_layout"] = (
            runtime_backend.method.unknown_layout
        )
        self.runtime_summary["runtime_space_scheme"] = (
            runtime_backend.method.space_scheme_id
        )
        self.runtime_summary["runtime_time_scheme"] = time_scheme.id
        self.runtime_summary["runtime_problem_kind"] = time_scheme.problem_kind
        self.runtime_summary["runtime_method_description"] = (
            runtime_backend.method.description
        )

    def _run_transient_runtime(self) -> bool:
        """Advance the head state over all launcher stress periods.

        This method resolves every period-dependent forcing into numeric arrays,
        then loops over the stress periods and asks the selected runtime backend
        to solve one fully implicit step at a time.
        """
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before running the runtime.")
        if self.state is None:
            raise RuntimeError("Initial state must exist before time integration.")
        contract = self._resolve_solver_contract()
        runtime_backend = contract.runtime_backend
        self._record_runtime_backend_summary(contract)
        self._assert_runtime_mesh_size_supported(runtime_backend)

        period_lengths = tuple(
            float(value)
            for value in (getattr(self.time_grid, "period_lengths_seconds", ()) or ())
        )
        if not period_lengths:
            return True

        nper = len(period_lengths)
        # Resolve all time-varying forcings once so the per-period loop only
        # has to pass already normalized arrays to the backend.
        recharge_series_m_s = self._resolve_recharge_series(nper)
        well_flux_by_period_m3_s = self._resolve_well_flux_by_period(nper)
        ocean_series_m = self._resolve_ocean_series(nper)
        dirichlet_supports_by_period = self._resolved_dirichlet_supports_by_period(
            nper,
            ocean_series_m=ocean_series_m,
        )
        prescribed_heads_by_period = tuple(
            self._project_dirichlet_supports_to_cells(period_supports)
            for period_supports in dirichlet_supports_by_period
        )
        boundary_heads_by_period = tuple(
            self._project_dirichlet_supports_to_edges(period_supports)
            for period_supports in dirichlet_supports_by_period
        )
        ocean_supported_cell_masks = self._ocean_supported_cell_masks_by_period(
            ocean_series_m,
            nper=nper,
        )
        drainage_conductance_series_m2_s = self._resolve_drainage_conductance_series(
            nper
        )

        head_prev = np.asarray(self.state.head_m, dtype=float)
        history = TransientRuntimeHistory.initialize(
            mesh=self.mesh,
            head_m=head_prev,
            saturated_thickness_m=np.asarray(
                self.state.saturated_thickness_m,
                dtype=float,
            ),
        )
        nonlinear_iterations: list[int] = []
        converged_by_period: list[bool] = []
        last_residual_norm = 0.0

        for kper, dt_seconds in enumerate(period_lengths):
            ocean_supported_cell_mask = np.asarray(
                ocean_supported_cell_masks[kper],
                dtype=bool,
            )
            drainage_conductance: np.ndarray | float
            if (
                np.any(ocean_supported_cell_mask)
                and float(drainage_conductance_series_m2_s[kper]) != 0.0
            ):
                # Cells influenced by the ocean stage already have an imposed
                # head support; top drainage is disabled there to avoid
                # stacking two different release mechanisms on the same cells.
                drainage_conductance = np.full(
                    self.mesh.n_cells,
                    float(drainage_conductance_series_m2_s[kper]),
                    dtype=float,
                )
                drainage_conductance[np.asarray(ocean_supported_cell_mask, dtype=bool)] = 0.0
            else:
                drainage_conductance = float(drainage_conductance_series_m2_s[kper])
            step = runtime_backend.solve_transient_step(
                TransientStepInputs(
                    mesh=self.mesh,
                    head_prev_m=head_prev,
                    dt_seconds=float(dt_seconds),
                    head_initial_guess_m=head_prev,
                    recharge_rate_m_s=recharge_series_m_s[kper],
                    well_flux_m3_s=well_flux_by_period_m3_s[kper],
                    prescribed_head_m_by_cell=prescribed_heads_by_period[kper],
                    drainage_conductance_m2_s=drainage_conductance,
                    options=self._runtime_options(),
                )
            )
            nonlinear_iterations.append(int(step.iterations))
            converged_by_period.append(bool(step.converged))
            head_prev = np.asarray(step.head_m, dtype=float)
            last_residual_norm = float(step.residual_norm_inf)
            self.runtime_summary["last_termination_reason"] = str(
                step.termination_reason
            )
            history.append_step(
                mesh=self.mesh,
                head_m=head_prev,
                assembly=step.assembly,
                prescribed_head_m_by_cell=np.asarray(
                    prescribed_heads_by_period[kper],
                    dtype=float,
                ),
                boundary_head_m_by_edge=np.asarray(
                    boundary_heads_by_period[kper],
                    dtype=float,
                ),
            )
            if not step.converged:
                # Keep the partial state on failure so the caller can inspect
                # how far the solve got and what the last iterate looked like.
                self.state = history.build_runtime_state(
                    period_lengths_seconds=period_lengths,
                    nonlinear_iterations=tuple(nonlinear_iterations),
                    converged_by_period=tuple(converged_by_period),
                )
                self.runtime_summary["last_residual_norm_inf"] = last_residual_norm
                self.runtime_summary["n_periods"] = nper
                self.runtime_summary.update(
                    build_transient_activity_flags(
                        recharge_series_m_s=recharge_series_m_s,
                        well_flux_by_period_m3_s=well_flux_by_period_m3_s,
                        dirichlet_supports_by_period=dirichlet_supports_by_period,
                        prescribed_heads_by_period=prescribed_heads_by_period,
                        ocean_supported_cell_masks=ocean_supported_cell_masks,
                        drainage_conductance_series_m2_s=drainage_conductance_series_m2_s,
                    )
                )
                return False

        self.state = history.build_runtime_state(
            period_lengths_seconds=period_lengths,
            nonlinear_iterations=tuple(nonlinear_iterations),
            converged_by_period=tuple(converged_by_period),
        )
        self.runtime_summary["n_periods"] = nper
        self.runtime_summary["last_residual_norm_inf"] = last_residual_norm
        self.runtime_summary.update(
            build_transient_activity_flags(
                recharge_series_m_s=recharge_series_m_s,
                well_flux_by_period_m3_s=well_flux_by_period_m3_s,
                dirichlet_supports_by_period=dirichlet_supports_by_period,
                prescribed_heads_by_period=prescribed_heads_by_period,
                ocean_supported_cell_masks=ocean_supported_cell_masks,
                drainage_conductance_series_m2_s=drainage_conductance_series_m2_s,
            )
        )
        return True

    def _run_steady_runtime(self) -> bool:
        """Solve one steady nonlinear balance on the selected backend."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before running the runtime.")
        if self.state is None:
            raise RuntimeError("Initial state must exist before steady solve.")
        contract = self._resolve_solver_contract()
        runtime_backend = contract.runtime_backend
        self._record_runtime_backend_summary(contract)
        self._assert_runtime_mesh_size_supported(runtime_backend)

        recharge_rate_m_s = self._resolve_recharge_series(1)[0]
        well_flux_m3_s = np.asarray(
            self._resolve_well_flux_by_period(1)[0],
            dtype=float,
        )
        ocean_series_m = self._resolve_ocean_series(1)
        dirichlet_supports = self._resolved_dirichlet_supports_by_period(
            1,
            ocean_series_m=ocean_series_m,
        )[0]
        boundary_heads_by_edge = np.asarray(
            self._project_dirichlet_supports_to_edges(dirichlet_supports),
            dtype=float,
        )
        prescribed_head_m_by_cell = np.asarray(
            self._project_dirichlet_supports_to_cells(dirichlet_supports),
            dtype=float,
        )
        ocean_supported_cell_mask = np.asarray(
            self._ocean_supported_cell_masks_by_period(ocean_series_m, nper=1)[0],
            dtype=bool,
        )
        drainage_value = float(self._resolve_drainage_conductance_series(1)[0])
        if np.any(ocean_supported_cell_mask) and drainage_value != 0.0:
            # Same rule as in transient mode: an ocean-supported cell should not
            # also leak through the generic top-drainage operator.
            drainage_conductance: np.ndarray | float = np.full(
                self.mesh.n_cells,
                drainage_value,
                dtype=float,
            )
            drainage_conductance[np.asarray(ocean_supported_cell_mask, dtype=bool)] = 0.0
        else:
            drainage_conductance = drainage_value

        steady = runtime_backend.solve_steady_problem(
            SteadySolveInputs(
                mesh=self.mesh,
                head_initial_guess_m=np.asarray(self.state.head_m, dtype=float),
                recharge_rate_m_s=recharge_rate_m_s,
                well_flux_m3_s=well_flux_m3_s,
                prescribed_head_m_by_cell=prescribed_head_m_by_cell,
                drainage_conductance_m2_s=drainage_conductance,
                options=self._runtime_options(),
            )
        )
        self.state = build_steady_runtime_state(
            mesh=self.mesh,
            head_m=np.asarray(steady.head_m, dtype=float),
            assembly=steady.assembly,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            boundary_head_m_by_edge=boundary_heads_by_edge,
            nonlinear_iterations=int(steady.iterations),
            converged=bool(steady.converged),
        )
        self.runtime_summary["steady_mode"] = f"nonlinear_{runtime_backend.name}"
        self.runtime_summary["steady_residual_norm_inf"] = float(
            steady.residual_norm_inf
        )
        self.runtime_summary["steady_nonlinear_iterations"] = int(steady.iterations)
        self.runtime_summary["steady_termination_reason"] = str(
            steady.termination_reason
        )
        self.runtime_summary["active_recharge"] = self._has_active_recharge_payload(
            (recharge_rate_m_s,)
        )
        self.runtime_summary["active_wells"] = bool(np.any(well_flux_m3_s != 0.0))
        self.runtime_summary["active_prescribed_head_bc"] = bool(len(dirichlet_supports) > 0)
        self.runtime_summary["active_dirichlet_bc"] = bool(
            self.runtime_summary["active_prescribed_head_bc"]
        )
        self.runtime_summary["active_ocean"] = bool(np.any(ocean_supported_cell_mask))
        self.runtime_summary["active_drainage"] = bool(drainage_value != 0.0)
        return bool(steady.converged)

    def _build_initial_state(self) -> BoussinesqState:
        """Create the initial state from the ``Flow`` initial-condition contract."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before initializing the state.")
        head_m = self._resolve_initial_head_field()
        saturated_thickness_m = saturated_thickness_from_head(self.mesh, head_m)
        return BoussinesqState.initial(
            head_m=head_m,
            saturated_thickness_m=saturated_thickness_m,
        )

    def _build_state_history_export_payload(self) -> dict[str, np.ndarray]:
        """Return the canonical state-history export payload.

        `prescribed_*` is the canonical boundary-head representation and
        `boundary_edge_flux_*` is the canonical reconstructed edge diagnostic.
        """
        if self.state is None:
            raise RuntimeError("State must exist before exporting Boussinesq history.")
        return build_state_history_export_payload(self.state)

    def _assert_runtime_mesh_size_supported(
        self,
        runtime_backend: BoussinesqRuntimeBackend,
    ) -> None:
        """Fail fast when the selected runtime still relies on dense Jacobians.

        The current ``local`` and ``scipy`` backends still assemble dense
        semianalytic Jacobians. That is acceptable for validation meshes,
        but it should be rejected on larger production meshes.
        """
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

    def _forcing_resolver(self) -> BoussinesqForcingResolver:
        """Return the shared forcing/boundary resolver for this solver instance."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving forcings.")
        return BoussinesqForcingResolver(
            mesh=self.mesh,
            mesh_bundle=self.mesh_bundle,
            flow=self.flow,
            time_grid=self.time_grid,
            planar_mesh_loader=load_planar_mesh,
            support_metadata=getattr(self.mesh, "support_metadata", None),
        )

    def _resolve_initial_head_field(self) -> np.ndarray:
        """Resolve the canonical ``Flow`` initial condition into cell heads."""
        return self._forcing_resolver().resolve_initial_head_field()

    def _resolve_recharge_series(
        self,
        nper: int,
    ) -> tuple[float | np.ndarray, ...]:
        """Resolve one recharge payload per stress period.

        The returned per-period payload can be either:
        - one scalar homogeneous recharge rate, or
        - one cell-aligned array produced from a heterogeneous forcing source.
        """
        return self._forcing_resolver().resolve_recharge_series(nper)

    def _resolve_well_flux_by_period(self, nper: int) -> np.ndarray:
        """Resolve all localized well fluxes to one cell vector per period."""
        return self._forcing_resolver().resolve_well_flux_by_period(nper)

    def _resolved_dirichlet_supports_by_period(
        self,
        nper: int,
        *,
        ocean_series_m: np.ndarray | None = None,
    ):
        """Resolve all Dirichlet supports once, then reuse them across projections.

        Each returned item is one stress period payload made of
        ``ResolvedDirichletSupport`` records.
        """
        return self._forcing_resolver().resolved_dirichlet_supports_by_period(
            nper,
            ocean_series_m=ocean_series_m,
        )

    def _project_dirichlet_supports_to_edges(self, supports) -> np.ndarray:
        """Project resolved Dirichlet supports to the edge-support view."""
        return self._forcing_resolver().project_dirichlet_supports_to_edges(supports)

    def _project_dirichlet_supports_to_cells(self, supports) -> np.ndarray:
        """Project resolved Dirichlet supports to the canonical cell view."""
        return self._forcing_resolver().project_dirichlet_supports_to_cells(supports)

    def _resolve_ocean_series(self, nper: int) -> np.ndarray | None:
        """Resolve the ocean stage series when the ocean boundary is active."""
        return self._forcing_resolver().resolve_ocean_series(nper)

    def _ocean_supported_cell_masks_by_period(
        self,
        ocean_series_m: np.ndarray | None,
        *,
        nper: int,
    ) -> tuple[np.ndarray, ...]:
        """Return one ocean support mask per stress period."""
        return self._forcing_resolver().ocean_supported_cell_masks_by_period(
            ocean_series_m,
            nper=nper,
        )

    def _resolve_drainage_conductance_series(self, nper: int) -> np.ndarray:
        """Return one drainage conductance value per period."""
        return self._forcing_resolver().resolve_drainage_conductance_series(nper)

    @staticmethod
    def _has_active_recharge_payload(
        payloads_by_period: tuple[float | np.ndarray, ...],
    ) -> bool:
        """Return whether at least one recharge payload contains a non-zero value."""
        return BoussinesqForcingResolver.has_active_recharge_payload(
            payloads_by_period
        )


__all__ = ["Boussinesq", "BoussinesqState"]
