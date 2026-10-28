Mesh engines
============

.. rst-class:: lead

A mesh engine turns one request into one cell mesh. Three engines are built in, ``regular``,
``triangle`` and ``voronoi``, and others join through the ``hydromodpy.mesh.engine`` entry
point. Every consumer reads the cell mesh the same way, so the engine is a choice of the
``[mesh]`` section and nothing else.

Code: ``hydromodpy/spatial/mesh/``. The cell mesh is on :doc:`mesh-pivot`, and the choice of an
engine and the size field are on :doc:`/theory/mesh`.

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

The engine reads no file and no config, because the request holds everything it needs. The
workflow step is the only place that reads ``[mesh]``. It plans the request and asks the cache.

The request
-----------

``MeshRequest`` is plain frozen data (``spatial/mesh/request.py``). It holds the domain polygon,
the DEM grid (``RasterGridSpec``), whose CRS is the CRS of the request, the nominal cell size,
the line families, the size field, the seed, the options of the engine, an optional input
triangulation and the notes of the planner, and ``source_runs``, the sorted ``sim_id`` of the runs a refinement zone read.
``canonical_hash()`` names it, so two requests with the same hash ask for the same mesh. The list
of ``source_runs`` enters the hash when it is not empty, so a request with no such run keeps its
hash.
The engine and its version enter the identity hash of the run, so a run on another generator is
never taken for an identical run.

Each stage checks what only it can see. ``[mesh]`` refuses what a user writes, with a message in
the terms of the TOML file. The request refuses what no engine can mesh, such as a grid whose steps,
shape and bounds disagree, a size that is not finite and positive, an invalid domain or zones
that do not match the lines. It does not check the type of a member, which its annotation
states. An engine trusts its request and reads its options as the planner wrote them.

Each line family (``LineFamilySpec``) has a name, an intent, the lines, the zone on each side of a
contact and a flag for closed lines. A ``cell`` line runs through a chain of cells, and a ``face``
line lies on cell faces.

The planner
-----------

``plan_mesh_request`` (``spatial/mesh/planning/``) is the one place that knows the project.

- It sets the intent of each family from ``[mesh.families]``. Rivers are ``cell`` lines, and
  geology contacts, lake shores and the catchment boundary are ``face`` lines.
- It clips the lines to the domain and cleans them, for every engine but a triangulation read
  from a file. The rules are on :ref:`mesh-cleanup`.
- For the graded engines, it smooths the staircase of the catchment outline where the mesh
  follows it (``planning/catchment_outline.py``). The rules are on :ref:`mesh-cleanup` too.
- For an engine that grades its cells, it builds the size field (``planning/size_field.py``) and
  the term for the gap between face lines (``planning/gap_size.py``), which ``[mesh] gap_cells = 0``
  switches off. The rule is on :doc:`/theory/mesh`.
- It turns each ``[[mesh.refinement_zone]]`` drawn by a field into a term of the size field
  (``planning/refinement_zones.py``). The zone is a set of DEM pixels, a ``PixelRegion`` of the size
  field. The height above the stream comes from ``planning/height_above_stream.py``. A field of
  an earlier run is read by the workflow step (``workflow/steps/mesh_run_fields.py``), because
  ``spatial`` cannot import ``results``, and it reaches the planner as pixels. The ``regular``
  engine does not grade its cells, so the planner drops these zones and the QA says so.
- With ``[mesh.lake_refinement]``, it turns each hydraulic structure of a lake into a term of the
  size field. The size rules are in ``planning/lake_structures.py``: each cutoff wall, the sill
  between two lakes apart, finer than their gap so that no cell holds both lakes, and the disk
  around the declared outlet unless a wall zone reaches it. The workflow step reads the walls,
  the lake footprints and the outlet from the run (``workflow/steps/mesh_inputs.py``) and hands
  them to these rules as plain geometries.
- For a triangulation read from a file (``planning/input_triangulation.py``), it reads the ``.msh`` file
  of ``[mesh.triangle] path`` once, through ``io/msh.py``, instead of planning one. It refuses a T-junction, a vertex inside
  the edge of a triangle that does not hold it, and gives its coordinates. It warns about
  duplicate vertices.

