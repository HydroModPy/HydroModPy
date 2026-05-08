Mesh Architecture Pivot
=======================

Links:
:doc:`gmsh_conformal_meshing <gmsh_meshing>`,
:doc:`modflow_contracts <modflow_contracts>`.

Code: ``hydromodpy/spatial/field/`` (mesh core) and
``hydromodpy/spatial/mesh/`` (Gmsh integration toward solvers).

1. Overview
-----------

HydroModPy manipulates several 2D and 3D mesh types to discretize
hydrogeological parameters (conductivity, storage, recharge) and pass
them to the solvers (MODFLOW-NWT, MODFLOW 6, Boussinesq).

This page covers:

- the mesh class hierarchy (``BaseFieldMesh`` and subclasses);
- the ``HydroMesh`` pivot format that unifies every type;
- how variables are placed on a mesh (``FieldParam``,
  ``FieldSpatial``);
- 3D extrusion and vertical profiles;
- unified plotting, disk I/O (VTU), and FloPy adapters;
- the forcing pipeline (recharge, climate variables);
- current limitations and the scope of the pivot.

2. Mesh types
-------------

2.1 Class hierarchy
~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   BaseFieldMesh (ABC)                      # hydromodpy/spatial/field/core/field_mesh.py
   ├── StructuredFieldMesh                  # hydromodpy/spatial/field/meshes/structured_field_mesh.py
   │     _kind = "structured"               # Quadrilaterals on a regular grid
   ├── TriangularStructuredFieldMesh        # hydromodpy/spatial/field/meshes/triangular_field_mesh.py
   │     _kind = "triangular_structured"    # Triangles on a regular grid
   ├── TriangularUnstructuredFieldMesh      # hydromodpy/spatial/field/meshes/triangular_field_mesh.py
   │     _kind = "triangular_unstructured"  # Random Delaunay triangles
   ├── GeologyStructuredMesh                # hydromodpy/spatial/field/geology/geology_mesh.py
   │     _kind = "structured_rect"          # Quadrilaterals in real coordinates
   └── GmshPlanarMesh2D                     # hydromodpy/spatial/mesh/gmsh_grid/gmsh_planar_mesh.py
         _kind = "gmsh_2d"                  # Triangles or quads from a .msh file

   ExtrudedPrismMesh3D                      # hydromodpy/spatial/mesh/gmsh_grid/extruded_prism_mesh.py
         # 3D prisms by vertical extrusion of a GmshPlanarMesh2D

