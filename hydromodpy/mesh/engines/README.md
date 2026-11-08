# mesh/engines

This folder holds the mesh engines, and this file is the contract of the mesh port. An engine is a class with
`engine_id`, `engine_version`, `capabilities` and one method, `build(request)`. It reads a `MeshRequest`
(`mesh/request.py`) and returns a `PlanarCellMesh` (`mesh/planar/planar_cell_mesh.py`). It reads no file and no
config, because the request holds the domain, the DEM grid, the cell size, the line families, the size field, a
triangulation read from a file and, for a lumped engine, the catchment outline. The mesh names its engine, its version
and the hash of the request, and `engine_version` changes whenever the mesh of one request changes.

`MeshEngineCapabilities` (`mesh/port.py`) states what every mesh of the engine is: its cell types, structured, graded,
exact faces, how a river becomes a chain, deterministic, cached, and lumped. A lumped engine meshes the catchment as
one cell. The planner gives it `MeshRequest.catchment` and gives no other engine that member, so the hash of every
other request is unchanged. A solver that accepts `*planar` reads any engine of planar cells that is not lumped, and
`engine_accepted` of `mesh/registry.py` is that rule. A request an engine cannot honor raises `MeshRequestError`, which
names what it refuses.

Four engines ship. `regular` gives square cells on the DEM grid. `triangle` gives gmsh triangles that follow the lines.
`voronoi` gives polygons around generators. `catchment` gives the catchment as one polygon cell, with its holes filled,
and refuses lines, a size field and a triangulation. A third party adds an engine on the entry point group
`hydromodpy.mesh.engine`, named like its `engine_id`, and `tests/contract/test_mesh_engine_contract.py` runs on every
engine the registry resolves.
