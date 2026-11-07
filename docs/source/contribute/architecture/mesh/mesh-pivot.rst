The mesh pivot and the cell mesh
================================

``HydroMesh`` is the exchange format of a mesh. ``PlanarCellMesh`` wraps a planar one, and it
is the mesh that every solver, every workflow step and every field support reads. The code is in
``hydromodpy/spatial/mesh/``, and the field supports that sample the cells are in
``hydromodpy/model/properties/``. The engines are on :doc:`mesh-engines`, and the grid of the MODFLOW
family is on :doc:`../solver/backends`.

Mesh types
----------

``HydroMesh`` and ``PlanarCellMesh`` are the two mesh classes. A mesh engine builds a
``PlanarCellMesh`` from a request. ``FieldMeshSquare`` builds one on the unit square for the
field demos and the tests:

.. code-block:: python

   from hydromodpy.model.properties.unit_square_mesh import FieldMeshSquare

   # mesh_kind: "structured", "triangular_structured" or "triangular_unstructured"
   mesh = FieldMeshSquare.from_unit_square(target_n_cells=400, mesh_kind="structured")
   mesh.n_cells        # 400
   mesh.mesh.n_nodes   # 441

Placing a parameter on a mesh
-----------------------------

A ``FieldParam`` (``model/properties/field_param.py``) is a scalar or one value per zone, with
a unit and an optional vertical profile. A ``Field`` (``model/properties/field_spatial.py``)
gives the zones, and a ``PlanarCellMesh`` gives the cells. A homogeneous parameter gives one value
per cell:

.. code-block:: python

   from hydromodpy.model.properties.field_param import FieldParam

   K = FieldParam(identifier="K", kind="homogeneous", unit="m/s", value=1e-4)
   result = K.to_mesh_field(mesh=mesh)     # MeshWithValues, every cell 1e-4

A heterogeneous parameter (``kind="heterogeneous"``, ``values_by_key``, ``field_spatial_id``)
takes the zone-weighted mean in each cell, with the zone fractions of
``field.on_mesh(cell_mesh, ...)``. A vertical profile (``none``, ``exponential`` or
``tabulated``) multiplies the value by ``FieldParam.vertical_factor(depth)``. ``FieldParam``
stores values in SI units. The solvers take the zone fractions from ``zone_fractions``, see
:ref:`consumers-read-the-cell-mesh`. The field layer is in :doc:`../field/index`.

The pivot
---------

``HydroMesh`` (``spatial/mesh/model/hydro_mesh.py``) is a frozen dataclass. It describes any 2D
or 3D mesh the same way, in the data model of meshio.

.. code-block:: python

   from hydromodpy.spatial.mesh.model.cell_types import CellType
   from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh

   mesh = HydroMesh(
       vertices=points_xy,                                  # (n_nodes, 2 or 3)
       cell_blocks=(CellBlock(CellType.TRIANGLE, conn),),   # connectivity
       cell_data={"K": conductivity},                       # one value per cell
       structured_shape=None,                               # (nrow, ncol) for a regular grid
   )

A ``PlanarCellMesh`` holds its pivot as ``.mesh``. The pivot serves the disk formats and the
solver adapters.

``CellType`` has ``TRIANGLE``, ``QUADRILATERAL``, ``POLYGON`` (cells of any node count, as in
the ``voronoi`` engine), ``WEDGE`` and ``HEXAHEDRON``. It accepts aliases such as ``"tri"`` and
``"triangular_prism"``. A ``CellBlock`` holds one ``(n_cells, k)`` table of node ids. A polygon
block has as many columns as its largest cell, the nodes of a cell fill its row from the left and
the free slots hold ``-1``. It also takes one node array per cell and pads it so.
``flat_connectivity`` stacks the blocks into one table, padded with ``-1`` to the widest. ``is_structured`` is true when ``structured_shape`` is set. The plot then
uses ``pcolormesh``. ``SolverMesh.to_dis_kwargs()`` writes the DIS grid of MODFLOW-NWT only for a
cell mesh with a ``structured_shape``. ``with_cell_data`` and ``with_point_data`` return a new
instance because the class is frozen.

Plot, disk and solver adapters
------------------------------

