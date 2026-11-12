"""Tests of `optim.method_config`."""

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
from hydromodpy.calibration.optim.optimizer import EvaluationResult, build_optimizer
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    options_the_recipe_already_runs,
)
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.workflow.steps.prepare_solver.freeze import portable_config_document
from tests.unit.calibration._factories import two_dim_space
from tests.unit.config.test_a_renamed_key_warns_and_a_sealed_one_reads import PROJECT, _project

# From test_lhs_adapter.py
# Stratification, reproducibility, and budget contract for ``lhs``.
#
# ``lhs`` draws a true stratified Latin hypercube design, once, in the unit
# hypercube, then maps each dimension into its parameter's transformed space.
# Unlike ``random_search`` (independent per-dimension draws), every one of the
# ``n_samples`` strata of every dimension is hit exactly once: that guarantee,
# not just "within bounds", is what these tests check.


def _logtwo_dim_space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="k", lower=1e-6, upper=1e-2, search_space="log")])


def _strata_indices(values: list[float], low: float, high: float, n: int) -> list[int]:
    """Bin each value into one of *n* equal-width strata of [low, high]."""
    width = (high - low) / n
    return sorted(min(int((v - low) / width), n - 1) for v in values)


class TestStratification:
    @pytest.mark.parametrize(("engine", "options"), [("lhs", {"n_samples": 5}), ("optuna", {})])
    def test_normal_prior_is_refused_naming_the_parameter(self, engine: str, options: dict) -> None:
        space = ParameterSpace(
            [CalibParameter(name="theta", lower=0.0, upper=1.0, sampling="normal")]
        )
        with pytest.raises(ValueError, match=f"{engine} cannot draw.*theta"):
            build_optimizer(engine, space, seed=0, **options)


class TestReproducibility:
    def test_same_seed_gives_the_same_design(self) -> None:
        opt_a = build_optimizer("lhs", two_dim_space(), n_samples=10, seed=42)
        opt_b = build_optimizer("lhs", two_dim_space(), n_samples=10, seed=42)
        a = opt_a.ask(n=10)
        b = opt_b.ask(n=10)
        for pa, pb in zip(a, b, strict=True):
            assert pa.values["x"] == pytest.approx(pb.values["x"])
            assert pa.values["y"] == pytest.approx(pb.values["y"])

    def test_another_seed_gives_a_different_design(self) -> None:
        opt_a = build_optimizer("lhs", two_dim_space(), n_samples=10, seed=1)
        opt_b = build_optimizer("lhs", two_dim_space(), n_samples=10, seed=2)
        xs_a = [p.values["x"] for p in opt_a.ask(n=10)]
        xs_b = [p.values["x"] for p in opt_b.ask(n=10)]
        assert xs_a != xs_b


class TestAskContract:
    def test_suggest_next_raises_once_exhausted(self) -> None:
        opt = build_optimizer("lhs", two_dim_space(), n_samples=1, seed=0)
        opt.ask(n=1)
        with pytest.raises(StopIteration):
            opt.suggest_next()


class TestTellAndBest:
    def test_best_tracks_lowest_completed_objective(self) -> None:
        opt = build_optimizer("lhs", two_dim_space(), n_samples=8, seed=3)
        suggestions = opt.ask(n=8)
        results = [
            EvaluationResult(
                trial_id=s.trial_id,
                sim_id=f"sim-{s.trial_id}",
                cost=(s.values["x"] - 0.5) ** 2,
                status="completed",
            )
            for s in suggestions
        ]
        opt.tell(results)
        best = opt.best()
        expected = min(results, key=lambda r: r.cost)
        assert best is not None
        assert best.trial_id == expected.trial_id


# From test_max_trials_is_the_only_search_budget.py
# ``max_trials`` is the one number that bounds a search.
#
# ``max_iter`` counted evaluations, and ``maxfev``, ``max_evaluations`` and
# gp_mapping's own ``max_iter`` counted them too, under four names that did not
# agree about what an iteration was. A key renamed or removed is refused with the
# name that replaces it, and the file is not rewritten.


PROTOCOL = "matching_hydrographic_network"


def _phase(**fields: object) -> CalibPhaseDecl:
    return CalibPhaseDecl.model_validate({"name": "sy", "parameters": ["Sy"], **fields})


def test_the_protocol_refuses_its_stage_budgets_and_names_the_new_ones() -> None:
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
def test_a_method_option_that_counted_evaluations_is_refused_for_max_trials(
    method: str, option: str
) -> None:
    problem = method_options_problem(method, {option: 10})

    assert problem is not None
    assert f"{option}" in problem
    assert "max_trials" in problem
    with pytest.raises(ValueError, match="max_trials"):
        validate_method_kwargs(method, {option: 10})


