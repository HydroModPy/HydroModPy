# `hydromodpy/site_selection`

This package picks the catchments that fit a study from a large set of possible ones. A candidate is an outlet, taken from a gauging station or sampled on the stream network of a DEM. The package delineates the catchment above each outlet, adds what is known about it (stations, piezometers, dams, geology), applies the criteria of the selection file and keeps or rejects each basin with a written reason. It writes the audit files, the selected sites and a manifest. It does not run a solver and it does not read any data provider. The data and the run of a selection file are in `hydromodpy/workflow/site_selection/`.

The package is a layer of its own, because it answers another question than `spatial`. `spatial` describes the model of one catchment in space, while this package chooses which catchments a study should model. It reads the spatial blocks it needs (the terrain engines, the delineation backends, the flow products and the catchment from a point), and no part of `spatial` reads it.

The package also holds the `terrain-delineate` capability, in `hydrology/`. It delineates catchments from a DEM and a list of outlets inside one job directory and seals it.

## How a selection is made

A selection goes through these steps. The functions of `pipelines/build.py` run them in this order.

1. The tables of the selection file are read into `SiteSelectionFile` (`config/`).
2. The candidates are made (`candidates/`). Station outlets come from loaded `PointRecord` objects. Generated outlets are sampled on the accumulation raster of the DEM. An outlet can be moved onto a reference stream network first.
3. The flow products of the DEM are built and one catchment is delineated per outlet (`hydrology/`). The result is a `DelineatedCatchment` (`domain/`).
4. Each catchment is annotated with the influence, geology and piezometer layers of the file (`evidence/`).
5. The criteria give one component per criterion and per basin, then the selection keeps or rejects the basin (`evaluation/`). The selection also applies the spatial quota, the spacing between outlets and the overlap rule.
6. The components and the decisions become normalized records (`decisions/`).
7. The files and the manifest are written (`outputs/`).

```text
selection file ([site_selection], [hydrometry], [data.dem])
        |
        |  config/                 SiteSelectionFile
        v
   candidate outlets               candidates/
        |
        |  hydrology/              flow products, then one catchment per outlet
        v
   DelineatedCatchment             domain/
        |
        |  evidence/               influence, geology, piezometers
        |  evaluation/             criteria, then keep or reject
        |  decisions/              DecisionRecord, EvidenceRecord
        v
   SelectionResult  ------>  outputs/  ------>  files + site_selection_manifest.json
```

The workflow layer calls the builders of `pipelines/build.py`. It hands them the loaded station records, the DEM path and the fetcher of the reference network, so this package never reads Hub'Eau, a data store or a network.

## The input modes

`[site_selection.input] mode` names the action. The workflow layer dispatches it.

| mode | what runs |
|------|-----------|
| `plan_only` | the file is checked and the plan manifest is written, no spatial work |
| `hydrometry` | station-led selection, with the stations loaded through the data layer |
| `generated_candidates` | outlets sampled on the DEM stream network (`candidate_mode = "network_sampling"`) |
| `dem_area_light` | a light selection on basin area only |
| `delineated_catchments` | the selection stage alone, on a CSV of catchments delineated beforehand |

Two strategy profiles are supported. `gauged_downstream_station` goes with `principle = "observation_led"` and station outlets. `area_only` goes with `criteria_crossing` and area as the only axis. `config/strategy_config.py` refuses any other mix. The keys, their defaults and their values are in the generated reference, so they are not repeated here.

## Outlets and the reference network

An outlet is snapped in one of two ways, set by `[site_selection.outlets] snap_strategy`.

- `dem_accumulation` moves the point onto the accumulation raster of the DEM. It searches a square window whose width is `snap_dist_m`, so a point can move further than `snap_dist_m` along a diagonal (see `snap_window_cells` in `spatial/terrain/port.py`).
- `bdtopage_then_dem` first projects the point onto a reference stream network (BD Topage, or a network the user gives) and refuses the site when the network is farther than `reference_network_max_distance_m`. Then it snaps on the DEM as in the first case.

The reference network only keeps the outlet near the observed station and river line. The catchment is still delineated from the DEM flow direction and accumulation. `hydrology/reference_network.py` does the snapping and receives the download function as an argument, so it imports nothing from `data`.

