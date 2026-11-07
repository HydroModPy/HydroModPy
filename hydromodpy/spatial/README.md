# `hydromodpy/spatial`

Where the model is in space. From a DEM and an outlet to a catchment, its river
network and the ground of the model, and from the ground to the input of a mesh. The mesh itself lives in `hydromodpy/mesh`. The aquifer
geometry, the fields that carry a value per zone, per cell or per depth, and the
forcings on the cells live in `model/`. The package knows no solver and no data
provider: the geology source is registered at start-up.
This file is the map of the package: what each part answers, the import
rules, the tree, how a catchment becomes a mesh, and where to add what. Each
sub-package has a note of its own with the full map.

## Parts

| part | answers |
|---|---|
| `raster_support.py`, `surface.py`, `surface_sampling.py` | where a 2D surface sits (`RasterSupport`), the surfaces of the domain (`Surface`), and samplers prepared for repeated reads at points |
| `protocols.py` | the `GeologyDataSource` Protocol that spatial needs from outside, and its registration |
| `job_inputs.py` | the input checks of the `domain-build` worker, and the hashes of the outputs it seals |
| `administrative/` | the French departments and regions of the bundled `departement.gpkg`: their codes in a box or a region, their box and outline |
| `delineation/` | the backends that route flow on a DEM and delineate a catchment. `whitebox_workflows_backend/` is the one shipped |
| `drainage/` | where water goes on the cells of the model top: the receiver graph, depression filling, the descent D and the downslope distance |
| `terrain/` | the `TerrainEngine` port, its two engines (Whitebox and numpy), the artifact writers and the D8 pointer reader |
| `geographic/` | the pipeline before the simulation: the ground, the flow products, the catchment, the zones and the river networks. `GeographicConfig` is `[geographic]`, and `CatchmentZonesField` is the zonation that `model/domain/structure_binders.py` puts in `Domain.zones` |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives spatial `core`, `schema` and
itself, and treats it as one block: the parts import each other freely, and
`geographic` does. A grep of every `hydromodpy`
import in the package, deferred ones included, finds only `core`, `schema`
and `spatial`. The demos that load a whole project TOML live outside the
package, in `tools/cases/`.

No module of spatial imports `data`. The matrix has no `spatial -> data`
tolerance left. The one link to data goes through the caller: geology reaches
spatial through `protocols.GeologyDataSource`, and `hydromodpy/_bootstrap.py`
registers `default_geology_data_source()` at start-up.

Three rules hold inside:

1. `terrain/` imports `core` and itself, and one thing more. The method
   `WhiteboxTerrainEngine.__init__` in `terrain/whitebox_engine.py` imports
   `spatial.delineation` inside the function, and only when it is given no
   backend. So a third-party engine needs nothing of HydroModPy but the port
   module, and no other module of `terrain/` loads `delineation`. The matrix
   cannot see this, so `tests/unit/architecture/test_terrain_port_stands_alone.py`
   checks it, with that one declared exception.
2. `drainage/` imports `core` and itself. `hydromodpy/mesh/planning/height_above_stream.py` reads it, and `terrain/` and `geographic/` do not: they work on D8 pixels before the mesh exists.
3. A third-party terrain engine joins through the `hydromodpy.terrain.engine`
   entry-point group; one conformance suite, `tests/contract/test_terrain_engine_contract.py`,
   runs on every engine the registry resolves.

Who imports spatial: `solver` and `workflow` (most), `data`,
`results`, `calibration`, `config`, `project`, `model` and the
package root (`_bootstrap.py`, `_lazy.py`).

## Tree

Each sub-package has its own README with the full map: `administrative/`,
`delineation/`, `drainage/`, `geographic/` and `terrain/`.

