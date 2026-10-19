The mesh pivot and the cell mesh
================================

HydroModPy manipulates several 2D and 3D mesh types to discretize hydrogeological
parameters (conductivity, storage, recharge) and to pass them to the solvers.
``HydroMesh`` is the one exchange format between them, and ``PlanarCellMesh`` is the planar
mesh every solver and every workflow step reads. This page covers the mesh classes, the
pivot, the cell mesh with its families, and their place in the solver pipeline. Code:
``hydromodpy/spatial/field/`` (the mesh classes of the field layer) and
``hydromodpy/spatial/mesh/`` (the pivot, the cell mesh, the engines and the adapters). How a
cell mesh is built is on :doc:`mesh-engines`, and the grid the MODFLOW family reads is on
:doc:`../solver/backends`.

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

Every ``BaseFieldMesh`` exposes the node coordinates (``x_plot``, ``y_plot``), ``shape``,
``n_nodes`` and ``n_cells``, the cells as ``MeshCell`` objects (``cells``,
``iter_cells()``), ``cell_centroids()``, ``to_cell_values(values)``,
``plot_cell_values(ax, values)`` and ``to_hydro_mesh()``. A ``MeshWithValues`` pairs a mesh
with one value per cell. It is the return type of ``FieldParam.to_mesh_field()``.

A square test mesh, from ``hydromodpy/spatial/field/cases/square/field_mesh_square.py``:

.. code-block:: python

   from hydromodpy.spatial.field.cases.square.field_mesh_square import FieldMeshSquare

   mesh = FieldMeshSquare.from_unit_square(target_n_cells=400, mesh_kind="structured")
   mesh.n_cells      # 400
   mesh.shape        # (21, 21) nodes

``mesh_kind`` is ``"structured"``, ``"triangular_structured"`` or
``"triangular_unstructured"``. A Gmsh mesh is read with
``GmshPlanarMesh2D.from_file("domain.msh")``.

Placing a parameter on a mesh
-----------------------------

Three objects discretize a parameter:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Object
     - Role
   * - ``Field``
     - The spatial geometry that defines zones (``spatial/field/core/field_spatial.py``).
   * - ``FieldParam``
     - The parameter: a scalar or one value per zone, with a unit and an optional
       vertical profile (``spatial/field/core/field_param.py``).
   * - ``BaseFieldMesh``
     - The cells on which to discretize.

A homogeneous parameter gives one value per cell:

.. code-block:: python

   from hydromodpy.spatial.field.core.field_param import FieldParam

   K = FieldParam(identifier="K", kind="homogeneous", unit="m/s", value=1e-4)
   result = K.to_mesh_field(mesh=mesh)     # MeshWithValues, every cell 1e-4

A heterogeneous parameter takes the zone-weighted mean in each cell: the mesh gets the
fraction of every zone from a ``Field`` (``field.on_mesh(mesh, ...)``), and the parameter
(``kind="heterogeneous"``, ``values_by_key``, ``field_spatial_id``) is discretized with
that distribution. A vertical profile (``mode`` of ``none``, ``exponential`` or
``tabulated``) multiplies the value by a factor that depends on depth;
``FieldParam.vertical_factor(depth)`` returns it. Values are stored in SI units whatever
the input unit. The solvers do not go through ``BaseFieldMesh``: they map the parameters on the
cells of the cell mesh, see :ref:`consumers-read-the-cell-mesh`. The field layer is described
in :doc:`../field/index`.

The pivot
---------

``HydroMesh`` (``spatial/mesh/model/hydro_mesh.py``) is a frozen dataclass that represents any
2D or 3D mesh the same way, in the data model of meshio: vertices, cell blocks, per-cell
and per-node data.

.. code-block:: python

   from hydromodpy.spatial.mesh import HydroMesh, CellBlock, CellType

   mesh = HydroMesh(
       vertices=points_xy,                                  # (n_nodes, 2 or 3)
       cell_blocks=(CellBlock(CellType.TRIANGLE, conn),),   # connectivity
       cell_data={"K": conductivity},                       # one value per cell
       structured_shape=None,                               # (nrow, ncol) for a regular grid
   )

