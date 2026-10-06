# Select catchments in a region

You have a region and you do not yet know which catchments to model. After these steps you
have a catalog of the catchments that pass your criteria, a reason for every one that
fails, and a static HTML review of the choice. The run delineates catchments on a DEM. It
builds no model and runs no solver.

Example 04, `examples/projects/04_streamflow_intermittence_in_transient`, is one
catchment and has no site-selection file. The files below stand alone: each one is a
complete project file for this workflow. The coordinates, the region and the thresholds
are placeholders for your own campaign.

## What you need first

- A region. {toml}`site_selection.territory.mode` names French regions or departments, a
  polygon file, or a box.
- A DEM, from one of two places: the IGN BD ALTI, fetched through the shorthand in step 2,
  or a file you give in {toml}`site_selection.dem.path`. The CSV route needs a DEM only
  when you ask the run to delineate the catchments itself.
- For the gauged route: network access to Hub'Eau. For the area route: nothing else.
- A working directory for the outputs. A relative path in the file is read from the
  folder of the file.

## Choose how the candidates are found

A candidate is a catchment the run considers. The way you get candidates is the first
decision, and it sets {toml}`site_selection.input.mode`.

| You have | Route | The run needs |
| --- | --- | --- |
| A region and its flow stations | `hydrometry` | Hub'Eau and a DEM |
| A region and a target catchment size | `dem_area_light` | a DEM |
| A table of outlets or of catchments | `delineated_catchments` | the CSV file |
| A region and its DEM drainage network | `generated_candidates` | a DEM |
| Only the wish to check a file | `plan_only` | nothing |

`generated_candidates` samples the DEM drainage network for outlets. It takes the
{toml}`site_selection.outlets` table, which this guide does not walk through.

```{hmp-params}
site_selection.input.mode
```

## 1. Name the campaign and the region

This file loads and runs in plan mode. It reads no data and delineates nothing, so use it
to see that the file is valid before you add anything heavy.

```toml
[workflow]
mode = "site_selection"

[site_selection]
selection_id = "bretagne_plan"
output_root = "bretagne_plan"

[site_selection.territory]
mode = "admin_regions"
country = "FR"
regions = ["Bretagne"]

[site_selection.output]
write_report_html = true
```

{toml}`site_selection.selection_id` is the name of the campaign. It is written in every
output file. {toml}`site_selection.output_root` is the folder that receives them all.

```{hmp-params}
site_selection.selection_id
site_selection.output_root
site_selection.territory.mode
site_selection.territory.country
site_selection.territory.regions
site_selection.territory.departments
site_selection.territory.bbox
site_selection.territory.polygon_file
site_selection.territory.clip_to_territory
```

Regions are checked against the list of French regions when {toml}`country|site_selection.territory.country`
is `"FR"`. Departments are given as codes, for example `"35"` or `"2A"`. A box is read in
Lambert-93 (EPSG:2154) metres when the run asks a data provider for the territory. The
territory bounds the search for generated candidates. With
{toml}`clip_to_territory|site_selection.territory.clip_to_territory` set to false, it does
not clip them.

The HTML review is written only when
{toml}`site_selection.output.write_report_html` is true. Its card is in step 5.

## 2. Pick the route

Each route is a complete file. Take one and replace the names.

### Gauged catchments in a region

The run asks Hub'Eau for the flow stations of the territory, makes each station an outlet,
snaps it onto the DEM drainage network, delineates the catchment, and applies your
criteria. A station whose catchment cannot be delineated is rejected and says why.

```toml
[workflow]
mode = "site_selection"

[site_selection]
selection_id = "bretagne_gauged"
output_root = "bretagne_gauged"

[site_selection.strategy]
principle = "observation_led"
profile = "gauged_downstream_station"
primary_observation_type = "flow_station"
candidate_mode = "station_outlets"

[site_selection.territory]
mode = "admin_regions"
country = "FR"
regions = ["Bretagne"]

[site_selection.input]
mode = "hydrometry"

[site_selection.dem]
source = "ign_geoplateforme_dem"
request_extent = "outlets"
margin_km = 5.0

[site_selection.criteria.area]
mode = "hard_reject"
hard_min_area_km2 = 50.0
hard_max_area_km2 = 500.0

[site_selection.output]
write_report_html = true

[hydrometry]
date_start = "2010-01-01"
date_end = "2020-01-01"

[[hydrometry.sources]]
source = "hubeau"
product = "QmnJ"
extent = "study_area"
max_stations = 20
```

