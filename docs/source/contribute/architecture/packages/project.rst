project
=======

``hydromodpy.project`` is the public object-oriented facade. It sits
above the layer matrix like ``cli``: it may call lower layers, but
``workflow``, ``calibration`` and ``analysis`` must not import it.

Role
----

The package binds workflows to a reusable project context. It owns the
``Project`` class, read-only accessors, prepared-run state and dispatch
adapters that connect TOML workflows to project sessions.

Sub-modules
-----------

- ``project/facade.py`` -- ``Project`` class and lifecycle entry point.
- ``project/session.py`` -- run-phase facade with ``prepare``,
  ``execute``, ``ingest``, ``render``, ``cleanup``, ``simulate`` and
  expert Python-only ``sweep``.
- ``project/runner.py`` -- project execution wrapper.
- ``project/prepared_run.py`` -- prepared-run primitives and active-run
  bookkeeping.
- ``project/accessors.py`` -- read-only data and run accessors.
- ``project/catalog.py`` -- project-level catalog binding.
- ``project/dispatch/`` -- workflow and calibration adapters that keep
  lower layers independent from ``Project``.

Key public symbols
------------------

- ``hydromodpy.project.Project``
- ``hydromodpy.Project`` through the root facade

``ProjectSession.sweep`` is an expert Python API. It is not a V1 TOML
workflow and is not exposed as ``workflow.mode = "sweep"``.

Recommended reading path
------------------------

1. ``project/facade.py`` for the user-facing facade.
2. ``project/session.py`` for run-phase operations.
3. ``project/dispatch/workflow.py`` for the binding between workflow
   launchers and ``Project``.
4. ``project/runner.py`` for repeated run orchestration.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``config``, ``physics``,
  ``data``, ``spatial``, ``simulation``, ``solver``, ``calibration``,
  ``results``, ``display``, ``analysis``, ``reporting``,
  ``workflow``, ``catalog`` and ``project``.
- Allowed sources: root facade and ``cli``.
- Lower layers must not import ``project``. Binding to the facade lives
  here or in ``cli``.

See also
--------

- :doc:`../release-contract-v1` for the Python API / CLI / TOML status
  table.
- :doc:`workflow` for the lower-level orchestration package.
