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
- the generic `report_artifact_manifest.json` report-artifact contract;
- downstream hand-off references for catalog consumers;
- an optional static HTML review page built from the manifest.

The package is not responsible for:

- Hub'Eau API details or cache management;
- reimplementing D8, flow accumulation or watershed delineation;
- `regional_lab` recipe expansion;
- testbed child-workflow orchestration;
- MF6, Boussinesq, calibration or comparison execution.

Observation and hydrometry loading lives in `hydromodpy.workflow.site_selection`
and `hydromodpy.workflow.site_selection_data`, which call the existing data
manager stack and pass normalized `PointRecord` objects into the spatial build
pipeline.

For station-led French workflows, observation APIs and hydrologic products do
not use the same CRS. Hub'Eau station locations are fetched in WGS84 for API
queries, while IGN DEMs and catchment delineation use Lambert-93. The workflow
therefore resolves the observation bbox in WGS84, then `candidates/outlets.py`
projects station locations to the DEM/project CRS before delineation. When
Hub'Eau provides `x_l93` and `y_l93` metadata, those official Lambert-93
coordinates are used directly.

DEM loading follows the same boundary. `site_selection` may request
`delineate_from_outlets = true`, but the DEM itself should be declared under
`[data.dem]` and cached by the data manager stack. The workflow resolves the
DEM file path before calling flow-product and catchment-from-point utilities.
This keeps provider access, cache layout and regional data extents outside the
selection primitives.

Outlet snapping has two explicit strategies:

- `site_selection.outlets.snap_strategy = "dem_accumulation"` keeps the direct
  path: the candidate point is snapped to the DEM-derived accumulation raster
  with the short radius `dem_snap_max_distance_m`.
- `site_selection.outlets.snap_strategy = "bdtopage_then_dem"` first projects
  the candidate point onto BD Topage or a custom reference network, rejects the
  site if that network is farther than `reference_network_snap_max_distance_m`,
  then runs the DEM snap locally with `dem_snap_max_distance_m`.

The reference-network strategy constrains the outlet to stay near the observed
station and river line. It does not replace the DEM: watershed delineation still
uses DEM flow direction and accumulation rasters.

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

The package is organized by workflow phase. Code should import detailed
processing primitives from the subpackages below. The top-level
`hydromodpy.spatial.site_selection` facade is intentionally small and exposes
only stable workflow entrypoints, manifest helpers and report renderers.

- `config/`: Pydantic configuration and validation models.
- `domain/`: shared domain records that are not tied to one processing phase.
- `candidates/`: candidate outlet records, DEM/network candidate builders,
  station-led candidate building, thinning, and reference-network snapping.
- `hydrology/`: thin adapters to existing DEM flow-product and
  catchment-from-point utilities, plus batch delineation.
- `evidence/`: observation evidence, context-layer annotation, influence,
  geology, piezometry, stable evidence references, and evidence exports.
- `evaluation/criteria/`: auditable area, observation, influence and geology
  criterion components.
- `evaluation/selection.py`: final selected/rejected catchment decisions,
  including spatial quota, outlet spacing and overlap rules.
- `evaluation/spatial_filters.py`: geometry overlap helpers used by selection.
- `outputs/`: stable output schemas, CSV/JSONL/GeoJSON/geospatial writers,
  manifest IO, core output orchestration and final artifact assembly.
- `reports/`: static map, HTML report, plan report and report blocks.
- `decisions/`: normalized `DecisionRecord`, `EvidenceRecord` and
  per-catchment summary helpers built from criteria and final selections.
- `pipelines/build.py`: orchestration of the end-to-end spatial build phases.

## Output Contract

Completed selection runs always write the audit core:

- `criteria_components.jsonl`
- `site_selection_decisions.csv`
- `site_selection_decisions.jsonl`
- `site_selection_evidence.jsonl` when at least one normalized evidence row is
  available
- `site_selection_manifest.json`
- `report_artifact_manifest.json`

With the default GeoJSON switch they also write:

- `selected_outlets.geojson`
- `rejected_outlets.geojson`
- `selected_basins.geojson`
- `rejected_basins.geojson`

With the default tabular switches they also write:

