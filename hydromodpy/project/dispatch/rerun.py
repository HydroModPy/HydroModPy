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
    ) -> str:
        """Rebuild the config, apply dotted-path overrides, and simulate."""
        from hydromodpy.calibration.runners.trial import _set_by_path
        from hydromodpy.project import Project

        project = Project(dict(snapshot))
        for dotted, value in overrides.items():
            _set_by_path(project.config, dotted, value)
        run = project.simulate(name=name)
        if run is None:
            raise RuntimeError("Rerun did not produce a run.")
        return run.sim_id


__all__ = ["ProjectRerunProvider"]
