"""Run a sealed configuration again through the public Project facade.

Lives under :mod:`hydromodpy.project.dispatch` because :class:`Project` is the
top-level facade. ``hmp catalog rerun`` calls :func:`rerun_config` directly,
since ``cli`` reads ``project``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


def rerun_config(
    snapshot: Mapping[str, Any],
    *,
    changes: Mapping[str, Any],
    name: str | None,
    source_sim_id: str | None,
    source_dir: Path | None,
    project_options: Mapping[str, Any] | None = None,
) -> Any:
    """Run the frozen configuration *snapshot* again and return the new run.

    The snapshot is read from the project it names in ``[workspace]
    project_root`` (:meth:`HydroModPyConfig.from_snapshot`): its paths resolve in
    the workspace of that project, wherever the run was frozen. *changes* are the
    dotted paths to set, the grammar of ``--set``, or names of ``hmp config targets``
    (:func:`~hydromodpy.project.run_overrides.override_changes`). Each key that differs from what
    *source_dir* sealed for another reason (a default that moved) gets a warning.
    The seal of the new run carries ``lineage.kind = "rerun"``, the id of its
    source, the dotted paths that changed, and the keys that moved.
    """
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.project.facade import Project
    from hydromodpy.project.run_overrides import override_changes
    from hydromodpy.project.runner import pin_parent_sim_id
    from hydromodpy.project.trial_pipeline import fill_trial_pipeline
    from hydromodpy.schema.lineage import Lineage
    from hydromodpy.workflow.replay_checks import warn_config_drift

    # A run played again may be a trial of a calibration, which reads its files
    # through the trial pipeline, the one global the library keeps.
    fill_trial_pipeline()
    if any("." not in key for key in changes):
        changes = override_changes(HydroModPyConfig.from_snapshot(snapshot), changes)
    project = Project(
        HydroModPyConfig.from_snapshot(snapshot, changes=changes), **(project_options or {})
    )
    drift = warn_config_drift(project._cfg, source_dir, intended=changes)
    lineage = Lineage(
        parent_sim_id=source_sim_id,
        kind="rerun" if source_sim_id else None,
        overrides={str(key): value for key, value in changes.items()},
        drift=drift,
    )
    with pin_parent_sim_id(project._ctx, source_sim_id):
        return project.simulate(name=name, lineage=lineage)


__all__ = ["rerun_config"]
