# model/domain

The aquifer as a body of rock. The package takes the ground surface from the DEM, puts the base of the
aquifer below it with a depth model, and cuts the column between the two into layers. It holds the spatial
supports, the maps (geology, catchment zones, bands, rings) that a parameter such as K can vary on. The
lake bed rebuilt from a bathymetry raster lives here too, because it changes the top and the layers of
the cells under a lake. The mesh decides the cells in the plan, and this package decides what is above
and below each cell.

## How the work flows

1. The `[domain]` table is read into a `DomainConfig`. Its three parts are the depth model, the layers
   and the supports.
2. `build.py` builds a `Domain` (`domain.py`) from that config and a surface. The depth model gives the
   base of the aquifer, and the raster models read a base raster first.
3. `structure_binders.py` writes the geology and the catchment zones into the domain, once the data is
   loaded. The catchment zones are a `CatchmentZonesField`, defined in
   `spatial/geographic/core/catchment_zones_field.py` beside the code that computes them.
4. The solvers read the layers. `layering.py` turns `[domain.layers]` and the two surfaces into the
   bottom and the `idomain` of every layer.
5. A heterogeneous parameter asks for a support. A provider in `spatial_support.py` builds a support
   field (`support_fields.py`), which gives the zone share of each cell of a mesh.
6. For a lake with a bathymetry, `lake_bed_regrid.py` gives each lake cell the mean of the bathymetry
   pixels in it, and `lake_bed_abacus.py` remaps the elevations by area-weighted quantiles so the lake
   fills the way its abacus says. The solver then re-grades each column of layers around the carved bed,
   in `solver/modflow6/builders/lake_column_regrade.py`.

The `domain-build` capability does steps 1 and 2 as a job. A request names a DEM and a depth model. The
worker calls the same `build_domain`, writes the rasters of the top and the base, and seals a
`domain.json` for the mesh generator. It is a capability for outside tools. No `hmp` command and no step
of a run starts it. A tool stages a job directory (the contract is in `hydromodpy/schema/job/`) and calls
`worker.run(job, exit_code_for=...)`. Only the tests in `tests/integration/domain/` call it inside this
repository. It stays on purpose, so keep it when you tidy the package.

There are four depth models, each with its own `kind` in `depth_model_config.py`. They are
`constant_thickness`, `flat_substratum`, `raster_substratum` and `raster_thickness`. The first two need
no file. The two raster models read a raster from `[data.substratum]`, and `build.py` reads it
(`read_substratum_source`). A layering by surfaces can also read one base raster per layer
(`read_layer_base_sources`).

## Modules

| module | answers |
|---|---|
| `active_cells.py` | The cells a domain is defined on, read from the terrain or from a mask layer |
| `build.py` | The one constructor of a domain geometry |
| `capability.py` | The `domain-build` declaration and its request model |
| `depth_model_config.py` | The four depth models |
| `domain.py` | Domain assembly logic built on top of `Surface` and `DomainConfig` |
| `domain_config.py` | The `[domain]` table |
| `domain_document.py` | The document that describes a built domain, written for the mesh generator |
| `lake_bed_abacus.py` | Reconciles a bed to the abacus of the lake, and simulates the abacus of a bed |
| `lake_bed_regrid.py` | Averages a bathymetry raster onto the mesh cells, and rebuilds the bed of one lake |
| `layering.py` | Layer bottoms and `idomain` of a layering, from shares of the column or from one base per layer |
| `layers_config.py` | Pydantic configuration of `[domain.layers]`, the vertical layering of the aquifer |
| `spatial_support.py` | The support providers, their registry and the contract of the supports a parameter asks for |
| `spatial_support_config.py` | The kinds of support, as config models |
| `structure_binders.py` | Binders that write the geology and the catchment zones into a `Domain` |
| `support_fields.py` | The support fields that cut a domain into zones a parameter can vary on |
| `worker.py` | The `domain-build` job, from a request to a sealed output |

## Where to start