Station locations come in WGS84 from Hub'Eau. `candidates/outlets.py` projects them to the CRS of the DEM before the delineation, and uses the Lambert-93 coordinates of the provider when it gives them.

## Criteria and decisions

Each module of `evaluation/criteria/` holds one or more criterion families: basin area, flow stations, station influence, piezometers, influence flags and geology. A criterion can reject, warn, score, stratify or only report, as its `mode` says. A basin with no influence flag gets the status `missing`, so it is never rejected for lack of data. Only a flag that is explicitly true, and that the file lists as a rejection flag, fails the basin.

`station_influence` reads the metadata of the station. It cannot tell that a dam exists upstream of the basin, which needs the influence layers of `evidence/influence.py`.

The criteria components go to `criteria_components.jsonl`. `decisions/` turns each component and each final decision into a `DecisionRecord` with one of `ACCEPT`, `WARNING`, `REJECT` or `NEUTRAL`, and `decisions/aggregate.py` gives one summary row per catchment. Evidence rows carry an `evidence_ref` (`domain/refs.py`) so a decision can point to the feature behind it.

## The output files

A completed run always writes the audit core: `criteria_components.jsonl`, `site_selection_decisions.csv`, `site_selection_decisions.jsonl` and `site_selection_manifest.json`, plus `site_selection_evidence.jsonl` when there is evidence. The `write_*` switches of `[site_selection.output]` turn on or off the selected and rejected sites as CSV, the outlets and basins as GeoJSON, GeoParquet or one GeoPackage, and the evidence layers. A generated run also writes `candidate_generation.jsonl`, `candidate_outlets.geojson` and `generated_dem_network.geojson`. Every GeoJSON follows RFC 7946: its coordinates are WGS 84 longitudes and latitudes, it has no `crs` member, and `hydromodpy_project_crs` names the CRS the features came from. The GeoPackage and GeoParquet layers keep the project CRS, and a number that does not exist is null there where the CSV and the GeoJSON write `""`. `write_report_html` adds `review/index.html` and its map, drawn by `hydromodpy/reporting/site_selection/`.

The manifest is the hand-off. A consumer reads it and never a fixed file name, because the manifest says which file holds each output key. `selected_sites.csv` is the table that `hmp site import --selection` reads into the site catalog, and its columns are `SELECTED_SITES_FIELDS` in `outputs/schemas.py`. The schema and the check of the manifest are in `hydromodpy/schema/site_selection_manifest.py` (`validate_selection_manifest`).

A plan-only run writes `site_selection_plan.json` instead, built in the workflow layer.

## The folder map

