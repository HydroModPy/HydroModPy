# Site Selection Package

This package contains the spatial and audit primitives for the upstream
`site_selection` workflow. It is intentionally narrower than `regional_lab`:
it builds or filters basin candidates and explains the decision. It does not
expand sites into simulation recipes and it does not run solvers.

## Boundaries

The package is responsible for:

- typed site-selection configuration models;
- candidate outlet records;
- delegation to existing DEM flow-product and catchment-delineation code;
- auditable criterion components and selection decisions;
- CSV/JSONL exports for selected and rejected sites;
- the official `site_selection_manifest.json` contract;
- an optional static HTML review page generated from the manifest.

The package is not responsible for:

- Hub'Eau API details or cache management;
- reimplementing D8, flow accumulation or watershed delineation;
- `regional_lab` recipe expansion;
- MF6, Boussinesq, calibration or comparison execution.

Observation and hydrometry loading lives in `hydromodpy.workflow.site_selection`
and `hydromodpy.workflow.site_selection_data`, which call the existing data
manager stack and pass normalized `PointRecord` objects into the spatial build
pipeline.

For station-led French workflows, observation APIs and hydrologic products do
not use the same CRS. Hub'Eau station locations are fetched in WGS84 for API
queries, while IGN DEMs and catchment delineation use Lambert-93. The workflow
therefore resolves the observation bbox in WGS84, then `candidate_outlets.py`
projects station locations to the DEM/project CRS before delineation. When
Hub'Eau provides `x_l93` and `y_l93` metadata, those official Lambert-93
coordinates are used directly.

DEM loading follows the same boundary. `site_selection` may request
`delineate_from_outlets = true`, but the DEM itself should be declared under
`[data.dem]` and cached by the data manager stack. The workflow resolves the
DEM file path before calling flow-product and catchment-from-point utilities.
This keeps provider access, cache layout and regional data extents outside the
selection primitives.

In `site_selection.input.mode = "hydrometry"`, the same rule applies: the
workflow loads hydrometry through the existing data managers, resolves the DEM
through `[data.dem]`, builds flow products, and only then delegates to the
spatial selection primitives. The spatial package does not call Hub'Eau or
Geoplateforme directly.

Pre-delineated CSV inputs may also contain already-normalized observation
columns such as `flow_station_id`, `flow_station_x`, `piezometer_id` and
`piezometer_x`. These columns are converted into the same normalized evidence
schema used by provider-loaded `PointRecord` objects. They are intended for
fixtures, catalogs and frozen data extracts, not for direct provider access.

## Main Modules

- `config.py`: Pydantic configuration and validation.
- `candidate_outlets.py`: candidate outlet records and spacing helpers.
- `flow_products_adapter.py`: thin adapter to existing regional DEM flow products.
- `delineation.py`: thin adapter to existing catchment-from-point utilities.
- `criteria.py`: auditable criterion components for area, observation evidence,
  anthropic influence and geology evidence.
- `selection.py`: selected/rejected catchment decisions.
- `schemas.py`: stable output schemas and row builders.
- `exports_tabular.py`: CSV and JSONL writers.
- `exports_geojson.py`: GeoJSON writers for outlets, basins and observations.
- `exports.py`: public export facade used by workflow code and callers.
- `manifest.py`: official manifest construction and IO.
- `artifacts.py`: final manifest/report assembly.
- `figures.py`: static map figure generated from manifest artifacts.
- `html_report.py`: optional HTML v0 renderer from the manifest.
- `plan_report.py`: optional HTML renderer for plan-only runs.
- `build.py`: station-led spatial build from already-loaded observations.

## Output Contract

Completed selection runs always write the audit core:

- `selection_decisions.jsonl`
- `criteria_components.jsonl`
- `site_selection_manifest.json`

With the default GeoJSON switch they also write:

- `selected_outlets.geojson`
- `rejected_outlets.geojson`
- `selected_basins.geojson`
- `rejected_basins.geojson`

With the default tabular switches they also write:

