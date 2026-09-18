spatial
=======

``hydromodpy.spatial`` carries the spatial-support stack: catchment
delineation, geographic context, domain definition, mesh generation,
and the field abstractions that bridge geology to solver inputs.

Sub-modules
-----------

- ``spatial/delineation/`` -- backend-agnostic delineation. One shipped
  backend, ``WhiteboxWorkflowsBackend`` (D8 on a DEM raster). Other
  backends register through ``register_backend()``.
- ``spatial/terrain/`` -- the ``TerrainEngine`` port: five methods and two
  identifying strings, sized by what the flow chain asks for rather than by
  the 66-method Whitebox facade. Products declare what cannot be read back
  from their values (pointer convention, accumulation units and transform,
  conditioning method and extent, CRS). Two implementations serve it,
  ``WhiteboxTerrainEngine`` and ``NumpyTerrainEngine``, and the same
  conformance suite runs against both
  (``tests/contract/test_terrain_engine_contract.py``).
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
  ``FlatSubstratumDepthModel`` (fixed elevation). ``build.py`` is the one
  constructor of that geometry -- it copies the declared section before arming
  the binder zone ids on it -- and the setup step, the rebuild a second run on a
  live project triggers, the domain case script and the bundle exporter all go
  through it. Beside it, the ``domain-build`` capability: ``capability.py``
  declares it (``DOMAIN_BUILD``, ``DomainBuildRequest``) and ``worker.py`` runs
  it, sealing a bottom, a thickness, an active-cell mask and one
  ``domain.json`` from a terrain and a depth model. It declares
  ``reaches_network=()`` and ``writes_outside_jobdir=()``, and a gate holds it
  to both.
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
- ``spatial/site_selection/hydrology/`` -- besides the site-selection
  adapters, the ``terrain-delineate`` capability: ``capability.py``
  declares it (``TERRAIN_DELINEATE``, ``TerrainDelineateRequest``) and
  ``worker.py`` runs it. ``run(job, exit_code_for=...)`` takes a job
  directory, reads the one document the caller wrote, writes its six
  artefacts inside it and seals it. It opens no workspace, no catalog
  and no database, and registers nothing in the user's state directory.
  It declares ``reaches_network=()`` and a gate checks it against a real
  run, so "no network" is the declaration and not a hope. The exit-code
  mapper is an argument because
  ``spatial`` cannot import ``cli``, and because the exception a
  capability raises and the status a shim reads are two contracts.

Key public symbols
------------------

- ``hydromodpy.spatial.delineation.whitebox_workflows_backend.WhiteboxWorkflowsBackend``
- ``hydromodpy.spatial.terrain.{TerrainEngine, WhiteboxTerrainEngine, NumpyTerrainEngine}``
- ``hydromodpy.spatial.geographic.core.flow_products``
- ``hydromodpy.spatial.geographic.core.river_network``
- ``hydromodpy.spatial.geographic.core.hydrographic_network.HydrographicNetwork``
- ``hydromodpy.spatial.domain.Domain``
- ``hydromodpy.spatial.domain.build.build_domain``
- ``hydromodpy.spatial.domain.capability.DOMAIN_BUILD``
- ``hydromodpy.spatial.mesh.cartesian_grid.{SGridConfig, StructuredGridBuilder}``
- ``hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh.GmshPlanarMesh2D``
- ``hydromodpy.spatial.mesh.gmsh_grid.extruded_prism_mesh.ExtrudedPrismMesh3D``
- ``hydromodpy.spatial.mesh.HydroMesh``
- ``hydromodpy.spatial.field.core.{FieldSpatial, FieldParam}``
- ``hydromodpy.spatial.site_selection.hydrology.capability.TERRAIN_DELINEATE``
- ``hydromodpy.spatial.site_selection.hydrology.worker.run``

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
2. ``hydromodpy/spatial/geographic/core/domain_geographic_pipeline.py``
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
