Triangle engine
===============

.. rst-class:: lead

The ``triangle`` engine builds constrained Delaunay triangles with Gmsh, or reads the
triangulation of a ``.msh`` file. A line of a face family lies on mesh edges, so the faces
follow the geology contacts and the lake shores exactly.

The code lives in ``hydromodpy/spatial/mesh/engines/triangle/``. The engine declares
``deterministic = False`` and ``needs_cache = True``. Gmsh does not give the same
triangulation twice, so the engine builds the mesh of a request once and keeps it
(:doc:`mesh-engines`).

A generated triangulation
-------------------------

``gmsh_cdt.py`` drives Gmsh. It nodes the family lines with the domain boundary in shapely and
gives Gmsh one point per vertex and one straight curve per segment. It embeds the interior
segments in the plane surface and meshes it under the size field of the request. The developer
key ``[mesh.triangle] algorithm`` picks the 2D algorithm (``delaunay`` by default). Building
needs the ``mesh`` extra, because the engine imports ``gmsh`` only when it builds the mesh.

``[mesh] cell_size`` is the side of the square that has the mean area of a cell, as for the other
engines. Gmsh reads a size as an edge length, so the adapter multiplies every size it hands to
Gmsh by a factor measured for the algorithm: 1.62 for ``delaunay``, 1.58 for ``meshadapt`` and 1.52
for ``frontal`` (``MESH_SIZE_PER_CELL_SIZE`` in ``gmsh_cdt.py``). A triangle is then about 1.5 times
longer than ``cell_size``, and a uniform size gives A over its square in triangles, to within 3 %.
When the request has a size field, the adapter also resamples the family lines at the field times
the same factor, because Gmsh keeps every vertex it receives. The corners of the barriers stay
fixed vertices. A request with no size field keeps its lines, and Gmsh cuts them at its own size.
The engine version, 1.2.0, is part of the cache key, so an older cached mesh is rebuilt.

A triangulation read
--------------------

With ``[mesh.triangle] path`` the engine reads a ``.msh`` file (format 2.2, ASCII) instead of
generating one. The outline of the file is the domain, and the request carries no size field.
The engine derives the families on the mesh it read. It uses the named physical line groups of
the file, or else it matches the edges to the lines of the request. The report notes that the
family lines were not embedded. The ``voronoi`` engine can start from the same file
(:doc:`voronoi-engine`).

Families
--------

Each family line becomes one row per mesh edge. The triangle on the left of the oriented line
is ``cell_a``, the one on the right is ``cell_b``, and ``-1`` marks the boundary of the domain.
The zone on each side of a contact comes from the request. The river is a ``cell`` family. Its
chain is the triangles on one bank of the line, in order, so their centres sit beside the
line, and the report gives the offset. The engine keeps the face rows of the river line too.
The four sides of the domain are the face families ``boundary:<side>``.

The centre of a triangle is the mean of its vertices (``center_kind = "vertex_mean"``). The
line between two centres is not perpendicular to their common edge, so MODFLOW 6 turns XT3D on
by default for triangle cells. An explicit ``mf6_enable_xt3d`` wins
(:doc:`/theory/solvers/xt3d-on-irregular-disv-meshes`).

The cache
---------

A mesh read from a file is cached like a generated one. If ``.hmp/mesh_cache/`` is deleted, a
resume meshes again, and the log says that the new mesh may differ from the one the results
were computed on. Then ``restart_from`` refuses.

Limits
------

- Only the cache makes a run repeatable, and the cache is per project.
- Gmsh takes the size field as a target. The report gives the size it reaches.
- With lines in the request, the count stays above the integral of the field, because Gmsh adds
  cells around the lines it keeps, at bends and at confluences. The excess is 11 % with one river
  in a graded square, and 35 % on the dense network of the Flume. Without lines, the same field
  gives 1.05.
- Under Newton, XT3D can cycle on these triangles. The cause and the way out are on
  :doc:`/theory/solvers/xt3d-on-irregular-disv-meshes`.

See also
--------

- :doc:`mesh-engines` for the port, the planner and the cache.
- :doc:`mesh-pivot` for the cell mesh the engine returns.
- :doc:`/theory/mesh` for the size field and the choice of an engine.
