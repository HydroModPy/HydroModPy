# mesh

This package turns a project into the cells that MODFLOW 6 and the other solvers compute on.
It reads the catchment, the rivers, the lakes and the geology of the project, and it returns
one mesh object that the rest of HydroModPy reads. It also writes and reads the mesh in the
usual exchange formats, so a mesh opens in ParaView or gmsh.

## How a mesh is made

A mesh is made in four steps, and each step has its own place in the package.

1. The planner in `planning/` reads the `[mesh]` table and the project inputs. It cleans the
   input lines, smooths the catchment outline and computes the target cell size at every
   point. It returns a `MeshRequest` (`request.py`), plain frozen data that holds everything
   an engine needs. For a lumped engine, which meshes the catchment as one cell, the request
   also carries the catchment outline, and for no other engine.
   Every engine declares in `MeshEngineCapabilities.ignored_families` the line families its
   mesh cannot follow. The `catchment` engine ignores them all, so the planner drops such a
   family with a named note instead of failing on the default `rivers = "cell"`, and a family
   an engine ignores, written with a value other than `none`, is refused when the file is read.
2. The registry (`registry.py`) finds the engine that `[mesh] engine` names.
3. The engine in `engines/<name>/` builds the cells from the request. It reads no file and
   no config.
4. The engine returns a `PlanarCellMesh` (`planar/`). The solvers, the forcing, the property
   supports and the exports all read this one object.

```text
[mesh] table + project inputs
        |
        |  planning/plan.py         clean the lines, smooth the outline, size the cells
        v
   MeshRequest                      request.py
        |
        |  registry.py              pick the engine
        v
   engines/regular, triangle, voronoi or catchment
        |
        v
   PlanarCellMesh                   planar/
        |
        +-->  solvers, forcing, property supports
        +-->  run store (results/) and exchange files (io/)
```

The workflow step `hydromodpy/workflow/steps/mesh.py` runs these steps. It is the only place
that reads `[mesh]` and asks the mesh cache (`cache.py`). Some engines cannot promise the same
cells twice, so their mesh is stored under `<project>/.hmp/mesh_cache/` and a later run reads
the same cells back.

## The two mesh objects

`PlanarCellMesh` is the mesh of a run. It holds the cells with their centers and CRS, the
line families (river chains, lake shores, barriers, sides), the zones, the engine identity and
the quality report. Areas, edges and neighbors are computed once, on first use.

`HydroMesh` is the plain geometry inside it: vertices and blocks of cells, following the
meshio data model. Plots and exchange files use it, and it accepts 3D cells. A block of
polygons pads the rows of its smaller cells with `-1`.

## The folder map

The top level holds what every step shares. Then each step has its own folder, and a folder
goes one level deeper only where a step has several parts, as the Voronoi constraints do.

