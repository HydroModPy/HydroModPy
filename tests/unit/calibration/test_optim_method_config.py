"""Tests of `optim.method_config`."""

from __future__ import annotations

import math
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibPhaseDecl, CalibrationConfig, CalibrationProtocolDecl
from hydromodpy.calibration.optim.method_config import (
    CmaEsMethodConfig,
    GridMethodConfig,
    LhsMethodConfig,
    OptunaMethodConfig,
    default_relative_precision,
    method_options_are_its_defaults,
    method_options_problem,
    typed_methods,
    validate_method_kwargs,
)
from hydromodpy.calibration.optim.optimizer import EvaluationResult, best_completed, build_optimizer
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.stopping import resolve_budget, short_budget
from hydromodpy.calibration.preflight import _check_engines
from hydromodpy.calibration.protocols import (
    expand_calibration_protocol,
    options_the_recipe_already_runs,
)
from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.config_migration import fix_config_file, migrate_sealed_config_doc
from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.workflow.steps.prepare_solver.dispatch import portable_config_document
from tests.unit.calibration._factories import two_dim_space
from tests.unit.calibration._factories_search import fix_toml
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
    def test_each_stratum_is_hit_exactly_once_per_dimension(self) -> None:
        n = 12
        opt = build_optimizer("lhs", two_dim_space(), n_samples=n, seed=0)
        points = opt.ask(n=n)
        xs = [p.values["x"] for p in points]
        ys = [p.values["y"] for p in points]
        assert _strata_indices(xs, 0.0, 1.0, n) == list(range(n))
        assert _strata_indices(ys, -2.0, 2.0, n) == list(range(n))

    def test_log_transform_stratifies_log10_space(self) -> None:
        n = 10
        opt = build_optimizer("lhs", _logtwo_dim_space(), n_samples=n, seed=1)
        points = opt.ask(n=n)
        logs = [math.log10(p.values["k"]) for p in points]
        assert _strata_indices(logs, -6.0, -2.0, n) == list(range(n))

    def test_bounds_are_respected(self) -> None:
        opt = build_optimizer("lhs", two_dim_space(), n_samples=50, seed=2)
        for p in opt.ask(n=50):
            assert 0.0 <= p.values["x"] <= 1.0
            assert -2.0 <= p.values["y"] <= 2.0

    def test_normal_prior_is_refused_naming_the_parameter(self) -> None:
        space = ParameterSpace(
            [CalibParameter(name="theta", lower=0.0, upper=1.0, sampling="normal")]
        )
        with pytest.raises(ValueError, match="theta"):
            build_optimizer("lhs", space, n_samples=5, seed=0)

    def test_random_cd_optimization_keeps_the_stratification_guarantee(self) -> None:
        n = 12
        opt = build_optimizer("lhs", two_dim_space(), n_samples=n, seed=0, optimization="random-cd")
        points = opt.ask(n=n)
        xs = [p.values["x"] for p in points]
        assert _strata_indices(xs, 0.0, 1.0, n) == list(range(n))

    def test_lloyd_optimization_is_not_guaranteed_to_keep_every_stratum(self) -> None:
        # scipy's Lloyd relaxation trades the one-point-per-stratum guarantee
        # for better point spacing: this seed is a known case where several
        # strata of "x" are left unsampled, which is why "lloyd" is documented
        # as a best-effort post-process rather than an exact design.
        n = 12
        opt = build_optimizer("lhs", two_dim_space(), n_samples=n, seed=0, optimization="lloyd")
        points = opt.ask(n=n)
        xs = [p.values["x"] for p in points]
        assert _strata_indices(xs, 0.0, 1.0, n) != list(range(n))


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
    def test_ask_returns_batches_and_then_exhausts(self) -> None:
        opt = build_optimizer("lhs", two_dim_space(), n_samples=5, seed=0)
        first = opt.ask(n=3)
        assert len(first) == 3
        assert opt.converged() is False
        second = opt.ask(n=3)
        assert len(second) == 2
        assert opt.converged() is True
        assert opt.ask(n=1) == []

    def test_trial_ids_are_unique_and_monotonic(self) -> None:
        opt = build_optimizer("lhs", two_dim_space(), n_samples=6, seed=0)
        ids = [p.trial_id for p in opt.ask(n=3) + opt.ask(n=3)]
        assert ids == sorted(ids)
        assert len(set(ids)) == len(ids)

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


