"""High-level driver for the standalone Boussinesq flow backend.

This module does not assemble the nonlinear equations itself. Instead it:

- builds the runtime mesh and initial state from launcher objects,
- delegates each nonlinear solve to a runtime backend,
- stores the accepted state in the shape expected by the rest of HydroModPy.

Forcing resolution lives in ``forcing/`` and the per-regime
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
import time
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.exceptions import IncompatibleCapabilitiesError
from hydromodpy.core.logging import get_logger
from hydromodpy.mesh.io.bundle import CatchmentMeshBundle
from hydromodpy.model.initial.heads import summarize_head_initial_condition_bounds
from hydromodpy.model.initial.state import SteadyStart
from hydromodpy.model.model import Model, steady_variant
from hydromodpy.model.runtime_config import FlowRuntimeConfig
from hydromodpy.solver.boussinesq.assembly import (
    saturated_thickness_from_head,
)
from hydromodpy.solver.boussinesq.catalog import (
    ResolvedBoussinesqRuntimeBackend,
    resolve_runtime_backend,
    resolve_surface_interaction_model_token,
)
from hydromodpy.solver.boussinesq.drivers import (
    run_steady_runtime,
    run_transient_runtime,
)
from hydromodpy.solver.boussinesq.export_payload import (
    build_state_history_export_payload,
)
from hydromodpy.solver.boussinesq.forcing import BoussinesqForcingResolver
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
)
from hydromodpy.solver.boussinesq.runtime_summary import (
    record_surface_threshold_summary,
)
from hydromodpy.solver.boussinesq.runtimes.ts_vi_obstacle_diagnostics import (
    write_ts_vi_obstacle_diagnostic_files,
)
from hydromodpy.solver.boussinesq.runtimes.vi_obstacle_diagnostics import (
    write_vi_obstacle_diagnostic_files,
)
from hydromodpy.solver.boussinesq.solver_contract import (
    AUTO_RUNTIME_BACKEND,
    DENSE_ENGINE_MAX_CELLS,
    BoussinesqSolverContract,
    assert_supported_runtime_subset,
    build_runtime_options,
    resolve_runtime_backend_name,
    resolve_solver_contract,
    runtime_backend_name,
    steady_initialization_runtime,
)
from hydromodpy.solver.boussinesq.state import BoussinesqState

logger = get_logger(__name__)


class Boussinesq:
    """Boussinesq solver driver compatible with the HydroModPy solver contract.

    The class acts as a translator between the frozen ``Model`` of the run,
    the ``[flow.runtime]`` options and the low-level residual assembly and
    nonlinear runtime APIs used inside this package. It reads the ``Model``
    and never changes it: the auxiliary steady solve of a ``steady_state``
    start runs on a ``steady_variant`` of it.
    """

    def __init__(
        self,
        *,
        mesh_bundle: CatchmentMeshBundle | None,
        mesh: BoussinesqMesh | None = None,
        model: Model,
        runtime: FlowRuntimeConfig,
        model_folder: str | Path,
        model_name: str,
    ) -> None:
        if mesh_bundle is None and mesh is None:
            raise ValueError("Boussinesq requires either mesh_bundle or a prebuilt mesh")
        self.mesh_bundle = mesh_bundle
        self.inputs = model
        self.runtime = runtime
        self.steady_start_strategy = (
            model.initial.strategy if isinstance(model.initial, SteadyStart) else None
        )
        self.model_folder = Path(model_folder)
        self.model_name = str(model_name).strip() or "boussinesq"
        self.full_path = self.model_folder / self.model_name
        self.mesh: BoussinesqMesh | None = mesh
        self.state: BoussinesqState | None = None
        self.runtime_summary: dict[str, Any] = {}
        self.last_flow_solve_time_seconds: float | None = None
        self.has_numerical_solution = False
        self.solve_stage = "created"
        self._runtime_engine_logged = False

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
        self.last_flow_solve_time_seconds = None
        if self.inputs.time.regime == "steady":
            success = self._time_flow_solve(self._run_steady_runtime)
        elif self.inputs.time.grid is None:
            return True
        else:
            if self._uses_steady_state_initial_condition():
                success = self._run_steady_state_initialization()
                if not success:
                    self.has_numerical_solution = False
                    self.solve_stage = "failed"
                    self.post_processing()
                    return False
            success = self._time_flow_solve(self._run_transient_runtime)

        self.has_numerical_solution = bool(success)
        self.solve_stage = "solved" if success else "failed"
        try:
            self.post_processing()
        except Exception as exc:
            self.solve_stage = "post_processing_failed"
            raise RuntimeError("Boussinesq post-processing failed") from exc
        return bool(success)

    def _time_flow_solve(self, solve_callable) -> bool:
        """Run one main flow solve and record its elapsed wall time."""
        solve_start = time.perf_counter()
        try:
            return bool(solve_callable())
        finally:
            elapsed = time.perf_counter() - solve_start
            self.last_flow_solve_time_seconds = elapsed
            self.runtime_summary["flow_solve_time_seconds"] = float(elapsed)

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
                state_payload["storage_coefficient"] = np.asarray(
                    self.mesh.storage_coefficient, dtype=float
                )
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
        write_vi_obstacle_diagnostic_files(self.full_path, summary_payload)
        write_ts_vi_obstacle_diagnostic_files(self.full_path, summary_payload)
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
        assert_supported_runtime_subset(self.inputs)

    def _mesh_cell_count(self) -> int | None:
        """Return the number of solver cells, or None before the mesh exists."""
        return None if self.mesh is None else int(self.mesh.n_cells)

    def _runtime_backend_name(self) -> str:
        """Return the engine that runs, with ``"auto"`` resolved on the mesh size."""
        return resolve_runtime_backend_name(
            runtime_backend_name(self.runtime),
            n_cells=self._mesh_cell_count(),
        )

    def _surface_interaction_model(self) -> str:
        """Return the selected groundwater/surface interaction closure."""
        return resolve_surface_interaction_model_token(
            runtime_backend_name=self._runtime_backend_name(),
            surface_interaction_model=self.runtime.surface_interaction_model,
        )

    def _runtime_backend(self) -> ResolvedBoussinesqRuntimeBackend:
        """Resolve the selected nonlinear runtime backend implementation."""
        return resolve_runtime_backend(
            self._runtime_backend_name(),
            surface_interaction_model=self._surface_interaction_model(),
        )

    def _runtime_options(self) -> NonlinearRuntimeOptions:
        """Build backend-neutral nonlinear options for the selected runtime."""
        return build_runtime_options(self.runtime, n_cells=self._mesh_cell_count())

    def _resolve_solver_contract(self) -> BoussinesqSolverContract:
        """Resolve the explicit solver contract from the model and the options."""
        contract = resolve_solver_contract(
            self.inputs, self.runtime, n_cells=self._mesh_cell_count()
        )
        self._log_runtime_engine_once(contract)
        return contract

    def _log_runtime_engine_once(self, contract: BoussinesqSolverContract) -> None:
        """Log at info level, once per solver, which engine runs and why."""
        if self._runtime_engine_logged:
            return
        self._runtime_engine_logged = True
        n_cells = self._mesh_cell_count()
        engine = contract.runtime_backend.name
        if contract.runtime_backend_requested == AUTO_RUNTIME_BACKEND:
            logger.info(
                "Boussinesq engine '%s', chosen by runtime_backend 'auto' for %s cells "
                "(dense 'local' up to %d cells, sparse 'scipy_sparse' above).",
                engine,
                n_cells,
                DENSE_ENGINE_MAX_CELLS,
            )
            return
        logger.info(
            "Boussinesq engine '%s', set by flow.runtime.backend, for %s cells.",
            engine,
            n_cells,
        )

    def _forcing_resolver(self) -> BoussinesqForcingResolver:
        """Build one forcing resolver bound to the current solver state."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving forcings.")
        return BoussinesqForcingResolver(mesh=self.mesh, inputs=self.inputs)

    def _run_transient_runtime(self) -> bool:
        """Advance the head state over all launcher stress periods."""
        return run_transient_runtime(self)

    def _run_steady_runtime(self) -> bool:
        """Solve one steady nonlinear balance on the selected backend."""
        return run_steady_runtime(self)

    def _uses_steady_state_initial_condition(self) -> bool:
        """Return whether `[flow.ic]` requests same-solver steady initialization."""
        return isinstance(self.inputs.initial, SteadyStart)

    def _run_steady_state_initialization(self) -> bool:
        """Materialize a same-solver steady-state initial condition.

        The steady solve runs on a second solver built over ``steady_variant`` of
        the model, which starts from the top. It shares the mesh, the start head
        and the summary of this one, and hands the head state it reaches back. The
        model of this solver is never touched.
        """
        auxiliary = Boussinesq(
            mesh_bundle=self.mesh_bundle,
            mesh=self.mesh,
            model=steady_variant(self.inputs),
            runtime=steady_initialization_runtime(self.runtime),
            model_folder=self.model_folder,
            model_name=self.model_name,
        )
        auxiliary.state = self.state
        auxiliary.runtime_summary = dict(self.runtime_summary)
        auxiliary.steady_start_strategy = self.steady_start_strategy
        auxiliary._runtime_engine_logged = self._runtime_engine_logged
        success = auxiliary._run_steady_runtime()
        self.state = auxiliary.state
        self.runtime_summary.update(auxiliary.runtime_summary)
        self._runtime_engine_logged = auxiliary._runtime_engine_logged
        self.runtime_summary["steady_state_initialization"] = bool(success)
        self.runtime_summary["steady_state_initialization_solver"] = "boussinesq"
        return bool(success)

    def _build_initial_state(self) -> BoussinesqState:
        """Create the initial state from the start state of the model."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before initializing the state.")
        head_m = self._resolve_initial_head_field()
        self.runtime_summary["initial_head_bounds"] = summarize_head_initial_condition_bounds(
            head=head_m,
            top=self.mesh.z_top_m,
            bottom=self.mesh.z_bottom_m,
            location_prefix="flow.ic",
        )
        saturated_thickness_m = saturated_thickness_from_head(self.mesh, head_m)
        return BoussinesqState(
            head_m=head_m,
            saturated_thickness_m=saturated_thickness_m,
        )

    def _assert_runtime_mesh_size_supported(
        self,
        runtime_backend: ResolvedBoussinesqRuntimeBackend,
    ) -> None:
        """Refuse a dense engine on a mesh above its size limit.

        ``"auto"`` never resolves to a dense engine above the limit, so this
        only stops an explicit ``local`` or ``scipy`` request.
        """
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before checking runtime limits.")
        if runtime_backend.linear_system_layout != "dense":
            return
        if self.mesh.n_cells > DENSE_ENGINE_MAX_CELLS:
            raise IncompatibleCapabilitiesError(
                f"flow.runtime.backend = '{runtime_backend.name}' builds a dense "
                f"Jacobian by design and runs on at most {DENSE_ENGINE_MAX_CELLS} "
                f"cells; this mesh has {self.mesh.n_cells}. Remove the key, or set "
                "it to 'auto', to run 'scipy_sparse' on this mesh, or set "
                "'scipy_sparse' or 'petsc'."
            )

    def _resolve_initial_head_field(self) -> np.ndarray:
        """Resolve the start state of the model into cell heads."""
        if self.mesh is None:
            raise RuntimeError("Mesh must be built before resolving initial heads.")

        return self._forcing_resolver().resolve_initial_head_field()


__all__ = ["Boussinesq", "BoussinesqState"]