- `selected_sites.csv`
- `rejected_sites.csv`
- `regional_lab_sites.csv`

With production vector switches they can also write:

- `site_selection.gpkg` when `site_selection.output.write_geopackage = true`;
- `selected_outlets.parquet`, `rejected_outlets.parquet`,
  `selected_basins.parquet`, `rejected_basins.parquet` when
  `site_selection.output.write_geoparquet = true`.

When influence layers are configured under
`site_selection.criteria.influence.layers`, completed runs also write:

- `influence_evidence.jsonl`
- `influence_features.geojson` when `write_geojson = true`
- `influence_features.parquet` when `write_geoparquet = true`
- an `influence_features` layer in `site_selection.gpkg` when
  `write_geopackage = true`

When geology layers are configured under
`site_selection.criteria.geology.layers`, completed runs also write:

- `geology_evidence.jsonl`
- `geology_basins.geojson` when `write_geojson = true`
- `geology_basins.parquet` when `write_geoparquet = true`
- a `geology_basins` layer in `site_selection.gpkg` when
  `write_geopackage = true`

When piezometer layers are configured under
`site_selection.criteria.observations.piezometer_layers`, completed runs also
write:

- `piezometer_evidence.jsonl`
- piezometer rows in `observation_evidence.jsonl`
- piezometer point geometries in `observation_points.geojson`,
  `observation_points.parquet` and the `observation_points` GeoPackage layer
  when their corresponding output switches are active.

If the generic report contract declares `[report.html] build_at_end = true`
for the `site_selection` profile, completed runs also write:

- `review/index.html`
- `review/site_selection_map.png`

Plan-only runs use a lighter contract:

- `site_selection_plan.json` when `site_selection.input.write_plan_manifest = true`
  or when an HTML report is requested;
- `report_artifact_manifest.json` when the plan manifest is written;
- `review/index.html` when `[report.html] build_at_end = true`.

The plan-only HTML explicitly states that no site has been selected or rejected.
It is intended for reviewing strategy, territory, required data and planned
outputs before running hydrometry loading or DEM-based delineation.

DEM target-area runs use `site_selection.input.mode = "dem_area_target"`.
This is the simplified DEM path for "find basins around this upstream area"
campaigns: candidate outlets are ranked by their distance to
`site_selection.dem_area_target.target_area_km2`, then delineated and selected
with the normal area and spatial criteria.

DEM network sampling runs use `site_selection.input.mode =
"dem_network_sampling"` with `site_selection.outlets.candidate_mode =
"network_sampling"`. This is the lower-level stream-network sampling path: it
exposes outlet-construction controls such as spacing, candidate caps and optional
reference-network scoring. It remains outside the short-term stable business
contract, but it is kept as a tested capability. It writes the normal selection
outputs plus:

- `candidate_generation.jsonl`
- `candidate_outlets.geojson` when `write_geojson = true`
- `dem_network.geojson` when `write_geojson = true`

These candidates come from high-accumulation DEM cells, constrained by
`min_distance_between_outlets_km` and `max_network_candidates`, then pass
through the same delineation and selection stages as imported or station-led
candidates. The candidate audit includes accepted and rejected candidate cells,
with rejection reasons such as spacing or candidate-count caps. When a BD
Topage/custom reference network is loaded, candidates also carry
`reference_network_distance_m`, `reference_network_score` and
`reference_network_status`.

DEM-derived candidates and their exported DEM network are clipped to the
configured territory by default (`territory.clip_to_territory = true`). For
French administrative territories, this uses the union of department or region
geometries rather than only the rectangular DEM extent, which avoids sampling
coastal sea cells.

The outlet GeoJSON files are point geometries. When a delineation produced an
`outlet_snap_shp`, selected outlet geometries use the snapped outlet point and
preserve the original candidate coordinates in properties. If no snapped point
is available, the outlet geometry remains the original candidate point. The
basin GeoJSON files contain the corresponding watershed contours when the
delineation stage produced a readable vector file. If a contour is missing, the
file is still written and the missing basin is listed in
`hydromodpy_skipped_basins`.