class TestBestCompleted:
    @pytest.mark.parametrize(
        ("rows", "expected"),
        [
            ([], None),
            ([(0, 1.0, "failed")], None),
            ([(0, 0.1, "failed"), (1, 3.0, "completed"), (2, 2.0, "completed")], 2),
            ([(0, 2.0, "completed"), (1, 2.0, "completed")], 0),
        ],
    )
    def test_the_lowest_completed_cost_wins_and_a_tie_keeps_the_first(self, rows, expected) -> None:
        history = [
            EvaluationResult(trial_id=trial_id, sim_id=None, cost=cost, status=status)
            for trial_id, cost, status in rows
        ]
        best = best_completed(history)
        assert (None if best is None else best.trial_id) == expected


class TestBudget:
    def test_auto_resolves_to_n_samples(self) -> None:
        opt = build_optimizer("lhs", two_dim_space(), n_samples=17, seed=0)
        assert resolve_budget(opt, "auto") == 17

    def test_written_max_trials_below_n_samples_is_refused(self) -> None:
        opt = build_optimizer("lhs", two_dim_space(), n_samples=17, seed=0)
        verdict = short_budget(opt.counted_budget, 10)
        assert verdict is not None
        severity, message = verdict
        assert severity == "error"
        assert "17" in message

    def test_written_max_trials_at_or_above_n_samples_is_accepted(self) -> None:
        opt = build_optimizer("lhs", two_dim_space(), n_samples=17, seed=0)
        assert short_budget(opt.counted_budget, 17) is None
        assert short_budget(opt.counted_budget, 30) is None


class TestMethodConfig:
    def test_n_samples_is_required(self) -> None:
        with pytest.raises(Exception):
            validate_method_kwargs("lhs", {})

    def test_n_samples_and_optimization_validate(self) -> None:
        cfg = validate_method_kwargs("lhs", {"n_samples": 20, "optimization": "random-cd"})
        assert isinstance(cfg, LhsMethodConfig)
        assert cfg.n_samples == 20
        assert cfg.optimization == "random-cd"

    def test_extra_key_is_refused(self) -> None:
        with pytest.raises(Exception, match="popsize"):
            validate_method_kwargs("lhs", {"n_samples": 10, "popsize": 5})

    def test_non_positive_n_samples_is_refused(self) -> None:
        with pytest.raises(Exception):
            validate_method_kwargs("lhs", {"n_samples": 0})


# From test_max_trials_is_the_only_search_budget.py
# ``max_trials`` is the one number that bounds a search.
#
# ``max_iter`` counted evaluations, and ``maxfev``, ``max_evaluations`` and
# gp_mapping's own ``max_iter`` counted them too, under four names that did not
# agree about what an iteration was. A key renamed or removed is refused with the
# name that replaces it, the doctor rewrites the file, and a sealed run config
# still reads.


PROTOCOL = "matching_hydrographic_network"


def _phase(**fields: object) -> CalibPhaseDecl:
    return CalibPhaseDecl.model_validate({"name": "sy", "parameters": ["Sy"], **fields})


def test_the_section_refuses_max_iter_and_names_max_trials() -> None:
    with pytest.raises(ValidationError, match=r"'max_iter' is not accepted any more: renamed") as e:
        CalibrationConfig.model_validate({"max_iter": 30})

    assert "'max_trials'" in str(e.value)
    assert "hmp doctor --fix-config" in str(e.value)
    assert CalibrationConfig.model_validate({"max_trials": 30}).max_trials == 30


def test_a_phase_refuses_max_iter_and_names_max_trials() -> None:
    with pytest.raises(ValidationError, match="renamed to 'max_trials'"):
        _phase(max_iter=30)

    assert _phase(max_trials=30).max_trials == 30
    assert _phase().max_trials is None
    assert _phase(max_trials="auto").max_trials == "auto"


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


@pytest.mark.parametrize("method", ["scipy_nelder_mead", "scipy_de"])
def test_maxiter_is_refused_because_an_iteration_is_not_an_evaluation(method: str) -> None:
    problem = method_options_problem(method, {"maxiter": 10})

    assert problem is not None
    assert "not an evaluation count" in problem
    assert "max_trials" in problem


def test_the_chain_length_of_da_mh_gp_has_its_own_name() -> None:
    problem = method_options_problem("da_mh_gp", {"max_iter": 100})

    assert problem is not None
    assert "chain_length" in problem
    assert validate_method_kwargs("da_mh_gp", {"chain_length": 100}).chain_length == 100


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