Three things differ from a simulation file.

- The stations come from the top-level {toml}`hydrometry` section. This workflow does not
  read `[data.hydrometry]`, the section that example 04 uses for a simulation.
- {toml}`extent|hydrometry.sources.extent` is what hands the territory to the Hub'Eau
  request. Set it, or name the stations with {toml}`station_ids|hydrometry.sources.station_ids`.
- {toml}`site_selection.dem.source` set to `"ign_geoplateforme_dem"` fetches the IGN DEM
  without a `[data.dem]` section. With `request_extent = "outlets"`, the request is the
  box of the station outlets plus {toml}`site_selection.dem.margin_km`, not the whole
  region. A `[data.dem]` section, when you write one, wins over the shorthand.

The profile `gauged_downstream_station` fixes four keys together. The file is refused
when any of them disagrees: {toml}`site_selection.strategy.principle`,
{toml}`site_selection.strategy.profile`,
{toml}`site_selection.strategy.primary_observation_type` and
{toml}`site_selection.strategy.candidate_mode`.

```{hmp-params}
site_selection.strategy.principle
site_selection.strategy.profile
site_selection.strategy.primary_observation_type
site_selection.strategy.candidate_mode
site_selection.dem.source
site_selection.dem.path
site_selection.dem.request_extent
site_selection.dem.margin_km
site_selection.dem.map_background_extent
hydrometry.date_start
hydrometry.date_end
hydrometry.sources.source
hydrometry.sources.product
hydrometry.sources.extent
hydrometry.sources.max_stations
hydrometry.sources.require_observations
```

#### Where the outlet lands

A station sits near the river, not on the DEM drainage line. The run moves the outlet onto
the line before it delineates.

```{hmp-params}
site_selection.outlets.snap_strategy
site_selection.outlets.snap_dist_m
site_selection.outlets.reference_network_source
site_selection.outlets.reference_network_max_distance_m
```

With `snap_strategy = "dem_accumulation"` the outlet moves to the DEM flow accumulation
within {toml}`site_selection.outlets.snap_dist_m`. With `"bdtopage_then_dem"` it first
moves to the BD Topage network, or to the file in
{toml}`site_selection.outlets.reference_network_path`. A reference line farther than
{toml}`site_selection.outlets.reference_network_max_distance_m` rejects the candidate. The
DEM snap then runs.

### Catchments of a given size, with no stations

The run scans the DEM drainage network for outlets whose upstream area falls in a window
around a target. It delineates at most
{toml}`site_selection.dem_area_light.max_candidates_before_delineation` of them, and
selects at most {toml}`site_selection.dem_area_light.n_basins`.

```toml
[workflow]
mode = "site_selection"

[site_selection]
selection_id = "calvados_area"
output_root = "calvados_area"

[site_selection.strategy]
principle = "criteria_crossing"
profile = "area_only"
primary_axes = ["area"]

[site_selection.territory]
mode = "admin_departments"
country = "FR"
departments = ["14"]

[site_selection.input]
mode = "dem_area_light"

[site_selection.dem]
source = "ign_geoplateforme_dem"

[site_selection.dem_area_light]
target_area_km2 = 100.0
min_area_km2 = 75.0
max_area_km2 = 125.0
n_basins = 10
max_candidates_before_delineation = 40

[site_selection.criteria.area]
mode = "hard_reject"
hard_min_area_km2 = 75.0
hard_max_area_km2 = 125.0

[site_selection.output]
write_report_html = true
```

The profile `area_only` refuses a file whose {toml}`site_selection.criteria.area` is left
at `report_only`: the area must be an active criterion. The run itself then replaces that
criterion by the window of {toml}`site_selection.dem_area_light`: it rejects every basin
outside `min_area_km2` and `max_area_km2` and ignores the bounds of
{toml}`site_selection.criteria.area`. Write the same bounds in both, so that the file says
what the run does.

This route also fixes four rules of step 4 whatever the file says. It forbids nested
basins, compares overlaps against the smaller basin, rejects on overlap, and keeps at most
`n_basins` sites. The overlap fraction is 0.10 unless you set
{toml}`site_selection.spatial_selection.max_pairwise_basin_overlap_fraction`.

