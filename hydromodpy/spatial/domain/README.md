# spatial/domain

This package describes the aquifer as a body of rock. It takes the ground surface from the DEM, puts the base of the aquifer below it with a depth model, and cuts the column between the two into layers. It also holds the spatial supports, the maps (geology, catchment zones, bands, rings) that a parameter such as K can vary on. The mesh decides the cells in the plan, and this package decides what is above and below each cell.

## How the work flows

1. The `[domain]` table is read into a `DomainConfig` (`domain_config.py`). Its three parts are the depth model, the layers and the supports.
2. `build.py` builds a `Domain` (`domain.py`) from that config and a surface. The depth model gives the base of the aquifer, and the raster models read a base raster first.
3. The binders in `spatial/geographic/structure_binders.py` write the geology and the catchment zones into the domain, once the data is loaded. The catchment zones are a `CatchmentZonesField`, defined in `spatial/geographic/core/catchment_zones_field.py` beside the code that computes them.
4. The solvers read the layers. `layering.py` turns `[domain.layers]` and the two surfaces into the bottom and the `idomain` of every layer.
5. A heterogeneous parameter asks for a support. The provider in `spatial_support.py` builds a support field (`support_fields.py`), which gives the zone share of each cell of a mesh.

```text
[domain] table + DEM surface
        |
        |  build.py             one constructor
        v
      Domain                    top, base of the aquifer, layer bases, zones
        |
        +-->  layering.py       bottoms and idomain, read by the solvers
        +-->  spatial_support.py  zone maps for the parameters
```

The `domain-build` capability does steps 1 and 2 as a job. A request names a DEM and a depth model. The worker calls the same `build_domain`, writes the rasters of the top and the base, and seals a `domain.json` for the mesh generator.

## The depth models

There are four, and each one has its own `kind` in `depth_model_config.py`: `constant_thickness`, `flat_substratum`, `raster_substratum` and `raster_thickness`. The first two need no file. The two raster models read a raster from `[data.substratum]`, and `build.py` reads it (`read_substratum_source`). A layering by surfaces can also read one base raster per layer, and `read_layer_base_sources` reads them.

## The folder map

```text
domain/
├── domain.py               Domain, the surface, the base of the aquifer, the layer bases, the zones
├── build.py                the one constructor of a Domain, its rebuild with the zones carried over, and the readers of the base rasters
├── domain_config.py        the [domain] table
├── depth_model_config.py   the four depth models
├── layers_config.py        the [domain.layers] table
├── layering.py             layer bottoms, idomain and the pinch-out
├── active_cells.py         the cells of the domain, from the terrain or from a mask layer
├── spatial_support_config.py   the kinds of support, as config models
├── spatial_support.py      the support providers, their registry, and the contract (which supports the flow parameters ask for)
├── support_fields.py       the support fields, zone shares on the cells of a mesh
├── capability.py           the domain-build declaration and its request model
├── domain_document.py      the domain.json document written for the mesh generator
└── worker.py               the domain-build job, from a request to a sealed output
```

The demo that builds a Domain from a project TOML and draws a summary figure lives outside the package, in `tools/cases/domain/`.

No `__init__.py` re-exports a name. Each name is imported from the module that defines it.

## Where to start

| To change | Open first |
|-----------|------------|
| a `[domain]` key or its default | `domain_config.py`, `depth_model_config.py` or `layers_config.py` |
| how the base of the aquifer is placed | `domain.py` (`Domain._build_surfaces`), then the model in `depth_model_config.py` |
| the reading of a base raster | `build.py` |
| the layer bottoms, the pinch-out, `idomain` | `layering.py` |
| which cells are active | `active_cells.py` |
| a new kind of support | `spatial_support_config.py`, then a provider in `spatial_support.py` |
| how a support gives zone shares on a mesh | `support_fields.py` |
| the request or the output files of `domain-build` | `capability.py`, then `worker.py` |
| the content of `domain.json` | `domain_document.py` |