Before it, each mesh type had its own data model and plotting code, and generic code
could not be written without coupling to a concrete type. Now every type converts to the
pivot, and the pivot serves the plot, the disk formats and the solver adapters:

.. code-block:: text

   StructuredFieldMesh ---+                  +-- plot_cell_values()
   TriangularFieldMesh ---+                  +-- write_vtu() / read_vtu()
   PolygonFieldMesh ------+-- to_hydro_mesh -+-- to_flopy_disv_args()
   GmshPlanarMesh2D ------+                  +-- to_meshio()

The mesh engines build a ``HydroMesh`` directly, inside the cell mesh described below.

The cell types are ``TRIANGLE``, ``QUADRILATERAL``, ``POLYGON`` (ragged cells, such as the
cells of the ``voronoi`` engine), ``WEDGE`` and ``HEXAHEDRON`` (``CellType``, with string
aliases such as ``"tri"`` and ``"triangular_prism"``). A ``POLYGON`` block stores its
connectivity as a tuple of rows of different lengths.
``is_structured`` is true when ``structured_shape`` is set. That hint lets the plot use
``pcolormesh`` and lets an export use DIS instead of DISV. ``with_cell_data(**fields)``
and ``with_point_data(**fields)`` return a new instance, because the class is frozen.

The existing classes stay in place. Each keeps its own logic (generation, validation,
association with a ``FieldParam``) and produces or consumes a ``HydroMesh`` through
``to_hydro_mesh()``. New code takes a ``HydroMesh`` as input and output and does not
depend on a concrete class.

Plot, disk and solver adapters
------------------------------

**Plot.** ``plot_cell_values(ax, hydro_mesh, values, cmap=..., show_mesh=...)`` in
``spatial/mesh/plotting.py`` picks the renderer from the topology: ``pcolormesh`` for a
structured quadrilateral mesh, ``tripcolor`` for triangles, ``PolyCollection`` otherwise.
The ``plot_cell_values`` methods of the mesh classes delegate to it.

**Disk.** VTU is the recommended format: it is self-describing, opens in ParaView,
PyVista and QGIS, and round-trips through ``HydroMesh``. Use ``write_vtu`` and
``read_vtu`` from ``spatial/mesh/io``, or the public functions of
``spatial/mesh/gmsh_grid/exchange_api.py`` (``load_planar_as_hydro_mesh``,
``save_hydro_mesh_vtu``, ``load_hydro_mesh_vtu``).
``to_meshio`` and ``from_meshio`` in ``spatial/mesh/adapters`` convert to and from
``meshio``, an optional dependency imported on demand. A run stores its cell mesh in the
Zarr store and exports it as a GeoPackage, see :doc:`../storage-layout`.

**FloPy.** ``to_flopy_disv_args(hydro_mesh, top=..., botm=...)`` returns the keyword
arguments of a MODFLOW 6 DISV package (``nvert``, ``vertices``, ``ncpl``, ``cell2d``,
``top``, ``botm``).

Dependencies stay light: the core (``model/cell_types.py``, ``model/hydro_mesh.py``)
needs only numpy, the plot needs matplotlib, and the adapters import meshio and flopy
only when called.

Cell mesh
---------

``PlanarCellMesh`` (``spatial/mesh/model/planar_cell_mesh.py``) is the mesh the solvers and
the workflow steps read, as ``setup.cell_mesh``. It wraps one planar ``HydroMesh`` block of
triangles, quadrilaterals or polygons, unchanged, and holds what every consumer would
otherwise recompute:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Attribute
     - Content
   * - ``centers``, ``center_kind``
     - The one cell centre rule, ``(n_cells, 2)``: ``generator`` (Voronoi), ``cell_center``
       (regular grid) or ``vertex_mean`` (triangles).
   * - ``crs_wkt``
     - The CRS of the vertices, as WKT. It is required.
   * - ``face_families``, ``cell_chains``
     - The face rows and the cell chains of the line families, see below.
   * - ``cell_zone``, ``zone_names``
     - The zone index of each cell, ``-1`` when unknown, and the sorted zone names.
   * - ``identity``
     - ``MeshIdentity``: engine id, engine version, request hash and seed.
   * - ``qa``
     - ``MeshQA``: area, size, centre offset and non-orthogonality quantiles, degenerate
       faces, family coverage, and the engine declarations (``graded``, ``exact_faces``,
       ``deterministic``, ``needs_cache``).
   * - ``structured_shape``
     - ``(nrow, ncol)`` of a regular grid, otherwise ``None``.

