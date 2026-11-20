Mesh engines
============

.. rst-class:: lead

A mesh engine turns one request into one cell mesh. Four engines are built in, ``regular``,
``triangle``, ``voronoi`` and ``catchment``, and others join through the
``hydromodpy.mesh.engine`` entry point. Every consumer reads the cell mesh the same way, so the
engine is a choice of the ``[mesh]`` section and nothing else.

The package page is :doc:`../packages/mesh` and the cell mesh is on :doc:`mesh-pivot`. The choice
of an engine, the size field and the line cleaning are on :doc:`/theory/mesh`.

From the project to the cell mesh
---------------------------------

``plan_mesh_request`` (``mesh/planning/plan.py``) turns ``[mesh]`` and the project inputs into a
``MeshRequest`` (``mesh/request.py``). ``engine.build`` (``mesh/engines/<id>/``) turns it into a
``PlanarCellMesh`` (``mesh/planar/``). The step ``workflow/steps/mesh.py`` stores it as
``setup.cell_mesh``, and the solvers, the forcing, the supports and the Zarr store read it.

The engine reads no file and no config, because the request holds everything it needs. Only the
workflow step reads ``[mesh]``.

The request
-----------

``MeshRequest`` (``mesh/request.py``) holds the domain, the DEM grid, the nominal cell size, the
line families, the size field, the seed, the options of the engine and an optional input
triangulation. ``canonical_hash()`` names it, so two requests with the same hash ask for the same
mesh. ``source_runs`` (the runs a refinement zone read) and ``catchment`` (the outline of a lumped
engine) enter the hash only when they are set, so a request that does not use them keeps its hash.
The engine and its version enter the identity hash of the run, so a run on another generator is
never taken for an identical run.

Each stage checks what only it can see. ``[mesh]`` refuses what a user writes. The request
refuses what no engine can mesh, such as a grid whose steps, shape and bounds disagree. An engine
trusts its request.

A line family (``LineFamilySpec``) has a name, an intent, the lines and the zone on each side of
a contact. A ``cell`` line runs through a chain of cells, and a ``face`` line lies on cell faces.

The planner
-----------

``plan_mesh_request`` is the one place that knows the project. It works in this order.

1. For a lumped engine, it puts the catchment outline in the request. This is the delineated
   polygon, or the domain on a synthetic support. A real support without a delineated polygon is
   refused with ``MeshRequestError``.
2. It sets the intent of each family from ``[mesh.families]``.
3. It clips the lines to the domain and cleans them (:ref:`mesh-cleanup`). A triangulation read
   from a file skips this step.
4. For a graded engine, it smooths the catchment outline where the mesh follows it, then builds
   the size field, the gap term, the refinement zones and the lake structures
   (``planning/size_field.py``, ``gap_size.py``, ``refinement_zones.py``,
   ``lake_structures.py``).
5. For a triangulation read from a file, it reads the ``.msh`` file of ``[mesh.triangle] path``
   once, through ``io/msh.py`` (``planning/input_triangulation.py``). It refuses a T-junction,
   a vertex inside the edge of a triangle that does not hold it, and gives its coordinates.

The inputs that come from a run reach the planner as plain geometries, because ``mesh`` cannot
import ``results``. The workflow step reads them (``workflow/steps/mesh_inputs.py``).

The engine contract
-------------------

An engine is a class with three class variables and one method. A third-party engine imports the
port module, the request, the cell mesh model and the exceptions of ``core``, and nothing else of
HydroModPy.

.. literalinclude:: ../../../../../hydromodpy/mesh/port.py
   :pyobject: MeshEngine

The capabilities are claims that a caller can act on before the mesh exists. Each built-in engine
states its own values in its ``engine.py``, and the QA of every mesh repeats the first four.

.. literalinclude:: ../../../../../hydromodpy/mesh/port.py
   :pyobject: MeshEngineCapabilities

``graded`` means that the engine follows the size field, and ``exact_faces`` that a face line
lies exactly on cell faces. ``cell_families`` says how a river becomes a chain of cells.
``deterministic`` means that one request gives one mesh, and ``needs_cache`` that the engine
cannot rebuild a mesh it built before.

Which solver reads which engine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each flow adapter declares ``accepted_meshes`` (``solver/base/adapter_protocol.py``). It lists
the engine ids the solver reads, or ``*planar`` for any planar engine that is not lumped. A solver
that reads one cell names the lumped engine, so MODFLOW 6 never computes on the single cell of
``catchment``. The rule is ``engine_accepted`` of ``mesh/registry.py``. ``HydroModPyConfig``
checks the pair while it reads the file, and it refuses a cell addressed by ``[lay, row, col]`` (a
well, an SFR reach) on every engine but ``regular``.

The product store
~~~~~~~~~~~~~~~~~

Every mesh is stored under ``<project>/.hmp/products/<key>/`` (``mesh/stored.py``). The key names
the request, the engine and its version, the builds of Gmsh, shapely, GEOS and scipy, and the code
of the mesh package, so a change of code rebuilds the mesh once. A resume and ``restart_from``
read the mesh from there. A sealed run keeps its mesh in the ``mesh/`` group of its Zarr store, so
it never depends on the product store (:doc:`../storage-layout`).

