"""What the Boussinesq solver reads from the ``Model`` and the ``[solver.boussinesq]`` options.

It turns the options into nonlinear iteration limits and tolerances (residual in
m3/s, head update in m) and refuses what the adapter's ``supports`` leaves out.
"""

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
def test_requested_backend(backend: str, expected: str) -> None:
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
    ("settings", "expected"),
    [pytest.param(settings, expected, id=case) for case, settings, expected in OPTION_CASES],
)
def test_nonlinear_options(settings: dict, expected: dict) -> None:
    options = build_runtime_options(BoussinesqOptions(**settings), n_cells=10)

    for name, value in expected.items():
        assert getattr(options, name) == value, name


def test_iteration_limit_by_engine() -> None:
    options = BoussinesqOptions()

    assert build_runtime_options(options, n_cells=DENSE_ENGINE_MAX_CELLS).max_iterations == 20
    assert build_runtime_options(options, n_cells=DENSE_ENGINE_MAX_CELLS + 1).max_iterations == 60


def _bundle(*active: str) -> BoundaryConditionBundle:
    return BoundaryConditionBundle(conditions={}, active_ids=tuple(active))


SUPPORTS = BoussinesqFlowAdapter.supports


def test_lake_is_refused() -> None:
    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        assert_supported_runtime_subset(make_model(boundaries=_bundle("lake")), SUPPORTS)

    assert "lake" in str(excinfo.value)
    assert excinfo.value.code == "HMPY.E407"


def test_unsupported_sink_is_named() -> None:
    with pytest.raises(NotImplementedError, match="sinks and sources etp"):
        assert_supported_runtime_subset(
            make_model(active_sinks_sources=("recharge", "etp")), SUPPORTS
        )


def test_unsupported_boundary_is_named() -> None:
    with pytest.raises(NotImplementedError, match="boundaries .*flow_barrier|boundaries "):
        assert_supported_runtime_subset(make_model(boundaries=_bundle("not_a_boundary")), SUPPORTS)
