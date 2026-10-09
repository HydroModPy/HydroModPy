The HydroMesh pivot
===================

HydroModPy manipulates several 2D and 3D mesh types to discretize hydrogeological
parameters (conductivity, storage, recharge) and to pass them to the solvers.
``HydroMesh`` is the one exchange format between them. This page covers the mesh
classes, the pivot, its conversions and its place in the solver pipeline. Code:
``hydromodpy/spatial/field/`` (the mesh classes of the field layer) and
``hydromodpy/spatial/mesh/`` (the pivot, the Gmsh integration and the adapters). For the
Gmsh pipeline, see :doc:`gmsh-meshing`, and for the grid the MODFLOW family reads,
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

   ExtrudedPrismMesh3D                  spatial/mesh/gmsh_grid/extruded_prism_mesh.py
         prisms, by vertical extrusion of a GmshPlanarMesh2D

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
``GmshPlanarMesh2D.from_file("domain.msh")``, and a 3D mesh is built from it with
``ExtrudedPrismMesh3D.from_planar_mesh(planar, z_interfaces=[...])`` or
``ExtrudedPrismMesh3D.from_layer_thicknesses(planar, top_z=..., layer_thicknesses=[...])``.

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
the input unit. The MODFLOW and Gmsh paths have their own entry points:
``discretize_fieldparam_on_sgrid`` in
``spatial/mesh/cartesian_grid/sgrid_fieldparam_discretization.py`` returns the 3D values of
a structured grid, and ``discretize_fieldparam_on_extruded_mesh`` in
``spatial/mesh/gmsh_grid/extruded_fieldparam_discretization.py`` does the same on an
extruded mesh. The field layer is described in :doc:`../field/index`.

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
   GmshPlanarMesh2D ------+-- to_hydro_mesh -+-- to_flopy_disv_args()
   ExtrudedPrismMesh3D ---+                  +-- to_meshio()
   FloPy StructuredGrid --+

The cell types are ``TRIANGLE``, ``QUADRILATERAL``, ``WEDGE`` and ``HEXAHEDRON``
(``CellType``, with string aliases such as ``"tri"`` and ``"triangular_prism"``).
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
``load_extruded_as_hydro_mesh``, ``save_hydro_mesh_vtu``, ``load_hydro_mesh_vtu``).
``to_meshio`` and ``from_meshio`` in ``spatial/mesh/adapters`` convert to and from
``meshio``, an optional dependency imported on demand.

**FloPy.** ``from_flopy_structured(modelgrid)`` reads a FloPy structured grid into a
``HydroMesh``. ``to_flopy_disv_args(hydro_mesh, top=..., botm=...)`` returns the keyword
arguments of a MODFLOW 6 DISV package (``nvert``, ``vertices``, ``ncpl``, ``cell2d``,
``top``, ``botm``).

Dependencies stay light: the core (``model/cell_types.py``, ``model/hydro_mesh.py``)
needs only numpy, the plot needs matplotlib, and the adapters import meshio and flopy
only when called.

Module layout
-------------

.. code-block:: text

   hydromodpy/spatial/mesh/
   |-- __init__.py          CellType, CellBlock, HydroMesh
   |-- model/               cell_types.py, hydro_mesh.py, grid_wrappers.py, protocol.py
   |-- plotting.py          plot_cell_values
   |-- adapters/            meshio_adapter.py, field_mesh_adapter.py, flopy_adapter.py
   |-- io/                  vtu_io.py
   |-- cartesian_grid/      the structured grid path
   |-- gmsh_grid/           the Gmsh path: planar, extruded, bundles, exchange API
   |-- launcher/            the runtime mesh launcher, single and batch
   `-- config/              the [mesh_catchment] and [mesh_input] models

What the solvers read
---------------------

The mesh a solver reads is not the pivot itself but the ``SolverMesh`` of
``hydromodpy/solver/modflow_grid/solver_mesh.py``, built from the planar mesh and the
vertical layers.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Backend
     - Mesh it reads
   * - MODFLOW 6
     - DISV for every grid. A structured grid is written as DISV too, through
       ``SolverMesh.to_disv_kwargs()``, which calls ``to_flopy_disv_args``. A runtime
       Gmsh mesh uses the same path.
   * - MODFLOW-NWT
     - A structured grid (DIS) only. It does not consume a runtime Gmsh mesh.
   * - Boussinesq
     - Triangular meshes from a Gmsh catchment bundle.

Parameter discretization (``FieldParam``) works on every mesh type, and so do the plot
and the VTU I/O.

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

- :doc:`gmsh-meshing` for the conformal Gmsh pipeline.
- :doc:`index` for the mesh section.
- :doc:`../solver/backends` for the DIS and BAS contracts that consume the structured
  grid.
