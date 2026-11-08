"""What the Boussinesq solver can run, and how a run picks it.

A method is a physical formulation (the unknowns and the surface closure) on
one space scheme (finite volumes on triangles, heads at the cell centers) and
one time scheme per regime. An engine is the nonlinear and linear solver that
runs a method. ``resolve_runtime_backend`` turns the ``[solver.boussinesq]`` backend
and surface model into one method, one engine, and the runtime module that
solves it. The descriptions and labels feed the runtime summary of a run.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Literal, Protocol, cast, runtime_checkable

from hydromodpy.model.time.regime import normalize_flow_regime
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
    TransientStepInputs,
)


@dataclass(frozen=True)
class TimeSchemeSpec:
    """Descriptor for one time-discretization family."""

    id: str
    regime: str
    problem_kind: str
    description: str


STEADY_BALANCE = TimeSchemeSpec(
    id="steady_balance",
    regime="steady",
    problem_kind="steady_head_balance",
    description="Stationary nonlinear balance with no storage term.",
)


BACKWARD_EULER = TimeSchemeSpec(
    id="backward_euler",
    regime="transient",
    problem_kind="transient_head_balance",
    description="Fully implicit backward-Euler step on the head balance.",
)


def resolve_time_scheme(flow_regime: str | None) -> TimeSchemeSpec:
    """Return the canonical time-discretization descriptor for one regime."""

    regime = normalize_flow_regime(flow_regime or "transient")
    if regime == "steady":
        return STEADY_BALANCE
    if regime == "transient":
        return BACKWARD_EULER
    raise ValueError("Unsupported Boussinesq flow regime. Expected one of: steady, transient.")


@dataclass(frozen=True)
class SpaceSchemeSpec:
    """Descriptor for one spatial discretization family."""

    id: str
    mesh_support: str
    unknown_support: str
    flux_family: str
    description: str


FV_TRI_CELL_CENTERED = SpaceSchemeSpec(
    id="fv_tri_cell_centered",
    mesh_support="triangular_planar_mesh",
    unknown_support="cell_centers",
    flux_family="two_point_flux_with_edge_transmissivity",
    description=(
        "Finite-volume balance on triangular cells with cell-centered hydraulic "
        "head unknowns and edge-based transmissive fluxes."
    ),
)


UnknownLayoutName = Literal["head_only", "head_plus_qex_qdry"]


SurfaceClosureName = Literal[
    "regularized_partition",
    "complementarity",
    "vi_obstacle",
    "ts_vi_obstacle",
]


@dataclass(frozen=True)
class BoussinesqFormulationSpec:
    """Descriptor for one algebraic formulation of the Boussinesq problem."""

    id: str
    unknown_layout: UnknownLayoutName
    surface_closure: SurfaceClosureName
    steady_residual_label: str
    transient_residual_label: str
    description: str


HEAD_ONLY_REGULARIZED_PARTITION = BoussinesqFormulationSpec(
    id="head_only_regularized_partition",
    unknown_layout="head_only",
    surface_closure="regularized_partition",
    steady_residual_label="steady_regularized_partition_head_balance",
    transient_residual_label="transient_regularized_partition_head_balance",
    description=(
        "Head-only residual where saturation excess is reconstructed from the "
        "regularized partition law q_ex = G_r(theta) R(balance)."
    ),
)


MIXED_COMPLEMENTARITY = BoussinesqFormulationSpec(
    id="mixed_complementarity",
    unknown_layout="head_plus_qex_qdry",
    surface_closure="complementarity",
    steady_residual_label="steady_mixed_complementarity_balance",
    transient_residual_label="transient_mixed_complementarity_balance",
    description=(
        "Mixed formulation with hydraulic head, saturation-excess rate and dry-deficit "
        "rate as unknowns. The algebraic rates enforce upper and lower head obstacles."
    ),
)


HEAD_ONLY_VI_OBSTACLE = BoussinesqFormulationSpec(
    id="head_only_vi_obstacle",
    unknown_layout="head_only",
    surface_closure="vi_obstacle",
    steady_residual_label="steady_vi_obstacle_head_balance",
    transient_residual_label="transient_vi_obstacle_head_balance",
    description=(
        "Experimental head-only variational-inequality formulation with direct "
        "lower/upper head bounds. Surface-excess and dry-deficit rates are "
        "reconstructed after convergence as obstacle reactions."
    ),
)


HEAD_ONLY_TS_VI_OBSTACLE = BoussinesqFormulationSpec(
    id="head_only_ts_vi_obstacle",
    unknown_layout="head_only",
    surface_closure="ts_vi_obstacle",
    steady_residual_label="steady_vi_obstacle_head_balance",
    transient_residual_label="transient_ts_vi_obstacle_head_balance",
    description=(
        "Experimental head-only variational-inequality formulation integrated "
        "with PETSc TS. Head is bounded directly and surface/bottom reactions "
        "are reconstructed from the implicit TS residual."
    ),
)


@dataclass(frozen=True)
class BoussinesqMethodSpec:
    """Descriptor for one complete physical-method family."""

    id: str
    formulation: BoussinesqFormulationSpec
    space_scheme_id: str
    supported_time_scheme_ids: tuple[str, ...]
    supported_runtime_backends: frozenset[str]
    description: str

    @property
    def unknown_layout(self) -> str:
        return self.formulation.unknown_layout

    @property
    def surface_closure(self) -> str:
        return self.formulation.surface_closure

    def time_scheme_for_regime(self, flow_regime: str | None) -> TimeSchemeSpec:
        """Return the canonical time-discretization for one flow regime."""

        scheme = resolve_time_scheme(flow_regime)
        if scheme.id not in self.supported_time_scheme_ids:
            raise NotImplementedError(
                f"Boussinesq method '{self.id}' does not support time scheme '{scheme.id}'."
            )
        return scheme


HEAD_ONLY_REGULARIZED_PARTITION_METHOD = BoussinesqMethodSpec(
    id="head_only_regularized_partition",
    formulation=HEAD_ONLY_REGULARIZED_PARTITION,
    space_scheme_id=FV_TRI_CELL_CENTERED.id,
    supported_time_scheme_ids=(STEADY_BALANCE.id, BACKWARD_EULER.id),
    supported_runtime_backends=frozenset({"local", "scipy", "scipy_sparse", "petsc"}),
    description=(
        "Historical head-only formulation with the regularized partition "
        "surface closure. This is the common comparison baseline across the "
        "dense, sparse and PETSc partition runtimes."
    ),
)


MIXED_COMPLEMENTARITY_METHOD = BoussinesqMethodSpec(
    id="mixed_complementarity",
    formulation=MIXED_COMPLEMENTARITY,
    space_scheme_id=FV_TRI_CELL_CENTERED.id,
    supported_time_scheme_ids=(STEADY_BALANCE.id, BACKWARD_EULER.id),
    supported_runtime_backends=frozenset({"petsc"}),
    description=(
        "Mixed formulation where head, saturation-excess and dry-deficit rates "
        "are co-solved under a double-obstacle complementarity closure."
    ),
)


HEAD_ONLY_VI_OBSTACLE_METHOD = BoussinesqMethodSpec(
    id="head_only_vi_obstacle",
    formulation=HEAD_ONLY_VI_OBSTACLE,
    space_scheme_id=FV_TRI_CELL_CENTERED.id,
    supported_time_scheme_ids=(STEADY_BALANCE.id, BACKWARD_EULER.id),
    supported_runtime_backends=frozenset({"petsc"}),
    description=(
        "Experimental PETSc SNESVI head-only obstacle formulation. The solve "
        "bounds h directly between z_bottom and z_top and reconstructs "
        "surface and bottom reactions after convergence."
    ),
)


HEAD_ONLY_TS_VI_OBSTACLE_METHOD = BoussinesqMethodSpec(
    id="head_only_ts_vi_obstacle",
    formulation=HEAD_ONLY_TS_VI_OBSTACLE,
    space_scheme_id=FV_TRI_CELL_CENTERED.id,
    supported_time_scheme_ids=(BACKWARD_EULER.id,),
    supported_runtime_backends=frozenset({"petsc"}),
    description=(
        "Experimental PETSc TS + SNESVI head-only obstacle formulation. PETSc "
        "TS performs fixed Backward-Euler steps inside each HydroModPy stress "
        "period, while h is bounded directly between z_bottom and z_top."
    ),
)


_METHOD_BY_SURFACE_CLOSURE = {
    HEAD_ONLY_REGULARIZED_PARTITION_METHOD.surface_closure: HEAD_ONLY_REGULARIZED_PARTITION_METHOD,
    MIXED_COMPLEMENTARITY_METHOD.surface_closure: MIXED_COMPLEMENTARITY_METHOD,
    HEAD_ONLY_VI_OBSTACLE_METHOD.surface_closure: HEAD_ONLY_VI_OBSTACLE_METHOD,
    HEAD_ONLY_TS_VI_OBSTACLE_METHOD.surface_closure: HEAD_ONLY_TS_VI_OBSTACLE_METHOD,
}


def resolve_surface_interaction_model_token(
    *,
    runtime_backend_name: str | None,
    surface_interaction_model: str | None = "auto",
) -> str:
    """Return the resolved surface-interaction token for one backend choice."""

    backend_name = str(runtime_backend_name or "local").strip().lower() or "local"
    requested = str(surface_interaction_model or "auto").strip().lower() or "auto"
    if requested == "auto":
        return "complementarity" if backend_name == "petsc" else "regularized_partition"
    if requested not in _METHOD_BY_SURFACE_CLOSURE:
        raise ValueError(
            "Unsupported Boussinesq surface interaction model. Expected one of: "
            "auto, regularized_partition, complementarity, vi_obstacle, ts_vi_obstacle."
        )
    return requested


def resolve_method_spec(
    *,
    runtime_backend_name: str | None,
    surface_interaction_model: str | None = "auto",
) -> BoussinesqMethodSpec:
    """Resolve one explicit Boussinesq method descriptor."""

    backend_name = str(runtime_backend_name or "local").strip().lower() or "local"
    resolved_surface = resolve_surface_interaction_model_token(
        runtime_backend_name=backend_name,
        surface_interaction_model=surface_interaction_model,
    )
    method = _METHOD_BY_SURFACE_CLOSURE[resolved_surface]
    if backend_name not in method.supported_runtime_backends:
        raise NotImplementedError(
            "The requested Boussinesq surface-interaction model is not implemented "
            f"for runtime_backend='{backend_name}'."
        )
    return method


@dataclass(frozen=True)
class BoussinesqEngineSpec:
    """Descriptor for one runtime execution engine."""

    id: str
    name: str
    module_name: str
    nonlinear_solver_kind: str
    linear_system_layout: str
    jacobian_strategy: str
    linear_solver_kind: str
    convergence_policy: str
    iteration_counter_label: str
    supported_method_ids: frozenset[str]
    description: str


_ENGINE_SPECS = (
    BoussinesqEngineSpec(
        id="local_dense_newton",
        name="local",
        module_name="hydromodpy.solver.boussinesq.runtimes.local",
        nonlinear_solver_kind="newton_line_search_dense_semianalytic_regularized_partition",
        linear_system_layout="dense",
        jacobian_strategy="fd_dense",
        linear_solver_kind="numpy_dense_solve",
        convergence_policy="residual_inf <= tol_residual_inf",
        iteration_counter_label="newton_iterations",
        supported_method_ids=frozenset({"head_only_regularized_partition"}),
        description="In-process dense Newton loop used for small validation meshes.",
    ),
    BoussinesqEngineSpec(
        id="scipy_dense_hybr",
        name="scipy",
        module_name="hydromodpy.solver.boussinesq.runtimes.scipy_dense",
        nonlinear_solver_kind="scipy_root_hybr_dense_semianalytic_regularized_partition",
        linear_system_layout="dense",
        jacobian_strategy="semianalytic_dense",
        linear_solver_kind="scipy_minpack_hybr",
        convergence_policy="state_update_inf <= tol_state_update_inf and residual_inf <= tol_residual_inf",
        iteration_counter_label="function_evaluations",
        supported_method_ids=frozenset({"head_only_regularized_partition"}),
        description="Dense SciPy root solve around the head-only regularized-partition residual.",
    ),
    BoussinesqEngineSpec(
        id="scipy_sparse_newton",
        name="scipy_sparse",
        module_name="hydromodpy.solver.boussinesq.runtimes.scipy_sparse",
        nonlinear_solver_kind="scipy_sparse_newton_line_search_semianalytic_regularized_partition",
        linear_system_layout="sparse",
        jacobian_strategy="hybrid_sparse",
        linear_solver_kind="scipy_sparse_spsolve",
        convergence_policy="residual_inf <= tol_residual_inf",
        iteration_counter_label="newton_iterations",
        supported_method_ids=frozenset({"head_only_regularized_partition"}),
        description="Sparse Newton loop with semi-analytic smooth terms and colored FD saturation corrections.",
    ),
    BoussinesqEngineSpec(
        id="petsc_partition_snes",
        name="petsc",
        module_name="hydromodpy.solver.boussinesq.runtimes.petsc_partition",
        nonlinear_solver_kind="petsc_snes_newtonls_sparse_semianalytic_regularized_partition",
        linear_system_layout="sparse",
        jacobian_strategy="semianalytic_sparse",
        linear_solver_kind="petsc_ksp_direct_preferred",
        convergence_policy="residual_inf <= tol_residual_inf",
        iteration_counter_label="nonlinear_iterations",
        supported_method_ids=frozenset({"head_only_regularized_partition"}),
        description="PETSc SNES solve on the head-only regularized-partition system.",
    ),
    BoussinesqEngineSpec(
        id="petsc_mixed_complementarity_snes",
        name="petsc",
        module_name="hydromodpy.solver.boussinesq.runtimes.petsc_mixed",
        nonlinear_solver_kind="petsc_snes_newtonls_sparse_semiexplicit_dae_fischer_burmeister",
        linear_system_layout="sparse",
        jacobian_strategy="semianalytic_sparse_block",
        linear_solver_kind="petsc_ksp_direct_preferred",
        convergence_policy="full_dae_residual_inf <= tol_residual_inf",
        iteration_counter_label="nonlinear_iterations",
        supported_method_ids=frozenset({"mixed_complementarity"}),
        description="PETSc SNES solve on the mixed head-plus-q_ex complementarity system.",
    ),
    BoussinesqEngineSpec(
        id="petsc_vi_obstacle_snes",
        name="petsc",
        module_name="hydromodpy.solver.boussinesq.runtimes.petsc_vi_obstacle",
        nonlinear_solver_kind="petsc_snesvi_vinewtonrsls_sparse_head_only_obstacle",
        linear_system_layout="sparse",
        jacobian_strategy="semianalytic_sparse_base",
        linear_solver_kind="petsc_ksp_direct_default",
        convergence_policy="projected_vi_residual_inf <= tol_residual_inf",
        iteration_counter_label="nonlinear_iterations",
        supported_method_ids=frozenset({"head_only_vi_obstacle"}),
        description="Experimental PETSc SNESVI solve on a bounded head-only obstacle system.",
    ),
    BoussinesqEngineSpec(
        id="petsc_ts_vi_obstacle",
        name="petsc",
        module_name="hydromodpy.solver.boussinesq.runtimes.petsc_ts_vi_obstacle",
        nonlinear_solver_kind="petsc_ts_beuler_snesvi_sparse_head_only_obstacle",
        linear_system_layout="sparse",
        jacobian_strategy="semianalytic_sparse_ifunction_ijacobian",
        linear_solver_kind="petsc_ksp_lu_shifted_default",
        convergence_policy="projected_vi_residual_inf <= tol_residual_inf",
        iteration_counter_label="ts_snes_iterations",
        supported_method_ids=frozenset({"head_only_ts_vi_obstacle"}),
        description=(
            "Experimental PETSc TS Backward-Euler integration with SNESVI "
            "bounds on the head-only obstacle system."
        ),
    ),
)


def resolve_engine_spec(
    *,
    runtime_backend_name: str | None,
    method_id: str,
) -> BoussinesqEngineSpec:
    """Return the engine descriptor compatible with one method choice."""

    backend_name = str(runtime_backend_name or "local").strip().lower() or "local"
    for spec in _ENGINE_SPECS:
        if spec.name == backend_name and method_id in spec.supported_method_ids:
            return spec
    raise ValueError(
        "Unsupported Boussinesq runtime backend. Expected one of: "
        "local, scipy, scipy_sparse, petsc."
    )


RuntimeBackendName = Literal["local", "scipy", "scipy_sparse", "petsc"]


LinearSystemLayout = Literal["dense", "sparse", "matrix_free"]


SurfaceInteractionModel = Literal[
    "auto",
    "regularized_partition",
    "complementarity",
    "vi_obstacle",
    "ts_vi_obstacle",
]


@runtime_checkable
class BoussinesqRuntimeBackend(Protocol):
    """Minimal execution contract implemented by runtime modules."""

    def solve_transient_step(
        self,
        inputs: TransientStepInputs,
    ) -> RuntimeSolveResult: ...

    def solve_steady_problem(
        self,
        inputs: SteadySolveInputs,
    ) -> RuntimeSolveResult: ...


@dataclass(frozen=True)
class ResolvedBoussinesqRuntimeBackend:
    """Normalized descriptor for one nonlinear runtime backend.

    The two solve callables are the only mandatory execution entry points.
    The extra string fields are not cosmetic: they document how the backend
    reached its answer and are exported in runtime summaries for diagnostics.
    """

    name: RuntimeBackendName
    engine_id: str
    method: BoussinesqMethodSpec
    backend: BoussinesqRuntimeBackend
    nonlinear_solver_kind: str
    linear_system_layout: LinearSystemLayout
    jacobian_strategy: str
    linear_solver_kind: str
    convergence_policy: str
    iteration_counter_label: str

    def solve_transient_step(
        self,
        inputs: TransientStepInputs,
    ) -> RuntimeSolveResult:
        """Delegate one transient step to the resolved runtime module."""
        return self.backend.solve_transient_step(inputs)

    def solve_steady_problem(
        self,
        inputs: SteadySolveInputs,
    ) -> RuntimeSolveResult:
        """Delegate one steady solve to the resolved runtime module."""
        return self.backend.solve_steady_problem(inputs)


def resolve_runtime_backend(
    name: str | None,
    *,
    surface_interaction_model: SurfaceInteractionModel | str = "auto",
) -> ResolvedBoussinesqRuntimeBackend:
    """Return the backend descriptor matching one user-facing backend name.

    Parameters
    ----------
    name:
        Free-form backend token coming from configuration or the flow object.
        The value is normalized to lowercase and defaults to ``"local"``.

    Returns
    -------
    ResolvedBoussinesqRuntimeBackend
        One descriptor bundling the solve callables and a short explanation of
        the nonlinear strategy used by that backend.
    """
    normalized = str(name or "local").strip().lower() or "local"
    method = resolve_method_spec(
        runtime_backend_name=normalized,
        surface_interaction_model=surface_interaction_model,
    )
    engine = resolve_engine_spec(
        runtime_backend_name=normalized,
        method_id=method.id,
    )
    backend = _load_engine_backend(engine)
    return ResolvedBoussinesqRuntimeBackend(
        name=engine.name,  # type: ignore[arg-type]
        engine_id=engine.id,
        method=method,
        backend=backend,
        nonlinear_solver_kind=engine.nonlinear_solver_kind,
        linear_system_layout=engine.linear_system_layout,  # type: ignore[arg-type]
        jacobian_strategy=engine.jacobian_strategy,
        linear_solver_kind=engine.linear_solver_kind,
        convergence_policy=engine.convergence_policy,
        iteration_counter_label=engine.iteration_counter_label,
    )


def _load_engine_backend(
    engine: BoussinesqEngineSpec,
) -> BoussinesqRuntimeBackend:
    """Import one runtime module and validate the backend execution contract."""

    module = import_module(engine.module_name)
    if not isinstance(module, BoussinesqRuntimeBackend):
        missing = [
            name
            for name in ("solve_steady_problem", "solve_transient_step")
            if not callable(getattr(module, name, None))
        ]
        missing_text = ", ".join(missing) if missing else "required runtime entry points"
        raise TypeError(
            f"{engine.module_name} does not implement the Boussinesq runtime "
            f"backend protocol; missing {missing_text}."
        )
    return cast(BoussinesqRuntimeBackend, module)


__all__ = [
    "BACKWARD_EULER",
    "BoussinesqEngineSpec",
    "BoussinesqFormulationSpec",
    "BoussinesqMethodSpec",
    "BoussinesqRuntimeBackend",
    "FV_TRI_CELL_CENTERED",
    "HEAD_ONLY_REGULARIZED_PARTITION",
    "HEAD_ONLY_REGULARIZED_PARTITION_METHOD",
    "HEAD_ONLY_TS_VI_OBSTACLE",
    "HEAD_ONLY_TS_VI_OBSTACLE_METHOD",
    "HEAD_ONLY_VI_OBSTACLE",
    "HEAD_ONLY_VI_OBSTACLE_METHOD",
    "LinearSystemLayout",
    "MIXED_COMPLEMENTARITY",
    "MIXED_COMPLEMENTARITY_METHOD",
    "ResolvedBoussinesqRuntimeBackend",
    "RuntimeBackendName",
    "STEADY_BALANCE",
    "SpaceSchemeSpec",
    "SurfaceClosureName",
    "SurfaceInteractionModel",
    "TimeSchemeSpec",
    "UnknownLayoutName",
    "resolve_engine_spec",
    "resolve_method_spec",
    "resolve_runtime_backend",
    "resolve_surface_interaction_model_token",
    "resolve_time_scheme",
]
