Voronoi engine
==============

.. rst-class:: lead

The ``voronoi`` engine builds polygons whose faces lie on the perpendicular bisector of the
two generators they separate. It places the generators itself, or takes the vertices of a
triangulation read from a file.

The code lives in ``hydromodpy/spatial/mesh/engines/voronoi/``. The engine declares
``deterministic = True`` and ``needs_cache = False``, so a resume rebuilds the mesh instead of
reading a cache.

Two modes
---------

``[mesh.voronoi] seeds`` picks the source of the generators. Unset, it is ``triangulation``
when ``[mesh.triangle] path`` is given and ``generated`` otherwise.

``generated``
   ``generated.py`` places the generators from the size field, the river lines and the face
   lines.

``triangulation``
   ``triangulation_seeds.py`` takes the vertices of the triangulation as generators, with no
   constraint and no relaxation, so the cells are the dual of the triangles. A face family is
   the staircase of dual faces between its two sides (``dual_families.py``), and a QA note says
   that the faces do not follow the lines. The engine declares exact faces and a staircase is
   not exact, so this mode publishes no cell zone and no staircase for the lake shores. The
   zones and the lake cells come from the support and the polygon overlap.

Generated mode
--------------

The engine first resamples the request lines at the local size. Then it runs six steps.

1. ``frame.py`` moves every coordinate to a frame centred on a multiple of 1 km, before any
   GEOS or scipy call. On Lambert-93 coordinates, two seeds a few metres apart can give
   identical cells.
2. ``constraints.py`` and ``mirror.py`` place the constraint seeds. A river line gets one seed
   per vertex. A face line gets one pair of mirror seeds per segment, after Berge (2019), so
   that the two cells share a face. The boundary gets seeds between its corners. Lloyd never
   moves them, and the rank of a seed is its cell id.
3. ``free_seeds.py`` draws the free seeds. The total number of seeds is the integral of
   ``1 / h^2`` over the domain, so the seed does not change it. A PCG64 generator seeded with
   ``[mesh] seed`` draws them, and a Morton curve of a 1 m grid orders them.
4. ``lloyd.py`` moves each free seed to the centroid of its cell for the density ``h^-4``, with
   one quadrature point per fan triangle. A move into a Berge ball or a river Gabriel disk is
   projected out, or refused. The relaxation stops when the root mean square of the moves, as a
   share of the local size, falls under ``[mesh.voronoi] lloyd_tolerance`` (default 0.01), or
   after 25 iterations.
5. ``tessellation.py`` runs GEOS Voronoi and clips the cells to the domain. A piece that the
   clip cut away from its seed gets a boundary seed, for up to three rounds.
6. ``gates.py`` checks the mesh, then ``line_families.py`` builds the families.

Gates
-----

A failed gate stops the build with ``MeshGenerationError``. The message names at most 20
faults, in Lambert-93 coordinates, and the total of each gate.

.. list-table::
   :header-rows: 1
   :widths: 10 90

   * - Gate
     - Checks
   * - G0
     - One cell per seed, of positive area, covering its seed.
   * - G1
     - Berge definition 2: no seed inside the ball of a conformal vertex but the seeds of its
       own sphere.
   * - G2
     - Each conformal segment is the face shared by the cells of its pair, with its two nodes
       within 1 mm of the segment ends.
   * - G3
     - Two distinct consecutive cells of a river chain are neighbours.
   * - G4
     - The cell areas add up to the domain area at ``1e-9``.
   * - G5
     - No vertex repeated in a cell, at least three vertices per cell.
   * - G6
     - No face shorter than ``1e-6`` m.

A segment that is not conformal is not a fault. A merged sector, a river crossing and a contact
that yielded to a family of higher priority make such segments, and the QA ``families`` counts
their cells as mixed.

Families
--------

The river lines give the ``rivers`` chains, and each face line gives its own family. When two
face lines get in each other's way, the family of higher priority keeps its faces, in this
order: ``lakes``, ``barriers``, ``geology``, ``watershed_boundary``. A face line along an
earlier one, such as a lake cutoff wall on the shore, shares its faces as rows of both
families.

