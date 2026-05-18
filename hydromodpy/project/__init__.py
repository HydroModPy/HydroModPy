"""Public ``Project`` facade and its helper subsystems.

The :class:`Project` class is the high-level entry point for interactive
Python usage. The submodules below split its responsibilities so the
facade stays focused on the public verbs:

- :mod:`.facade` -- the :class:`Project` class itself
- :mod:`.session` -- run-phase orchestrator returned by :meth:`Project.session`
- :mod:`.runner` -- internal runner backing ``run`` / ``calibrate`` / ``mesh`` / ``report``
- :mod:`.catalog` -- catalog access and lifecycle helper
- :mod:`.prepared_run` -- low-level prepared-run primitives
- :mod:`.accessors` -- read-only accessors exposed on ``project.data`` and ``project.runs``
- :mod:`.phases` -- model-phase verbs (``configure``, ``build_geographic``, ...)
- :mod:`.dispatch` -- workflow and calibration dispatch adapters
"""

from __future__ import annotations

from hydromodpy.project.accessors import ProjectDataAccessor, ProjectRunsAccessor
from hydromodpy.project.catalog import ProjectCatalog
from hydromodpy.project.facade import Project
from hydromodpy.project.prepared_run import DEFAULT_RUN_NAME_TEMPLATE, ProjectPreparedRun
from hydromodpy.project.runner import ProjectRunner
from hydromodpy.project.session import ProjectSession

__all__ = [
    "DEFAULT_RUN_NAME_TEMPLATE",
    "Project",
    "ProjectCatalog",
    "ProjectDataAccessor",
    "ProjectPreparedRun",
    "ProjectRunner",
    "ProjectRunsAccessor",
    "ProjectSession",
]