| To change | Open first |
|---|---|
| a `[domain]` key or its default | `domain_config.py`, `depth_model_config.py` or `layers_config.py` |
| how the base of the aquifer is placed | `domain.py` (`Domain._build_surfaces`), then the model in `depth_model_config.py` |
| the reading of a base raster | `build.py` |
| the layer bottoms, the pinch-out, `idomain` | `layering.py` |
| which cells are active | `active_cells.py` |
| a new kind of support | `spatial_support_config.py`, then a provider in `spatial_support.py` |
| how a support gives zone shares on a mesh | `support_fields.py` |
| the geology or the zones put on a domain | `structure_binders.py` |
| how the bathymetry follows the abacus | `lake_bed_regrid.py`, then `lake_bed_abacus.py` |
| the request or the output files of `domain-build` | `capability.py`, then `worker.py` |
| the content of `domain.json` | `domain_document.py` |

## Rules between the modules

The package reads `core`, `schema` and, until `spatial` is emptied, a few modules of `spatial/`.

- `depth_model_config.py`, `layers_config.py` and `spatial_support_config.py` import only `core`.
  `domain_config.py` reads these three and `core`.
- `layering.py` reads `layers_config.py` and `core`. It works on arrays only, so it knows no `Domain`.
- `build.py` and `domain.py` read the config modules, `spatial/surface.py` and `spatial/raster_support.py`.
- `support_fields.py` reads `model/properties/` (`Field` and `cell_sampling`) and
  `spatial/mesh/model/planar_cell_mesh.py`. `spatial_support.py` reads `support_fields.py` and the support
  config.
- `capability.py` reads `schema`, `depth_model_config.py` and `spatial/job_inputs.py`. `worker.py` reads
  `schema` and `spatial/job_inputs.py`, and `spatial/geographic/core/surface_from_dem.py` for the top
  surface.
- `active_cells.py` reads `core` and `schema.job.refusal`. `domain_document.py` reads `capability.py` and
  nothing else from HydroModPy.
- `structure_binders.py` reads `spatial/geographic/core/` and names `Domain` and `GeologyField` for
  typing only.
- `lake_bed_abacus.py` reads only `core.logging`. `lake_bed_regrid.py` reads it, `spatial/surface.py` and
  `spatial/surface_sampling.py`, and takes the mesh as an argument.
- Nothing in `model/properties/` imports `domain/`.

## What lives outside the package

The setup step, `workflow/steps/setup.py`, builds the domain of a run (`build_domain`) and rebuilds it
(`rebuild_domain`) when it is stale or the depth model of a trial moved. It also builds the supports of
a phase (`build_phase_supports`). The solvers read the layering through
`solver/modflow_grid/discretization_spatial.py`, which calls `layer_stack` and `assert_bottom_below_top`.
The caller of the lake bed is `carve_lake_bed` in `solver/modflow6/builders/lake_cells.py`. It reads the
`bed_reconstruction` table of each lake and imports the two lake bed modules inside the function, so a
run without a lake bed never loads them. The `[domain]` config is a field of `HydroModPyConfig`. The
calibration reads the depth models in `calibration/parameter_resolution.py`. The demo that builds a
`Domain` from a project TOML lives in `tools/cases/domain/`.

## Changing the code

The unit tests are in `tests/unit/model/domain/`, and a test file carries the name of the module it
tests. The worker is tested in `tests/integration/domain/test_worker.py`. The grids, surfaces, layerings
and masks come from `tests/_helpers/domain_cases.py`, and the lake bed meshes and columns from
`tests/_helpers/lake_bed_cases.py`. The CI job `mesh-coverage` in `.github/workflows/main-ci.yml` keeps a
coverage floor for the domain and one for the lake bed.

```bash
pytest tests/unit/model/domain tests/integration/domain -q
```

A new `[domain]` key is a field of the Pydantic model, with its description. The parameter reference is
built from the models, so the key needs no other page. The theory pages are
`docs/source/theory/groundwater-flow.md` (the top, the bottom and the layers), `docs/source/theory/mesh.md`
(layers by surfaces and the pinch-out) and `docs/source/theory/exits/lakes.md` (the active shore and the
carved bed). The support pages are in `docs/source/contribute/architecture/spatial_support/`.