Add an engine
-------------

An engine declares ``engine_id``, ``engine_version``, ``capabilities`` and ``build``, as the
protocol above shows. ``mesh/engines/catchment/engine.py`` is the shortest one to copy.

It joins the registry through the entry-point group ``hydromodpy.mesh.engine``, under the name of
its ``engine_id``, as ``myengine = "mypackage.engine:MyEngine"`` in the ``[project.entry-points]``
table of its ``pyproject.toml``.

Then ``[mesh] engine = "myengine"`` selects it. The registry ignores, with a warning, an entry
point whose name is not the ``engine_id`` of its class or is the name of a built-in engine. Bump
``engine_version`` whenever the mesh for one request changes, because the product store and the
run identity key on it. The engine raises ``MeshRequestError`` for a request it cannot honor and
``MeshGenerationError`` for a mesh it cannot build.

The contract tests are in ``tests/ports/test_mesh.py``, for every registered engine and for a
plugin installed from a clone. They give ``cell_size`` one meaning. A uniform size gives the area
over the square of that size, within 10 % (row 182 of ``tests/TOLERANCES.md``).

The regular and catchment engines
---------------------------------

``regular`` (``engines/regular/``) builds square cells of one pitch, bit for bit the grid FloPy
builds, with row 0 in the north. The pitch is the DEM pitch or a larger :toml:`mesh.cell_size`,
and the engine refuses a smaller one. The size field shapes no cell, because the solver masks the
cells outside the domain. A river is rasterized, and a face family is a staircase.

``catchment`` (``engines/catchment/``) builds one polygon cell from the exterior ring of
``MeshRequest.catchment``, with no face. A hole of the outline is filled and a note gives its
area, because the water that falls in a hole still reaches the outlet. The center comes from
shapely's ``point_on_surface``, so it lies in the cell even when the vertex mean of a concave
catchment does not. The engine declares every line family in ``ignored_families``, so the planner
drops them with a named note and the default ``rivers = "cell"`` does not refuse the engine. It
refuses a size field and an input triangulation.

The triangle engine
-------------------

The code is in ``engines/triangle/``. The engine declares ``deterministic = False`` and
``needs_cache = True``, so only the product store makes a run repeatable, per project.

A generated triangulation
~~~~~~~~~~~~~~~~~~~~~~~~~

``gmsh_triangulation.py`` drives Gmsh. It nodes the family lines with the domain boundary in
shapely and gives Gmsh one point per vertex and one straight curve per segment. It embeds the
interior segments in the plane surface and meshes it under the size field of the request. The
developer key ``[mesh.triangle] algorithm`` picks the 2D algorithm, ``delaunay`` by default. The
engine imports ``gmsh`` only when it builds, because the ``mesh`` extra holds it.

:toml:`mesh.cell_size` is the side of the square that has the mean area of a cell, as for the
other engines. Gmsh reads a size as an edge length, so the adapter multiplies every size it hands
to Gmsh by a factor measured for the algorithm, in ``MESH_SIZE_PER_CELL_SIZE``. A triangle is then
about 1.5 times longer than ``cell_size``, and a uniform size gives A over its square in
triangles, to within 3 %. When the request has a size field, the adapter also resamples the
family lines at the field times the same factor, because Gmsh keeps every vertex it receives. The
corners of the barriers stay fixed vertices. A request with no size field keeps its lines, and
Gmsh cuts them at its own size.

A triangulation read
~~~~~~~~~~~~~~~~~~~~

With ``[mesh.triangle] path`` the engine reads a ``.msh`` file (format 2.2, ASCII). The outline of
the file is the domain, and the request carries no size field. The engine derives the families on
the mesh it read, from the named physical line groups or by matching the edges to the lines of the
request, and the report notes that the lines were not embedded. ``voronoi`` can start from the same
file.

Families and centers
~~~~~~~~~~~~~~~~~~~~

Each family line becomes one row per mesh edge. The triangle on the left of the oriented line is
``cell_a``, the one on the right is ``cell_b``, and ``-1`` marks the boundary of the domain. A
river is a ``cell`` family. Its chain is the triangles on one bank, in order, so their centers sit
beside the line, and the report gives the offset. The engine keeps the face rows of the river line
too.

The center of a triangle is the mean of its vertices. The line between two centers is not
perpendicular to their common edge, so MODFLOW 6 turns XT3D on by default for triangle cells, and
under Newton it can cycle on them (:doc:`/theory/solvers/xt3d-on-irregular-disv-meshes`). An
explicit :toml:`solver.modflow6.runtime.mf6_enable_xt3d` wins.

Limits
~~~~~~

- If the product store is deleted, the run meshes again. On one thread Gmsh redraws the same mesh,
  and the log warns that it may differ from the one the results came from.
- With lines in the request, the cell count stays above the integral of the field, because Gmsh
  adds cells around the lines it keeps. The excess is 11 % with one river in a graded square, 35 %
  on the dense network of the Flume, and 5 % without lines.

