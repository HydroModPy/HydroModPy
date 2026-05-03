from __future__ import annotations

import pytest

from hydromodpy.solver.boussinesq.engines import resolve_engine_spec
from hydromodpy.solver.boussinesq.methods import (
    resolve_method_spec,
    resolve_surface_interaction_model_token,
)
from hydromodpy.solver.boussinesq.runtime_selection import resolve_runtime_backend


def test_method_catalog_resolves_regularized_partition_for_scipy_sparse() -> None:
    method = resolve_method_spec(
        runtime_backend_name="scipy_sparse",
        surface_interaction_model="auto",
    )

    assert method.id == "head_only_regularized_partition"
    assert method.unknown_layout == "head_only"
    assert method.surface_closure == "regularized_partition"
    assert method.space_scheme_id == "fv_tri_cell_centered"
    assert method.time_scheme_for_regime("transient").id == "backward_euler"


def test_method_catalog_resolves_complementarity_only_for_petsc() -> None:
    method = resolve_method_spec(
        runtime_backend_name="petsc",
        surface_interaction_model="complementarity",
    )

    assert method.id == "mixed_complementarity"
    assert method.unknown_layout == "head_plus_qex_qdry"
    assert method.surface_closure == "complementarity"

    with pytest.raises(NotImplementedError):
        resolve_method_spec(
            runtime_backend_name="scipy_sparse",
            surface_interaction_model="complementarity",
        )


def test_surface_interaction_auto_remains_backend_dependent() -> None:
    assert (
        resolve_surface_interaction_model_token(
            runtime_backend_name="local",
            surface_interaction_model="auto",
        )
        == "regularized_partition"
    )
    assert (
        resolve_surface_interaction_model_token(
            runtime_backend_name="petsc",
            surface_interaction_model="auto",
        )
        == "complementarity"
    )


def test_engine_catalog_routes_petsc_variants_by_method() -> None:
    partition_engine = resolve_engine_spec(
        runtime_backend_name="petsc",
        method_id="head_only_regularized_partition",
    )
    mixed_engine = resolve_engine_spec(
        runtime_backend_name="petsc",
        method_id="mixed_complementarity",
    )

    assert partition_engine.id == "petsc_partition_snes"
    assert partition_engine.jacobian_strategy == "semianalytic_sparse"
    assert mixed_engine.id == "petsc_mixed_complementarity_snes"
    assert mixed_engine.jacobian_strategy == "semianalytic_sparse_block"


def test_runtime_selection_exposes_method_and_engine_axes() -> None:
    backend = resolve_runtime_backend(
        "scipy_sparse",
        surface_interaction_model="regularized_partition",
    )

    assert backend.name == "scipy_sparse"
    assert backend.engine_id == "scipy_sparse_newton"
    assert backend.method.id == "head_only_regularized_partition"
    assert backend.jacobian_strategy == "hybrid_sparse"
    assert backend.linear_solver_kind == "scipy_sparse_spsolve"
