"""Programmatic entry point ``Project.calibrate(parameters=...)``.

Used by ``Project.calibrate`` to drive a calibration **without** a stand-alone
calibration TOML. The simulation TOML attached to the project is reused as
``cfg_path`` for :func:`prepare_trials` so promotion keeps working. Pure
in-memory projects materialize a base TOML so the trial pipeline can locate
the source declaration.

A ``cfg`` that declares ``phases`` cannot run through the single-search loop
below: a staged calibration forks each phase's configuration from a file, and
Python mode has none. :func:`_write_python_mode_document` writes one next to
the project's ``sessions/`` as ``<case>.toml``, and
:func:`run_calibration_programmatic` hands it to
:func:`~hydromodpy.calibration.runners.staged_runner.run_staged_calibration`.
The document is a plain calibration TOML: ``hmp calibrate <path>`` replays it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.config import CalibrationConfig, apply_project_defaults
from hydromodpy.calibration.runners.cli_runner import (
    refuse_an_objective_that_is_not_an_entry_point,
    run_single_search,
)
from hydromodpy.calibration.runners.session import calibration_case_name, case_named_by
from hydromodpy.calibration.runners.state import space_from_config
from hydromodpy.calibration.runners.trial import TrialMetricFn
from hydromodpy.core.state.layout import sessions_dir_for
from hydromodpy.core.workspace.path_registry import in_run_scratch

if TYPE_CHECKING:
    from hydromodpy.calibration.report import CalibrationReport


def _write_python_mode_document(
    cfg: CalibrationConfig,
    *,
    document: dict[str, Any],
    case: str,
    ws_root: Path,
    src_path: Path | None,
) -> Path:
    """Write the calibration TOML a Python-mode staged run replays from.

    Embeds *document*, the project configuration (already resolved: every
    relative path it declared was resolved against the project's own file when
    ``Project`` validated it, eagerly, at construction) rather than pointing at the
    source file through ``base_config``, so the document means the same
    thing wherever it is read from. It is named after *case*, so that the
    staged runner names the same case and ``resume`` finds the session of an
    earlier call. A later call of the case overwrites it.

    ``[calibration]`` is a plain overwrite, never a merge, on both a
    file-backed and a pure in-memory project: a phases= call declares its
    own parameters, outputs and blocks, and none of the project's own
    ``[calibration]`` (if any) carries over. Written beside ``sessions/``,
    under the project root the source file resolves to.

    A relative ``map.complete`` or ``map.permanent`` in ``cfg`` is meant relative to the
    project, the same as in TOML mode: :func:`resolve_stream_geometry_paths`
    is called here, anchored on the project's own file, before ``cfg`` is
    dumped, so the document carries an absolute path like the rest of the
    embedded config.
    """
    from hydromodpy.calibration.runners.cli_runner import resolve_stream_geometry_paths
    from hydromodpy.calibration.runners.materialize import write_overlay_toml
    from hydromodpy.core.state.result_dirs import resolve_project_root

    if src_path is not None:
        anchor_path = Path(src_path).expanduser().resolve()
        sessions_root = resolve_project_root(anchor_path.parent)
    else:
        sessions_root = ws_root
        # Only its parent is read; the file itself never needs to exist.
        anchor_path = ws_root / "project.toml"

    resolve_stream_geometry_paths(cfg, anchor_path)

    payload = {
        **document,
        # The staged runner names the case from this document, whatever the project inherits.
        "simulation": {**(document.get("simulation") or {}), "name": case},
        "workflow": {"mode": "calibration"},
        "calibration": cfg.model_dump(mode="json", exclude_none=True, exclude_unset=True),
    }
    doc_path = sessions_dir_for(sessions_root) / f"{case}.toml"
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


def _document_of(project: Any, cfg_path: Path) -> dict[str, Any]:
    """Return the resolved document the session freezes: the project config, else the file."""
    config = getattr(project, "config", None)
    if config is not None and hasattr(config, "model_dump"):
        return dict(config.model_dump(mode="json", exclude_none=True, exclude_unset=True))
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    return dict(load_toml_with_base_config(cfg_path))


def project_defaults_on(section: dict[str, Any], project: Any) -> dict[str, Any]:
    """Return a raw ``[calibration]`` with ``[site] gauge`` and ``[metrics] window`` written in."""
    config = getattr(project, "config", None)
    window = getattr(getattr(config, "metrics", None), "window", None)
    return apply_project_defaults(
        section,
        site_gauge=getattr(getattr(config, "site", None), "gauge", None),
        metrics_window=window.model_dump(mode="json") if window is not None else None,
    )


def with_project_defaults(cfg: CalibrationConfig, project: Any) -> CalibrationConfig:
    """Write ``[site] gauge`` and ``[metrics] window`` of the project into ``cfg``."""
    written = cfg.model_dump(mode="json", exclude_none=True, exclude_unset=True)
    section = project_defaults_on(written, project)
    return cfg if section == written else CalibrationConfig.model_validate(section)


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
    phase: str | None = None,
    case: str | None = None,
    resume: bool = False,
) -> CalibrationReport:
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
    ws_root = _project_root(project, workspace)
    src_path = getattr(project, "_config_path", None)
    cfg = with_project_defaults(cfg, project)

    cfg_path = (
        Path(src_path).expanduser().resolve()
        if src_path is not None
        else ws_root / ".hydromodpy" / "calibration_base.toml"
    )
    raw = _document_of(project, cfg_path)
    case = case or (
        calibration_case_name(cfg_path)
        if src_path is not None
        else case_named_by(raw, cfg_path.stem)
    )

    if cfg.phases:
        from hydromodpy.calibration.runners.staged_runner import run_staged_calibration

        doc_path = _write_python_mode_document(
            cfg, document=raw, case=case, ws_root=ws_root, src_path=src_path
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
            resume=resume,
        )

    space = space_from_config(cfg)

    if src_path is None:
        from hydromodpy.calibration.runners.materialize import write_overlay_toml

        write_overlay_toml(cfg_path, raw)

    raw["calibration"] = cfg.model_dump(mode="json", exclude_none=True, exclude_unset=True)
    report, _spread = run_single_search(
        cfg,
        space=space,
        cfg_path=cfg_path,
        case=case,
        raw=raw,
        project_root=ws_root,
        project=project_label,
        metric_fn=metric_fn,
        objective=objective,
        resume=resume,
    )
    return report


__all__ = ["project_defaults_on", "run_calibration_programmatic", "with_project_defaults"]
