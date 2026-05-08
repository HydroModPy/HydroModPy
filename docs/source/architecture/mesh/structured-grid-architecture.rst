Structured Grid Architecture
============================

This page documents the FloPy ``StructuredGrid`` path used by the
MODFLOW-family solvers: static object model, build sequence, and the
bridge to ``Field`` / ``FieldParam`` for solver-ready arrays.

Code map
--------

- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_config.py``:
  validated grid config contract.
- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_from_config.py``:
  public build entry point.
- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_generation.py``:
  ``StructuredGridBuilder`` and geometric assembly.
- ``hydromodpy/spatial/mesh/cartesian_grid/utils/raster_grid_reader.py``:
  top-surface raster loading.
- ``hydromodpy/spatial/mesh/cartesian_grid/utils/planar_discretizer.py``:
  planar discretization helpers.
- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_mesh_adapter.py``:
  geometry bridge from solver grid to field-side mesh logic.
- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_field_discretization.py``:
  field discretization helpers.
- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_fieldparam_discretization.py``:
  heterogeneous parameter mapping to solver arrays.
- ``hydromodpy/solver/modflow_common/solver_mesh.py``: solver-side
  consumer of the resolved mesh contract.
- ``hydromodpy/spatial/field/core/field_param.py``: upstream field
  parameter contract.

Recommended reading path:

1. ``sgrid_config.py`` and ``sgrid_from_config.py``
2. ``raster_grid_reader.py`` and ``planar_discretizer.py``
3. ``sgrid_generation.py``
4. ``sgrid_mesh_adapter.py``
5. ``sgrid_field_discretization.py`` and
   ``sgrid_fieldparam_discretization.py``

Static class diagram
--------------------

The static object model around FloPy ``StructuredGrid``: HydroModPy
domain objects that feed the builder, the narrow responsibility of
``StructuredGridBuilder``, the boundary between HydroModPy classes
and the external FloPy grid, and the downstream adapters that read
``StructuredGrid`` geometry.

Reading guide:

- ``-->`` means a stable relation or a produced object.
- ``..>`` means a transient usage or read dependency.

.. uml:: diagrams/structured_grid_class.wsd

.. literalinclude:: diagrams/structured_grid_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - StructuredGrid class diagram

Notes:

- ``StructuredGrid`` itself belongs to FloPy. The diagram focuses on
  the HydroModPy classes that prepare or consume it.
- ``SGridConfig``, ``RasterGridReader``, and ``PlanarDiscretizer``
  are not shown here on purpose; they belong to the build sequence
  below.

Build sequence
--------------

The dynamic workflow that turns one user-facing SGrid config payload
into one FloPy ``StructuredGrid``: validation and normalisation of
``SGridConfig``, top-surface loading and planar discretisation, the
branches that resolve the bottom surface, and the final handoff to
``StructuredGridBuilder``.

Reading guide:

- ``->`` means a call.
- ``-->`` means a returned value.
- ``alt`` blocks show the mutually exclusive bottom-surface
  strategies driven by ``cfg.genmtd_bot``.

.. uml:: diagrams/structured_grid_build_sequence.wsd

.. literalinclude:: diagrams/structured_grid_build_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - StructuredGrid build sequence diagram

Notes:

- ``build_sgrid_from_config(...)`` owns config resolution and surface
  preparation.
- ``StructuredGridBuilder`` stays narrower: it validates top/bottom
  geometric consistency, computes vertical layering, and instantiates
  the FloPy grid.

SGrid / FieldParam discretization
---------------------------------

How HydroModPy bridges FloPy ``StructuredGrid`` (solver side), planar
field meshes (field/geology side), and ``Field`` / ``FieldParam``
value mapping for solver-ready arrays.

Class view:

.. uml:: diagrams/sgrid_fieldparam_discretization_class.wsd

.. literalinclude:: diagrams/sgrid_fieldparam_discretization_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - SGrid/FieldParam discretization class diagram

Activity view:

.. uml:: diagrams/sgrid_fieldparam_discretization_activity.wsd

.. literalinclude:: diagrams/sgrid_fieldparam_discretization_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - SGrid/FieldParam discretization activity diagram

See also
--------

- :doc:`catchment-mesh-architecture` for the unstructured / Gmsh
  catchment-mesh path.
- :doc:`../field/index` for the field-side abstractions consumed
  here.
- :doc:`../spatial_support/spatial-support-uml-diagrams` for the
  parameter support layer above.
- :doc:`../mesh_pivot` for the cross-mesh pivot format.
- :doc:`../modflow_contracts` for the DIS / BAS contract that
  consumes the structured grid.