2.2 Common contract (``BaseFieldMesh``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every subclass implements:

.. list-table::
   :header-rows: 1

   * - Property / Method
     - Description
   * - ``x_plot``, ``y_plot``
     - Node coordinates (1D or 2D arrays)
   * - ``shape``
     - Node-array shape ``(ny, nx)`` or ``(n_nodes,)``
   * - ``n_nodes``
     - Total number of nodes
   * - ``n_cells``
     - Total number of cells
   * - ``cells``
     - Tuple of ``MeshCell`` (explicit per-cell geometry)
   * - ``iter_cells()``
     - ``MeshCell`` generator
   * - ``cell_centroids()``
     - Cell-centroid coordinates
   * - ``to_cell_values(values)``
     - Normalize a raw array to one value per cell
   * - ``plot_cell_values(ax, values, ...)``
     - Matplotlib visualisation
   * - ``to_hydro_mesh()``
     - Conversion to the ``HydroMesh`` pivot format
   * - ``attach_cell_values(values, label)``
     - Returns a ``MeshWithValues``

2.3 ``MeshCell``: a single cell
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   @dataclass(frozen=True)
   class MeshCell:
       index: int                        # Global index in the mesh
       kind: str                         # "triangle", "quadrilateral"
       node_indices: tuple[int, ...]     # Node indices
       vertices: np.ndarray              # Coordinates (n_nodes_per_cell, 2)
       centroid: tuple[float, float]     # Cell centroid

2.4 ``MeshWithValues``: mesh plus data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   @dataclass(frozen=True)
   class MeshWithValues:
       mesh: BaseFieldMesh
       cell_values: np.ndarray    # one value per cell
       label: str | None = None

This is the return type of ``FieldParam.to_mesh_field()``: the result
of discretizing a parameter on a mesh.

3. Building a mesh
------------------

3.1 Structured grid (unit square)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from hydromodpy.spatial.field.cases.square.field_mesh_square import FieldMeshSquare

   # 20x20 = 400 quadrilateral cells
   mesh = FieldMeshSquare.from_unit_square(
       target_n_cells=400,
       mesh_kind="structured",    # "structured" | "triangular_structured" | "triangular_unstructured"
       seed=42,
   )
   # mesh.kind == "structured"
   # mesh.n_cells == 400
   # mesh.shape == (21, 21)  # nodes

3.2 Structured triangular grid
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   mesh = FieldMeshSquare.from_unit_square(
       target_n_cells=400,
       mesh_kind="triangular_structured",
   )
   # mesh.kind == "triangular_structured"
   # mesh.n_cells == 800  # ~2x more cells (each quad -> 2 triangles)

3.3 Unstructured Delaunay grid
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   mesh = FieldMeshSquare.from_unit_square(
       target_n_cells=400,
       mesh_kind="triangular_unstructured",
       seed=42,  # reproducibility of random points
   )

3.4 Gmsh mesh from ``.msh``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D

   planar = GmshPlanarMesh2D.from_file("domain.msh")
   # planar.points_xy -> ndarray (n_nodes, 2)
   # planar.connectivity -> ndarray (n_cells, 3) or (n_cells, 4)
   # planar.cell_type -> "triangle" or "quadrilateral"

3.5 Geology mesh in real coordinates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from hydromodpy.spatial.field.geology import GeologyStructuredMesh

   mesh = GeologyStructuredMesh.from_bounds(
       [xmin, ymin, xmax, ymax],
       target_n_cells=400,
   )
   # mesh.kind == "structured_rect"

3.6 Extruded 3D mesh (prisms)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from hydromodpy.spatial.mesh.gmsh_grid.extruded_prism_mesh import ExtrudedPrismMesh3D

   mesh_3d = ExtrudedPrismMesh3D.from_planar_mesh(
       planar,
       z_interfaces=[0.0, -5.0, -15.0, -50.0],  # 3 layers
   )
   # mesh_3d.n_layers == 3
   # mesh_3d.n_prisms == n_cells_2d * n_layers
   # mesh_3d.cell_type_3d -> "triangular_prism" or "quadrilateral_prism"

Alternative with thicknesses:

.. code-block:: python

   mesh_3d = ExtrudedPrismMesh3D.from_layer_thicknesses(
       planar,
       top_z=100.0,
       layer_thicknesses=[5.0, 10.0, 35.0],
   )

3.7 From TOML configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   mesh = FieldMeshSquare.from_toml("config.toml", section="mesh")

with a TOML containing:

.. code-block:: toml

   [mesh]
   target_n_cells = 400
   mesh_kind = "structured"
   seed = 42

4. Placing variables on a mesh
------------------------------

The discretization pipeline uses three objects:

.. list-table::
   :header-rows: 1

   * - Object
     - Role
   * - ``Field`` (or ``FieldSpatial``)
     - Spatial geometry: defines zones (for example granite vs
       micaschists)
   * - ``FieldParam``
     - Parameter value: scalar or per-zone, with unit and vertical
       profile
   * - ``BaseFieldMesh``
     - Geometric support: cells on which to discretize

4.1 Homogeneous case (single value)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from hydromodpy.spatial.field.core.field_param import FieldParam

   K = FieldParam(
       identifier="K",
       kind="homogeneous",
       unit="m/s",
       value=1e-4,
   )

   # Discretize on a mesh:
   result = K.to_mesh_field(mesh=mesh)
   # result.cell_values -> ndarray, every cell = 1e-4
   # result.mesh == mesh

4.2 Heterogeneous case (several zones)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Three steps:

.. code-block:: python

   # 1) Define the spatial geometry (zones)
   from hydromodpy.spatial.field.cases.square.field_spatial_square import FieldSquare

   field = FieldSquare(
       line="diag_main",           # diag_main | diag_anti | axis_vertical | axis_horizontal
       zone1_side="positive",
       identifier="geology_field",
       zone1_name="granite",
       zone2_name="micaschists",
   )

   # 2) Project the zones on the mesh
   #    -> compute the fraction of each zone in every cell
   field_discretization = field.on_mesh(mesh, cell_samples_per_axis=10)
   # field_discretization.weighted_components() -> (zone_keys, fractions_by_zone)

   # 3) Discretize the parameter with the zone distribution
   K = FieldParam(
       identifier="K",
       kind="heterogeneous",
       unit="m/s",
       values_by_key={"granite": 1e-4, "micaschists": 1e-6},
       field_spatial_id="geology_field",
   )

   result = K.to_mesh_field(field_discretization)
   # result.cell_values -> zone-weighted average per cell
   # 100% granite cell -> 1e-4
   # 60% granite / 40% micaschists -> 0.6 * 1e-4 + 0.4 * 1e-6

4.3 Vertical profile (depth dependence)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A ``FieldParam`` can carry a multiplicative vertical profile:

.. code-block:: python

   K = FieldParam(
       identifier="K",
       kind="homogeneous",
       unit="m/s",
       value=1e-4,
       vertical_profile={
           "mode": "exponential",     # "none" | "exponential" | "tabulated"
           "decay_length": 30.0,      # K(z) = K_ref * exp(-z/30)
           "min_factor": 0.01,        # floor at 1% of K_ref
       },
   )

   # Factor at 10 m depth:
   factor = K.vertical_factor(depth=10.0)  # ~ 0.716

   # Factor at 100 m:
   factor = K.vertical_factor(depth=100.0)  # ~ 0.036

Tabulated mode:

.. code-block:: python

   vertical_profile={
       "mode": "tabulated",
       "depths": [0.0, 10.0, 50.0, 100.0],
       "factors": [1.0, 0.8, 0.3, 0.05],
   }

4.4 3D discretization on a structured grid (SGrid)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For the MODFLOW pipeline (FloPy ``StructuredGrid``):

.. code-block:: python

   from hydromodpy.spatial.mesh.cartesian_grid.sgrid_fieldparam_discretization import (
       discretize_fieldparam_on_sgrid,
   )

   result = discretize_fieldparam_on_sgrid(
       support_field=field,     # Field (spatial zones), or None if homogeneous
       field_param=K,           # FieldParam
       sgrid=model.modelgrid,   # FloPy StructuredGrid (nrow, ncol, nlay)
   )
   # result.values_3d -> (nlay, nrow, ncol): per-cell value with vertical profile
   # result.values_2d -> (nrow, ncol)      : reference surface value

4.5 3D discretization on an extruded mesh (Gmsh)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For unstructured meshes:

.. code-block:: python

   from hydromodpy.spatial.mesh.gmsh_grid.extruded_fieldparam_discretization import (
       discretize_fieldparam_on_extruded_mesh,
   )

   result = discretize_fieldparam_on_extruded_mesh(
       support_field=field,
       field_param=K,
       mesh_3d=mesh_3d,           # ExtrudedPrismMesh3D
   )
   # result.values_3d -> (n_layers, n_cells_2d)
   # result.prism_center_depths -> (n_layers, n_cells_2d)

4.6 Units
~~~~~~~~~

Values are **always stored in SI units** inside ``FieldParam``.
Conversion from the input unit happens automatically at construction:

.. list-table::
   :header-rows: 1

   * - Parameter
     - Accepted units
     - Internal storage
   * - K (conductivity)
     - m/s, m/day, cm/s, cm/day, m/min, cm/min
     - m/s
   * - Sy (specific yield)
     - dimensionless
     - dimensionless
   * - Ss (specific storage)
     - 1/m, 1/cm
     - 1/m

5. ``HydroMesh`` pivot format
-----------------------------

5.1 Principle
~~~~~~~~~~~~~

``HydroMesh`` is an **immutable data container** that represents any 2D
or 3D mesh in a uniform way:

.. code-block:: python

   from hydromodpy.spatial.mesh import HydroMesh, CellBlock, CellType

   mesh = HydroMesh(
       vertices=points_xy,                              # ndarray (n_nodes, 2|3)
       cell_blocks=(CellBlock(CellType.TRIANGLE, conn),),  # connectivity
       cell_data={"K": conductivity_array},              # per-cell scalars
       point_data={},                                    # per-node scalars
       structured_shape=(nrow, ncol),                    # optional hint
   )

5.2 Why a pivot format
~~~~~~~~~~~~~~~~~~~~~~

Before ``HydroMesh``, every mesh type had its own data model and
plotting routines. Generic code (for example a post-processing that
works on structured *and* unstructured) was impossible to write
without coupling to a concrete type.

``HydroMesh`` solves this:

.. code-block:: text

   StructuredFieldMesh ─┐
   TriangularFieldMesh ─┤                  ┌── plot_cell_values()
   GmshPlanarMesh2D ────┼── .to_hydro_mesh() ──┼── write_vtu() / read_vtu()
   ExtrudedPrismMesh3D ─┤                  ├── to_flopy_disv_args()
   FloPy StructuredGrid ┘                  └── to_meshio()

5.3 Cell types (``CellType``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   TRIANGLE        3 nodes   2D   aliases: "tri", "triangle", "triangles"
   QUADRILATERAL   4 nodes   2D   aliases: "quad", "quads", "quadrilateral"
   WEDGE           6 nodes   3D   aliases: "wedge", "triangular_prism"
   HEXAHEDRON      8 nodes   3D   aliases: "hex", "hexahedron", "quadrilateral_prism"

Useful properties:

.. code-block:: python

   CellType.TRIANGLE.nodes_per_cell  # 3
   CellType.TRIANGLE.dimension       # 2
   CellType.TRIANGLE.meshio_name     # "triangle"
   CellType.from_string("tri")       # CellType.TRIANGLE

5.4 ``HydroMesh`` properties
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Property
     - Type
     - Description
   * - ``ndim``
     - int
     - 2 or 3 (spatial dimension)
   * - ``n_nodes``
     - int
     - Number of vertices
   * - ``n_cells``
     - int
     - Total number of cells
   * - ``is_structured``
     - bool
     - ``True`` if ``structured_shape`` is set
   * - ``cell_types``
     - tuple[CellType]
     - Cell types per block
   * - ``single_cell_type``
     - CellType
     - Unique type (raises if mixed)
   * - ``flat_connectivity``
     - ndarray
     - Concatenated connectivity across blocks
   * - ``bounds()``
     - tuple
     - ``(xmin, ymin, [zmin,] xmax, ymax, [zmax])``

5.5 Immutability
~~~~~~~~~~~~~~~~

``HydroMesh`` is a frozen dataclass. To add data:

.. code-block:: python

   # Add per-cell data:
   mesh2 = mesh.with_cell_data(K=conductivity, Sy=porosity)

   # Add per-node data:
   mesh2 = mesh.with_point_data(head=head_values)

These methods return a **new instance** without mutating the original.

5.6 Conversions
~~~~~~~~~~~~~~~

All mesh classes expose ``.to_hydro_mesh()``:

.. code-block:: python

   # From any BaseFieldMesh:
   hm = structured_mesh.to_hydro_mesh()
   hm = triangular_mesh.to_hydro_mesh()

   # From GmshPlanarMesh2D (optimised override):
   hm = planar.to_hydro_mesh()

   # From ExtrudedPrismMesh3D:
   hm = mesh_3d.to_hydro_mesh()
   # -> preserves cell_data["layer_index"] and cell_data["source_cell_index"]

   # From FloPy StructuredGrid:
   from hydromodpy.spatial.mesh.adapters import from_flopy_structured
   hm = from_flopy_structured(model.modelgrid)

   # Back to GmshPlanarMesh2D:
   planar_bis = GmshPlanarMesh2D.from_hydro_mesh(hm)

5.7 The ``structured_shape`` hint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When a mesh comes from a regular grid, ``structured_shape`` keeps
``(nrow, ncol)``. This lets plotting use ``pcolormesh`` (faster than
``PolyCollection``) and exports use the DIS format instead of DISV.

.. code-block:: python

   hm = structured_mesh.to_hydro_mesh()
   hm.is_structured          # True
   hm.structured_shape       # (20, 20)

6. Unified plotting
-------------------

6.1 Single function
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from hydromodpy.spatial.mesh.plotting import plot_cell_values

   fig, ax = plt.subplots()
   mappable = plot_cell_values(ax, hydro_mesh, values, cmap="coolwarm")
   fig.colorbar(mappable)

6.2 Automatic dispatch
~~~~~~~~~~~~~~~~~~~~~~

The function picks the rendering strategy from the topology:

.. list-table::
   :header-rows: 1

   * - Condition
     - Strategy
     - Performance
   * - ``is_structured`` + QUADRILATERAL
     - ``pcolormesh``
     - Very fast
   * - TRIANGLE
     - ``tripcolor``
     - Fast
   * - Anything else (unstructured QUAD, mixed)
     - ``PolyCollection``
     - Slower

6.3 From existing classes
~~~~~~~~~~~~~~~~~~~~~~~~~

The ``plot_cell_values()`` methods on existing classes all delegate to
the unified plotter internally:

.. code-block:: python

   # These two calls produce the same result internally:
   structured_mesh.plot_cell_values(ax, values)
   plot_cell_values(ax, structured_mesh.to_hydro_mesh(), values)

   # The public interface does not change: caller code needs no edit.

Affected classes:

- ``StructuredFieldMesh.plot_cell_values()``
- ``TriangularStructuredFieldMesh.plot_cell_values()``
- ``TriangularUnstructuredFieldMesh.plot_cell_values()``
- ``GmshPlanarMesh2D.plot_cell_values()``
- ``GeologyStructuredMesh.plot_cell_values()``
- ``extruded_mesh_visualization.plot_planar_cell_values()``

7. Disk I/O
-----------

7.1 VTU format (recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

VTU (VTK Unstructured Grid XML) is the recommended serialisation
format:

.. code-block:: python

   from hydromodpy.spatial.mesh.io import write_vtu, read_vtu

   # Write:
   write_vtu("output.vtu", hydro_mesh)

   # Read:
   mesh = read_vtu("output.vtu")

VTU advantages:

- Self-describing (vertices, connectivity, cell types, data).
- Supported by ParaView, PyVista, meshio, QGIS.
- Agnostic 2D/3D and structured/unstructured.
- Round-trip guaranteed with ``HydroMesh``.

Dependency: ``meshio`` (optional, imported on demand).

7.2 Gmsh format (``.msh``)
~~~~~~~~~~~~~~~~~~~~~~~~~~

For Gmsh meshes:

.. code-block:: python

   # Read:
   planar = GmshPlanarMesh2D.from_file("domain.msh")

   # Write:
   planar.to_file("output.msh")

7.3 Public exchange API
~~~~~~~~~~~~~~~~~~~~~~~

The public API in ``hydromodpy.spatial.mesh.gmsh_grid.exchange_api``:

.. code-block:: python

   from hydromodpy.spatial.mesh.gmsh_grid.exchange_api import (
       load_planar_as_hydro_mesh,     # .msh -> HydroMesh 2D
       load_extruded_as_hydro_mesh,   # .vtu -> HydroMesh 3D
       save_hydro_mesh_vtu,           # HydroMesh -> .vtu
       load_hydro_mesh_vtu,           # .vtu -> HydroMesh
   )

7.4 meshio round-trip conversion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from hydromodpy.spatial.mesh.adapters import from_meshio, to_meshio

   # HydroMesh -> meshio.Mesh:
   meshio_mesh = to_meshio(hydro_mesh)

   # meshio.Mesh -> HydroMesh:
   hydro_mesh = from_meshio(meshio_mesh)

8. FloPy adapters
-----------------

8.1 Import from FloPy (DIS -> HydroMesh)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from hydromodpy.spatial.mesh.adapters import from_flopy_structured

   sgrid = model.modelgrid  # FloPy StructuredGrid
   hm = from_flopy_structured(sgrid)
   # hm.is_structured == True
   # hm.structured_shape == (nrow, ncol)
   # hm.single_cell_type == CellType.QUADRILATERAL

8.2 Export to MODFLOW 6 DISV
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from hydromodpy.spatial.mesh.adapters import to_flopy_disv_args

   disv_kwargs = to_flopy_disv_args(
       hydro_mesh,
       top=100.0,
       botm=botm_array,   # (nlay, ncpl)
   )
   # disv_kwargs = {nvert, vertices, ncpl, cell2d, top, botm}

   flopy.mf6.ModflowGwfdisv(gwf, **disv_kwargs)

9. Forcing pipeline (recharge and climate variables)
----------------------------------------------------

9.1 Context
~~~~~~~~~~~

Climate variables (recharge, precipitation, ETP, etc.) flow through
``LoadResult`` -> ``ForcingBridge`` -> ``Flow``.

9.2 Processing chain
~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   DataManager.load()
          │
          ▼
      LoadResult          # points: list[PointRecord], fields: list[FieldRecord]
          │
          ▼
   resolve_forcing()      # -> ResolvedForcing (homogeneous or heterogeneous)
          │
          ▼
   apply_recharge_load_result_to_flow()   # -> FlowRechargeConfig -> Flow
          │
          ▼
   SolverAdapter          # FlowModflowInputs -> MODFLOW packages

9.3 Spatial modes
~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Mode
     - Description
     - Pipeline
   * - Homogeneous
     - One value per timestep
     - ``series: pd.Series`` (m/s)
   * - Heterogeneous
     - One value per cell per timestep
     - ``LoadResult.fields`` -> grid interpolation

9.4 Current limitation
~~~~~~~~~~~~~~~~~~~~~~

**The forcing pipeline is currently wired to structured grids.**
Heterogeneous discretization uses ``sgrid.nrow`` / ``sgrid.ncol`` to
build 2D arrays. Supporting unstructured meshes (DISV) requires
adapting the spatial discretization of ``FieldRecord`` to the cells of
a ``HydroMesh`` instead of a ``(nrow, ncol)`` grid.

10. Module layout
-----------------

.. code-block:: text

   hydromodpy/mesh/
   ├── __init__.py              # Exports: CellType, CellBlock, HydroMesh
   ├── cell_types.py            # CellType enum + aliases + properties
   ├── hydro_mesh.py            # CellBlock + HydroMesh (frozen dataclasses)
   ├── plotting.py              # plot_cell_values(): unified dispatch
   ├── adapters/
   │   ├── __init__.py          # re-exports of every adapter
   │   ├── meshio_adapter.py    # from_meshio() / to_meshio()
   │   ├── field_mesh_adapter.py   # from_field_mesh() / from_gmsh_planar() / from_extruded_prism()
   │   └── flopy_adapter.py     # from_flopy_structured() / to_flopy_disv_args()
   └── io/
       └── vtu_io.py            # write_vtu() / read_vtu()

10.1 Dependencies
~~~~~~~~~~~~~~~~~

The core (``cell_types.py``, ``hydro_mesh.py``) only depends on
**numpy**.

.. list-table::
   :header-rows: 1

   * - Module
     - Extra dependencies
   * - ``plotting.py``
     - matplotlib
   * - ``meshio_adapter.py``
     - meshio (optional)
   * - ``vtu_io.py``
     - meshio (optional)
   * - ``flopy_adapter.py``
     - flopy (lazy import of ``sgrid_mesh_adapter``)
   * - ``field_mesh_adapter.py``
     - none (duck-typed against ``BaseFieldMesh``)

11. End-to-end data flow
------------------------

.. code-block:: text

               ┌──────────────────────────────────────┐
               │         TOML configuration            │
               │  [field] [mesh] [field_param]         │
               └──────┬───────────┬───────────────────┘
                      │           │
                      ▼           ▼
               FieldSquare    FieldParam
               (geometry)     (K=1e-4 m/s, zones, vertical profile)
                      │           │
                      ▼           │
               field.on_mesh()    │
                      │           │
                      ▼           ▼
               FieldDiscretization    <- field_param.to_mesh_field()
               (zone_keys, fractions)           │
                                                ▼
                                         MeshWithValues
                                         (mesh + cell_values)
                                                │
               ┌────────────────────────────────┼───────────────────┐
               │                                │                   │
               ▼                                ▼                   ▼
   discretize_fieldparam       discretize_fieldparam    .to_hydro_mesh()
     _on_sgrid()                _on_extruded_mesh()            │
               │                                │              ▼
               ▼                                ▼         HydroMesh
   values_3d (nlay,nrow,ncol)   values_3d (nlay,n2d)         │
               │                                │       ┌────┼────┐
               ▼                                ▼       │    │    │
        MODFLOW NWT/6                    VTU export   plot  VTU  DISV

12. Methods added on existing classes
-------------------------------------

.. list-table::
   :header-rows: 1

   * - Class
     - Method
     - Notes
   * - ``BaseFieldMesh``
     - ``to_hydro_mesh()``
     - Inherited by every subclass
   * - ``GmshPlanarMesh2D``
     - ``to_hydro_mesh()``
     - Optimised override (direct array access)
   * - ``GmshPlanarMesh2D``
     - ``from_hydro_mesh(hm)``
     - Classmethod, rebuilds from a 2D HydroMesh
   * - ``ExtrudedPrismMesh3D``
     - ``to_hydro_mesh()``
     - Preserves ``layer_index`` and ``source_cell_index``

13. Relation to existing classes
--------------------------------

The existing classes (``GmshPlanarMesh2D``,
``StructuredFieldMesh``, etc.) **stay in place**. ``HydroMesh`` does
not replace them: it serves as an exchange format between them.

Each class keeps its own business logic (generation, validation,
``FieldParam`` association) and can produce or consume a
``HydroMesh`` through ``.to_hydro_mesh()``.

New modules should prefer ``HydroMesh`` as the input/output type
rather than depending directly on a concrete implementation.

14. Current limitations and scope
---------------------------------

.. list-table::
   :header-rows: 1

   * - Feature
     - Structured (DIS)
     - Unstructured (DISV)
   * - FieldParam -> 2D discretization
     - Yes
     - Yes
   * - FieldParam -> 3D discretization
     - Yes (``sgrid``)
     - Yes (``extruded_mesh``)
   * - Unified plotting
     - Yes
     - Yes
   * - VTU I/O
     - Yes
     - Yes
   * - MODFLOW-NWT solver
     - Yes (DIS)
     - No (DIS only)
   * - MODFLOW 6 solver
     - Yes (DIS)
     - No (DISV not wired)
   * - Recharge/forcing pipeline
     - Yes
     - No (hardcoded ``nrow x ncol``)
   * - DISV export to FloPy
     - Available (``to_flopy_disv_args``)
     - Not wired to the solver

**Summary.** The ``HydroMesh`` pivot unifies plotting, I/O, and
conversions across mesh types. Parameter discretization
(``FieldParam``) works on every mesh type. But the solver pipeline
(MODFLOW-NWT / MF6) and the forcing pipeline are still
structured-only. The ``to_flopy_disv_args()`` adapter exists for DISV
but is not yet wired into the simulation runner.

15. Design choices
------------------

15.1 Why not xugrid / UGRID NetCDF?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **xugrid** is excellent for 2D plus pseudo-3D layered (UGRID2D),
  but it does not support fully 3D unstructured.
- For temporal result storage (per-cell time series), UGRID NetCDF
  remains relevant via xugrid as an *output* format.
- As an *internal pivot*, vertices plus connectivity is simpler, more
  general, and dependency-free.

15.2 Why not meshio directly?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

meshio is an optional I/O dependency, not a pivot type:

- ``meshio.Mesh`` is not frozen / immutable.
- It supports ~30 cell types, most of which we do not need.
- The ``cell_data`` mapping is a list of lists per block, not flat
  arrays.

``HydroMesh`` is a strict, normalised subset of the meshio model with
guaranteed round-trip conversions through the adapters.

15.3 Why frozen dataclass?
~~~~~~~~~~~~~~~~~~~~~~~~~~

Immutability guarantees that a ``HydroMesh`` cannot be modified after
construction. This simplifies reasoning about data flow and avoids
bugs from accidental mutation. The ``with_cell_data()`` /
``with_point_data()`` methods return copies.

See also
--------

- :doc:`gmsh_meshing` for the conformal Gmsh pipeline.
- :doc:`mesh/index` for the broader mesh architecture and the
  catchment-mesh workflow.
- :doc:`modflow_contracts` for the DIS / BAS contract that consumes
  the structured pivot.
