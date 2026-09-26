"""Programmatic entry point ``hmp.calibrate(project, cfg)``.

Used by ``Project.calibrate`` to drive a calibration **without** a stand-alone
calibration TOML. The simulation TOML attached to the project is reused as
``cfg_path`` for :func:`prepare_trials` so promotion and overlay materialization
keep working. Pure in-memory projects materialize a temporary overlay TOML so
the trial pipeline can locate the source declaration.

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

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.persistence import CalibrationStoreFactory
from hydromodpy.calibration.runners.cli_runner import (
    refuse_an_objective_that_is_not_an_entry_point,
    run_calibration_core,
)
from hydromodpy.calibration.runners.state import (
    override_paths as resolve_override_paths,
)
from hydromodpy.calibration.runners.state import space_from_config
from hydromodpy.calibration.runners.trial import TrialMetricFn, prepare_trials

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
    source file through ``base_config``. ``HydroModPyConfig.from_toml``
    resolves a relative path against the file it is given, so a document
    inheriting one through ``base_config`` would re-anchor it on wherever
    this document sits (``sessions/``), not on the project: a ``project_root
    = "."`` inherited that way silently becomes ``<project>/sessions/``, and
    every other relative path in the project along with it. Embedding a
    config whose paths are already absolute makes this document mean the
    same thing wherever it is read from.

    ``[calibration]`` is a plain overwrite, never a merge, on both a
    file-backed and a pure in-memory project: a phases= call declares its
    own parameters, outputs and blocks, and none of the project's own
    ``[calibration]`` (if any) carries over. Written beside ``sessions/``:
    :func:`resolve_stream_geometry_paths` and the parameter-name resolution
    both anchor on the document that declares them, and a document one
    level below the project root resolves a path relative to that root the
    same way a hand-written calibration TOML does.

    A file-backed project's own directory, not ``ws_root``, anchors
    ``sessions/``: the heavy model phase is lazy (see the module docstring
    of :mod:`hydromodpy.project.facade`), so ``ws_root`` may still be the
    caller's working directory the first time ``calibrate`` runs. The source
    file is always known, so :func:`resolve_project_root` finds the real
    project directory from it directly.

    A relative ``stream_geometry_path`` in ``cfg`` is meant relative to the
    project, the same as in TOML mode: :func:`resolve_stream_geometry_paths`
    is called here, anchored on the project's own file, before ``cfg`` is
    dumped, so the document carries an absolute path like the rest of the
    embedded config. Anchoring on the document instead (one level below,
    under ``sessions/``) stops the search one directory short.
    """
    from hydromodpy.calibration.runners.cli_runner import resolve_stream_geometry_paths
    from hydromodpy.calibration.runners.materialize import write_overlay_toml
    from hydromodpy.core.state.paths import resolve_project_root
    from hydromodpy.results.session_journal import sessions_dir_for

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
    doc_path = sessions_dir_for(sessions_root) / f"{stamp}-python-{uuid4().hex[:8]}.toml"
    write_overlay_toml(doc_path, payload)
    return doc_path


def run_calibration_programmatic(
    cfg: CalibrationConfig,
    *,
    project,
    workspace: Path | str | None = None,
    project_label: str = "calibration",
    metric_fn: TrialMetricFn | None = None,
    objective: str | None = None,
    return_report: bool = True,
    store_factory: CalibrationStoreFactory | None = None,
    phase: str | None = None,
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

    if workspace is not None:
        ws_root = Path(workspace).expanduser().resolve()
    else:
        ws_obj = getattr(project, "_ctx", None)
        ws_setup = getattr(ws_obj, "setup", None) if ws_obj is not None else None
        ws_root_obj = getattr(ws_setup, "workspace", None) if ws_setup is not None else None
        if ws_root_obj is not None:
            ws_root = Path(ws_root_obj.project_root)
        else:
            ws_root = Path.cwd()

    src_path = getattr(project, "_config_path", None)

    if cfg.phases:
        from hydromodpy.calibration.runners.staged_runner import run_staged_calibration

        doc_path = _write_python_mode_document(
            cfg, project=project, ws_root=ws_root, src_path=src_path
        )
        # Not ws_root: a caller override still wins, but otherwise the staged
        # runner resolves its own workspace from the document it just read
        # (prepare_trials), which stays correct even when ws_root above fell
        # back to the caller's working directory.
        return run_staged_calibration(
            doc_path,
            phase=phase,
            objective=objective,
            workspace=workspace,
            project=project_label,
            metric_fn=metric_fn,
            store_factory=store_factory,
            return_report=return_report,
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

    report = run_calibration_core(
        cfg,
        trial_ctx,
        workspace=ws_root,
        space=space,
        project_label=project_label,
        cfg_path=cfg_path,
        metric_fn=metric_fn,
        objective=objective,
        store_factory=store_factory,
    )
    if return_report:
        return report
    return report.to_dict()


__all__ = ["run_calibration_programmatic"]
