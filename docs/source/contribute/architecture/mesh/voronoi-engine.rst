Voronoi engine
==============

.. rst-class:: lead

The ``voronoi`` engine builds polygons whose faces lie on the perpendicular bisector of the
two generators they separate. It places the generators itself, or takes the vertices of a
triangulation read from a file.

Code lives in ``hydromodpy/spatial/mesh/engines/voronoi/``. The engine declares
``deterministic = True`` and ``needs_cache = False``: one request gives one mesh on one
platform and one GEOS version, so a resume rebuilds the mesh instead of reading a cache.

Two modes
---------

``[mesh.voronoi] seeds`` picks the source of the generators. Unset, it is ``triangulation``
when ``[mesh.triangle] path`` is given and ``generated`` otherwise.

``generated``
   ``generated.py`` places the generators from the request: the size field, the river lines
   and the face lines. Every face follows its bisector, and a face line is followed by the
   face of a pair of mirror generators.

``triangulation``
   ``triangulation_seeds.py`` takes the vertices of the triangulation read as the generators.
   There is no constraint and no relaxation, so the cells are the dual of the triangles. A
   face family is the staircase of dual faces between the cells of its two sides
   (``dual_families.py``): the faces do not follow the lines, and the QA says so in a note.
   The engine declares exact faces, which a staircase is not, so this mode publishes no cell
   zone and no staircase for the lake shores: the zones and the lake cells keep coming from the
   support and the polygon overlap.

Both modes tessellate with GEOS in a local frame (below), identify the cell vertices by a
millimetre key and publish the same ``PlanarCellMesh``.

Generated mode
--------------

1. **Local frame** (``frame.py``). Every coordinate moves to a frame centred on a multiple of
   1 km near the domain, before any GEOS or scipy call: on Lambert-93 coordinates two seeds a
   few metres apart can give two identical cells. A point moved there and back is the same
   float.
2. **Constraint seeds** (``constraints.py``, ``mirror.py``). One seed per vertex of a river
   line, which makes the cells of its chain. One pair of mirror seeds per segment of a face
   line, placed after Berge (2019) so that the two cells share a face on the segment. Seeds on
   the domain boundary, between its corners. The constraint seeds are fixed: Lloyd never moves
   them, and their rank is their cell id.
3. **Free seeds** (``free_seeds.py``). Their number is the integral of ``1 / h^2`` over the
   domain, so it does not depend on the seed. They are drawn by rejection from a PCG64
   generator seeded with ``[mesh] seed``, and sorted along a Morton curve of a 1 m grid.
4. **Lloyd relaxation** (``lloyd.py``). Each free seed moves to the centroid of its cell for
   the density ``h^-4``, with one quadrature point per fan triangle. A move that would enter
   a Berge ball or a Gabriel disk of a river link is projected out of it, or refused. The
   relaxation stops when the largest move falls under ``[mesh.voronoi] lloyd_tolerance`` or
   after 25 iterations.
5. **Tessellation** (``tessellation.py``). GEOS Voronoi, clipped to the domain. A piece of a
   cell that the clip cut away from its seed gets a boundary seed, up to three rounds.
6. **Gates** (``gates.py``), then the families (``line_families.py``).

The planner has already resampled the lines at the local size. The engine runs
``resample_families`` on its request once more, so a request built by hand gets the crossings
as vertices of both lines and one vertex per local cell; on a planned request the second pass
moves a vertex by a few millimetres at most.

Where a river crosses a face line, the river wins. The crossing becomes a short segment whose
pair of seeds joins the river chain, a lateral offset away from the river. The offset is
published in ``CellChain.offset_m`` and the solver takes the minimum of the surface elevation
over such a cell.

Gates
-----

A gate that fails stops the build with ``MeshGenerationError``. The message names at most 20
faults, in Lambert-93 coordinates, and the total of each gate. There is no warning.

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

A segment that is not conformal (a merged sector, a river crossing, a contact that yielded to
a family of higher priority) is declared, not a fault: its cells are counted as mixed in the
QA ``families``.

Families
--------

The river lines give the ``rivers`` chains. The face lines give one family each, ordered by
priority when two of them get in each other's way: ``lakes``, ``geology``, ``barriers``, then
``watershed_boundary``. A river always wins. The boundary faces on the four sides of the
vertex box are the families ``boundary:<side>``. The zone of a cell comes from the geology
pairs and spreads through the cells until a geology face stops it; a cell that two zones
reach, or that a yielded contact crosses, has zone ``-1``.

Quality report
--------------

The common ``MeshQA`` fields are described in :doc:`mesh-pivot`. The engine adds to
``extras``: the ``lloyd_*`` numbers (iterations, cap, whether the tolerance was reached, the
median, 99th percentile and largest move), the seed counts by role (``n_seeds_*``), the
boundary seeds the tessellation added, the origin of the local frame and the gate counts. It
adds to each face family ``mirror_pairs``, ``conformal_length_share``, ``merged_circles``,
``yielded_segments`` and the other counts of the constraint stage, and to ``rivers`` the
crossings and their largest offset. The ``notes`` name the library builds the mesh is
reproducible with.

Limits
------

- **Size ratio.** A graded Voronoi mesh whose cell has the size of its seed cannot keep the
  size ratio between two neighbours under ``(1 + s / 2) / (1 - s / 2)`` for a size field of
  slope ``s``, nor the offset between a seed and the centroid of its cell under ``s / 4``
  along the gradient. The QA reports both.
- **Lloyd.** The relaxation reaches its cap before its tolerance on a graded field. The
  quality is flat from about ten iterations; ``lloyd_converged`` says which end stopped it.
- **Acute sectors.** Where two face lines meet at an angle too small for the cell size, or a
  face line meets the boundary under 30 degrees, the circles merge and the segments next to
  the vertex are not conformal.
- **Narrow arms.** A closed face line whose arms are narrower than the local cell (a lake
  with long inlets sampled at 80 m cells) cannot hold a pair of circles in each arm. The
  segments in the arm are yielded, the ring is open, and ``conformal_length_share`` of the
  family drops (0.58 on the two-lake Cheze reservoir). The lake cells are then those the lake
  polygon overlaps, each with its overlap area, as on a mesh without shore faces.
- **Touching rings.** A hole of the domain that touches the outer ring or another hole at a
  single point splits the cell that spans the touching point. The piece beyond it gets a
  boundary seed, but the bisector of the two seeds always leaves a sliver at the touching
  point, so three rounds of boundary seeds do not close the area and gate G4 stops the mesh.
  Holes smaller than one local cell squared are dropped by the planner, which removes most
  of these cases; a larger hole that touches a ring must be separated in the domain first.
- **Holes.** The planner drops a hole of the domain, a lake or the catchment that is smaller
  than one local cell squared, for every engine, and says how many in the log.
- **Fewer cells than the dual of a triangulation.** At equal size parameters the generated mode
  makes about half the cells the dual of a triangulation made: 826 became 344 cells on one
  catchment and 303 became 144 on another. The cause is not isolated. A comparison at equal cost
  reads the cell count of the mesh, which the QA reports, and does not infer it from
  ``[mesh] cell_size`` (:ref:`mesh-budget`).
- **Reproducibility.** The mesh is reproducible for one platform, one GEOS and one scipy
  version. A resume on another build can rebuild a different mesh; the QA notes name the
  versions.

See also
--------

- :doc:`mesh-pivot` for the ``PlanarCellMesh`` this engine returns.
- :doc:`mesh-engines` for the port, the planner and the other engines.
- :doc:`/theory/mesh` for the choice of a Voronoi mesh.
