# catchment

This package takes a DEM and an outlet and gives the catchment, its river network and the ground of the model.
It routes flow on the DEM, delineates the catchment, cuts the domain polygons and extracts the streams. It also holds
the surfaces the model sits on, the routing of water on the cells of the model top, and the French departments used to
pick data tiles. The mesh itself is in `hydromodpy/mesh`. The aquifer geometry, the fields and the forcings are in
`hydromodpy/model`. The package knows no solver and no data provider: the DEM arrives
as a resolved `dem_path` argument, with its digest and state, from the caller, and a geology map is read by a
function the caller passes as an argument.

This file is the map of the package. One sub-package is a port and has a README of its own, `terrain/`. The other parts
have none and are described here.

## Parts

The parts are listed lowest first. A part reads only the parts above it in this table, and `catchment_layout.yaml`
holds the same order.

| part | answers |
|---|---|
| `raster_support.py`, `surface.py`, `surface_sampling.py` | where a 2D surface sits (`RasterSupport`), the surfaces of the domain (`Surface`), and samplers prepared for repeated reads at points |
| `administrative/` | the French departments and regions of the bundled `departement.gpkg`: their codes in a box or a region, their box and outline |
| `delineation/` | the one Whitebox Workflows environment of the process, in `whitebox_workflows_backend/`, and the two helpers that read a backend |
| `terrain/` | the `TerrainEngine` port, its two engines (Whitebox and numpy), the artifact writers, the D8 pointer reader, the DEM header contract and the undrained-cell count (README) |
| `algorithms/` | one module per processing block: the ground, the flow products, the catchment, the zones, the river and hydrographic networks, the lakes, the SFR reaches |
| `synthetic/` | analytic catchments with no DEM, for validation, and `[geographic.synthetic]` |
| `preprocess/` | the pipeline before the simulation: the run, the geographic tree, the `[geographic]` configuration and the runtime objects others read |
| `drainage/` | where water goes on the cells of the model top: the receiver graph, depression filling, the descent D, the downslope distance, the channel tree of the river network A (`channel_tree.py`) and the routing of a release to a discharge (`routing.py`) |
| `stream_network/` | the stream-network criterion on arrays: the simulated network, the flowing cells and the extent masks, the mapped network drawn from its heads, the geometry of a comparison and its partition, and the signed cost a trial is scored on |

## The Whitebox backend

`delineation/whitebox_workflows_backend/` wraps Whitebox Workflows in a facade, `WhiteboxWorkflowsBackend`, with three
parts that share one Whitebox environment. `raster` reads and writes files, `flow` runs the depressions, the D8 pointer
and the accumulation, and `delineation` snaps pour points and traces watersheds and streams. Only `raster.py` and the
child script `depression_child.py` import `whitebox_workflows`.

A process holds one facade. `get_whitebox_backend()` in `delineation/__init__.py` builds it on the first call, and
`clear_whitebox_backend_cache()` drops it. Importing `delineation` does not load Whitebox, so a caller that needs a
class of the backend imports it from `whitebox_workflows_backend`. A function that takes a backend as an argument
receives it from `resolve_delineation_backend(backend)`, which returns the argument when there is one.

Whitebox 1.3.5 can end the process that calls it, with no exception, when two of its threads race in a depression tool.
So `isolated.py` runs depression removal in a child Python process, and the parent runs it again after a crash, three
attempts in all.

## How the work flows

A preprocess run has seven steps. `preprocess/pipeline.py` runs them and `algorithms/` holds the code of each one.

1. `preprocess/pipeline_steps.py` receives `dem_path` from the caller, checks the DEM header and the outlet
   through `terrain/dem_contract.py`, resolves the output paths, reads the CRS and the cell size of the DEM, and
   aggregates the DEM to a coarser cell when `[geographic.catchment]` asks for it.
2. The run asks the product store for the terrain, the conditioned DEM with its D8 directions and its accumulation,
   keyed by the digest and state of the DEM, the method, the engine and the code. A present product is read back
   into the run tree and the conditioning of step 4 is skipped.
