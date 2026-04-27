Spatial Support UML Diagrams
============================

Scope
-----

These diagrams document the architecture around:

- ``domain.supports`` and ``domain.zone_ids``,
- the different support-definition cases (generated bands, rings, catchment,
  geology),
- the bridge from domain-side supports to the generic ``Field`` contract,
- the way ``FieldParam`` consumes those supports during solver property
  mapping.

Code map
--------

- ``hydromodpy/spatial/domain/domain_config.py``:
  high-level domain declaration including support registration.
- ``hydromodpy/spatial/domain/spatial_support_config.py``:
  typed support-definition models.
- ``hydromodpy/spatial/domain/spatial_support.py``:
  runtime support builders and providers.
- ``hydromodpy/spatial/field/core/field_param.py``:
  consumption point through ``field_spatial_id``.
- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_fieldparam_discretization.py``:
  downstream discretization over solver meshes.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/domain/domain_config.py``
2. ``hydromodpy/spatial/domain/spatial_support_config.py``
3. ``hydromodpy/spatial/domain/spatial_support.py``
4. ``hydromodpy/spatial/field/core/field_param.py``
5. ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_fieldparam_discretization.py``

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

Support-Resolution Activity Diagram
-----------------------------------

Use this diagram to explain how explicit support declarations drive runtime
behavior and data dependencies.

.. uml:: diagrams/spatial_support_resolution_activity.wsd

.. literalinclude:: diagrams/spatial_support_resolution_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - spatial support mode activity diagram

Support-Build Sequence Diagram
------------------------------

Use this diagram to describe how the project facade builds and
registers support objects during setup and data phases.

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

Related diagrams
----------------

- :doc:`support-selection-guide`
- :doc:`../field/field-uml-diagrams`
- :doc:`../mesh/sgrid-fieldparam-discretization-diagrams`