def test_the_doctor_renames_the_budgets_and_moves_the_options_into_them(tmp_path: Path) -> None:
    path, changes, document = fix_toml(
        tmp_path,
        "[calibration]\n"
        'method = "scipy_nelder_mead"\n'
        "max_iter = 60\n"
        "method_options = { maxfev = 25, xatol = 0.01 }\n"
        "[[calibration.phases]]\n"
        'name = "a"\n'
        'method = "cma_es"\n'
        'max_iter = "auto"\n'
        "method_options = { max_evaluations = 40, popsize = 4 }\n"
        "[[calibration.phases]]\n"
        'name = "b"\n'
        'method = "gp_mapping"\n'
        "method_options = { max_iter = 15, n_init = 5 }\n"
        "[[calibration.phases]]\n"
        'name = "c"\n'
        'method = "da_mh_gp"\n'
        "max_iter = 30\n"
        "method_options = { max_iter = 200 }\n"
        "[[calibration.phases]]\n"
        'name = "d"\n'
        'method = "scipy_de"\n'
        "method_options = { maxiter = 5 }\n"
        "[calibration.protocol]\n"
        'name = "matching_hydrographic_network"\n'
        "steady_max_iter = 20\n"
        "transient_max_iter = 90\n"
        'transient_method = "scipy_nelder_mead"\n'
        "transient_method_options = { maxfev = 50 }\n",
    )

    phases = {phase["name"]: phase for phase in document["phases"]}
    assert document["max_trials"] == 25
    assert document["method_options"] == {"xatol": 0.01}
    assert phases["a"]["max_trials"] == 40
    assert phases["a"]["method_options"] == {"popsize": 4}
    assert phases["b"]["max_trials"] == 15
    assert phases["b"]["method_options"] == {"n_init": 5}
    assert phases["c"]["max_trials"] == 30
    assert phases["c"]["method_options"] == {"chain_length": 200}
    assert phases["d"]["method_options"] == {"maxiter": 5}
    assert document["protocol"]["steady_max_trials"] == 20
    assert document["protocol"]["transient_max_trials"] == 50
    assert "transient_method_options" not in document["protocol"]
    assert any("not an evaluation count" in change and "[3]" in change for change in changes)
    assert "max_iter" not in path.read_text(encoding="utf-8")


def test_the_doctor_keeps_the_smaller_of_the_two_budgets(tmp_path: Path) -> None:
    _, _, document = fix_toml(
        tmp_path,
        '[calibration]\nmethod = "cma_es"\nmax_iter = 20\nmethod_options = { max_evaluations = 90 }\n',
    )

    assert document["max_trials"] == 20


def test_a_phase_takes_the_method_and_budget_of_the_section(tmp_path: Path) -> None:
    _, _, document = fix_toml(
        tmp_path,
        '[calibration]\nmethod = "scipy_nelder_mead"\nmax_trials = 50\n'
        '[[calibration.phases]]\nname = "a"\nmethod_options = { maxfev = 80 }\n'
        '[[calibration.phases]]\nname = "b"\nmethod_options = { maxfev = 30 }\n',
    )

    phases = document["phases"]
    assert [phase["max_trials"] for phase in phases] == [50, 30]
    assert all("method_options" not in phase for phase in phases)


def test_a_budget_option_without_a_method_is_left_with_the_reason(tmp_path: Path) -> None:
    path, changes, _ = fix_toml(tmp_path, "[calibration]\nmethod_options = { max_iter = 20 }\n")

    assert "max_iter = 20" in path.read_text(encoding="utf-8")
    assert any("method" in change and "left" in change for change in changes)


def test_a_sealed_document_reads_the_old_budget_keys_and_drops_the_old_options() -> None:
    doc = {
        "calibration": {
            "method": "gp_mapping",
            "max_iter": 50,
            "method_options": {"max_iter": 10, "n_init": 4},
            "phases": [
                {"name": "p", "method": "da_mh_gp", "method_options": {"max_iter": 80}},
                {"name": "q", "method": "scipy_nelder_mead", "method_options": {"maxfev": 9}},
            ],
            "protocol": {"steady_max_iter": 12},
        }
    }

    migrate_sealed_config_doc(doc)

    section = doc["calibration"]
    assert section["max_trials"] == 50
    assert section["method_options"] == {"n_init": 4}
    assert section["phases"][0]["method_options"] == {"chain_length": 80}
    assert "method_options" not in section["phases"][1]
    assert section["protocol"] == {"steady_max_trials": 12}


