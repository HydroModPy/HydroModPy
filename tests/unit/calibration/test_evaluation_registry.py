"""The registry of trial evaluators, the thing that turns a parameter sample into a cost.

A search runs on any registered evaluator without preparing a HydroModPy model.
What needs the model (promotion, a validation window, phases, a linearized width) is
refused, and the ask/tell engine names no evaluator.
"""

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
from hydromodpy.calibration.runners.state import space_from_config
from hydromodpy.core.exceptions import CalibrationError

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


def run_core(cfg, tmp_path, **extra):
    return run_calibration_core(
        cfg,
        None,
        persistence=_session(tmp_path),
        space=space_from_config(cfg),
        project_root=tmp_path,
        **extra,
    )


def test_search_finds_the_optimum_without_a_model(registered_quadratic, tmp_path) -> None:
    report = run_core(_config(evaluator="test_quadratic"), tmp_path).to_dict()

    assert report["n_trials"] == 5
    # Five grid points over [1e-6, 1e-2]; the third sits within 1e-6 of the target.
    assert report["best_parameters"]["k"] == pytest.approx(5e-3, abs=1e-5)
    assert report["best_cost"] < 1e-11


def test_promotion_is_refused_before_the_search(registered_quadratic, tmp_path) -> None:
    cfg = _config(evaluator="test_quadratic", save_runs="best_n", save_best_n=1)

    with pytest.raises(CalibrationError, match="save_runs"):
        run_core(cfg, tmp_path)


@pytest.mark.parametrize(
    ("options", "metric_fn"),
    [({"evaluator": "test_quadratic"}, None), ({}, lambda *_, **__: (0.0, {}))],
    ids=["another evaluator", "a metric function"],
)
def test_validation_window_nothing_scores_is_refused(
    registered_quadratic, tmp_path, options, metric_fn
) -> None:
    cfg = _config(
        window={"end": "2001-12-31"},
        validation_window={"start": "2002-01-01", "end": "2002-12-31"},
        **options,
    )

    with pytest.raises(CalibrationError, match="validation_window"):
        run_core(cfg, tmp_path, metric_fn=metric_fn)


def test_staged_protocol_is_refused(registered_quadratic, tmp_path) -> None:
    document = _document(tmp_path / "staged.toml", 2, options=False)

    with pytest.raises(CalibrationError, match="phases"):
        run_staged_calibration(document)


def test_linearized_width_is_refused(registered_quadratic, tmp_path) -> None:
    tail = '[calibration.uncertainty]\nmethod = "linearized"\nperturbation = 0.01\n'
    document = _document(tmp_path / "linearized.toml", 3, tail=tail)

    with pytest.raises(CalibrationError, match="linearized"):
        run_calibration_cli(document, project="test")


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


def test_only_two_launchers_run_a_pipeline_trial() -> None:
    assert _functions_calling("run_trial_light") == LAUNCHERS_ALLOWED_TO_RUN_A_PIPELINE_TRIAL


def test_engine_names_no_evaluator() -> None:
    source = inspect.getsource(engine)

    assert "evaluator_id" not in source
    assert "evaluation.registry" not in source
    assert "hydromodpy_pipeline" not in source


def test_pipeline_evaluator_is_built_by_the_registry_only() -> None:
    assert _functions_calling("PipelineTrialEvaluator") == set()
