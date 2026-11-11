"""Workflow steps - one module per pipeline concern.

Each module exposes both:

* function-based ``step_*`` helpers, called by the ``Project`` facade and by the
  calibration runners;
* a single ``*Step`` class adapting those helpers to the
  :class:`~hydromodpy.workflow.step.Step` protocol so the steps can
  be composed by ``workflow.runner.Pipeline``.

The canonical ordered tuple of pipeline-grade steps is
:func:`hydromodpy.workflow.steps.sequence.standard_steps`.
"""
