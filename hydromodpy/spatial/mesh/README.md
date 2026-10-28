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
- The exchange formats: VTU, the meshio bridge, the `.msh` files of gmsh and the mesh
  bundles.

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
| `mesh_config.py` | The `[mesh]` Pydantic models |
| `refinement_config.py` | The `[mesh.lake_refinement]` and `[[mesh.refinement_zone]]` Pydantic models |
| `model/` | `PlanarCellMesh`, `HydroMesh`, `CellType`, `DerivedGeometry`, `MeshQA`, `RegularGrid` and its cell mesh (`regular_grid.py`) |
| `port.py` | `MeshEngine` protocol and `MeshEngineCapabilities` |
| `registry.py` | Engine id to class, plus the `hydromodpy.mesh.engine` entry-point group |
| `request.py` | `MeshRequest`, `LineFamilySpec`, `RasterGridSpec`, `SizeField` |
| `resample.py` | The lines resampled at the local cell size, read by the planner and the engines |
| `planning/` | `plan_mesh_request`: from the project to a request, after the catchment smoothing (`catchment_outline.py`) and the geometry cleanup (`cleanup.py`), with the line families in `families.py` and the size terms in `size_terms.py`; `smoothed_catchment` gives the outline the mesh followed, kept on `PlanarCellMesh.smoothed_catchment`. The size field of the graded engines (`size_field.py`) and its terms on the gaps between face lines (`gap_size.py`), the refinement zones and the fields a zone reads (`refinement.py`, `height_above_stream.py`), the size rules of the lake walls, sills and outlet disk (`lake_structures.py`) |
| `engines/face_families.py` | The face family rows the engines share: oriented edges, the family table, the zones cut by the lines |
| `engines/regular/` | Square cells of the DEM grid, bit for bit the FloPy grid |
| `engines/triangle/` | Constrained Delaunay triangles from gmsh (`gmsh_cdt.py`), or a `.msh` file and its physical groups (`msh_groups.py`) |
| `engines/voronoi/` | Voronoi cells from generated seeds (`generated.py`, the constraint seeds in `constraints/`), Lloyd, gates, or the dual of a read triangulation (`from_triangulation.py`) |
| `cache.py` | Mesh cache under `<project>/.hmp/mesh_cache/` |
| `ops/` | Shared cell helpers: families, `locate_cells`, flow barriers, chains, zonal stats |
| `io/` | The exchange formats, one module per format: `vtu.py`, `meshio_bridge.py`, `msh.py`, `bundle.py` |

No `__init__.py` re-exports a name: each name is imported from the module that defines it.

## Exchange formats

`io/` depends on `model/` only. It reads and writes files and generates no mesh: the engines
in `engines/` write their cells through the `PlanarCellMesh` model.

- `vtu.py` writes and reads a `HydroMesh` as VTU, in 2D or 3D, with values of the whole mesh in
  its `FieldData`. A planar mesh reads back planar. `hmp export` writes its VTU files through it.
- `meshio_bridge.py` turns a `HydroMesh` into a meshio mesh and back, mixed and 3D cells
  included. A Voronoi mesh goes to meshio as runs of polygons of one arity, in its cell order.
- `msh.py` reads a `.msh` file into `GmshMeshData` (cells, CRS from the `.prj` file next to
  it, named line groups) or into a `HydroMesh` (`read_msh`), and writes one (`write_msh`). It
  reads through meshio and falls back on a small reader of the ASCII 2.2 format. The planner
  reads `[mesh.triangle] path` through it, once.
- `bundle.py` loads a mesh bundle (CSV files plus a `metadata.json`) whole, cells of any arity
  and geology fields included, and reads its triangles as a `PlanarCellMesh`, with the river and
  outer-side face families the solvers read (`cell_mesh_from_bundle`). No mesh engine writes a
  bundle any more. The reader stays for the committed bundles of the Boussinesq validation
  cases, which Boussinesq reads through `output_exchange_bundle_dir`. Meshes made for a run are
  read from the cell mesh stored with the run, not from a bundle.

What only a solver reads lives with the solver. The `sgrid` table of the MODFLOW backends
(`sgrid_config.py`), the vertical part of a regular grid (`StructuredGridBuilder` in
`discretization_spatial.py`) and the MODFLOW 6 DISV arguments (`to_flopy_disv_args` in
`solver_mesh.py`) are in `hydromodpy/solver/modflow_grid/`. The cells a lake owns, the faces of
its cutoff wall (`_lake_geometry.py`) and the share of a reach among the cells
(`_sfr_network.py`) are in `hydromodpy/solver/modflow6/builders/`. In the same way, the
field meshes, `GmshPlanarMesh2D` among them, their conversion to and from a `HydroMesh`
(`field_mesh_adapter.py`) and `plot_cell_values` (`plotting.py`) live in the `meshes/` folder
of the field package.

## Layering rules

- `engines/` never import `workflow/`. They read the request, not the config.
- Gmsh is imported on demand, so the `regular` engine never loads it.
- Consumers read the cell mesh. They never read an engine-specific support.
- Nothing in this package imports the field package. The field package reads the mesh.

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
