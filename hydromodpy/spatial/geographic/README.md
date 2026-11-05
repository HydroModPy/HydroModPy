# spatial/geographic

This package prepares the land surface that every later step builds on. It starts from a DEM and
a way to say where the catchment is (an outlet point, a polygon, or the whole DEM). It conditions
the DEM so that water can run downhill, delineates the catchment, cuts the domain polygons and
the clipped rasters, and extracts the river network. It can also build a synthetic support (flat,
sloping or radial) when no real DEM is wanted. The result is a tree of files on disk plus one
runtime object, `CatchmentDelineation`, that the domain, the mesh and the solvers read.

## How the work flows

A geographic run has seven steps. `pipeline.py` runs them and `core/` holds the code of each one.

1. `core/pipeline_steps.py` resolves the output paths, reads the CRS and the cell size of the
   DEM, and aggregates the DEM to a coarser cell when `[geographic.catchment]` asks for it.
2. `geographic_cache.py` checks whether an earlier run left a tree with the same fingerprint. If
   it did, the run reads that tree and skips steps 3 to 6.
3. `core/ground_corrections.py` builds the ground, which is the DEM plus the corrections the
   project declares. Without a correction it is the raw DEM, with no copy.
4. `core/flow_products.py` conditions the ground (fill, breach or capped breach) and computes the
   D8 direction and accumulation rasters. With `reg_fold` set, `regional_flow_job.py` copies
   these rasters from a sealed job instead.
5. `core/catchment_from_point.py` delineates the catchment, or `core/direct_dem_domain.py` takes
   the DEM extent. `core/catchment_domain.py` cuts the buffered and box polygons.
   `core/river_network.py` extracts the streams.
6. When `[geographic.crossings]` is on, `core/crossing_notch.py` lowers the embankments where
   they cross the channel, and the delineation runs a second time on the notched ground. Then
   `domain_rasters.py` clips the DEM rasters to the domain polygons. When
   `[geographic.bed_regularization]` is on, `core/ground_bed.py` fits the channel bed.
7. `geographic_cache.py` writes the manifest, and `dem_metadata.py` reads the metadata of the
   clipped rasters. `pipeline.py` returns one `GeographicRuntimeContext`.

```text
[geographic] table + DEM
        |
        |  core/pipeline_steps.py      paths, CRS, optional aggregation
        v
   cache hit? ---- yes ----> geographic_cache.py reads the tree
        | no
        |  core/ground_corrections.py  the ground
        |  core/flow_products.py       conditioned DEM, D8 direction, accumulation
        |  core/catchment_*.py         catchment and domain polygons
        |  core/river_network.py       generated streams
        |  domain_rasters.py           clipped rasters
        v
   GeographicRuntimeContext            pipeline.py
        |
        v
   CatchmentDelineation                catchment_delineation.py, read by domain, mesh, solvers
```

`source_mode = "synthetic"` skips all of this. `synthetic/catchment.py` builds the support
from the `[geographic.synthetic]` table and returns a `SyntheticGeographic` object with the
same public attributes.

The workflow step `BuildGeographicStep` in `hydromodpy/workflow/steps/setup.py` is the caller.
It chooses between the two runtimes. The tree lives in the preprocessing folder of the run
(`preprocessing_dir` in `hydromodpy/core/state/scratch.py`), and `preprocessing_cleanup.py` removes
it once the run holds what it needs, unless `write_intermediates` keeps it.

## The folder map

The top level holds the runtime, the cache and one config file per TOML table. `core/` holds one
module per processing block. `synthetic/` is small. The demos that run the catchment cases by
hand and plot them live outside the package, in `tools/cases/geographic/`.

