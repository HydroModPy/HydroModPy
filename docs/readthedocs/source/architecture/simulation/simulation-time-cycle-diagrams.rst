Simulation Time Cycle Diagrams
==============================

Scope
-----

These diagrams document the canonical time cycle driven by ``[simulation.time]``
in launcher workflows.

They focus on:

- normalization and validation of the simulation window,
- canonical stress-period grid construction,
- propagation toward forcing preparation and flow solvers,
- runtime decisions between canonical ``time_grid`` and solver ``tgrid`` fallback.

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
