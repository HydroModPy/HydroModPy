The mesh pivot and the cell mesh
================================

HydroModPy has several mesh types to place parameters such as conductivity and recharge.
``HydroMesh`` is the exchange format between them. ``PlanarCellMesh`` is the mesh that every
solver and every workflow step reads. The code is in ``hydromodpy/spatial/field/`` and
``hydromodpy/spatial/mesh/``. The engines are on :doc:`mesh-engines`, and the grid of the MODFLOW
family is on :doc:`../solver/backends`.

Mesh types
----------

.. code-block:: text

   BaseFieldMesh (ABC)                  spatial/field/core/field_mesh.py
   |-- StructuredFieldMesh              spatial/field/meshes/structured_field_mesh.py
   |     _kind = "structured"           quadrilaterals on a regular grid
   |-- TriangularStructuredFieldMesh    spatial/field/meshes/triangular_field_mesh.py
   |     _kind = "triangular_structured"
   |-- TriangularUnstructuredFieldMesh  spatial/field/meshes/triangular_field_mesh.py
   |     _kind = "triangular_unstructured"   Delaunay triangles
   |-- PolygonFieldMesh                 spatial/field/meshes/polygon_field_mesh.py
   |     _kind = "polygon"
   |-- GeologyStructuredMesh            spatial/field/geology/geology_mesh.py
   |     _kind = "structured_rect"      quadrilaterals in real coordinates
   `-- GmshPlanarMesh2D                 spatial/mesh/gmsh_grid/gmsh_planar_mesh.py
         _kind = "gmsh_2d"              triangles or quads from a .msh file

Every ``BaseFieldMesh`` has ``shape``, ``n_nodes``, ``n_cells``, ``cell_centroids()``,
``to_cell_values()`` and ``to_hydro_mesh()``. A ``MeshWithValues`` pairs a mesh with one value
per cell, and ``FieldParam.to_mesh_field()`` returns it.
``GmshPlanarMesh2D.from_file("domain.msh")`` reads a Gmsh mesh. A test mesh looks like this:

.. code-block:: python

   from hydromodpy.spatial.field.cases.square.field_mesh_square import FieldMeshSquare

   # mesh_kind: "structured", "triangular_structured" or "triangular_unstructured"
   mesh = FieldMeshSquare.from_unit_square(target_n_cells=400, mesh_kind="structured")
   mesh.n_cells      # 400
   mesh.shape        # (21, 21) nodes

Placing a parameter on a mesh
-----------------------------

A ``FieldParam`` (``spatial/field/core/field_param.py``) is a scalar or one value per zone, with
a unit and an optional vertical profile. A ``Field`` (``spatial/field/core/field_spatial.py``)
gives the zones, and a ``BaseFieldMesh`` gives the cells. A homogeneous parameter gives one value
per cell:

.. code-block:: python

   from hydromodpy.spatial.field.core.field_param import FieldParam

   K = FieldParam(identifier="K", kind="homogeneous", unit="m/s", value=1e-4)
   result = K.to_mesh_field(mesh=mesh)     # MeshWithValues, every cell 1e-4

A heterogeneous parameter (``kind="heterogeneous"``, ``values_by_key``, ``field_spatial_id``)
takes the zone-weighted mean in each cell, with the zone fractions of ``field.on_mesh(mesh, ...)``.
A vertical profile (``none``, ``exponential`` or ``tabulated``) multiplies the value by
``FieldParam.vertical_factor(depth)``. ``FieldParam`` stores values in SI units. The solvers do
not use this path. They map the parameters on the cell mesh, see
:ref:`consumers-read-the-cell-mesh`. The field layer is in :doc:`../field/index`.

The pivot
---------

``HydroMesh`` (``spatial/mesh/model/hydro_mesh.py``) is a frozen dataclass. It describes any 2D
or 3D mesh the same way, in the data model of meshio.

.. code-block:: python

   from hydromodpy.spatial.mesh import HydroMesh, CellBlock, CellType

   mesh = HydroMesh(
       vertices=points_xy,                                  # (n_nodes, 2 or 3)
       cell_blocks=(CellBlock(CellType.TRIANGLE, conn),),   # connectivity
       cell_data={"K": conductivity},                       # one value per cell
       structured_shape=None,                               # (nrow, ncol) for a regular grid
   )

Every mesh type converts to the pivot with ``to_hydro_mesh()``. The pivot serves the plot, the
disk formats and the solver adapters:

.. code-block:: text

   StructuredFieldMesh ---+                  +-- plot_cell_values()
   TriangularFieldMesh ---+                  +-- write_vtu() / read_vtu()
   PolygonFieldMesh ------+-- to_hydro_mesh -+-- to_flopy_disv_args()
   GmshPlanarMesh2D ------+                  +-- to_meshio()

``CellType`` has ``TRIANGLE``, ``QUADRILATERAL``, ``POLYGON`` (ragged cells, as in the
``voronoi`` engine), ``WEDGE`` and ``HEXAHEDRON``. It accepts aliases such as ``"tri"`` and
``"triangular_prism"``. ``is_structured`` is true when ``structured_shape`` is set. The plot then
uses ``pcolormesh``. ``SolverMesh.to_dis_kwargs()`` writes the DIS grid of MODFLOW-NWT only for a
cell mesh with a ``structured_shape``. ``with_cell_data`` and ``with_point_data`` return a new
instance because the class is frozen. New code takes and returns a ``HydroMesh``, so it does
not depend on a concrete mesh class.

Plot, disk and solver adapters
------------------------------

``plot_cell_values`` in ``spatial/mesh/plotting.py`` uses ``pcolormesh`` for a structured
quadrilateral mesh, ``tripcolor`` for triangles and ``PolyCollection`` otherwise. VTU is the
recommended disk format. It describes itself, opens in ParaView, PyVista and QGIS, and
round-trips through ``HydroMesh``. Use ``write_vtu`` and ``read_vtu`` from ``spatial/mesh/io``,
or ``load_planar_as_hydro_mesh``, ``save_hydro_mesh_vtu`` and ``load_hydro_mesh_vtu`` from
``spatial/mesh/gmsh_grid/exchange_api.py``. ``to_meshio`` and ``from_meshio`` in
``spatial/mesh/adapters`` need meshio, which is imported on demand. A ``.msh`` file carries no
CRS, so ``write_gmsh_2d_mesh`` given a ``crs`` writes its WKT to ``<name>.prj`` next to the mesh,
and ``read_gmsh_2d_mesh`` reads it back into ``crs_wkt``.
``to_flopy_disv_args(hydro_mesh, top=..., botm=...)`` returns the arguments of a MODFLOW 6 DISV
package (``nvert``, ``vertices``, ``ncpl``, ``cell2d``, ``top``, ``botm``). The core needs only
numpy, the plot needs matplotlib, and the adapters import meshio and flopy when called. A run
stores its cell mesh in Zarr and exports it as a GeoPackage, see :doc:`../storage-layout`.

Cell mesh
---------

``PlanarCellMesh`` (``spatial/mesh/model/planar_cell_mesh.py``) is the mesh that the solvers and
the workflow steps read, as ``setup.cell_mesh``. It wraps one planar ``HydroMesh`` block of
triangles, quadrilaterals or polygons, unchanged. It also holds what every consumer would
otherwise recompute:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Attribute
     - Content
   * - ``centers``, ``center_kind``
     - The one cell centre rule, shape ``(n_cells, 2)``. ``center_kind`` is ``generator``
       (Voronoi), ``cell_center`` (regular grid) or ``vertex_mean`` (triangles).
   * - ``crs_wkt``
     - The CRS of the vertices, as WKT. It is required.
   * - ``face_families``, ``cell_chains``
     - The face rows and the cell chains of the line families, see below.
   * - ``cell_zone``, ``zone_names``
     - The zone index of each cell, ``-1`` when unknown, and the sorted zone names.
   * - ``identity``
     - ``MeshIdentity``: engine id, engine version, request hash and seed.
   * - ``qa``
     - ``MeshQA``: quantiles of area, size, centre offset, non-orthogonality and cell shape,
       then the concave cells, the degenerate faces, the family coverage and the engine
       declarations (``graded``, ``exact_faces``, ``deterministic``, ``needs_cache``).
       ``quality_warnings`` turns the shape entries into build warnings and never refuses a mesh.
   * - ``structured_shape``
     - ``(nrow, ncol)`` of a regular grid, otherwise ``None``.
   * - ``smoothed_catchment``
     - The catchment outline the planner smoothed and the mesh followed, otherwise ``None``.
       The planner gives it by ``smoothed_catchment(mesh_cfg, inputs)``, and
       ``PlanningInputs.outlet`` keeps the declared outlet on it.

``cell_mesh.geometry`` is a ``DerivedGeometry`` (``spatial/mesh/model/derived_geometry.py``),
derived once on first use. It holds the ``-1`` padded connectivity (the format of the Zarr
store), the areas and area centroids, the edge table (``edge_nodes``, ``edge_cells``, length and
midpoint) and the CSR adjacency of the interior edges. An edge shared by more than two cells
raises ``ValueError``. ``cell_mesh.connectivity_rows`` returns the cells as one array. It is the
block itself for triangles and quadrilaterals, and the padded rows for polygons.

``cell_mesh_from_bundle`` in ``spatial/mesh/gmsh_grid/bundle_cell_mesh.py`` reads a Boussinesq
validation bundle, a folder of CSV files. The format is versioned. ``metadata.json`` declares
``mesh_catchment_bundle_v1``, the value of ``BUNDLE_SCHEMA_VERSION``, and ``BUNDLE_COLUMNS`` gives
the columns of each file, both in ``spatial/mesh/gmsh_grid/catchment_mesh_bundle_reader.py``. ``to_field_mesh(cell_mesh.mesh)`` in
``adapters/field_mesh_adapter.py`` gives a field mesh to a consumer that samples a field on the
cells.

Line families
~~~~~~~~~~~~~

A family is a set of lines that the mesh honours, under one name. Its intent decides what the
cell mesh keeps.

- A cell family (``rivers``) runs through the cells. ``cell_chains`` holds one chain of cells per
  line, from upstream to downstream. ``CellChain.offset_m`` gives the distance from each cell
  centre to the line. The ``voronoi`` engine fills it, and it is ``None`` where the cell holds the
  line.
- A face family (``geology``, ``lakes``, ``barriers``, ``watershed_boundary``) lies on cell
  faces. ``face_families`` has one row per mesh edge on a line, with the two cells (``-1``
  outside the domain), the two vertices and the zone on each side. An edge on two families, such
  as a cutoff wall along a lake shore, has a row in each. The four sides of the domain are face
  families named ``boundary:<side>``.

The ``cell_families`` capability of an engine says how it forms a cell family: exactly, by
rasterizing the line, or from the faces. The intent of each family comes from
``[mesh.families]``.

.. _consumers-read-the-cell-mesh:

Consumers read the cell mesh
----------------------------

Every consumer reads the cell mesh, and none reads an engine-specific support. One function
serves every engine for each question:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Question
     - Where
   * - Centres, areas, adjacency
     - ``SolverMesh.cell_centroids()``, ``cell_areas()`` and ``face_adjacency()``, read from
       ``cell_mesh.geometry``.
   * - Cells of a side, of the river, of a label
     - ``side_cells``, ``stream_cells``, ``label_cells`` in ``spatial/mesh/ops/family_cells.py``.
   * - Cell that holds a point
     - ``locate_cells`` in ``spatial/mesh/ops/cell_location.py``. For a point outside the mesh,
       ``locate_cells_near`` gives the nearest cell only within one cell size (the square root
       of its area), and otherwise gives no cell and warns. The solvers call
       ``locate_cell_on_solver_mesh`` in ``solver/base/cell_lookup.py``, which uses the top active
       layer of the column.
   * - Forcing grids and stations on the cells
     - ``discretize_fields_on_cells`` and ``discretize_points_on_cells`` in
       ``spatial/mesh/forcing/``. The method ``area`` (``_area.py``) clips each cell by the
       pixels its box reaches and needs the planar mesh.
   * - Zone fractions of a cell
     - ``zone_fractions`` in ``spatial/field/zone_fractions.py``. It uses the zone the engine
       gave the cell when the faces lie on the contacts, else the polygon areas of a vector
       geology source, else the sampling of the support.
   * - K, Sy and Ss on the cells
     - ``map_flow_properties`` in ``solver/field_property_mapping.py``, for MODFLOW 6,
       MODFLOW-NWT and Boussinesq.
   * - HFB, lake and SFR cells
     - ``spatial/mesh/ops/flow_barrier.py``, ``family_interior.py`` and ``line_on_chain.py``.
   * - The catchment of the run
     - The basin of the descent D, computed once per build and stored with the mesh
       (``mesh/descent_basin``), and the share of each cell inside the delineated polygon
       (``mesh/catchment_fraction``, ``cell_area_fraction`` in
       ``spatial/mesh/ops/vector_cell_mask.py``), see :doc:`../storage-layout`.

Every engine gives a river as cell chains. A triangle mesh also keeps the faces of the river
line as face rows.

Module layout
-------------

.. code-block:: text

   hydromodpy/spatial/mesh/
   |-- model/               the mesh classes, DerivedGeometry, MeshQA, RegularGrid
   |-- port.py              MeshEngine, MeshEngineCapabilities
   |-- registry.py          engine id to class, entry-point group hydromodpy.mesh.engine
   |-- request.py           MeshRequest, LineFamilySpec, RasterGridSpec, SizeField
   |-- cache.py             meshes an engine cannot rebuild bit for bit
   |-- engines/             regular/, triangle/, voronoi/
   |-- planning/            plan_mesh_request, catchment_outline.py, cleanup.py, input_mesh.py
   |-- sizing/              size_field.py, gap.py
   |-- refinement/          models of [[mesh.refinement_zone]] and [mesh.lake_refinement],
   |                        height_above_stream.py and run_fields.py (the fields a zone reads)
   |-- config/              the [mesh] models
   |-- forcing/             grids and stations on the cell centres, spatial_interpolation.py
   |-- ops/                 shared cell helpers
   |-- adapters/            meshio, field mesh, FloPy, cell_mesh.py
   |-- io/                  VTU
   |-- plotting.py
   |-- structured_grid/     grid of the regular engine, keys of the top sampling
   `-- gmsh_grid/           .msh and bundle readers, GmshPlanarMesh2D, exchange_api.py

