# `hydromodpy/spatial`

Where the model is in space. From a DEM and an outlet to a catchment, its river
network and the ground of the model; from the ground and a depth model to the
domain; from the domain to a mesh; and the fields that carry a value per zone,
per cell or per depth onto that mesh. Sites that fit a study are selected here
too. The package knows no solver and no data provider: the geology source is
registered at start-up, the BD Topage fetcher of a site selection is passed in
by the workflow, and a mesh leaves as a `PlanarCellMesh` that each solver reads.
This file is the map of the package: what each part answers, the import
rules, the tree, how a catchment becomes a mesh, and where to add what. Each
sub-package has a note of its own with the full map.

## Parts

| part | answers |
|---|---|
| `raster_support.py`, `surface.py`, `surface_sampling.py` | where a 2D surface sits (`RasterSupport`), the surfaces of the domain (`Surface`), and samplers prepared for repeated reads at points |
| `catchment_zones_field.py` | `CatchmentZonesField`, the class codes of `Domain.zones` on the domain grid, with their labels. `geographic/structure_binders.py` fills it with `domain`, `buffer` and `core`, or `uniform` |
| `protocols.py` | the `GeologyDataSource` Protocol that spatial needs from outside, and its registration |
| `job_inputs.py` | the input checks the `domain-build` and `terrain-delineate` workers share, and the hashes of the outputs they seal |
| `administrative/` | the French departments and regions of the bundled `departement.gpkg`: their codes in a box or a region, their box and outline |
| `delineation/` | the backends that route flow on a DEM and delineate a catchment. `whitebox_workflows_backend/` is the one shipped |
| `terrain/` | the `TerrainEngine` port, its two engines (Whitebox and numpy), the artifact writers and the D8 pointer reader |
| `geographic/` | the pipeline before the simulation: the ground, the flow products, the catchment, the zones and the river networks. `GeographicConfig` is `[geographic]` |
| `domain/` | the aquifer geometry: `Domain`, its four depth models, the layering of the column, the zoning supports and the `domain-build` capability |
| `field/` | values on zones, cells and depths: `Field`, `FieldParam` with its vertical profile, and the geology field. `mesh/` never imports it |
| `mesh/` | the unified mesh (`HydroMesh`, `PlanarCellMesh`), its regular, triangle and Voronoi engines, its exchange formats and the `[mesh]` config |
| `forcing/` | gridded and station forcings as one rate per cell and per stress period. `mesh/` never imports it |
| `lake_bed/` | the lake bed rebuilt from bathymetry and reconciled to the abacus |
| `site_selection/` | the steps of a site selection (candidates, criteria, evidence, decisions, outputs) and the `terrain-delineate` capability |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives spatial `core`, `schema` and
itself, and treats it as one block: the parts import each other freely, and
`domain`, `geographic`, `mesh` and `field` do. A grep of every `hydromodpy`
import in the package, deferred ones included, finds only `core`, `schema`
and `spatial`, with one exception:

1. `config`, in two scripts. `domain/cases/run_domain_case.py` and
   `geographic/cases/reference_catchment_delineation_case/run_case.py` load a
   `HydroModPyConfig` from a TOML file. Both are listed under `exempt_files`
   of the matrix.

No module of spatial imports `data`. The matrix has no `spatial -> data`
tolerance left. The two links to data go through the caller:

1. Geology reaches spatial through `protocols.GeologyDataSource`.
   `hydromodpy/_bootstrap.py` registers `default_geology_data_source()` at
   start-up.
2. The BD Topage network of a site selection reaches
   `site_selection/hydrology/reference_network.py` as a `fetcher` argument.
   `workflow/site_selection/build_from_toml.py` passes
   `fetch_bdtopage_reference_network`.

Two rules hold inside:

1. `terrain/` imports `core` and itself, and one thing more. The method
   `WhiteboxTerrainEngine.__init__` in `terrain/whitebox_engine.py` imports
   `spatial.delineation` inside the function, and only when it is given no
   backend. So a third-party engine needs nothing of HydroModPy but the port
   module, and no other module of `terrain/` loads `delineation`. The matrix
   cannot see this, so `tests/unit/architecture/test_terrain_port_stands_alone.py`
   checks it, with that one declared exception.