```{hmp-params}
site_selection.dem_area_light.target_area_km2
site_selection.dem_area_light.min_area_km2
site_selection.dem_area_light.max_area_km2
site_selection.dem_area_light.n_basins
site_selection.dem_area_light.max_candidates_before_delineation
```

A low value of `max_candidates_before_delineation` makes the run faster. It can also leave
fewer accepted basins after the spatial rules of step 4.

### Outlets you already have

Give the run a CSV file. Each row is a candidate. The file needs one column `site_id` and
the outlet coordinates, in `x_outlet` and `y_outlet` or in `x` and `y`. The columns
`area_km2`, `outlet_crs` (or `crs`), `site_label` and `priority` are read when present.
The outlet CRS is `EPSG:2154` when the file does not say. Every other column stays with the
candidate as an attribute, and the criteria read it by name: a `record_years` column feeds
the flow-station criterion.

```text
site_id,x_outlet,y_outlet,area_km2
A,380000,6800000,60
B,381000,6801000,300
C,390000,6810000,45
```

```toml
[workflow]
mode = "site_selection"

[site_selection]
selection_id = "from_csv"
output_root = "from_csv"

[site_selection.territory]
mode = "bbox"
bbox = [280000.0, 6780000.0, 420000.0, 6860000.0]

[site_selection.input]
mode = "delineated_catchments"
catchments_csv = "sites.csv"
region_id = "demo"

[site_selection.criteria.area]
mode = "hard_reject"
hard_min_area_km2 = 50.0
hard_max_area_km2 = 200.0

[site_selection.output]
write_report_html = true
```

The run takes `area_km2` from the file. It needs no DEM and no network. To have the run
compute the catchments from the outlets, set
{toml}`site_selection.input.delineate_from_outlets` and give a DEM as in the other routes.
The CSV can also carry the paths of catchments you delineated before, in the columns
`outlet_shp`, `outlet_snap_shp`, `watershed_tif` and `watershed_shp`.

```{hmp-params}
site_selection.input.catchments_csv
site_selection.input.region_id
site_selection.input.delineate_from_outlets
```

## 3. Say what a good catchment is

A criterion is a check on one family of evidence. Each family has a `mode`, and the mode
decides what a failed check does.

| Mode | A failed check |
| --- | --- |
| `hard_reject` | rejects the candidate |
| `warning` | flags the candidate and keeps it |
| `score` | adds to or removes from its rank |
| `stratify` | makes the value available to group candidates |
| `report_only` | is recorded, with no decision |

The default of every family is `report_only`. A file with no criteria therefore selects
every candidate that was delineated. Turn on the families you care about.

The families are:

- the basin area, {toml}`site_selection.criteria.area`;
- the flow station, {toml}`site_selection.criteria.observations.flow_station`: record
  length, distance from the station to the outlet, and whether the station lies at the
  outlet;
- the station influence, {toml}`site_selection.criteria.observations.station_influence`:
  the influence fields that Hub'Eau gives for the station;
- the influence of dams and withdrawals,
  {toml}`site_selection.criteria.influence`, read from vector layers you provide;
- the geology, {toml}`site_selection.criteria.geology`, read from polygon layers you
  provide;
- piezometers, from the layers of
  {toml}`site_selection.criteria.observations.piezometer_layers`.

This block turns on three of them for the gauged route.

```toml
# not checked: fragment, to add to a gauged-route file of step 2
[site_selection.criteria.observations.flow_station]
mode = "hard_reject"
min_record_years = 10.0
max_station_to_outlet_distance_km = 2.0

[site_selection.criteria.observations.station_influence]
mode = "warning"
unknown_policy = "neutral"
```

```{hmp-params}
site_selection.criteria.area.mode
site_selection.criteria.area.hard_min_area_km2
site_selection.criteria.area.hard_max_area_km2
site_selection.criteria.area.ranges
site_selection.criteria.observations.flow_station.mode
site_selection.criteria.observations.flow_station.min_record_years
site_selection.criteria.observations.flow_station.max_station_to_outlet_distance_km
site_selection.criteria.observations.flow_station.require_station_inside_or_at_outlet
site_selection.criteria.observations.station_influence.mode
site_selection.criteria.observations.station_influence.unknown_policy
```

