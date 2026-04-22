"""Execution-engine catalog for the Boussinesq solver."""

from __future__ import annotations

from dataclasses import dataclass


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


__all__ = ["BoussinesqEngineSpec", "resolve_engine_spec"]
