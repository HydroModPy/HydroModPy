"""Tests of `evaluation.registry`."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.optim import engine
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from hydromodpy.calibration.runners.search import run_calibration_core
from hydromodpy.calibration.runners.staged_runner import run_staged_calibration
from hydromodpy.calibration.runners.state import (
    build_cache_context,
    override_paths,
    space_from_config,
)
from hydromodpy.core.exceptions import CalibrationError

# From test_trial_evaluator_registry.py
# What turns a parameter sample into a cost is named, not imported.
#
# Before evaluators were named at all, the production calibration path built one
# evaluator and could be nothing else. The ask/tell loop has always taken any
# callable -- eight construction sites of this repository already pass one that
# is not the pipeline -- and the scored-forward route is gone with it, folded
# into the solver backends of 2.0.0. The one published injection point besides
# the pipeline evaluator, a metric function, applies after the solve, over a
# context the pipeline has already produced: it changes how a run is scored,
# never what runs.
#
# Five gates, and they answer different questions.
#
# 1. The registry itself: what it resolves, what it refuses, and what it binds.
# 2. At the document: a file naming an evaluator this installation cannot serve is
#    refused while the TOML is read, with the list of what it does serve.
# 3. Behavioral, end to end: a registered evaluator that runs no HydroModPy model
#    drives a whole search through ``run_calibration_core``, and the preparation of
#    a trial context is never paid for.
# 4. What is refused rather than silently wrong: promotion, a linearized width and
#    a staged protocol all need the model the evaluator replaced.
# 5. Derived from the source: the ask/tell engine names no evaluator, and the two
#    functions that launch a pipeline trial are the two that are allowed to.

pytestmark = pytest.mark.fast


def _session(project_root: Path):
    """An open session journal under ``project_root``, for a search run without a file."""

    session_dir = project_root / "sessions" / "probe"
    session_dir.mkdir(parents=True, exist_ok=True)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(
        session_id="a" * 32,
        case_id="probe",
        site=None,
        project=project_root.name,
        config_hash="c" * 64,
        hydromodpy_version="2.0.0a5",
        method="grid",
        cost_name="rmse",
        bounds={},
        windows={},
    )
    return persistence


REPO_ROOT = Path(__file__).resolve().parents[3]


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
    evaluation_registry.evaluators.register(_Quadratic, replace=True)
    try:
        yield _Quadratic
    finally:
        evaluation_registry.evaluators.unregister(_Quadratic.evaluator_id)


def _config(**overrides: object) -> CalibrationConfig:
    payload: dict[str, object] = {
        "method": "grid",
        "max_trials": 5,
        "parameters": {"k": {"path": "flow.properties.k_aquifer", "bounds": [1e-6, 1e-2]}},
        "method_options": {"points_per_dim": 5},
    }
    payload.update(overrides)
    return CalibrationConfig.model_validate(payload)


def _document(path: Path, max_trials: int, tail: str = "", options: bool = True) -> Path:
    """Write a model-free grid document over ``k``; ``tail`` adds sections after the header."""
    path.write_text(
        "[calibration]\n"
        'evaluator = "test_quadratic"\n'
        'method = "grid"\n'
        f"max_trials = {max_trials}\n"
        + ("method_options = { points_per_dim = 3 }\n" if options else "")
        + tail
        + "[calibration.parameters.k]\n"
        'path = "flow.properties.k_aquifer"\n'
        "bounds = [1e-6, 1e-2]\n"
        + ('[[calibration.phases]]\nname = "one"\nparameters = ["k"]\n' if not options else "")
    )
    return path


#


# --------------------------------------------------------------------------
# 1. The registry
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 2. At the document
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 3. A whole search on an evaluator that runs no HydroModPy model
# --------------------------------------------------------------------------
class TestASearchRunsOnANamedEvaluator:
    def test_the_loop_finds_the_optimum_of_a_model_hydromodpy_never_ran(
        self, registered_quadratic, tmp_path
    ) -> None:

        cfg = _config(evaluator="test_quadratic")
        report = run_calibration_core(
            cfg,
            None,
            persistence=_session(tmp_path),
            space=space_from_config(cfg),
            project_root=tmp_path,
        ).to_dict()

        assert report["n_trials"] == 5
        # Five grid points over [1e-6, 1e-2]; the third sits within 1e-6 of the
        # target the evaluator was built with.
        assert report["best_parameters"]["k"] == pytest.approx(5e-3, abs=1e-5)
        assert report["best_cost"] < 1e-11

    @staticmethod
    def _cache_context(evaluator: str | None) -> dict:
        cfg = _config(evaluator=evaluator)
        return build_cache_context(
            cfg=cfg,
            trial_ctx=None,
            space=space_from_config(cfg),
            override_paths=override_paths(cfg),
            objective_entrypoint=None,
        )


# --------------------------------------------------------------------------
# 4. What is refused rather than silently wrong
# --------------------------------------------------------------------------
class TestWhatNeedsTheModelIsRefusedNotFaked:
    def test_promotion_is_refused_before_the_search_not_after_it(
        self, registered_quadratic, tmp_path
    ) -> None:

        cfg = _config(evaluator="test_quadratic", save_runs="best_n", save_best_n=1)
        with pytest.raises(CalibrationError) as excinfo:
            run_calibration_core(
                cfg,
                None,
                persistence=_session(tmp_path),
                space=space_from_config(cfg),
                project_root=tmp_path,
            )

        assert "save_runs" in str(excinfo.value)

    @pytest.mark.parametrize(
        ("options", "metric_fn"),
        [({"evaluator": "test_quadratic"}, None), ({}, lambda *_, **__: (0.0, {}))],
        ids=["another_evaluator", "a_metric_function"],
    )
    def test_a_validation_window_nothing_would_score_is_refused(
        self, registered_quadratic, tmp_path, options, metric_fn
    ) -> None:
        cfg = _config(
            window={"end": "2001-12-31"},
            validation_window={"start": "2002-01-01", "end": "2002-12-31"},
            **options,
        )
        with pytest.raises(CalibrationError, match="validation_window"):
            run_calibration_core(
                cfg,
                None,
                persistence=_session(tmp_path),
                space=space_from_config(cfg),
                project_root=tmp_path,
                metric_fn=metric_fn,
            )

    def test_a_staged_protocol_is_refused_because_a_freeze_would_reach_nothing(
        self, registered_quadratic, tmp_path
    ) -> None:
        document = _document(tmp_path / "staged.toml", 2, options=False)

        with pytest.raises(CalibrationError) as excinfo:
            run_staged_calibration(document)

        assert "phases" in str(excinfo.value)

    def test_a_linearized_width_is_refused_because_there_is_nothing_to_perturb(
        self, registered_quadratic, tmp_path
    ) -> None:
        document = _document(
            tmp_path / "linearized.toml",
            3,
            tail='[calibration.uncertainty]\nmethod = "linearized"\nperturbation = 0.01\n',
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
    "calibration/runners/pipeline_evaluator.py:evaluate",
    # Not an evaluator: it perturbs the optimum once per parameter to read a
    # Jacobian off it, and it is refused outright when no model was prepared.
    "calibration/runners/search.py:evaluate",
}


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


class TestNothingReHardwiresTheChoiceOfEvaluator:
    def test_only_the_two_named_launchers_run_a_pipeline_trial(self) -> None:
        assert _functions_calling("run_trial_light") == (LAUNCHERS_ALLOWED_TO_RUN_A_PIPELINE_TRIAL)

    def test_the_ask_tell_engine_names_no_evaluator(self) -> None:
        """The loop must not learn what an evaluator id is. That is the contract."""

        source = inspect.getsource(engine)

        assert "evaluator_id" not in source
        assert "evaluation.registry" not in source
        assert "hydromodpy_pipeline" not in source

    def test_the_in_tree_evaluator_is_built_by_the_registry_and_by_nobody_else(self) -> None:
        constructions = _functions_calling("PipelineTrialEvaluator")

        assert constructions == set()
