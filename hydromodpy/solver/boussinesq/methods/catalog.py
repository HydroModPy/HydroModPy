"""Explicit method catalog for the Boussinesq solver."""

from __future__ import annotations

from dataclasses import dataclass

from hydromodpy.solver.boussinesq.discretization import (
    BACKWARD_EULER,
    FV_TRI_CELL_CENTERED,
    STEADY_BALANCE,
    TimeSchemeSpec,
    resolve_time_scheme,
)
from hydromodpy.solver.boussinesq.formulations import (
    HEAD_ONLY_REGULARIZED_PARTITION,
    MIXED_COMPLEMENTARITY,
    BoussinesqFormulationSpec,
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
        "Mixed formulation where head and saturation-excess are co-solved "
        "under a complementarity closure."
    ),
)

_METHOD_BY_SURFACE_CLOSURE = {
    HEAD_ONLY_REGULARIZED_PARTITION_METHOD.surface_closure: HEAD_ONLY_REGULARIZED_PARTITION_METHOD,
    MIXED_COMPLEMENTARITY_METHOD.surface_closure: MIXED_COMPLEMENTARITY_METHOD,
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
            "auto, regularized_partition, complementarity."
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
            "The Boussinesq complementarity surface-interaction model is currently "
            f"implemented only for runtime_backend='petsc'. Got runtime_backend='{backend_name}'."
        )
    return method


__all__ = [
    "BoussinesqMethodSpec",
    "HEAD_ONLY_REGULARIZED_PARTITION_METHOD",
    "MIXED_COMPLEMENTARITY_METHOD",
    "resolve_method_spec",
    "resolve_surface_interaction_model_token",
]