A river wins over every face family but ``barriers`` and ``lakes``. The engine drops a chain
seed in the way of those two. The river then passes through the cell of the nearest mirror seed,
on the river's side of a lake shore. A shore seed across the shore from a chain link yields, so a
river never enters a lake. Where a river crosses a face line, the crossing becomes a short
segment whose pair of seeds joins the river chain, a lateral offset away from the river. The
chain publishes the offset in ``CellChain.offset_m``, and the solver takes the minimum of the
surface elevation over such a cell.

The four sides of the vertex box are the families ``boundary:<side>``. The zone of a cell comes
from the geology pairs and spreads until a geology face stops it. A cell that two zones reach,
or that a yielded contact crosses, has zone ``-1``.

Quality report
--------------

:doc:`mesh-pivot` describes the common ``MeshQA`` fields. The engine adds to ``extras`` the
``lloyd_*`` numbers (iterations, cap, whether the tolerance was reached, and the root mean
square ``lloyd_move_rms``, the median, the 99th percentile and the largest move
``lloyd_move_max``), the seed counts by role (``n_seeds_*``), the boundary seeds the
tessellation added, the origin of the local frame and the gate counts. Each face family gets
``mirror_pairs``, ``conformal_length_share``, ``merged_circles``, ``yielded_segments`` and the
other counts of the constraint stage. ``rivers`` gets the crossings and their largest offset.

Limits
------

- On a graded size field of slope ``s``, a mesh whose cell has the size of its seed cannot keep
  the size ratio between two neighbours under ``(1 + s / 2) / (1 - s / 2)``. It cannot keep the
  seed offset under ``s / 4`` along the gradient either. The QA reports both, and a unit test
  holds the median offset under ``s / 4``.
- On a graded field, the Lloyd relaxation reaches its cap before its tolerance, and the quality
  is flat from about ten iterations. On a catchment of 23 148 cells, the root mean square stays
  at 0.0100 after 25 iterations. The median offset ``center_offset`` is 0.095 of the cell side,
  the floor of ``s / 4``. Three attempts to lower it fail. Three quadrature points per
  fan triangle give 0.115. A refinement of the seeds by levels adds 9 to 14 per cent of cells
  and breaks the validation row 176 of the generated variant. A last pass that adds a seed
  where the dual triangle has a corner under 20 degrees changes nothing.
- Where two face lines meet at an angle too small for the cell size, or a face line meets the
  boundary under 30 degrees, the circles merge and the segments next to the vertex are not
  conformal.
- A closed face line whose arms are narrower than the local cell cannot hold a pair of circles
  in each arm. So the planner smooths each lake shore at 0.6 of its largest shore cell. Arms,
  necks and spits narrower than twice that radius go. The rivers stop half a river cell off the
  lakes, and a wall wing shorter than half the local cell size where it leaves the shore goes
  too. The smoothing takes one radius per lake, so an arm that the gap term refines can still
  be left out of the followed shore. The notes give the area each lake left out and took in. The
  lake owns the regions its smoothed shore encloses and the cells outside them that it covers for
  more than half. If the faces leave a shore open, the notes say so, and the lake takes the cells
  its polygon overlaps.
- A hole of the domain that touches a ring at one point leaves a sliver that three rounds of
  boundary seeds do not close, and gate G4 stops the mesh. Such a hole must be separated from
  the ring first. The planner drops any hole, lake or catchment smaller than one local
  cell squared, for every engine (:doc:`mesh-engines`), which removes most of these cases.
- At equal size parameters, the generated mode makes about half the cells of the dual of a
  triangulation: 826 become 344 cells on one catchment and 303 become 144 on another. The dual
  keeps one generator per vertex of the Gmsh triangulation. Gmsh reads the size as an edge length,
  so it makes about 2.6 A/ℓ² triangles and 1.3 A/ℓ² vertices, and every vertex of the outline is
  a generator too. The generated mode gives A/ℓ² cells by construction, which is the definition
  of ``cell_size`` (:ref:`mesh-budget`). A comparison at equal cost uses the cell count of the QA.
- One request gives one mesh only for one platform, one GEOS version and one scipy version. A
  resume on another build can rebuild a different mesh, and the QA notes name the versions.

See also
--------

- :doc:`mesh-pivot` for the ``PlanarCellMesh`` this engine returns.
- :doc:`mesh-engines` for the port, the planner and the other engines.
- :doc:`/theory/mesh` for the choice of a Voronoi mesh.
