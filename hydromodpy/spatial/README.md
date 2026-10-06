# `hydromodpy/spatial`

Where the model is in space. From a DEM and an outlet to a catchment, its river
network and the ground of the model; from the ground and a depth model to the
domain; from the domain to a mesh; and the fields that carry a value per zone,
per cell or per depth onto that mesh. Sites that fit a study are selected here
too. The package knows no solver and no data provider: the geology source is
registered at start-up, and a mesh leaves as a `HydroMesh` that each solver
converts.
This file is the map of the package: what each part answers, the import
rules, how a catchment becomes a mesh, and where to add what. `field/`,
`geographic/`, `mesh/` and `site_selection/` each have a note of their own.

## Parts

| part | answers |
|---|---|
| `raster_support.py`, `surface.py`, `surface_sampling.py` | where a 2D surface sits in space (`RasterSupport`), the surfaces of the domain (`Surface`), and prepared samplers for repeated sampling at points (`PreparedSurfaceSampler`) |
| `catchment_zones_field.py` | the three-class zonation `domain`, `buffer`, `core` of a catchment |
| `protocols.py` | what spatial needs from outside it: the `GeologyDataSource` Protocol and its registration (`register_geology_data_source`) |
| `administrative/` | which French department a point lies in |
| `delineation/` | the backends that delineate a catchment and route flow on a DEM; `registry.py` resolves one by name, `whitebox_workflows_backend/` is the one shipped |
| `terrain/` | the `TerrainEngine` port, what a flow-routing engine owes its callers, and the two engines that serve it (`whitebox_engine.py`, `numpy_engine.py`); `registry.py` resolves one by id, plugins included |
| `geographic/` | the pre-simulation pipeline: `core/` builds the ground (DEM and its corrections), flow products, catchment from a point or a polygon, zones, river network, hydrographic network, SFR reach network, lake enforcement; `pipeline.py` assembles the artifacts; `GeographicConfig` is `[geographic]`; `structure_binders.py` writes geology and catchment zones into the domain; `synthetic/` makes analytic geographies for validation; map in `geographic/README.md` |
| `domain/` | the aquifer geometry: `Domain` (surface, depth model, zones), `build.py` (its one constructor), the four depth models, `spatial_support.py` (the supports a parameter can be zoned by), and the `domain-build` capability (`capability.py`, `worker.py`) |
| `field/` | values on zones, cells and depths: `Field`, `FieldParam` (homogeneous or per zone, with a vertical profile), their TOML sections, geology, the field meshes |
| `mesh/` | the unified mesh pivot and the ways to make one; `model/` has `HydroMesh`, `CellBlock`, `CellType`; `cartesian_grid/` is the structured DIS route; `gmsh_grid/` is the conformal DISV route (zone-conformal planar meshes, 3D prism extrusion, catchment mesh bundles); `adapters/` converts to and from `meshio` and FloPy; `ops/` holds geometric operations; `refinement/`, `launcher/`, `config/` (`[mesh_catchment]`) and `mesh_cache.py` run and reuse a catchment meshing |
| `lake_bed/` | the lake bed rebuilt from bathymetry and reconciled to the abacus, and the carve of a mesh column |
| `site_selection/` | the primitives of a site selection: candidates, criteria, evidence, decisions, outputs, and the `terrain-delineate` capability (`hydrology/capability.py`, `hydrology/worker.py`); map in `site_selection/README.md` |

## Import rules

`tests/unit/architecture/layer_matrix.yaml` gives spatial `core`, `schema` and
itself, and treats it as one block: the parts import each other freely, and
`domain`, `geographic`, `mesh` and `field` do. Today it imports `core` and
`schema`, plus two exceptions:

1. **`data`, in one module.** `site_selection/candidates/reference_network.py`
   fetches the BD Topage network inside a function, to snap an outlet. It is the
   documented tolerance of `layer_matrix.yaml`. Do not extend it.
2. **`config`, in two scripts.** `domain/cases/run_domain_case.py` and
   `geographic/cases/reference_catchment_delineation_case/run_case.py` are
   listed under `exempt_files` of the matrix.

Three rules hold inside:

1. Geology reaches spatial through `protocols.GeologyDataSource`. Spatial
   imports no `data` module for geology; `hydromodpy/_bootstrap.py` registers
   `default_geology_data_source()`.
2. `terrain/` imports no sibling of `spatial`. A third-party engine then needs
   nothing of HydroModPy but the port module. The matrix cannot see this, so
   `tests/unit/architecture/test_terrain_port_stands_alone.py` checks it.
