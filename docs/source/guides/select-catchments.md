# Select catchments in a region

You have a region and you do not yet know which catchments to model. After these steps you
have a catalog of the catchments that pass your criteria, a reason for every one that
fails, and a static HTML review of the choice. The run delineates catchments on a DEM. It
builds no model and runs no solver.

Example 04, `examples/projects/04_streamflow_intermittence_in_transient`, is one
catchment and has no site-selection file. The files below stand alone: each one is a
complete project file for this workflow. The measures quoted in this guide come from a run
of each route on a 25 km by 25 km box around the Nançon, with the regional DEM of example 04
(`DEM_armorican_massif.tif`) as the DEM. Write your own region and thresholds.

```{hmp-task}
Task
: Find the catchments of a region that pass your criteria, and keep a reason for each one that fails.

Time
: On a 25 km by 25 km box: 4 s for the plan and for a CSV of outlets, 23 s for two gauged catchments, 38 s for 20 candidates by area, 59 s for 40 sampled candidates. A larger region takes longer, and a DEM to download adds its own time. Only this box was measured.

Needs
: A region, a DEM (your file, or the IGN download), and for the gauged route network access to Hub'Eau.

Gives
: `selected_sites.csv`, a reason for every rejected candidate, GeoJSON of outlets and basins, and a static HTML review. From 0.1 MB for a plan to 12 MB for 40 sampled candidates.
```

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

Each route is a value of {toml}`site_selection.input.mode`. `plan_only`, the default, is step 1.
`generated_candidates` and `dem_area_light` both start from the DEM. `dem_area_light`
looks for outlets whose upstream area falls near a target. `generated_candidates` samples the
cells of highest flow accumulation, so it finds large basins first.

```{hmp-params}
site_selection.input.mode
```

## 1. Name the campaign and the region

This file loads and runs in plan mode, the `plan_only` route: `input.mode` is left at its default.
It reads no data and delineates nothing, so use it to see that the file is valid before you add
anything heavy. `hmp run` on it took 4 s and wrote `site_selection_plan.json` (2 KB) and a
`review/` folder with the HTML plan (about 0.5 MB).

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
selection_id = "nancon_gauged"
output_root = "nancon_gauged"

[site_selection.strategy]
principle = "observation_led"
profile = "gauged_downstream_station"
primary_observation_type = "flow_station"
candidate_mode = "station_outlets"

[site_selection.territory]
mode = "bbox"
bbox = [375000.0, 6805000.0, 400000.0, 6830000.0]

[site_selection.input]
mode = "hydrometry"

[site_selection.dem]
source = "ign_geoplateforme_dem"
request_extent = "outlets"
margin_km = 5.0

[site_selection.criteria.area]
mode = "hard_reject"
hard_min_area_km2 = 10.0
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

On the box of 25 km by 25 km, Hub'Eau lists two flow stations: the Nançon gauge
(`J001401001`, 64.5 km2) and `I912201002` (148.0 km2). Both pass the area window, so the run
selects both. It took 23 s with the DEM given as a file, and left 2.3 MB. The `data/` folder
under the output folder (0.7 MB) is the cache of the stations. To replace the box by a region,
write `mode = "admin_regions"` with `regions = ["Bretagne"]`, and give the DEM as the IGN
download.

Three things differ from a simulation file.

- The stations come from the top-level {toml}`hydrometry` section. This workflow does not
  read `[data.hydrometry]`, the section that example 04 uses for a simulation.
- {toml}`extent|hydrometry.sources.extent` is what hands the territory to the Hub'Eau
  request. Set it, or name the stations with {toml}`station_ids|hydrometry.sources.station_ids`.
- {toml}`site_selection.dem.source` set to `"ign_geoplateforme_dem"` fetches the IGN DEM
  without a `[data.dem]` section. With `request_extent = "outlets"`, the request is the
  box of the station outlets plus {toml}`site_selection.dem.margin_km`, not the whole
  region. A `[data.dem]` section, when you write one, wins over the shorthand. The measure
  above used {toml}`site_selection.dem.path` instead, a file you already have.

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
selection_id = "nancon_area"
output_root = "nancon_area"

