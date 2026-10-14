Triangle engine
===============

.. rst-class:: lead

The ``triangle`` engine builds constrained Delaunay triangles with Gmsh, or reads the
triangulation of a ``.msh`` file. A line of a face family lies on mesh edges, so the faces
follow the geology contacts and the lake shores exactly.

Code lives in ``hydromodpy/spatial/mesh/engines/triangle/``. The engine declares
``deterministic = False`` and ``needs_cache = True``: Gmsh does not give the same
triangulation twice, so the mesh of a request is built once and kept
(:doc:`mesh-engines`).

A generated triangulation
-------------------------

``gmsh_cdt.py`` is the driver. It nodes the family lines with the domain boundary in
shapely, hands Gmsh one point per vertex and one straight curve per segment, embeds the
interior segments in the plane surface and meshes it under the size field of the request.
Coordinates move to an origin rounded to the kilometre while Gmsh runs, so its tolerances act
on small numbers. The 2D algorithm is the developer key ``[mesh.triangle] algorithm``
(``delaunay`` by default). ``gmsh`` is imported when the mesh is built and not when the engine
is resolved: building needs the ``mesh`` extra, listing the engines does not.

A triangulation read
--------------------

With ``[mesh.triangle] path`` the engine reads a ``.msh`` file (format 2.2, ASCII) instead of
generating one. The request then carries no size field, its lines are the raw lines of the
planner, and the outline of the file is the domain. The families are derived on the mesh read:
from the named physical line groups of the file when it has them, else by matching its edges
to the lines of the request. The report notes that the family lines were not embedded. The
``voronoi`` engine can start from the same file (:doc:`voronoi-engine`).

Families
--------

Each family line becomes a row per mesh edge, with the triangle on the left of the oriented
line as ``cell_a`` and the one on the right as ``cell_b`` (``-1`` on the boundary of the
domain). The zone on each side of a contact is read from the request. The river is a ``cell``
family, and the engine derives its chain from the faces: the triangles on one bank of the
line, in order. A river cell has its centre beside the line, and the report gives the offset.
The face rows of the river line are kept as well. The four sides of the domain are the face
families ``boundary:<side>``.

The centre of a triangle is the mean of its vertices (``center_kind = "vertex_mean"``). The
connection between two centres is not perpendicular to their common edge, and MODFLOW 6 turns
XT3D on by default for triangle cells, and an explicit ``mf6_enable_xt3d`` wins (:doc:`/theory/solvers/xt3d-on-irregular-disv-meshes`).

The cache
---------

The cache key names the request hash, the engine and its version and the builds of Gmsh,
shapely, GEOS and scipy. A mesh read from a file is cached like a generated one. Deleting
``.hmp/mesh_cache/`` makes a resume mesh again, with a log line that says the new mesh may
differ from the one the results were computed on, and makes ``restart_from`` refuse.

Limits
------

- **Not reproducible.** Two builds of one request give two meshes. Only the cache makes a run
  repeatable, and it is per project.
- **One bank.** A river is the chain of triangles on one side of its line, so the centres sit
  beside the line.
- **A size, not a promise.** Gmsh takes the size field as a target. The report gives the size
  actually reached.

See also
--------

- :doc:`mesh-engines` for the port, the planner and the cache.
- :doc:`mesh-pivot` for the cell mesh the engine returns.
- :doc:`/theory/mesh` for the size field and the choice of an engine.
