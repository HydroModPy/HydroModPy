Mesh engines
============

.. rst-class:: lead

A mesh engine turns one request into one cell mesh. Three engines are built in, ``regular``,
``triangle`` and ``voronoi``, and other engines join through the ``hydromodpy.mesh.engine`` entry point. Every
consumer reads the cell mesh the same way, so the engine is a choice of the ``[mesh]``
section and nothing else.

Code: ``hydromodpy/spatial/mesh/``. For the cell mesh an engine returns, see
:doc:`mesh-pivot`. For the choice of an engine and the size field, see :doc:`/theory/mesh`.

From the project to the cell mesh
---------------------------------

.. code-block:: text

   [mesh] + the project inputs
        |  plan_mesh_request     spatial/mesh/planning/
        v
   MeshRequest                   spatial/mesh/request.py      plain frozen data
        |  engine.build          spatial/mesh/engines/<id>/
        v
   PlanarCellMesh                spatial/mesh/model/
        |  step_mesh             workflow/steps/mesh.py       cache, setup.cell_mesh
        v
   solvers, forcing, supports, the Zarr store

The engine reads no file and no config: everything it needs is in the request. The workflow
step is the only place that reads ``[mesh]``, plans the request, asks the cache and hands the
cell mesh to the rest of the run.

The request
-----------

``MeshRequest`` holds the domain polygon, the CRS, the DEM grid (``RasterGridSpec``), the
nominal cell size, the line families (``LineFamilySpec``), the size field, the seed, the
options of the engine, an optional input triangulation and the notes of the planner. Arrays
are copied and read-only, and ``canonical_hash()`` names the request: two requests with the
same hash ask for the same mesh. The hash is part of the identity of the mesh. The engine and
its version enter the identity hash of the run, so a run on another generator is never taken
for an identical run.

A ``LineFamilySpec`` carries a name, an intent (``cell`` or ``face``), the lines, the zone on
each side of a contact and whether the lines are closed. The intent says what the engine does
with the lines: a ``cell`` line runs through a chain of cells, a ``face`` line lies on cell
faces.

The planner
-----------

``plan_mesh_request`` (``spatial/mesh/planning/``) is the one place that knows the project:

- It sets the intent of each family from ``[mesh.families]``: the rivers are ``cell`` lines,
  the geology contacts, the lake shores and the catchment boundary are ``face`` lines.
- It clips the lines to the domain.
- It cleans the lines (``planning/cleanup.py``), for every engine but a triangulation read from
  a file. At a tolerance of a tenth of the DEM pixel (``CLEANUP_PIXEL_SHARE``) it drops the
  holes of the domain, of a lake or of the catchment whose area is below the square of the
  local cell size, merges the vertices closer than the tolerance, cuts back the end of a
  river or a contact that runs along another line, and snaps the end of a line that misses
  another by less than the tolerance. A barrier is only snapped, never cut back, and a vertex
  that two geometries share is not moved. Each kind of change is one line of the log and one
  note of ``MeshQA``, and a request that needs no change is returned as it was.
- For an engine that grades its cells it builds the size field
  (``spatial/mesh/sizing/size_field.py``) from the rivers, the lake shores and the refinement
  zones, plus the terms of ``sizing/gap.py``: one ``SizeTerm`` per level of the gap between
  the face lines, switched off by ``[mesh] gap_cells = 0``. It resamples each line at the
  local cell size and merges the segments shorter than 0.8 of it. A barrier wing next to a
  lake shore is left out when it is shorter than half the local cell size where it leaves the
  shore. The rule of the size field is on :doc:`/theory/mesh`.
- For a request with a triangulation read from a file (``planning/input_mesh.py``), it refuses
  a T-junction, a vertex that lies inside the edge of a triangle that does not hold it, with
  the coordinates in the message, and warns about vertices closer than 1e-9 of the extent.
- It reads the ``.msh`` file of ``[mesh.triangle] path``, when given, into the request instead
  of planning a triangulation.

Engines and capabilities
------------------------

An engine is a class with three class variables and one method, checked structurally by the
``MeshEngine`` protocol (``spatial/mesh/port.py``). Its capabilities are claims a caller can
act on before the mesh exists. The values are the capabilities each engine class declares (``MeshEngineCapabilities``), and the last column lists
the flow solvers that read the engine:

.. list-table::
   :header-rows: 1

   * - Engine
     - Cells
     - Structured
     - Graded
     - Exact faces
     - River chain
     - Deterministic
     - Cached
     - Read by
   * - ``regular``
     - ``quadrilateral``
     - yes
     - no
     - no
     - ``rasterized``
     - yes
     - no
     - ``modflow6``, ``modflow_nwt``
   * - ``triangle``
     - ``triangle``
     - no
     - yes
     - yes
     - ``derived_from_faces``
     - no
     - yes
     - ``boussinesq``, ``modflow6``
   * - ``voronoi``
     - ``polygon``
     - no
     - yes
     - yes
     - ``exact``
     - yes
     - no
     - ``modflow6``