```text
geographic/
├── geographic_config.py            GeographicConfig, the [geographic] table
├── catchment_config.py             the four ways to give the catchment
├── river_network_config.py         [geographic.river_network], stream extraction
├── capped_breach_config.py         [geographic.capped_breach], limits of the capped breach
├── crossings_config.py             [geographic.crossings], road and rail embankments
├── bed_regularization_config.py    [geographic.bed_regularization], the channel bed fit
├── enforce_lakes_config.py         [geographic.enforce_lakes], lake footprints to keep
├── synthetic_config.py             [geographic.synthetic], grid and topography laws
├── pipeline.py                     the run, GeographicRuntimeContext
├── geographic_cache.py             fingerprint, manifest and reuse of the tree
├── geographic_paths.py             every output path of the tree
├── catchment_delineation.py        CatchmentDelineation, the runtime object others read
├── domain_rasters.py               DEM rasters clipped to the domain polygons
├── dem_metadata.py                 CRS, extent, cell size and elevations of the clipped rasters
├── regional_flow_job.py            one sealed flow stack shared by several catchments
├── delineated_catchment.py         the one reader of the delineated catchment polygon
├── structure_binders.py            catchment zones and geology bound to the domain
├── store_ingestion.py              the tree written into the catalog store
├── preprocessing_cleanup.py        removal of the preprocessing tree
├── subbasin.py                     results over sub-basins inside the domain
│
├── core/                           one module per processing block
│   ├── pipeline_steps.py           paths, CRS, DEM aggregation, catchment and polygons
│   ├── dem_aggregation.py          the DEM aggregated to a coarser cell
│   ├── ground_corrections.py       the ground: the DEM plus the declared corrections
│   ├── ground_inputs.py            the lake polygons that the corrections leave alone
│   ├── crossing_notch.py           embankments of roads and rails cut out of the DEM
│   ├── channel_bed_fit.py          least-change fit of the bed along the D8 tree
│   ├── ground_bed.py               the regularised ground and its report
│   ├── flow_products.py            conditioned DEM, D8 direction, D8 accumulation
│   ├── catchment_from_point.py     catchment from an outlet, or from a given polygon
│   ├── direct_dem_domain.py        the DEM extent taken as the domain
│   ├── catchment_domain.py         buffered and box polygons, catchment area
│   ├── domain_dem.py               the DEM clipped to the buffered box
│   ├── catchment_zones.py          zone rasters: catchment core, buffer ring, outside
│   ├── catchment_zones_field.py    CatchmentZonesField, the zone codes and labels kept in Domain.zones
│   ├── river_network.py            stream extraction and its products
│   ├── river_network_vector.py     the stream vector read back, and its summary
│   ├── river_mesh_trace.py         the river lines the mesh follows
│   ├── sfr_network.py              the SFR reach table from the stream links
│   ├── sfr_traces.py               one SFR reach trace per declared network
│   ├── hydrographic_network.py     one object for a generated or a reference network
│   ├── hydrographic_network_comparison.py   two networks compared within a tolerance
│   ├── network_heads.py            free ends of a mapped network, where heads may lie
│   ├── stream_dem_agreement.py     how far the D8 paths stray from the mapped network
│   ├── lake_catchments.py          the area each lake drains on the D8 grid
│   ├── metric_crs.py               lengths and areas measured in a projected CRS
│   ├── derived_features.py         the bundle of geographic products and its domain view
│   └── surface_from_dem.py         a DEM raster as a RasterSupport and a Surface
│
├── synthetic/                      the analytical support, with no DEM
│   ├── catchment.py                SyntheticGeographic and its builder
│   └── topography.py               flat, linear and radial topography laws
```

The `__init__.py` files export no names. A name is imported from the module that defines it,
for example `GeographicConfig` from `geographic_config.py` and `build_synthetic_geographic` from
`synthetic/catchment.py`.

## Where to start

| To change | Open first |
|-----------|------------|
| a `[geographic]` key or its default | `geographic_config.py`, or the file of its sub-table |
| a way to give the catchment | `catchment_config.py`, then `core/pipeline_steps.py` |
| the order of the steps of a run | `pipeline.py` |
| DEM conditioning or the D8 rasters | `core/flow_products.py` |
| the outlet snap or the watershed | `core/catchment_from_point.py` |
| the buffer around the catchment | `core/catchment_domain.py` |
| the generated stream network | `core/river_network.py`, then `core/river_network_vector.py` |
| the cut of an embankment | `core/crossing_notch.py`, then `core/ground_corrections.py` |
| the regularized channel bed | `core/channel_bed_fit.py`, then `core/ground_bed.py` |
| when a tree is reused | `geographic_cache.py` |
| the name or place of an output file | `geographic_paths.py` |
| the SFR reaches | `core/sfr_network.py`, `core/sfr_traces.py` |
| the shared network object | `core/hydrographic_network.py` |
| a synthetic topography | `synthetic_config.py`, then `synthetic/topography.py` |

## Rules between the folders

The imports go one way, from the config files and the paths up to `core/`, then to the pipeline
and the cache, and last to the runtime objects.

- The config files import only `hydromodpy.core` and the terrain port. They import nothing from
  `core/` or from the pipeline. `geographic_config.py` imports the other config files.
- `geographic_paths.py` imports nothing else from the package.
- `core/` imports only `river_network_config.py` and `geographic_paths.py` from the top level.
  It never imports the pipeline, the cache, `domain_rasters.py` or the runtime objects. Only
  `core/pipeline_steps.py` names `GeographicConfig`, under `TYPE_CHECKING`. The other modules
  take the config as an argument.
- `pipeline.py` reads `core/`, the cache, the config and the paths. `geographic_cache.py` and
  `domain_rasters.py` read `core/` too.
- `catchment_delineation.py` calls the pipeline. No other module of this package imports it.
  The workflow setup step and the project facade do, from outside.
- `synthetic/` reads `synthetic_config.py`, `core/derived_features.py` and
  `core/river_network.py`. Nothing in `core/` imports `synthetic/`.

