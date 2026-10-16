"""Programmatic entry point ``Project.calibrate(parameters=...)``.

Used by ``Project.calibrate`` to drive a calibration **without** a stand-alone
calibration TOML. The simulation TOML attached to the project is reused as
``cfg_path`` for :func:`prepare_trials` so promotion keeps working. Pure
in-memory projects materialize a base TOML so the trial pipeline can locate
the source declaration.

A ``cfg`` that declares ``phases`` cannot run through the single-search loop
below: a staged calibration forks each phase's configuration from a file, and
Python mode has none. :func:`_write_python_mode_document` writes one next to
the project's ``sessions/``, and :func:`run_calibration_programmatic` hands it
to :func:`~hydromodpy.calibration.runners.staged_runner.run_staged_calibration`.
The document is a plain calibration TOML: ``hmp calibrate <path>`` replays it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from hydromodpy.calibration.config import CalibrationConfig, apply_project_defaults
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.persistence import DEFAULT_PHASE, PhaseContext
from hydromodpy.calibration.runners.cli_runner import (
    SessionScope,
    _keep_trial_solves,
    closing_session,
    open_calibration_session,
    promote_and_close,
    refuse_an_objective_that_is_not_an_entry_point,
    run_one_search,
)
from hydromodpy.calibration.runners.promotion import promotion_name_check
from hydromodpy.calibration.runners.state import (
    override_paths as resolve_override_paths,
)
from hydromodpy.calibration.runners.state import space_from_config
from hydromodpy.calibration.runners.trial import TrialMetricFn, prepare_trials
from hydromodpy.core.state.paths import sessions_dir_for
from hydromodpy.core.workspace.path_registry import in_run_scratch

if TYPE_CHECKING:
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.calibration.runners.staged_runner import StagedCalibrationReport


def _write_python_mode_document(
    cfg: CalibrationConfig, *, project: Any, ws_root: Path, src_path: Path | None
) -> Path:
    """Write the calibration TOML a Python-mode staged run replays from.

    Embeds ``project.config`` (already resolved: every relative path it
    declared was resolved against the project's own file when ``Project``
    validated it, eagerly, at construction) rather than pointing at the
    source file through ``base_config``, so the document means the same
    thing wherever it is read from.

    ``[calibration]`` is a plain overwrite, never a merge, on both a
    file-backed and a pure in-memory project: a phases= call declares its
    own parameters, outputs and blocks, and none of the project's own
    ``[calibration]`` (if any) carries over. Written beside ``sessions/``,
    under the project root the source file resolves to.

    A relative ``stream_geometry_path`` in ``cfg`` is meant relative to the
    project, the same as in TOML mode: :func:`resolve_stream_geometry_paths`
    is called here, anchored on the project's own file, before ``cfg`` is
    dumped, so the document carries an absolute path like the rest of the
    embedded config.
    """
    from hydromodpy.calibration.runners.cli_runner import resolve_stream_geometry_paths
    from hydromodpy.calibration.runners.materialize import write_overlay_toml
    from hydromodpy.core.state.paths import resolve_project_root

    if src_path is not None:
        anchor_path = Path(src_path).expanduser().resolve()
        sessions_root = resolve_project_root(anchor_path.parent)
    else:
        sessions_root = ws_root
        # Only its parent is read; the file itself never needs to exist.
        anchor_path = ws_root / "project.toml"

    resolve_stream_geometry_paths(cfg, anchor_path)

    payload: dict[str, Any] = dict(project.config.model_dump(mode="json", exclude_none=True))
    payload["workflow"] = {"mode": "calibration"}
    payload["calibration"] = cfg.model_dump(mode="json", exclude_none=True)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    doc_path = sessions_dir_for(sessions_root) / f"python-{stamp}-{uuid4().hex[:8]}.toml"
    write_overlay_toml(doc_path, payload)
    return doc_path


def _project_root(project: Any, workspace: Path | str | None) -> Path:
    """Return the project root a programmatic calibration runs in.

    ``workspace`` wins, then the workspace of the project's built context,
    then the current directory.
    """
    if workspace is not None:
        return Path(workspace).expanduser().resolve()
    ws_obj = getattr(project, "_ctx", None)
    ws_setup = getattr(ws_obj, "setup", None) if ws_obj is not None else None
    ws_root_obj = getattr(ws_setup, "workspace", None) if ws_setup is not None else None
    if ws_root_obj is not None:
        return Path(ws_root_obj.project_root)
    return Path.cwd()


def _case_name(project: Any, cfg_path: Path) -> str:
    """Return the case a Python-mode calibration names: the simulation name, else the stem."""
    simulation = getattr(getattr(project, "config", None), "simulation", None)
    name = str(getattr(simulation, "name", "") or "").strip()
    return name or cfg_path.stem


def _document_of(project: Any, cfg_path: Path) -> dict[str, Any]:
    """Return the resolved document the session freezes: the project config, else the file."""
    config = getattr(project, "config", None)
    if config is not None and hasattr(config, "model_dump"):
        return dict(config.model_dump(mode="json", exclude_none=True))
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    return dict(load_toml_with_base_config(cfg_path))


def _with_project_defaults(cfg: CalibrationConfig, project: Any) -> CalibrationConfig:
    """Write ``[site] gauge`` and ``[metrics] window`` of the project into ``cfg``."""
    config = getattr(project, "config", None)
    site = getattr(config, "site", None)
    metrics = getattr(config, "metrics", None)
    window = getattr(metrics, "window", None)
    gauge = getattr(site, "gauge", None)
    if gauge is None and window is None:
        return cfg
    section = apply_project_defaults(
        cfg.model_dump(mode="json", exclude_none=True),
        site_gauge=gauge,
        metrics_window=window.model_dump(mode="json") if window is not None else None,
    )
    return CalibrationConfig.model_validate(section)


@in_run_scratch(
    lambda cfg, **kw: _project_root(kw["project"], kw.get("workspace")),
    lambda cfg, **_kw: "calibration",
    check=lambda *_a, **kw: refuse_an_objective_that_is_not_an_entry_point(kw.get("objective")),
)
def run_calibration_programmatic(
    cfg: CalibrationConfig,
    *,
    project,
    workspace: Path | str | None = None,
    project_label: str | None = None,
    metric_fn: TrialMetricFn | None = None,
    objective: str | None = None,
    return_report: bool = True,
    phase: str | None = None,
    resume: bool = False,
) -> CalibrationReport | StagedCalibrationReport | dict:
    """Run calibration without a stand-alone calibration TOML.

    The :class:`hydromodpy.Project` instance carries the simulation config;
    ``cfg.parameters`` declares the calibratable knobs. The project's source
    TOML is reused as ``cfg_path`` for :func:`prepare_trials`. Pure in-memory
    projects materialize a base TOML so both the trial pipeline and the
    promotion step still find a path.

    A ``cfg`` that declares ``phases`` runs staged instead: the document
    :func:`_write_python_mode_document` writes is handed to
    :func:`~hydromodpy.calibration.runners.staged_runner.run_staged_calibration`,
    and ``phase`` selects one of its phases the same way it does on a TOML
    calibration.
    """
    refuse_an_objective_that_is_not_an_entry_point(objective)

    ws_root = _project_root(project, workspace)
    src_path = getattr(project, "_config_path", None)
    cfg = _with_project_defaults(cfg, project)

    if cfg.phases:
        from hydromodpy.calibration.runners.staged_runner import run_staged_calibration

        doc_path = _write_python_mode_document(
            cfg, project=project, ws_root=ws_root, src_path=src_path
        )
        # Not ws_root: a caller override still wins, but otherwise the staged
        # runner resolves its own project root from the document it just read,
        # which stays correct even when ws_root above fell back to the
        # caller's working directory.
        return run_staged_calibration(
            doc_path,
            phase=phase,
            objective=objective,
            workspace=workspace,
            project=project_label,
            metric_fn=metric_fn,
            return_report=return_report,
            resume=resume,
        )

    space = space_from_config(cfg)
    paths = resolve_override_paths(cfg)

    if src_path is None:
        from hydromodpy.calibration.runners.materialize import write_overlay_toml

        cfg_path = ws_root / ".hydromodpy" / "calibration_base.toml"
        payload = project.config.model_dump(mode="json", exclude_none=True)
        write_overlay_toml(cfg_path, payload)
    else:
        cfg_path = Path(src_path).expanduser().resolve()

    # Same question as the CLI route asks, from the name alone: an evaluator that
    # replaces the model has no use for the model's setup prefix.
    trial_ctx = (
        prepare_trials(cfg_path, override_paths=paths, parameter_space=space)
        if evaluation_registry.needs_prepared_model(cfg.evaluator)
        else None
    )
    case = _case_name(project, cfg_path)
    promotion_name_check(case)
    raw = _document_of(project, cfg_path)
    raw["calibration"] = cfg.model_dump(mode="json", exclude_none=True)
    persistence, _reopened = open_calibration_session(
        ws_root,
        case,
        resume=resume,
        raw=raw,
        cfg=cfg,
        space=space,
        trial_ctx=trial_ctx,
        project=project_label,
    )
    _keep_trial_solves(cfg, trial_ctx)
    scope = SessionScope(
        cfg=cfg, project_root=ws_root, persistence=persistence, trial_ctx=trial_ctx
    )
    with closing_session(scope):
        report, _spread = run_one_search(
            cfg,
            trial_ctx,
            persistence=persistence,
            space=space,
            project_root=ws_root,
            cfg_path=cfg_path,
            metric_fn=metric_fn,
            objective=objective,
            phase=PhaseContext(DEFAULT_PHASE, 0, 0),
        )
        report = promote_and_close(
            cfg=cfg,
            trial_ctx=trial_ctx,
            persistence=persistence,
            project_root=ws_root,
            report=report,
            phase=DEFAULT_PHASE,
            status=str(report.extra.get("search_status", "completed")),
            root_search={
                key: report.extra[key] for key in ("bracket", "roots") if key in report.extra
            },
        )
    if return_report:
        return report
    return report.to_dict()


__all__ = ["run_calibration_programmatic"]