In `hard_reject` mode, the station influence rejects a station whose metadata reports a
general or a local influence. A station whose metadata is missing is never rejected:
{toml}`site_selection.criteria.observations.station_influence.unknown_policy` set to
`"neutral"` raises no warning for it, and set to `"warning"` raises one. Comment keywords
found in the station notes are flagged as warnings. They never reject a candidate.

The four lists {toml}`site_selection.criteria.hard_reject`,
{toml}`site_selection.criteria.warning`, {toml}`site_selection.criteria.soft_score` and
{toml}`site_selection.criteria.report_only` are copied into the manifest. They change no
decision. The decision of a family is its own `mode`.

### Several area windows

{toml}`site_selection.criteria.area.ranges` lists named windows, each with a minimum and a
maximum. A candidate that falls in any window passes. Use it when the campaign is defined
by size classes rather than one pair of bounds. Write one table per window:

```toml
# not checked: fragment, to add to a file of step 2
[[site_selection.criteria.area.ranges]]
range_id = "small"
label = "Small"
min_area_km2 = 50.0
max_area_km2 = 150.0

[[site_selection.criteria.area.ranges]]
range_id = "medium"
label = "Medium"
min_area_km2 = 150.0
max_area_km2 = 500.0
```

### Exclude regulated catchments

Hub'Eau metadata tells you about the station only. It does not prove that no dam lies
upstream. To test the basin itself, give a vector layer of dams, withdrawals or regulated
reaches. The run matches each layer against each basin and sets one flag per influence
type.

```toml
# not checked: fragment, to add to a file of step 2
[site_selection.criteria.influence]
mode = "hard_reject"
reject_major_dam_upstream = true

[[site_selection.criteria.influence.layers]]
name = "Dams"
path = "layers/dams.gpkg"
influence_type = "major_dam_upstream"
```

```{hmp-params}
site_selection.criteria.influence.mode
site_selection.criteria.influence.reject_major_dam_upstream
site_selection.criteria.influence.layers.path
site_selection.criteria.influence.layers.influence_type
site_selection.criteria.influence.layers.severity_field
site_selection.criteria.influence.layers.major_values
```

The geology criterion works the same way, with polygon layers and a class column. Only
`score` and `stratify` change what it does. In `hard_reject` and `warning` it behaves as
`report_only`.

```{hmp-params}
site_selection.criteria.geology.mode
site_selection.criteria.geology.layers.path
site_selection.criteria.geology.layers.class_field
```

## 4. Thin the selection

The candidates that pass the criteria are ranked, then thinned in that order. A candidate
that fails a rule here is rejected with the rule named. The rank is the outlet priority
plus the scores of the families in `score` mode. A tie goes to the candidate with fewer
warnings, then to the lower `site_id`.

```toml
# not checked: fragment, to add to a file of step 2
[site_selection.spatial_selection]
max_selected_sites = 30
min_outlet_distance_km = 5.0
spatial_quota_mode = "grid"
spatial_quota_cell_size_km = 50.0
```

```{hmp-params}
site_selection.spatial_selection.max_selected_sites
site_selection.spatial_selection.min_outlet_distance_km
site_selection.spatial_selection.max_pairwise_basin_overlap_fraction
site_selection.spatial_selection.overlap_reference
site_selection.spatial_selection.overlap_mode
site_selection.spatial_selection.spatial_quota_mode
site_selection.spatial_selection.spatial_quota_cell_size_km
site_selection.spatial_selection.spatial_quota_max_sites_per_cell
```

The overlap rules read the basin polygons, and only the `dem_area_light` route passes them
to the selection. In the other routes
{toml}`site_selection.spatial_selection.max_pairwise_basin_overlap_fraction` has no effect.
The spacing rule, the count limit and the grid quota work in every route.

## 5. Choose what is written

```{hmp-params}
site_selection.output.write_selected
site_selection.output.write_rejected
site_selection.output.write_csv
site_selection.output.write_regional_lab_csv
site_selection.output.write_geojson
site_selection.output.write_geopackage
site_selection.output.write_geoparquet
site_selection.output.write_report_html
site_selection.output.keep_intermediate_rasters
```

The flow products and the catchment rasters are intermediate files. They are removed after
the outputs are written, unless
{toml}`site_selection.output.keep_intermediate_rasters` is true.

## 6. Check before you run

