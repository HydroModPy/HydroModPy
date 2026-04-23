StructuredGrid Build Sequence Diagram
=====================================

Scope
-----

This diagram documents the dynamic workflow that turns one user-facing SGrid
config payload into one FloPy ``StructuredGrid``.

It highlights:

- validation and normalization of ``SGridConfig``,
- top-surface loading and planar discretization,
- the different branches used to resolve the bottom surface,
- the final handoff to ``StructuredGridBuilder`` for grid assembly.

Code map
--------

- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_config.py``:
  validated grid config contract.
- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_from_config.py``:
  public build entry point.
- ``hydromodpy/spatial/mesh/cartesian_grid/utils/raster_grid_reader.py``:
  top-surface raster loading.
- ``hydromodpy/spatial/mesh/cartesian_grid/utils/planar_discretizer.py``:
  planar discretization helpers.
- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_generation.py``:
  final FloPy grid assembly.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_config.py``
2. ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_from_config.py``
3. ``hydromodpy/spatial/mesh/cartesian_grid/utils/raster_grid_reader.py``
4. ``hydromodpy/spatial/mesh/cartesian_grid/utils/planar_discretizer.py``
5. ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_generation.py``

Reading Guide
-------------

- ``->`` means a call.
- ``-->`` means a returned value.
- ``alt`` blocks show the mutually exclusive bottom-surface strategies driven
  by ``cfg.genmtd_bot``.

Diagram source
--------------

.. uml:: diagrams/structured_grid_build_sequence.wsd

.. literalinclude:: diagrams/structured_grid_build_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - StructuredGrid build sequence diagram

Notes
-----

- ``build_sgrid_from_config(...)`` owns config resolution and surface
  preparation.
- ``StructuredGridBuilder`` stays narrower: it validates top/bottom geometric
  consistency, computes vertical layering, and instantiates the FloPy grid.
- For the static class relationships around the resulting grid, see
  :doc:`structured-grid-class-diagram`.

Related diagrams
----------------

- :doc:`structured-grid-class-diagram`
- :doc:`sgrid-fieldparam-discretization-diagrams`
