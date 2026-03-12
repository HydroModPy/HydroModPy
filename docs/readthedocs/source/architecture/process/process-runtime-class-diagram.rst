Process Runtime Class Diagram
=============================

Scope
-----

This diagram shows runtime inheritance and composition for process objects:

- ``ProcessSpatial`` as the abstract runtime base.
- ``Flow`` and ``Transport`` as concrete process implementations.
- Runtime initial conditions, boundary conditions, and sink/source containers.

Diagram source
--------------

.. uml:: diagrams/process_runtime_class.wsd

.. literalinclude:: diagrams/process_runtime_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - process runtime class diagram

Notes
-----

- ``Flow`` and ``Transport`` both inherit from ``ProcessSpatial``.
- ``FlowInitialCondition`` inherits from prototype ``InitialCondition``.
- Runtime boundary conditions stored by ``ProcessSpatial`` use prototype ``BoundaryCondition``.
- Runtime sink/source storage is generic (``dict[str, object]``), with process-specific payloads
  injected by child classes.
- Recharge chronicle preparation stays outside this inheritance tree and is
  handled by simulation forcing services before solver assembly.
