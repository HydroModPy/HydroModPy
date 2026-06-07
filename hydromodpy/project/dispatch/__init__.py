"""Dispatch adapters that bind workflow launchers to the public ``Project``.

These modules sit above the architectural matrix because they depend on
:class:`hydromodpy.project.Project`. The matrix layers (``calibration``,
``workflow``, ``analysis``) must not reach Project, so the adapters live
here instead.

- :mod:`.workflow` exposes ``dispatch_workflow``, ``DISPATCH`` and the
  ``run_*`` functions used by the CLI and the public ``hmp.run`` facade.
- :mod:`.calibration` exposes ``ProjectTrialPromotionProvider`` registered
  in the calibration runner bootstrap.
"""

from __future__ import annotations

from hydromodpy.project.dispatch.calibration import ProjectTrialPromotionProvider
from hydromodpy.project.dispatch.workflow import (
    DISPATCH,
    ProjectTestbedRunnerProvider,
    dispatch_workflow,
    run_calibration,
    run_comparison,
    run_overview,
    run_simulation,
    run_testbed,
)

__all__ = [
    "DISPATCH",
    "ProjectTestbedRunnerProvider",
    "ProjectTrialPromotionProvider",
    "dispatch_workflow",
    "run_calibration",
    "run_comparison",
    "run_overview",
    "run_simulation",
    "run_testbed",
]
