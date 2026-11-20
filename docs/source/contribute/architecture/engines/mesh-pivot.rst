The mesh pivot and the cell mesh
================================

``HydroMesh`` is the exchange format of a mesh. ``PlanarCellMesh`` wraps a planar one, and it is
the mesh that every solver, every workflow step and every field support reads. The code is in
``hydromodpy/mesh/planar/`` and its package page is :doc:`../packages/mesh`. The engines that
build it are on :doc:`mesh-engines`, and the grids of the solvers are on :doc:`backends`.

The pivot
---------

``HydroMesh`` (``mesh/planar/hydro_mesh.py``) is a frozen dataclass. It describes any 2D or 3D
mesh the same way, in the data model of meshio.

.. literalinclude:: ../../../../../hydromodpy/mesh/planar/hydro_mesh.py
   :pyobject: CellBlock
   :end-before: def __post_init__

``CellType`` has ``TRIANGLE``, ``QUADRILATERAL``, ``POLYGON``, ``WEDGE`` and ``HEXAHEDRON``. A
``POLYGON`` block is the one case of a block with cells of unequal size, so it pads its rows with
``-1``. ``flat_connectivity`` stacks the blocks into one table padded the same way. A
``HydroMesh`` with a ``structured_shape`` is a regular grid, and only such a mesh gives the DIS
grid of MODFLOW-NWT (``SolverMesh.to_dis_kwargs()``). The class is frozen, so ``with_cell_data``
and ``with_point_data`` return a new instance.

The disk formats live in ``mesh/io/``, one module per format, and depend on the mesh model only.

- VTU (``io/vtu.py``) is the recommended format. It describes itself, opens in ParaView, PyVista
  and QGIS, and round-trips through ``HydroMesh``. ``write_vtu`` also writes whole-mesh values,
  such as the CRS of a run, in the ``FieldData`` of the grid, and ``read_vtu_field_data`` reads
  them back. ``hmp export`` writes its VTU files through this module, with the cells in the order
  of the run store.
- ``io/meshio_bridge.py`` passes a ``HydroMesh`` through meshio. A polygon block goes out as runs
  of consecutive cells of one node count, so the cell order is kept, and comes back as one block.
- ``io/msh.py`` reads a Gmsh ``.msh`` file. ``read_gmsh_2d_mesh`` uses meshio, or a small reader
  of the ASCII 2.2 format when meshio fails, and returns the lines of the named physical groups.
  A ``.msh`` file carries no CRS, so ``write_gmsh_2d_mesh`` writes the WKT of a given ``crs`` to
  ``<name>.prj`` next to the mesh, and the reader reads it back.
- ``io/bundle.py`` reads a Boussinesq validation bundle, a folder of CSV files. The version is
  ``BUNDLE_SCHEMA_VERSION`` and ``BUNDLE_COLUMNS`` gives the columns of each file.

xugrid handles 2D and layered pseudo-3D meshes but not fully 3D unstructured ones, so it cannot be
the pivot. meshio is the I/O dependency, but its ``meshio.Mesh`` is mutable and supports about
thirty cell types, most of them useless here. ``HydroMesh`` is a strict, frozen subset of that
model.

The cell mesh
-------------

``PlanarCellMesh`` (``mesh/planar/planar_cell_mesh.py``) is the mesh that the solvers and the
workflow steps read, as ``setup.cell_mesh``. It wraps one planar ``HydroMesh`` block of
triangles, quadrilaterals or polygons, unchanged, and it holds what every consumer would
otherwise recompute.

.. literalinclude:: ../../../../../hydromodpy/mesh/planar/planar_cell_mesh.py
   :pyobject: PlanarCellMesh
   :end-before: def __post_init__

The cell centers follow one rule for every consumer. The ``center_kind`` says which, and it is
``generator`` for Voronoi, ``cell_center`` for a regular grid, ``vertex_mean`` for triangles and
``interior_point`` for the one cell of the ``catchment`` engine. A ``HydroMesh`` carries no
centers, so a consumer reads ``cell_mesh.centers``.

``cell_mesh.geometry`` is a ``DerivedGeometry`` (``mesh/planar/geometry.py``), derived once on
first use. It holds the ``-1`` padded connectivity (the format of the Zarr store), the areas, the
area centroids, the edge table and the CSR adjacency of the interior edges. An edge shared by
more than two cells raises ``ValueError``. ``cell_mesh.connectivity_rows`` returns the cells as
one array, which is the block itself for triangles and quadrilaterals and the padded rows as
32-bit ids for polygons.