3. `algorithms/ground_corrections.py` builds the ground, which is the DEM plus the corrections the project declares.
   Without a correction it is the raw DEM, with no copy.
4. `algorithms/flow_products.py` conditions the ground (fill, breach or capped breach, or `provided` for a DEM
   declared conditioned elsewhere) and computes the D8 direction and accumulation rasters, through a terrain engine.
   A missing product is written by `algorithms/terrain_stored.py`.
5. `algorithms/catchment_from_point.py` delineates the catchment, or `algorithms/direct_dem_domain.py` takes the DEM
   extent. `algorithms/catchment_domain.py` cuts the buffered and box polygons, and `algorithms/river_network.py`
   extracts the streams.
6. When `[geographic.crossings]` is on, `algorithms/crossing_notch.py` lowers the embankments where they cross the
   channel, and the delineation runs a second time on the notched ground. Then `preprocess/domain_rasters.py` clips the
   DEM rasters to the domain polygons. When `[geographic.bed_regularization]` is on, `algorithms/ground_bed.py` fits the
   channel bed.
7. `algorithms/dem_metadata.py` reads the metadata of the clipped rasters. `pipeline.py` returns one
   `GeographicRuntimeContext`.

`source_mode = "synthetic"` skips all of this. `synthetic/catchment.py` builds the support from the
`[geographic.synthetic]` table and returns a `SyntheticGeographic` object with the same public attributes.

The runtime object that others read is `CatchmentDelineation`, in `preprocess/catchment_delineation.py`. The workflow
step `BuildGeographicStep` in `hydromodpy/workflow/steps/setup.py` is the caller, passing the resolved `dem_path` to
the pipeline. The tree lives in the preprocessing
folder of the run, and `preprocess/preprocessing_cleanup.py` removes it once the run holds what it needs, unless
`write_intermediates` keeps it.

## From a catchment to a mesh

1. Preprocess. `[geographic]` (`GeographicConfig`) drives the run above. The artifacts are kept in the workspace and
   reused when the inputs have not changed.
2. Domain. `hydromodpy/model/domain/build.py` is the one constructor of a `Domain` from a `DomainConfig` (`[domain]`), a
   surface and a depth model. The zones come later, from `model/domain/structure_binders.py`, which reads
   `algorithms/catchment_zones_field.py` and the geology field its caller brings.
3. Mesh. `[mesh]` picks an engine in `hydromodpy/mesh`. Triangles and Voronoi cells follow the zones and the river
   trace, and the regular grid makes a staircase along them. The planner reads the river lines through
   `resolve_river_mesh_trace` in `algorithms/derived_features.py`.
4. Fields and hand-off. A `FieldParam` is discretized on the mesh in `model/`, and a solver reads the cells through its
   `solver/modflow_grid/` description.

## Tree

