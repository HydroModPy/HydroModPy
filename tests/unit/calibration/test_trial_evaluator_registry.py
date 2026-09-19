"""What turns a parameter sample into a cost is named, not imported.

Before this, the production calibration path had exactly one forward model and
no way to name another. The ask/tell loop has always taken any callable -- eight
construction sites of this repository already pass one that is not the pipeline
-- but from a project TOML, through ``hmp calibrate``, the evaluator was built in
one place and could be nothing else. The one published injection point,
``metric_fn``, applies after the solve, over a context the pipeline has already
produced: it changes how a run is scored, never what runs.

Five gates, and they answer different questions.

1. The registry itself: what it resolves, what it refuses, and what it binds.
2. At the document: a file naming an evaluator this installation cannot serve is
   refused while the TOML is read, with the list of what it does serve.
3. Behavioural, end to end: a registered evaluator that runs no HydroModPy model
   drives a whole search through ``run_calibration_core``, and the preparation of
   a trial context is never paid for.
4. What is refused rather than silently wrong: promotion, a linearized width and
   a staged protocol all need the model the evaluator replaced.
5. Derived from the source: the ask/tell engine names no evaluator, and the two
   functions that launch a pipeline trial are the two that are allowed to.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.evaluation import TrialOutcome, TrialRequest
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialEvaluator, evaluator_members
from hydromodpy.core.exceptions import CalibrationError

pytestmark = pytest.mark.fast

REPO_ROOT = Path(__file__).resolve().parents[3]
"""Anchored on this file. A tree scan that reads the cwd scans nothing from tests/."""


class _Quadratic:
    """An evaluator with no model behind it, which is the whole point."""

    evaluator_id = "test_quadratic"
    needs_prepared_model = False

    def __init__(self, *, target: float = 5e-3) -> None:
        self.target = target

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        k = float(request.values["k"])
        return TrialOutcome(cost=(k - self.target) ** 2, status="completed", duration_s=0.0)


@pytest.fixture
def registered_quadratic():
    """Register :class:`_Quadratic` for one test and take it out again."""
    evaluation_registry.register(_Quadratic, replace=True)
    try:
        yield _Quadratic
    finally:
        evaluation_registry.unregister(_Quadratic.evaluator_id)


def _config(**overrides: object) -> CalibrationConfig:
    payload: dict[str, object] = {
        "method": "grid",
        "max_iter": 5,
        "parameters": {"k": {"path": "flow.properties.k_aquifer", "bounds": [1e-6, 1e-2]}},
        "optimizer_kwargs": {"points_per_dim": 5},
    }
    payload.update(overrides)
    return CalibrationConfig.model_validate(payload)


# --------------------------------------------------------------------------
# 1. The registry
# --------------------------------------------------------------------------


class TestTheRegistryResolves:
    def test_a_document_that_names_none_gets_the_pipeline(self) -> None:
        assert evaluation_registry.get(None).evaluator_id == "hydromodpy_pipeline"
        assert evaluation_registry.DEFAULT_EVALUATOR_ID == "hydromodpy_pipeline"

    def test_an_unknown_name_names_the_group_a_third_party_joins_on(self) -> None:
        with pytest.raises(CalibrationError) as excinfo:
            evaluation_registry.get("no_such_evaluator")

        message = str(excinfo.value)
        assert "no_such_evaluator" in message
        assert "hydromodpy_pipeline" in message
        assert evaluation_registry.ENTRY_POINT_GROUP in message

    def test_the_declaration_is_read_without_building_anything(self, registered_quadratic) -> None:
        assert evaluation_registry.needs_prepared_model("hydromodpy_pipeline") is True
        assert evaluation_registry.needs_prepared_model("test_quadratic") is False

    def test_an_installed_evaluator_joins_the_list(self, registered_quadratic) -> None:
        assert "test_quadratic" in evaluation_registry.list_evaluator_ids()
        assert "test_quadratic" not in evaluation_registry.builtin_evaluator_ids()
        assert evaluation_registry.is_registered("test_quadratic")


class TestTheRegistryRefuses:
    def test_a_class_declaring_no_id_cannot_be_held_by_a_registry_keyed_on_one(self) -> None:
        class Nameless:
            needs_prepared_model = False

            def evaluate(self, request):  # pragma: no cover - never reached
                raise AssertionError

        with pytest.raises(TypeError, match="evaluator_id"):
            evaluation_registry.register(Nameless)

    def test_a_class_that_does_not_satisfy_the_port_is_named_member_by_member(self) -> None:
        class Halfway:
            evaluator_id = "halfway"
            needs_prepared_model = False

        with pytest.raises(TypeError) as excinfo:
            evaluation_registry.register(Halfway)

        assert "evaluate" in str(excinfo.value)

    def test_a_member_bound_to_none_is_as_missing_as_an_absent_one(self) -> None:
        """It passes ``hasattr`` and fails the first call, so the registry is the door."""

        class Hollow:
            evaluator_id = "hollow"
            needs_prepared_model = False
            evaluate = None

        with pytest.raises(TypeError, match="evaluate"):
            evaluation_registry.register(Hollow)

    def test_a_class_cannot_claim_the_name_this_build_ships(self, monkeypatch) -> None:
        """Before the first lookup imports it, a built-in is a declaration only.

        ``_BUILTIN_PATHS`` is the declaration and ``_REGISTRY`` is what has been
        imported. A guard reading the second alone left ``hydromodpy_pipeline``
        free until something resolved it, so a class could claim it and every
        document naming no evaluator would run that class -- keyed, by the
        resolved id, exactly like the pipeline it displaced.

        The import cache is emptied of that one id here on purpose: it is the
        state of a fresh process, and asserting this without it passes for the
        wrong reason as soon as another test in the file has resolved the
        default first.
        """
        from hydromodpy.calibration.evaluation.pipeline_evaluator import (
            PipelineTrialEvaluator,
        )

        monkeypatch.delitem(
            evaluation_registry._REGISTRY,
            evaluation_registry.DEFAULT_EVALUATOR_ID,
            raising=False,
        )
        assert evaluation_registry.DEFAULT_EVALUATOR_ID in (
            evaluation_registry.builtin_evaluator_ids()
        )

        class Hijack:
            evaluator_id = "hydromodpy_pipeline"
            needs_prepared_model = False

            def evaluate(self, request):  # pragma: no cover - never reached
                raise AssertionError

        with pytest.raises(ValueError, match="already registered"):
            evaluation_registry.register(Hijack)

        assert evaluation_registry.get(None) is PipelineTrialEvaluator

    def test_an_id_held_by_a_falsy_class_is_still_held(self) -> None:
        """A class is truthy unless its metaclass says otherwise.

        ``_REGISTRY.get(id) or _BUILTIN_PATHS.get(id)`` read such a class as
        absent, so the next registration displaced it without ``replace=True``.
        The shape that introduced this was the fix for the reserved-id hole; the
        two lookups are now separate and compared against ``None``.
        """

        class Falsy(type):
            def __bool__(cls) -> bool:
                return False

        class Held(metaclass=Falsy):
            evaluator_id = "test_falsy_evaluator"
            needs_prepared_model = False

            def evaluate(self, request):  # pragma: no cover - never reached
                raise AssertionError

        class Usurper:
            evaluator_id = "test_falsy_evaluator"
            needs_prepared_model = False

            def evaluate(self, request):  # pragma: no cover - never reached
                raise AssertionError

        evaluation_registry.register(Held)
        try:
            assert not bool(Held)
            with pytest.raises(ValueError, match="already registered"):
                evaluation_registry.register(Usurper)
            assert evaluation_registry.get("test_falsy_evaluator") is Held
        finally:
            evaluation_registry.unregister("test_falsy_evaluator")

    def test_a_taken_id_is_not_silently_substituted(self, registered_quadratic) -> None:
        class Other:
            evaluator_id = "test_quadratic"
            needs_prepared_model = False

            def evaluate(self, request):  # pragma: no cover - never reached
                raise AssertionError

        with pytest.raises(ValueError, match="already registered"):
            evaluation_registry.register(Other)


class TestTheRegistryBindsOnlyWhatIsNamed:
    def test_an_option_no_parameter_names_never_arrives(self, registered_quadratic) -> None:
        built = evaluation_registry.create(
            "test_quadratic",
            target=1.0,
            trial_ctx=object(),
            cfg=object(),
            metric_fn=object(),
        )

        assert isinstance(built, _Quadratic)
        assert built.target == 1.0

    def test_the_port_members_come_from_the_protocol(self) -> None:
        assert evaluator_members() == ("evaluate", "evaluator_id", "needs_prepared_model")
        assert isinstance(_Quadratic(), TrialEvaluator)


# --------------------------------------------------------------------------
# 2. At the document
# --------------------------------------------------------------------------


class TestTheDocumentRefusesAnEvaluatorNobodyInstalled:
    def test_the_refusal_happens_while_the_section_is_read(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _config(evaluator="not_installed_here")

        message = str(excinfo.value)
        assert "calibration.evaluator" in message
        assert "not_installed_here" in message
        assert "hydromodpy_pipeline" in message
        assert evaluation_registry.ENTRY_POINT_GROUP in message

    def test_unset_means_whatever_this_build_defaults_to(self) -> None:
        assert _config().evaluator is None

    def test_an_installed_name_is_accepted(self, registered_quadratic) -> None:
        assert _config(evaluator="test_quadratic").evaluator == "test_quadratic"


# --------------------------------------------------------------------------
# 3. A whole search on an evaluator that runs no HydroModPy model
# --------------------------------------------------------------------------


class TestASearchRunsOnANamedEvaluator:
    def test_the_loop_finds_the_optimum_of_a_model_hydromodpy_never_ran(
        self, registered_quadratic, tmp_path
    ) -> None:
        from hydromodpy.calibration.runners.cli_runner import run_calibration_core
        from hydromodpy.calibration.runners.state import space_from_config

        cfg = _config(evaluator="test_quadratic")
        report = run_calibration_core(
            cfg,
            None,
            workspace=tmp_path,
            space=space_from_config(cfg),
        ).to_dict()

        assert report["n_iterations"] == 5
        # Five grid points over [1e-6, 1e-2]; the third sits within 1e-6 of the
        # target the evaluator was built with.
        assert report["best_parameters"]["k"] == pytest.approx(5e-3, abs=1e-5)
        assert report["best_objective"] < 1e-11

    def test_the_setup_of_the_model_it_replaces_is_never_paid_for(
        self, registered_quadratic, monkeypatch, tmp_path
    ) -> None:
        """``prepare_trials`` is the whole geographic, mesh and data prefix."""
        import hydromodpy.calibration.runners.cli_runner as cli_runner

        def _explode(*args, **kwargs):
            raise AssertionError("prepare_trials was called for a model-free evaluator")

        monkeypatch.setattr(cli_runner, "prepare_trials", _explode)

        document = tmp_path / "calibration.toml"
        document.write_text(
            "[calibration]\n"
            'evaluator = "test_quadratic"\n'
            'method = "grid"\n'
            "max_iter = 3\n"
            "optimizer_kwargs = { points_per_dim = 3 }\n"
            "[calibration.parameters.k]\n"
            'path = "flow.properties.k_aquifer"\n'
            "bounds = [1e-6, 1e-2]\n"
        )

        report = cli_runner.run_calibration_cli(document, project="test", return_report=True)

        assert report.to_dict()["n_iterations"] == 3

    def test_the_project_root_the_document_declares_is_still_honoured(
        self, registered_quadratic, tmp_path
    ) -> None:
        """Without a prepared context there is nothing to read the root off, so the file is asked.

        Falling through to the file's directory would put the session journal of
        a model-free run somewhere else than the same document run on the
        pipeline evaluator, over the same declared root.
        """
        from hydromodpy.calibration.runners.cli_runner import run_calibration_cli

        root = tmp_path / "declared_root"
        root.mkdir()
        document = tmp_path / "rooted.toml"
        document.write_text(
            "[workspace]\n"
            f'project_root = "{root.as_posix()}"\n'
            "[calibration]\n"
            'evaluator = "test_quadratic"\n'
            'method = "grid"\n'
            "max_iter = 3\n"
            "optimizer_kwargs = { points_per_dim = 3 }\n"
            "[calibration.parameters.k]\n"
            'path = "flow.properties.k_aquifer"\n'
            "bounds = [1e-6, 1e-2]\n"
        )

        report = run_calibration_cli(document, project="test", return_report=True)

        assert Path(report.to_dict()["workspace"]) == root
        assert not list(tmp_path.glob("*.duckdb"))

    @staticmethod
    def _cache_context(evaluator: str | None) -> dict:
        from hydromodpy.calibration.runners.state import (
            build_cache_context,
            override_paths,
            space_from_config,
        )

        cfg = _config(evaluator=evaluator)
        return build_cache_context(
            cfg=cfg,
            trial_ctx=None,
            space=space_from_config(cfg),
            override_paths=override_paths(cfg),
            objective_entrypoint=None,
        )

    def test_the_evaluator_name_scopes_a_cache_hit(self, registered_quadratic) -> None:
        """Two evaluators asked the same parameters return different costs."""
        from hydromodpy.calibration.optim.cache import params_hash

        values = {"k": 5e-3}
        default = self._cache_context(None)
        other = self._cache_context("test_quadratic")

        assert params_hash(values, context=default) != params_hash(values, context=other)

    def test_naming_the_default_out_loud_is_the_same_key_as_leaving_it_unset(self) -> None:
        """Both resolve to one class, so both must resolve to one key."""
        from hydromodpy.calibration.optim.cache import params_hash

        values = {"k": 5e-3}
        unset = self._cache_context(None)
        spelled_out = self._cache_context("hydromodpy_pipeline")

        assert params_hash(values, context=unset) == params_hash(values, context=spelled_out)

    def test_a_pipeline_calibration_keys_as_if_the_field_had_never_been_added(self) -> None:
        """The field must not re-solve every trial of every calibration that predates it.

        The payload hashed is the whole calibration section, so a key present in
        it for every document would move the hash of every run computed before
        this field existed. The default therefore writes nothing.
        """
        for evaluator in (None, "hydromodpy_pipeline"):
            payload = self._cache_context(evaluator)["calibration"]

            assert "evaluator" not in payload

    def test_a_named_evaluator_does_write_itself_into_the_key(self, registered_quadratic) -> None:
        assert self._cache_context("test_quadratic")["calibration"]["evaluator"] == (
            "test_quadratic"
        )


# --------------------------------------------------------------------------
# 4. What is refused rather than silently wrong
# --------------------------------------------------------------------------


class TestWhatNeedsTheModelIsRefusedNotFaked:
    def test_promotion_is_refused_before_the_search_not_after_it(
        self, registered_quadratic, tmp_path
    ) -> None:
        from hydromodpy.calibration.runners.cli_runner import run_calibration_core
        from hydromodpy.calibration.runners.state import space_from_config

        cfg = _config(evaluator="test_quadratic", save_runs="best_n", save_best_n=1)
        with pytest.raises(CalibrationError) as excinfo:
            run_calibration_core(cfg, None, workspace=tmp_path, space=space_from_config(cfg))

        assert "save_runs" in str(excinfo.value)

    def test_a_staged_protocol_is_refused_because_a_freeze_would_reach_nothing(
        self, registered_quadratic, tmp_path
    ) -> None:
        from hydromodpy.calibration.runners.staged_runner import run_staged_calibration

        document = tmp_path / "staged.toml"
        document.write_text(
            "[calibration]\n"
            'evaluator = "test_quadratic"\n'
            'method = "grid"\n'
            "max_iter = 2\n"
            "[calibration.parameters.k]\n"
            'path = "flow.properties.k_aquifer"\n'
            "bounds = [1e-6, 1e-2]\n"
            "[[calibration.phases]]\n"
            'name = "one"\n'
            'parameters = ["k"]\n'
        )

        with pytest.raises(CalibrationError) as excinfo:
            run_staged_calibration(document)

        assert "phases" in str(excinfo.value)

    def test_a_linearized_width_is_refused_because_there_is_nothing_to_perturb(
        self, registered_quadratic, tmp_path
    ) -> None:
        from hydromodpy.calibration.runners.cli_runner import run_calibration_cli

        document = tmp_path / "linearized.toml"
        document.write_text(
            "[calibration]\n"
            'evaluator = "test_quadratic"\n'
            'method = "grid"\n'
            "max_iter = 3\n"
            "optimizer_kwargs = { points_per_dim = 3 }\n"
            "[calibration.uncertainty]\n"
            'method = "linearized"\n'
            "perturbation = 0.01\n"
            "[calibration.parameters.k]\n"
            'path = "flow.properties.k_aquifer"\n'
            "bounds = [1e-6, 1e-2]\n"
        )

        with pytest.raises(CalibrationError) as excinfo:
            run_calibration_cli(document, project="test")

        assert "linearized" in str(excinfo.value)


# --------------------------------------------------------------------------
# 5. Derived from the source
# --------------------------------------------------------------------------


LAUNCHERS_ALLOWED_TO_RUN_A_PIPELINE_TRIAL = {
    # The evaluator the registry resolves for "hydromodpy_pipeline". This is the
    # one the ask/tell loop reaches, and the only one.
    "calibration/evaluation/pipeline_evaluator.py:evaluate",
    # Not an evaluator: it perturbs the optimum once per parameter to read a
    # Jacobian off it, and it is refused outright when no model was prepared.
    "calibration/runners/cli_runner.py:_simulate",
}
"""Named by file and enclosing function, not by function name alone.