1. `hmp config check bretagne_gauged.toml` validates the `[site_selection]` section and,
   when the file has one, the `[hydrometry]` section. It catches a wrong mode, a missing
   key, an unknown key and an unknown region. It does not look for the CSV, the DEM or the
   network, and it does not test the link between the route and its sections.
2. `hmp site-selection plan bretagne_gauged.toml` validates the file the same way, then
   prints the plan as JSON: the strategy, the territory, the DEM, the criteria and the
   outputs the run will write. With `--write-manifest` it writes `site_selection_plan.json`
   under `output_root`. With `--write-report` it also writes `review/index.html` from that
   plan.
3. `hmp run bretagne_gauged.toml` runs the route.

For the CSV route, `hmp site-selection select-catchments config.toml sites.csv` applies
the criteria of the file to a CSV you name on the command line. `--output-root` and
`--region-id` override the file for that pass.

`hmp run` reads {toml}`site_selection.input.mode`. The verbs `build-observed` and
`build-generated` of `hmp site-selection` each run one route, whatever
{toml}`site_selection.input.mode` says. Use `hmp run`.

When the run ends, it prints one line per file it wrote and the counts, here for the
three-line CSV above:

```text
Workflow 'site_selection' complete: from_csv.toml
  action: delineated_catchments
  selection_id: from_csv
  selected: 1
  rejected: 2
  selected_sites_csv: /path/to/from_csv/selected_sites.csv
  regional_lab_sites_csv: /path/to/from_csv/regional_lab_sites.csv
  ...
  site_selection_manifest_json: /path/to/from_csv/site_selection_manifest.json
  site_selection_report_html: /path/to/from_csv/review/index.html
  site_selection_map_png: /path/to/from_csv/review/site_selection_map.png
```

The gauged and area routes print `candidates` as well: the number of outlets that were
tried, before any criterion.

## Read the result

Every selection run writes the audit core into `output_root`.

| File | What it holds |
| --- | --- |
| `site_selection_decisions.csv` | one row per candidate: `ACCEPT` or `REJECT`, and the reasons |
| `site_selection_decisions.jsonl` | the same decisions, one record each |
| `criteria_components.jsonl` | every check on every candidate, with its value and threshold |
| `site_selection_manifest.json` | the hand-off file: the configuration, the counts and the path of every output |

The other files follow the switches of step 5.

| File | Written when |
| --- | --- |
| `selected_sites.csv` | `write_csv` and `write_selected` |
| `rejected_sites.csv` | `write_csv` and `write_rejected` |
| `regional_lab_sites.csv` | `write_regional_lab_csv` |
| `selected_outlets.geojson`, `rejected_outlets.geojson`, `selected_basins.geojson`, `rejected_basins.geojson` | `write_geojson` |
| `site_selection.gpkg` | `write_geopackage` |
| `site_selection_evidence.jsonl` | the run produced evidence |
| `candidate_generation.jsonl`, `candidate_outlets.geojson`, `generated_dem_network.geojson` | the route generates candidates |
| `diagnostics.csv` | the `dem_area_light` route |
| `review/index.html` | `write_report_html` |

The decisions file says why each candidate stands where it does. This is the file of the
CSV route above:

```text
run_id,catchment_id,global_decision,n_accept,n_warning,n_reject,n_neutral,reject_reasons,warning_reasons,evidence_refs
from_csv,A,ACCEPT,2,0,0,5,,,flow_station:A:A
from_csv,B,REJECT,0,0,2,5,area: area 300 km2 is above hard_max_area_km2 200; final_selection: area 300 km2 is above hard_max_area_km2 200,,flow_station:B:B
from_csv,C,REJECT,0,0,2,5,area: area 45 km2 is below hard_min_area_km2 50; final_selection: area 45 km2 is below hard_min_area_km2 50,,flow_station:C:C
```

`selected_sites.csv` is the catalog. `regional_lab_sites.csv` holds the same selected sites
with the columns the regional-lab profile of the testbed reads.

Open `review/index.html` to review the choice. It is built from the manifest and the files
the manifest names, so check the manifest first when a number looks wrong. The page
holds a map, `review/site_selection_map.png`, and the tables of decisions and criteria. A
selector sets the level of detail for each block. The same review exists at three fixed
levels: `review/compact/index.html` for a quick plausibility check,
`review/standard/index.html` for the usual read, and `review/audit/index.html` for the
provenance, the detailed criteria tables and the links to the artifacts.