def test_a_frozen_protocol_run_with_the_old_budget_keys_reads_back(tmp_path: Path) -> None:
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

    replayed = HydroModPyConfig.from_toml(sealed)

    expected = [p.model_dump(mode="json") for p in cfg.calibration.phases]
    assert [p.model_dump(mode="json") for p in replayed.calibration.phases] == expected
    document = tomllib.loads(old)
    with pytest.raises(ConfigValidationError):
        HydroModPyConfig.from_dict(document, base_dir=project)
    assert (
        HydroModPyConfig.from_snapshot({**document, "workspace": {"project_root": str(project)}})
        .calibration.phases[0]
        .max_trials
        == cfg.calibration.phases[0].max_trials
    )


# From test_method_config.py
# Tests for the discriminated-union ``CalibrationMethodConfig``.
#
# A file writes ``method: str`` beside a free-form ``method_options`` table,
# which used to fail only at runtime when an option was foreign to the chosen
# method. The discriminated union promotes those failures to validation time
# and dumps a clear Pydantic error.


def test_grid_method_with_default_kwargs_validates() -> None:
    cfg = validate_method_kwargs("grid", {})
    assert isinstance(cfg, GridMethodConfig)
    assert cfg.method == "grid"
    assert cfg.points_per_dim is None


def test_cma_es_method_with_supported_kwargs_validates() -> None:
    cfg = validate_method_kwargs("cma_es", {"sigma0": 0.5, "popsize": 10, "restarts": 2})
    assert isinstance(cfg, CmaEsMethodConfig)
    assert cfg.sigma0 == 0.5
    assert cfg.popsize == 10
    assert cfg.restarts == 2


def test_optuna_method_with_sampler_validates() -> None:
    cfg = validate_method_kwargs("optuna", {"sampler": "tpe", "direction": "minimize"})
    assert isinstance(cfg, OptunaMethodConfig)
    assert cfg.sampler == "tpe"
    assert cfg.direction == "minimize"


def test_cma_es_method_rejects_optuna_kwarg() -> None:
    """Mixing ``method='cma_es'`` with the Optuna ``sampler`` kwarg must fail eagerly."""
    with pytest.raises(ValidationError) as excinfo:
        validate_method_kwargs("cma_es", {"sampler": "tpe"})
    assert "sampler" in str(excinfo.value).lower()


# From test_method_options.py
# The options of a calibration method are called ``method_options``, and load checked.
#
# They were ``optimizer_kwargs`` on a phase and on ``[calibration]``, and
# ``steady_engine_options`` / ``transient_engine_options`` on the protocol: Python
# jargon for one concept under two names. The old spellings are refused, with an
# error naming the new one. An option its method does not take is refused when
# the file loads, naming where it was written, instead of when that phase starts,
# after the phases before it have spent their budget.


def test_the_problem_names_the_foreign_key_and_what_the_method_takes() -> None:
    problem = method_options_problem("bisection", {"points_per_dim": 3})

    assert problem is not None
    assert "'bisection' does not take points_per_dim" in problem
    assert "bracket_expand, rel_tol, signed_component, sweep_points" in problem


def test_the_problem_names_a_value_of_the_wrong_type() -> None:
    problem = method_options_problem("bisection", {"sweep_points": "seven"})

    assert problem is not None
    assert "sweep_points = 'seven'" in problem


def test_options_the_method_takes_raise_no_problem() -> None:
    assert method_options_problem("bisection", {"sweep_points": 5}) is None
    assert method_options_problem("grid", {}) is None


def test_a_method_with_no_model_here_is_left_to_its_own_constructor() -> None:
    assert "a_plugin_engine" not in typed_methods()
    assert method_options_problem("a_plugin_engine", {"anything": 1}) is None


def test_a_phase_option_its_method_refuses_is_refused_at_load_with_the_phase() -> None:
    with pytest.raises(ValidationError, match="phase 'sy' method_options: 'grid' does not take"):
        _phase(method="grid", method_options={"rel_tol": 0.01})


def test_a_section_option_its_method_refuses_is_refused_at_load() -> None:
    with pytest.raises(ValidationError, match=r"\[calibration\] method_options: 'optuna'"):
        CalibrationConfig.model_validate({"method": "optuna", "method_options": {"popsize": 4}})