[site_selection.strategy]
principle = "criteria_crossing"
profile = "area_only"
primary_axes = ["area"]

[site_selection.territory]
mode = "bbox"
bbox = [375000.0, 6805000.0, 400000.0, 6830000.0]

[site_selection.input]
mode = "dem_area_light"

[site_selection.dem]
source = "ign_geoplateforme_dem"

[site_selection.dem_area_light]
target_area_km2 = 20.0
min_area_km2 = 10.0
max_area_km2 = 30.0
n_basins = 5
max_candidates_before_delineation = 20

[site_selection.criteria.area]
mode = "hard_reject"
hard_min_area_km2 = 10.0
hard_max_area_km2 = 30.0

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

On the box of 25 km by 25 km, the scan found 857 raw outlets in the window, thinned them to 20
(`diagnostics.csv` lists these counts), delineated the 20 basins, and selected 5 of 19.7 to 20.3
km2. It took 38 s, with 120 s of processor time and 1.3 GB of memory at the peak, and left
7.9 MB. The delineated basins (1 MB), the DEM drainage network as GeoJSON (3 MB) and the HTML
review (3 MB in all) are most of it. With `source = "ign_geoplateforme_dem"` in place of a
`path`, add the time to download the DEM of the box.

### Candidates sampled from the drainage network

`generated_candidates` takes the cells of the DEM drainage network with the largest flow
accumulation, keeps the ones at least
{toml}`site_selection.outlets.min_distance_between_outlets_km` apart, up to
{toml}`site_selection.outlets.max_generated_candidates`, and delineates each. The largest
basins come first, so the area window has to be set for large basins, or the run rejects every
candidate: with a window of 10 to 30 km2 and the default spacing, all of the first 20 candidates
were 328 to 331 km2, on the main river, and none was selected.

```toml
[workflow]
mode = "site_selection"

[site_selection]
selection_id = "nancon_generated"
output_root = "nancon_generated"

[site_selection.strategy]
principle = "criteria_crossing"
profile = "area_only"
primary_axes = ["area"]

[site_selection.territory]
mode = "bbox"
bbox = [375000.0, 6805000.0, 400000.0, 6830000.0]

[site_selection.input]
mode = "generated_candidates"

[site_selection.dem]
source = "ign_geoplateforme_dem"

[site_selection.outlets]
candidate_mode = "network_sampling"
max_generated_candidates = 40
min_distance_between_outlets_km = 2.0
allow_nested_basins = true

[site_selection.criteria.area]
mode = "hard_reject"
hard_min_area_km2 = 5.0
hard_max_area_km2 = 40.0

[site_selection.spatial_selection]
max_selected_sites = 5
min_outlet_distance_km = 3.0

[site_selection.output]
write_report_html = true
```

`generated_candidates` requires `candidate_mode = "network_sampling"`. With 40 candidates
(nested basins allowed, spaced by 2 km) the run rejected 23 for the area, 11 because the
count of 5 was reached and 1 for a spacing under 3 km, and selected 5 basins of 31 to 37 km2. It took 59 s with
200 s of processor time and 1.1 GB of memory at the peak, and left 12 MB, the DEM drainage
network and the review included.

```{hmp-params}
site_selection.outlets.candidate_mode
site_selection.outlets.max_generated_candidates
site_selection.outlets.min_distance_between_outlets_km
site_selection.outlets.allow_nested_basins
```

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

The run takes `area_km2` from the file. It needs no DEM and no network. With the three rows
above it took 4 s and left 1.2 MB, 0.6 MB of it the HTML review. To have the run
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

1. `hmp config check nancon_gauged.toml` validates the `[site_selection]` section and,
   when the file has one, the `[hydrometry]` section. It catches a wrong mode, a missing
   key, an unknown key and an unknown region. It does not look for the CSV, the DEM or the
   network, and it does not test the link between the route and its sections.