The map shows the DEM, the selected and rejected basins and the final outlets. For the
gauged route it also shows the stations and the link from each station to its outlet.
{toml}`site_selection.dem.map_background_extent` sets the DEM behind the map.

## What can go wrong

`hmp config check` stops on an unknown region, and lists the names it knows:

```text
Config invalid: bretagne.toml
  territory: Value error, Unknown French region 'Bretagn'. Known regions: Auvergne-Rhone-Alpes, Bourgogne-Franche-Comte, Bretagne, ...
```

The same command stops on a mode that lacks its companion key:

```text
Config invalid: area.toml
  criteria.area: Value error, area mode='hard_reject' requires at least one area range or a hard min/max area. (input={'mode': 'hard_reject'})
```

```text
Config invalid: sites.toml
  input: Value error, mode='delineated_catchments' requires catchments_csv. (input={'mode': 'delineated_catchments'})
```

A route and a strategy that do not go together are refused:

```text
Config invalid: area.toml
  : Value error, site_selection.input.mode='dem_area_light' requires strategy.profile='area_only'. (...)
```

```text
Config invalid: gauged.toml
  strategy: Value error, observation_led requires primary_observation_type (for example 'flow_station'). (input={'principle': 'observation_led'})
```

A file with no `[site_selection]` section, run with the mode `site_selection`, stops with:

```text
Config invalid: TOML file must contain a [site_selection] section.
```

The next errors come from `hmp run`, after the file has passed the check. A gauged run
without a `[hydrometry]` section stops before it loads anything:

```text
site_selection.input.mode='hydrometry' requires [hydrometry].
```

An area or generated run with no DEM source stops with the message below. Set
{toml}`site_selection.dem.path`, or {toml}`site_selection.dem.source` to
`"ign_geoplateforme_dem"`, or write a `[data.dem]` section.

```text
site_selection.input.mode='generated_candidates' or 'dem_area_light' requires either site_selection.dem.path or a [data.dem] source.
```

A gauged run reaches the DEM after the stations. Without a DEM source it stops with this
message, once the stations are loaded:

```text
site_selection.input.mode='hydrometry' requires either site_selection.dem.path or a [data.dem] source so station outlets can be delineated from a DEM.
```

A failure while the run fetches stations or the DEM begins with this text. The end of the
message is the error of the provider:

```text
site_selection failed while loading hydrometry data. data_root=<default>. Check [site_selection.input].data_root, the matching [hydrometry] TOML section, and provider cache permissions. Original error: ...
```

For a DEM the message says `loading DEM data` and names `[data.dem]`. Look at the network
first, then at {toml}`site_selection.input.data_root`, the folder that holds the provider
cache. Its default is a `data` folder under `output_root`.

A CSV row with no usable coordinate stops the run, with exit code 16
(see {doc}`../reference/cli/exit-codes`):

```text
catchments CSV row 1 is missing numeric 'y_outlet' or fallback 'y'.
```

A row with no `site_id` stops it the same way:

```text
catchments CSV row 1 is missing required field 'site_id'.
```

A candidate whose area is unknown fails an area criterion in `hard_reject` mode. The
decisions file says so, and the candidate lands in `rejected_sites.csv`:

```text
from_csv,A,REJECT,0,0,2,5,area: area_km2 is missing; final_selection: area_km2 is missing,,flow_station:A:A
```

Add an `area_km2` column, or delineate the catchments with
{toml}`site_selection.input.delineate_from_outlets`.

When every candidate is rejected, read `reject_reasons` in
`site_selection_decisions.csv` before you loosen a threshold. A candidate that the run could
not delineate has the stage `delineation` in its decision and its `failure_reason` in
`rejected_sites.csv`.

When selected sites sit on a regular grid, the input is a generated one, such as the
`dem_area_light` route, and not a set of real stations.

## Next

- Test a method on the sites you kept: {doc}`test-a-method`. The regional-lab profile of
  the testbed takes the catalog from the manifest, through the key
  `from_site_selection_manifest` of its catalog table.
- Run again with no network after a first run: {doc}`work-offline`.
- Every key of the section: {toml}`site_selection`.
- The commands and their options: {doc}`../reference/cli/site-selection`.
- Give your own DEM or polygon files: {doc}`use-your-own-files`.