``plot_cell_values`` in ``model/properties/plotting.py`` draws a ``PlanarCellMesh`` or a
``HydroMesh``. It uses ``pcolormesh`` for quadrilaterals with a ``structured_shape``,
``tripcolor`` for triangles and ``PolyCollection`` otherwise. VTU is the
recommended disk format. It describes itself, opens in ParaView, PyVista and QGIS, and
round-trips through ``HydroMesh``. The exchange formats live in ``spatial/mesh/io/``, one module
per format, and depend on the mesh model only. ``write_vtu`` and ``read_vtu`` in ``io/vtu.py``
write and read a ``HydroMesh`` in 2D or 3D. A planar mesh is written with a zero z and reads back
planar. ``write_vtu`` also writes values of the whole mesh, such as the CRS of a run, in the
``FieldData`` of the grid, a text as its UTF-8 bytes and a number as ``Int32``, and
``read_vtu_field_data`` reads them back. ``hmp export`` writes its VTU files through this module,
the cells in the order of the run store. ``to_meshio`` and ``from_meshio`` in ``io/meshio_bridge.py`` pass a ``HydroMesh`` through
meshio, mixed and 3D cells included. A polygon block (a Voronoi mesh) goes to meshio as its
runs of consecutive cells of one node count, so the cell order is kept, and comes back as one block.
``read_msh`` and ``write_msh`` in ``io/msh.py`` read a ``.msh`` file into a ``HydroMesh`` and write
a planar one back. Under them, ``read_gmsh_2d_mesh`` reads the file through meshio, or through a
small reader of the ASCII 2.2 format when meshio fails, into ``GmshMeshData``, with the lines of
the named physical groups in ``line_groups``. A ``.msh`` file carries no CRS, so
``write_gmsh_2d_mesh`` given a ``crs`` writes its WKT to ``<name>.prj`` next to the mesh, and
``read_gmsh_2d_mesh`` reads it back into ``crs_wkt``.
``to_flopy_disv_args(hydro_mesh, top=..., botm=..., centers=...)`` in ``solver/modflow_grid/solver_mesh.py``
returns the arguments of a MODFLOW 6 DISV package (``nvert``, ``vertices``, ``ncpl``, ``cell2d``,
``top``, ``botm``). The core needs only numpy and the plot needs matplotlib. A run stores its
cell mesh in Zarr and exports it as a GeoPackage, see :doc:`../storage-layout`.

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
     - The one cell center rule, shape ``(n_cells, 2)``. ``center_kind`` is ``generator``
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
     - ``MeshQA``: quantiles of area, size, center offset, non-orthogonality and cell shape,
       then the concave cells, the degenerate faces, the family coverage and the engine
       declarations (``graded``, ``exact_faces``, ``deterministic``, ``needs_cache``).
       ``quality_warnings`` turns the shape entries into build warnings and never refuses a mesh.
   * - ``structured_shape``
     - ``(nrow, ncol)`` of a regular grid, otherwise ``None``.
   * - ``smoothed_catchment``
     - The catchment outline the planner smoothed and the mesh followed, otherwise ``None``.
       The planner gives it by ``smoothed_catchment(mesh_cfg, inputs)``, and
       ``PlanningInputs.outlet`` keeps the declared outlet on it.

``cell_mesh.geometry`` is a ``DerivedGeometry`` (``spatial/mesh/model/geometry.py``),
derived once on first use. It holds the ``-1`` padded connectivity (the format of the Zarr
store), the areas and area centroids, the edge table (``edge_nodes``, ``edge_cells``, length and
midpoint) and the CSR adjacency of the interior edges. An edge shared by more than two cells
raises ``ValueError``. ``cell_mesh.connectivity_rows`` returns the cells as one array. It is the
block itself for triangles and quadrilaterals, and the padded rows as 32-bit ids for polygons.
The cell centers are ``cell_mesh.centers``, the generators of a Voronoi mesh: a ``HydroMesh``
carries none, and its ``cell_centroids()`` gives the mean of the cell vertices.
``mesh_cells`` in ``model/properties/mesh_cells.py`` reads these rows without their ``-1``
slots, for a support that samples a field on the cells.

``cell_mesh_from_bundle`` in ``spatial/mesh/io/bundle.py`` reads a Boussinesq validation bundle,
a folder of CSV files, which ``load_catchment_mesh_bundle`` of the same module loads whole. The
format is versioned. ``metadata.json`` declares ``mesh_catchment_bundle_v1``, the value of
``BUNDLE_SCHEMA_VERSION``, and ``BUNDLE_COLUMNS`` gives the columns of each file, both in
``io/bundle.py``.

Line families
~~~~~~~~~~~~~

A family is a set of lines that the mesh honors, under one name. Its intent decides what the
cell mesh keeps.

