discretization
==============

``hydromodpy.discretization`` hosts numerical discretization primitives
that are shared by solver backends but are not themselves solver policy.
It currently contains temporal grid generation.

Sub-modules
-----------

- ``discretization/time/`` -- ``TMeshConfig``, ``TmeshGenerator`` and
  ``TimeGrid`` for period lengths, time-step counts and derived datetime
  vectors.
- ``discretization/time/cases/`` -- small runnable temporal-grid demo
  scenarios.

Key public symbols
------------------

- ``hydromodpy.discretization.time.TMeshConfig``
- ``hydromodpy.discretization.time.TmeshGenerator``
- ``hydromodpy.discretization.time.TimeGrid``
- ``hydromodpy.discretization.time.load_tmesh_toml``
- ``hydromodpy.discretization.time.validate_tmesh_config_data``

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema`` and ``discretization``.
- Allowed sources: ``solver`` and top-level orchestration layers that
  already consume solver/config APIs.
- Temporal discretization does not import ``physics``. Flow regime policy
  is assembled by solver adapters from ``flow.flow_regime`` and
  ``flow.first_period_steady``.

See also
--------

- :doc:`core` for time-window resolution under ``core/time``.
- :doc:`solver` for MODFLOW temporal-discretization assembly.
