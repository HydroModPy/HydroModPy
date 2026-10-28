Field layer
===========

This section documents the ``hydromodpy.spatial.field`` layer.

Open it when you want:

- the reusable field abstractions behind ``Field`` and
  ``FieldParam``;
- how a support samples the cells of a ``PlanarCellMesh``;
- the bridge from field-side zoning to solver-side discretization
  workflows.

Code map
--------

- ``hydromodpy/spatial/field/core/field_spatial.py``: reusable
  field-side zone/value carrier.
- ``hydromodpy/spatial/field/core/field_param.py`` and
  ``field_param_config.py``: heterogeneous parameter contract
  consumed downstream by solvers.
- ``hydromodpy/spatial/field/core/mesh_cells.py``: the cells of a
  ``PlanarCellMesh`` as a support samples them (``mesh_cells``), the
  check of one value per cell (``cell_values``) and ``MeshWithValues``.
- ``hydromodpy/spatial/field/zone_fractions.py``: the share of each
  zone of a support in each cell, which the solvers read.
- ``hydromodpy/spatial/field/plotting.py``: ``plot_cell_values``.
- ``hydromodpy/spatial/field/geology/``: geology-backed
  specialisations built on the same field contract.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/field/README.md``
2. ``hydromodpy/spatial/field/core/field_spatial.py``
3. ``hydromodpy/spatial/field/core/field_param.py``
4. ``hydromodpy/spatial/field/core/mesh_cells.py``
5. ``hydromodpy/spatial/field/cases/square/`` for a concrete runnable
   example

Core classes
------------

This view is intentionally limited to the reusable ``field.core``
abstractions.

.. uml:: diagrams/field_classes.wsd

Square case
-----------

This view shows how the square example specialises the core
abstractions and builds its unit-square meshes.

.. uml:: diagrams/field_spatial_cases_classes.wsd

Activity
--------

.. uml:: diagrams/field_activity.wsd

Sequence
--------

.. uml:: diagrams/field_sequence.wsd

Related pages
-------------

- :doc:`../spatial_support/spatial-support-uml-diagrams`
- :doc:`../mesh/mesh-engines`
- :doc:`../mesh/mesh-pivot` for the cross-mesh pivot format.
