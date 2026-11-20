"""Workflow steps - one module per pipeline concern.

Each module exposes both:

* function-based ``step_*`` helpers, called by the ``Project`` facade and by the
  calibration runners;
* a single ``*Step`` class adapting those helpers to the
  :class:`~hydromodpy.workflow.step.Step` protocol so the steps can
  be composed by ``workflow.runner.Pipeline``.

The canonical ordered tuple of pipeline-grade steps is
:func:`hydromodpy.workflow.steps.sequence.standard_steps`.

A step never opens the index of the project. It writes through ``run_store(ctx)``, and
its ``reads``, ``writes`` and ``config_sections`` are exact, which
``tests/unit/architecture/test_run_path.py`` checks. A new step is a module here with
its ``step_*`` function and its ``*Step`` class, placed in ``sequence.py`` and named in
``core/pipeline_steps.py``, with ``depends_on``, ``reads``, ``writes`` and
``config_sections``. A persistent step implements ``artifacts`` and ``rebuild_state``,
so that a resume can skip it. Something done after the solve is a function of
``run_outputs.py``, called from the matching step, and something written when the run
opens goes to ``prepare_solver/``. A key of the shared payload is written in the
``reads`` and ``writes`` of the steps that touch it, in the same commit.
"""
