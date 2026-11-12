"""Catalog of the Boussinesq numerical methods, engines and runtime backends.

A runtime backend name and a surface interaction model pick one method (unknown
layout, surface closure, time scheme). The method and the backend pick one engine
and its Jacobian strategy. Complementarity and the VI closures need PETSc.
"""

from __future__ import annotations

import pytest

from hydromodpy.solver.boussinesq.catalog import (
    resolve_engine_spec,
    resolve_method_spec,
    resolve_runtime_backend,
    resolve_surface_interaction_model_token,
)

# (backend, surface interaction model, method id, unknown layout, surface closure)
METHODS = [
    pytest.param(
        "scipy_sparse",
        "auto",
        "head_only_regularized_partition",
        "head_only",
        "regularized_partition",
        id="regularized partition on scipy sparse",
    ),
    pytest.param(
        "petsc",
        "complementarity",
        "mixed_complementarity",
        "head_plus_qex_qdry",
        "complementarity",
        id="complementarity on petsc",
    ),
    pytest.param(
        "petsc",
        "vi_obstacle",
        "head_only_vi_obstacle",
        "head_only",
        "vi_obstacle",
        id="vi obstacle on petsc",
    ),
    pytest.param(
        "petsc",
        "ts_vi_obstacle",
        "head_only_ts_vi_obstacle",
        "head_only",
        "ts_vi_obstacle",
        id="ts vi obstacle on petsc",
    ),
]


@pytest.mark.parametrize(("backend", "model", "method_id", "layout", "closure"), METHODS)
def test_method_of_a_backend(backend, model, method_id, layout, closure) -> None:
    method = resolve_method_spec(runtime_backend_name=backend, surface_interaction_model=model)

    assert method.id == method_id
    assert method.unknown_layout == layout
    assert method.surface_closure == closure


def test_scipy_sparse_partition_method_details() -> None:
    method = resolve_method_spec(
        runtime_backend_name="scipy_sparse", surface_interaction_model="auto"
    )

    assert method.space_scheme_id == "fv_tri_cell_centered"
    assert method.time_scheme_for_regime("transient").id == "backward_euler"


def test_ts_vi_obstacle_time_scheme() -> None:
    method = resolve_method_spec(
        runtime_backend_name="petsc", surface_interaction_model="ts_vi_obstacle"
    )

    assert method.time_scheme_for_regime("transient").id == "backward_euler"


@pytest.mark.parametrize("model", ["complementarity", "vi_obstacle", "ts_vi_obstacle"])
def test_petsc_only_methods_are_refused_on_scipy_sparse(model) -> None:
    with pytest.raises(NotImplementedError):
        resolve_method_spec(runtime_backend_name="scipy_sparse", surface_interaction_model=model)


AUTO_CLOSURES = [
    pytest.param("local", "regularized_partition", id="local"),
    pytest.param("petsc", "complementarity", id="petsc"),
]


@pytest.mark.parametrize(("backend", "closure"), AUTO_CLOSURES)
def test_auto_closure_depends_on_the_backend(backend, closure) -> None:
    token = resolve_surface_interaction_model_token(
        runtime_backend_name=backend, surface_interaction_model="auto"
    )

    assert token == closure


# (method id on petsc, engine id, Jacobian strategy)
ENGINES = [
    pytest.param(
        "head_only_regularized_partition",
        "petsc_partition_snes",
        "semianalytic_sparse",
        id="partition",
    ),
    pytest.param(
        "mixed_complementarity",
        "petsc_mixed_complementarity_snes",
        "semianalytic_sparse_block",
        id="mixed complementarity",
    ),
    pytest.param(
        "head_only_vi_obstacle",
        "petsc_vi_obstacle_snes",
        "semianalytic_sparse_base",
        id="vi obstacle",
    ),
    pytest.param(
        "head_only_ts_vi_obstacle",
        "petsc_ts_vi_obstacle",
        "semianalytic_sparse_ifunction_ijacobian",
        id="ts vi obstacle",
    ),
]


@pytest.mark.parametrize(("method_id", "engine_id", "jacobian"), ENGINES)
def test_engine_of_a_petsc_method(method_id, engine_id, jacobian) -> None:
    engine = resolve_engine_spec(runtime_backend_name="petsc", method_id=method_id)

    assert engine.id == engine_id
    assert engine.jacobian_strategy == jacobian


def test_runtime_backend_exposes_method_and_engine() -> None:
    backend = resolve_runtime_backend(
        "scipy_sparse", surface_interaction_model="regularized_partition"
    )

    assert backend.name == "scipy_sparse"
    assert backend.engine_id == "scipy_sparse_newton"
    assert backend.method.id == "head_only_regularized_partition"
    assert backend.jacobian_strategy == "hybrid_sparse"
    assert backend.linear_solver_kind == "scipy_sparse_spsolve"


def test_ts_vi_obstacle_has_no_steady_scheme() -> None:
    method = resolve_method_spec(
        runtime_backend_name="petsc", surface_interaction_model="ts_vi_obstacle"
    )

    with pytest.raises(NotImplementedError, match="does not support time scheme 'steady_balance'"):
        method.time_scheme_for_regime("steady")


def test_unknown_surface_interaction_model() -> None:
    with pytest.raises(ValueError, match="Unsupported Boussinesq surface interaction model"):
        resolve_surface_interaction_model_token(
            runtime_backend_name="local", surface_interaction_model="sponge"
        )


ENGINE_REFUSALS = [
    pytest.param("gpu", "head_only_regularized_partition", id="unknown backend"),
    pytest.param("local", "mixed_complementarity", id="method the backend cannot run"),
]


@pytest.mark.parametrize(("backend", "method_id"), ENGINE_REFUSALS)
def test_engine_refusals(backend: str, method_id: str) -> None:
    with pytest.raises(ValueError, match="Unsupported Boussinesq runtime backend"):
        resolve_engine_spec(runtime_backend_name=backend, method_id=method_id)