```text
mesh/
├── mesh_config.py              the [mesh] table: engine, cell size, families
├── refinement_config.py        the [mesh.lake_refinement] and [[mesh.refinement_zone]] tables
├── request.py                  MeshRequest, everything an engine reads
├── resample.py                 lines resampled at the local cell size
├── port.py                     what an engine must provide (MeshEngine)
├── registry.py                 engine name to engine class, and the entry point group
├── cache.py                    stored meshes that an engine cannot rebuild bit for bit
│
├── planning/                   from the project to one MeshRequest
│   ├── plan.py                 the entry point, plan_mesh_request
│   ├── inputs.py               what the planner reads besides [mesh]
│   ├── catchment_outline.py    smooth the staircase of the catchment outline
│   ├── geometry_cleanup.py     tiny holes, repeated vertices, lines that almost meet
│   ├── families.py             the line families that [mesh.families] asks for
│   ├── geology_contacts.py     contacts between geology zones, as lines
│   ├── barrier_lines.py        flow barriers that run along a lake shore
│   ├── lake_shores.py          lake shores a Voronoi mesh can follow
│   ├── lake_structures.py      cell sizes at lake walls, sills and outlets
│   ├── size_field.py           the target cell size h(x) on the DEM grid
│   ├── size_terms.py           the terms that make up h(x)
│   ├── gap_size.py             cell size from the gap between two lines
│   ├── refinement_zones.py     the refinement zones, as regions with a cell size
│   ├── height_above_stream.py  height of each DEM pixel above its stream
│   └── input_triangulation.py  a triangulation read from a .msh file
│
├── engines/                    from a MeshRequest to cells, README.md is the port contract
│   ├── face_families.py        face rows the regular, triangle and voronoi engines share
│   ├── catchment/              the catchment as one polygon cell, for a global model
│   │   └── engine.py           the engine class
│   ├── regular/                square cells on the DEM grid
│   │   ├── engine.py           the engine class
│   │   ├── grid.py             shape, pitch and vertices, as FloPy builds them
│   │   └── families.py         river chains, staircase faces, sides
│   ├── triangle/               triangles from gmsh, or from a .msh file
│   │   ├── engine.py           the engine class
│   │   ├── gmsh_triangulation.py   the constrained Delaunay call to gmsh
│   │   ├── msh_groups.py       families from the physical groups of a .msh
│   │   └── families.py         oriented faces, chains, zones
│   └── voronoi/                polygons whose faces are orthogonal to the centre links
│       ├── engine.py           the engine class
│       ├── from_seeds.py       generated mesh: seeds, Lloyd, cells, checks
│       ├── from_triangulation.py   dual of a triangulation read from a file
│       ├── constraints/        fixed seeds that put cells and faces on the lines
│       │   ├── plan.py         the constraint stage, step by step
│       │   ├── rivers.py       one seed per river cell
│       │   ├── face_pairs.py   mirror pairs that put a face on a line (Berge, 2019)
│       │   ├── boundary_seeds.py   seeds along the domain outline
│       │   ├── conflicts.py    what happens when two constraints meet
│       │   ├── lines.py        request lines in the local frame
│       │   └── state.py        the working state of the stage
│       ├── free_seeds.py       the other seeds: count, draw, order
│       ├── lloyd.py            Lloyd relaxation of the free seeds
│       ├── tessellation.py     Voronoi cells clipped to the domain
│       ├── local_coords.py     local frame and cell size sampled in it
│       ├── checks.py           the checks that refuse a bad mesh
│       └── families.py         river chains, family faces, sides, zones
│
├── planar/                     the mesh objects every consumer reads
│   ├── planar_cell_mesh.py     PlanarCellMesh, what an engine returns
│   ├── hydro_mesh.py           HydroMesh, the geometry for plots and exchange files
│   ├── geometry.py             areas, edges and neighbours, computed once
│   ├── quality.py              the quality report, the same for every engine
│   ├── cell_types.py           the cell types
│   └── regular_grid.py         a DEM-aligned grid built without a config
│
├── cells/                      which cells or faces a consumer asks for
│   ├── boundary.py             cells of the sides, of the river, of a family
│   ├── locate.py               the cell that holds a point
│   ├── in_polygons.py          the cells inside polygons and inside a delineated catchment
│   ├── crossed_by_lines.py     the cells a line crosses
│   ├── barrier_faces.py        the faces of a flow barrier
│   ├── regions.py              the regions left once a family cuts the mesh
│   └── zonal_stats.py          a raster reduced onto the cells
│
└── io/                         exchange files, one module per format
    ├── vtu.py                  VTU for ParaView, also written by hmp export
    ├── meshio_bridge.py        meshio, and through it most mesh formats
    ├── msh.py                  gmsh .msh files, with the CRS in a .prj beside them
    └── bundle.py               the mesh bundles of the Boussinesq validation cases
```

No `__init__.py` re-exports a name. Each name is imported from the module that defines it, so
a search for the name finds its file.

## Where to start

| To change | Open first |
|-----------|------------|
| a `[mesh]` key or its default | `mesh_config.py` or `refinement_config.py` |
| the cell size near rivers, lakes or barriers | `planning/size_terms.py`, then `planning/size_field.py` |
| the smoothing of the catchment outline | `planning/catchment_outline.py` |
| the cleaning of messy input lines | `planning/geometry_cleanup.py` |
| which lines the mesh follows | `planning/families.py`, then `families.py` of each engine |
| the river cells of a Voronoi mesh | `engines/voronoi/constraints/rivers.py` |
| the quality numbers of a mesh | `planar/quality.py` |
| the area, the edges or the neighbors of a cell | `planar/geometry.py` |
| the cells under a point, a polygon or a line | `cells/` |
| an exchange format | `io/` |