When `bdtopage_then_dem` is active, outlet GeoJSON properties also carry
`reference_network_source`, `reference_network_snap_distance_m`,
`reference_network_original_x/y` and `reference_network_x/y` so reviewers can
separate the station-to-reference-network adjustment from the later DEM snap.

Observation-led builds also write:

- `observation_evidence.jsonl`
- `observation_points.geojson`

When production vector switches are active, observation points are appended to
the `observation_points` layer in `site_selection.gpkg` and written as
`observation_points.parquet` when they have usable coordinates.

Observation points are derived from normalized evidence, not from provider-
specific raw schemas. This allows the same review map to symbolize flow stations,
piezometers or future observation types once their coordinates are available.

The HTML map is a figure of control. It is built from the manifest-declared
GeoJSON artifacts, colors selected basin contours by area class with light
fills and thin edges, and uses separate symbols for selected outlets, rejected
outlets when present, flow stations, piezometers and future observation point
types. For DEM-network runs, it also draws the vectorized DEM network
from `dem_network.geojson`. When outlets were snapped, the map draws
the snapped outlet and a dashed station-to-outlet link for visible
displacements.
Optional `site_selection.map_context.layers` can add static context layers such
as a territory outline, simplified hydrography or geology. These layers are for
visual review only; they do not replace criterion evidence.

Automatic influence layers are stricter than map context layers. They are
declared under `site_selection.criteria.influence.layers`, intersected with
delineated basin contours when available, and converted into normalized flags
such as `major_dam_upstream`, `major_withdrawal_upstream` and
`major_regulated_reach`. These flags are then consumed by the existing
influence criterion and exported as auditable evidence.
Geology and piezometer evidence layers follow the same rule: they are criterion
evidence, not visual context. Geology layers are polygonal and fill dominant
geology attributes plus surface fractions per class. Piezometer layers are
point layers and fill the normalized observation evidence consumed by the
`piezometer` criterion.
Do not add the BD Topage snapping network as a default review-map layer: it is
a reference used to constrain outlet placement, not evidence that the selected
basins contain that exact hydrographic network.

Candidate catalog export and Markdown reports are deliberately not enabled by
default until their writers are implemented.

## Selection Outputs

`regional_lab_sites.csv` keeps the stable downstream catalog contract:

- `site_id`: stable selected basin identifier.
- `site_label`: human-readable label, defaulting to `site_id`.
- `region_id`: output grouping label for downstream catalogs. It is inferred
  from a single administrative region or department when omitted, and can be
  set explicitly to override the exported label for multi-territory, bbox,
  polygon or custom campaigns.
- `source_selection_id`: selection campaign that produced the row.
- `site_status`: selection status, usually `selected`.
- `maturity`: downstream maturity flag, for example `screening`.
- `x`, `y`: outlet coordinates in the outlet CRS.
- `x_outlet`, `y_outlet`: explicit outlet coordinates in the outlet CRS.
- `area_km2`: delineated catchment area when available.
- `tags`: semicolon-separated provenance tags.
- `enabled`: boolean flag used by downstream catalog loaders.

Downstream catalog consumers should prefer the selection manifest over a
hard-coded CSV path. The manifest declares which file currently satisfies the
`regional_lab_sites_csv` output key, and both `testbed` and `regional_lab`
catalog loaders can resolve that key directly:

```toml
[testbed.catalog]
from_site_selection_manifest = "outputs/site_selection/site_selection_manifest.json"
output = "regional_lab_sites_csv"
```

```toml
[regional_lab.catalog]
from_site_selection_manifest = "outputs/site_selection/site_selection_manifest.json"
output = "regional_lab_sites_csv"
```

If `output` is omitted, the downstream loader uses `regional_lab_sites_csv`.

`selected_sites.csv` contains the same core fields plus review fields for the
snapped outlet when available:

- `x_outlet_snapped`: snapped outlet x coordinate.
- `y_outlet_snapped`: snapped outlet y coordinate.
- `outlet_snap_distance_m`: distance between the original candidate outlet and
  the snapped outlet, in projected metres.

With `bdtopage_then_dem`, the catalog outlet coordinates are the reference-
network point used for delineation. The outlet GeoJSON keeps the pre-reference
station coordinates in `reference_network_original_x/y` and the projected
reference point in `reference_network_x/y`.

