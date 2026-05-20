"""Programmatic entry point ``hmp.calibrate(project, cfg)``.

Used by ``Project.calibrate`` to drive a calibration **without** a stand-alone
calibration TOML. The simulation TOML attached to the project is reused as
``cfg_path`` for :func:`prepare_trials` so promotion and overlay materialization
keep working. Pure in-memory projects materialize a temporary overlay TOML so
the trial pipeline can locate the source declaration.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.calibration.cli_runner import run_calibration_core
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners.trial import TrialMetricFn, prepare_trials
from hydromodpy.calibration.state import (
    CalibrationStoreFactory,
    space_from_config,
)
from hydromodpy.calibration.state import (
    override_paths as resolve_override_paths,
)

if TYPE_CHECKING:
    from hydromodpy.calibration.report import CalibrationReport


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
) -> CalibrationReport | dict:
    """Run calibration without a calibration TOML file.

    The :class:`hydromodpy.Project` instance carries the simulation config;
    ``cfg.parameters`` declares the calibratable knobs. The project's source
    TOML is reused as ``cfg_path`` for :func:`prepare_trials`. Pure in-memory
    projects materialize a base TOML so both the trial pipeline and the
    promotion step still find a path.
    """
    space = space_from_config(cfg)
    paths = resolve_override_paths(cfg)

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
    if src_path is None:
        from hydromodpy.calibration.materialize import write_overlay_toml

        cfg_path = ws_root / ".hydromodpy" / "calibration_base.toml"
        payload = project.cfg.model_dump(mode="json", exclude_none=True)
        write_overlay_toml(cfg_path, payload)
    else:
        cfg_path = Path(src_path).expanduser().resolve()

    trial_ctx = prepare_trials(
        cfg_path,
        override_paths=paths,
        parameter_space=space,
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