## Rules between the folders

The package is part of the spatial layer, which may import `core`, `schema` and itself. The architecture tests check that rule.

- `depth_model_config.py`, `layers_config.py` and `spatial_support_config.py` import only `core`. `domain_config.py` reads these three and `core`.
- `layering.py` reads `layers_config.py` and `core`. It works on arrays only, so it knows no `Domain`.
- `build.py` and `domain.py` read the config modules, `spatial/surface.py` and `spatial/raster_support.py`.
- `support_fields.py` reads `spatial/field/` (`Field`, `cell_sampling`) and `spatial/mesh/model/planar_cell_mesh.py`. `spatial_support.py` reads `support_fields.py` and the support config.
- `capability.py` reads `schema`, `depth_model_config.py` and `spatial/job_inputs.py` (the refusal of an absent input). `worker.py` reads `schema` and `spatial/job_inputs.py`. It also reads `spatial/geographic/core/surface_from_dem.py` for the top surface.
- `active_cells.py` reads `core` and `schema.job.refusal`. `domain_document.py` reads `capability.py` and nothing else from HydroModPy.
- Nothing in `field/` imports `domain/`. `geographic/structure_binders.py` imports `Domain` only for typing.
- Every import of HydroModPy is at the top of its module. None is deferred inside a function.

## What lives outside the package

The setup step, `hydromodpy/workflow/steps/setup.py`, builds the domain of a run (`build_domain`) and rebuilds it (`rebuild_domain`) when it is stale or the depth model of a trial moved, reading the base rasters for it. It also builds the supports of a phase (`build_phase_supports`, through `step_spatial_supports`). `hydromodpy/workflow/steps/prepare_solver/prepare.py` and `hydromodpy/project/facade.py` import `Domain` for typing only.

The solvers read the layering through `hydromodpy/solver/modflow_grid/discretization_spatial.py`, which calls `layer_stack` and `assert_bottom_below_top`. The `[domain]` config is a field of `HydroModPyConfig` in `hydromodpy/config/hydromodpy_config.py`. The calibration reads the depth models in `hydromodpy/calibration/parameter_resolution.py`.

The `domain-build` declaration is `DOMAIN_BUILD` in `capability.py`. Its JSON schema is `hydromodpy/schema/processes/domain-build@1.json`, and `hydromodpy/spatial/job_inputs.py` holds its input checks.

## Changing the code

The unit tests are in `tests/unit/domain/`. A test file carries the name of the module it tests, for example `test_layering.py` for `layering.py`. The worker is tested in `tests/integration/domain/test_worker.py`. `active_cells.py`, `domain_document.py` and `capability.py` have no test file of their own. `test_build.py` and the worker test cover them. The grids, surfaces, layerings and masks come from `tests/_helpers/domain_cases.py`.

Two more checks guard the package. `tests/contract/test_a_stack_with_inactive_and_pass_through_cells_reads_back.py` checks that a stack with pass-through cells reads back. The architecture tests check the layer rules. The CI job `mesh-coverage` in `.github/workflows/main-ci.yml` fails when the coverage of this package drops below 99.3.

```bash
pytest tests/unit/domain tests/integration/domain -q
```

```bash
pytest tests/unit/architecture -q
```

A new `[domain]` key is a field of the Pydantic model, with its description. The parameter reference is built from the models, so the key needs no other page.

## Documentation

- `docs/source/reference/parameters/domain.md` is the generated reference of the `[domain]` table.
- `docs/source/theory/groundwater-flow.md` covers the top, the bottom and the depth models, and the layers.
- `docs/source/theory/mesh.md` covers the layers by surfaces and the pinch-out.
- `docs/source/theory/solvers/field-to-cell-parameter-transfer.md` covers how a zone map becomes cell values.
- `docs/source/contribute/architecture/spatial_support/` covers the supports, with `support-selection-guide.rst` to choose one.
- `docs/source/contribute/architecture/how-to/add-a-config-field.rst` explains how to add a config key.
