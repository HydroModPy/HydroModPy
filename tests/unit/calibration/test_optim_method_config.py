"""Options of a calibration method, checked when the file loads.

A method's options are a Pydantic model. An option the method does not take, or
a budget written as an option instead of `max_trials`, is refused with the name
that replaces it. Search budgets count trials. Precisions are relative (-) or in
parameter units.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_objective import CalibrationProtocolDecl
from hydromodpy.calibration.config_phases import CalibPhaseDecl
from hydromodpy.calibration.optim.method_config import (
    default_relative_precision,
    method_options_are_its_defaults,
    method_options_problem,
    validate_method_kwargs,
)
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    options_the_recipe_already_runs,
)
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.workflow.steps.prepare_solver.freeze import portable_config_document
from tests.unit.config.test_config_migration import PROJECT, _project

PROTOCOL = "matching_hydrographic_network"


def _phase(**fields: object) -> CalibPhaseDecl:
    return CalibPhaseDecl.model_validate({"name": "sy", "parameters": ["Sy"], **fields})


def test_protocol_stage_budgets() -> None:
    with pytest.raises(ValidationError, match="renamed to 'steady_max_trials'"):
        CalibrationProtocolDecl.model_validate({"name": PROTOCOL, "steady_max_iter": 20})
    with pytest.raises(ValidationError, match="renamed to 'transient_max_trials'"):
        CalibrationProtocolDecl.model_validate({"name": PROTOCOL, "transient_max_iter": 20})

    declared = CalibrationProtocolDecl.model_validate(
        {"name": PROTOCOL, "steady_max_trials": 20, "transient_max_trials": 40}
    )
    assert (declared.steady_max_trials, declared.transient_max_trials) == (20, 40)


@pytest.mark.parametrize(
    ("method", "option"),
    [("scipy_nelder_mead", "maxfev"), ("cma_es", "max_evaluations"), ("gp_mapping", "max_iter")],
)
def test_evaluation_count_options_refused(method: str, option: str) -> None:
    problem = method_options_problem(method, {option: 10})

    assert problem is not None
    assert f"{option}" in problem
    assert "max_trials" in problem
    with pytest.raises(ValueError, match="max_trials"):
        validate_method_kwargs(method, {option: 10})


@pytest.mark.parametrize("method", ["grid", "optuna", "bisection", "cma_es", "gp_mapping"])
def test_budget_is_not_a_method_option(method):
    problem = method_options_problem(method, {"max_trials": 10})
    assert problem is not None
    assert "[calibration] max_trials" in problem


def test_budget_option_refused_at_load() -> None:
    with pytest.raises(ValidationError, match="phase 'sy' method_options.*max_trials"):
        _phase(method="cma_es", method_options={"max_evaluations": 20})
    with pytest.raises(ValidationError, match="transient_method_options.*max_trials"):
        CalibrationProtocolDecl.model_validate(
            {"name": PROTOCOL, "transient_method_options": {"maxfev": 20}}
        )
    with pytest.raises(ValidationError, match=r"\[calibration\] method_options.*max_trials"):
        CalibrationConfig.model_validate(
            {"method": "gp_mapping", "method_options": {"max_iter": 20}}
        )


def test_frozen_run_with_old_budget_keys(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    cfg = HydroModPyConfig.from_toml(project / "project.toml")
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    frozen = portable_config_document(cfg, run_dir, project)
    old = frozen.replace("max_trials", "max_iter")
    assert old != frozen
    sealed = run_dir / "config.toml"
    sealed.write_text(old, encoding="utf-8")
    assert PROJECT  # the same project the run was frozen from

    with pytest.raises(ConfigValidationError, match="written by a pre-release of 2.0") as refused:
        HydroModPyConfig.from_toml(sealed)

    assert "This version does not rewrite the file." in str(refused.value)
    document = tomllib.loads(old)
    with pytest.raises(ConfigValidationError):
        HydroModPyConfig.from_dict(document, base_dir=project)
    with pytest.raises(ConfigValidationError, match="written by a pre-release of 2.0"):
        HydroModPyConfig.from_snapshot({**document, "workspace": {"project_root": str(project)}})


def test_unknown_method_left_to_its_constructor() -> None:
    assert method_options_problem("a_plugin_engine", {"anything": 1}) is None


def test_stage_option_refused_under_its_key() -> None:
    with pytest.raises(ValidationError, match="transient_method_options: 'scipy_nelder_mead'"):
        CalibrationProtocolDecl.model_validate(
            {"name": PROTOCOL, "transient_method_options": {"sweep_points": 7}}
        )


# Example 04 writes options the recipe runs anyway (sweep_points = 7, a 1 % precision).


NAME = "matching_hydrographic_network"
TIME = SimpleNamespace(start_datetime="2000-01-01", end_datetime="2002-12-31")
PLAIN = SimpleNamespace(window=None)


def _same(calibration=PLAIN, **options: object) -> frozenset[str]:
    declared = CalibrationProtocolDecl.model_validate({"name": NAME, **options})
    return options_the_recipe_already_runs(declared, calibration, TIME)


BOUNDED = SimpleNamespace(window={"start": "2000-06-01"})
RECIPE_CASES = [
    pytest.param(
        PLAIN,
        {"steady_method_options": {"sweep_points": 7}},
        {"steady_method_options"},
        id="default sweep points",
    ),
    pytest.param(
        PLAIN,
        {"steady_method_options": {"sweep_points": 7, "rel_tol": 0.01}},
        {"steady_method_options"},
        id="default sweep points and tolerance",
    ),
    pytest.param(
        PLAIN, {"steady_precision": 0.01}, {"steady_precision"}, id="default bisection precision"
    ),
    pytest.param(PLAIN, {"steady_precision": 0.05}, set(), id="other bisection precision"),
    # Nelder-Mead writes its xatol from the bounds: no default equals a written number.
    pytest.param(PLAIN, {"transient_precision": 0.05}, set(), id="simplex precision"),
    pytest.param(PLAIN, {"window": {"start": "2002-06-01"}}, set(), id="other window start"),
    pytest.param(
        PLAIN,
        {"window": {"start": "2001-01-01", "end": "2002-06-30"}},
        set(),
        id="other window",
    ),
    pytest.param(
        BOUNDED, {"window": {"start": "2001-01-01"}}, set(), id="window with a bounded calibration"
    ),
]


@pytest.mark.parametrize(("calibration", "options", "expected"), RECIPE_CASES)
def test_options_the_recipe_already_runs(calibration, options, expected):
    assert _same(calibration, **options) == expected


def test_options_equal_to_defaults() -> None:
    assert method_options_are_its_defaults("bisection", {"sweep_points": 7})
    assert not method_options_are_its_defaults("bisection", {"sweep_points": 0})
    assert not method_options_are_its_defaults("bisection", {"points_per_dim": 3})
    assert not method_options_are_its_defaults("a_plugin_engine", {"x": 1})


def test_default_precision() -> None:
    assert default_relative_precision("bisection", {}) == 0.01
    assert default_relative_precision("bisection", {"rel_tol": 0.02}) is None
    assert default_relative_precision("scipy_nelder_mead", {}) is None
    assert default_relative_precision("optuna", {}) is None


@pytest.mark.parametrize(
    ("method", "valid_opts", "unknown_key", "refused_key"),
    [
        ("bisection", {"sweep_points": 7}, "unknown", "max_trials"),
        ("cma_es", {"sigma0": 0.25}, "unknown", "max_evaluations"),
        ("da_mh_gp", {"chain_length": 100}, "unknown", "max_iter"),
        ("gp_mapping", {"n_init": 5}, "unknown", "max_iter"),
        ("grid", {"points_per_dim": 3}, "unknown", "max_trials"),
        ("lhs", {"n_samples": 10}, "unknown", "max_trials"),
        ("optuna", {"sampler": "tpe"}, "unknown", "max_trials"),
        ("random_search", {}, "unknown", "max_trials"),
        ("scipy_de", {"popsize": 10}, "unknown", "maxiter"),
        ("scipy_nelder_mead", {"xatol": 0.01}, "unknown", "maxfev"),
    ],
)
def test_optimizer_options_model(
    method: str, valid_opts: dict, unknown_key: str, refused_key: str
) -> None:
    from pydantic import BaseModel

    from hydromodpy.calibration.optim.optimizer import optimizers

    cls = optimizers.get(method)
    assert hasattr(cls, "options")
    model = cls.options
    assert issubclass(model, BaseModel)

    validated = validate_method_kwargs(method, valid_opts)
    assert isinstance(validated, model)

    problem = method_options_problem(method, {unknown_key: 1})
    assert problem is not None
    assert f"'{method}' does not take {unknown_key}" in problem

    with pytest.raises(ValueError, match="does not take"):
        validate_method_kwargs(method, {refused_key: 1})