def test_a_protocol_stage_option_is_refused_under_the_key_the_file_wrote() -> None:
    with pytest.raises(ValidationError, match="transient_method_options: 'scipy_nelder_mead'"):
        CalibrationProtocolDecl.model_validate(
            {"name": PROTOCOL, "transient_method_options": {"sweep_points": 7}}
        )


@pytest.mark.parametrize(
    ("model", "old", "new"),
    [
        (CalibPhaseDecl, "optimizer_kwargs", "method_options"),
        (CalibrationConfig, "optimizer_kwargs", "method_options"),
        (CalibrationProtocolDecl, "steady_engine_options", "steady_method_options"),
        (CalibrationProtocolDecl, "transient_engine_options", "transient_method_options"),
    ],
)
def test_an_old_name_of_the_method_options_is_refused_with_the_new_one(model, old, new) -> None:
    document = {"name": PROTOCOL} if model is CalibrationProtocolDecl else {"method": "grid"}
    if model is CalibPhaseDecl:
        document["name"] = "sy"

    with pytest.raises(
        ValidationError, match=rf"'{old}' is not accepted any more: renamed to '{new}'"
    ):
        model.model_validate({**document, old: {"sweep_points": 5}})


def test_the_schema_carries_the_new_names_as_user_keys_and_not_the_old_ones() -> None:
    schema = CalibrationConfig.model_json_schema()
    phase = schema["$defs"]["CalibPhaseDecl"]["properties"]
    protocol = schema["$defs"]["MatchingHydrographicNetworkOptions"]["properties"]

    assert schema["properties"]["method_options"]["x-hmp-profile"] == "user"
    assert phase["method_options"]["x-hmp-profile"] == "user"
    assert protocol["steady_method_options"]["x-hmp-profile"] == "user"
    assert protocol["transient_method_options"]["x-hmp-profile"] == "user"
    for properties in (schema["properties"], phase, protocol):
        assert not [key for key in properties if "optimizer_kwargs" in key]
        assert not [key for key in properties if "engine_options" in key]
    assert "model_legacy_keys" not in str(schema)
    # The old names survive only as the renames the reference lists.
    assert phase["method_options"]["renamed_from"] == ["calibration.phases.optimizer_kwargs"]


def test_the_protocol_writes_its_stage_options_as_method_options() -> None:
    document = {
        "simulation": {"time": {"start_datetime": "2000-01-01", "end_datetime": "2002-12-31"}},
        "data": {"hydrometry": {"sources": [{"station_ids": ["G1"]}]}},
        "calibration": {
            "protocol": {"name": PROTOCOL, "steady_method_options": {"sweep_points": 5}},
            "parameters": {"K": {}, "Sy": {}},
            "outputs": {"streams": {"support": "network", "stream_geometry_path": "streams.gpkg"}},
        },
    }

    phases = expand_calibration_protocol(document)["calibration"]["phases"]

    assert phases[0]["method_options"] == {"sweep_points": 5}
    assert "optimizer_kwargs" not in phases[0]


def test_the_preflight_names_the_phase_whose_options_its_method_refuses() -> None:
    """A configuration assembled without validation still meets the check."""

    phase = CalibPhaseDecl.model_construct(
        name="transient_storage",
        parameters=["Sy"],
        method="scipy_nelder_mead",
        method_options={"sweep_points": 7},
    )
    calibration = CalibrationConfig.model_construct(parameters={}, phases=[phase])

    findings = [item for item in _check_engines(calibration) if item.severity == "error"]

    assert len(findings) == 1
    assert findings[0].where == "[[calibration.phases]] 'transient_storage'"
    assert "'scipy_nelder_mead' does not take sweep_points" in findings[0].detail


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


def test_another_value_is_away_from_the_recipe() -> None:
    assert _same(steady_method_options={"sweep_points": 5}) == frozenset()


def test_the_bisection_s_own_precision_written_out_runs_as_the_recipe() -> None:
    assert _same(steady_precision=0.01) == {"steady_precision"}
    assert _same(steady_precision=0.05) == frozenset()


def test_a_precision_the_simplex_reads_as_a_width_is_always_a_choice() -> None:
    """Nelder-Mead writes its xatol from the bounds: no default equals a written number."""
    assert _same(transient_precision=0.05) == frozenset()


def test_the_spin_up_window_written_out_runs_as_the_recipe() -> None:
    assert _same(window={"start": "2001-01-01"}) == {"window"}
    assert _same(window={"start": "2001-01-01", "end": "2002-12-31"}) == {"window"}


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