2. A third-party terrain engine joins through the `hydromodpy.terrain.engine`
   entry-point group; one conformance suite, `tests/contract/test_terrain_engine_contract.py`,
   runs on every engine the registry resolves.

Who imports spatial: `solver` and `workflow` (most), `data`, `results`,
`calibration`, `config`, `project`, `simulation`, `physics` (one module, the
field sections in `physics/flow/flow_param_config.py`) and the package root
(`_bootstrap.py`, `_lazy.py`).

## Tree

Each sub-package has its own README with the full map: `administrative/`,
`delineation/`, `domain/`, `field/`, `forcing/`, `geographic/`, `lake_bed/`,
`mesh/`, `site_selection/`, `terrain/`, and
`hydromodpy/workflow/site_selection/` (the workflow side of a site selection).

```text
spatial/
├── __init__.py                lazy names: Domain, FieldParam, HydroMesh, GeographicConfig, ...
├── raster_support.py          RasterSupport, where a 2D surface sits in space
├── surface.py                 Surface, the surfaces of the domain
├── surface_sampling.py        PreparedSurfaceSampler, repeated sampling at points
├── catchment_zones_field.py   CatchmentZonesField, the zonation kept in Domain.zones
├── protocols.py               GeologyDataSource and its registration
├── job_inputs.py              input checks shared by the two capability workers
│
├── administrative/            French departments and regions
│   ├── france.py              codes, bounding boxes and geometries
│   └── departement.gpkg       bundled department polygons, Lambert-93
├── delineation/               catchment delineation and flow routing backends
│   ├── registry.py            backend name to backend class
│   └── whitebox_workflows_backend/   raster, flow and delineation sub-backends
├── terrain/                   the terrain port and its engines
│   ├── port.py                TerrainEngine and its value types
│   ├── registry.py            engine id to engine class, and the entry point group
│   ├── artifacts.py           the rasters and vectors an engine writes
│   ├── d8.py                  receiver of each cell of a D8 pointer
│   ├── whitebox_engine.py     engine on the Whitebox backend
│   └── numpy_engine.py        engine in plain NumPy
├── geographic/                the pre-simulation pipeline
│   ├── core/                  ground, flow products, catchment, zones, networks, lakes
│   ├── synthetic/             analytic geographies for validation
│   ├── cases/                 reference cases and their data
│   ├── pipeline.py            assembles the artifacts
│   ├── geographic_config.py   GeographicConfig, the [geographic] table
│   ├── structure_binders.py   geology and catchment zones into the domain
│   └── catchment_delineation.py   catchment from an outlet or a polygon
├── domain/                    the aquifer geometry
│   ├── domain.py              Domain: surface, depth model, zones
│   ├── build.py               the one constructor of a Domain
│   ├── domain_config.py       the [domain] table
│   ├── depth_model_config.py  the four depth models
│   ├── layers_config.py       the [domain.layers] table
│   ├── layering.py            layer bottoms and idomain
│   ├── spatial_support.py     the supports a parameter can be zoned by
│   ├── support_fields.py      zone fields cut from rasters and bands
│   ├── active_cells.py        the cells a domain is defined on
│   ├── domain_document.py     the document written for the mesh generator
│   ├── capability.py          the domain-build capability
│   ├── worker.py              its worker
│   └── cases/                 a run script and a TOML for the domain
├── field/                     values on zones, cells and depths
│   ├── field_param.py         FieldParam
│   ├── field_spatial.py       Field
│   ├── vertical_profile.py    depth profile of a parameter
│   ├── geology_config.py      geology polygons or raster, and its config
│   ├── geology_field.py       geology as a field
│   ├── mesh_cells.py          cells of a PlanarCellMesh a support samples
│   └── cases/                 square-domain demos
├── forcing/                   gridded and station forcings on mesh cells
│   ├── cells.py               one rate per cell and per stress period
│   ├── rasters.py             xarray, NetCDF and GeoTIFF sources
│   ├── stations.py            located series
│   ├── sources.py             units and variables
│   ├── area_weights.py        the area method
│   └── interpolation.py       nearest, linear and IDW
├── lake_bed/                  lake bed from bathymetry
│   ├── abacus.py              stage-volume-area curve
│   └── regrid.py              raster bed to cell bed
├── mesh/                      the mesh pivot and the engines
│   ├── model/                 PlanarCellMesh, HydroMesh, CellBlock, CellType
│   ├── engines/               regular, triangle and voronoi
│   ├── planning/              from the project to one MeshRequest
│   ├── io/                    VTU, meshio, Gmsh .msh, mesh bundles
│   ├── cells/                 which cells or faces
│   ├── mesh_config.py         the [mesh] table
│   ├── refinement_config.py   refinement tables
│   ├── request.py             MeshRequest
│   ├── resample.py            lines resampled at the cell size
│   ├── port.py                what an engine must provide
│   ├── registry.py            engine name to engine class
│   └── cache.py               stored meshes
└── site_selection/            the primitives of a site selection
    ├── candidates/            outlets and candidate catchments
    ├── config/                the site-selection tables
    ├── decisions/             decision records and aggregation
    ├── domain/                the value objects of a selection
    ├── evaluation/            criteria and selection
    ├── evidence/              observations, geology and piezometer layers
    ├── hydrology/             delineation, flow products, terrain-delineate capability
    ├── outputs/               files written by a selection
    └── pipelines/             the build of a selection
```

