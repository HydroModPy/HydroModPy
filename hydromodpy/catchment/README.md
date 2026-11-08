# catchment

This package takes a DEM and an outlet and gives the catchment, its river network and the ground of the model.
It routes flow on the DEM, delineates the catchment, cuts the domain polygons and extracts the streams. It also holds
the surfaces the model sits on, the routing of water on the cells of the model top, and the French departments used to
pick data tiles. The mesh itself is in `hydromodpy/mesh`. The aquifer geometry, the fields and the forcings are in
`hydromodpy/model`. The package knows no solver and no data provider. The geology source is registered at start-up.

This file is the map of the package. Two sub-packages are ports and have a README of their own, `terrain/` and
`delineation/`. The other parts have none and are described here.

## Parts

The parts are listed lowest first. A part reads only the parts above it in this table, and `catchment_layout.yaml`
holds the same order.

| part | answers |
|---|---|
| `raster_support.py`, `surface.py`, `surface_sampling.py` | where a 2D surface sits (`RasterSupport`), the surfaces of the domain (`Surface`), and samplers prepared for repeated reads at points |
| `protocols.py` | the `GeologyDataSource` Protocol that the package needs from outside, and its registration |
| `administrative/` | the French departments and regions of the bundled `departement.gpkg`: their codes in a box or a region, their box and outline |
| `delineation/` | the backends that route flow on a DEM and delineate a catchment. `whitebox_workflows_backend/` is the one shipped (README) |
| `terrain/` | the `TerrainEngine` port, its two engines (Whitebox and numpy), the artifact writers and the D8 pointer reader (README) |
| `algorithms/` | one module per processing block: the ground, the flow products, the catchment, the zones, the river and hydrographic networks, the lakes, the SFR reaches |
| `synthetic/` | analytic catchments with no DEM, for validation, and `[geographic.synthetic]` |
| `preprocess/` | the pipeline before the simulation: the run, its cache, the `[geographic]` configuration and the runtime objects others read |
| `drainage/` | where water goes on the cells of the model top: the receiver graph, depression filling, the descent D and the downslope distance |

## How the work flows

A preprocess run has seven steps. `preprocess/pipeline.py` runs them and `algorithms/` holds the code of each one.

1. `preprocess/pipeline_steps.py` resolves the output paths, reads the CRS and the cell size of the DEM, and
   aggregates the DEM to a coarser cell when `[geographic.catchment]` asks for it.
2. `preprocess/geographic_cache.py` checks whether an earlier run left a tree with the same fingerprint. If it did,
   the run reads that tree and skips steps 3 to 6.
3. `algorithms/ground_corrections.py` builds the ground, which is the DEM plus the corrections the project declares.
   Without a correction it is the raw DEM, with no copy.
4. `algorithms/flow_products.py` conditions the ground (fill, breach or capped breach) and computes the D8 direction
   and accumulation rasters, through a terrain engine. With `reg_fold` set, `preprocess/regional_flow_job.py` copies
   these rasters from a sealed job instead.
5. `algorithms/catchment_from_point.py` delineates the catchment, or `algorithms/direct_dem_domain.py` takes the DEM
   extent. `algorithms/catchment_domain.py` cuts the buffered and box polygons, and `algorithms/river_network.py`
   extracts the streams.
6. When `[geographic.crossings]` is on, `algorithms/crossing_notch.py` lowers the embankments where they cross the
   channel, and the delineation runs a second time on the notched ground. Then `preprocess/domain_rasters.py` clips the
   DEM rasters to the domain polygons. When `[geographic.bed_regularization]` is on, `algorithms/ground_bed.py` fits the
   channel bed.
7. `preprocess/geographic_cache.py` writes the manifest and `algorithms/dem_metadata.py` reads the metadata of the
   clipped rasters. `pipeline.py` returns one `GeographicRuntimeContext`.

`source_mode = "synthetic"` skips all of this. `synthetic/catchment.py` builds the support from the
`[geographic.synthetic]` table and returns a `SyntheticGeographic` object with the same public attributes.

The runtime object that others read is `CatchmentDelineation`, in `preprocess/catchment_delineation.py`. The workflow
step `BuildGeographicStep` in `hydromodpy/workflow/steps/setup.py` is the caller. The tree lives in the preprocessing
folder of the run, and `preprocess/preprocessing_cleanup.py` removes it once the run holds what it needs, unless
`write_intermediates` keeps it.

## From a catchment to a mesh

1. Preprocess. `[geographic]` (`GeographicConfig`) drives the run above. The artifacts are kept in the workspace and
   reused when the inputs have not changed.
