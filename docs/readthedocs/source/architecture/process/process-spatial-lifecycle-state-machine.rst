ProcessSpatial Lifecycle State Machine
======================================

Scope
-----

This state machine captures the usual lifecycle of a ``ProcessSpatial``-based
runtime object from creation to solver execution and post-processing.

Diagram source
--------------

.. uml:: diagrams/process_spatial_lifecycle_state.wsd

.. literalinclude:: diagrams/process_spatial_lifecycle_state.wsd
   :language: text
   :caption: PlantUML (.wsd) source - ProcessSpatial lifecycle state machine

Notes
-----

- ``RuntimeHydrated`` means parameters, IC, BC, and sinks/sources are set.
- ``PreparedForSolver`` represents adapter-resolved arrays/dictionaries.
- Failures can route back to hydration after config or data corrections.
