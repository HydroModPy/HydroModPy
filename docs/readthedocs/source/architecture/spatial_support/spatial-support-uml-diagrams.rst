Spatial Support UML Diagrams
============================

Scope
-----

These diagrams document the architecture around:

- ``domain.support_mode`` and ``domain.supports``,
- the different support-definition cases (generated bands, rings, catchment,
  geology),
- the bridge from domain-side supports to the generic ``Field`` contract,
- the way ``FieldParam`` consumes those supports during solver property
  mapping.

Context Diagram
---------------

Use this diagram to position the main modules and runtime responsibilities.

.. uml:: diagrams/spatial_support_context.wsd

.. literalinclude:: diagrams/spatial_support_context.wsd
   :language: text
   :caption: PlantUML (.wsd) source - spatial support context diagram

Class Diagram
-------------

Use this diagram to document the supported zone-definition cases and the
relationships between ``DomainConfig``, support configs, provider classes,
support-field implementations, ``Field``, and ``FieldParam``.

.. uml:: diagrams/spatial_support_classes.wsd

.. literalinclude:: diagrams/spatial_support_classes.wsd
   :language: text
   :caption: PlantUML (.wsd) source - spatial support class diagram

Support-Mode Activity Diagram
-----------------------------

Use this diagram to explain how ``support_mode = none|geology|zones`` drives
runtime behavior and data dependencies.

.. uml:: diagrams/spatial_support_mode_activity.wsd

.. literalinclude:: diagrams/spatial_support_mode_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - spatial support mode activity diagram

Support-Build Sequence Diagram
------------------------------

Use this diagram to describe how the launcher builds and registers support
objects during setup and data phases.

.. uml:: diagrams/spatial_support_build_sequence.wsd

.. literalinclude:: diagrams/spatial_support_build_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - spatial support build sequence diagram

FieldParam-Mapping Sequence Diagram
-----------------------------------

Use this diagram to describe how a support is consumed when a heterogeneous
``FieldParam`` is mapped to solver arrays.

.. uml:: diagrams/spatial_support_fieldparam_sequence.wsd

.. literalinclude:: diagrams/spatial_support_fieldparam_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - spatial support to FieldParam sequence diagram