2. Domain. `hydromodpy/model/domain/build.py` is the one constructor of a `Domain` from a `DomainConfig` (`[domain]`), a
   surface and a depth model. The zones come later, from `model/domain/structure_binders.py`, which reads
   `algorithms/catchment_zones_field.py` and the geology source.
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
├── protocols.py               GeologyDataSource and its registration
│
├── administrative/            French departments and regions
│   ├── regions.py             names and codes of the regions
│   ├── france.py              codes, bounding boxes and geometries
│   └── departement.gpkg       bundled department polygons, Lambert-93
├── delineation/               catchment delineation and flow routing backends
│   ├── registry.py            backend name to backend class
│   └── whitebox_workflows_backend/   raster, flow and delineation sub-backends
├── terrain/                   the terrain port and its engines
│   ├── port.py                TerrainEngine and its value types
│   ├── registry.py            `terrain_engines`, engine id to engine class, and the entry point group
│   └── ...                    artifacts, d8, numpy and Whitebox engines
├── algorithms/                one module per processing block
│   ├── ground_corrections.py  the ground: the DEM plus the declared corrections
│   ├── flow_products.py       conditioned DEM, D8 direction, D8 accumulation
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
│   ├── geographic_cache.py    fingerprint, manifest and reuse of the tree
│   ├── catchment_delineation.py   CatchmentDelineation, read by domain, mesh, solvers
│   └── ...                    domain rasters, sub-basins, store ingestion, cleanup
└── drainage/                  where water goes on the model top
    ├── graph.py               receiver graph and accumulation
    ├── filling.py             depression filling
    ├── pins.py                pinned cells a descent passes through
    ├── descent.py             the descent D
    └── distance.py            downslope distance to a mask
```

The `__init__.py` files hold a docstring and export no name. A name is imported from the module that defines it, for
example `GeographicConfig` from `preprocess/geographic_config.py` and `build_synthetic_geographic` from
`synthetic/catchment.py`.

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives the package `core`, `schema` and itself. A grep of every
`hydromodpy` import in the package, deferred ones included, finds only these. No module reads `data`. The one link to
data goes through the caller, because geology reaches this package through `protocols.GeologyDataSource` and
`hydromodpy/_bootstrap.py` registers the default source at start-up.

`catchment_layout.yaml` orders the parts. Each part reads only the parts above it in the table of this file, so a cycle
cannot be declared. Another layer of HydroModPy may import only the modules listed under `public` in that file. The
inside of the pipeline stays private (`preprocess/pipeline.py`, `pipeline_steps.py`, `domain_rasters.py`,
`subbasin.py`, `regional_flow_job.py` and the small configurations it composes).

Four more rules hold inside.

1. `terrain/` imports `core` and itself, and one thing more. `WhiteboxTerrainEngine.__init__` imports
   `catchment.delineation` inside the function, and only when it is given no backend. A third-party engine needs
   nothing of HydroModPy but the port module. `tests/unit/architecture/test_terrain_port_stands_alone.py` checks it.
2. `drainage/` imports `core` and itself. `hydromodpy/mesh/planning/height_above_stream.py` reads it, and `terrain/`
   and `preprocess/` do not, because they work on D8 pixels before the mesh exists.
3. `algorithms/` reads no configuration of the pipeline. Only `pipeline_steps.py` in `preprocess/` names
   `GeographicConfig`, under `TYPE_CHECKING`, and the other modules take the config as an argument.
4. A third-party terrain engine joins through the entry-point group `hydromodpy.terrain.engine`. The conformance suite
   `tests/contract/test_terrain_engine_contract.py` runs on every engine the registry resolves.

Who imports `catchment`: `solver` and `workflow` (most), `model`, `mesh`, `results`, `calibration`, `config`, `project`,
`data` and the package root (`_bootstrap.py`). The demos that load a whole project TOML live outside the package, in
`tools/cases/`.

## Where to add what

| to add | where |
|---|---|
| a delineation backend | a loader registered with `register_backend` in `delineation/registry.py`. This is the one registry that does not use the engine of `core/plugin_registry.py`, and it stays so until the delineation port is written |
| a terrain engine | a class that satisfies the port in `terrain/port.py`, registered by `terrain_engines.register` in `terrain/registry.py` or on the `hydromodpy.terrain.engine` entry-point group |
| a geographic product | a module in `algorithms/`, called from `preprocess/pipeline.py`, and a field on `GeographicConfig` for its options |
| a `[geographic]` key | a field of the Pydantic model in `preprocess/geographic_config.py` or in the file of its sub-table, with its description |
| a name or place of an output file | `algorithms/geographic_paths.py`, and the tree list of `preprocess/geographic_cache.py` when a resume must find it |
| a synthetic topography | `synthetic/synthetic_config.py`, then `synthetic/topography.py` |
| a routing rule or a distance on the model top | `drainage/graph.py`, `drainage/descent.py` or `drainage/distance.py` |
| another country for the departments | a new module beside `administrative/france.py` |
| a mesh engine | a class that satisfies the port in `hydromodpy/mesh/port.py`, see `docs/source/contribute/architecture/mesh/mesh-engines.rst` |
| a capability | a `CapabilityDecl` and a worker beside the code, see `hydromodpy/schema/README.md` |

## Tests and documentation

The tests mirror the code under `tests/unit/catchment/`. A module of `algorithms/` is tested in
`tests/unit/catchment/algorithms/` and one of `preprocess/` in `tests/unit/catchment/preprocess/`. The delineation
signatures that the unit tests compare to are in `tests/unit/catchment/preprocess/golden/`. A test builds its DEMs,
configs and cached trees with the helpers of `tests/_helpers/geographic_cases.py`.

```bash
pytest tests/unit/catchment -q
```

The CI job `mesh-coverage` in `.github/workflows/main-ci.yml` keeps a coverage floor for `preprocess/`, `terrain/`,
`delineation/` and `administrative/`, and the floors only go up. The parameter reference of the table is
`docs/source/reference/parameters/geographic.md`, and `CatchmentDelineation` is documented in
`docs/source/reference/python/CatchmentDelineation.md`. The network objects of `algorithms/` are described in
`docs/source/contribute/architecture/spatial_support/`.
