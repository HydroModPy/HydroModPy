"""Atomic workflow steps.

Two coexisting layers live here:

* function-based steps that take a ``WorkflowContext`` and mutate it
  (used directly by ``workflow.orchestrator`` verbs and ``Project``);
* ``*Step`` classes that adapt those functions to the
  :class:`~hydromodpy.workflow.internals.step.Step` protocol so they can
  be composed by ``workflow.runner.Pipeline``.

The canonical ordered tuple of pipeline-grade steps is
:func:`hydromodpy.workflow.orchestrator.standard_steps`.
"""

from __future__ import annotations

from hydromodpy.workflow.steps.build_geographic import BuildGeographicStep
from hydromodpy.workflow.steps.build_mesh import BuildMeshStep
from hydromodpy.workflow.steps.derive import DeriveStep
from hydromodpy.workflow.steps.display import DisplayStep
from hydromodpy.workflow.steps.export import ExportStep
from hydromodpy.workflow.steps.extract import ExtractStep
from hydromodpy.workflow.steps.load_data import LoadDataStep
from hydromodpy.workflow.steps.prepare_solver import PrepareSolverStep
from hydromodpy.workflow.steps.resolve import ResolveStep
from hydromodpy.workflow.steps.run_solver import RunSolverStep
from hydromodpy.workflow.steps.setup_process import SetupProcessStep
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
