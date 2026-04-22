Simulation Time Cycle Diagrams
==============================

Scope
-----

These diagrams document the canonical time cycle driven by ``[simulation.time]``
in launcher workflows.

They focus on:

- normalization and validation of the simulation window,
- canonical stress-period grid construction,
- strict launcher enforcement for flow-process time grids,
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
- ``hydromodpy.simulation.forcing`` remains the stable re-export surface used
  by orchestration code.

Code map
--------

- ``hydromodpy/simulation/settings.py``:
  typed simulation settings and canonical time-window validation.
- ``hydromodpy/process/hydrology/synthetic/forcing.py``:
  generator-side synthetic forcing helpers.
- ``hydromodpy/process/forcing/forcing_bridge.py``:
  generic forcing conversion and unit handling.
- ``hydromodpy/process/forcing/time_alignment.py``:
  stress-period aggregation.
- ``hydromodpy/process/flow/time_forcing.py``:
  flow-side forcing preparation before adapter dispatch.

Recommended reading path
------------------------

1. ``hydromodpy/simulation/settings.py``
2. ``hydromodpy/process/hydrology/synthetic/forcing.py``
3. ``hydromodpy/process/forcing/forcing_bridge.py``
4. ``hydromodpy/process/forcing/time_alignment.py``
5. ``hydromodpy/process/flow/time_forcing.py``

Class Diagram
-------------

.. uml:: diagrams/simulation_time_cycle_class.wsd

.. literalinclude:: diagrams/simulation_time_cycle_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - simulation time cycle class diagram

Structure Diagram
-----------------

.. uml:: diagrams/simulation_time_cycle_structure.wsd

.. literalinclude:: diagrams/simulation_time_cycle_structure.wsd
   :language: text
   :caption: PlantUML (.wsd) source - simulation time cycle structure diagram

Activity Diagram
----------------

.. uml:: diagrams/simulation_time_cycle_activity.wsd

.. literalinclude:: diagrams/simulation_time_cycle_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - simulation time cycle activity diagram

Related diagrams
----------------

- :doc:`launcher-simulation-class-diagram`
- :doc:`toml-to-solver-walkthrough`
