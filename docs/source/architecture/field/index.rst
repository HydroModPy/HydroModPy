Field Architecture
==================

This section documents the ``hydromodpy.spatial.field`` layer.

Open it when you want:

- the reusable field abstractions behind ``FieldSpatial`` and
  ``FieldParam``;
- the concrete mesh implementations reused by geology and solver
  adapters;
- the bridge from field-side zoning to solver-side discretization
  workflows.

Code map
--------

- ``hydromodpy/spatial/field/core/field_spatial.py``: reusable
  field-side zone/value carrier.
- ``hydromodpy/spatial/field/core/field_param.py`` and
  ``field_param_config.py``: heterogeneous parameter contract
  consumed downstream by solvers.
- ``hydromodpy/spatial/field/meshes/``: concrete structured and
  triangular mesh implementations.
- ``hydromodpy/spatial/field/geology/``: geology-backed
  specialisations built on the same field contract.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/field/README.md``
2. ``hydromodpy/spatial/field/core/field_spatial.py``
3. ``hydromodpy/spatial/field/core/field_param.py``
4. one mesh implementation under
   ``hydromodpy/spatial/field/meshes/``
5. ``hydromodpy/spatial/field/cases/square/`` for a concrete runnable
   example

Core class diagram
------------------

This view is intentionally limited to the reusable ``field.core``
abstractions.

.. uml:: diagrams/field_classes.wsd

Square case relation diagram
----------------------------

This view shows how the square example specialises the core
abstractions and which concrete mesh implementations it reuses.

.. uml:: diagrams/field_spatial_cases_classes.wsd

Activity diagram
----------------

.. uml:: diagrams/field_activity.wsd

Sequence diagram
----------------

.. uml:: diagrams/field_sequence.wsd

Related pages
-------------

- :doc:`../spatial_support/spatial-support-uml-diagrams`
- :doc:`../mesh/structured-grid-architecture`
- :doc:`../mesh_pivot` for the cross-mesh pivot format.
