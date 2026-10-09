Calibration architecture
========================

This page is the code-oriented entry point for the calibration stack: the package map, the
reading path, the loop of one session and the core classes. For the operational reference
(TOML sections, optimizer catalogue, storage rules, pitfalls, Python API), see
:doc:`calibration-guide`.

Architecture map
----------------

The package is split into parts that import in one direction. The README of the package
(:doc:`../packages/calibration`) lists them in dependency order, with the import rules and
a "where to add what" table. The rules are held by
``tests/unit/architecture/calibration_layout.yaml``.

- ``hydromodpy/calibration/runners/`` runs a calibration. ``cli_runner.py`` is the
  ``hmp run <calibration.toml>`` entry point for one search, ``staged_runner.py`` runs
  phases, ``programmatic_runner.py`` serves Python use. ``trial.py`` is the prepare-once,
  evaluate-many primitive, and ``promotion.py`` replays the best trials through the full
  pipeline.
- ``hydromodpy/calibration/optim/`` holds the parameter space, the objective, the optimizer
  Protocol and its registry, the engine, the stopping rules and the params-hash cache. The
  search methods are the modules of ``optim/adapters/``.
- ``hydromodpy/calibration/criteria/`` scores a simulated series against an observed one.
- ``hydromodpy/calibration/evaluation/`` defines what one trial must answer: the
  ``TrialEvaluator`` port, the forward-model port and their registries.
- ``hydromodpy/calibration/metrics/`` and ``observations/`` extract the outputs of a trial and
  pair them with the observations.
- ``hydromodpy/calibration/persistence.py`` writes a session (the journal first, then the
  DuckDB index), and ``report.py`` reads it back.
- ``hydromodpy/calibration/cases/`` keeps two demonstrators as regression fixtures.

Recommended reading path
------------------------

1. ``hydromodpy/project/dispatch/workflow.py`` (``run_calibration``)
2. ``hydromodpy/calibration/runners/cli_runner.py``
3. ``hydromodpy/calibration/optim/engine.py``
4. ``hydromodpy/calibration/runners/trial.py``
5. ``hydromodpy/calibration/runners/pipeline_evaluator.py``

How a calibration flows
-----------------------

The README of the package gives the nine steps, from loading the ``[calibration]`` table to
the report. The sequence below shows the loop.

.. uml:: diagrams/calibration_sequence.wsd

Core classes
------------

.. uml:: diagrams/calibration_classes.wsd

Notes:

- The engine decides when to stop and which results to forward to the optimizer. Running
  the model, the catalog and the promotion all happen in the evaluator.
- A trial lives in memory inside the loop. Every trial leaves one line in the session journal
  and one row in ``calibration_iterations``, and only a promoted trial becomes a run on disk.
- A search method is one module of ``optim/adapters/``, with no list to edit: see
  :doc:`/contribute/architecture/how-to/add-a-calibration-method`.

See also
--------

- :doc:`calibration-guide` for the full operational reference.
- :doc:`/theory/index` for inverse-problem
  formulation and methods.
- :doc:`/theory/validation` for stable benchmark
  pages.