The Voronoi engine
------------------

The code is in ``engines/voronoi/``. The engine builds polygons whose faces lie on the
perpendicular bisector of two generators. It declares ``deterministic = True``, so a resume
rebuilds the mesh instead of reading a cache.

The mode
~~~~~~~~

``[mesh.voronoi] seeds`` picks the source of the generators. Unset, it is ``triangulation`` when
``[mesh.triangle] path`` is given and ``generated`` otherwise. The ``generated`` mode
(``from_seeds.py``) places the generators from the size field and the lines. The
``triangulation`` mode (``from_triangulation.py``) takes the vertices of the triangulation as
generators, with no constraint and no relaxation, so the cells are the dual of the triangles. A
face family is then a staircase of dual faces, and a QA note says that the faces do not follow
the lines. The zones and the lake cells come from the support and the polygon overlap.

The generated mode
~~~~~~~~~~~~~~~~~~

The engine first resamples the request lines at the local size, then runs six steps.

1. ``local_coords.py`` moves every coordinate to a frame centered on a multiple of 1 km, before
   any GEOS or scipy call. On Lambert-93 coordinates, two seeds a few meters apart can give
   identical cells.
2. ``constraints/plan.py`` runs the constraint steps in order. A river line gets one seed per
   vertex. A face line gets one pair of mirror seeds per segment, after Berge (2019), so that the
   two cells share a face. Then the conflicts between seeds are settled and the boundary gets its
   seeds. Lloyd never moves them, and the rank of a seed is its cell id.
3. ``free_seeds.py`` draws the free seeds, as many as the integral of ``1 / h^2`` over the domain.
   A PCG64 generator seeded with :toml:`mesh.seed` draws them and a Morton curve of a 1 m grid
   orders them, so one request gives one mesh.
4. ``lloyd.py`` moves each free seed to the centroid of its cell for the density ``h^-4``. A move
   into a Berge ball or a river Gabriel disk is projected out, or refused. The relaxation stops
   when the root mean square of the moves, as a share of the local size, falls under
   ``[mesh.voronoi] lloyd_tolerance`` (0.01), or after 25 iterations.
5. ``tessellation.py`` runs GEOS Voronoi and clips the cells to the domain. A piece that the clip
   cut away from its seed gets a boundary seed, for up to three rounds.
6. ``checks.py`` checks the mesh, then ``families.py`` builds the families.

A failed gate stops the build with ``MeshGenerationError``, which names at most 20 faults. The
gates check one cell per seed (G0), Berge definition 2 for the ball of each conformal vertex
(G1), each conformal segment as the shared face of its pair (G2), neighbor cells along a river
chain (G3), the sum of the cell areas against the domain at ``1e-9`` (G4), and no repeated vertex,
no cell under three vertices and no face under ``1e-6`` m (G5, G6).

A segment that is not conformal is not a fault. The QA ``families`` counts its cells as mixed.

Families
~~~~~~~~

When two face lines get in each other's way, the family of higher priority keeps its faces, in
this order: ``lakes``, ``barriers``, ``geology``, ``watershed_boundary``. A face line along an
earlier one, such as a cutoff wall on a lake shore, shares its faces as rows of both families.

A river wins over every face family but ``barriers`` and ``lakes``. The engine drops a chain seed
in the way of those two, so a river never enters a lake. Where a river crosses a face line, the
crossing becomes a short segment whose pair of seeds joins the river chain, a lateral offset away
from the river. The chain publishes the offset in ``CellChain.offset_m``, and the solver takes the
minimum of the surface elevation over such a cell.

Limits
~~~~~~

- On a graded size field of slope ``s``, a mesh whose cell has the size of its seed cannot keep
  the size ratio of two neighbors under ``(1 + s / 2) / (1 - s / 2)``, nor the seed offset under
  ``s / 4``. The QA reports both.
- On a graded field, Lloyd reaches its cap before its tolerance, and the quality is flat from
  about ten iterations. Three attempts to lower the median offset below its floor failed, so do
  not retry them. They were three quadrature points per fan triangle, a refinement of the seeds by
  levels (it breaks validation row 176) and a last pass that adds a seed where the dual triangle
  has a corner under 20 degrees.
- Where two face lines meet at an angle too small for the cell size, or a face line meets the
  boundary under 30 degrees, the circles merge and the segments next to the vertex are not
  conformal.
- A closed face line whose arms are narrower than the local cell cannot hold a pair of circles in
  each arm. So the planner smooths each lake shore at 0.6 of its largest shore cell, and arms
  narrower than twice that radius go.
- A hole of the domain that touches a ring at one point leaves a sliver that three rounds of
  boundary seeds do not close, and gate G4 stops the mesh. Separate such a hole from the ring
  first. The planner already drops any hole, lake or catchment smaller than one local cell squared.
- One request gives one mesh only for one platform, one GEOS version and one scipy version. A
  resume on another build can rebuild a different mesh, and the QA notes name the versions.
