Package: mesh
=============

.. include:: ../../../../../hydromodpy/mesh/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: mesh

Inside the package
------------------

A mesh is made in four steps, and each step has its own place in the package. The
planner of ``planning/`` reads the ``[mesh]`` table and the project inputs. It cleans the
input lines, smooths the catchment outline, computes the target cell size at every point,
and returns a ``MeshRequest``. The registry then finds the engine that ``[mesh] engine``
names. The engine of ``engines/<name>/`` builds the cells from the request, and it returns a
``PlanarCellMesh`` of ``planar/``. The solvers, the forcing, the property supports and the
exports all read this one object. Every engine declares in
``MeshEngineCapabilities.ignored_families`` the line families its mesh cannot follow. The
``catchment`` engine ignores them all, so the planner drops such a family with a named note
instead of failing on the default ``rivers = "cell"``.

The workflow step ``hydromodpy/workflow/steps/mesh.py`` runs these steps. It is the only
place that reads ``[mesh]`` and asks the product store of ``stored.py``. Every mesh is stored
under ``<project>/.hmp/products/``, and a later run reads the same cells back.
``needs_cache`` only marks an engine that cannot rebuild the same cells bit for bit.

There are two mesh objects. ``PlanarCellMesh`` is the mesh of a run. It holds the cells
with their centres and CRS, the line families (river chains, lake shores, barriers, sides),
the zones, the engine identity and the quality report, and it computes areas, edges and
neighbours once, on first use. ``HydroMesh`` is the plain geometry inside it, vertices and
blocks of cells after the meshio data model. Plots and exchange files use it, it accepts 3D
cells, and a block of polygons pads the rows of its smaller cells with ``-1``.

The imports go one way, from the request and the planar mesh up to the engines.
``request.py``, ``mesh_config.py`` and ``refinement_config.py`` import nothing else from
the package, and ``planar/`` imports only itself. ``io/`` and ``cells/`` read ``planar/``,
and ``cells/`` also reads ``request.py``. ``planning/`` reads the two config modules,
``request.py``, ``resample.py`` and ``planar/``, and it reads a triangulation file through
``io/msh.py``. The engines read ``request.py``, ``resample.py``, ``planar/`` and ``cells/``,
and never ``planning/`` or the workflow. Nothing in the package imports the workflow or
``hydromodpy/model/properties``, because both read the mesh. gmsh is imported in one place,
``engines/triangle/gmsh_triangulation.py``, so a regular or a Voronoi mesh never loads it.
``tests/unit/architecture/mesh_layout.yaml`` holds this order. No ``__init__.py``
re-exports a name, so a search for a name finds its file.

What only a solver reads lives with that solver. The ``sgrid`` table of the MODFLOW
backends, the vertical part of a regular grid and the MODFLOW 6 DISV arguments are in
``hydromodpy/solver/modflow_grid/``. The cells a lake owns, the faces of its cutoff wall and
the share of a reach among the cells are in ``hydromodpy/solver/modflow6/builders/``. The
package ``hydromodpy/model/properties`` samples its property supports on the cells of a
``PlanarCellMesh``.

The tests follow the layout of the code. A test file carries the name of the module it
tests and sits in the same folder under ``tests/unit/mesh/``, so ``planning/size_field.py``
is tested in ``tests/unit/mesh/planning/test_size_field.py``. A few small modules are tested
through the module that calls them. A test builds its grid, request and meshes with the
helpers of ``tests/_helpers/mesh_cases.py``. The port suite ``tests/ports/test_mesh.py``
holds what every engine must do, and the mesh regression of ``tests/regression/mesh/``
compares the meshes of fixed cases to committed references, so a change there must be
wanted. With ``HMP_REQUIRE_GMSH=1``, a missing gmsh fails the triangle tests instead of
skipping them. A new ``[mesh]`` key is a field of the Pydantic model of ``mesh_config.py``
with its description, and the parameter reference is built from it.

The developer pages :doc:`../mesh/mesh-pivot`, :doc:`../mesh/mesh-engines`,
:doc:`../mesh/triangle-engine` and :doc:`../mesh/voronoi-engine` cover the mesh objects,
the port, the two engines that need the most care, and the product store.