``graded`` says that the engine follows the size field. ``exact_faces`` says that a face line
lies on cell faces and not on a staircase of them. ``cell_families`` says how a river becomes
a chain of cells: on the line itself, by rasterizing it, or from the faces of the cells on one
bank. ``deterministic`` says that one request gives one mesh, and ``needs_cache`` that the
engine cannot rebuild a mesh it built before. The quality report of every mesh repeats the
claims, and a note in it says what the engine did not do (a ``regular`` engine given a river
size says that it ignores it).

``regular``
   ``engines/regular/``. Square cells of one pitch, bit for bit the grid FloPy builds: row 0
   in the north, the vertices computed and ordered as FloPy does. The pitch is the DEM pitch
   or a larger ``[mesh] cell_size``, and the engine refuses a smaller one. The domain polygon
   and the size field shape no cell: the solver masks the cells outside the domain. A river is
   rasterized with the thin-line rule of WhiteboxTools and ordered along the line, and a face
   family is a staircase whose distance to the line the report gives.

``triangle``
   ``engines/triangle/``, described on :doc:`triangle-engine`.

``voronoi``
   ``engines/voronoi/``, described on :doc:`voronoi-engine`.

Which solver reads which engine
-------------------------------

Each flow adapter declares ``accepted_meshes`` beside ``requires``
(``solver/base/adapter_protocol.py``): the engine ids it reads, or the token ``*planar`` for
any engine whose cells are triangles, quadrilaterals or polygons.
The last column of the table above lists them.

``HydroModPyConfig`` checks the pair while it reads the file, before any step runs, and the
message names the engines the solver reads and the solvers that read the engine asked for. A
cell addressed by ``[lay, row, col]`` (a well, an SFR reach) is refused on every engine but
``regular``, in the same place.

The cache
---------

An engine with ``needs_cache`` is built once per request. The mesh is stored under
``<project>/.hmp/mesh_cache/<key>/`` (``mesh.npz`` and ``mesh.json``), written in a temporary
folder and renamed. The key names the request, the engine and its version, and the builds of
Gmsh, shapely, GEOS and scipy. A resume and ``restart_from`` read the mesh from there. The
folder is the one entry of ``.hmp/`` that is not disposable, see :doc:`../storage-layout`.

The step then writes the mesh once, before the solve, in the ``mesh/`` group of the Zarr store.
The solver extractors check the grid they solved against it and raise ``IncompatibleMeshError``
when they differ.

Add an engine
-------------

A third-party engine needs the port module, the request, the cell mesh model and the exceptions
of ``core``, and nothing else of HydroModPy:

.. code-block:: python

   from typing import ClassVar

   from hydromodpy.spatial.mesh.model.cell_types import CellType
   from hydromodpy.spatial.mesh.port import MeshEngineCapabilities


   class MyEngine:
       engine_id: ClassVar[str] = "myengine"
       engine_version: ClassVar[str] = "1.0.0"
       capabilities: ClassVar[MeshEngineCapabilities] = MeshEngineCapabilities(
           cell_types=(CellType.POLYGON,),
           structured=False,
           graded=True,
           exact_faces=False,
           cell_families="derived_from_faces",
           deterministic=True,
           needs_cache=False,
       )

       def build(self, request):
           ...  # return a PlanarCellMesh

It joins the registry through the entry-point group ``hydromodpy.mesh.engine``, named on its
``engine_id``:

.. code-block:: toml

   [project.entry-points."hydromodpy.mesh.engine"]
   myengine = "mypackage.engine:MyEngine"

Then ``[mesh] engine = "myengine"`` names it. An entry point whose name is not the ``engine_id``
of its class, or a name that a built-in engine owns, is ignored with a warning. Bump
``engine_version`` whenever the mesh the engine returns for one request changes: the cache and
the identity of the run key on it. The engine raises ``MeshRequestError`` for a request it
cannot honour and ``MeshGenerationError`` for a mesh it cannot build.

The contract is proven for every registered engine by
``tests/contract/test_mesh_engine_contract.py``, and the path of a plugin by
``tests/contract/test_mesh_conformance_reaches_an_installed_engine.py``.

See also
--------

- :doc:`mesh-pivot` for the cell mesh, its families and the consumers.
- :doc:`triangle-engine` and :doc:`voronoi-engine`.
- :doc:`/theory/mesh` for the size field and the choice of an engine.
- :doc:`../solver/backends` for the grids the solvers write.
