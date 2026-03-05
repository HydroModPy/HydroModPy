Data Definition And Transfer Class Diagram
==========================================

Scope
-----

This diagram documents the static collaboration that defines which data must be
prepared, then transfers those data objects to the runtime state where they are
consumed.

It focuses on:

- data-type inference and normalization (`DataManagersPlanner` -> `DataLoadPlan`),
- transfer of resolved data types into the launcher config and runtime state,
- setup-time transfer for geology (`GeologyField` -> `Domain.set_zone`),
- hook-time transfer for hydrometry (`StationSet` -> `RunResult.hydrometry`).

Diagram source
--------------

.. uml:: diagrams/data_definition_transfer_class.wsd

.. literalinclude:: diagrams/data_definition_transfer_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - data definition and transfer class diagram

Notes
-----

- `DataLoadPlan` defines **which** data families are active.
- `_run_setup` and hooks define **where** corresponding objects are stored.
- Geology is transferred into `Domain` as a zone used by process solvers.
- Hydrometry is transferred into `RunResult` for diagnostics and downstream use.