``cell_mesh.geometry`` is a ``DerivedGeometry`` (``spatial/mesh/model/derived_geometry.py``),
derived once on first use with vectorised numpy. It holds the ``-1`` padded connectivity
(the format of the Zarr store), the areas and area centroids, the edge table keyed by
vertex ids (``edge_nodes``, ``edge_cells``, length and midpoint) and the CSR adjacency of
the interior edges. An edge shared by more than two cells raises ``ValueError``.
``cell_mesh.connectivity_rows`` returns the cells as one array: the block itself for
triangles and quadrilaterals, the padded rows for polygons.

An engine builds a cell mesh from a request (:doc:`mesh-engines`). A Boussinesq validation
bundle, a folder of CSV files, is read into one by ``cell_mesh_from_bundle`` in
``spatial/mesh/gmsh_grid/bundle_cell_mesh.py``. A consumer that samples a field on the cells
calls ``to_field_mesh(cell_mesh.mesh)`` in ``adapters/field_mesh_adapter.py``.

Line families
~~~~~~~~~~~~~

A family is a set of lines the mesh honours, under one name. It has one of two intents, and
the cell mesh keeps what each intent needs:

- **Cell family** (``rivers``). The line runs through the cells. ``cell_chains`` holds one
  ordered chain of cells per line, upstream to downstream, and ``CellChain.offset_m`` the
  distance from each chain cell centre to the line. It is optional: the ``voronoi`` engine
  publishes it, and it is ``None`` where the cell holds the line.
- **Face family** (``geology``, ``lakes``, ``barriers``, ``watershed_boundary``). The line
  lies on cell faces. ``face_families`` has one row per mesh edge on a line: the two cells
  (``-1`` outside the domain), the two vertices, and the zone on each side. An edge on the
  lines of two families (a cutoff wall along a lake shore) has a row in each. The four sides
  of the domain are face families named ``boundary:<side>``.

An engine says in its capabilities how it forms each kind (``cell_families``): exactly, by
rasterizing the line, or from the faces. The quality report states how far the cells and
faces are from the source lines. The intent of each family comes from ``[mesh.families]``.

.. _consumers-read-the-cell-mesh:

Consumers read the cell mesh
----------------------------

Every solver reads the cell mesh, never a producer's own support. One function serves
every engine for each question a consumer asks:

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
     - ``locate_cells`` in ``spatial/mesh/ops/cell_location.py``.
   * - Forcing grids and stations on the cells
     - ``discretize_fields_on_cells`` and ``discretize_points_on_cells`` in
       ``spatial/mesh/forcing/``.
   * - Zone fractions of a cell
     - ``zone_fractions`` in ``spatial/field/zone_fractions.py``: the zone the engine gave the
       cell when its faces lie on the contacts, else the exact polygon areas of a vector
       geology source, else the sampling of the support.
   * - K, Sy and Ss on the cells
     - ``map_flow_properties`` in ``solver/field_property_mapping.py``, for MODFLOW 6,
       MODFLOW-NWT and Boussinesq.
   * - HFB, lake and SFR cells
     - ``spatial/mesh/ops/flow_barrier.py``, ``family_interior.py`` and ``line_on_chain.py``.
   * - The catchment of the run
     - The basin of the descent D, computed once per build and stored with the mesh
       (``mesh/descent_basin``), see :doc:`../storage-layout`.

