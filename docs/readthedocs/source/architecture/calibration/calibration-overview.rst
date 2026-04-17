Calibration Overview
====================

Scope
-----

This page is the code-oriented entry point for the calibration stack.

It is useful when you want to answer:

- which package owns launcher orchestration versus generic calibration logic,
- where prepared runtime support comes from before optimization starts,
- where runnable cases stop and reusable calibration-core code starts.

Architecture map
----------------

The current calibration stack is split into five layers:

- ``launchers/model_calibration`` owns launcher-facing orchestration:
  validation, candidate actualization, reruns, manifests, reports, and output
  selection.
- ``launchers/process_simulation/model_calibration_support.py`` exposes the
  public bridge from a prepared simulation runtime to reusable hydraulic
  support.
- ``hydromodpy/simulation/model_calibration_support.py`` owns the shared
  support contract used between prepared simulation state and calibration
  runtime helpers.
- ``hydromodpy/analysis/calibration/core`` owns the reusable calibration
  engine, parameter sets, objective handling, method dispatch, and canonical
  results.
- ``hydromodpy/analysis/calibration/cases`` and ``devkit`` own runnable
  scientific cases plus scaffolding and maintenance helpers for new cases.

Recommended reading path
------------------------

When reading the code from the published docs, the shortest useful path is:

1. ``launchers/model_calibration/launcher.py``
2. ``launchers/model_calibration/runtime.py``
3. ``hydromodpy/simulation/model_calibration_support.py``
4. ``hydromodpy/analysis/calibration/core/``
5. one package under ``hydromodpy/analysis/calibration/cases/``

Related code-oriented docs
--------------------------

Several useful prose documents already exist in the repository even though
they were not previously surfaced from the architecture section:

- ``hydromodpy/analysis/calibration/README.md`` for the package map,
- ``hydromodpy/analysis/calibration/docs/case_cookbook.md`` for case authoring,
- ``hydromodpy/analysis/calibration/docs/config_reference.md`` for config
  conventions,
- case-local ``README.md`` files under ``cases/`` for runnable examples.

See also
--------

- :doc:`calibration-execution-flows`
- :doc:`calibration-core-classes`
- :doc:`calibration-case-structure`
