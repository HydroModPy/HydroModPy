Calibration Architecture
========================

This page is the code-oriented entry point for the calibration stack.
It groups the package map, the runtime classes, the execution-flow
diagrams, and the case-vs-core boundary in one place.

For the full operational reference (TOML sections, optimizer
catalogue, storage rules, pitfalls, Python API), see
:doc:`calibration-guide`.

Architecture map
----------------

The current calibration stack is split into four layers:

- ``hydromodpy/calibration/runner.py`` owns the
  ``hmp run <calibration.toml>`` workflow entry point: validates the
  config, builds the engine, runs the optimizer, writes the report.
- ``hydromodpy/simulation/execution/trial.py`` owns the prepare-once,
  evaluate-many primitive used by every trial inside the ask/tell
  loop.
- ``hydromodpy/calibration/`` (engine, parameters, objective,
  optimizer, diagnostics, persistence) owns the reusable engine,
  parameter sets, objective handling, method dispatch, and canonical
  results.
- ``hydromodpy/calibration/cases/`` owns runnable scientific cases
  that exercise the full calibration loop end to end.

Recommended reading path
------------------------

When reading the code from the published docs:

1. ``hydromodpy/cli/commands/run.py`` (``[workflow].mode =
   "calibration"`` dispatch)
2. ``hydromodpy/calibration/runner.py``
3. ``hydromodpy/calibration/engine.py``
4. ``hydromodpy/simulation/execution/trial.py``
5. one case under ``hydromodpy/calibration/cases/``

Companion files:

- ``hydromodpy/calibration/README.md`` for the package map.
- :doc:`calibration-guide` for the end-to-end reference.
- Case-local docstrings under ``hydromodpy/calibration/cases/`` for
  runnable examples.

Core classes (config)
---------------------

This diagram focuses on validated configuration and method-selection
objects.

.. uml:: diagrams/core_classes_config.wsd

.. literalinclude:: diagrams/core_classes_config.wsd
   :language: text
   :caption: PlantUML (.wsd) source - core classes config

Core classes (main runtime)
---------------------------

This diagram focuses on the reusable runtime objects exchanged during
one calibration session.

.. uml:: diagrams/core_classes_main.wsd

.. literalinclude:: diagrams/core_classes_main.wsd
   :language: text
   :caption: PlantUML (.wsd) source - core classes main runtime

Calibration activity
--------------------

The high-level activity view of one calibration session driven by
``hmp run``.

.. uml:: diagrams/calibration_activity.wsd

.. literalinclude:: diagrams/calibration_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - calibration activity

Calibration sequence
--------------------

The handoff between the CLI entry point and the generic calibration
engine.

.. uml:: diagrams/calibration_sequence.wsd

.. literalinclude:: diagrams/calibration_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - calibration sequence

Reservoir sequence (case example)
---------------------------------

How one runnable calibration case plugs into the shared core.

.. uml:: diagrams/reservoir_sequence.wsd

.. literalinclude:: diagrams/reservoir_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - reservoir sequence

Devkit sequence
---------------

The developer tooling used to scaffold and validate new calibration
cases.

.. uml:: diagrams/devkit_sequence.wsd

.. literalinclude:: diagrams/devkit_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - devkit sequence

Case / core structure
---------------------

How runnable calibration cases are organized around the shared
calibration core: where ``core/`` ends and ``cases/`` begins.

.. uml:: diagrams/case_core_structure.wsd

.. literalinclude:: diagrams/case_core_structure.wsd
   :language: text
   :caption: PlantUML (.wsd) source - case/core structure

Notes:

- Case packages under ``hydromodpy/calibration/cases`` are expected
  to stay thin adapters around the shared engine.
- CLI-specific concerns such as manifests, reruns, and report
  persistence are owned by ``hydromodpy/calibration/runner.py`` and
  the reporting helpers in
  ``hydromodpy/calibration/persistence.py`` and ``report.py``.

See also
--------

- :doc:`calibration-guide` for the full operational reference.
- :doc:`../../user_guide/calibration` for the user-facing hub.
- :doc:`../../theory/calibration/index` for inverse-problem
  formulation and methods.
- :doc:`../../capability_gallery/calibration` for stable benchmark
  pages.
