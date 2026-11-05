"""The workflow layer: the steps of a run and the pipeline that chains them.

A :class:`~hydromodpy.workflow.runner.Pipeline` runs the steps of
:mod:`hydromodpy.workflow.steps`, journals them under the run directory and
resumes a run from their artifacts. One path serves a TOML file, the Python API
and a calibration trial.

Public API
----------
WorkflowContext
    Extended run state with result-store lifecycle support.
"""

from hydromodpy.core.state.run_state import WorkflowContext

__all__ = ["WorkflowContext"]