The vertical layers live outside this folder, in ``spatial/domain/layers_config.py`` and
``layering.py``.

What the solvers read
---------------------

A solver reads the ``SolverMesh`` of ``hydromodpy/solver/modflow_grid/solver_mesh.py``. It is
built from the cell mesh and the vertical layers of ``[domain.layers]``, which both MODFLOW
backends read. ``layer_stack`` in ``spatial/domain/layering.py`` turns shares or surfaces into
the layer bottoms and the integer ``idomain`` (1, 0 or -1). ``discretization_spatial.py``, next
to ``solver_mesh.py``, samples the base rasters on the cell centres or resamples them to a
regular grid. ``SolverMesh`` checks the interfaces once it is built, and the run stores them with
the ``idomain``, see :doc:`../storage-layout`. ``active_connectivity.py`` warns when some groups
of active cells have no connection to the rest. The MODFLOW 6 build and the MODFLOW-NWT solver
call it on the final grid, after the lake mask, and it counts a pass-through cell and a lake as
connections.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Backend
     - Mesh it reads
   * - MODFLOW 6
     - DISV for every engine. A regular grid is also written as DISV, through
       ``SolverMesh.to_disv_kwargs()``, which calls ``to_flopy_disv_args``.
   * - MODFLOW-NWT
     - A DIS grid, which only the ``regular`` engine gives.
   * - Boussinesq
     - The triangles of the cell mesh. A validation case gives a bundle, which
       ``cell_mesh_from_bundle`` turns into a cell mesh.

Each flow adapter declares the engines it reads in ``accepted_meshes``, see :doc:`mesh-engines`.

Design choices
--------------

xugrid handles 2D and layered pseudo-3D meshes (UGRID2D) but not fully 3D unstructured ones, so
it cannot be the pivot. meshio is an optional I/O dependency. Its ``meshio.Mesh`` is mutable and
supports about thirty cell types, most of them useless here. ``HydroMesh`` is a strict, frozen
subset of that model, with round trips through the adapters.

See also
--------

- :doc:`mesh-engines` for the port, the planner and the three engines.
- :doc:`voronoi-engine` and :doc:`triangle-engine` for the two engines that use a size field.
- :doc:`index` for the mesh section.
- :doc:`../storage-layout` for the mesh in the Zarr store and its Parquet tables.
- :doc:`../solver/backends` for the DIS and BAS contracts that consume the regular grid.
