Package: workflow
=================

.. include:: ../../../../../hydromodpy/workflow/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: workflow

Inside the package
------------------

The steps
~~~~~~~~~

``standard_steps()`` of ``steps/sequence.py`` returns the thirteen steps in order, with the
names of ``core/pipeline_steps.py``. Each step declares the step it depends on, so the graph is
a chain and every cohort holds one step. The order is ``validate``, ``resolve``,
``build_geographic``, ``load_data``, ``build_mesh``, ``setup_process``, ``prepare_solver``,
``run_solver``, ``extract``, ``derive``, ``export``, ``seal`` and ``display``. ``prepare_solver`` freezes the configuration into ``config.toml``
and ``config.resolved.toml``. ``seal`` writes the seal from the facts of the run. The data exports and the views
(``step_after_seal`` of ``steps/export.py``) and the figures come after it and carry its
label.

How a run goes through it
~~~~~~~~~~~~~~~~~~~~~~~~~

1. The launcher claims the directory of the case under ``runs/`` through ``record/attempt.py``,
   before the first step. ``outcome.json`` says ``running`` and a heartbeat pulses.
2. ``Pipeline`` builds the graph from ``depends_on()`` and runs it with
   ``Pipeline.run(state, resume_from=..., parallel=..., heartbeat=...)``. Each step is
   ``state.advance(...)`` over the shared ``PipelineState``, whose main member is the
   ``WorkflowContext``. ``window.py`` bounds the steps with ``from_step`` and ``until_step``.
3. Each step is recorded in ``<run>/.hmp/checkpoints/steps.json`` with the hash of its
   artifacts. ``ResolvedRunManifest`` and the facts of the run (``RunFacts``) sit beside it in
   ``<run>/.hmp/``. A step that writes durable artifacts implements ``artifacts(state_out)`` and
   ``rebuild_state(...)``. At resume the runner rebuilds the state of a completed step from
   disk and does not run it again, as :doc:`../pipeline_resume` tells. There is no pickle layer.
4. Before each cohort the runner reads the stop flag ``.hmp/stop.json`` and raises
   ``StopRequested`` when it is there. The step that a stop interrupts is marked ``aborted``, so
   a resume plays it again from its start, ``run_solver`` included.
5. After the seal, the attempt protocol flips the outcome to ``completed`` and removes
   ``<run>/.hmp/``. A render that raises after the seal leaves the run sealed and ``completed``,
   because ``close_sealed_attempt`` closes it and the error goes up. A run that stops before
   the seal keeps ``failed``, ``aborted`` or, for a window ended by ``--until``, ``partial``.

A calibration trial skips the shared steps, because it asks ``earliest_affected_step`` of
``steps/dependencies.py`` for the first step that an override reaches, from the
``config_sections`` of the steps.

Import rules
~~~~~~~~~~~~

``record/`` imports ``state`` and ``step`` and never ``steps``. A step's ``reads`` and
``writes`` are exact, because ``tests/unit/architecture/test_run_path.py`` derives both from the
source of the step and fails when a declaration and the code disagree. A step never opens the
index of the project. It writes through ``run_store(ctx)`` into the directory of the run, and
the launcher derives the index once the worker has returned.

Where to add what
~~~~~~~~~~~~~~~~~

- A step is described in the docstring of ``steps/__init__.py``, with its name in
  ``core/pipeline_steps.py``.
- Something that a run records about itself goes to ``record/``. A fact of the run is a field
  of ``RunFacts`` in ``results/storage/run_facts.py`` and the block of the seal it feeds in
  ``results/storage/sealing.py``.
- A derived field is a row of ``VIRTUAL_FIELD_ROWS`` in ``results/derive/virtual_fields.py``,
  rebuilt on read and never written by a step.
- A workflow mode is a name in ``KNOWN_WORKFLOWS`` and its adapter in
  ``project/dispatch/workflow.py``.
- A standalone launcher is a class next to ``overview.py``, built on the steps it needs. A
  check at replay is a function of ``replay_checks.py``.
