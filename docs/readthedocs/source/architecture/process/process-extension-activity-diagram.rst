Process Extension Activity Diagram
==================================

Scope
-----

This activity diagram proposes a practical workflow to add a new
``ProcessSpatial`` specialization in HydroModPy.

Diagram source
--------------

.. literalinclude:: diagrams/process_extension_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - process extension activity diagram

Notes
-----

- The flow follows config model first, then runtime class, then adapters.
- Testing and documentation updates are treated as mandatory completion steps.
- Iteration is expected before final integration.