Engines and capabilities
------------------------

The capabilities of an engine are claims that a caller can act on before the mesh exists. The
table gives them for the built-in engines, with the flow solvers that read each engine.

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

``graded`` means that the engine follows the size field, and ``exact_faces`` that a face line
lies exactly on cell faces. ``cell_families`` says how a river becomes a
chain of cells: on the line itself, by rasterizing it, or from the faces of the cells on one
bank. ``deterministic`` means that one request gives one mesh, and ``needs_cache`` that the
engine cannot rebuild a mesh it built before. The quality report of every mesh repeats these
claims and notes what the engine left out.

``regular``
   ``engines/regular/``. Square cells of one pitch, bit for bit the grid FloPy builds, with row 0
   in the north. The pitch is the DEM pitch or a larger ``[mesh] cell_size``, and the engine
   refuses a smaller one. The domain polygon and the size field shape no cell, because the solver
   masks the cells outside the domain. A river is rasterized with the thin-line rule of
   WhiteboxTools. A face family is a staircase, and the report gives its distance to the line.

``triangle``
   ``engines/triangle/``, described on :doc:`triangle-engine`.

``voronoi``
   ``engines/voronoi/``, described on :doc:`voronoi-engine`.

Which solver reads which engine
-------------------------------

Each flow adapter declares ``accepted_meshes`` (``solver/base/adapter_protocol.py``). It lists
the engine ids the solver reads, or ``*planar`` for any engine whose cells are triangles,
quadrilaterals or polygons. ``HydroModPyConfig`` checks the pair while it reads the file, before
any step runs. Its message names the engines the solver reads and the solvers that read the engine
asked for. In the same place it refuses a cell addressed by ``[lay, row, col]`` (a well, an SFR
reach) on every engine but ``regular``.

The cache
---------

An engine with ``needs_cache`` is built once per request. The step stores the mesh under
``<project>/.hmp/mesh_cache/<key>/``, as ``mesh.npz`` and ``mesh.json``. The key names the
request, the engine and its version, and the builds of Gmsh, shapely, GEOS and scipy. A resume
and ``restart_from`` read the mesh from there, so this folder is the one entry of ``.hmp/`` that
is not disposable (:doc:`../storage-layout`).

The step writes the mesh once, before the solve, in the ``mesh/`` group of the Zarr store. A
solver extractor raises ``IncompatibleMeshError`` when its grid differs from it.

Add an engine
-------------

An engine is a class with three class variables and one method, checked by the ``MeshEngine``
protocol (``spatial/mesh/port.py``). A third-party engine imports the port module, the request,
the cell mesh model and the exceptions of ``core``, and nothing else of HydroModPy:

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

It joins the registry through the entry-point group ``hydromodpy.mesh.engine``, under the name
of its ``engine_id``:

.. code-block:: toml

   [project.entry-points."hydromodpy.mesh.engine"]
   myengine = "mypackage.engine:MyEngine"

Then ``[mesh] engine = "myengine"`` selects it. The registry ignores, with a warning, an entry
point whose name is not the ``engine_id`` of its class or is the name of a built-in engine. Bump
``engine_version`` whenever the mesh for one request changes, because the cache and the run
identity key on it. The engine raises ``MeshRequestError`` for a request it cannot honour and
``MeshGenerationError`` for a mesh it cannot build. The contract tests are
``tests/contract/test_mesh_engine_contract.py`` for every registered engine and
``tests/contract/test_mesh_conformance_reaches_an_installed_engine.py`` for a plugin. The contract
gives ``cell_size`` one meaning: a uniform size gives the area over the square of that size,
within 10 % (row 182 of ``tests/TOLERANCES.md``), and a plugin meets it too. An engine whose own
parameter is an edge length converts it, as the ``triangle`` engine does.

See also
--------

- :doc:`mesh-pivot` for the cell mesh, its families and the consumers.
- :doc:`triangle-engine` and :doc:`voronoi-engine`.
- :doc:`/theory/mesh` for the size field and the choice of an engine.
- :doc:`../solver/backends` for the grids the solvers write.
