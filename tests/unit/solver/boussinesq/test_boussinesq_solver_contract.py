"""The Boussinesq contract reads the ``Model``, the ``[solver.boussinesq]`` options and the adapter's ``supports``."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import IncompatibleCapabilitiesError
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.solver.boussinesq.adapter import BoussinesqFlowAdapter
from hydromodpy.solver.boussinesq.options import BoussinesqOptions
from hydromodpy.solver.boussinesq.solver_contract import (
    DENSE_ENGINE_MAX_CELLS,
    assert_supported_runtime_subset,
    build_runtime_options,
    runtime_backend_name,
)
from tests._helpers.model_factory import make_model

pytestmark = pytest.mark.fast

BACKENDS = (
    ("auto", "auto"),
    ("local", "local"),
    ("scipy", "scipy"),
    ("scipy_sparse", "scipy_sparse"),
    ("petsc", "petsc"),
)


@pytest.mark.parametrize(("backend", "expected"), BACKENDS, ids=[b for b, _ in BACKENDS])
def test_the_requested_backend_is_the_one_of_the_options(backend: str, expected: str) -> None:
    assert runtime_backend_name(BoussinesqOptions(backend=backend)) == expected


OPTION_CASES = (
    ("defaults", {}, {"max_iterations": 20, "tol_residual_inf": 1e-9}),
    ("sparse engine", {"backend": "scipy_sparse"}, {"max_iterations": 60}),
    (
        "stated iterations",
        {"backend": "scipy_sparse", "max_iterations": 7},
        {"max_iterations": 7},
    ),
    (
        "stated tolerances",
        {"tol_residual_inf": 1e-6, "tol_state_update_inf": 1e-5},
        {"tol_residual_inf": 1e-6, "tol_state_update_inf": 1e-5},
    ),
    (
        "substeps follow each other",
        {"vi_substeps_per_period": 3},
        {"vi_substeps_per_period": 3, "vi_max_adaptive_substeps": 3},
    ),
    (
        "stated adaptive substeps",
        {"vi_substeps_per_period": 3, "vi_max_adaptive_substeps": 9},
        {"vi_max_adaptive_substeps": 9},
    ),
    (
        "ts vi settings",
        {
            "ts_vi_steps_per_period": 8,
            "ts_vi_adapt": True,
            "ts_vi_dt_min_fraction": 0.01,
            "ts_vi_dt_max_fraction": 0.5,
            "ts_vi_type": "cn",
            "ts_vi_snes_type": "vinewtonssls",
        },
        {
            "ts_vi_steps_per_period": 8,
            "ts_vi_adapt": True,
            "ts_vi_dt_min_fraction": 0.01,
            "ts_vi_dt_max_fraction": 0.5,
            "ts_vi_type": "cn",
            "ts_vi_snes_type": "vinewtonssls",
        },
    ),
    (
        "release depth",
        {"partition_release_depth_m": 0.02},
        {"regularization_radius": 0.02},
    ),
)


@pytest.mark.parametrize(
    ("case", "settings", "expected"), OPTION_CASES, ids=[c[0] for c in OPTION_CASES]
)
def test_the_nonlinear_options_are_those_of_the_runtime_section(
    case: str, settings: dict, expected: dict
) -> None:
    del case
    options = build_runtime_options(BoussinesqOptions(**settings), n_cells=10)

    for name, value in expected.items():
        assert getattr(options, name) == value, name


def test_the_automatic_engine_takes_the_sparse_iteration_limit_above_the_dense_size() -> None:
    options = BoussinesqOptions()

    assert build_runtime_options(options, n_cells=DENSE_ENGINE_MAX_CELLS).max_iterations == 20
    assert build_runtime_options(options, n_cells=DENSE_ENGINE_MAX_CELLS + 1).max_iterations == 60


STEADY_START_CASES = (
    ("petsc", "ts_vi_obstacle", "regularized_partition"),
    ("petsc", "vi_obstacle", None),
    ("petsc", "complementarity", None),
    ("petsc", "auto", None),
    ("scipy_sparse", "auto", None),
    ("local", "regularized_partition", None),
)


def _bundle(*active: str) -> BoundaryConditionBundle:
    return BoundaryConditionBundle(conditions={}, active_ids=tuple(active))


SUPPORTS = BoussinesqFlowAdapter.supports


def test_a_lake_is_refused_with_the_typed_capability_error() -> None:
    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        assert_supported_runtime_subset(make_model(boundaries=_bundle("lake")), SUPPORTS)

    assert "lake" in str(excinfo.value)
    assert excinfo.value.code == "HMPY.E407"


def test_a_sink_or_source_outside_the_slice_is_named() -> None:
    with pytest.raises(NotImplementedError, match="sinks and sources etp"):
        assert_supported_runtime_subset(
            make_model(active_sinks_sources=("recharge", "etp")), SUPPORTS
        )


def test_a_boundary_outside_the_slice_is_named() -> None:
    with pytest.raises(NotImplementedError, match="boundaries .*flow_barrier|boundaries "):
        assert_supported_runtime_subset(make_model(boundaries=_bundle("not_a_boundary")), SUPPORTS)
