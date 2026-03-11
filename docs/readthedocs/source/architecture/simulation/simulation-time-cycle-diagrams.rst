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

- ``hydromodpy.simulation.forcing.recharge_chronicle_config`` validates modes,
  generators, and inline rate units.
- ``hydromodpy.hydrology.synthetic.forcing`` generates conceptual hydrological
  signals such as ``seasonal_step``.
- ``hydromodpy.simulation.forcing.recharge_chronicle`` converts these series to
  ``m/s`` and aligns them on simulation stress-period boundaries.

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
