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

from collections.abc import Mapping
from dataclasses import dataclass
import json
from numbers import Real
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.process.flow.boundary_conditions import SIDE_DIRICHLET_BC_IDS
from hydromodpy.process.flow.initial_conditions import FlowInitialConditions
from hydromodpy.solver.boussinesq.assembly import (
    internal_edge_flux_from_head,
    saturated_thickness_from_head,
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
from hydromodpy.solver.utils.mesh.gmsh_grid import load_planar_mesh
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.planar_forcing_discretization import (
    discretize_fields_on_planar_mesh,
    discretize_points_on_planar_mesh,
)
from hydromodpy.support.units.volumetric_flow import (
    convert_to_m3_per_s,
    normalize_m3_per_s_unit,
)

_SUPPORTED_BC_IDS = frozenset(set(SIDE_DIRICHLET_BC_IDS) | {"stream", "ocean", "drainage"})
_SUPPORTED_SINK_SOURCE_IDS = frozenset({"recharge", "wells"})
_DEFAULT_SATURATION_EXCESS_REGULARIZATION = 0.05


@dataclass
class BoussinesqState:
    """Normalized flow state carried by the Boussinesq runtime.

    The state stores both the current solution and, when available, the short
    histories needed by validation and post-processing helpers.
    """

    head_m: np.ndarray
    saturated_thickness_m: np.ndarray
    recharge_rate_m_s: np.ndarray | None = None
    well_flux_m3_s: np.ndarray | None = None
    saturation_excess_rate_m_s: np.ndarray | None = None
    head_history_m: np.ndarray | None = None
    saturated_thickness_history_m: np.ndarray | None = None
    saturation_excess_history_m_s: np.ndarray | None = None
    internal_edge_flux_m3_s: np.ndarray | None = None
    imposed_head_edge_flux_m3_s: np.ndarray | None = None
    drainage_flux_m3_s: np.ndarray | None = None
    period_lengths_seconds: tuple[float, ...] = ()
    nonlinear_iterations: tuple[int, ...] = ()
    converged_by_period: tuple[bool, ...] = ()


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
            np.savez(
                state_history_path,
                head_history_m=self._as_export_array(self.state.head_history_m),
                saturated_thickness_history_m=self._as_export_array(
                    self.state.saturated_thickness_history_m
                ),
                saturation_excess_history_m_s=self._as_export_array(
                    self.state.saturation_excess_history_m_s
                ),
                final_head_m=np.asarray(self.state.head_m, dtype=float),
                final_saturated_thickness_m=np.asarray(
                    self.state.saturated_thickness_m,
                    dtype=float,
                ),
                final_recharge_rate_m_s=self._as_export_array(
                    self.state.recharge_rate_m_s
                ),
                final_well_flux_m3_s=self._as_export_array(self.state.well_flux_m3_s),
                final_saturation_excess_rate_m_s=self._as_export_array(
                    self.state.saturation_excess_rate_m_s
                ),
                internal_edge_flux_m3_s=self._as_export_array(
                    self.state.internal_edge_flux_m3_s
                ),
                imposed_head_edge_flux_m3_s=self._as_export_array(
                    self.state.imposed_head_edge_flux_m3_s
                ),
                drainage_flux_m3_s=self._as_export_array(self.state.drainage_flux_m3_s),
                period_lengths_seconds=np.asarray(
                    self.state.period_lengths_seconds,
                    dtype=float,
                ),
            )

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

        This small compatibility layer lets existing plotting and validation
        utilities consume Boussinesq results without a dedicated code path.
        """
        if self.state is None or self.mesh is None:
            return

        postprocess_dir = self.full_path / "_postprocess"
        postprocess_dir.mkdir(parents=True, exist_ok=True)

        raw_head_history = self.state.head_history_m
        if raw_head_history is None:
            head_history = np.asarray(self.state.head_m, dtype=float).reshape(1, -1)
        else:
            head_history = np.asarray(raw_head_history, dtype=float)
            if head_history.ndim == 1:
                head_history = head_history.reshape(1, -1)
            if head_history.size == 0:
                head_history = np.asarray(self.state.head_m, dtype=float).reshape(1, -1)

        z_top = np.asarray(self.mesh.z_top_m, dtype=float).reshape(1, -1)
        watertable_elevation = {
            int(index): np.asarray(head_values, dtype=float)
            for index, head_values in enumerate(head_history)
        }
        watertable_depth = {
            int(index): np.maximum(z_top[0] - np.asarray(head_values, dtype=float), 0.0)
            for index, head_values in enumerate(head_history)
        }

        np.save(postprocess_dir / "watertable_elevation.npy", watertable_elevation)
        np.save(postprocess_dir / "watertable_depth.npy", watertable_depth)

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

    def _runtime_backend(self) -> BoussinesqRuntimeBackend:
        """Resolve the selected nonlinear runtime backend implementation."""
        return resolve_runtime_backend(self._runtime_backend_name())

    def _runtime_options(self) -> NonlinearRuntimeOptions:
        """Build backend-neutral nonlinear options for the selected runtime."""
        runtime_backend_name = self._runtime_backend_name()
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
        runtime_backend: BoussinesqRuntimeBackend,
    ) -> None:
        """Record which nonlinear strategy was used for this solve.

        These summary fields are meant for humans first: they help explain
        afterwards whether the run used the in-house Newton loop, SciPy root
        finding, dense Jacobians, and which convergence policy applied.
        """
        options = self._runtime_options()
        self.runtime_summary["runtime_backend"] = runtime_backend.name
        self.runtime_summary["runtime_solver_kind"] = (
            runtime_backend.nonlinear_solver_kind
        )
        self.runtime_summary["runtime_linear_system_layout"] = (
            runtime_backend.linear_system_layout
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
        runtime_backend = self._runtime_backend()
        self._record_runtime_backend_summary(runtime_backend)
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
        imposed_heads_by_period = self._resolve_imposed_head_by_period(
            nper,
            ocean_series_m=ocean_series_m,
        )
        ocean_supported_cell_masks = self._ocean_supported_cell_masks_by_period(
            ocean_series_m,
            nper=nper,
        )
        drainage_conductance_series_m2_s = self._resolve_drainage_conductance_series(
            nper
        )

        head_prev = np.asarray(self.state.head_m, dtype=float)
        head_history = [head_prev.copy()]
        thickness_history = [
            np.asarray(self.state.saturated_thickness_m, dtype=float).copy()
        ]
        saturation_excess_history = [
            np.zeros(self.mesh.n_cells, dtype=float)
        ]
        nonlinear_iterations: list[int] = []
        converged_by_period: list[bool] = []
        final_internal_flux = internal_edge_flux_from_head(self.mesh, head_prev)
        final_imposed_head_flux = np.zeros(self.mesh.n_edges, dtype=float)
        final_drainage_flux = np.zeros(self.mesh.n_cells, dtype=float)
        final_recharge_rate = np.zeros(self.mesh.n_cells, dtype=float)
        final_well_flux = np.zeros(self.mesh.n_cells, dtype=float)
        final_saturation_excess_rate = np.zeros(self.mesh.n_cells, dtype=float)
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
                    imposed_head_m_by_edge=imposed_heads_by_period[kper],
                    drainage_conductance_m2_s=drainage_conductance,
                    options=self._runtime_options(),
                )
            )
            nonlinear_iterations.append(int(step.iterations))
            converged_by_period.append(bool(step.converged))
            head_prev = np.asarray(step.head_m, dtype=float)
            final_internal_flux = np.asarray(
                step.assembly.internal_edge_flux_m3_s,
                dtype=float,
            )
            final_imposed_head_flux = np.asarray(
                step.assembly.imposed_head_edge_flux_m3_s,
                dtype=float,
            )
            final_drainage_flux = np.asarray(
                step.assembly.drainage_flux_m3_s,
                dtype=float,
            )
            final_recharge_rate = np.asarray(
                step.assembly.recharge_rate_m_s,
                dtype=float,
            )
            final_well_flux = np.asarray(step.assembly.well_flux_m3_s, dtype=float)
            final_saturation_excess_rate = np.asarray(
                step.assembly.saturation_excess_rate_m_s,
                dtype=float,
            )
            last_residual_norm = float(step.residual_norm_inf)
            self.runtime_summary["last_termination_reason"] = str(
                step.termination_reason
            )
            head_history.append(head_prev.copy())
            thickness_history.append(step.assembly.saturated_thickness_m.copy())
            saturation_excess_history.append(final_saturation_excess_rate.copy())
            if not step.converged:
                # Keep the partial state on failure so the caller can inspect
                # how far the solve got and what the last iterate looked like.
                self.state = BoussinesqState(
                    head_m=head_prev.copy(),
                    saturated_thickness_m=step.assembly.saturated_thickness_m.copy(),
                    recharge_rate_m_s=final_recharge_rate.copy(),
                    well_flux_m3_s=final_well_flux.copy(),
                    saturation_excess_rate_m_s=final_saturation_excess_rate.copy(),
                    head_history_m=np.vstack(head_history),
                    saturated_thickness_history_m=np.vstack(thickness_history),
                    saturation_excess_history_m_s=np.vstack(
                        saturation_excess_history
                    ),
                    internal_edge_flux_m3_s=final_internal_flux.copy(),
                    imposed_head_edge_flux_m3_s=final_imposed_head_flux.copy(),
                    drainage_flux_m3_s=final_drainage_flux.copy(),
                    period_lengths_seconds=period_lengths,
                    nonlinear_iterations=tuple(nonlinear_iterations),
                    converged_by_period=tuple(converged_by_period),
                )
                self.runtime_summary["last_residual_norm_inf"] = last_residual_norm
                self.runtime_summary["n_periods"] = nper
                self.runtime_summary["active_recharge"] = self._has_active_recharge_payload(
                    recharge_series_m_s
                )
                self.runtime_summary["active_wells"] = bool(
                    np.any(well_flux_by_period_m3_s != 0.0)
                )
                self.runtime_summary["active_imposed_head_bc"] = bool(
                    any(np.isfinite(values).any() for values in imposed_heads_by_period)
                )
                self.runtime_summary["active_ocean"] = bool(
                    any(np.any(mask) for mask in ocean_supported_cell_masks)
                )
                self.runtime_summary["active_drainage"] = bool(
                    np.any(drainage_conductance_series_m2_s != 0.0)
                )
                return False

        final_thickness = np.asarray(thickness_history[-1], dtype=float)
        self.state = BoussinesqState(
            head_m=head_prev.copy(),
            saturated_thickness_m=final_thickness.copy(),
            recharge_rate_m_s=final_recharge_rate.copy(),
            well_flux_m3_s=final_well_flux.copy(),
            saturation_excess_rate_m_s=final_saturation_excess_rate.copy(),
            head_history_m=np.vstack(head_history),
            saturated_thickness_history_m=np.vstack(thickness_history),
            saturation_excess_history_m_s=np.vstack(saturation_excess_history),
            internal_edge_flux_m3_s=final_internal_flux.copy(),
            imposed_head_edge_flux_m3_s=final_imposed_head_flux.copy(),
            drainage_flux_m3_s=final_drainage_flux.copy(),
            period_lengths_seconds=period_lengths,
            nonlinear_iterations=tuple(nonlinear_iterations),
            converged_by_period=tuple(converged_by_period),
        )
        self.runtime_summary["n_periods"] = nper
        self.runtime_summary["last_residual_norm_inf"] = last_residual_norm
        self.runtime_summary["active_recharge"] = self._has_active_recharge_payload(
            recharge_series_m_s
        )
        self.runtime_summary["active_wells"] = bool(
            np.any(well_flux_by_period_m3_s != 0.0)
        )
        self.runtime_summary["active_imposed_head_bc"] = bool(
            any(np.isfinite(values).any() for values in imposed_heads_by_period)
        )
        self.runtime_summary["active_ocean"] = bool(
            any(np.any(mask) for mask in ocean_supported_cell_masks)
        )
        self.runtime_summary["active_drainage"] = bool(
            np.any(drainage_conductance_series_m2_s != 0.0)
        )
        return True

    def _run_steady_runtime(self) -> bool:
        """Solve one steady nonlinear balance on the selected backend."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before running the runtime.")
        if self.state is None:
            raise RuntimeError("Initial state must exist before steady solve.")
        runtime_backend = self._runtime_backend()
        self._record_runtime_backend_summary(runtime_backend)
        self._assert_runtime_mesh_size_supported(runtime_backend)

        recharge_rate_m_s = self._resolve_recharge_series(1)[0]
        well_flux_m3_s = np.asarray(
            self._resolve_well_flux_by_period(1)[0],
            dtype=float,
        )
        ocean_series_m = self._resolve_ocean_series(1)
        imposed_head_m_by_edge = np.asarray(
            self._resolve_imposed_head_by_period(
                1,
                ocean_series_m=ocean_series_m,
            )[0],
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
                imposed_head_m_by_edge=imposed_head_m_by_edge,
                drainage_conductance_m2_s=drainage_conductance,
                options=self._runtime_options(),
            )
        )
        self.state = BoussinesqState(
            head_m=np.asarray(steady.head_m, dtype=float).copy(),
            saturated_thickness_m=np.asarray(
                steady.assembly.saturated_thickness_m,
                dtype=float,
            ).copy(),
            recharge_rate_m_s=np.asarray(
                steady.assembly.recharge_rate_m_s,
                dtype=float,
            ).copy(),
            well_flux_m3_s=np.asarray(
                steady.assembly.well_flux_m3_s,
                dtype=float,
            ).copy(),
            saturation_excess_rate_m_s=np.asarray(
                steady.assembly.saturation_excess_rate_m_s,
                dtype=float,
            ).copy(),
            head_history_m=np.asarray([steady.head_m], dtype=float),
            saturated_thickness_history_m=np.asarray(
                [steady.assembly.saturated_thickness_m],
                dtype=float,
            ),
            saturation_excess_history_m_s=np.asarray(
                [steady.assembly.saturation_excess_rate_m_s],
                dtype=float,
            ),
            internal_edge_flux_m3_s=np.asarray(
                steady.assembly.internal_edge_flux_m3_s,
                dtype=float,
            ).copy(),
            imposed_head_edge_flux_m3_s=np.asarray(
                steady.assembly.imposed_head_edge_flux_m3_s,
                dtype=float,
            ).copy(),
            drainage_flux_m3_s=np.asarray(
                steady.assembly.drainage_flux_m3_s,
                dtype=float,
            ).copy(),
            period_lengths_seconds=(),
            nonlinear_iterations=(int(steady.iterations),),
            converged_by_period=(bool(steady.converged),),
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
        self.runtime_summary["active_imposed_head_bc"] = bool(
            np.isfinite(imposed_head_m_by_edge).any()
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
        return BoussinesqState(
            head_m=head_m,
            saturated_thickness_m=saturated_thickness_m,
        )

    def _assert_runtime_mesh_size_supported(
        self,
        runtime_backend: BoussinesqRuntimeBackend,
    ) -> None:
        """Fail fast when the selected runtime still relies on dense Jacobians.

        The current ``local`` and ``scipy`` backends still assemble dense
        finite-difference Jacobians. That is acceptable for validation meshes,
        but it should be rejected on larger production meshes.
        """
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before checking runtime limits.")
        if runtime_backend.linear_system_layout != "dense":
            return
        max_cells_dense = 256
        if self.mesh.n_cells > max_cells_dense:
            raise NotImplementedError(
                f"The current {runtime_backend.name} boussinesq runtime still "
                "assembles a dense finite-difference Jacobian and is limited to "
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
                raise ValueError(
                    "flow.ic.value is required when flow.ic.type='custom'."
                )
            return np.full(self.mesh.n_cells, float(head_ic.value), dtype=float)
        raise ValueError(f"Unsupported flow.ic.type for boussinesq: '{head_ic.type}'.")

    def _resolve_recharge_series(
        self,
        nper: int,
    ) -> tuple[float | np.ndarray, ...]:
        """Resolve one recharge payload per stress period.

        The returned per-period payload can be either:
        - one scalar homogeneous recharge rate, or
        - one cell-aligned array produced from a heterogeneous forcing source.
        """
        active = tuple(getattr(self.flow, "active_sinks_sources", ()) or ())
        if "recharge" not in active:
            return tuple(0.0 for _ in range(int(nper)))

        recharge_cfg = self._recharge_config()
        if recharge_cfg is None:
            return tuple(0.0 for _ in range(int(nper)))

        heterogeneous_source = getattr(recharge_cfg, "heterogeneous_source", None)
        if heterogeneous_source is not None:
            return self._resolve_heterogeneous_recharge_series(
                heterogeneous_source=heterogeneous_source,
                nper=nper,
                first_clim=getattr(recharge_cfg, "first_clim", "mean"),
                interpolation_method=getattr(
                    recharge_cfg,
                    "interpolation_method",
                    "nearest",
                ),
            )

        series = self._recharge_period_series(
            payload=getattr(recharge_cfg, "values", 0.0),
            nper=int(nper),
            first_clim=getattr(recharge_cfg, "first_clim", "mean"),
            label="flow.sinks_sources.recharge.values",
        )
        return tuple(float(value) for value in np.asarray(series, dtype=float).tolist())

    def _resolve_heterogeneous_recharge_series(
        self,
        *,
        heterogeneous_source: object,
        nper: int,
        first_clim: object,
        interpolation_method: str,
    ) -> tuple[np.ndarray, ...]:
        """Discretize heterogeneous recharge onto the current Gmsh cell set."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving recharge.")
        solver_mesh = self._planar_mesh_for_forcing()

        simulation_window = (
            getattr(self.time_grid, "window", None)
            if self.time_grid is not None
            else None
        )
        if getattr(heterogeneous_source, "has_fields", False):
            raw_arrays = discretize_fields_on_planar_mesh(
                load_result=heterogeneous_source,
                planar_mesh=solver_mesh,
                nper=int(nper),
                simulation_window=simulation_window,
                method=str(interpolation_method),
            )
        elif getattr(heterogeneous_source, "has_points", False):
            raw_arrays = discretize_points_on_planar_mesh(
                load_result=heterogeneous_source,
                planar_mesh=solver_mesh,
                nper=int(nper),
                simulation_window=simulation_window,
                method=str(interpolation_method),
            )
        else:
            raw_arrays = {
                int(kper): np.zeros(self.mesh.n_cells, dtype=float)
                for kper in range(int(nper))
            }

        return self._apply_first_clim_to_cellwise_recharge(
            raw_arrays=raw_arrays,
            nper=int(nper),
            first_clim=first_clim,
        )

    def _planar_mesh_for_forcing(self):
        """Return the planar mesh used to discretize spatial forcings."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving forcings.")
        planar_mesh = getattr(self.mesh, "planar_mesh", None)
        if planar_mesh is not None:
            return planar_mesh
        if self.mesh_bundle is None:
            raise RuntimeError(
                "Spatial forcings require either one runtime planar mesh or one "
                "mesh bundle exposing mesh_path."
            )
        return load_planar_mesh(self.mesh_bundle.mesh_path)

    def _apply_first_clim_to_cellwise_recharge(
        self,
        *,
        raw_arrays: Mapping[int, np.ndarray],
        nper: int,
        first_clim: object,
    ) -> tuple[np.ndarray, ...]:
        """Apply the historical `first_clim` convention to cellwise recharge."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving recharge.")

        if nper <= 0:
            return ()

        arrays = {
            int(kper): np.asarray(values, dtype=float).reshape(-1)
            for kper, values in raw_arrays.items()
        }
        if not arrays:
            return tuple(np.zeros(self.mesh.n_cells, dtype=float) for _ in range(nper))

        stacked = np.stack(tuple(arrays.values()), axis=0)
        flow_regime = str(getattr(self.flow, "flow_regime", "transient")).strip().lower()
        if flow_regime == "steady" or nper <= 1:
            mean_array = np.nanmean(stacked, axis=0)
            return (np.asarray(mean_array, dtype=float).reshape(-1),)

        result = {
            kper: arrays.get(kper, np.zeros(self.mesh.n_cells, dtype=float)).copy()
            for kper in range(nper)
        }
        if first_clim == "mean":
            result[0] = np.nanmean(stacked, axis=0)
        elif first_clim == "first":
            pass
        elif self._is_scalar_number(first_clim):
            result[0] = np.full(self.mesh.n_cells, float(first_clim), dtype=float)
        else:
            raise ValueError(
                "flow.sinks_sources.recharge.first_clim must be 'mean', 'first', "
                "or a numeric value."
            )
        return tuple(
            np.asarray(result[kper], dtype=float).reshape(-1).copy()
            for kper in range(nper)
        )

    def _resolve_well_flux_by_period(self, nper: int) -> np.ndarray:
        """Resolve all localized well fluxes to one cell vector per period."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving wells.")
        active = tuple(getattr(self.flow, "active_sinks_sources", ()) or ())
        if "wells" not in active:
            return np.zeros((nper, self.mesh.n_cells), dtype=float)

        sinks_sources = getattr(self.flow, "sinks_sources", {})
        wells = sinks_sources.get("wells", {}) if isinstance(sinks_sources, Mapping) else {}
        if not isinstance(wells, Mapping) or not wells:
            return np.zeros((nper, self.mesh.n_cells), dtype=float)

        by_period = np.zeros((nper, self.mesh.n_cells), dtype=float)
        for well_id, well_cfg in wells.items():
            cell_index = self._resolve_well_cell_index(str(well_id), well_cfg)
            flux_series = self._resolve_well_flux_series(str(well_id), well_cfg, nper)
            by_period[:, cell_index] += flux_series
        return by_period

    def _resolve_imposed_head_by_period(
        self,
        nper: int,
        *,
        ocean_series_m: np.ndarray | None = None,
    ) -> tuple[np.ndarray, ...]:
        """Return one imposed-head edge vector per stress period.

        The result is a tuple of edge-aligned arrays. Each array contains
        ``NaN`` on edges without imposed head and a stage value on the edges
        controlled by side, stream or ocean boundary conditions.
        """
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving imposed-head BCs.")

        period_vectors = [
            np.full(self.mesh.n_edges, np.nan, dtype=float) for _ in range(nper)
        ]
        boundary_conditions = self._boundary_conditions_mapping()
        for bc_id in ("west_side", "east_side", "south_side", "north_side"):
            if not self._is_bc_active(bc_id):
                continue
            boundary = boundary_conditions.get(bc_id)
            if boundary is None:
                raise ValueError(f"Active boundary '{bc_id}' is missing from flow.bc.")
            boundary_type = str(getattr(boundary, "type", "dirichlet")).strip().lower()
            if boundary_type != "dirichlet":
                raise ValueError(
                    f"Boundary '{bc_id}' must be Dirichlet for the current "
                    "boussinesq backend slice."
                )
            edge_indices = self.mesh.boundary_edge_indices_for_side(bc_id)
            if edge_indices.size == 0:
                raise ValueError(
                    f"Boundary '{bc_id}' is active but no matching boundary edge was found."
                )
            series = self._boundary_value_series(
                boundary=boundary,
                bc_id=bc_id,
                nper=nper,
            )
            for kper, head_value in enumerate(series.tolist()):
                self._assign_imposed_head_edges(
                    period_vectors[kper],
                    edge_indices=edge_indices,
                    head_value_m=float(head_value),
                    label=f"flow.bc.{bc_id}",
                )

        if self._is_bc_active("stream"):
            boundary = boundary_conditions.get("stream")
            if boundary is None:
                raise ValueError("Active boundary 'stream' is missing from flow.bc.")
            boundary_type = str(getattr(boundary, "type", "dirichlet")).strip().lower()
            if boundary_type != "dirichlet":
                raise ValueError(
                    "Boundary 'stream' must be Dirichlet for the current "
                    "boussinesq backend slice."
                )
            edge_indices = self.mesh.river_edge_indices()
            if edge_indices.size == 0:
                raise ValueError(
                    "Boundary 'stream' is active but no edge is tagged is_river in the mesh bundle."
                )
            series = self._boundary_value_series(
                boundary=boundary,
                bc_id="stream",
                nper=nper,
            )
            for kper, head_value in enumerate(series.tolist()):
                self._assign_imposed_head_edges(
                    period_vectors[kper],
                    edge_indices=edge_indices,
                    head_value_m=float(head_value),
                    label="flow.bc.stream",
                )
        if ocean_series_m is not None and ocean_series_m.size > 0:
            # Ocean support depends on the stage itself because only coastal
            # cells below the stage are considered active.
            for kper, head_value in enumerate(np.asarray(ocean_series_m, dtype=float).tolist()):
                edge_indices = self._ocean_support_edge_indices(float(head_value))
                self._assign_imposed_head_edges(
                    period_vectors[kper],
                    edge_indices=edge_indices,
                    head_value_m=float(head_value),
                    label="flow.bc.ocean",
                )
        return tuple(period_vectors)

    def _resolve_ocean_series(self, nper: int) -> np.ndarray | None:
        """Resolve the ocean stage series when the ocean boundary is active."""
        if not self._is_bc_active("ocean"):
            return None
        boundary = self._boundary_conditions_mapping().get("ocean")
        if boundary is None:
            raise ValueError("Active boundary 'ocean' is missing from flow.bc.")
        boundary_type = str(getattr(boundary, "type", "dirichlet")).strip().lower()
        if boundary_type != "dirichlet":
            raise ValueError(
                "Boundary 'ocean' must be Dirichlet for the current "
                "boussinesq backend slice."
            )
        return self._boundary_value_series(boundary=boundary, bc_id="ocean", nper=nper)

    def _ocean_support_edge_indices(
        self,
        ocean_stage_m: float | np.ndarray | None,
    ) -> np.ndarray:
        """Return boundary edges influenced by the current ocean stage.

        The current heuristic is geometric: a boundary edge is ocean-supported
        when it is not a river edge and the top elevation of its owner cell lies
        below the current sea stage.
        """
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving the ocean support.")
        if ocean_stage_m is None or np.asarray(ocean_stage_m, dtype=float).size == 0:
            return np.asarray([], dtype=int)
        sea_threshold_m = float(np.max(np.asarray(ocean_stage_m, dtype=float)))
        boundary_mask = np.asarray(self.mesh.boundary_edge_mask, dtype=bool)
        non_river_mask = ~np.asarray(self.mesh.edge_is_river, dtype=bool)
        owner_cell_indices = np.asarray(self.mesh.edge_cell_a, dtype=int)
        coastal_mask = self.mesh.z_top_m[owner_cell_indices] <= sea_threshold_m
        return np.flatnonzero(boundary_mask & non_river_mask & coastal_mask).astype(
            int,
            copy=False,
        )

    def _ocean_supported_cell_mask(
        self,
        ocean_stage_m: float | np.ndarray | None,
    ) -> np.ndarray:
        """Return one boolean mask marking ocean-influenced cells."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving the ocean support.")
        mask = np.zeros(self.mesh.n_cells, dtype=bool)
        for edge_index in self._ocean_support_edge_indices(ocean_stage_m).tolist():
            mask[int(self.mesh.edge_cell_a[edge_index])] = True
        return mask

    def _ocean_supported_cell_masks_by_period(
        self,
        ocean_series_m: np.ndarray | None,
        *,
        nper: int,
    ) -> tuple[np.ndarray, ...]:
        """Return one ocean support mask per stress period."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving the ocean support.")
        if ocean_series_m is None or np.asarray(ocean_series_m, dtype=float).size == 0:
            return tuple(np.zeros(self.mesh.n_cells, dtype=bool) for _ in range(int(nper)))
        series = np.asarray(ocean_series_m, dtype=float).reshape(-1)
        if series.size != int(nper):
            raise ValueError(
                "ocean_series_m length must match nper when building support masks."
            )
        return tuple(
            self._ocean_supported_cell_mask(float(head_value))
            for head_value in series.tolist()
        )

    def _resolve_drainage_conductance_series(self, nper: int) -> np.ndarray:
        """Return one drainage conductance value per period."""
        if not self._is_bc_active("drainage"):
            return np.zeros(nper, dtype=float)

        boundary = self._boundary_conditions_mapping().get("drainage")
        if boundary is None:
            raise ValueError("Active boundary 'drainage' is missing from flow.bc.")
        boundary_type = str(getattr(boundary, "type", "cauchy")).strip().lower()
        if boundary_type not in {"cauchy", "robin"}:
            raise ValueError(
                "Boundary 'drainage' must be of type cauchy/robin for the "
                "current boussinesq backend slice."
            )
        return self._simple_period_series(
            getattr(boundary, "value", None),
            nper=nper,
            label="flow.bc.drainage.value",
        )

    def _resolve_well_cell_index(self, well_id: str, well_cfg: object) -> int:
        """Project one well location to one cell of the triangular mesh."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving wells.")

        layer = getattr(well_cfg, "layer", 0)
        if layer is not None and int(layer) != 0:
            raise NotImplementedError(
                f"Well '{well_id}' targets layer={int(layer)} but the current "
                "boussinesq backend is 2D and supports only layer 0."
            )

        cell_payload = getattr(well_cfg, "cell", None)
        location_mode = str(getattr(well_cfg, "location_mode", "") or "").strip().lower()
        if cell_payload is not None or location_mode in {"", "cell"}:
            raise NotImplementedError(
                f"Well '{well_id}' uses structured-grid cell addressing. "
                "The current boussinesq backend on gmsh triangles supports "
                "only coordinate-based wells (absolute_xy or relative_xy)."
            )

        if location_mode == "absolute_xy":
            x_m = float(getattr(well_cfg, "x"))
            y_m = float(getattr(well_cfg, "y"))
        elif location_mode == "relative_xy":
            x_rel = float(getattr(well_cfg, "x_rel"))
            y_rel = float(getattr(well_cfg, "y_rel"))
            x_m = self.mesh.x_min_m + x_rel * (self.mesh.x_max_m - self.mesh.x_min_m)
            y_m = self.mesh.y_min_m + y_rel * (self.mesh.y_max_m - self.mesh.y_min_m)
        else:
            raise ValueError(
                f"Unsupported well location mode for '{well_id}': {location_mode!r}."
            )
        return self.mesh.locate_cell_index_for_point(x_m, y_m, allow_nearest=True)

    def _resolve_well_flux_series(
        self,
        well_id: str,
        well_cfg: object,
        nper: int,
    ) -> np.ndarray:
        """Resolve one well rate to one value per period in m3/s.

        Both direct scalar/sequence payloads and time-forcing objects are
        accepted. Values are converted to canonical ``m3/s`` units here so the
        runtime only sees one unit system.
        """
        forcing = getattr(well_cfg, "forcing", None)
        if forcing is not None:
            from hydromodpy.process.flow.time_forcing import (
                resolve_period_values_from_forcing,
            )

            raw_values = resolve_period_values_from_forcing(
                forcing=forcing,
                simulation_window=getattr(self.time_grid, "window", None)
                if self.time_grid is not None
                else None,
                nper=int(nper),
                label=f"flow.sinks_sources.wells.{well_id}.forcing",
            )
            raw_units = getattr(forcing, "units", None) or getattr(well_cfg, "units", "m3/s")
            canonical_units = normalize_m3_per_s_unit(str(raw_units))
            return np.asarray(
                [
                    convert_to_m3_per_s(
                        value,
                        unit=canonical_units,
                        label=f"flow.sinks_sources.wells.{well_id}.forcing[{idx}]",
                    )
                    for idx, value in enumerate(raw_values)
                ],
                dtype=float,
            )
        return self._simple_period_series(
            getattr(well_cfg, "flux", None),
            nper=nper,
            label=f"flow.sinks_sources.wells.{well_id}.flux",
        )

    @staticmethod
    def _assign_imposed_head_edges(
        edge_values_m: np.ndarray,
        *,
        edge_indices: np.ndarray,
        head_value_m: float,
        label: str,
    ) -> None:
        """Assign one imposed head to a set of edges with overlap checks.

        Overlap is allowed only when the overlapping conditions prescribe the
        same value, which keeps corner cases deterministic.
        """
        candidate = float(head_value_m)
        for edge_index in np.asarray(edge_indices, dtype=int).tolist():
            previous = float(edge_values_m[edge_index])
            if np.isfinite(previous) and not np.isclose(
                previous,
                candidate,
                rtol=0.0,
                atol=1.0e-12,
            ):
                raise ValueError(
                    f"{label} overlaps another imposed-head BC on edge {edge_index} "
                    f"with conflicting values ({previous} vs {candidate})."
                )
            edge_values_m[edge_index] = candidate

    def _boundary_value_series(
        self,
        *,
        boundary: object,
        bc_id: str,
        nper: int,
    ) -> np.ndarray:
        """Resolve one boundary condition to one head value per period."""
        forcing = getattr(boundary, "forcing", None)
        if forcing is not None:
            from hydromodpy.process.flow.time_forcing import (
                resolve_period_values_from_forcing,
            )

            return np.asarray(
                resolve_period_values_from_forcing(
                    forcing=forcing,
                    simulation_window=getattr(self.time_grid, "window", None)
                    if self.time_grid is not None
                    else None,
                    nper=int(nper),
                    label=f"flow.bc.{bc_id}.forcing",
                ),
                dtype=float,
            )
        return self._simple_period_series(
            getattr(boundary, "value", None),
            nper=nper,
            label=f"flow.bc.{bc_id}.value",
        )

    def _recharge_period_series(
        self,
        *,
        payload: object,
        nper: int,
        first_clim: object,
        label: str,
    ) -> np.ndarray:
        """Resolve the canonical recharge payload to one value per period.

        Recharge is slightly special because the first stress period may use a
        climate aggregate (`mean`, `first` or an explicit value) while later
        periods map directly to the provided sequence.
        """
        if nper <= 0:
            return np.asarray([], dtype=float)
        if payload is None:
            return np.zeros(nper, dtype=float)
        if isinstance(payload, Mapping):
            series = np.zeros(nper, dtype=float)
            for raw_key, raw_value in payload.items():
                if isinstance(raw_key, bool) or not isinstance(raw_key, Real):
                    raise TypeError(f"{label} mapping keys must be integer period indices.")
                kper = int(raw_key)
                if float(raw_key) != float(kper):
                    raise TypeError(f"{label} mapping keys must be integer period indices.")
                if kper < 0 or kper >= int(nper):
                    raise ValueError(
                        f"{label} mapping key {kper} is outside [0, {int(nper) - 1}]."
                    )
                series[kper] = float(raw_value)
            return series
        if self._is_scalar_number(payload):
            return np.full(nper, float(payload), dtype=float)

        sequence = self._payload_to_sequence(payload, label=label)
        if sequence.size == 1:
            return np.full(nper, float(sequence[0]), dtype=float)
        if sequence.size < int(nper):
            raise ValueError(
                f"{label} length ({int(sequence.size)}) must be 1 or at least nper ({int(nper)})."
            )

        # Period 0 follows the historical "first_clim" convention used by the
        # Flow contract, while later periods use the explicit sequence values.
        series = np.zeros(nper, dtype=float)
        if first_clim == "mean":
            series[0] = float(np.nanmean(sequence))
        elif first_clim == "first":
            series[0] = float(sequence[0])
        elif self._is_scalar_number(first_clim):
            series[0] = float(first_clim)
        else:
            raise ValueError(
                "flow.sinks_sources.recharge.first_clim must be 'mean', 'first', "
                "or a numeric value."
            )
        for kper in range(1, int(nper)):
            series[kper] = float(sequence[kper])
        return series

    @staticmethod
    def _simple_period_series(
        payload: object,
        *,
        nper: int,
        label: str,
    ) -> np.ndarray:
        """Resolve one scalar or explicit period sequence to length ``nper``."""
        if nper <= 0:
            return np.asarray([], dtype=float)
        if payload is None:
            raise ValueError(f"{label} is required.")
        if Boussinesq._is_scalar_number(payload):
            return np.full(nper, float(payload), dtype=float)
        sequence = Boussinesq._payload_to_sequence(payload, label=label)
        if sequence.size == 1:
            return np.full(nper, float(sequence[0]), dtype=float)
        if sequence.size != int(nper):
            raise ValueError(
                f"{label} length ({int(sequence.size)}) must be 1 or match nper ({int(nper)})."
            )
        return sequence.astype(float, copy=False)

    @staticmethod
    def _payload_to_sequence(
        payload: object,
        *,
        label: str,
    ) -> np.ndarray:
        """Convert one runtime payload to a flat numeric sequence."""
        if hasattr(payload, "iloc"):
            size = len(payload)
            values = [payload.iloc[idx] for idx in range(size)]
            return np.asarray(values, dtype=float).reshape(-1)
        try:
            array = np.asarray(payload, dtype=float).reshape(-1)
        except Exception as exc:
            raise TypeError(
                f"{label} must be numeric or a sequence of numeric values."
            ) from exc
        if array.size == 0:
            raise ValueError(f"{label} cannot be empty.")
        return array.astype(float, copy=False)

    @staticmethod
    def _is_scalar_number(value: object) -> bool:
        """Return true for numeric scalars while excluding booleans."""
        return isinstance(value, Real) and not isinstance(value, bool)

    @staticmethod
    def _has_active_recharge_payload(
        payloads_by_period: tuple[float | np.ndarray, ...],
    ) -> bool:
        """Return whether at least one recharge payload contains a non-zero value."""
        return any(
            bool(np.any(np.asarray(payload, dtype=float) != 0.0))
            for payload in payloads_by_period
        )

    def _recharge_config(self) -> object | None:
        """Return the recharge config object when the flow contract provides one."""
        sinks_sources = getattr(self.flow, "sinks_sources", {})
        if not isinstance(sinks_sources, Mapping):
            return None
        return sinks_sources.get("recharge")

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

    @staticmethod
    def _as_export_array(values: np.ndarray | None) -> np.ndarray:
        """Normalize optional arrays before writing them to disk."""
        if values is None:
            return np.asarray([], dtype=float)
        return np.asarray(values, dtype=float)


__all__ = ["Boussinesq", "BoussinesqState"]
