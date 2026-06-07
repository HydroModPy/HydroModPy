"""Workflow steps - one module per pipeline concern.

Each module exposes both:

* function-based ``step_*`` helpers consumed by ``workflow.orchestrator`` verbs
  and by ``Project``;
* a single ``*Step`` class adapting those helpers to the
  :class:`~hydromodpy.workflow.internals.step.Step` protocol so the steps can
  be composed by ``workflow.runner.Pipeline``.

The canonical ordered tuple of pipeline-grade steps is
:func:`hydromodpy.workflow.orchestrator.standard_steps`.
"""

from __future__ import annotations

from hydromodpy.workflow.steps.data import LoadDataStep
from hydromodpy.workflow.steps.derive import DeriveStep
from hydromodpy.workflow.steps.display import DisplayStep
from hydromodpy.workflow.steps.export import ExportStep
from hydromodpy.workflow.steps.extract import ExtractStep
from hydromodpy.workflow.steps.mesh import BuildMeshStep
from hydromodpy.workflow.steps.prepare_solver import PrepareSolverStep
from hydromodpy.workflow.steps.resolve import ResolveStep
from hydromodpy.workflow.steps.run_solver import RunSolverStep
from hydromodpy.workflow.steps.setup import BuildGeographicStep, SetupProcessStep
from hydromodpy.workflow.steps.validate import ValidateStep

__all__ = (
    "BuildGeographicStep",
    "BuildMeshStep",
    "DeriveStep",
    "DisplayStep",
    "ExportStep",
    "ExtractStep",
    "LoadDataStep",
    "PrepareSolverStep",
    "ResolveStep",
    "RunSolverStep",
    "SetupProcessStep",
    "ValidateStep",
)
