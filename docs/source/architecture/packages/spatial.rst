spatial
=======

``hydromodpy.spatial`` carries the spatial-support stack: catchment
delineation, geographic context, domain definition, mesh generation,
and the field abstractions that bridge geology to solver inputs.

Sub-modules
-----------

- ``spatial/delineation/`` -- backend-agnostic delineation. Default
  backends: ``WhiteboxWorkflowsBackend`` (D8 on a DEM raster) and
  ``SyntheticBackend``. Other backends register through
  ``register_backend()``.
- ``spatial/geographic/`` -- pre-simulation pipeline:
  ``flow_products`` (D8 correction and accumulation rasters),
  ``catchment_from_point`` and ``catchment_from_polygon``,
  ``river_network`` (Strahler order, pruning),
  ``hydrographic_network`` (canonical concept shared with comparison
  and display layers), ``domain_geographic_pipeline`` (high-level
  orchestration).
- ``spatial/domain/`` -- ``Domain`` aggregates ``surface_topo``,
  ``substratum`` (via depth model), and ``zones``. Two depth models
  ship: ``ConstantThicknessDepthModel`` (homogeneous offset),
  ``FlatSubstratumDepthModel`` (fixed elevation).
- ``spatial/mesh/cartesian_grid/`` -- DIS / structured path. Pydantic
  ``SGridConfig``, ``StructuredGridBuilder``, FloPy ``StructuredGrid``
  output.
- ``spatial/mesh/gmsh_grid/`` -- DISV / unstructured path. Conformal
  Gmsh meshing from polygons (geology, river network),
  ``catchment_mesh_bundle`` for self-contained export,
  ``extruded_prism_mesh`` for vertical extrusion to 3D.
- ``spatial/field/`` -- ``FieldSpatial`` (geometric zones),
  ``FieldParam`` (homogeneous or per-zone values with vertical
  profile), and the ``HydroMesh`` pivot that unifies every mesh
  representation.

Key public symbols
------------------

- ``hydromodpy.spatial.delineation.WhiteboxWorkflowsBackend``
- ``hydromodpy.spatial.geographic.flow_products``
- ``hydromodpy.spatial.geographic.river_network``
- ``hydromodpy.spatial.geographic.hydrographic_network.HydrographicNetwork``
- ``hydromodpy.spatial.domain.Domain``
- ``hydromodpy.spatial.mesh.cartesian_grid.{SGridConfig, StructuredGridBuilder}``
- ``hydromodpy.spatial.mesh.gmsh_grid.GmshPlanarMesh2D``
- ``hydromodpy.spatial.mesh.gmsh_grid.ExtrudedPrismMesh3D``
- ``hydromodpy.spatial.mesh.HydroMesh``
- ``hydromodpy.spatial.field.core.{FieldSpatial, FieldParam}``

HydroMesh pivot
---------------

``HydroMesh`` is a frozen dataclass that represents any 2D or 3D
mesh in a uniform way:

.. code-block:: python

   mesh = HydroMesh(
       vertices=points_xy,
       cell_blocks=(CellBlock(CellType.TRIANGLE, conn),),
       cell_data={"K": conductivity_array},
       point_data={},
       structured_shape=(nrow, ncol),  # optional hint
   )

Every concrete mesh class exposes ``.to_hydro_mesh()``. The pivot
unifies plotting, VTU I/O, and conversions toward FloPy's
``StructuredGrid`` (DIS) and DISV. See :doc:`/architecture/mesh/mesh-pivot`
for the full reference.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/geographic/README.md``
2. ``hydromodpy/spatial/geographic/domain_geographic_pipeline.py``
3. ``hydromodpy/spatial/domain/domain.py``
4. ``hydromodpy/spatial/field/README.md`` for the FieldSpatial /
   FieldParam contract.
5. ``hydromodpy/spatial/mesh/README.md`` for the meshing routes.
6. ``hydromodpy/spatial/mesh/cartesian_grid/README.md`` for DIS
   path.
7. ``hydromodpy/spatial/mesh/gmsh_grid/README.md`` for DISV path.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``spatial``.
- Allowed sources: ``simulation``, ``solver``, ``calibration``,
  ``results`` (tolerance), ``physics`` (tolerance for
  ``FieldSection``), ``data`` (tolerance for geology field).
- New cross-edges into ``spatial`` are not added without a clear
  rationale; the layer is intentionally narrow.

See also
--------

- :doc:`/architecture/mesh/mesh-pivot` -- ``HydroMesh`` pivot reference.
- :doc:`/architecture/mesh/gmsh-meshing` -- conformal Gmsh pipeline.
- :doc:`/architecture/mesh/catchment-mesh-architecture` --
  catchment-mesh workflow.
- :doc:`/architecture/mesh/structured-grid-architecture` --
  StructuredGrid path.
- :doc:`/architecture/spatial_support/index` -- spatial-support
  selection guide.
- :doc:`/architecture/field/index` -- field abstractions.