2. `hmp site-selection plan nancon_gauged.toml` validates the file the same way, then
   prints the plan as JSON: the strategy, the territory, the DEM, the criteria and the
   outputs the run will write. With `--write-manifest` it writes `site_selection_plan.json`
   under `output_root`. With `--write-report` it also writes `review/index.html` from that
   plan.
3. `hmp run nancon_gauged.toml` runs the route.

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
tried, before any criterion. For the area route above it printed `candidates: 20`,
`selected: 5` and `rejected: 15`.

To draw the review again from a manifest, after you edited the manifest or deleted the page,
use the verb `report`:

```bash
hmp site-selection report nancon_area/site_selection_manifest.json --output review_again.html
```

It reads the manifest and the files it names, writes the page (3.5 s for the CSV route) and
prints `[written] site_selection_report_html: <path>`. Without `--output`, the page goes to
`<output_root>/review/index.html`. A path that is not there exits with 10 and `File not found:
<path>`. A file that is not a manifest exits with 14 and lists the keys it misses, for example
`Invalid site-selection manifest: missing top-level key: schema_version; ...`.

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

What each route left, in the runs above:

| Route | Time | Selected of tried | Size | Largest parts |
| --- | --- | --- | --- | --- |
| `plan_only` | 4 s | none | 0.08 MB | the three views of the plan |
| `delineated_catchments`, three rows | 4 s | 1 of 3 | 1.2 MB | the review (0.6 MB), `criteria_components.jsonl` (12 KB) |
| `hydrometry`, two stations | 23 s | 2 of 2 | 2.3 MB | the review (1.3 MB), the cache of the stations in `data/` (0.7 MB) |
| `dem_area_light`, 20 candidates | 38 s | 5 of 20 | 7.9 MB | the DEM network (3 MB), the review (3 MB), the basins in `catchments/` (1 MB) |
| `generated_candidates`, 40 candidates | 59 s | 5 of 40 | 11.5 MB | the DEM network, the review, `catchments/` |

The decisions file says why each candidate stands where it does. This is the file of the
CSV route above:

```text
run_id,catchment_id,global_decision,n_accept,n_warning,n_reject,n_neutral,reject_reasons,warning_reasons,evidence_refs
from_csv,A,ACCEPT,2,0,0,5,,,flow_station:A:A
from_csv,B,REJECT,0,0,2,5,area: area 300 km2 is above hard_max_area_km2 200; final_selection: area 300 km2 is above hard_max_area_km2 200,,flow_station:B:B
from_csv,C,REJECT,0,0,2,5,area: area 45 km2 is below hard_min_area_km2 50; final_selection: area 45 km2 is below hard_min_area_km2 50,,flow_station:C:C
```

`selected_sites.csv` is the catalog. `regional_lab_sites.csv` holds the same selected sites
with the columns the regional-lab profile of the testbed reads (`site_id`, `site_label`,
`x_outlet`, `y_outlet`, `area_km2`, `tags` and a few more). For the area route above:

```text
site_id,site_label,region_id,source_selection_id,site_status,maturity,x,y,x_outlet,y_outlet,area_km2,tags,enabled
dem_area_00001,dem_area_00001,,nancon_area,selected,screening,382950.0,6820500.0,382950.0,6820500.0,20.10375,site_selection;nancon_area,True
dem_area_00002,dem_area_00002,,nancon_area,selected,screening,375600.0,6826725.0,375600.0,6826725.0,19.895625,site_selection;nancon_area,True
...
```

These five outlets are the catalog of the next guide, {doc}`test-a-method`.

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