For station-led workflows, flow-station distance criteria are evaluated against
the final displayed outlet. If a DEM delineation snapped the outlet, this means
the station-to-outlet distance is recomputed from the station location to the
snapped outlet rather than trusting an imported pre-snap distance.

`criteria_components.jsonl` contains the detailed criterion evidence behind
the selection. `site_selection_decisions.jsonl` is the normalized decision
layer: it converts each criterion component and each final site decision into a
stable `DecisionRecord` with `ACCEPT`, `WARNING`, `REJECT` or `NEUTRAL`.
`site_selection_decisions.csv` aggregates those records into one readable row
per catchment, with the global decision and rejection or warning reasons.

`site_selection_evidence.jsonl` is the normalized evidence layer. It converts
flow-station, piezometer, influence and geology evidence into stable
`EvidenceRecord` rows. Decision records use the same `evidence_ref` convention
when a criterion can be linked to a concrete evidence feature.

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
- station-influence evidence can use hydrometry station metadata to warn or
  reject stations whose site or station is explicitly reported as influenced;
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

For station-led campaigns, `station_influence` is a hydrometric metadata check.
It is useful for filtering stations whose own reference metadata reports a
local or general hydrologic influence. It is not a substitute for a spatial
obstacle inventory such as ROE: it cannot prove that no dam exists upstream of
the delineated basin. Hard rejection is based only on explicit influence fields;
comment keyword matches remain warnings for human review.

## Short-Term Profiles

Two profiles are treated as the supported short-term contract:

- `area_only`: select basins from DEM/candidate geometry using basin area as
  the active criterion. This is the profile behind `dem_area_target` examples.
- `gauged_downstream_station`: select gauged basins from downstream flow
  stations. It infers `principle = "observation_led"`,
  `primary_observation_type = "flow_station"` and
  `candidate_mode = "station_outlets"`. Optional influence layers can reject
  basins with major upstream dams or other configured major influences.

Station-led hydrometry TOML files can omit the strategy profile:
`site_selection.input.mode = "hydrometry"` infers
`profile = "gauged_downstream_station"` and rejects contradictory explicit
profiles. The manifest still exposes `strategy.effective_profile` as the
resolved profile. DEM target-area runs must still declare `profile = "area_only"`
explicitly.

The bounded short-term contract is documented in
`docs/_dev_notes/site_selection_short_term_contract.md`.
The matching business doctrine is documented in
`docs/_dev_notes/site_selection_final_business_doctrine.md`.

## Closure Validation Examples

The two small examples used to validate the stabilized package structure are:

- `examples/projects/17_site_selection_workflow/configs/calvados_non_jauge_dem_10bassins_100km2.toml`
  (`area_only`): 26 candidates, 10 selected, 16 rejected, with
  `outputs/calvados_non_jauge_dem_100km2_v1/review/index.html`.
- `examples/projects/17_site_selection_workflow/configs/bretagne_jauge_7stations.toml`
  (`gauged_downstream_station`): 6 candidates, 6 selected, 0 rejected, with
  `outputs/bretagne_jauge_7stations/review/index.html`.

The output paths above are relative to
`examples/projects/17_site_selection_workflow/`. The map to inspect alongside
each HTML report is `review/site_selection_map.png`; the report artifact
contract is `report_artifact_manifest.json`.

## Manifest Validation

`site_selection_manifest.json` is the official hand-off contract. Use
`validate_selection_manifest()` or `hmp site-selection report` to check that
the manifest has the expected schema version and that referenced output files
exist. The HTML report is intentionally derived from the manifest and its
declared artifacts; it should not become a second source of truth.
`report_artifact_manifest.json` mirrors those declared outputs in the generic
HTML-report artifact format used by the rest of HydroModPy.

Downstream workflows should receive the manifest path, not a copied catalog
path. This keeps site-selection output naming, review artifacts and later
catalog schema additions behind one stable contract. The end-to-end dry-run
examples in `examples/projects/18_site_selection_to_testbed/` show the same
manifest feeding a generic `testbed` plan and a `regional_lab` plan.
