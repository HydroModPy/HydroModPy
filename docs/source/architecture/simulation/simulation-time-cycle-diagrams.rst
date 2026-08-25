Simulation Time Cycle Diagrams
==============================

Scope
-----

These diagrams document the canonical time cycle driven by
``[simulation.time]`` inside the simulation orchestration layer.

They focus on:

- normalization and validation of the simulation window,
- canonical stress-period grid construction,
- strict orchestration-level enforcement for flow-process time grids,
- typed validation of ``[recharge_chronicle]`` payloads before runtime use,
- propagation toward forcing preparation and flow solvers,
- generator-based forcing built at fine resolution then aggregated to stress periods,
- runtime coordination between canonical ``time_grid`` and solver ``tgrid``.

The forcing path now separates three responsibilities:

- ``hydromodpy.physics.hydrology.synthetic.forcing`` generates conceptual hydrological
  signals such as ``seasonal_step``.
- ``hydromodpy.physics.forcing.forcing_bridge`` converts loaded data to
  homogeneous or heterogeneous solver-ready forcing payloads.
- ``hydromodpy.physics.forcing.time_alignment`` aligns series on simulation
  stress-period boundaries.
- ``hydromodpy.physics.flow.time_forcing`` prepares the flow-side payload
  handed to the solver adapters.

Code map
--------

- ``hydromodpy/simulation/planning/config.py``:
  typed simulation settings and canonical time-window validation.
- ``hydromodpy/physics/hydrology/synthetic/forcing.py``:
  generator-side synthetic forcing helpers.
- ``hydromodpy/physics/forcing/forcing_bridge.py``:
  generic forcing conversion and unit handling.
- ``hydromodpy/physics/forcing/time_alignment.py``:
  stress-period aggregation.
- ``hydromodpy/physics/flow/time_forcing.py``:
  flow-side forcing preparation before adapter dispatch.

Recommended reading path
------------------------

1. ``hydromodpy/simulation/planning/config.py``
2. ``hydromodpy/physics/hydrology/synthetic/forcing.py``
3. ``hydromodpy/physics/forcing/forcing_bridge.py``
4. ``hydromodpy/physics/forcing/time_alignment.py``
5. ``hydromodpy/physics/flow/time_forcing.py``

Class Diagram
-------------

.. uml:: diagrams/simulation_time_cycle_class.wsd

Structure Diagram
-----------------

.. uml:: diagrams/simulation_time_cycle_structure.wsd

Activity Diagram
----------------

.. uml:: diagrams/simulation_time_cycle_activity.wsd

Related diagrams
----------------

- :doc:`simulation-orchestration-class-diagram`
- :doc:`toml-to-solver-walkthrough`