A future re-hardwire in another module would be free to call its closure
``_simulate`` too, and a set keyed on the bare name would not see it.
"""


def _functions_calling(name: str) -> set[str]:
    """Return ``<path>:<enclosing function>`` for every call of *name* in ``hydromodpy/``."""
    callers: set[str] = set()
    scanned = 0
    for path in sorted((REPO_ROOT / "hydromodpy").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        scanned += 1
        enclosing: dict[ast.AST, str] = {}
        stack: list[ast.AST] = [tree]
        while stack:
            node = stack.pop()
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    enclosing[child] = child.name
                else:
                    enclosing[child] = enclosing.get(node, "<module>")
                stack.append(child)
        relative = path.relative_to(REPO_ROOT / "hydromodpy").as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if called == name:
                callers.add(f"{relative}:{enclosing.get(node, '<module>')}")
    # Anti-vacuity: the tree holds about 1575 modules, and a scan pointed at the
    # wrong root satisfies an empty assertion without reading any of them.
    assert scanned > 1000, f"the scan read {scanned} files, so it proves nothing"
    return callers


class TestNothingReHardwiresTheForwardModel:
    def test_only_the_two_named_launchers_run_a_pipeline_trial(self) -> None:
        assert _functions_calling("run_trial_light") == (LAUNCHERS_ALLOWED_TO_RUN_A_PIPELINE_TRIAL)

    def test_the_ask_tell_engine_names_no_evaluator(self) -> None:
        """The loop must not learn what an evaluator id is. That is the contract."""
        from hydromodpy.calibration.optim import engine

        source = inspect.getsource(engine)

        assert "evaluator_id" not in source
        assert "evaluation.registry" not in source
        assert "hydromodpy_pipeline" not in source

    def test_the_in_tree_evaluator_is_built_by_the_registry_and_by_nobody_else(self) -> None:
        constructions = _functions_calling("PipelineTrialEvaluator")

        assert constructions == set()
