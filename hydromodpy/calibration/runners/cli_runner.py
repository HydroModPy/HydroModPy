"""CLI entry point ``hmp calibrate <calibration.toml>``.

The workflow of a calibration without phases:

1. Load the TOML and validate the ``[calibration]`` section into a
   :class:`CalibrationConfig`, with the defaults of the project written in
   (``[site] gauge`` as the station, ``[metrics] window`` as the scoring window).
2. Name the case and reserve ``sessions/<case>/``; freeze the resolved
   document there as ``config.toml``; open the journal.
3. Prepare the downstream pipeline once via :func:`prepare_trials` when the
   resolved evaluator declares it needs one.
4. Drive the ask/tell loop through :class:`CalibrationEngine`, which calls the
   evaluator once per suggestion. Every trial goes to ``trials.jsonl``.
5. Promote the trials ``save_runs`` names, once, after the last restart: the
   best one to ``runs/<case>/``, the others under ``sessions/<case>/trials/``.
6. Close the session: ``session.json``, ``outcome.json``, ``README.md``.

The reading of the document is in ``document.py``, the scope of the session in
``session_scope.py`` and the loop in ``search.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.runners.document import (
    load_calibration_document,
    refuse_an_objective_that_is_not_an_entry_point,
    with_its_method,
)
from hydromodpy.calibration.runners.search import run_single_search
from hydromodpy.calibration.runners.session import (
    project_root_for,
)
from hydromodpy.calibration.runners.state import (
    space_from_config,
)
from hydromodpy.calibration.runners.trial import (
    TrialMetricFn,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.workspace.path_registry import in_run_scratch
from hydromodpy.results.storage.run_log import in_project_log

if TYPE_CHECKING:
    from hydromodpy.calibration.report import CalibrationReport


logger = get_logger(__name__)


def _root_of_call(config_path: Path | str, **kw: Any) -> Path:
    return project_root_for(Path(config_path), kw.get("workspace"))


@in_run_scratch(
    _root_of_call,
    lambda config_path, **_kw: Path(config_path).stem,
    check=lambda *_a, **kw: refuse_an_objective_that_is_not_an_entry_point(kw.get("objective")),
)
@in_project_log(_root_of_call)
def run_calibration_cli(
    config_path: Path | str,
    *,
    objective: str | None = None,
    workspace: Path | str | None = None,
    project: str | None = None,
    metric_fn: TrialMetricFn | None = None,
    resume: bool = False,
    bounds: Bounds | None = None,
) -> CalibrationReport:
    """Run a calibration described by ``config_path``.

    Parameters
    ----------
    config_path
        Path to a TOML that declares ``[calibration]`` plus the full
        ``[simulation]`` / ``[flow]`` / ``[data]`` blocks.
    objective
        Optional escape hatch: ``"module.path:callable"`` selects the
        RAM metric extractor. ``metric_fn`` wins when both are given;
        a value that is not an entry point is refused.
    workspace
        Override the project root (defaults to the one resolved from the
        location of the TOML).
    project
        Project name written in the outcome of the session. Unset, the name
        of the project root folder.
    metric_fn
        Programmatic override for the metric extractor.
    resume
        Reopen the latest session of the case instead of starting a new one;
        the trials already journaled preload the cache.
    bounds
        The :class:`~hydromodpy.core.runtime.bounds.Bounds` of the call that
        launched the calibration. ``prepare_trials`` builds its context under
        them, so each trial loads its data under the hosts the call allows.
        ``None`` keeps the all-allowing default.
    """
    cfg_path, project_root, cfg, raw, case = load_calibration_document(config_path, workspace)
    cfg = with_its_method(cfg)
    report, _spread = run_single_search(
        cfg,
        space=space_from_config(cfg),
        cfg_path=cfg_path,
        case=case,
        raw=raw,
        project_root=project_root,
        project=project,
        metric_fn=metric_fn,
        objective=objective,
        resume=resume,
        bounds=bounds,
    )
    return report


__all__ = ["run_calibration_cli"]