The package imports from other HydroModPy layers only `core`, `schema` and `spatial`, as
`tests/unit/architecture/layer_matrix.yaml` allows for `spatial`.

- `hydromodpy.core` supplies the config base classes, units, logging, raster and CRS helpers,
  the exceptions and the path conventions.
- `hydromodpy.schema` is read by `regional_flow_job.py` alone, for the sealed job documents.
- Inside `spatial`, the package reads `terrain` (the flow-routing port and its registry),
  `delineation` (the backend registry), `surface` and `raster_support`. It reads `domain` and
  `field` only under `TYPE_CHECKING`, in `structure_binders.py`.
- Some imports sit inside the function that needs them. They are the `hydromodpy.core.state.scratch`
  import of `geographic_paths.py` and `subbasin.py`, the `toml_io.loader` import of
  `synthetic_config.py`, the terrain registry import of `geographic_config.py`, and two imports
  of `core/network_heads.py`. A module that only needs its types or its constants does not load
  them. The test `tests/unit/architecture/test_geographic_imports.py` checks that the config
  and the network modules import without a cycle.

The architecture gate runs with the layer rules:

```bash
pytest tests/unit/architecture -q
```

## What lives outside the package

The package prepares files. What reads them is elsewhere.

- The DEM conditioning and the D8 engines are in `hydromodpy/spatial/terrain/`. The package
  calls them through `core/flow_products.py` and `core/catchment_from_point.py`.
- The backend that wraps the flow-routing library is in `hydromodpy/spatial/delineation/`.
- The workflow step `BuildGeographicStep` in `hydromodpy/workflow/steps/setup.py` runs a build.
  Its function `build_geographic_runtime` chooses between `CatchmentDelineation` and the
  synthetic runtime. `hydromodpy/workflow/steps/prepare_solver/prepare.py` calls
  `persist_geographic_to_store` to write the tree into the catalog store.
- The mesh planner reads the river lines through `resolve_river_mesh_trace`
  (`core/derived_features.py`). `hydromodpy/workflow/steps/mesh_inputs.py` calls it.
- The workflow data step `hydromodpy/workflow/steps/data.py` calls `build_sfr_reach_traces`
  (`core/sfr_traces.py`) and `lake_areas_or_even_split` (`core/lake_catchments.py`). The MODFLOW 6 SFR builder in
  `hydromodpy/solver/modflow6/builders/sfr.py` turns the reach table into package data.
- `hydromodpy/results/` reads the network objects to compare and export them.

## Changing the code

The tests mirror the code under `tests/unit/geographic/`, so `core/flow_products.py` is tested in
`tests/unit/geographic/core/test_flow_products.py` and `pipeline.py` in
`tests/unit/geographic/test_pipeline.py`, and the synthetic support in
`tests/unit/geographic/synthetic/`. The demos are tested in `tests/unit/tools/cases/geographic/`.
A test builds its DEMs, configs and cached trees with the helpers of
`tests/_helpers/geographic_cases.py`, which uses `tests/_helpers/ground_bench.py`, a small valley
with a road across it.

Some checks sit outside the unit folder:

- `tests/unit/geographic/golden/` holds the delineation signatures that the unit tests compare
  to.
- `tests/regression/fast/geographic/` runs two golden cases, the DEM processing and the river
  network. `tests/regression/extensive/test_run_geographic_case_regression.py` is the larger one.
- `tests/contract/test_crossing_notch_on_whitebox.py` and
  `tests/contract/test_capped_breach_on_whitebox.py` run the notch and the capped breach on the
  real flow-routing engine.

The CI job `mesh-coverage` in `.github/workflows/main-ci.yml` fails when the branch coverage of
`hydromodpy/spatial/geographic/*` drops below 96.4, and that floor only goes up.

```bash
pytest tests/unit/geographic -q
```

A new `[geographic]` key is a field of the Pydantic model in `geographic_config.py` or in the
file of its sub-table, with its description. The parameter reference is built from the model.
A new output file gets its name in `geographic_paths.py`, and a file that a resume must find
also goes into the tree list of `geographic_cache.py`.

## Documentation

- `docs/source/reference/parameters/geographic.md` is the parameter reference of the table.
- `docs/source/reference/python/CatchmentDelineation.md` and
  `docs/source/reference/python/Subbasin.md` document the two public classes.
- `docs/source/contribute/architecture/spatial_support/hydrographic-network-uml-diagrams.rst`
  and `hydrographic-network-simulated-active-inventory.rst` in
  `docs/source/contribute/architecture/spatial_support/` describe the
  network objects of `core/`.
- `docs/source/theory/exits/simulated-network.md` points to
  `core/hydrographic_network_comparison.py` for the overlap of lines.
- `docs/source/contribute/architecture/how-to/add-a-config-field.rst` uses
  `geographic_config.py` as its worked case.
