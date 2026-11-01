# workflow/site_selection

This package runs a site selection from a TOML file. It reads the `[site_selection]` table, loads the data the selection needs through the data layer (the gauging stations, the DEM, the BD Topage network), and hands everything to the `site_selection` layer, which does the selection itself. It is the code behind `hmp site select`.

The package is the only place in the selection chain that loads data for a selection. The `site_selection` layer in `hydromodpy/site_selection/` imports no `data` module, so the loaders and the download function of the reference network are passed to it from here. The report renderers come from the caller in the same way.

## How a selection runs

1. `hmp site select <file>` loads the renderers of `hydromodpy/reporting/site_selection/` and calls `run_site_selection` (`selection_run.py`).
2. `run_site_selection` reads the file, refuses a `[workflow] mode` key (a selection file is not a project file) and validates `[site_selection]` through `load_site_selection_config` (`data_loading.py`). It resolves the relative paths against the folder of the file (`config_paths.py`).
3. `[site_selection.input] mode` picks the action.
4. The action runs. A plan writes `site_selection_plan.json`. A CSV of catchments goes to the selection stage, after a delineation only when `delineate_from_outlets` is true. The other three modes load the data, resolve the DEM and call a builder of the `site_selection` layer.
5. The run returns a `SelectionRun` with the action, the counts and the paths of the files written.

```text
mode in [site_selection.input]
   |
   +-- plan_only ---------------> selection_plan.py          site_selection_plan.json
   +-- delineated_catchments ---> catchments_csv.py          selection stage only
   +-- hydrometry --------------> build_from_toml.py         stations, DEM, delineation, selection
   +-- generated_candidates ----> build_from_toml.py         DEM network, delineation, selection
   +-- dem_area_light ----------> build_from_toml.py         DEM network, area only
                                       |
                                       |  data_loading.py, dem_request.py
                                       v
                             hydromodpy/site_selection/pipelines/build.py
```

`hmp site select --dry-run` calls `plan_site_selection` and prints the plan without writing a file.

## The folder map

```text
site_selection/
├── selection_run.py      run_site_selection and SelectionRun, the dispatch on the input mode
├── selection_plan.py     the plan of a selection and its manifest, checked before any heavy work
├── build_from_toml.py    one builder per mode that loads data, then calls the selection build
├── catchments_csv.py     read a CSV of delineated catchments and run the selection stage on it
├── data_loading.py       hydrometry records and DEM file through the data layer, the config loaders
├── dem_request.py        which DEM to ask for and over which box, delineation from given outlets
└── config_paths.py       relative paths of the file, the default data root, the data access message
```

No `__init__.py` re-exports a name. Each name is imported from the module that defines it.

## The data it loads

For a station-led selection, `data_loading.py` asks the `DataStore` of `hydromodpy.data` for the hydrometry points of `[hydrometry]`, over the box of the territory in WGS84. The box is built in `dem_request.py`. The data layer owns the provider calls and the cache. A caller can pass its own loader, which is how the tests avoid the network.

The DEM comes from `dem.path` when the file gives one. Otherwise `dem_request.py` asks the data layer for the `[data.dem]` source over the box of the outlets or the territory, and passes the file path to the selection code. The review map can use a larger DEM than the calculation, set by `dem.map_background_extent`.

When an outlet snaps on a reference network, `build_from_toml.py` and `dem_request.py` give the selection code `fetch_bdtopage_reference_network` of `hydromodpy/data/sites/importers.py`. A failure in the data layer is raised as a `ConfigError` that names the `data_root` and the table to check (`data_access_error` in `config_paths.py`).

## Where to start

| To change | Open first |
|-----------|------------|
| which action a mode runs | `selection_run.py` |
| what the plan manifest holds | `selection_plan.py` |
| the order of the steps of a mode | `build_from_toml.py` |
| the columns of the CSV of catchments | `catchments_csv.py` |
| how the stations or the DEM are loaded | `data_loading.py` |
| the box asked for the DEM or the stations | `dem_request.py` |
| how a relative path or the data root is resolved | `config_paths.py` |
| a key of the selection file | `hydromodpy/site_selection/config/` |
| a criterion, a file written or a decision | `hydromodpy/site_selection/` |

## Rules with the rest of HydroModPy

The modules read each other in one direction. `config_paths.py` imports no module of the package. `data_loading.py` reads `config_paths.py`. `dem_request.py` reads these two, and `selection_plan.py` reads `data_loading.py`. `catchments_csv.py` and `build_from_toml.py` read these two and `dem_request.py` and `selection_plan.py`. `selection_run.py` reads `build_from_toml.py`, `catchments_csv.py`, `data_loading.py` and `selection_plan.py`.

All the imports of HydroModPy are at the top of the modules, none is deferred. The package imports:

- `core`: exceptions, logging and the TOML loader with its base config (`core.toml_io.loader`).
- `data`: `DataStore` (`hydromodpy.data`), the hydrometry and DEM config models (`data.variables`), the point and field contracts (`data.contracts`) and the BD Topage download (`data.sites.importers`).
- `site_selection`: the selection primitives in `hydromodpy/site_selection/`.
- `spatial`: `spatial/geographic/core` (flow products, catchment from a point) in `dem_request.py`.

It imports no `reporting`, `display`, `cli` or `project`. The renderers of the HTML report are arguments of `run_site_selection` (`ReportRenderer` in `selection_plan.py`), and the CLI command supplies them. `workflow` may import every layer below it, and the matrix is checked by `tests/unit/architecture/`.

## What lives outside the package

- `hydromodpy/cli/commands/site/select.py` is the command. It builds the renderers, shows the progress, maps an error to an exit code and, with `--into-catalog`, declares the selected sites in the site catalog.
- `hydromodpy/site_selection/` holds the selection itself. Its `README.md` explains the phases and the output files.
- `hydromodpy/reporting/site_selection/` draws the HTML report and the map from the manifest.
- This package is not a step of the project pipeline. A selection does not run through `hydromodpy/workflow/steps/`, and a project file refuses a `[site_selection]` table.

## Changing the code

The tests are in `tests/unit/workflow/site_selection/`, with the modules `test_selection_run.py`, `test_build_from_toml.py`, `test_data_loading.py` and `test_catchments_csv.py`. `selection_plan.py`, `dem_request.py` and `config_paths.py` are tested through them. The builders of `tests/_helpers/site_selection_cases.py` write the selection file, a basin and a vector layer, and the tests pass fake loaders so no provider is called. The command is tested in `tests/unit/cli/site/test_select.py`.

`tests/unit/architecture/test_site_selection_has_no_legacy_names.py` refuses retired names in this package. The CI job `mesh-coverage` in `.github/workflows/main-ci.yml` fails when the coverage of `hydromodpy/workflow/site_selection/*` drops below 96.4. The floor only goes up.

```bash
pytest tests/unit/workflow/site_selection tests/unit/cli/site -q
```

## Documentation

- `docs/source/reference/parameters/site-selection-file.md` lists every key of the selection file.
- `docs/source/reference/cli/site.md` documents `hmp site select`.
