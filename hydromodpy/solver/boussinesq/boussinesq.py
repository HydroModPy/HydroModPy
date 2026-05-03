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