## How a catchment becomes a mesh

1. Geographic. `[geographic]` (`GeographicConfig`) drives
   `geographic/pipeline.py`. It conditions the DEM into the ground, routes flow
   (a delineation backend or a terrain engine), delineates the catchment from an
   outlet coordinate or takes a given polygon, and builds the river network, the
   hydrographic network and the zone rasters. The artifacts are kept in the
   workspace and reused when the inputs have not changed.
2. Domain. `domain/build.py` is the one constructor of a `Domain` from a
   `DomainConfig` (`[domain]`), a surface and a depth model. It arms the zone ids
   that the binders write afterwards. The zones themselves come later, from
   `geographic/structure_binders.py` (`apply_geology_to_domain`,
   `apply_catchment_zones_to_domain`), called by the workflow from the data that
   step loads. The supports a parameter may be zoned by are the providers of
   `domain/spatial_support.py`.
3. Mesh. `[mesh]` picks an engine. Triangles and Voronoi cells follow the zones and
   the river trace, and the regular grid makes a staircase along them. `mesh/cache.py` stores the mesh of an
   engine that cannot be rebuilt bit for bit and reads it back on later runs.
   Every engine gives a `PlanarCellMesh`, and the solvers read the cells from it.
4. Fields. A `FieldParam` is discretized on the mesh, per zone, per cell and
   per depth: `K`, `Sy` and any other `[flow.param.<id>]`. `physics/` holds
   the parameter section, and `field/` holds the objects.
5. Hand-off. A solver reads the cell mesh through its `solver/modflow_grid/`
   description. Each flow adapter declares the engines it reads.

## Where to add what

| to add | where |
|---|---|
| a delineation backend | a loader registered with `register_backend` in `delineation/registry.py` |
| a terrain engine | a class that satisfies the port in `terrain/port.py`, registered by `terrain.registry.register` or on the `hydromodpy.terrain.engine` entry-point group |
| a geographic product | a module in `geographic/core/`, called from `geographic/pipeline.py`, and a field on `GeographicConfig` for its options |
| a depth model | a model in `domain/depth_model_config.py` joined to the depth-model union, its use in `domain/domain.py`, and a reader in `domain/build.py` if it needs a raster |
| a spatial support kind | a provider in `domain/spatial_support.py` registered in `SpatialSupportProviderRegistry`, and its config in `domain/spatial_support_config.py`; see `docs/source/contribute/architecture/spatial_support/index.rst` |
| a mesh engine | a class that satisfies the port in `mesh/port.py`, registered by `mesh.registry.register` or on the `hydromodpy.mesh.engine` entry-point group; see `docs/source/contribute/architecture/mesh/mesh-engines.rst` |
| a question on the cells or faces of a mesh | a mesh-agnostic function in `mesh/cells/` |
| a field kind | `field/` (`Field` in `field_spatial.py`, `FieldParam` in `field_param.py` and their sections); see `docs/source/contribute/architecture/field/index.rst` |
| a way to bring loaded data into the domain | a function in `geographic/structure_binders.py`, called from `workflow/steps/` |
| a site-selection criterion | `site_selection/evaluation/criteria/`; see `site_selection/README.md` |
| a capability | a `CapabilityDecl` and a worker beside the code; see `hydromodpy/schema/README.md` |
