"""The workflow layer: the steps of a run and the pipeline that chains them.

A :class:`~hydromodpy.workflow.runner.Pipeline` runs the steps of
:mod:`hydromodpy.workflow.steps`, journals them under the run directory and
resumes a run from their artifacts. One path serves a TOML file, the Python API
and a calibration trial.

Public API
----------
WorkflowContext
    Extended run state with result-store lifecycle support.

A file such as ``step4_transient.toml`` becomes thirteen steps, from validation to the
seal of the run, and one file always drives one lifecycle. A run writes its own
directory and nothing else: it never opens the index of the project, and nothing here
imports ``hydromodpy.project``. No lower layer imports ``workflow`` either. Calibration
reaches these steps through the ``TrialPipeline`` protocol of
``calibration/runners/trial.py``, whose implementation lives in
``project/trial_pipeline.py``.
"""