```text
site_selection/
├── config/                       the tables of the selection file
│   ├── site_selection_config.py  SiteSelectionConfig, SiteSelectionFile, input, output and map context
│   ├── strategy_config.py        [strategy] and [territory]
│   ├── outlets_config.py         [outlets] and [spatial_selection]
│   ├── dem_config.py             the DEM and hydrology tables, and the light area mode
│   ├── criteria_config.py        one table per criterion family, and their layers
│   └── value_types.py            the literal value types, with the text of each value
│
├── domain/                       the records that every phase shares
│   ├── candidate_outlet.py       CandidateOutlet
│   ├── delineated_catchment.py   DelineatedCatchment, snapped outlet and its distance
│   ├── observation_evidence.py   ObservationEvidence, what a station or piezometer says
│   ├── station_influence.py      the influence of a station, from its metadata
│   ├── attribute_values.py       one text, number or flag out of the attributes of a site
│   ├── refs.py                   stable evidence_ref strings
│   ├── watershed.py              read the watershed file of a delineation
│   └── export_values.py          values the vector exports write
│
├── candidates/                   from stations or the DEM network to outlets
│   ├── outlets.py                outlets from station records, and thinning
│   ├── generation.py             outlets sampled on the DEM stream network
│   └── pipeline.py               the candidate phases, territory and reference network loading
│
├── hydrology/                    from outlets to catchments
│   ├── flow_products.py          the flow products of the DEM for a selection
│   ├── delineation.py            one catchment per outlet, and the batch
│   ├── reference_network.py      snap an outlet on a reference stream network
│   ├── capability.py             the terrain-delineate declaration and its request model
│   └── worker.py                 terrain-delineate, one job directory in and one seal out
│
├── evidence/                     what is known about each catchment
│   ├── annotations.py            the annotation phase over all the layers
│   ├── observations.py           observation evidence from records or attributes
│   ├── influence.py              dams, withdrawals and regulated reaches upstream
│   ├── geology_layers.py         dominant geology and surface fractions
│   └── piezometer_layers.py      piezometers inside each basin
│
├── evaluation/                   keep or reject
│   ├── selection.py              SelectionResult, quota, spacing and overlap
│   ├── spatial_filters.py        the overlap fraction between two basins
│   └── criteria/                 one module per criterion family
│       ├── common.py             CriteriaComponent, the shared primitives
│       ├── area.py               basin area
│       ├── observations.py       flow stations, station influence, piezometers
│       ├── influence.py          influence flags
│       └── geology.py            geology
│
├── decisions/                    the audit records
│   ├── models.py                 DecisionRecord, EvidenceRecord, SiteDecisionSummary
│   ├── records.py                records from the components and the decisions
│   ├── evidence_records.py       evidence records from each kind of evidence
│   └── aggregate.py              one summary row per catchment
│
├── outputs/                      the files of a run
│   ├── writer.py                 the core outputs, the entry point of the phase
│   ├── manifest.py               build and write the manifest, call the report renderer
│   ├── schemas.py                the columns of selected_sites.csv and its row builder
│   ├── tabular.py                CSV and JSONL writers
│   ├── decision_files.py         decision, evidence and summary files
│   ├── evidence_files.py         observation and evidence outputs
│   ├── evidence_layers.py        vector layers of the geology and influence evidence
│   ├── candidate_files.py        candidate generation files
│   ├── features.py               properties and geometries of the vector exports
│   ├── geojson.py                GeoJSON writers
│   ├── geospatial.py             GeoPackage and GeoParquet writers
│   └── cleanup.py                remove the intermediate rasters
│
└── pipelines/                    the whole build
    └── build.py                  the builders of each input mode and the selection stage
```

No `__init__.py` re-exports a name. Each name is imported from the module that defines it.

## Where to start

| To change | Open first |
|-----------|------------|
| a key of the selection file or its default | `config/`, the table that owns it |
| how outlets are taken from stations | `candidates/outlets.py` |
| how outlets are sampled on the DEM network | `candidates/generation.py` |
| the territory a search covers, its default CRS and the Lambert-93 check | `candidates/pipeline.py` |
| how an outlet is snapped | `hydrology/reference_network.py`, then `hydrology/delineation.py` |
| a criterion | `evaluation/criteria/<family>.py` |
| the quota, the spacing or the overlap rule | `evaluation/selection.py` |
| what a layer says about a basin | `evidence/` |
| the text or the status of a decision | `decisions/records.py` |
| a column of `selected_sites.csv` | `outputs/schemas.py` |
| a written file or the manifest | `outputs/`, then `hydromodpy/schema/site_selection_manifest.py` |
| the order of the phases | `pipelines/build.py` |
| what `terrain-delineate` accepts or writes | `hydrology/capability.py` |
| what `terrain-delineate` does | `hydrology/worker.py` |

## Rules between the folders and with the rest of HydroModPy

The folders read each other in one direction, from the records and the config up to the pipeline.

- `config/` and `domain/` import only themselves.
- `hydrology/` and `evidence/` read `config/` and `domain/`.
- `evaluation/` reads `config/` and `domain/`.
- `candidates/` reads `config/`, `domain/` and `hydrology/reference_network.py`.
- `decisions/` reads `domain/`, `evaluation/` and `evidence/`.
- `outputs/` reads every other folder but `pipelines/`.
- `pipelines/` reads every other folder except `decisions/`. Nothing else in the package imports it, the workflow does.

`tests/unit/architecture/layer_matrix.yaml` gives the layer `core`, `schema` and `spatial`, and the code imports nothing else:

