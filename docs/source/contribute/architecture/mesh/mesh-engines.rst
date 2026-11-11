Mesh engines
============

.. rst-class:: lead

A mesh engine turns one request into one cell mesh. Four engines are built in, ``regular``,
``triangle``, ``voronoi`` and ``catchment``, and others join through the
``hydromodpy.mesh.engine`` entry point. Every consumer reads the cell mesh the same way, so the engine is a choice of the
``[mesh]`` section and nothing else.

Code: ``hydromodpy/mesh/``. The cell mesh is on :doc:`mesh-pivot`, and the choice of an
engine and the size field are on :doc:`/theory/mesh`.

From the project to the cell mesh
---------------------------------

.. code-block:: text

   [mesh] + the project inputs
        |  plan_mesh_request     mesh/planning/
        v
   MeshRequest                   mesh/request.py      plain frozen data
        |  engine.build          mesh/engines/<id>/
        v
   PlanarCellMesh                mesh/planar/
        |  step_mesh             workflow/steps/mesh.py       product store, setup.cell_mesh
        v
   solvers, forcing, supports, the Zarr store

The engine reads no file and no config, because the request holds everything it needs. The
workflow step is the only place that reads ``[mesh]``. It plans the request and asks the product store.

The request
-----------

``MeshRequest`` is plain frozen data (``mesh/request.py``). It holds the domain polygon,
the DEM grid (``RasterGridSpec``), whose CRS is the CRS of the request, the nominal cell size,
the line families, the size field, the seed, the options of the engine, an optional input
triangulation and the notes of the planner, and ``source_runs``, the sorted ``sim_id`` of the runs a refinement zone read.
``canonical_hash()`` names it, so two requests with the same hash ask for the same mesh. The list
of ``source_runs`` enters the hash when it is not empty, so a request with no such run keeps its
hash. ``catchment`` is the outline of the catchment the outlet closes. The planner fills it for a
lumped engine only, and it enters the hash only when it is there, so the hash of every request for
another engine does not change.
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

``plan_mesh_request`` (``mesh/planning/``) is the one place that knows the project.

- For a lumped engine, it puts the catchment outline in the request: the delineated polygon, or the
  domain on a synthetic support, which has no other catchment. A real support without a delineated
  polygon is refused with ``MeshRequestError``. The workflow step reads the delineated polygon for
  such an engine, as it does for a graded one.
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
  an earlier run is read by the workflow step (``results/run/field_envelope.py``), because
  ``mesh`` cannot import ``results``, and it reaches the planner as pixels. The ``regular``
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
     - Lumped
     - Read by
   * - ``regular``
     - ``quadrilateral``
     - yes
     - no
     - no
     - ``rasterized``
     - yes
     - no
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
     - no
     - ``boussinesq``, ``modflow6``
   * - ``voronoi``
     - ``polygon``
     - no
     - yes
     - yes
     - ``exact``
     - yes
     - no
     - no
     - ``modflow6``
   * - ``catchment``
     - ``polygon``
     - no
     - no
     - no
     - ``derived_from_faces``
     - yes
     - no
     - yes
     - ``linear_reservoir``

``graded`` means that the engine follows the size field, and ``exact_faces`` that a face line
lies exactly on cell faces. ``cell_families`` says how a river becomes a
chain of cells: on the line itself, by rasterizing it, or from the faces of the cells on one
bank. ``deterministic`` means that one request gives one mesh, and ``needs_cache`` that the
engine cannot rebuild a mesh it built before. ``lumped`` means that the engine meshes the catchment
as one cell, for a global model. It defaults to ``False``, so an engine written before it keeps its
capabilities. The quality report of every mesh repeats the first four of these claims and notes
what the engine left out.

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

``catchment``
   ``engines/catchment/``. One polygon cell whose vertices are the exterior ring of
   ``MeshRequest.catchment``, counterclockwise, with no face. A hole of the outline is filled, and a
   note of the mesh gives how many and their area, because the water that falls in a hole of a
   delineated catchment still reaches its outlet. The center is the point that shapely's
   ``point_on_surface`` gives (``center_kind = "interior_point"``), so it lies in the cell even when
   the vertex mean of a concave catchment does not. The engine declares every line family in
   ``ignored_families``, and the planner drops what those families would have asked with a named
   note in the mesh report, so the default ``rivers = "cell"`` does not refuse the engine. A family
   an engine ignores, written with a value other than ``none``, is refused when the file is read.
   The engine refuses a size field and an input triangulation, which one cell cannot hold.

Which solver reads which engine
-------------------------------

Each flow adapter declares ``accepted_meshes`` as a class attribute, one of the twelve of ``solver/base/adapter_protocol.py``. It lists
the engine ids the solver reads, or ``*planar`` for any engine whose cells are triangles,
quadrilaterals or polygons and that is not lumped. A solver that reads one cell names the lumped
engine, so MODFLOW 6 never computes on the single cell of ``catchment``. The rule is
``engine_accepted`` of ``mesh/registry.py``, which loads the engine class only when its capabilities
decide. ``HydroModPyConfig`` checks the pair while it reads the file, before any step runs. Its
message names the engines the solver reads and the solvers that read the engine
asked for. In the same place it refuses a cell addressed by ``[lay, row, col]`` (a well, an SFR
reach) on every engine but ``regular``. Without ``[mesh] engine``, when the only engines the
flow backend accepts are lumped ones, the engine of the run is that lumped engine, and the
seal writes it among the mesh facts.

The product store
-----------------

Every mesh is stored in the product store under ``<project>/.hmp/products/<key>/``, as ``mesh.npz``
and ``mesh.json``. The key names the request, the engine and its version, the builds of Gmsh,
shapely, GEOS and scipy, and the code of the mesh package, so a change of code rebuilds the mesh
once. A resume and ``restart_from`` read the mesh from there, and a sealed run keeps its mesh in
the ``mesh/`` group of its Zarr store, so it never depends on the store
(:doc:`../storage-layout`).

The step writes the mesh once, before the solve, in the ``mesh/`` group of the Zarr store. A
solver extractor raises ``IncompatibleMeshError`` when its grid differs from it.

Add an engine
-------------

An engine is a class with three class variables and one method, checked by the ``MeshEngine``
protocol (``mesh/port.py``). A third-party engine imports the port module, the request,
the cell mesh model and the exceptions of ``core``, and nothing else of HydroModPy:

.. code-block:: python

   from typing import ClassVar

   from hydromodpy.mesh.planar.cell_types import CellType
   from hydromodpy.mesh.port import MeshEngineCapabilities


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
``engine_version`` whenever the mesh for one request changes, because the product store and the run
identity key on it. The engine raises ``MeshRequestError`` for a request it cannot honor and
``MeshGenerationError`` for a mesh it cannot build. The contract tests are in
``tests/ports/test_mesh.py``, for every registered engine and for a plugin installed from a
clone. The contract
gives ``cell_size`` one meaning: a uniform size gives the area over the square of that size,
within 10 % (row 182 of ``tests/TOLERANCES.md``), and a plugin meets it too. An engine whose own
parameter is an edge length converts it, as the ``triangle`` engine does.

See also
--------

- :doc:`mesh-pivot` for the cell mesh, its families and the consumers.
- :doc:`triangle-engine` and :doc:`voronoi-engine`.
- :doc:`/theory/mesh` for the size field and the choice of an engine.
- :doc:`../solver/backends` for the grids the solvers write.
