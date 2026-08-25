"""Rerun adapter that depends on the public Project facade.

Lives under :mod:`hydromodpy.project.dispatch` because :class:`Project` is the
top-level facade and the architectural matrix forbids the ``results`` layer
from depending on it; the catalog calls this through the ``RerunProvider``
protocol registered at bootstrap.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


class ProjectRerunProvider:
    """Re-launch a simulation from a config snapshot through ``Project``."""

    def rerun(
        self,
        snapshot: Mapping[str, Any],
        *,
        overrides: Mapping[str, Any],
        name: str | None,
        source_sim_id: str | None = None,
    ) -> str:
        """Rebuild the config, apply dotted-path overrides, and simulate.

        ``source_sim_id`` is pinned as the child's ``parent_sim_id`` so rerun
        lineage is preserved.
        """
        from hydromodpy.calibration.optim.parameters import set_by_path
        from hydromodpy.project import Project
        from hydromodpy.project.runner import _pin_parent_sim_id

        project = Project(dict(snapshot))
        for dotted, value in overrides.items():
            set_by_path(project.config, dotted, value)
        with _pin_parent_sim_id(project._ctx, source_sim_id):
            run = project.simulate(name=name)
        if run is None:
            raise RuntimeError("Rerun did not produce a run.")
        return run.sim_id


__all__ = ["ProjectRerunProvider"]