A river is read from its cell chains on every engine. A triangle mesh keeps the faces of the
river line as face rows too.

Module layout
-------------

.. code-block:: text

   hydromodpy/spatial/mesh/
   |-- __init__.py          CellType, CellBlock, HydroMesh, PlanarCellMesh
   |-- model/               cell_types.py, hydro_mesh.py, grid_wrappers.py (RegularGrid),
   |                        planar_cell_mesh.py, derived_geometry.py, mesh_qa.py
   |-- port.py              MeshEngine, MeshEngineCapabilities
   |-- registry.py          engine id -> engine class, entry-point group hydromodpy.mesh.engine
   |-- request.py           MeshRequest, LineFamilySpec, RasterGridSpec, SizeField
   |-- cache.py             the meshes an engine cannot rebuild bit for bit
   |-- engines/             regular/, triangle/, voronoi/
   |-- planning/            plan_mesh_request: the project to a request
   |-- sizing/              the size field of the graded engines
   |-- refinement/          the models of [[mesh.refinement_zone]] and [mesh.lake_refinement]
   |-- config/              the [mesh] models
   |-- forcing/             grids and stations sampled on the cell centres
   |-- ops/                 the shared cell helpers (families, location, chains, voronoi)
   |-- adapters/            meshio_adapter.py, field_mesh_adapter.py, flopy_adapter.py,
   |                        cell_mesh.py
   |-- io/                  vtu_io.py
   |-- plotting.py          plot_cell_values
   |-- cartesian_grid/      the vertical layers of the grid (sgrid_generation.py), the keys of
   |                        the layers and of the top sampling (sgrid_config.py) and the
   |                        interpolation of values onto cell centres (spatial_interpolation.py)
   `-- gmsh_grid/           the reader of a .msh and GmshPlanarMesh2D, the reader of a
                            Boussinesq validation bundle, exchange_api.py

What the solvers read
---------------------

The mesh a solver reads is not the pivot itself but the ``SolverMesh`` of
``hydromodpy/solver/modflow_grid/solver_mesh.py``, built from the cell mesh and the
vertical layers.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Backend
     - Mesh it reads
   * - MODFLOW 6
     - DISV for every engine. A regular grid is written as DISV too, through
       ``SolverMesh.to_disv_kwargs()``, which calls ``to_flopy_disv_args``.
   * - MODFLOW-NWT
     - A DIS grid, which only the ``regular`` engine gives.
   * - Boussinesq
     - The triangles of the cell mesh. The validation cases give it a bundle, which
       ``cell_mesh_from_bundle`` turns into a cell mesh.

Each flow adapter declares the engines it reads in ``accepted_meshes``, see
:doc:`mesh-engines`. Parameter discretization (``FieldParam``) works on every mesh type, and
so do the plot and the VTU I/O.

Design choices
--------------

**Why not xugrid or UGRID NetCDF as the pivot?** xugrid handles 2D and layered
pseudo-3D (UGRID2D), but not fully 3D unstructured meshes. UGRID NetCDF stays relevant
as an output format for per-cell time series. As an internal pivot, vertices and
connectivity are simpler, more general and free of dependencies.

**Why not meshio directly?** meshio is an optional I/O dependency and not a pivot
type. ``meshio.Mesh`` is mutable, supports about thirty cell types, most of them
useless here, and stores ``cell_data`` as lists of lists per block. ``HydroMesh`` is a
strict, normalised subset of its model with round trips through the adapters.

**Why a frozen dataclass?** A mesh that cannot change after construction makes the data
flow easier to reason about and removes a class of accidental mutation.

See also
--------

- :doc:`mesh-engines` for the port, the planner and the three engines.
- :doc:`voronoi-engine` and :doc:`triangle-engine` for the two engines that mesh the catchment
  under a size field.
- :doc:`index` for the mesh section.
- :doc:`../storage-layout` for the mesh in the Zarr store and its Parquet tables.
- :doc:`../solver/backends` for the DIS and BAS contracts that consume the regular grid.
