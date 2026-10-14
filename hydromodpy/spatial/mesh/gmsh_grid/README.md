# gmsh_grid package

This package reads Gmsh meshes and frozen catchment mesh bundles. It does not
generate meshes: the mesh engines live in `engines/` and write their cells
through the `PlanarCellMesh` model.

## Modules

- `gmsh_reader.py` reads a `.msh` file (and writes one) into a stable
  in-memory payload, `GmshMeshData`.
- `gmsh_planar_mesh.py` exposes a 2D planar mesh, `GmshPlanarMesh2D`, and
  converts it to and from the `HydroMesh`.
- `exchange_api.py` is the small public I/O surface: load and save a planar
  mesh, and move a `HydroMesh` through a VTU file.
- `catchment_mesh_bundle_reader.py` loads a frozen bundle (CSV files plus a
  `metadata.json`). A bundle is the input of the Boussinesq validation
  cases and of the mesh bundle viewer.
- `bundle_cell_mesh.py` reads the triangles of a bundle as a `PlanarCellMesh`,
  with the river and outer-side face families the solvers read.
- `_deps.py` imports the optional `gmsh` and `meshio` dependencies on demand.

## Reading order

1. `README.md`
2. `__init__.py`
3. `gmsh_reader.py`
4. `gmsh_planar_mesh.py`
5. `exchange_api.py`
6. `catchment_mesh_bundle_reader.py`
7. `bundle_cell_mesh.py`

## Scope

The package is small on purpose. It keeps simple and auditable readers and
stable exchange formats. Meshes made for a run are read from the cell mesh
stored with the run, not from a bundle.
