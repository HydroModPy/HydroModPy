"""The Boussinesq contract reads the ``Model``, the ``[solver.boussinesq]`` options and the adapter's ``supports``."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import IncompatibleCapabilitiesError
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.model import ModelTime
from hydromodpy.solver.boussinesq.adapter import BoussinesqFlowAdapter
from hydromodpy.solver.boussinesq.options import (
    DEFAULT_PARTITION_RELEASE_DEPTH_M,
    BoussinesqOptions,
)
from hydromodpy.solver.boussinesq.solver_contract import (
    DENSE_ENGINE_MAX_CELLS,
    assert_supported_runtime_subset,
    build_runtime_options,
    resolve_flow_regime,
    resolve_solver_contract,
    resolve_surface_interaction_model,
    runtime_backend_name,
    steady_initialization_runtime,
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


def test_the_default_options_ask_for_the_automatic_engine() -> None:
    assert runtime_backend_name(BoussinesqOptions()) == "auto"


@pytest.mark.parametrize("regime", ["steady", "transient"])
def test_the_regime_is_the_one_of_the_model(regime: str) -> None:
    model = make_model(time=ModelTime(grid=None, regime=regime, first_period_steady=True))

    assert resolve_flow_regime(model) == regime


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


def test_the_default_release_depth_and_vi_settings_are_those_of_the_runtime_section() -> None:
    options = build_runtime_options(BoussinesqOptions())

    assert options.regularization_radius == DEFAULT_PARTITION_RELEASE_DEPTH_M
    assert options.vi_substeps_per_period == 1
    assert options.vi_substep_on_failure is False
    assert options.ts_vi_steps_per_period == 4
    assert options.ts_vi_type == "beuler"
    assert options.ts_vi_snes_type == "vinewtonrsls"


def test_the_automatic_engine_takes_the_sparse_iteration_limit_above_the_dense_size() -> None:
    options = BoussinesqOptions()

    assert build_runtime_options(options, n_cells=DENSE_ENGINE_MAX_CELLS).max_iterations == 20
    assert build_runtime_options(options, n_cells=DENSE_ENGINE_MAX_CELLS + 1).max_iterations == 60


def test_the_surface_closure_resolves_on_the_engine_the_mesh_size_picks() -> None:
    auto = BoussinesqOptions()

    assert resolve_surface_interaction_model(auto, n_cells=10) == "regularized_partition"
    assert resolve_surface_interaction_model(auto, n_cells=DENSE_ENGINE_MAX_CELLS + 1) == (
        "regularized_partition"
    )


def test_the_solver_contract_joins_the_model_regime_and_the_options() -> None:
    model = make_model(time=ModelTime(grid=None, regime="steady", first_period_steady=True))

    contract = resolve_solver_contract(model, BoussinesqOptions(backend="scipy_sparse"), n_cells=5)

    assert contract.flow_regime == "steady"
    assert contract.runtime_backend_requested == "scipy_sparse"
    assert contract.runtime_backend.name == "scipy_sparse"
    assert contract.surface_interaction_model_requested == "auto"


STEADY_START_CASES = (
    ("petsc", "ts_vi_obstacle", "regularized_partition"),
    ("petsc", "vi_obstacle", None),
    ("petsc", "complementarity", None),
    ("petsc", "auto", None),
    ("scipy_sparse", "auto", None),
    ("local", "regularized_partition", None),
)


@pytest.mark.parametrize(
    ("backend", "surface", "expected"),
    STEADY_START_CASES,
    ids=[f"{b}-{s}" for b, s, _ in STEADY_START_CASES],
)
def test_only_the_ts_vi_obstacle_runs_another_closure_for_its_steady_start(
    backend: str, surface: str, expected: str | None
) -> None:
    runtime = BoussinesqOptions(backend=backend, surface_interaction_model=surface)

    steady = steady_initialization_runtime(runtime)

    if expected is None:
        assert steady is runtime
    else:
        assert steady.surface_interaction_model == expected
        assert steady.backend == backend
        assert runtime.surface_interaction_model == surface
        assert steady.model_dump() | {"surface_interaction_model": surface} == runtime.model_dump()


def _bundle(*active: str) -> BoundaryConditionBundle:
    return BoundaryConditionBundle(conditions={}, active_ids=tuple(active))


SUPPORTS = BoussinesqFlowAdapter.supports


def test_the_supported_slice_is_accepted() -> None:
    assert_supported_runtime_subset(
        make_model(
            boundaries=_bundle("west_side", "ocean"), active_sinks_sources=("recharge", "wells")
        ),
        SUPPORTS,
    )


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


def test_the_check_reads_the_supports_it_is_given() -> None:
    """The adapter's list decides, so a trait added there is built without a second list."""
    assert_supported_runtime_subset(
        make_model(boundaries=_bundle("lake"), active_sinks_sources=("etp",)),
        SUPPORTS | {"lake", "etp"},
    )