- `selected_sites.csv`
- `rejected_sites.csv`
- `regional_lab_sites.csv`

If `site_selection.output.write_report_html = true`, they also write:

- `review/index.html`
- `review/site_selection_map.png`

Plan-only runs use a lighter contract:

- `site_selection_plan.json` when `site_selection.input.write_plan_manifest = true`
  or when an HTML report is requested;
- `review/index.html` when `site_selection.output.write_report_html = true`.

The plan-only HTML explicitly states that no site has been selected or rejected.
It is intended for reviewing strategy, territory, required data and planned
outputs before running hydrometry loading or DEM-based delineation.

The outlet GeoJSON files are point geometries. The basin GeoJSON files contain
the corresponding watershed contours when the delineation stage produced a
readable vector file. If a contour is missing, the file is still written and the
missing basin is listed in `hydromodpy_skipped_basins`.

Observation-led builds also write:

- `observation_evidence.jsonl`
- `observation_points.geojson`

Observation points are derived from normalized evidence, not from provider-
specific raw schemas. This allows the same review map to symbolize flow stations,
piezometers or future observation types once their coordinates are available.

The HTML map is a figure of control. It is generated from the manifest-declared
GeoJSON artifacts, colors selected basin contours by area class, and uses
separate symbols for selected outlets, rejected outlets when present, flow
stations, piezometers and future observation point types.
Optional `site_selection.map_context.layers` can add static context layers such
as a territory outline, simplified hydrography or geology. These layers are for
visual review only; they do not replace criterion evidence.

GeoParquet, candidate catalog export and Markdown reports are deliberately not
enabled by default until their writers are implemented.

## Selection Outputs

`selected_sites.csv` and `regional_lab_sites.csv` currently share the same
stable column contract:

- `site_id`: stable selected basin identifier.
- `site_label`: human-readable label, defaulting to `site_id`.
- `region_id`: optional campaign or administrative region identifier.
- `source_selection_id`: selection campaign that produced the row.
- `site_status`: selection status, usually `selected`.
- `maturity`: downstream maturity flag, for example `screening`.
- `x`, `y`: outlet coordinates in the outlet CRS.
- `x_outlet`, `y_outlet`: explicit outlet coordinates in the outlet CRS.
- `area_km2`: delineated catchment area when available.
- `tags`: semicolon-separated provenance tags.
- `enabled`: boolean flag used by downstream catalog loaders.

`selection_decisions.jsonl` contains one final decision per candidate basin.
`criteria_components.jsonl` contains the detailed criterion evidence behind
those decisions. This separation is intentional: downstream tools can use the
final decision file directly, while review tools can inspect the criterion
components without re-running selection.

`selected_basins.geojson` is the spatial association between selected sites and
their watershed contours. It is intentionally separate from `selected_sites.csv`:
the CSV remains a lightweight catalog, while the GeoJSON carries geometries and
can be used directly by maps or GIS tools.

## Criterion Families

The current criterion layer is intentionally extensible:

- area can be a hard rejection, a warning, a score, a stratification axis or a
  report-only attribute;
- flow-station evidence can check record length, station-to-outlet distance and
  whether the station is inside or at the outlet;
- piezometer evidence can be reported, scored, warned on, stratified or used as
  a hard criterion through `piezometer_mode`;
- influence checks consume explicit flags such as upstream dam, major
  withdrawal or regulated reach;
- geology is currently an evidence and stratification hook, because the exact
  geological rules are expected to vary by campaign.

Unknown influence evidence is not treated as a hard rejection by default. A
hard rejection is applied only when a configured rejection flag is explicitly
present. This avoids silently discarding candidates because a regional data
layer has not yet been loaded.

## Manifest Validation

`site_selection_manifest.json` is the official hand-off contract. Use
`validate_selection_manifest()` or `hmp site-selection report` to check that
the manifest has the expected schema version and that referenced output files
exist. The HTML report is intentionally derived from the manifest and its
declared artifacts; it should not become a second source of truth.