3. A third-party terrain engine joins through the `hydromodpy.terrain.engine`
   entry-point group; one conformance suite, `tests/contract/test_terrain_engine_contract.py`,
   runs on every engine the registry resolves.

Who imports spatial: `solver` and `workflow` (most), `data`, `calibration`,
`results`, `config`, `project`, `cli`, `simulation`, `physics` (one module) and
the package root.

## Tree

```
hydromodpy/spatial/
  __init__.py       lazy names: Domain, FieldParam, HydroMesh, GeographicConfig, ...
  raster_support.py  surface.py  surface_sampling.py  catchment_zones_field.py  protocols.py
  administrative/  delineation/  terrain/
  geographic/       core/  synthetic/  pipeline.py  structure_binders.py  catchment_delineation.py ...
  domain/           domain.py  build.py  depth_model_config.py  spatial_support.py  capability.py  worker.py
  field/            core/  geology/  meshes/  aggregation.py
  mesh/             model/  adapters/  io/  ops/  cartesian_grid/  gmsh_grid/
                    refinement/  launcher/  config/  mesh_cache.py
  lake_bed/
  site_selection/   candidates/  config/  decisions/  evaluation/  evidence/  hydrology/  outputs/  pipelines/
```

## How a catchment becomes a mesh

1. **Geographic.** `[geographic]` (`GeographicConfig`) drives
   `geographic/pipeline.py`. It conditions the DEM into the ground, routes flow
   (a delineation backend or a terrain engine), delineates the catchment from an
   outlet coordinate or takes a given polygon, and builds the river network, the
   hydrographic network and the zone rasters. The artifacts are kept in the
   workspace and reused when the inputs have not changed.
2. **Domain.** `domain/build.py` is the one constructor of a `Domain` from a
   `DomainConfig` (`[domain]`), a surface and a depth model. It arms the zone ids
   that the binders write afterwards. The zones themselves come later, from
   `geographic/structure_binders.py` (`apply_geology_to_domain`,
   `apply_catchment_zones_to_domain`), called by the workflow from the data that
   step loads. The supports a parameter may be zoned by are the providers of
   `domain/spatial_support.py`.
3. **Mesh.** A structured grid comes from `cartesian_grid/` (`SGridConfig`), an
   unstructured one from `gmsh_grid/` (conformal to the zones and the river
   trace) through the launcher in `mesh/launcher/`, configured by
   `[mesh_catchment]`. `mesh/mesh_cache.py` reuses a mesh whose inputs have
   not changed. Both routes give a `HydroMesh`.
4. **Fields.** A `FieldParam` is discretized on the mesh, per zone, per cell and
   per depth: `K`, `Sy` and any other `[flow.param.<id>]`. `physics/` holds
   the parameter section, and `field/` holds the objects.
5. **Hand-off.** A solver reads the mesh through its `solver/modflow_grid/`
   description or, for Boussinesq, the catchment mesh bundle.

## Where to add what

| to add | where |
|---|---|
| a delineation backend | a loader registered with `register_backend` in `delineation/registry.py` |
| a terrain engine | a class that satisfies the port in `terrain/port.py`, registered by `terrain.registry.register` or on the `hydromodpy.terrain.engine` entry-point group |
| a geographic product | a module in `geographic/core/`, called from `geographic/pipeline.py`, and a field on `GeographicConfig` for its options |
| a depth model | a model in `domain/depth_model_config.py` joined to the depth-model union, its use in `domain/domain.py`, and a reader in `domain/build.py` if it needs a raster |
| a spatial support kind | a provider in `domain/spatial_support.py` registered in `SpatialSupportProviderRegistry`, and its config in `domain/spatial_support_config.py`; see `docs/source/contribute/architecture/spatial_support/index.rst` |
| a mesh route | a package under `mesh/` that returns a `HydroMesh`, with an adapter in `mesh/adapters/`; see `docs/source/contribute/architecture/mesh/mesh-pivot.rst` |
| a mesh operation | a mesh-agnostic function in `mesh/ops/` |
| a field kind | `field/core/` (`Field`, `FieldParam` and their sections); see `docs/source/contribute/architecture/field/index.rst` |
| a way to bring loaded data into the domain | a function in `geographic/structure_binders.py`, called from `workflow/steps/` |
| a site-selection criterion | `site_selection/evaluation/criteria/`; see `site_selection/README.md` |
| a capability | a `CapabilityDecl` and a worker beside the code, declared in `cli/_workers/process.py`; see `schema/README.md` |
