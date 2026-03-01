Process Config Class Diagram
============================

Scope
-----

This diagram shows validated configuration classes (Pydantic models):

- Shared ``ProcessSpatialConfig`` base.
- ``FlowConfig`` and ``TransportConfig`` specializations.
- Flow-specific initial conditions, boundary conditions, and sink/source configs.

Diagram source
--------------

.. literalinclude:: diagrams/process_config_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - process config class diagram

Notes
-----

- ``FlowConfig`` and ``TransportConfig`` inherit from ``ProcessSpatialConfig``.
- ``FlowInitialCondition`` inherits from prototype ``InitialCondition``.
- ``FlowBoundaryConditionConfig`` and ``FlowSinksSourcesConfig`` are dedicated flow models
  (not subclasses of prototype ``BoundaryCondition`` / ``SinkSource``).
- ``TransportConfig`` currently keeps boundary and sink/source payloads as generic mappings.