- `core`: CRS helpers, the config base classes (`config_kit`), exceptions, logging, the French administrative names and the GeoParquet writer.
- `schema`: the site selection manifest (`outputs/manifest.py`), and the job documents, the capability declaration and the media types (`hydrology/capability.py`, `hydrology/worker.py`).
- `spatial`: `spatial/geographic/core` (flow products, catchment from a point), `spatial/delineation/registry.py`, `spatial/terrain/registry.py`, `spatial/job_inputs.py`, and `spatial/administrative/france.py`.

Two layers import the package. `workflow/site_selection/` runs a selection file through it. `data/sites/importers.py` moves the outlets of `hmp site import` onto a reference network with `CandidateOutlet` and `hydrology/reference_network.py`, which is why the matrix gives `data` this layer.

Two imports of HydroModPy are inside a function. `candidates/pipeline.py` imports `spatial/administrative/france.py` only when the territory is a set of French departments or regions. `config/site_selection_config.py` imports `spatial/terrain/registry.py` in the validator of `terrain_engine`, which runs only when an engine is named. Some geospatial libraries (geopandas, shapely, pyproj) are also imported inside the functions that use them.

The package never imports `data`, `workflow`, `reporting` or `display`, so the edge from `data` makes no cycle. The BD Topage download function and the report renderers are arguments that the workflow layer passes in. The layer rules are checked by `tests/unit/architecture/`.

## What lives outside the package

- `hydromodpy/workflow/site_selection/` reads the TOML, loads the hydrometry records and the DEM through `data`, resolves the paths, writes the plan manifest and calls the builders here. Its map is in its own `README.md`.
- `hydromodpy/cli/commands/site/select.py` is `hmp site select`. It passes the renderers of `hydromodpy/reporting/site_selection/` to the run.
- `hydromodpy/data/sites/` is the site catalog. `importers.py` reads `selected_sites.csv` through the manifest (`hmp site import --selection`), holds the BD Topage download and snaps imported outlets with `hydrology/reference_network.py`.
- `hydromodpy/schema/site_selection_manifest.py` holds the manifest name, its writer and its check.
- `hydromodpy/spatial/` holds the blocks the package reads: `terrain/` with the flow-routing engines that `hydrology/` calls, `delineation/`, `geographic/core/`, `administrative/` and `job_inputs.py`, the input checks `terrain-delineate` shares with `domain-build`. `hydromodpy/schema/processes/terrain-delineate@1.json` is the generated description of the capability.

## Changing the code

The tests mirror the code under `tests/unit/site_selection/`, one folder per folder, with `test_<module>.py` for most modules. A few small modules are tested through the module that calls them. For example `evidence/annotations.py` runs inside the whole build of `tests/unit/site_selection/pipelines/test_build.py`. The shared builders are in `tests/_helpers/site_selection_cases.py`. They write a selection TOML, a basin and a vector layer, and give fake flow products.

Other tests guard the package.

- `tests/integration/site_selection/test_terrain_delineate_seals_a_job.py` runs `terrain-delineate` on a job directory.
- `tests/unit/schema/test_process_descriptions.py` and `tests/unit/schema/test_a_chain_feeds_one_job_from_another.py` read its declaration.
- `tests/contract/test_terrain_engine_contract.py` holds what every terrain engine must do.
- `tests/unit/architecture/test_site_selection_has_no_legacy_names.py` refuses retired names in this package, in the workflow package and in the CLI command.

The CI job `mesh-coverage` in `.github/workflows/main-ci.yml` fails when the coverage of `hydromodpy/site_selection/*` drops below 96.4. The floor only goes up.

```bash
pytest tests/unit/site_selection -q
```

```bash
pytest tests/unit/architecture -q
```

A new key of the selection file is a field of the Pydantic model in `config/`, with its description. The parameter page is built from that model, so the key needs no other page.

## Documentation

- `docs/source/reference/parameters/site-selection-file.md` lists every key of the selection file. It is generated from `config/`.
- `docs/source/reference/cli/site.md` documents `hmp site select`.
- `docs/source/contribute/architecture/how-to/add-a-block-html-report.rst` shows how the review map of a selection is drawn.
