# spatial/mesh

Package map of the mesh layer. The package turns a project into the cells a solver
reads, and defines the one mesh object every consumer shares.

## What the package owns

- `PlanarCellMesh`, the mesh every solver, forcing and export reads.
- `MeshEngine`, the port a mesh generator implements, and its registry.
- Three built-in engines: `regular`, `triangle`, `voronoi`.
- The planner that turns `[mesh]` and the project inputs into a `MeshRequest`.
- The cache of meshes an engine cannot rebuild bit for bit.
- The cell operations consumers share (families, location, flow barriers).
- `HydroMesh`, the exchange format for plotting, VTU and meshio.

## Data flow

```text
[mesh] + project inputs
    |  planning.plan_mesh_request
    v
MeshRequest                 request.py, plain frozen data
    |  engines/<id>/ build()
    v
PlanarCellMesh              model/
    |  workflow/steps/mesh.py (cache, setup.cell_mesh)
    v
solvers, forcing, supports  ->  Zarr store `mesh/` group, geopackage export
```

An engine reads no file and no config. The workflow step is the only place that reads
`[mesh]`, asks the cache and hands the cell mesh to the rest of the run.

## Layout

| Path | Role |
|------|------|
| `model/` | `PlanarCellMesh`, `HydroMesh`, `CellType`, `DerivedGeometry`, `MeshQA`, `RegularGrid` |
| `port.py` | `MeshEngine` protocol and `MeshEngineCapabilities` |
| `registry.py` | Engine id to class, plus the `hydromodpy.mesh.engine` entry-point group |
| `request.py` | `MeshRequest`, `LineFamilySpec`, `RasterGridSpec`, `SizeField` |
| `planning/` | `plan_mesh_request`: from the project to a request, after the catchment smoothing (`catchment_outline.py`) and the geometry cleanup (`cleanup.py`) |
| `sizing/` | Size field of the graded engines, and its terms on the gaps between face lines (`gap.py`) |
| `refinement/` | Models of the lake refinement and the refinement zones, and the fields a zone reads (`height_above_stream.py`, `run_fields.py`) |
| `config/` | The `[mesh]` Pydantic models (`mesh.py`) |
| `engines/regular/` | Square cells of the DEM grid, bit for bit the FloPy grid |
| `engines/triangle/` | Constrained Delaunay triangles from gmsh (`gmsh_cdt.py`), or a `.msh` file |
| `engines/voronoi/` | Voronoi cells from generated seeds, mirror pairs, Lloyd, gates |
| `cache.py` | Mesh cache under `<project>/.hmp/mesh_cache/` |
| `ops/` | Shared cell helpers: families, `locate_cells`, flow barriers, chains, zonal stats |
| `forcing/` | Rasters, NetCDF and stations sampled on the cell centres, nearest or by shared area (`_area.py`), and the interpolation of values onto them (`spatial_interpolation.py`) |
| `adapters/` | `HydroMesh` to and from meshio, FloPy DISV, field meshes; `cell_mesh.py` for a regular grid |
| `io/` | VTU read and write |
| `plotting.py` | `plot_cell_values` for quick QA plots |
| `structured_grid/` | Structured grid of the regular engine, the `sgrid` table (top sampling) of the MODFLOW backends |
| `gmsh_grid/` | Readers of `.msh` files and frozen mesh bundles, `GmshPlanarMesh2D` |

Each of `structured_grid/` and `gmsh_grid/` has its own README.

## Layering rules

- `engines/` never import `workflow/`. They read the request, not the config.
- Gmsh is imported on demand, so the `regular` engine never loads it.
- Consumers read the cell mesh. They never read an engine-specific support.

## Add an engine

An engine is a class with `engine_id`, `engine_version`, `capabilities` and a
`build(request)` method that returns a `PlanarCellMesh`. It joins the registry through
the `hydromodpy.mesh.engine` entry point, then `[mesh] engine = "<id>"` names it. Bump
`engine_version` whenever the mesh returned for one request changes.

Full recipe and capability table: `docs/source/contribute/architecture/mesh/mesh-engines.rst`.
Contract test: `tests/contract/test_mesh_engine_contract.py`.

## Documentation

All under `docs/source/contribute/architecture/mesh/`:

- `mesh-pivot.rst`: `HydroMesh`, `PlanarCellMesh`, line families, consumers.
- `mesh-engines.rst`: port, registry, request, planner, cache, how to add an engine.
- `triangle-engine.rst`: the gmsh triangle engine and its cache.
- `voronoi-engine.rst`: generated generators, mirror pairs, Lloyd, gates, limits.

Scientific choice of an engine and the size field: `docs/source/theory/mesh.md`.