`hmp config check` ends with exit code 14 on the first six rows. The next ones come from
`hmp run`, after the file has passed the check.

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Config invalid: <file>` then `territory: Value error, Unknown French region 'Bretagn'. Known regions: Auvergne-Rhone-Alpes, ...` | A region is misspelled. The message lists the names it knows. | Copy a name from the list. |
| `criteria.area: Value error, area mode='hard_reject' requires at least one area range or a hard min/max area.` | A mode lacks its companion key. | Write `hard_min_area_km2` and `hard_max_area_km2`, or `ranges`. |
| `input: Value error, mode='delineated_catchments' requires catchments_csv.` | The route has no input file. | Write {toml}`site_selection.input.catchments_csv`. |
| `Value error, site_selection.input.mode='dem_area_light' requires strategy.profile='area_only'.` | A route and a strategy that do not go together. | Write the profile of the route. |
| `strategy: Value error, observation_led requires primary_observation_type (for example 'flow_station').` | The gauged principle is incomplete. | Write the four keys of the profile `gauged_downstream_station` together. |
| `Config invalid: TOML file must contain a [site_selection] section.` | The mode is `site_selection` and the file has no section. | Add `[site_selection]`. |
| `site_selection.input.mode='hydrometry' requires [hydrometry].` (exit 14) | A gauged run with no `[hydrometry]` section. It stops before it loads anything. | Add the section. It is a top-level section, not `[data.hydrometry]`. |
| `site_selection.input.mode='generated_candidates' or 'dem_area_light' requires either site_selection.dem.path or a [data.dem] source.` (exit 14) | An area or generated run with no DEM source. | Set {toml}`site_selection.dem.path`, or {toml}`site_selection.dem.source` to `"ign_geoplateforme_dem"`, or write a `[data.dem]` section. |
| `site_selection.input.mode='hydrometry' requires either site_selection.dem.path or a [data.dem] source so station outlets can be delineated from a DEM.` | A gauged run reaches the DEM after the stations. | The same fix. |
| `site_selection failed while loading hydrometry data. data_root=<default>. Check [site_selection.input].data_root, the matching [hydrometry] TOML section, and provider cache permissions. Original error: ...` | The run could not fetch the stations. For a DEM the text says `loading DEM data` and names `[data.dem]`. | Look at the network first, then at {toml}`site_selection.input.data_root`, the folder that holds the provider cache. Its default is a `data` folder under `output_root`. |
| `catchments CSV row 1 is missing numeric 'y_outlet' or fallback 'y'.` (exit 16) | A row has no usable coordinate. | Fix the row. |
| `catchments CSV row 1 is missing required field 'site_id'.` (exit 16) | A row has no `site_id`. | Fix the row. |
| In `site_selection_decisions.csv`: `area: area_km2 is missing; final_selection: area_km2 is missing` | A candidate whose area is unknown fails an area criterion in `hard_reject` mode. The run ends with exit 0 and the candidate lands in `rejected_sites.csv`. | Add an `area_km2` column, or delineate the catchments with {toml}`site_selection.input.delineate_from_outlets`. |
| Every candidate is rejected | The criteria are tighter than the candidates. | Read `reject_reasons` in `site_selection_decisions.csv` before you loosen a threshold. A candidate that the run could not delineate has the stage `delineation` in its decision and its `failure_reason` in `rejected_sites.csv`. |
| `generated_candidates` selects nothing, and the rejected areas are all 300 km2 or more | The sampler takes the cells of largest accumulation first, on the main river. | Move the area window to large basins, or use `dem_area_light`. |
| `Invalid site-selection manifest: missing top-level key: schema_version; ...` (exit 14), from `hmp site-selection report` | The file is not a manifest. | Name `site_selection_manifest.json` of a run. |

When the selected sites sit on a regular grid, the input is a generated one, such as the
`dem_area_light` route, and not a set of real stations.

## Next

- Test a method on the sites you kept: {doc}`test-a-method`. The testbed and the regional lab
  ({doc}`regional-lab`) take the catalog from the manifest, through the key
  `from_site_selection_manifest` of their catalog table.
- Run again with no network after a first run: {doc}`work-offline`.
- Every key of the section: {toml}`site_selection`.
- The commands and their options: {doc}`../reference/cli/site-selection`.
- Give your own DEM or polygon files: {doc}`use-your-own-files`.
