Spatial support diagrams
========================

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

- ``hydromodpy/model/domain/domain_config.py``:
  high-level domain declaration including support registration.
- ``hydromodpy/model/domain/spatial_support_config.py``:
  typed support-definition models.
- ``hydromodpy/model/domain/spatial_support.py``:
  runtime support builders and providers.
- ``hydromodpy/model/domain/support_fields.py``:
  the band, ring and raster zone fields and their sampling on a mesh.
- ``hydromodpy/model/properties/field_param.py``:
  consumption point through ``field_spatial_id``.
- ``hydromodpy/model/properties/zone_fractions.py`` and
  ``hydromodpy/model/properties/property_table.py``: downstream discretization
  over the cells of the cell mesh.

Recommended reading path
------------------------

1. ``hydromodpy/model/domain/domain_config.py``
2. ``hydromodpy/model/domain/spatial_support_config.py``
3. ``hydromodpy/model/domain/spatial_support.py``
4. ``hydromodpy/model/properties/field_param.py``
5. ``hydromodpy/model/properties/zone_fractions.py`` and
   ``hydromodpy/model/properties/property_table.py``

Context
-------

Use this diagram to position the main modules and runtime responsibilities.

.. uml:: diagrams/spatial_support_context.wsd

Classes
-------

Use this diagram to document the supported zone-definition cases and the
relationships between ``DomainConfig``, support configs, provider classes,
support-field implementations, ``Field``, and ``FieldParam``.

.. uml:: diagrams/spatial_support_classes.wsd

Support resolution
------------------

Use this diagram to explain how explicit support declarations drive runtime
behavior and data dependencies.

.. uml:: diagrams/spatial_support_resolution_activity.wsd

Support build
-------------

Use this diagram to describe how the project facade builds and
registers support objects during setup and data phases.

.. uml:: diagrams/spatial_support_build_sequence.wsd

FieldParam mapping
------------------

Use this diagram to describe how a support is consumed when a heterogeneous
``FieldParam`` is mapped to solver arrays.

.. uml:: diagrams/spatial_support_fieldparam_sequence.wsd

Related diagrams
----------------

- :doc:`support-selection-guide`
- :doc:`../field/index`
- :doc:`../mesh/mesh-engines`