```text
spatial/
├── __init__.py                lazy names: GeographicConfig, ...
├── raster_support.py          RasterSupport, where a 2D surface sits in space
├── surface.py                 Surface, the surfaces of the domain
├── surface_sampling.py        PreparedSurfaceSampler, repeated sampling at points
├── protocols.py               GeologyDataSource and its registration
├── job_inputs.py              input checks shared by the two capability workers
│
├── administrative/            French departments and regions
│   ├── france.py              codes, bounding boxes and geometries
│   └── departement.gpkg       bundled department polygons, Lambert-93
├── delineation/               catchment delineation and flow routing backends
│   ├── registry.py            backend name to backend class
│   └── whitebox_workflows_backend/   raster, flow and delineation sub-backends
├── drainage/                  where water goes on the model top
│   ├── graph.py               receiver graph and accumulation
│   ├── filling.py             depression filling
│   ├── pins.py                pinned cells a descent passes through
│   ├── descent.py             the descent D
│   └── distance.py            downslope distance to a mask
├── terrain/                   the terrain port and its engines
│   ├── port.py                TerrainEngine and its value types
│   ├── registry.py            engine id to engine class, and the entry point group
│   ├── artifacts.py           the rasters and vectors an engine writes
│   ├── d8.py                  receiver of each cell of a D8 pointer
│   ├── whitebox_engine.py     engine on the Whitebox backend
│   └── numpy_engine.py        engine in plain NumPy
└── geographic/                the pre-simulation pipeline
    ├── core/                  ground, flow products, catchment, zones, networks, lakes
    ├── synthetic/             analytic geographies for validation
    ├── pipeline.py            assembles the artifacts
    ├── geographic_config.py   GeographicConfig, the [geographic] table
    └── catchment_delineation.py   catchment from an outlet or a polygon
```

## How a catchment becomes a mesh

1. Geographic. `[geographic]` (`GeographicConfig`) drives
   `geographic/pipeline.py`. It conditions the DEM into the ground, routes flow
   (a delineation backend or a terrain engine), delineates the catchment from an
   outlet coordinate or takes a given polygon, and builds the river network, the
   hydrographic network and the zone rasters. The artifacts are kept in the
   workspace and reused when the inputs have not changed.
2. Domain. `model/domain/build.py` is the one constructor of a `Domain` from a
   `DomainConfig` (`[domain]`), a surface and a depth model. It arms the zone ids
   that the binders write afterwards. The zones themselves come later, from
   `model/domain/structure_binders.py` (`apply_geology_to_domain`,
   `apply_catchment_zones_to_domain`), called by the workflow from the data that
   step loads. The supports a parameter may be zoned by are the providers of
   `model/domain/spatial_support.py`.
3. Mesh. `[mesh]` picks an engine. Triangles and Voronoi cells follow the zones and
   the river trace, and the regular grid makes a staircase along them. `hydromodpy/mesh/cache.py` stores the mesh of an
   engine that cannot be rebuilt bit for bit and reads it back on later runs.
   Every engine gives a `PlanarCellMesh`, and the solvers read the cells from it.
4. Fields. A `FieldParam` is discretized on the mesh, per zone, per cell and
   per depth: `K`, `Sy` and any other `[flow.param.<id>]`. `model/flow_config.py` holds
   the parameter section, and `model/properties/` holds the objects.
5. Hand-off. A solver reads the cell mesh through its `solver/modflow_grid/`
   description. Each flow adapter declares the engines it reads.

## Where to add what

| to add | where |
|---|---|
| a delineation backend | a loader registered with `register_backend` in `delineation/registry.py` |
| a terrain engine | a class that satisfies the port in `terrain/port.py`, registered by `terrain.registry.register` or on the `hydromodpy.terrain.engine` entry-point group |
| a geographic product | a module in `geographic/core/`, called from `geographic/pipeline.py`, and a field on `GeographicConfig` for its options |
| a mesh engine | a class that satisfies the port in `hydromodpy/mesh/port.py`, registered by `mesh.registry.register` or on the `hydromodpy.mesh.engine` entry-point group; see `docs/source/contribute/architecture/mesh/mesh-engines.rst` |
| a question on the cells or faces of a mesh | a mesh-agnostic function in `hydromodpy/mesh/cells/` |
| a capability | a `CapabilityDecl` and a worker beside the code; see `hydromodpy/schema/README.md` |