def test_the_budget_is_not_a_method_option_of_any_method() -> None:
    for method in ("grid", "optuna", "bisection", "cma_es", "gp_mapping"):
        problem = method_options_problem(method, {"max_trials": 10})
        assert problem is not None
        assert "[calibration] max_trials" in problem


def test_a_phase_and_a_stage_refuse_a_budget_option_at_load() -> None:
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


def test_a_frozen_protocol_run_with_the_old_budget_keys_is_refused_with_the_way_out(
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


# From test_method_config.py
# Tests for the discriminated-union ``CalibrationMethodConfig``.
#
# A file writes ``method: str`` beside a free-form ``method_options`` table,
# which used to fail only at runtime when an option was foreign to the chosen
# method. The discriminated union promotes those failures to validation time
# and dumps a clear Pydantic error.


# From test_method_options.py
# The options of a calibration method are called ``method_options``, and load checked.
#
# They were ``optimizer_kwargs`` on a phase and on ``[calibration]``, and
# ``steady_engine_options`` / ``transient_engine_options`` on the protocol: Python
# jargon for one concept under two names. The old spellings are refused, with an
# error naming the new one. An option its method does not take is refused when
# the file loads, naming where it was written, instead of when that phase starts,
# after the phases before it have spent their budget.


def test_a_method_with_no_model_here_is_left_to_its_own_constructor() -> None:
    assert method_options_problem("a_plugin_engine", {"anything": 1}) is None


def test_a_protocol_stage_option_is_refused_under_the_key_the_file_wrote() -> None:
    with pytest.raises(ValidationError, match="transient_method_options: 'scipy_nelder_mead'"):
        CalibrationProtocolDecl.model_validate(
            {"name": PROTOCOL, "transient_method_options": {"sweep_points": 7}}
        )


# From test_options_the_recipe_already_runs.py
# An option written the way the recipe runs it anyway has not moved off the recipe.
#
# Example 04 writes ``sweep_points = 7``, ``steady_precision = 0.01`` and the
# spin-up window out, so the file can be read beside the paper. The bisection's own
# defaults are seven points and one per cent, and the protocol leaves the first
# year out on its own: ``--check`` listed all three as moved.


NAME = "matching_hydrographic_network"
TIME = SimpleNamespace(start_datetime="2000-01-01", end_datetime="2002-12-31")
PLAIN = SimpleNamespace(window=None)


def _same(calibration=PLAIN, **options: object) -> frozenset[str]:
    declared = CalibrationProtocolDecl.model_validate({"name": NAME, **options})
    return options_the_recipe_already_runs(declared, calibration, TIME)


def test_the_method_s_own_defaults_written_out_run_as_the_recipe() -> None:
    assert _same(steady_method_options={"sweep_points": 7}) == {"steady_method_options"}
    assert _same(steady_method_options={"sweep_points": 7, "rel_tol": 0.01}) == {
        "steady_method_options"
    }


def test_the_bisection_s_own_precision_written_out_runs_as_the_recipe() -> None:
    assert _same(steady_precision=0.01) == {"steady_precision"}
    assert _same(steady_precision=0.05) == frozenset()


def test_a_precision_the_simplex_reads_as_a_width_is_always_a_choice() -> None:
    """Nelder-Mead writes its xatol from the bounds: no default equals a written number."""
    assert _same(transient_precision=0.05) == frozenset()


def test_another_window_is_away_from_the_recipe() -> None:
    assert _same(window={"start": "2002-06-01"}) == frozenset()
    assert _same(window={"start": "2001-01-01", "end": "2002-06-30"}) == frozenset()


def test_the_window_is_the_recipe_s_only_when_calibration_bounds_nothing() -> None:
    bounded = SimpleNamespace(window={"start": "2000-06-01"})

    assert _same(bounded, window={"start": "2001-01-01"}) == frozenset()


def test_options_equal_to_the_method_s_defaults_are_recognised() -> None:
    assert method_options_are_its_defaults("bisection", {"sweep_points": 7})
    assert not method_options_are_its_defaults("bisection", {"sweep_points": 0})
    assert not method_options_are_its_defaults("bisection", {"points_per_dim": 3})
    assert not method_options_are_its_defaults("a_plugin_engine", {"x": 1})


def test_only_a_relative_stopping_option_has_a_default_precision() -> None:
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
def test_each_optimizer_declares_its_options_model(
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
