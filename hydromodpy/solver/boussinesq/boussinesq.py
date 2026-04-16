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

import json
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    saturated_thickness_from_head,
)
from hydromodpy.solver.boussinesq.core.state import BoussinesqState
from hydromodpy.solver.boussinesq.driver_steady import run_steady_runtime
from hydromodpy.solver.boussinesq.driver_transient import run_transient_runtime
from hydromodpy.solver.boussinesq.export_payload import (
    build_state_history_export_payload,
    write_standard_postprocess_outputs,
)
from hydromodpy.solver.boussinesq.forcing_resolution import (
    BoussinesqForcingResolver,
)
from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtime_selection import (
    ResolvedBoussinesqRuntimeBackend,
)
from hydromodpy.solver.boussinesq.solver_contract import (
    BoussinesqSolverContract,
    assert_supported_runtime_subset,
    build_runtime_options,
    resolve_flow_regime,
    resolve_solver_contract,
    resolve_surface_interaction_model,
    runtime_backend_name,
)
from hydromodpy.solver.boussinesq.runtime_summary import (
    elapsed_days_for_snapshots,
    history_or_current,
    record_runtime_backend_summary,
    record_surface_threshold_summary,
)
from hydromodpy.solver.prototype.solver import Solver
# Test hook kept here while forcing resolution is delegated to the dedicated
# helper module.
from hydromodpy.solver.utils.mesh.gmsh_grid import load_planar_mesh
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
)

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
        """Record compact diagnostics about surface-threshold activation."""
        record_surface_threshold_summary(self)

    def _elapsed_days_for_snapshots(self, *, n_snapshots: int) -> np.ndarray:
        """Return one elapsed-time axis aligned with exported state snapshots."""
        return elapsed_days_for_snapshots(self.state, n_snapshots=n_snapshots)

    @staticmethod
    def _history_or_current(
        history_values: np.ndarray | None,
        current_values: np.ndarray | None,
        *,
        n_columns: int,
        default_value: float,
    ) -> np.ndarray:
        """Return one 2D history array from an optional history/current pair."""
        return history_or_current(
            history_values,
            current_values,
            n_columns=n_columns,
            default_value=default_value,
        )

    def _assert_supported_runtime_subset(self) -> None:
        """Fail fast when the requested problem exceeds the implemented slice.

        The current backend intentionally supports a narrow, explicit subset of
        HydroModPy flow features. Rejecting unsupported cases early is less
        dangerous than silently ignoring a forcing or boundary condition.
        """
        assert_supported_runtime_subset(self.flow)

    def _runtime_backend_name(self) -> str:
        """Return the selected nonlinear runtime backend name."""
        return runtime_backend_name(self.flow)

    def _resolve_flow_regime(self) -> str:
        """Return the normalized flow regime expected by the Boussinesq driver."""
        return resolve_flow_regime(self.flow)

    def _surface_interaction_model(self) -> str:
        """Return the selected groundwater/surface interaction closure."""
        return resolve_surface_interaction_model(self.flow)

    def _runtime_backend(self) -> ResolvedBoussinesqRuntimeBackend:
        """Resolve the selected nonlinear runtime backend implementation."""
        return self._resolve_solver_contract().runtime_backend

    def _resolve_solver_contract(self) -> BoussinesqSolverContract:
        """Return the explicit solver contract derived from the current `Flow`.

        Levels made explicit:
        - process regime: steady / transient,
        - requested execution backend,
        - requested surface-interaction model,
        - resolved physical method,
        - resolved nonlinear execution engine.
        """
        return resolve_solver_contract(self.flow)

    def _runtime_options(self) -> NonlinearRuntimeOptions:
        """Build backend-neutral nonlinear options for the selected runtime."""
        return build_runtime_options(
            self.flow,
            regularization_radius=float(
                self.saturation_excess_regularization_radius
            ),
        )

    def _record_runtime_backend_summary(
        self,
        contract: BoussinesqSolverContract,
    ) -> None:
        """Record which nonlinear strategy was used for this solve."""
        record_runtime_backend_summary(self, contract)

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
        runtime_backend: ResolvedBoussinesqRuntimeBackend,
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