- A cell family (``rivers``) runs through the cells. ``cell_chains`` holds one chain of cells per
  line, from upstream to downstream. ``CellChain.offset_m`` gives the distance from each cell
  center to the line. The ``voronoi`` engine fills it, and it is ``None`` where the cell holds the
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
   * - Centers, areas, adjacency
     - ``SolverMesh.cell_centers()``, ``cell_areas()`` and ``face_adjacency()``, read from
       ``cell_mesh.geometry``.
   * - Cells of a side, of the river, of a label
     - ``side_cells``, ``stream_cells``, ``label_cells`` in ``spatial/mesh/cells/boundary.py``.
   * - Cell that holds a point
     - ``locate_cells`` in ``spatial/mesh/cells/locate.py``. For a point outside the mesh,
       ``locate_cells_near`` gives the nearest cell only within one cell size (the square root
       of its area), and otherwise gives no cell and warns. The solvers call
       ``locate_cell_on_solver_mesh`` in ``solver/base/cell_lookup.py``, which uses the top active
       layer of the column.
   * - Forcing grids and stations on the cells
     - ``discretize_fields_on_cells`` and ``discretize_points_on_cells`` in
       ``model/forcing/cells.py``. The method ``area`` (``area_weights.py``) clips each cell by
       the pixels its box reaches and needs the planar mesh.
   * - Zone fractions of a cell
     - ``zone_fractions`` in ``model/properties/zone_fractions.py``. It uses the zone the engine
       gave the cell when the faces lie on the contacts, else the polygon areas of a vector
       geology source, else the sampling of the support.
   * - K, Sy and Ss on the cells
     - ``map_flow_properties`` in ``model/properties/property_table.py``, for MODFLOW 6,
       MODFLOW-NWT and Boussinesq.
   * - HFB, lake and SFR cells
     - ``spatial/mesh/cells/barrier_faces.py`` gives the faces a barrier line bars. The MODFLOW 6
       builders give the cells a lake owns and the faces of its cutoff wall
       (``solver/modflow6/builders/_lake_geometry.py``), and share a reach among the cells
       (``_sfr_network.py``).
   * - The catchment of the run
     - The basin of the descent D, computed once per build and stored with the mesh
       (``mesh/descent_basin``), and the share of each cell inside the delineated polygon
       (``mesh/catchment_fraction``, ``cell_area_fraction`` in
       ``spatial/mesh/cells/in_polygons.py``), see :doc:`../storage-layout`.

Every engine gives a river as cell chains. A triangle mesh also keeps the faces of the river
line as face rows.

Module layout
-------------

.. code-block:: text

   hydromodpy/spatial/mesh/
   |-- mesh_config.py       the [mesh] models
   |-- refinement_config.py the models of [mesh.lake_refinement] and [[mesh.refinement_zone]]
   |-- model/               the mesh classes, DerivedGeometry, MeshQA, RegularGrid (regular_grid.py)
   |-- port.py              MeshEngine, MeshEngineCapabilities
   |-- registry.py          engine id to class, entry-point group hydromodpy.mesh.engine
   |-- request.py           MeshRequest, LineFamilySpec, RasterGridSpec, SizeField
   |-- resample.py          the lines resampled at the local cell size, read by the engines
   |-- cache.py             meshes an engine cannot rebuild bit for bit
   |-- engines/             regular/, triangle/, voronoi/, and face_families.py, the face
   |                        family rows they share
   |-- planning/            plan_mesh_request, the line families (families.py) and the size
   |                        terms (size_terms.py), catchment_outline.py, geometry_cleanup.py,
   |                        geology_contacts.py, input_triangulation.py, the size field
   |                        (size_field.py, gap_size.py), the refinement zones
   |                        (refinement_zones.py, height_above_stream.py) and the lake
   |                        structures (lake_structures.py)
   |-- cells/               which cells or faces: sides, regions, barriers, polygons, zones
   `-- io/                  exchange formats: vtu.py, meshio_bridge.py, msh.py, bundle.py

The vertical layers live outside this folder, in ``model/domain/layers_config.py`` and
``layering.py``. So do the grids and stations put on the cells, in ``model/forcing/``, which
reads the mesh model and is never imported by the mesh. The ``sgrid`` table of the MODFLOW
backends (``sgrid_config.py``) and the vertical part of a regular grid
(``StructuredGridBuilder`` in ``discretization_spatial.py``) live in ``solver/modflow_grid/``.
The field package samples its supports on the cells of a ``PlanarCellMesh`` and draws one value
per cell with ``plot_cell_values`` (``model/properties/plotting.py``). It reads the mesh, and the
mesh never imports it.

What the solvers read
---------------------

A solver reads the ``SolverMesh`` of ``hydromodpy/solver/modflow_grid/solver_mesh.py``. It is
built from the cell mesh and the vertical layers of ``[domain.layers]``, which both MODFLOW
backends read. ``layer_stack`` in ``model/domain/layering.py`` turns shares or surfaces into
the layer bottoms and the integer ``idomain`` (1, 0 or -1). ``discretization_spatial.py``, next
to ``solver_mesh.py``, samples the base rasters on the cell centers or resamples them to a
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
it cannot be the pivot. meshio is the I/O dependency. Its ``meshio.Mesh`` is mutable and
supports about thirty cell types, most of them useless here. ``HydroMesh`` is a strict, frozen
subset of that model, with round trips through the adapters.

See also
--------

- :doc:`mesh-engines` for the port, the planner and the three engines.
- :doc:`voronoi-engine` and :doc:`triangle-engine` for the two engines that use a size field.
- :doc:`index` for the mesh section.
- :doc:`../storage-layout` for the mesh in the Zarr store and its Parquet tables.
- :doc:`../solver/backends` for the DIS and BAS contracts that consume the regular grid.