## Rules between the folders

The imports go one way, from the request and the planar mesh up to the engines.

- `request.py`, `mesh_config.py` and `refinement_config.py` import nothing else from the
  package.
- `planar/` imports only itself.
- `io/` and `cells/` read `planar/`. `cells/` also reads `request.py`.
- `planning/` reads the two config modules, `request.py`, `resample.py` and `planar/`. It reads
  a triangulation file through `io/msh.py`.
- `engines/` read `request.py`, `resample.py`, `planar/` and `cells/`. They never import
  `planning/` or the workflow.
- Nothing in the package imports the workflow or `hydromodpy/model/properties`. Both read the mesh.
- gmsh is imported in one place, `engines/triangle/gmsh_triangulation.py`, so a regular or a
  Voronoi mesh never loads it.

The order of these folders is checked by `tests/unit/architecture/mesh_layout.yaml`. The rules between HydroModPy layers are checked by `tests/unit/architecture/layer_matrix.yaml`.

## What lives outside the package

What only a solver reads lives with that solver. The `sgrid` table of the MODFLOW backends
(`sgrid_config.py`), the vertical part of a regular grid (`StructuredGridBuilder` in
`discretization_spatial.py`) and the MODFLOW 6 DISV arguments (`to_flopy_disv_args` in
`solver_mesh.py`) are in `hydromodpy/solver/modflow_grid/`. The cells a lake owns, the faces of
its cutoff wall (`_lake_geometry.py`) and the share of a reach among the cells
(`_sfr_network.py`) are in `hydromodpy/solver/modflow6/builders/`. The `hydromodpy/model/properties`
package samples its property supports on the cells of a `PlanarCellMesh`, and draws one value per cell with
`plot_cell_values` in `hydromodpy/model/properties/plotting.py`.

## Changing the code

The tests follow the layout of the code. A test file carries the name of the module it tests
and sits in the same folder under `tests/unit/mesh/`, so `planning/size_field.py` is tested in
`tests/unit/mesh/planning/test_size_field.py`. A few small modules are tested through the
module that calls them, for example `engines/voronoi/constraints/rivers.py` in
`constraints/test_plan.py`. A test builds its grid, request and meshes with the helpers of
`tests/_helpers/mesh_cases.py`, and the name of a test function says the behavior it checks.

Three more checks guard the meshes. The engine contract
(`tests/contract/test_mesh_engine_contract.py`) holds what every engine must do. The mesh
regression (`tests/regression/mesh/`) compares the meshes of fixed cases to committed
references, so any change there must be wanted. The CI job `mesh-coverage` in
`.github/workflows/main-ci.yml` fails when the branch coverage of this package drops below a
floor, and that floor only goes up.

```bash
pytest tests/unit/mesh -q
```

```bash
pytest tests/contract/test_mesh_engine_contract.py tests/regression/mesh -q
```

```bash
pytest tests/unit/architecture -q
```

With `HMP_REQUIRE_GMSH=1`, a missing gmsh fails the triangle tests instead of skipping them.

A new `[mesh]` key is a field of the Pydantic model in `mesh_config.py`, with its description.
The parameter reference of the documentation is built from that model, so the key needs no
other page.

## Add an engine

An engine is a class with `engine_id`, `engine_version`, `capabilities` and a
`build(request)` method that returns a `PlanarCellMesh`. It joins the registry through the
`hydromodpy.mesh.engine` entry point, and then `[mesh] engine = "<id>"` selects it. Raise
`engine_version` whenever the mesh returned for one request changes. The contract of the port
is `engines/README.md`.

The full recipe and the capability table are in
`docs/source/contribute/architecture/mesh/mesh-engines.rst`.

## Documentation

The developer pages are in `docs/source/contribute/architecture/mesh/`.

- `mesh-pivot.rst` covers `HydroMesh`, `PlanarCellMesh`, the line families and the consumers.
- `mesh-engines.rst` covers the port, the registry, the request, the planner and the cache.
- `triangle-engine.rst` covers the gmsh triangle engine and its cache.
- `voronoi-engine.rst` covers the generated seeds, the mirror pairs, Lloyd and the checks.

The scientific choice of an engine and of the cell size is explained in
`docs/source/theory/mesh.md`.