```text
catchment/
├── raster_support.py          RasterSupport, where a 2D surface sits in space
├── surface.py                 Surface, the surfaces of the domain
├── surface_sampling.py        PreparedSurfaceSampler, repeated sampling at points
│
├── administrative/            French departments and regions
│   ├── regions.py             names and codes of the regions
│   ├── france.py              codes, bounding boxes and geometries
│   └── departement.gpkg       bundled department polygons, Lambert-93
├── delineation/               the Whitebox environment of the process
│   ├── __init__.py            get_whitebox_backend and the two backend helpers
│   └── whitebox_workflows_backend/   raster, flow and delineation sub-backends
├── terrain/                   the terrain port, its engines and the DEM checks
│   ├── port.py                TerrainEngine and its value types
│   ├── registry.py            `terrain_engines`, engine id to engine class, and the entry point group
│   ├── dem_contract.py        DEMContract and the header, value and outlet checks of a DEM
│   ├── undrained.py           the cells a conditioned DEM leaves without descent
│   └── ...                    artifacts, d8, numpy and Whitebox engines
├── algorithms/                one module per processing block
│   ├── ground_corrections.py  the ground: the DEM plus the declared corrections
│   ├── flow_products.py       conditioned DEM, D8 direction, D8 accumulation
│   ├── terrain_stored.py      the terrain product of the store, written and read back
│   ├── catchment_*.py         catchment, domain polygons and zone rasters
│   ├── river_network*.py      stream extraction, its vector and its configuration
│   ├── hydrographic_network*.py   one object for a generated or a reference network
│   ├── sfr_network.py         the SFR reach table from the stream links
│   ├── geographic_paths.py    every output path of the preprocessing tree
│   └── ...                    crossings, bed fit, lakes, heads, derived features
├── synthetic/                 the analytical support, with no DEM
│   ├── catchment.py           SyntheticGeographic and its builder
│   ├── topography.py          flat, linear and radial topography laws
│   └── synthetic_config.py    [geographic.synthetic]
├── preprocess/                the run before the simulation
│   ├── pipeline.py            the run, GeographicRuntimeContext
│   ├── pipeline_steps.py      paths, CRS, DEM aggregation, catchment and polygons
│   ├── geographic_config.py   GeographicConfig, the [geographic] table
│   ├── *_config.py            one file per sub-table of [geographic]
│   ├── geographic_tree.py     the files of the geographic tree, by name
│   ├── catchment_delineation.py   CatchmentDelineation, read by domain, mesh, solvers
│   └── ...                    domain rasters, sub-basins, store ingestion, cleanup
└── drainage/                  where water goes on the model top
    ├── graph.py               receiver graph and accumulation
    ├── filling.py             depression filling, and `priority_flood`, the one flood of the criterion and of D
    ├── pins.py                pinned cells a descent passes through
    ├── descent.py             the descent D
    ├── distance.py            downslope distance to a mask
    ├── channel_tree.py        the river network A read around a mesh, and its projection on the cells
    └── routing.py             a per-cell release routed downstream, and the area upstream of a cell
└── stream_network/            the stream-network criterion on arrays
    ├── network.py             what the model calls a stream, from a per-cell release flux
    ├── extent.py              when a cell flows, how often in a year, and the two extent masks
    ├── heads.py               the mapped network drawn from its heads, down the descent
    ├── geometry.py            the static geometry of a comparison, its partition and its supports
    └── cost.py                the signed gap between an excess of simulated stream and a missing one
```

The `__init__.py` files hold a docstring and export no name. A name is imported from the module that defines it, for
example `GeographicConfig` from `preprocess/geographic_config.py` and `build_synthetic_geographic` from
`synthetic/catchment.py`.

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives the package `core`, `schema` and itself. A grep of every
`hydromodpy` import in the package, deferred ones included, finds only these. No module reads `data`: the DEM path
is passed as an argument by the caller, and the reader of one vector geology map is a function the caller passes as
an argument, as the mesh planner shows.

`catchment_layout.yaml` orders the parts. Each part reads only the parts above it in the table of this file, so a cycle
cannot be declared. Another layer of HydroModPy may import only the modules listed under `public` in that file. The
inside of the pipeline stays private (`preprocess/pipeline.py`, `pipeline_steps.py`, `domain_rasters.py`,
`subbasin.py` and the small configurations it composes).

Five more rules hold inside.

1. `terrain/` imports `core` and itself, and one thing more. `WhiteboxTerrainEngine.__init__` imports
   `catchment.delineation` inside the function, and only when it is given no backend. A third-party engine needs
   nothing of HydroModPy but the port module. `tests/unit/architecture/test_terrain_port_stands_alone.py` checks it.
2. `drainage/` imports `core`, itself, `terrain/` and `algorithms/`. `hydromodpy/mesh/planning/height_above_stream.py`
   reads it, and `terrain/` and `preprocess/` do not, because they work on D8 pixels before the mesh exists.
   `channel_tree.py` reads the D8 table of `terrain/` and the pointer name of `algorithms/flow_products.py`.
