"""Public ``Project`` facade and its helper subsystems.

The :class:`Project` class is the high-level entry point for interactive
Python usage. The submodules below split its responsibilities so the
facade stays focused on the public verbs:

- :mod:`.facade` -- the :class:`Project` class itself
- :mod:`.runner` -- internal runner backing ``simulate`` / ``calibrate`` / ``sweep``
- :mod:`.accessors` -- read-only accessors exposed on ``project.data`` and ``project.runs``,
  and :class:`ProjectCatalog`, which binds them to a project
- :mod:`.phases` -- model-phase verbs (``configure``, ``build_geographic``, ...)
- :mod:`.calibrate` -- the routing behind ``Project.calibrate``
- :mod:`.dispatch` -- workflow and calibration dispatch adapters
- :mod:`.launch` -- the launcher of a ``[sites]`` project and its summary
- :mod:`.exchange` -- publish, install and replay a published copy

``README.md`` in this folder is the map of the package.
"""

from __future__ import annotations

from hydromodpy.project.accessors import (
    ProjectCatalog,
    ProjectDataAccessor,
    ProjectRunsAccessor,
)
from hydromodpy.project.facade import Project
from hydromodpy.project.runner import DEFAULT_RUN_NAME_TEMPLATE, ProjectRunner

__all__ = [
    "DEFAULT_RUN_NAME_TEMPLATE",
    "Project",
    "ProjectCatalog",
    "ProjectDataAccessor",
    "ProjectRunner",
    "ProjectRunsAccessor",
]