``MeshQA`` (``mesh/planar/quality.py``) holds the quantiles of area, size, center offset,
non-orthogonality and cell shape, the concave cells, the degenerate faces, the family coverage and
the engine declarations. ``quality_warnings`` turns the shape entries into build warnings and
never refuses a mesh.

Line families
~~~~~~~~~~~~~

A family is a set of lines that the mesh honors, under one name. Its intent decides what the cell
mesh keeps.

- A cell family (``rivers``) runs through the cells. ``cell_chains`` holds one chain of cells per
  line, from upstream to downstream. ``CellChain.offset_m`` gives the distance from each cell
  center to the line. The ``voronoi`` engine fills it, and it is ``None`` where the cell holds the
  line.
- A face family (``geology``, ``lakes``, ``barriers``, ``watershed_boundary``) lies on cell faces.
  ``face_families`` has one row per mesh edge on a line, with the two cells (``-1`` outside the
  domain), the two vertices and the zone on each side. An edge on two families, such as a cutoff
  wall along a lake shore, has a row in each. The four sides of the domain are face families named
  ``boundary:<side>``.

The ``cell_families`` capability of an engine says how it forms a cell family, and the intent of
each family comes from ``[mesh.families]``. Every engine gives a river as cell chains, and a
triangle mesh also keeps the faces of the river line as face rows.

.. _consumers-read-the-cell-mesh:

Consumers read the cell mesh
----------------------------

Every consumer reads the cell mesh, and none reads an engine-specific support. One function
serves every engine for each question.

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Question
     - Where
   * - Centers, areas, adjacency
     - ``SolverMesh.cell_centers()``, ``cell_areas()`` and ``face_adjacency()``, read from
       ``cell_mesh.geometry``.
   * - Cells of a side, of the river, of a label
     - ``side_cells``, ``stream_cells`` and ``label_cells`` in ``mesh/cells/boundary.py``.
   * - Cell that holds a point
     - ``locate_cells`` in ``mesh/cells/locate.py``. A point outside the mesh gets the nearest cell
       only within one cell size (the square root of its area), otherwise no cell and a warning.
       The solvers call ``locate_cell_on_solver_mesh`` in ``solver/base/cell_lookup.py``, which
       uses the top active layer of the column.
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
     - ``mesh/cells/barrier_faces.py`` gives the faces a barrier line bars. The MODFLOW 6
       builders give the cells a lake owns and the faces of its cutoff wall
       (``solver/modflow6/builders/_lake_geometry.py``), and share a reach among the cells
       (``_sfr_network.py``).
   * - The share of a cell inside a polygon
     - ``cell_area_fraction`` in ``mesh/cells/in_polygons.py``.

The vertical layers, the grids and stations put on the cells, and the field supports live outside
``mesh/``, in ``model/domain/``, ``model/forcing/`` and ``model/properties/``. They read the mesh
model and the mesh never imports them. The field package is on :doc:`../packages/model`.

What the solvers read
---------------------

A solver reads the ``SolverMesh`` of ``solver/modflow_grid/solver_mesh.py``. It is built from the
cell mesh and the vertical layers of ``[domain.layers]``, which both MODFLOW backends read.
``layer_stack`` in ``model/domain/layering.py`` turns shares or surfaces into the layer bottoms
and the integer ``idomain`` (1, 0 or -1). ``discretization_spatial.py``, next to
``solver_mesh.py``, samples the base rasters on the cell centers or resamples them to a regular
grid. ``SolverMesh`` checks the interfaces once it is built, and the run stores them with the
``idomain`` (:doc:`../storage-layout`). ``active_connectivity.py`` warns when some groups of
active cells have no connection to the rest. The MODFLOW 6 build and the MODFLOW-NWT solver call
it on the final grid, after the lake mask, and it counts a pass-through cell and a lake as
connections.

MODFLOW 6 reads a DISV grid for every engine. A regular grid is also written as DISV, through
``SolverMesh.to_disv_kwargs()``, which calls ``to_flopy_disv_args``. MODFLOW-NWT reads a DIS grid,
which only the ``regular`` engine gives. Boussinesq reads the triangles of the cell mesh, and a
validation case gives a bundle that ``cell_mesh_from_bundle`` turns into a cell mesh. Each flow
adapter declares the engines it reads in ``accepted_meshes``, as :doc:`mesh-engines` says.