3. `algorithms/` reads no configuration of the pipeline. Only `pipeline_steps.py` in `preprocess/` names
   `GeographicConfig`, under `TYPE_CHECKING`, and the other modules take the config as an argument.
4. A third-party terrain engine joins through the entry-point group `hydromodpy.terrain.engine`. The conformance suite
   `tests/contract/test_terrain_engine_contract.py` runs on every engine the registry resolves.
5. `stream_network/` imports `core`, itself, `drainage/` and `algorithms/`. It is a science folder under rule 6 of the
   repository, and the imports it still needs outside numpy and one neighbour are listed one by one in the table
   `ALLOWED_OUTSIDE` of `tests/unit/architecture/test_science_module_imports.py`. That table can only shrink. The
   readers of the criterion on a stored run stay in `results/derive/stream/`.

Who imports `catchment`: `solver` and `workflow` (most), `model`, `mesh`, `results`, `calibration`, `config`,
`project` and `data`. The demos that load a whole project TOML live outside the package, in `tools/cases/`.

## Where to add what

| to add | where |
|---|---|
| a Whitebox tool | a method of the part it belongs to in `delineation/whitebox_workflows_backend/`, as a pair, a `*_raster` or `*_vector` method on objects in memory and a method that reads and writes files. A depression tool that can end the process also goes to `DEPRESSION_TOOLS` in `isolated.py` |
| a terrain engine | a class that satisfies the port in `terrain/port.py`, registered by `terrain_engines.register` in `terrain/registry.py` or on the `hydromodpy.terrain.engine` entry-point group |
| a geographic product | a module in `algorithms/`, called from `preprocess/pipeline.py`, and a field on `GeographicConfig` for its options |
| a `[geographic]` key | a field of the Pydantic model in `preprocess/geographic_config.py` or in the file of its sub-table, with its description |
| a name or place of an output file | `algorithms/geographic_paths.py`, and the tree list of `preprocess/geographic_tree.py` when a resume must find it |
| a synthetic topography | `synthetic/synthetic_config.py`, then `synthetic/topography.py` |
| a routing rule or a distance on the model top | `drainage/graph.py`, `drainage/descent.py`, `drainage/distance.py` or `drainage/routing.py` |
| a rule of the stream-network criterion | the module of `stream_network/` that owns it, with its defaults in `core/scoring/stream_defaults.py` |
| how the river network A is read or pinned on the cells | `drainage/channel_tree.py` |
| another country for the departments | a new module beside `administrative/france.py` |
| a mesh engine | a class that satisfies the port in `hydromodpy/mesh/port.py`, see `docs/source/contribute/architecture/mesh/mesh-engines.rst` |
| a capability | a `CapabilityDecl` and a worker beside the code, see `hydromodpy/schema/README.md` |

## Tests and documentation

The tests mirror the code under `tests/unit/catchment/`. A module of `algorithms/` is tested in
`tests/unit/catchment/algorithms/` and one of `preprocess/` in `tests/unit/catchment/preprocess/`. The delineation
signatures that the unit tests compare to are in `tests/unit/catchment/preprocess/golden/`. A test builds its DEMs,
configs and geographic trees with the helpers of `tests/_helpers/geographic_cases.py`.

```bash
pytest tests/unit/catchment -q
```

The CI runs `tests/unit/catchment/delineation/whitebox_workflows_backend/test_whitebox_workflows_backend.py` in its own
step, apart from the rest of the suite, because the Whitebox binding is not safe under pytest-xdist fork distribution.

The CI job `mesh-coverage` in `.github/workflows/main-ci.yml` keeps a coverage floor for `preprocess/`, `terrain/`,
`delineation/` and `administrative/`, and the floors only go up. The parameter reference of the table is
`docs/source/reference/parameters/geographic.md`, and `CatchmentDelineation` is documented in
`docs/source/reference/python/CatchmentDelineation.md`. The network objects of `algorithms/` are described in
`docs/source/contribute/architecture/spatial_support/`.
