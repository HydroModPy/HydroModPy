Calibration Overview
====================

Scope
-----

This page is the code-oriented entry point for the calibration stack.

It is useful when you want to answer:

- which package owns the calibration entry point versus the generic
  calibration logic,
- where prepared runtime support comes from before optimization
  starts,
- where runnable cases stop and reusable calibration-core code starts.

Architecture map
----------------

The current calibration stack is split into four layers:

- ``hydromodpy/calibration/runner.py`` owns the ``hmp run
  <calibration.toml>`` workflow entry point. It validates the config,
  builds the engine, runs the optimizer, and writes the report.
- ``hydromodpy/simulation/execution/trial.py`` owns the prepare-once,
  evaluate-many primitive used by every trial inside the ask/tell loop.
- ``hydromodpy/calibration/`` (engine, parameters, objective,
  optimizer, diagnostics, persistence) owns the reusable calibration
  engine, parameter sets, objective handling, method dispatch, and
  canonical results.
- ``hydromodpy/calibration/cases/`` owns runnable scientific cases that
  exercise the full calibration loop end to end.

Recommended reading path
------------------------

When reading the code from the published docs, the shortest useful
path is:

1. ``hydromodpy/cli/commands/run.py`` ([workflow].mode = "calibration"
   dispatch)
2. ``hydromodpy/calibration/runner.py``
3. ``hydromodpy/calibration/engine.py``
4. ``hydromodpy/simulation/execution/trial.py``
5. one case under ``hydromodpy/calibration/cases/``

Related code-oriented docs
--------------------------

Several useful prose documents already exist in the repository even
though they were not previously surfaced from the architecture
section:

- ``hydromodpy/calibration/README.md`` for the package map,
- ``docs/developers/calibration_guide.md`` for the end-to-end user
  guide,
- case-local docstrings under ``hydromodpy/calibration/cases/`` for
  runnable examples.

See also
--------

- :doc:`calibration-execution-flows`
- :doc:`calibration-core-classes`
- :doc:`calibration-case-structure`
