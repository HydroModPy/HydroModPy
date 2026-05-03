Process Config Class Diagram
============================

Scope
-----

This diagram shows validated configuration classes (Pydantic models):

- Shared ``ProcessSpatialConfig`` base.
- ``FlowConfig`` and ``TransportConfig`` specializations.
- Flow-specific initial conditions, boundary conditions, and sink/source configs.

Code map
--------

- ``hydromodpy/physics/base/process_spatial_config.py``:
  shared validated config contract.
- ``hydromodpy/physics/flow/flow_config.py``:
  flow-specific validated config model.
- ``hydromodpy/physics/transport/transport_config.py``:
  transport-specific validated config model.
- ``hydromodpy/physics/flow/*_config.py``:
  dedicated flow-side config payloads.

Recommended reading path
------------------------

1. ``hydromodpy/physics/base/process_spatial_config.py``
2. ``hydromodpy/physics/flow/flow_config.py``
3. ``hydromodpy/physics/transport/transport_config.py``
4. one specialized flow config file such as
   ``hydromodpy/physics/flow/boundary_conditions_config.py``

Diagram source
--------------

.. uml:: diagrams/process_config_class.wsd

.. literalinclude:: diagrams/process_config_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - process config class diagram

Notes
-----

- ``FlowConfig`` and ``TransportConfig`` inherit from ``ProcessSpatialConfig``.
- ``FlowInitialCondition`` inherits from base ``InitialCondition``.
- ``FlowBoundaryConditionConfig`` and ``FlowSinksSourcesConfig`` are dedicated flow models
  (not subclasses of base ``BoundaryCondition`` / ``SinkSource``).
- ``TransportConfig`` currently keeps boundary and sink/source payloads as generic mappings.

Related diagrams
----------------

- :doc:`process-runtime-class-diagram`
- :doc:`process-extension-activity-diagram`
- :doc:`process-package-map`
