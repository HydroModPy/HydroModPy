# mesh

This package turns a project into the cells that MODFLOW 6 and the other solvers compute on. It reads the catchment, the rivers, the lakes and the geology, returns one `PlanarCellMesh` that the rest of HydroModPy reads, and writes and reads the mesh in the usual exchange formats, so a mesh opens in ParaView or gmsh. It reads `core`, `schema` and `catchment`, and it also carries the mesh port, because its registry sits at the root of the package.

## The mesh port

An engine receives a `MeshRequest` (`request.py`), plain frozen data that holds the domain, the DEM grid, the cell size, the line families, the size field, a triangulation read from a file and, for a lumped engine only, the catchment outline. It reads no file and no config. `build(request)` returns a `PlanarCellMesh` (`planar/planar_cell_mesh.py`), which names its engine, its version and the hash of the request.

An engine declares `engine_id`, `engine_version`, `capabilities` and `build`. `MeshEngineCapabilities` (`port.py`) states what every mesh of the engine is: its cell types, structured, graded, exact faces, how a river becomes a chain, deterministic, cached, lumped, and the line families it ignores. Raise `engine_version` whenever the mesh of one request changes.

Four engines ship as dotted paths in `_BUILTIN_PATHS` of `registry.py`: `regular` (square cells on the DEM grid, the default), `triangle` (gmsh triangles that follow the lines), `voronoi` (polygons around generators) and `catchment` (the catchment as one polygon cell, holes filled, for a global model). A third party publishes an entry point named like its `engine_id` in the `hydromodpy.mesh.engine` group, and `[mesh] engine = "<id>"` selects it.

`[mesh] engine` is read by `check_registered_name`, which refuses a name nothing serves with the names served and the group. A request an engine cannot honour raises `MeshRequestError`, which names what it refuses. A family an engine ignores, written with a value other than `none`, is refused when the file is read. A solver that accepts `*planar` reads any planar engine that is not lumped, and `engine_accepted` of `registry.py` is that rule.

`tests/ports/test_mesh.py` runs on every engine the registry resolves, an installed one too, and holds the invariants a solver relies on.

## Where the rest is told

The page of the package in the developer docs gives the steps of a mesh, the two mesh objects and the rules between the folders. The developer pages of `docs/source/contribute/architecture/mesh/` cover the engines, and `docs/source/theory/mesh.md` explains the choice of an engine and of the cell size.
