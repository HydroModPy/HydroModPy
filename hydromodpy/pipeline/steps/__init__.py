"""Ported pipeline steps implementing the :class:`Step` protocol.

Each file in this package defines a small wrapper class around the
existing ``hydromodpy.workflow.steps.*`` functions. The wrappers expose
the new ``Step`` interface so they can be composed into a
:class:`~hydromodpy.pipeline.Pipeline`.

The canonical sequence is built by :func:`standard_steps`.
"""

from __future__ import annotations

from hydromodpy.pipeline.steps.step_00_validate import ValidateStep
from hydromodpy.pipeline.steps.step_01_resolve import ResolveStep
from hydromodpy.pipeline.steps.step_02_load_data import LoadDataStep
from hydromodpy.pipeline.steps.step_03_build_geographic import BuildGeographicStep
from hydromodpy.pipeline.steps.step_04_build_mesh import BuildMeshStep
from hydromodpy.pipeline.steps.step_05_setup_process import SetupProcessStep
from hydromodpy.pipeline.steps.step_06_prepare_solver import PrepareSolverStep
from hydromodpy.pipeline.steps.step_07_run_solver import RunSolverStep
from hydromodpy.pipeline.steps.step_08_extract import ExtractStep
from hydromodpy.pipeline.steps.step_09_derive import DeriveStep
from hydromodpy.pipeline.steps.step_10_export import ExportStep
from hydromodpy.pipeline.steps.step_11_display import DisplayStep


def standard_steps() -> tuple:
    """Return the canonical ordered tuple of simulation pipeline steps.

    Order matches the ``Project`` model phase: build the geographic
    runtime (which populates ``setup.domain``), load the external
    forcings (which need ``setup.domain``), then build the mesh and the
    process objects, then prepare and run the solver.
    """
    return (
        ValidateStep(),
        ResolveStep(),
        BuildGeographicStep(),
        LoadDataStep(),
        BuildMeshStep(),
        SetupProcessStep(),
        PrepareSolverStep(),
        RunSolverStep(),
        ExtractStep(),
        DeriveStep(),
        ExportStep(),
        DisplayStep(),
    )


__all__ = (
    "ValidateStep",
    "ResolveStep",
    "LoadDataStep",
    "BuildGeographicStep",
    "BuildMeshStep",
    "SetupProcessStep",
    "PrepareSolverStep",
    "RunSolverStep",
    "ExtractStep",
    "DeriveStep",
    "ExportStep",
    "DisplayStep",
    "standard_steps",
)
