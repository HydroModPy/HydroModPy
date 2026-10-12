# Changelog

All notable changes to this project will be documented in this file.

The format follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) convention
and this project adheres to [Semantic Versioning](https://semver.org/).

---

## About this file

This changelog lists every significant modification of the HydroModPy project,
from new features to fixes and internal updates.

Each release section includes the following standard categories:

- **Added** - for new features
- **Changed** - for updates in existing functionality
- **Deprecated** - for soon-to-be removed features
- **Removed** - for removed features or files
- **Fixed** - for any bug fixes
- **Security** - for security improvements

### How to update it

1. During development, document all notable changes under the **[Unreleased]** section.
2. When creating a new release (e.g., `v1.1.0`, `v2.0.0a1`, `v2.0.0b1`,
   or `v2.0.0rc1`), move that content into a new section named
   `## [vX.Y.Z] - YYYY-MM-DD` or the matching pre-release tag.
3. Keep the `[Unreleased]` section empty to start recording changes for the next release.

---

## [Unreleased]

### Added
- `[geographic.catchment].dem_resolution`: the cell size the DEM is aggregated to before
  anything is delineated, a length such as `"75 m"`. The routing surface, the catchment, the
  mesh and the model top all take it; unset keeps the pixel of the DEM file. Each coarse
  cell is the mean of the fine pixels it covers, on a grid aligned on the upper-left corner
  of the DEM, and a value finer than the DEM's own pixel is refused when the run starts.
  It is how a 25 m BD ALTI download runs at the 75 m of the published examples.
- flow.partition_release_depth_m: the depth scale, in metres, over which the
  regularized partition of the Boussinesq solver starts to release water at the
  surface, 0.05 m by default.
- Validation case `stream_depletion_glover_balmer_2d`: a well pumping 100 m from a stream
  held on the west side, against the Glover and Balmer (1954) stream depletion and the
  image-well Theis drawdown, on the six solver variants; the depletion is read from the
  per-cell constant-head budget.
- Validation case `hantush_recharge_mound_2d`: the growth of a groundwater mound under a
  rectangle of recharge read from a raster, against Hantush (1967) linearized with the
  mean saturated thickness, on the six solver variants, with a plan-view error map. Its
  two Gmsh meshes keep every cell wholly inside or outside the rectangle, since a mesh
  cell takes the recharge pixel under its centroid.
- Validation case `linearized_unconfined_boundary_periodic_1d`: a daily tide read as
  hourly means on a side head, against Ferris (1951), with the decay and lag lengths of
  the Ferris method, on the six solver variants.
- Validation variants `modflow6_voronoi` (the default dual of a Gmsh mesh) and
  `boussinesq_local` (the default Boussinesq engine, no PETSc), a patch test of uniform
  flow on skewed triangles, a grid-convergence test on the production path, and the
  data-rich transient twin (K and Sy from heads and discharge) again.
- The Validation page draws, per case, the plan-view error of the 2D cases with their
  meshes, the space-time error of the transient 1D cases and the samples of each
  calibration method against the truth. It compares MODFLOW 6 and MODFLOW-NWT on example
  04 from runs stored at full precision.
- `observed_rasterization = "heads"` on a network calibration output draws the mapped network
  from its heads only. The free ends of the map are found by geometry, whatever the source;
  an end is a head when the largest drained area within the snap radius does not exceed the
  same window at the other end of its reach. Each head lands on the nearest cell draining at
  least `heads_min_drained_area_km2` (0.02) within `heads_snap_radius` (100 m), and the
  criterion's own descent draws the rest down to the outlet. The map is connected by
  construction, so the path a field, a ditch or a rectified reach gave the mapped line no
  longer counts as model error. A minimal map is traced from its own heads, the maximal one
  from both sets. Each trial publishes `n_heads`, `n_heads_lost`, `head_snap_p90_m` and
  `heads_trace_near_map_share`. On the Flume Voronoi run: 112 heads, 1 lost, one piece of
  5078 cells to the outlet, 99.5 % of it within 100 m of BD Topage, where `"crossing"` left
  1989 pieces.
- The figure `observed_network_heads_map` draws the mapped lines, the traced cells, each head
  with the cell it landed on, and the lost heads, with the settings the run was scored with.
- The dam foot of a lake whose spillway is declared (an outlet of the lake package releasing
  downstream) is a forced head of the heads rule: the criterion draws the reach below the dam
  from it even where the descent of the heads above leaves the reservoir through a lower
  saddle. It comes from the model, never from the observed map, is counted apart
  (`n_forced_heads`), never makes a map draw that the rule refuses, and a lake without a
  declared spillway has none. It is stored with D as `mesh/descent_dam_foot`, read alone by the
  redraw of a stored run, and marked on `observed_network_heads_map`. On the Cheze the descent
  already leaves the reservoir by its dam, and nothing changes.
- The recharge can come from a daily soil reservoir fed by the rain and the ETP instead of a
  drainage loaded from SIM2: `[flow.sinks_sources.recharge.soil]`, MODFLOW 6 only, with `ru`
  (the available water capacity in mm, required, calibrated as `soil.ru`), `alpha` (0.6),
  `kc` (1.0), `impervious_fraction` (0), `bypass_fraction` (0), `transit_time` (0, at most 30
  days) and `spinup` (`"first_year"` or `"none"`). Each SAFRAN cell is a threshold bucket in
  float64 (the rain before the ETR, the ETR reduced below `alpha x ru`, the water above `ru` to
  the water table) whose balance closes to 1e-16 of the rain. Every run and every calibration
  trial computes it again; the recharge reaches RCHA as one gridded record, and with `"etp"` in
  `flow.active_sinks_sources` the ETP the soil left unmet is offered to a new EVTA whose surface
  is the drain elevation. `hmp run <file> --until load_data` checks the soil alone: it prints the
  budget in mm/year, the recharge for `ru` from 50 to 250 mm and the gauged discharge, and
  writes no run. A run keeps the daily columns under `fields.zarr/forcing/soil/` and the yearly
  budget in `tables.parquet/soil_budget.parquet`. The section refuses what would count water
  twice (`[data.recharge]`, `[data.runoff]`), another solver, a lake without its stream network
  and a steady first period, each refusal saying what to write instead. On the Nancon, daily
  2015-2020 with K and Sy unchanged, the KGE of the gauged discharge goes from 0.65 with the
  SIM2 drainage to 0.79 with the soil (`ru = 150 mm`), and a grid calibration of K and Sy
  finds K inside its range (3.2e-5 m/s, NSE on log flows 0.84) where the SIM2 drainage keeps it
  on the 1e-7 m/s bound (0.74). The mean yearly recharge of the soil stays within 3 % of the
  SIM2 drainage plus runoff over 1985-2015 and 2015-2020, with no summer floor: the SIM2
  drainage keeps about 0.3 mm/day all summer from 2016 on only.
- `[data.soil_capacity]`: a raster of soil water capacity in mm spreads `ru` over ten classes
  inside each SAFRAN cell; the recharge is computed per class and weighted back, never on the
  mean capacity of the cell.
- `source = "explore2"` for `[data.precipitation]` and `[data.etp]` reads a local DRIAS
  Explore2 NetCDF: cut by the run box in its Lambert II extended grid before any value is read,
  converted from kg m-2 s-1 to mm/day, resampled onto an 8 km grid in EPSG:2154, read again at
  each run; a calendar other than the standard ones is refused.
- Example 04 gains `step6_soil_reservoir.toml`, the sixth step of the staircase.
- `method = "lhs"`: a stratified Latin hypercube over the transformed parameter space
  (`scipy.stats.qmc.LatinHypercube`), sized by `method_options.n_samples`, with
  `optimization = "random-cd"` to spread the points further. `max_iter = "auto"` budgets
  exactly `n_samples`, and a smaller written `max_iter` is refused at load instead of
  cutting the design. The initial sample of `gp_mapping` is now described as what it is,
  an independent draw per parameter, not a Latin hypercube.
- `[flow.sinks_sources.etp] extinction_depth` is calibratable, as
  `[calibration.parameters.extinction_depth]` with its bounds in m: each trial rebuilds the
  EVT of MODFLOW 6 in soil mode, and of MODFLOW-NWT, with its own depth.
- `[calibration] persist_trial_series = true` writes the simulated and observed series of
  every point output a completed trial scored, as
  `sessions/<name>/trial_series/trial-NNNNNN.parquet`, without promoting the run;
  `hydromodpy.results.session_journal.read_trial_series` reads them back. Off by default.
- `[flow.sinks_sources.recharge.soil] impervious_fraction` is calibratable, as
  `[calibration.parameters.impervious_fraction]` with bounds below 1: each trial recomputes the
  runoff of the sealed share and adds it once to the discharge it scores.
- `[flow.sinks_sources.recharge.soil] curve_number` adds a curve-number runoff in the manner
  of HELP (Schroeder et al. 1994): its retention moves between the dry (CN1) and wet (CN3)
  values with the soil water, so ordinary rain on a dry summer soil does not run off and rain
  on a wet winter soil does; `runoff_time` (1 day) routes it through a linear reservoir to the
  gauged discharge. Both are calibratable; off by default, results unchanged.
- `runoff_lag` (0 day by default, at most 5) holds the routed curve-number runoff back by a
  fixed travel time, after `runoff_time` and before it joins the discharge, with fractional
  days interpolated between whole-day shifts; calibratable as `[calibration.parameters.runoff_lag]`.
  The first days of a run borrow from the settled spin-up instead of reading as zero when
  `spinup = "first_year"`. In an offline test on the Flume catchment, delaying the routed runoff
  by 0.75 day raised the daily NSE from 0.66 to 0.78, with the same optimum on the calibration
  period and on an independent one.
- The exponential vertical profile of a field is calibratable:
  `[calibration.parameters."K.characteristic_depth"]` (and `min_factor`) tune how K or Sy
  decrease with depth, evaluated at the layer centres. A calibration target that is not the
  headline quantity of its instance now takes its physical bounds from its own leaf, so a
  depth under `K` is no longer checked against the range of a conductivity.
- `[geographic] dem_correc_type = "capped_breach"`, with `[geographic.capped_breach]`
  `max_depth` (0.5 m) and `max_distance` (200 m), conditions the routing DEM by a least-cost
  breach bounded in metres, then fills what the breach left (Lindsay 2016). The two bounds
  become Whitebox's `max_cost`, a cumulative lowering along one breach path, and `max_dist`,
  counted in cells. The realised lowering is measured, logged and stored with the geographic
  metadata, with a warning when it exceeds `max_depth`. It is an option and `fill` stays the
  default: against `fill`, the catchment moved by less than 0.1 % on the Flume (25 m) and on
  the Nancon, but the agreement with BD Topage moved by 1.74 points on example 04's 75 m DEM
  and by 1.22 points on the 25 m Nancon DEM, over the one-point gate set for a default change
  (0.22 point on the Flume).
- `[data.crossings]` gathers where a stream may meet a structure: the roads and railways of the
  BD TOPO (`source = "bdtopo"`, Geoplateforme WFS; a segment above the ground is a `bridge`),
  the obstacles of the ROE (`source = "roe"`, Sandre WFS; dams, weirs, and bridge sills kept as
  weirs) or a vector file with a `kind` column (`custom`). These are structure data, an input
  of the model, never a calibration target.
- The ground G: the DEM plus the declared corrections, read by the routing DEM and by the
  model top in both geographic entry points. `[geographic.crossings]` (off by default) notches
  each road, railway or bridge crossing of the generated river network: the embankment span on
  the channel is lowered to the bed interpolated between the ends read `bed_reach` (50 m)
  upstream and downstream, across `notch_width` (10 m), by at most `max_depth` (3 m), and never
  where a dam or a weir is declared. On the Flume: 231 crossings found, 127 notched, 330 pixels
  lowered (median 0.32 m), catchment area and agreement with BD Topage unchanged.
- `[geographic.bed_regularization]` (off by default) regularises the channel bed in the model
  top. On the pixels of the generated river network A, the ground G is replaced by its
  least-squares isotonic fit along the channel tree (Pardalos and Xue 1999): the bed never rises
  downstream and keeps its mean. A crossing notched by `[geographic.crossings]` is a gap the fit
  interpolates across, a weir or a dam of `[data.crossings]` within the crossings `snap_radius`
  cuts the tree, and a declared lake is left out with its surface. `min_slope` (1e-4) sets the
  least drop, centred on each flat. The fit runs on the full-extent G, written as
  `dem_ground_bed.tif`, and serves both the model top and the SFR streambed, so DRN and SFR read
  one bed; the routing DEM, A, the catchment and the mesh never read it, and the mesh cache key
  ignores the section. `dem_ground_bed.json` reports the rises before the fit, the pixels raised
  and lowered, the blocks pooled at confluences with their amplitudes and what the closing pass
  raised. With the fit on, `[geographic.crossings] path` is resolved from
  `[[data.crossings.sources]]` even with the notch off, so declared weirs and dams cut it. The
  notch writes its own footprint (`dem_ground_notch_footprint.tif`), the gaps of the fit.
  Enabling the fit by default is left open.
- `[[data.dem.sources]] source = "ign_geoplateforme_dem"` takes `dataset = "rge-alti"`: the RGE
  ALTI is assembled from the Geoplateforme WMS-Raster service by extent, at 5 m (default) or
  1 m, in tiles of at most 2,500 pixels (the server stops at 5,010). Inland, at 5 m the server
  returns the 1 m pixel holding each centre, unchanged; other sizes go through an undocumented
  kernel and are refused. The server nodata, the flat -5 m water and the blend around them are
  nodata, while real land below the sea level is kept (the Ferques quarry, -66 m). The share of
  the box outside France, filled by another source, is written in the sidecar and warned above
  1 %. A request above 150 million pixels is refused with its size, and 1 m is refused on the
  project bootstrap box (60 km), before any request. Against the BD ALTI averaged at 25 m: bias
  -0.03 m, standard deviation 0.41 m. On the Flume box at 5 m: 2,000 x 2,000 pixels in 7 s cold.
- `[modflow6.sgrid.top_sampling] mode = "zonal"` also samples the top of a structured grid
  coarser than its DEM (`planar.mode = "resample_to_shape"`): a cell holding pixels of the
  generated river network A takes their `channel_stat` (lowest pixel), the other cells their
  `hillslope_stat` (median), as on a Voronoi mesh; the bottom and the idomain keep their rule,
  and `keep_native` and `centroid` are unchanged. On the Flume at 75 m the channel cells sit
  0.90 m lower than the resampled top (median; 2.98 m at the 90th percentile of the absolute
  gap), the hillslope cells unchanged in median.
- `hmp config resolve FILE` prints the TOML a `base_config` chain resolves to, before
  validation.
- Merge directive `key__merge = [...]`: merges a list of tables with the inherited one, table by
  table, and refuses another length, a missing inherited list, items that are not tables, or the
  plain key written beside it.
- `hmp.run(path, name=...)` names a run from a TOML path. Any other keyword on a path raises a
  TypeError that says to pass a configuration object.
- `hmp.read(run, field, time=...)` and `Catalog.read` take a date, `"first"`, `"last"` or a numpy
  integer; a date reads the stress period that holds it. Another kind of time raises TypeError, a
  time on a series or a feature raises ValueError.
- `hydromodpy.core.env` lists every `HMP_*` environment variable HydroModPy reads, with its
  default, scope and description. `tests/unit/architecture/test_env_vars_are_registered.py`
  fails on a variable without a row or a row nothing reads.
- `hydromodpy.config.schema_export.editor_schema()`: the JSON Schema published at
  `_static/hydromodpy-schema.json` is now an editor schema. It accepts `base_config`, the
  `__append`, `__delete` and `__merge` forms, quantities written as text with a unit, bare dates,
  and files that omit required keys. Every file of example 04 validates against it, with
  jsonschema and with Taplo. The model schema of `hmp config schema` and the lockfile
  `schema_sha256` are unchanged.
- The data-source registry states the licence of Sandre (BD Topage, ROE), Hub'Eau, SIM2, SHOM
  and Explore2 (`etalab-2.0`) and of EU-Hydro (`LicenseRef-Copernicus-1159-2013`), each with the
  publisher pages that state it, checked on 2026-10-09. Every source also records its coverage,
  resolution, period, update, authentication, limits and cache layout when a page or the adapter
  says them. Only `custom`, `constant` and `synthetic` stay undetermined: their licence is the
  user's to declare.
- `[context.geology] path` in a catchment report file names the geological map the legend is
  read from; without it, the BRGM GeoPackages of the user cache are tried, newest first.
- Exit code 23: a testbed or a regional lab in which a case failed ends with
  `FailedCasesError`, after writing every artifact. In Python the summary is on `.summary`.
- Validation tests record their measured values, thresholds, curves and outcomes to JSON when
  `HMP_VALIDATION_RESULTS` names a directory (`tests/validation/conftest.py`).
  `assert_metric_above` is new and `assert_metric_below` takes `inclusive=`.
  `tools/docs/validation_results.py` merges the parts and fetches the nightly artifact
  `validation-results-<branch>`, which the nightly job now uploads.
- `hydromodpy.results.catalog.constants.METRIC_SENSE` declares the direction of every ranked
  metric. `register_simulation(..., config_hash=...)` takes a precomputed hash and
  `Catalog.closed` tells a closed catalog.
- Docs: Understand pages (in five minutes, how sure, what validated means, where the data come
  from, can I check what was run) and a glossary of 75 terms; the reference pages Calibrable
  parameters, Minimal files, Objects and how they relate, Exceptions
  and error codes, and the exit codes of each command; the Validation page with the measured
  value, threshold, outcome, date and commit of each check, a case-by-solver matrix and the real
  CI schedule; generated contributor pages (layers, gates, CI, tests, packages, storage tree,
  environment variables, optional dependencies); one symbol registry
  (`docs/source/theory/symbols.yaml`) for every notation table, the build failing on a symbol
  with two meanings; About pages built from `CITATION.cff` and data files
  (Cite, Applications and papers, Changelog, Versions and stability, Work with us).
- Docs: every `hmp` leaf command shows an example in `--help`, and 35 options gained a help
  string. The parameter explorer ranks its results; one dev/expert switch serves the whole site;
  each section page offers its template as a download; the changes page compares any two
  released versions. Search runs on Pagefind, filtered by door.
- Docs: the figures of the documentation are drawn by `tools/docs/figures/render_ex04_figures.py`
  from runs of example 04; `tools/docs/figures/figures.toml` lists each image with the command
  that produced it.
- `hmp config schema --editor [--out FILE]` writes the editor JSON Schema, the file the
  documentation publishes at `_static/hydromodpy-schema.json`. The editor schema also accepts
  the `__merge` directive.
- `hmp catalog import --as NAME` names the project of an imported run, and
  `Catalog.import_package_multi(..., as_project=...)` does the same in Python.
- `hmp calibrate --check` refuses an output whose `observes` station no source of its data
  section lists, and a scoring window that holds no date of the run (exit 14, before any
  solve). It warns when `da_mh_gp` is scored on a metric other than `rmse`, the metric its
  likelihood is written for.
- Every figure option declares its type, default, unit and meaning where the figure takes it
  (`hydromodpy.display.figure_options.Opt`); the figures catalog shows them. Every figure
  takes `title` and `show_run_name`, in `[display.overrides.<figure>]`, `hmp.figure` and
  `render_figure`.
- `renamed_from` in the field metadata: the changes page lists the old calibration option
  names and the old `[export]` tables as renames.
- `.github/workflows/ci-nightly-petsc.yml` runs every `petsc`-marked validation test each
  night, the 14 Boussinesq analytical variants and the 2 PETSc obstacle variants included;
  the docs deploy fetches the results of both nightly jobs before it builds.
- Docs: generated reference pages for the calibration methods and metrics (formulas in the new
  module `hydromodpy/calibration/criteria/formulas.py`) and for the catchment report file;
  a Get started quick start on the synthetic demo; the
  theory of the exits in six pages, a page on the time alignment of outputs, and the theory
  figures drawn at build time from the code.
- `hmp viz show --opt NAME=VALUE`, repeatable, sets any option of the figure, typed as the
  figure declares it, `title` and `show_run_name` included.
- `hmp.read(run, "particles")` returns the particle paths as a table (particle, step, x, y, z, time_days,
  and status and reason when stored).
- The `sfr_reaches` table has a column `downstream`, the reaches each reach drains into, and
  `hydromodpy.results.run.sfr.sfr_reach_links(run)` reads it.
- `VisibleWhen` accepts a boolean value (`VisibleWhen("enabled", True)`).
- Docs: the URLs of the site published before the restructuring redirect to the matching page
  (`docs/source/redirects.txt`), and a pull request that moves or deletes a page without a
  redirect fails. Gates in CI: typos, a Vale house style, sybil on the Python blocks of Get
  started, a test that every message quoted in a page exists in the code, dead references to
  docs paths, a browser probe (axe, overflow at 390 px, header height), weekly external links
  (lychee), and a job that runs the Get started quick start. A ratchet test fails when a gate
  total of the parameter reference goes up (`tools/docs/field_gates_baseline.json`).
- Docs: the `{hmp-toml-diff}` directive resolves the diff of two example files through the
  loader at build time; the staircase uses it. `llms.txt` and `llms-full.txt` are written into
  each built version.
- `HydroModelBase.model_refused_keys` refuses a removed key with the key to write; rate
  forcings in length per time (`hydromodpy.physics.flow.sinks_sources.rate_forcing`).
- Docs: the root of the site serves the `llms.txt` of main.
- Docs: the Validation page draws the solvers of a case on one figure, each with its colour
  and shape, with a panel of each run minus its reference, from the recorded curves. It also
  compares MODFLOW 6 with MODFLOW-NWT on example 04: `render_ex04_figures.py` writes the NWT
  copy of the reference into its scratch project and draws the group `solvers`.
- Docs: `HMP_VALIDATION_RESULTS_FILE` points a docs build at a results file other than the
  committed snapshot, so a local build shows fresh measures without changing a tracked file.

### Changed
- A run keeps its whole per-cell budget by default: every scalar term the solver produces,
  storage included (`storage` under MODFLOW-NWT, `storage_ss` and `storage_sy` under
  MODFLOW 6), is written under `budget/` at extraction, and the group says what it kept
  (attributes `policy` and `kept_terms`, repeated in `manifest.json`). The developer option
  `[simulation.results] keep_per_cell_budget = false` keeps only the terms the run's own
  consumers read: the figures of `[display].figures` with their optional fields and
  overlays, the `[[export]]` names, the declared calibration outputs, the `[observation]`
  points and the seepage mask of a surface-excess solver. The filter acts before the
  per-cell slab is built, so nothing is computed to be dropped; the intermediate budget the
  seal dropped, and its log line, are gone. A field whose terms the run kept only in part is
  refused, never served as a partial sum, and the message names the terms the run kept and
  `keep_per_cell_budget`. On the six-year daily Nançon run (21 406 cells) the group weighs
  299 MB, 3.7 times the head; writing it costs no more extraction time than before.
- Boussinesq stores the descent of a raster run: the Whitebox D8 pointer of the filled top
  becomes `mesh/descent_*` once per run, and the accumulation fluxes route on it at read.
  A run on a triangle mesh stores none, and its accumulation fluxes are unavailable instead
  of the unrouted local outflow written under that name before. Boussinesq no longer writes
  `derived/seepage_mask` nor `derived/seepage_rate`: the mask is rebuilt from
  `budget/surface_excess`, and `seepage_rate` leaves the field registry.
- The catchment discharge and well pumping series read the `catchment` row of the budget
  table when the run has one (MODFLOW 6), the per-cell field masked to the basin otherwise.
  A Boussinesq run, which now keeps its per-cell budget, gets the basin total instead of the
  total of its whole domain.
- MODFLOW-NWT `STREAM LEAKAGE` and `LAKE SEEPAGE` records are stored as `stream` and `lake`,
  the names their MODFLOW 6 counterparts take, and enter `release_flux`.
- A file or a stored run configuration that writes `[simulation.results.derived]` or
  `[simulation.results.budget]`, at the root, in a comparison or testbed overlay or in the
  dotted `overrides` of a calibration phase, loads with both tables dropped, whatever they
  held, and says so in one line; `hmp doctor --fix-config` removes them from the file. A
  sealed run configuration is migrated by the stored route only. The new developer key
  `[simulation.results] keep_per_cell_budget`, true by default, takes their place.
- Every derived field of a run is rebuilt on read, over a range in bounded passes: the
  water table, its depth, the seepage mask, the drain outflow, the two accumulation fluxes
  and the solute seepage chain (`concentration_seepage`, `mass_seepage`,
  `mass_accumulated`), as `release_flux` already was. A step read alone is the row of the
  range read, and the values equal, bit for bit, what the post-run derivation wrote. The
  seepage mask of a six-year daily run on 21 406 cells reads in 0.3 s instead of 9.4 s.
  The accumulation fluxes route on the stored descent D, or on one rebuilt from the stored
  top once per store; a run with neither serves none, never the unrouted local outflow the
  derivation wrote under the same name. `outflow_drain` read back adds the DRN-TO-MVR
  record, as the stored field did; the field read back before took the DRN record alone.
- Every per-cell budget term a solver writes has a field descriptor: `storage` (MODFLOW-NWT),
  `storage_ss` and `storage_sy` (MODFLOW 6), `evapotranspiration`, `general_head` and the
  mover terms are listed, exported and read like `drain` or `recharge`, and so are
  `fluxes_from_budget` and the solute seepage chain. `cell_budget`, which no extractor wrote,
  leaves the registry.
- A steady run (`flow_regime = "steady"`) is one stress period over the whole
  `[simulation.time]` window, whatever `step_value` says, with the forcings averaged over
  it; the step is not read, and the run says so when it would have cut the window. Before,
  the step cut a steady window into identical steady periods, each the same solve, so a
  steady file had to write a step equal to its window. The calibration phase
  `regime = "steady"` already ran one period; a plain steady run now does the same.
- MODFLOW 6 reads a computational top. Under Newton it builds the horizontal conductance
  from the full thickness of the two cells times the upstream saturation, so a thickness
  that changes from one cell to the next gave too low a transmissivity (0.16 to 0.31 m of
  head RMSE against MODFLOW-NWT on the Nançon over a flat or regionalised substratum). The
  DISV of the GWF, GWT and PRT models now carries `z_top + max H_1 - H_1`, which gives every
  cell of the top layer the same thickness; lake columns keep the ground. Every package
  elevation, the initial heads and the run store keep the ground, which the build leaves
  beside the model as `<model>.ground.npz`. A constant thickness writes the same files as
  before (example 04 unchanged). MF6 heads change on every model whose thickness varies
  (`flat_substratum`, `raster_substratum`, `raster_thickness`, a zonal top): MF6
  calibrations made before on such geometries are no longer comparable.
- Under Newton, the WEL `AUTO_FLOW_REDUCE` fraction keeps the reduction interval within a
  tenth of the aquifer below the ground in every well cell, 0.1 when the top is the ground.
- The MODFLOW 6 extractor stores `topography`, `z_interfaces` and `layer_thickness` from
  the ground file and refuses a solver folder without it: the top of its grid file is a
  computational top. A store that keeps no Zarr asks for no mesh.
- MF6 circular-island thresholds re-derived after the computational top. On the Cartesian
  grid MF6 sits at NWT's distance from the closed form (Dupuit 0.0499 m, piecewise K
  0.0282 m of radial RMSE): twice the error and half the freeboard, as for the Boussinesq
  islands. On the Voronoi dual the measured value
  with a 10 % margin, the upstream saturation and the straddled K zones being left
  (rows 37, 38, 108, 109 of `tests/TOLERANCES.md`).
- The deep Brutsaert recession and the Glover-Balmer stream depletion compare the
  period-mean discharge and depletion with the mean of the closed form over each
  period, not with its value at the period end. Their thresholds are re-derived from
  a time-step refinement: deep discharge RMSE 2e-3 and maximum 5e-3 of Q0; depletion
  maximum 0.025 to 0.029 and final error 6e-4 to 1.1e-3 of the pumping rate.
- The time-alignment page states what a period cut into time steps stores; the
  Boussinesq and solver pages follow.
- MODFLOW 6 warns once per run when a declared drain conductance meets drained cells whose
  areas differ more than twofold: the conductance is applied per cell, so the drained flux
  per unit area, C / cell_area, then depends on the mesh. The warning names the area range
  and the derived conductance, C = K * cell_area / solver.drain_bed_thickness_m.
- The description of `mf6_newton` no longer says that MODFLOW 6 under Newton matches
  MODFLOW-NWT. Newton builds the horizontal conductance from the full cell thickness times
  the upstream saturation; where the cell thickness changes from one cell to the next, it
  gives a lower transmissivity than NWT.
- Citation: the technical note is cited as published in HESS 30, 5571-5592 (2026), with the
  28 authors in the published order. The software entry carries its Zenodo DOI, the one of the
  version when Zenodo archived it, the concept DOI otherwise. Ronan Abhervé's address is now
  `ronan.abherve@inrae.fr`.
- `[modflownwt.sgrid.top_sampling] mode = "zonal"` needs `channel_source = "none"`: MODFLOW-NWT
  builds no channel mask, so a channel source is refused at load instead of being ignored.
- The default of `observed_rasterization` is now `"heads"`. A network output that does not set
  it is drawn from its heads. `"crossing"` stays the rule of the paper and must be written
  explicitly to reproduce it. A sealed run redraws with the rule it sealed.
- A calibration phase that samples a recharge parameter writes the RCHA (and EVTA) of each trial
  in the trial's own `_recharge/` folder, removed with the trial, instead of adding one stack per
  trial to the shared `_shared_recharge/` folder. A phase that leaves the recharge alone still
  shares one stack.
- `hmp data get <variable>` without `--source` takes the one source that downloads, as its help
  says: `recharge`, `oceanic`, `precipitation` and `etp` no longer ask for a source because of a
  local one (`synthetic`, `constant`, `explore2`).
- A calibration target takes the unit its own `Calibrable` declares before the unit of the node
  above it; no target of the 320 example files changes unit.
- `extinction_depth` of `[flow.sinks_sources.etp]` is a user field. Under MODFLOW 6 outside soil
  mode, an active `"etp"` is still ignored, and the run now says so once.
- A raster read by a file family is labelled with the unit its manager declares (substratum and
  lake bathymetry stay in m).
- Under MODFLOW 6, a recharge chronicle whose negative part goes to EVT builds the EVTA
  arrays with numpy when every EVT cell sits on layer 0, instead of one Python record per
  cell and per deficit day first: on 36,465 cells and 2,452 daily periods the build takes
  0.24 s and 0.6 GB instead of about 50 s and 12 GB, for the same arrays.
- `rectify_on_mesh` and `route_drainage` of `[flow.sinks_sources.sfr.<id>]` descend D, a copy
  of the model top filled on the very graph they walk (shared nodes on a quad mesh, shared
  faces elsewhere), seeded on the domain rim and the constant-head cells, lakes crossed to
  their spill level. The copy never reaches the solver: `rtp` and the streambed profile keep
  reading the top. On the cells the generated river network crosses, D follows it (pinned
  receivers), and a filled flat drains into that channel rather than beside it.
  `route_drainage` no longer reads the preprocessing D8 pointer nor falls back to a walk on
  the raw top: it routes the DRN cells of the basin of D, closed on the snapped outlet.
  Measured on example 21 (aligned 25 m grid, burn off, `fill`): 99.8 % of the catchment DRN
  cells routed (100 % before), outlet discharge unchanged, 97.9 % of the cells feed the same
  reach link, 3 of 1455 reaches lose their drainage while 57 reaches receive none against 152.
  On the Cheze Voronoi mesh the routed share goes from 84 % to 93 %. Stub pruning and the
  lake-shore test of `rectify_on_mesh` read shared faces, and the streambed profile reports on
  every call how many reaches it relaxed, one per reach.
- Every MODFLOW 6 and MODFLOW-NWT build makes the descent D, with or without SFR, and every
  reader of a flow path follows it: the per-cell discharge of a point output, the upstream area
  and the accumulated fluxes of the derived fields, and the flow direction map. A constant-head
  cell seeds D and passes the water on, so an accumulation crosses a river CHD and the outlet
  sums the whole catchment. D is stored with the run in `fields.zarr/mesh/descent_*` (receiver,
  surface, base level, channel, pinned, constant-head and raised masks) and read back by
  `Run.descent`; a run stored before rebuilds it from its top, without pins. On example 04 the
  gauge cell drained 0.17 % of the catchment on the former face graph (664 sinks) and drains
  99.89 % on D; the tracked files read the whole-catchment series and keep their scores. D
  takes 5.6 MB at 90,000 cells. The transport routing context, the Boussinesq raster path and
  the network criterion (the model top with the D8 adjacency of the paper) keep their own
  graphs.
- The stream/DEM agreement alpha of the geographic step reads the map of a
  `[[data.hydrography.sources]]` entry with `source = "custom"` (a vector file), on every run
  and on a cached geographic tree too; an API source is not downloaded for it and the run says
  so. Alpha is a diagnostic: a map it cannot read or that misses the catchment gives a warning,
  never an error. `stream_dem_agreement.json` loses its `burned` key.
- `conditioning_impact_map` maps the top difference of two runs on one mesh (fill against
  capped breach, bed regularisation off against on): `reference=<run>` is required, and a run
  alone is skipped with a sentence.
- The zonal channel mask and the projection of A read the same raster of A: the link raster,
  else the pruned stream raster when `prune_short_streams = true`, else the stream raster, each
  only when it is not older than the one it replaces.
- Example 21 loses the burn, the top conditioning keys and its SFR threshold, and
  `calibrated_best.toml` says it no longer replays the calibration made on the burned DEM. With
  its `breach` routing DEM, D now pinned on A: 97.92 % of the catchment drain cells routed to the
  river (99.62 % with the burn), outlet discharge 1.127 m3/s (1.147). A traced on the breached
  routing DEM crosses ridges the model top keeps, and 2.0 % of the catchment leaves D's basin;
  with `fill`, 0.2 %. Every calibration of example 21 is to be redone.
- `[geographic.dam_carve]` corrects the ground G in both geographic entry points: the routing
  DEM now sees the carved dam as the model top does (one entry point carved the top only, the
  other ignored the section). `reg_fold` together with `dam_carve` or `[geographic.crossings]`
  is refused, the shared regional job being conditioned on the raw DEM.
- A list of tables written in a child TOML replaces the inherited list, whatever the lengths.
  Two lists of the same length used to merge table by table without a message. Write
  `key__merge = [...]` to merge tables in order, or `key__append` to extend.
- `solver.backend` follows the flow process of `[[simulation.process]]` when the file does not
  set it, and two different names are refused. The capability checks (boundaries, hotstart,
  cyclic spin-up, flow barriers) read the solver that runs; they used to read the default
  `modflow6`, so an NWT file that wrote only the process was checked as MODFLOW 6.
- `mesh_catchment.constraints_mode` is required by the model; the reference no longer shows a
  default the loader refused.
- The soil reservoir ranges (`ru`, `alpha`, `kc`, `impervious_fraction`, `bypass_fraction`,
  `transit_time`, `curve_number`, `runoff_time`, `runoff_lag`) are declared as field bounds and
  shown in the reference and the JSON schema. The refusal messages are unchanged.
- `recharge.units` is in the user profile.
- `[solver.modflownwt] thickfact` is described as the fraction of the cell thickness over which
  the saturated thickness is smoothed, and refused outside [0, 0.5).
- The run identity hash covers the resolved configuration without
  `workspace.solver_scratch_folder`, with the requested run name as `simulation.name`, plus the
  parameter overrides of `Project.simulate`. Two names, or one override, make two runs.
- `hmp.run(cfg)` and `Project.simulate()` without `name=` use `[simulation] name`; `run_0001`
  remains only for a configuration that names no run. `hmp.run(cfg)` skips an identical
  completed run like `hmp run` does, and `force=True` computes it again; a run with an override,
  or a resume, `from_step`, `until_step` or `dry_run` run, is never skipped.
- `hmp.run` raises `CatalogError` when a simulation finished but its catalog cannot be opened;
  None now means a dry run only. `hmp.open` on a workspace root names the projects under it, and
  `run.hydromodpy_config` on a snapshot this version no longer validates raises a ValueError
  that points to `run.config_snapshot`.
- A pipeline step failure exits with the code of its cause (for example 16 for a data error, 15
  for a solver error) instead of 1.
- `hmp config check` refuses a type listed in `data.types` that has no `[data.<type>]` section
  (geology excepted).
- `[testbed]` and its tables refuse unknown keys; a typo such as `exceute = false` used to be
  ignored. The reference names `testbed.base_config`, `testbed.catalog.from_site_selection_manifest`
  and `testbed.catalog.output`. The retired spellings `testbed_id` and `[[testbed.metric]]` are
  refused with the key to write.
- The testbed makes absolute only the values its child schema declares as paths:
  `track_dir = "forward"` or `profile = "x"` are no longer rewritten to a path, and a bare input
  file name absent next to its source stays bare, so the child finds it in the workspace data
  folders.
- `hmp report catchment` validates the report file with Pydantic (`ReportConfig`). An unknown
  key or table, an unknown preset, a quoted boolean or a missing required key is refused with
  the file line and exit code 14. `[context.observed_discharge]` requires `path`.
- The comparison web report, the compact network page, the overview web page and figures, and
  the catchment report pages are written in English, with `<html lang="en">`.
- A negative numeric `flow.sinks_sources.recharge.first_clim` is refused when `negative_to_evt`
  is false.
- Under `coverage_policy = "warn"` or `"ignore"`, a period before the first sample of a series
  takes that sample instead of stopping the run, and a grid gap takes the slice in force instead
  of the slice nearest the period start. A declared forcing with `aggregate = "last"` is a state
  and is not subject to the coverage check.
- Validation: the thin Brutsaert case is flagged as a documented gap (relative RMSE 0.217 to
  0.221 against its raised threshold 0.23, where the base file asks 0.04) and the deep Brutsaert
  MODFLOW-NWT variant as a smoke test (threshold 1.0). No threshold changed.
- Docs: the site keeps only main, dev and the stable tags; each deploy replaces its version
  folder and removes the folders the site no longer keeps. The About door has five pages, the
  release ceremony moved to the Contribute recipe Cut a release, and the Contribute door went
  from 87 to 78 pages, rewritten against the code.
- `geographic.catchment` and, in the dem shape, `dem_init_path` are shown as required in the
  reference and the JSON schema. Loading is unchanged.
- `[testbed]` declares the defaults its parser always applied: `profile = "generic"`,
  `subject = "mesh"`, `purpose = "robustness"`, `runner.type = "simulation"`.
- Path keys are typed as paths: `mesh_catchment.rivers.path`, `domain.path` and
  `refinement_zone.path`, the `values_csv_file` keys, `calibration.outputs.*.stream_geometry_path`
  and `minimal_stream_geometry_path`, and the `[comparison]` keys `anchors_file`, `output_root`,
  `base_simulation_config`, `simulation.simulation_config` and `simulation.run_folder`.
- One table of metric directions (`hydromodpy.results.catalog.constants.METRIC_SENSE`) drives
  `@best`/`@worst`, `Catalog.best/worst/rank`, `RunSet.best/worst`, `hmp dev rank` and the
  calibration criteria. `distance_gap` and `distance_mean` are lower-is-better.
- `FrozenDataError` and `FailedCasesError` live in `hydromodpy.core.exceptions`, with the codes
  `HMPY.E210` and `HMPY.E511`; their exit codes stay 16 and 23. They are no longer importable
  from `hydromodpy.data.registry.cache_store` or `hydromodpy.analysis.testbed.contracts`.
- The top-level verbs (`hmp.open`, `index`, `run`, `calibrate`, `spinup`, `read`, `figure`,
  `export`, `compare_pair`, `report`, `example_add`) declare real argument types.
- The data folders that `hmp workspace init` writes describe each variable in English
  (`VariableSpec.label_fr` is now `label`). The example 04 README and its scripts py2 to py6
  are in English, and `hmp example list` describes example 04 as six steps with measured times.
- Validation runs store their fields at full precision (`field_precision = "exact"`): the 8
  fast cross-row failures were the steps of the 16-bit compact rounding, not solver error.
- Comparison children make absolute only the values their schema types as paths, and find a
  bare input file name in the data folder of the base file's workspace.
- `hmp.calibrate(path)` and `Project.calibrate(config_path=...)` return the report object
  (`CalibrationReport`) for a file without phases, as they already did for a staged file; pass
  `return_report=False` for the dict.
- The NSE on log discharge has one name, `nse_log`, in calibration files, in the catalog and in
  `@best:`. Catalog migration 0005 and `hmp catalog reindex` rename stored rows; `@best:log_nse`
  is refused with the name to write.
- Keys a user sets are user keys and appear in `hmp config template --profile user`: wells
  units and forcing, lake and SFR forcings, the PRT, MODPATH, GWT and MT3DMS parameters,
  `simulation.results.keep_solver_files` and the derived fluxes, `lay_decay` and
  `lay_proportions`, `mesh_catchment.zone_meshing`, `data.inference_mode`,
  `simulation.time.coverage_policy` and others. The parameter reference gives every user key a
  description, every number a unit or a dimensionless mark, and every choice its values.
- The duplicate-import message names both spellings of the force flag, `hmp catalog rerun
  --help` shows a valid `--set` path, and `hmp dev completion --help` gives the bash, zsh and
  fish procedure.
- Docs: the site ships its fonts (Inter and JetBrains Mono, self-hosted, metric-matched
  fallbacks), so the header no longer shifts while a page loads; the header stays on one row
  from 390 to 1440 px; text reaches the WCAG AA contrast; the search page uses the Pagefind
  Component UI, and math source, buttons and card labels are out of its index.
- `hmp data import` and `hmp catalog import` exit 12 (write conflict) when the run is already in
  the catalog or its project name is taken, through `ImportConflictError` (`HMPY.E809`).
- The overview stats card, the station inventory, the catchment outline of the overview maps and
  the site selection map follow the dark theme; the site selection legend names an area class
  as a class. Docs: the five accessibility exceptions of the browser probe are fixed, and the
  quantities page groups every key with a unit.
- The run identity that `hmp run` and `hmp.run` compare to skip an identical completed run
  covers the sha256 of every input file the configuration names and the package version, and no
  longer the run name: a changed input file, or another HydroModPy version, computes again, and a
  renamed run no longer answers to its old name.
- `hmp catalog delete <name> --now` refuses a name that both a live and a trashed run carry and
  lists both ids; `hmp catalog restore <name>` looks the name up in the trash.
- A search by extent whose stations all lie outside the watershed warns and leaves the variable
  empty instead of stopping the run; stations named in `station_ids` or a custom file are still
  refused.

### Fixed
- A sealed run whose figures read the network criterion kept the release terms of its
  per-cell budget but not the recharge the seepage threshold is a fraction of:
  `hmp export <run> simulated_active_network` refused and `seepage_network_confusion_map`
  was skipped once the run was sealed. The recharge is kept, and the criterion gate asks the
  source the computation reads, a station forcing first and the per-cell recharge
  otherwise, so a station-forced run without a recharge budget is no longer refused.
- The network maps draw their topography background under MODFLOW 6 and MODFLOW-NWT:
  they read the per-cell `topography`, not the one-column `z_interfaces`.
- A stress period cut into time steps (simulation.time.substeps_per_period, adaptive
  time stepping, the internal steps of the Boussinesq PETSc closures) stores, on
  MODFLOW 6, MODFLOW-NWT and Boussinesq alike, the head of its last step and every
  flux as the mean of its steps weighted by their length, as the time convention
  says: a stamp closes its period. MODFLOW 6 and Boussinesq stored the flux of the
  last step; MODFLOW-NWT stored one slice per time step (1000 for the 10 periods of
  the deep Brutsaert case) beside one mass-balance row per period. The budget table,
  the per-cell budget fields, the listing water balance, the lake and stream series
  and the calibration readers take the period mean. A run of one step per period
  stores what it stored before, bit for bit.
- A MODFLOW 6 run with a lake or a stream network and more than one step a period no
  longer fails at extraction: its observation file holds a row per step, and the
  extractor now puts the rows on the periods.
- A transient Boussinesq run reads flow.first_period_steady, true by default, as MODFLOW 6
  and MODFLOW-NWT do: it solves the first stress period at steady state under the forcing
  of that period, its recharge set by first_clim, with the initial heads as a first guess
  only, then steps in time from that state. It ignored the key and started from the
  initial heads, so one file solved two problems. On the natural-mesh test started 5 m
  above its steady state, the first-period heads were 2.6 m (RMSE) off MODFLOW 6 and the
  constant-head outflow of that period 260 times larger. They now differ by the 0.23 m the
  two solvers show at steady state on that mesh, and the outflow of that period is the
  same. The TS VI obstacle closure solves that period with the VI obstacle closure. A run
  that must start from its initial heads sets first_period_steady = false.
- A well or a drain on a Boussinesq cell with an imposed head does nothing, as in
  MODFLOW, and the run warns about such a well. It was counted in its own budget term
  and fed by the boundary: on a test with a 1000 m3/day well on a fixed-head side, the
  Boussinesq pumping read 2000 m3/day where MODFLOW 6 read 1000. Heads are unchanged.
- A transient Boussinesq run stamps each stress period at its end, like the MODFLOW
  backends. The store also held the initial state as its first time step: the lumped
  budget gave each period the time step of the next one in MODFLOW 6, the catchment
  discharge and well pumping started with a zero at the run start, Run.time_index fell
  back to rebuilt stamps so a point read lost its dates, and a Boussinesq calibration
  scored undated series. The initial state stays in the boussinesq_state group.
- A Boussinesq cell with an imposed head takes no recharge, as in MODFLOW. The rain on
  it was counted as recharge and left at once as constant-head outflow: on the natural
  basin comparison, whose eight fixed-head cells cover 11.6 % of the mesh, the exported
  recharge was 13.1 % above the forcing on the aquifer (1.260e6 against 1.114e6 m3) and
  the constant-head outflow 6.5 times the flow the aquifer sent to the boundary. Heads
  are unchanged; the recharge now matches MODFLOW 6 to 1e-8, and the constant-head flux
  of such a cell is what its free neighbours send in or draw out.
- The residual history of a Boussinesq run is zero on a cell with an imposed head, so
  its sum is the closure error of the run. It carried the constant-head flux, and the
  comparison budget reported a closure of 0.35 m3/s (CHECK) on the natural basin, now
  2e-14 m3/s.
- The default surface closure of the Boussinesq solver, the regularized partition of
  every engine but PETSc, released water far below the ground: a cell sent to the
  surface the share exp(-(1 - s) / 0.05) of the water it received, s being the
  saturated share of its thickness, so a water table 10 m under the top of a 60 m
  aquifer lost 3.6 % of its recharge, and a pumped cell 11 m under the top sent 0.4 %
  of the pumping to the surface (a quarter at 1.5 m, where the run stopped
  converging). The share now follows the depth of the water table below the land
  surface, exp(-d / flow.partition_release_depth_m), 2e-9 at 1 m with the default
  0.05 m, and the water a cell receives counts its wells and its signed recharge. The
  recharge mound now stores all its recharge and the stream depletion run matches
  PETSc.
- A Boussinesq cell with an imposed head no longer reports a surface release: the
  water it receives goes to its constant-head flux. Heads are unchanged; the surface
  outflow of a run stops counting the inflow of its Dirichlet cells (16.7 of the 20.9
  m3/day reported on the steady interception hillslope).
- The Boussinesq plan-view map of the late-time pumping validation case was flipped
  north-south.
- Boussinesq derives an undeclared drain conductance as `K * cell_area /
  solver.drain_bed_thickness_m`, like MODFLOW 6 and MODFLOW-NWT. It ignored the bed
  thickness, so any value other than 1 m gave a different drainage, and a different
  calibrated K, than the MODFLOW backends.
- The per-cell `budget/constant_head` field of a Boussinesq run is signed positive into the
  aquifer, as the field registry and MODFLOW sign it. It was written positive out, so a
  map or a sum of it read the opposite of the same field from MODFLOW.
- Validation: the triangle variants of the two drainage cases solve the problem of their
  reference. Each drain derives its conductance from K, so the leakance is the same on
  every triangle, where one conductance per cell varied it forty-fold (head RMSE 7.3 and
  4.3 mm down to 0.27 and 0.23 mm).
- Validation: on the Voronoi dual, every cell of the coast node ring of the two island
  cases holds the sea level. A node on the shoreline is a tie that the 10 m DEM broke at
  random, and 36 of the 48 coast cells stayed land; the run now reads a 1 m DEM whose
  shoreline sits 1 m inside the ring (radial RMSE 0.204 to 0.102 m and 0.088 to 0.056 m;
  the rest is the documented MODFLOW 6 Newton bias).
- Validation: the late-time pumping reference is centred on the cell that holds the well,
  15 m from the well point on the MODFLOW 6 triangles and 6.6 m on the Boussinesq ones, and
  the azimuthal spread is taken on the error (0.136 and 0.087 m down to 0.0013 and 0.020 m).
  The Boussinesq variants run on 10082 triangles, the cell area of the MODFLOW grid.
- Validation: the deep recharge-step case sets the Newton closure of the default Boussinesq
  engine to 1e-12 m3/s; the absolute default of 1e-9 m3/s per cell left its steady profile
  1.7e-5 m off, worse than MODFLOW (now 1.6e-6 m).
- Validation: a twin calibration count is recorded with the number of runs as its ideal
  value, so the page reads the share of the margin a run used instead of 100 % for any
  success.
- Validation references compare what the model computes. The 1D cases pose their heads at
  the centres of the boundary cells, where the model holds them (errors of 3 to 5 cm down
  to 3 to 7 mm). The late-time pumping case evaluates the Theis well function with SciPy,
  where a hand-written E1 was wrong between u = 1 and 8, and reads it at the solver cell
  each monitor point reads. Ogata-Banks measures from the centre of the source cell. The
  thin Brutsaert case drains to the substratum and is read on its late recession, with the
  dimensions of the strip. The steady interception case compares with the exact
  seepage-face solution and starts from a neutral state, not from the reference.
- The MODFLOW-NWT validation profile runs chi-MD with closures below the compared
  discharges: the deep Brutsaert recession, frozen at a -200 % budget, recesses again and
  keeps the thresholds of the other solvers.
- The Boussinesq validation runtime builds the run view the solver adapters read since
  2026-09-18 (every Boussinesq validation test failed), and each variant writes to its own
  folder.
- The twin calibration tests publish the thresholds they assert; the stream-network twin
  stores its fields at full precision and sets the crossing rule it checks.
- The Boussinesq solver honours `simulation.time.substeps_per_period` with every engine:
  each stress period is solved in that many backward Euler steps of equal length. The
  `local`, `scipy`, `scipy_sparse` and PETSc partition engines took one step per period
  whatever the file asked; the PETSc VI keys `vi_substeps_per_period` and
  `ts_vi_steps_per_period` now refine each time step.
- `flow.runtime_backend` defaults to `"auto"`: the Boussinesq solver runs the dense `local`
  engine up to 400 cells and `scipy_sparse` above, and logs the engine once.
  `solvers = ["boussinesq"]` no longer fails on a catchment mesh; an explicit `local` or
  `scipy` on a larger mesh stops with `IncompatibleCapabilitiesError` (HMPY.E407) and names
  the key to change.
- The water budget of a MODFLOW-NWT run is read. FloPy names the NWT listing `.list`, which
  the reader skipped: an NWT run had no `water_budget_percent_discrepancy`, and a calibration
  threshold on the budget never applied to it.
- MODFLOW-NWT defaults to the chi-MD linear solver (`linmeth = 2`). With GMRES a stiff
  recession stopped reducing the residual and NWT accepted a frozen head as converged, its
  budget off by 200 %. `fluxtol` is in m3/s, the model's unit: its default is the 500 m3/day
  of the NWT manual, where it was 500 m3/s, a bound no model reaches.
- With `grid_dual = "voronoi"`, the default on a Gmsh mesh, MODFLOW 6 now places wells,
  side boundaries and the stream boundary on the Voronoi cells it solves, not on the
  triangles of the mesh. Since 2.0.0a1 such a run stopped on an out-of-range cell, or put a
  well in an unrelated cell without a warning (802 m off on a validation case). A side
  boundary takes the cells centred on its nodes, where a fixed head belongs.
- `hmp calibrate FILE --list-phases` on a file without phases printed only "declares no
  phases". It now prints one line for the single search, with its method and why it was
  chosen, and what each block compares.
- The Exceptions page of the Python API listed the classes of three fixed modules. It now
  finds every module that defines a `HydroModPyError` subclass, or a subclass of a class the
  exit codes map; 13 classes in 10 modules were missing.
- The channel mask of the zonal top covered the whole catchment. The stream raster was
  reprojected with nodata 0, and GDAL moves a valid 0 to the next float, so every background
  pixel counted as channel: on the Flume Voronoi mesh 146,384 pixels instead of 4,197, and the
  block minimum on 29,760 of the 32,382 zonal cells instead of the hillslope median. The mask
  now holds the channel pixels only, read on the full-extent channel tree A, so the channel
  cells of the buffer around the catchment are found too. A zonal run gets a higher top on its
  hillslopes; the weekly Flume v2 run no longer converges with its solver settings.
- `flow_persistence_map`, `flow_intermittence_map`, `seepage_network_reference_overlay` and
  `seepage_network_confusion_map` render again on a run with several layers. The seepage
  threshold reads the mean recharge from the budget, stored per layer; it now sums the layers
  onto each cell instead of laying them side by side, which failed with `operands could not be
  broadcast together`. Calibration scores were not affected.
- The soil budget printed by `hmp run` shows `kc` and the sealed and bypass shares with their real
  precision: a calibrated `kc = 0.9571` printed `kc 1.0` and `impervious_fraction = 0.00212`
  printed `impervious 0 %`. The values used by the run were right.
- A run on an unstructured (gmsh) mesh keeps its K, Sy and Ss fields under `derived/` again.
  The builder wrote them before the model folder existed and dropped the error silently, so
  the conductivity and storage a Voronoi run was given could not be read back or drawn.
- `hmp run` and `hmp.run` skip a run identical to a completed run of the project, as
  documented: the identity hash no longer includes the per-run scratch folder, which carried the
  process id. Runs registered before never match; their first rerun computes once.
- `cat["x"]` and every CLI reference resolve a bare name to a live run before a trashed one;
  after `if_exists = "replace"` the name reaches the run that replaced the old one.
- A `Run` or `RunSet` keeps reading after the catalog that made it is closed (end of a
  `with Project` block); it reopens the catalog read-only.
- `@best:<metric>`, `@worst:<metric>`, `Catalog.best/worst/rank` and `RunSet.best/worst` follow
  the metric direction: highest nse, kge, log_nse, r2, correlation; lowest rmse, mae, mse,
  objective_best, closure_*; bias and pbias closest to zero; kge_alpha and kge_beta closest to
  one. A metric with no declared direction is refused and NaN never ranks.
- A data variable declared in `[data]` that cannot be loaded (missing file, missing period,
  source error, frozen cache refusal) stops `hmp run` with a typed exit code (10, 14 or 16); it
  used to be logged with exit code 0. Only a type inferred under `data.inference_mode = "warn"`
  is still dropped, with a warning that names it.
- A frozen run (`--frozen`) that meets an entry missing from `hydromodpy.lock`, a cache miss or
  a digest mismatch stops with exit code 16 (`FrozenDataError`) for every variable, not only for
  the DEM, the geology and the river network.
- A custom DEM, geology file or river network without a CRS is refused (exit code 16) with the
  command that writes one; it used to be labelled EPSG:2154 or EPSG:4326 silently.
- Stations dropped outside the watershed mask are named in a warning; a source whose every
  station lies outside is refused.
- A NetCDF grid's finite `_FillValue` or `missing_value` is read as its nodata value.
- A station whose LOC file has no unit logs a warning naming the unit it is taken in.
- Messages that named `geographic.catch_def`, `geographic.x_outlet`/`y_outlet`, `snap_dist`,
  `buff_area` and `dem_init_path` name `geographic.catchment.*`, the key the file takes.
- A calibration of `flow.sinks_sources.recharge.values` reads its bounds in the unit of
  `recharge.units` (mm/day by default), not in m/s.
- Merge directives inside a table the parent file does not have are applied, instead of
  reaching validation as unknown keys.
- `first_clim` sets the rate of every steady stress period and of no other period, under
  MODFLOW 6, MODFLOW-NWT and Boussinesq, and for series, mappings and grids alike. MODFLOW 6
  grids honour it on a steady period; MODFLOW-NWT and Boussinesq no longer replace a transient
  period 0. With `negative_to_evt`, a steady period takes `first_clim` on the recharge part and
  on the deficit part, so its net rate is the one `first_clim` states. Example 04 and the frozen
  projects 00, 02 and 05 are bit-identical.
- `simulation.time.coverage_policy` applies to every forcing record (series, stations, grids)
  before any value is carried: a record that ends early stops the run under the default
  `"error"` instead of being extended in silence. Several gridded records covering one stress
  period are averaged with equal weights; they were merged pairwise.
- The `release_flux` field includes the constant head of the stream-role cells, stored as the
  budget term `budget/constant_head_stream`, so it sums the same paths as the stream-network
  calibration criterion. Runs stored before keep the old union.
- In a catchment report, a relative `dem_init_path` of the simulation file is resolved from
  that file's folder (it was resolved from the repository root), the geology legend no longer
  reads `examples/data/geology`, and a missing observed-discharge CSV logs a warning with its
  path.
- Example 04 `run_daily.toml` writes each recharge and runoff source in full, and examples 09
  and 10 use `__merge` and `[[testbed.metrics]]`, so they resolve to their former payloads.
- A resume (`--resume`, `Project.simulate(resume=...)`) in another process, or without
  `name=`, no longer stops on "Resolved configuration changed since the checkpoint was written
  (workspace)": the per-run scratch folder, which carries the process id and the run label, is
  left out of the checkpoint fingerprint as it is left out of the run identity.
- A transport process under the `boussinesq` flow is refused by `hmp config check`; the
  check read a field the transport config does not have.
- Testbed and comparison children no longer rewrite `calibration.parameters.<name>.path` or
  `display.output_dir` as absolute paths.
- The data-request, domain-build and terrain-delineate capabilities declare `HMP_VERBOSITY`
  instead of `HMP_LOG_LEVEL`, which nothing reads.
- `hmp dev rank` works again (it failed on every call with a DuckDB Binder Error) and ranks by
  the direction of the metric; a metric without a direction exits 10.
- `difference_map` no longer crashes on its title and names the runs by name; `side_by_side`
  and `conditioning_impact_map` no longer print sim ids; without a reference they are skipped.
- A figure that needs `release_flux` (or the accumulated fluxes) on a model with no drain,
  stream, lake or surface excess is skipped with its reason instead of stopping the run.
- The dark preset darkens the dry cells of `flow_intermittence_map`, the table of
  `watershed_id_card`, the inactive cells of `flow_direction_map` and every legend frame.
- The network calibration diagnostic page, the site-selection report and plan, and the Nançon
  river-network case figure are written in English.
- `hmp calibrate` prints the calibrated values, their interval and the cost for a file without
  phases; it printed nothing after "Calibration finished".
- A DEM without a CRS named by `dem_init_path` or a custom source is refused before the
  catchment is cut (exit 16), instead of a Whitebox panic with exit 1.
- `workflow.mode = "overview"` without an `[overview]` section is refused (exit 14); it ran,
  wrote nothing and exited 0.
- `hmp run --frozen` refuses a request the cache covers only in part before any download; it
  downloaded the gap, replaced the pinned file, then refused.
- `hmp report catchment --strict-figure-postflight` exits 16 on a missing figure (was 1), and
  the refusal of a workspace without `data/` is in English.
- `hmp catalog watch` no longer shows live runs as `[STALE]`; a run stopped by Ctrl+C or
  SIGTERM is marked `failed`; `hmp workspace search` works when two projects hold one run and
  while the full-text index is missing; the `label` of a probed point fills a new `point`
  column; opening one index read-only and read-write in one process raises
  `WriteConflictError` (exit 12) instead of advising to reindex a file that is not damaged.
- Wells declared under `flow.sinks_sources.wells` without `"wells"` in
  `flow.active_sinks_sources` are refused by `hmp config check`; the run built no WEL and said
  nothing.
- A flow solver name that is neither built in nor a registered plugin is refused with the valid
  names, instead of a message about the drainage boundary.
- A side, ocean or stream constant head below the bottom of its cell stops the run before
  MODFLOW 6 starts, with `SolverInputError` naming `flow.bc.<id>` and the cells; MODFLOW 6 used
  to abort.
- A mesh along the rivers, or the stream boundary on a `[mesh_input]` mesh, without a
  `[geographic.river_network]` threshold is refused by `hmp config check` with the key to set.
- The Methods paragraph of a staged calibration names the flow solver the trials run.
- The MODFLOW 6 GWT concentration file is read in its own layout; the flopy warning "Very large
  grid" came from reading it as an MT3DMS file first.
- A custom geology vector or CSV in another CRS than the request is clipped by the request box
  reprojected into its CRS.
- `hmp data get --workspace` keeps a downloaded river network in the workspace cache and reuses
  it, as a run does.
- A comparison point or outlet located by x and y works again on runs of the current layout: the
  cell is the nearest centre on the mesh each child stored.
- `hmp catalog restore` gives a trashed run its original name back when no other run holds it.
- `hmp run` reports a TOML syntax error, or an error in its `base_config` chain, with the file at
  fault; both used to be printed as "Invalid override:".
- The calibration metrics `nse_seasonal` and `reservoir` read the sampling step of the scored
  series from its dates; a monthly series scored NaN.
- The summary columns nse, kge, rmse and r2 of `v_simulation_summary` and of the federated
  `all_simulations` hold the outlet scores of a run, or of its only scored series; they were
  empty for runs scored on discharge.
- The warning "The mean recharge moved between two network criterion builds" compares only the
  trials of one calibration session.
- `hmp install-binaries` and the download of a missing solver raise a `NetworkError` (exit 16)
  naming the address, the proxy and token variables and the folder for the binaries.
- The dark preset also darkens the ground of the network and seepage maps, the cell edges of
  `mesh_map` and the text boxes; `sfr_longitudinal_profile` plots each branch against its
  distance to the outlet; the wells overlay warns with the key to set when the run kept no
  well field.
- A forcing value written with its unit (`'100 m**3/day'`) is no longer scaled a second time by
  `units`, wells included; a `units` key beside such a value is refused ("Write the unit once").
- Lake and SFR rainfall and evaporation are rates in length per time: `'2 mm/day'` is read as
  m/s and `units` must be a length per time. They were typed as a volume per time.
- A negative lake rainfall, evaporation, runoff, inflow or withdrawal is refused with the
  MODFLOW 6 LAK convention (each is zero or more), at `hmp config check` for values in the file
  and before the solver for values read from a file.
- A transport solver name that is neither built in nor a registered plugin is refused with the
  valid names.
- A side or sea constant head below the bottom of its cell stops a MODFLOW-NWT run before the
  solver, as for MODFLOW 6; NWT ran on with an inert boundary and a worse budget.
- A hydrography `rasterize_field` that holds text is numbered per feature instead of being
  handed to Whitebox as text.
- Runs recorded before the recent refusals rerun and resume again: a stored configuration
  (catalog snapshot, `runs/<run>/config.toml`, checkpoint `resolved_config.json`) is migrated when
  read, dropping or moving the root `[persistence]`, a stored `solver.backend` that disagrees with
  the flow process, a null `cell_id`, `data.lake_abacus.id` and the removed site_selection keys,
  with one log line. A file a user writes is still refused.
- Testbed and comparison children make the `mesh_catchment.geology` paths absolute again (the
  block is now typed), and a comparison child that changes the flow solver keeps what
  `comparison.base_simulation_overlay` sets in `simulation.process`. A `solver.backend` derived
  from the flow process no longer counts as written by the user.
- A forcing record whose time index is not in nanoseconds takes the samples of its own periods;
  every period silently took the last sample. A piecewise forcing checks the coverage of each
  segment only on the periods it keeps.
- Under MODFLOW 6 with `negative_to_evt`, a negative numeric `first_clim` gives the steady period
  that net rate through EVT even when the record has no negative value; a steady one-period run
  with `first_clim = "first"` takes the first value of the record again, not its mean.
- `hmp.run(cfg, until_step=0)` and `from_step=0` run the window instead of returning an identical
  completed run; an archive exported before the `nse_log` rename is imported under `nse_log`.
- A station whose data stops short of the window it was asked for (ONDE campaigns, a gauge
  without a value on the first day) is served by `hmp run --frozen`; stations cached before this
  change need one run without `--frozen`.
- Nightly validation results carry the commit and branch that were checked out; the Quick start
  check passes only `HMP_CACHE_HOME` and `HMP_BIN` to the page commands; the `llms.txt` of each
  documentation version links its own pages.

### Removed
- `[simulation.results.derived]` and `[simulation.results.budget]` (refused by the model,
  dropped on load by the migration), the `derive()` hook of every output adapter, the
  post-run derivation module `simulation/extraction/derivation/derived.py`, the derived
  registry of the workflow (`workflow/internals/derived.py`) and the drop of the
  intermediate budget at the seal.
- `[geographic.enforce_streams]`, the burn of the mapped network into the routing DEM, and what
  existed for it: the burned DEM, the catchment delineated again without the burn and its drift
  check (`max_catchment_area_drift`), the resolution of its `stream_geometry_path` from the
  hydrography sources and the download of an API network for it. An observed network never
  enters the model construction: the criterion takes the map by its heads, and the descent D is
  pinned on the generated network A whenever the run generates it. A file declaring the section
  is refused. The geographic cache fingerprint changes for every project, so each rebuilds its
  geographic tree once, and a run snapshot written before declares the section and no longer
  loads (`hmp catalog rerun`, `Project.derive`).
- `[modflow6.sgrid] condition_top` and `condition_top_epsilon`, `[modflow6.sgrid.top_sampling]
  network_safety_net` and `max_channel_lowering_m` (and their `[modflownwt.sgrid]` copies), with
  the surface conditioning they drove (`spatial/mesh/surface_conditioning/`, the
  `.conditioning_ref.npy` sidecar, `mesh/topography_reference`): the solver top is never
  conditioned, D carries every flow path. Refused when declared.
- `stream_threshold_km2` and `stream_threshold_cells` of `[flow.sinks_sources.sfr.<id>]`: SFR
  traces its reaches on A, whose threshold is `[geographic.river_network]`. Refused when declared.
- The one-way pass that lowered the downstream reach top of each SFR link below its upstream one
  (by up to 29.8 m): the streambed profile comes from the bed profile solve alone, the bed
  regularisation being the option that smooths it.
- `diagonal_neighbors` of the point and cell calibration outputs: their discharge follows D,
  whose neighbourhood the mesh fixes (shared nodes on an all-quad mesh, shared faces
  otherwise). A file declaring it there, including the dump of a run sealed before, is
  refused with the key named. The network outputs keep it for the criterion.
- `[geographic.snap_streams]` and everything that existed only for it: the snap of the
  mapped network onto the talwegs (`core/stream_snap.py`), its raster pass in the
  geographic step, the snapped map stored with a run, the two snap figures, the Eq. 4
  bounds on the snap displacement and rejected share, and the snap floor `F` of the
  validity length (provenance `auto_floor`), and the `network_map` column of the network
  comparison exports, which only told the snapped map from the raw one. In `apply` mode it rejected almost every
  mapped cell on a 25 m Voronoi mesh, because it placed a cell only when its receiver
  already reached the outlet. A TOML that still declares the section is refused.
- `rectify_on_mesh` no longer requires `[modflow6.sgrid] condition_top = true`: the check that
  refused it is gone, and nothing else requires a conditioned top.
- Docs: the About pages How to cite, Usage bibliography and Release policy, replaced by Cite,
  Applications and papers, and Versions and stability; the theory pages Vertical representation
  and storage assumptions and MODFLOW governing equation and CVFD formulation, merged into
  Groundwater flow and Solvers.
- The `geology_field` keyword of `discretize_fieldparam_on_sgrid`: use `support_field`.
- `_data/changelog.json`, which the docs build wrote and nothing read.
- The top-level `[persistence]` table, which no run read. A file that writes it is refused
  with the key to write: `[simulation.results.persistence]` for a run, `[calibration.persistence]`
  for a calibration.
- `transport.modpath.parameters.track_dir = "custom"`, which gave MODPATH no starting location.
- `calibration.outputs.<name>.cell_id`, which every run refused: name the cell with `row` and
  `col`, or place the output with `support = "point"` and `x`, `y`.
- The site_selection keys no step read (`random_seed`, `dem.resolution_m`, `dem.cache_policy`,
  `criteria.ruleset`, `criteria.hard_reject`, `warning`, `soft_score`, `report_only`,
  `criteria.geology.prefer_diversity`) and `data.lake_abacus.id`; each is refused with what to
  write. One key per job: `strategy.candidate_mode` is refused for `outlets.candidate_mode`, and
  the flat `observations.flow_station_mode` and `flow_station_max_distance_km` for the nested
  `flow_station` keys. Example 17 still writes them; its tests are marked as expected failures
  until it is migrated.
- `fill_method` of the CSV forcings (wells, boundaries and the generic CSV forcing) and the
  `id` of `[data.lake_bathymetry]` and `[data.lake_geometry]`, which no step read. A file that
  writes one is refused with what decides instead; a run stored before still loads.
- Docs: the user guide. Its task pages had to follow every change of the code by hand; a
  series of examples will replace them. Its old URLs redirect to the reference, Understand or
  Theory page of the same subject.
- Docs: the theory that external sources already give. The MODFLOW 6 and MODFLOW-NWT
  equations, the laws of the DRN, EVT, CHD, LAK, SFR and MVR packages, the Newton and IMS tests
  and the textbook derivations are now a sentence with the USGS report or the MODFLOW 6 input
  guide. Theory keeps what HydroModPy computes or decides. The comparison of MODFLOW 6 and
  MODFLOW-NWT and the limits of Dupuit are sections of Solvers and Groundwater flow, and their
  URLs redirect there.

---

## [v2.0.0a4] - 2026-09-29

### Changed
- Time-varying fields are stored in float32 with the mantissa rounded to 16 kept bits
  (`[simulation.results.persistence] field_precision = "compact"`, the default; `"exact"` keeps
  float64). The error is at most 2**-17 of the value, under 1 mm on a 130 m head, and a rounded
  array carries the CF `quantization` attributes. `release_flux` and `fluxes_from_budget` are
  rebuilt on read from the budget terms instead of stored. A daily 6-year run of example 04 goes
  from 1375 to 397 MB, a monthly one from 16 to 5.5 MB; its NSE moves by 7e-8. Stores written
  before read as they did. A spin-up writes its cycles exact, since their heads start the next
  cycle and the production run.
- A field is read over a range of timesteps with the store opened once
  (`results.run.geographic.field_range`, `field_steps`), and the flow-state figures use it: the
  15 figures of a daily example 04 run render in 17 s instead of about 2 min, the same pixels.
- A calibration promotes a trial from the solve the trial already ran: the trial's MODFLOW
  folder is kept while it may be promoted (every trial under `save_runs = "all"`, the
  `save_best_n` or the best otherwise), and the promotion resumes at extraction instead of
  writing inputs and solving again. The promoted run is the same, all Zarr arrays bit for bit,
  and is tagged `promoted_from_trial:<N>`; a trial that was not kept is replayed as before, with
  the reason logged. On the daily API grid of example 04 a promotion no longer spends its ~7 min
  of solve. The kept folders are released on every exit path.
- The CLI banner draws every letter whole in its color. The slanted font joined the Hydro "o" to
  the "M" and the Mod "d" to the "P" with a shared stroke, so the color changed inside a letter
  and the "P" had no yellow stem. The art keeps a blank column at both joins, four columns wider.
- Every file of example 04 draws more figures and writes exports to `share/<run>/`. Step 1
  declares three `[[export]]` blocks, steps 2 to 4 append theirs with `[[export__append]]`, and
  step 5 drops them with `export__delete = true` to write its own eleven. `project.toml` exports
  the catchment and its network, the water table and the seepage cells of October 2002, the
  discharge and the budget, which every calibration writes for each run it promotes; the daily
  API grid writes its own, dated 2019. Step 2 keeps the per-cell recharge, which the distance map
  and the persistence maps of step 4 read. The composite calibration draws its cost profile and
  its distance crossing against K instead of four figures that did not apply to two parameters.

### Fixed
- The scan of `data/<variable>/` before a run removes an orphan sidecar, one whose data file is
  gone, when it holds nothing the file does not give back (hash, CRS, bbox, undetermined licence).
  Git ignores the sidecars HydroModPy writes, so a data file a commit removed left its sidecar in
  every clone, and every `hmp run` of that workspace warned `auto_scan skipped` about it, lake
  sidecars included for a run without a lake. A sidecar with a stated licence or notes is kept
  and reported as kept; `hmp data check` says which of the two the next scan does.
- A calibration whose gauge comes from an API cache promotes its runs again. A station read back
  from its cached `_LOC.csv` carried numpy values, and a one-station file reads an integer
  column as `int64`, which the catalog refused to write as JSON: every promotion of the daily API
  grid of example 04 failed on its second launch. A station location now holds plain Python
  values, whatever reader built it.
- The catchment buffer no longer warns `The resolution argument to buffer is deprecated` under
  geopandas 1.2, which renamed it `quad_segs`; 1.1 still requires the old name, and the declared
  range covers both, so the buffer calls shapely directly.

---

## [v2.0.0a3] - 2026-09-29

### Changed
- On a terminal, a console log line starts with a glyph for its level, like the phase checkmarks:
  `✗` error, `!` warning, `›` milestone, `·` debug. A long line wraps under its message, not
  under the glyph. The `next:` line of the run recap prints dim, without a glyph
  (`core.progress.HINT`). A pipe keeps the `[WARNING]` labels, and the log files are unchanged.

### Fixed
- `hmp example add 04` merges the rows of the stations it reads (NANCON, NANCON_REA) into the
  workspace registries `data/<variable>/<variable>_custom_LOC.csv`. `hmp workspace init` writes
  those registries empty, so every hydrometry, recharge and runoff load failed and the full
  transient runs diverged. A row already there with other values is kept unless `--force`.
- `hydromodpy.__version__` reads the `pyproject.toml` of the checkout it is imported from before
  the installed metadata. An editable install keeps the number it was installed at, so a
  checkout bumped to 2.0.0a2 still reported 2.0.0a1 in `hmp doctor`, run provenance and PNG
  metadata.
- Several runs of one project run at once. Each run, or each calibration session with its
  trials, phases and promotions, works in its own `.hmp/scratch/<config>.p<pid>/`
  (`core.state.paths.run_scratch`): its preprocessing, its solver folders and the recharge its
  trials share. `.hmp/scratch/` was shared by the whole project, so on example 04 four runs
  started together lost three in `build_geographic` (a Whitebox panic, a missing
  `dem_fill.tif`, a missing `outlet.shp`), concurrent calibrations read the network another run
  wrote and shared one `_shared_recharge` across different recharges, and a run that ended
  swept the solver folders of all the others ("Solver output directory is missing", "CBC file
  not found"). A child process inherits its parent's folder through `HMP_RUN_SCRATCH`; the next
  run of the project removes the folders of killed runs. `PREPROCESSING_DIR` is replaced by
  `core.state.paths.preprocessing_dir(root)`.
- `batch_size` and `parallel` of a calibration and of a phase are user options, and `parallel`
  alone now runs trials side by side: a batch holds at least `parallel` trials, where a batch of
  one serialized them. Measured on the composite of example 04, 8 trials at `parallel = 4` take
  278 s for 695 s of solves. `run_calibration_api_daily.toml` solves its five K at once.
- `scipy_nelder_mead` runs on a port of SciPy 1.18.1's Nelder-Mead that evaluates the candidates of
  one step side by side (reflection, contractions, expansion, shrink points) and keeps only the
  values SciPy's rules read: the path, the answer, the evaluation count and the status are SciPy's,
  call for call, at every `parallel`. The candidates solved and not read stay in the history,
  marked `speculative_unused` in the journal, and spend no budget.
- The root search uses `parallel`: its sweep is solved at once, and each round cuts the bracket
  into `parallel + 1` parts in log instead of two, both roots of a two-bound search at the same
  time. On the Nancon bounds, one root takes 6 rounds (20 solves) at 4 against 15 rounds today,
  two roots 8 rounds (26) against 24. The root lies in the same stopping-width bracket; `parallel
  = 1` repeats today's search trial for trial, and the counted budget follows the width.
- Every phase takes the `parallel` and `batch_size` of `[calibration]` unless it sets its own
  (`CalibrationConfig.parallel_for`, `batch_size_for`): the phases a protocol writes declare none,
  so the section's value reached none of them.
- `Run completed: <name> [<id>] <n>s` prints the run's duration, the `duration_s` the catalog
  stores, instead of the solver step alone (6 s printed for a 19 s run).
- The help of `[simulation] if_exists` says what `replace` does: it trashes the predecessor,
  which keeps its name, and registers the new run under the next free `name.vN`. It said the
  new run took the name.
- `flux_timeseries`, `water_budget` and the testbed budget metrics read the catchment budget
  zone, or the domain one when there is no catchment, and the figures name the frame. They
  summed both zones: the catchment lies inside the MODFLOW 6 domain, so its water was counted
  twice (1.68 m3/s of recharge drawn for 1.09 on the domain and 0.59 on the catchment).
- `seepage_network_confusion_map` and `network_extent_bounds_map` count every legend class on
  the frame they declare. "no stream" counted the whole grid (20 548 cells) under "frame: the
  delineated catchment", and the both-bounds extents counted the domain (1234 cells) next to
  scored counts taken in the catchment (714).
- A GeoPackage or Shapefile export of `simulated_active_network` holds the active cells only,
  with their attribute. It wrote every cell of the grid (21 406 polygons, 610 active, 5 MB).
- The calibrated discharge adds a gridded runoff (SIM2, `extent = "watershed"`), reduced to its
  watershed mean as the run stores it. The objective read runoff stations only, so
  `run_calibration_api_daily.toml` scored the drain alone against the total gauged flow while
  its runs reported drain plus runoff, which pushed K onto the lower bound.
- A network output whose `time` is a date is redrawn at that date by the figures of the run,
  on the period `[s, e)` that holds it, the state the trials scored. The derive path accepted
  `last` and `first` only, so the promotion of `run_calibration_composite.toml`
  (`time = "2002-10-15"`) failed in its display step. The period rule moved to
  `core.time.selection.resolve_state`, shared by the calibration and the results layer.
- Every run a calibration promotes keeps its watershed. The export step of the first promotion
  dropped the session's shared preprocessing tree, so with `save_runs = "all"` the next ones
  had no watershed: their catchment discharge summed the whole domain (PBIAS -95 % on the
  daily API grid of example 04) and 6 of 15 figures did not apply.
- A calibration whose promotion fails says so and exits 21 (`CalibrationError`) from `hmp run`
  and `hmp calibrate`, after printing the results of the search, which are kept. It printed
  "done" and exited 0 while the promoted run was `failed` in the catalog.
- The progress line of a bisection shows its bracket, then its root, instead of the lowest
  cost met, which is not the answer of a root search (BD Topage: `best 71.8` at K = 1e-7 for a
  root at K = 5.9e-6).
- A calibrated value no other trial comes close to prints "no other trial within the
  tolerance" instead of a zero-width interval `[x, x]`.
- A session journal names its project (the project folder, as its runs do) and the metrics of
  its objective blocks, and drops the `variable`/`objective` pair a block-scored phase leaves at
  its defaults. It wrote `project = "calibration"`, `objective_name = "nse"` and
  `variable = "head"` for a network phase scored on `distance_gap`.
- The calibration figures read what they need from the session journal:
  - `parameter_cost_profile` marks the trial the calibration returned, not the lowest cost:
    the BD Topage profile named K = 1e-7 for a returned K of 5.9e-6.
  - `matching_hydrographic_network_card` of a two-bound search shows Delta, the combined value,
    the validity and the cells without being passed the roots.
  - `bisection_bracket_trace` draws a two-bound search, both residual series and both roots.
  - `parameter_cost_profile` and `calibration_progress` share the interval of the calibration
    summary (one mesh cell for a distance cost, 5 % otherwise). The profile drew a +10 % rise
    instead, `[8.094e-05, 8.115e-05]` for a summary of `[7.499e-05, 1e-4]`, and its `rise`
    option is removed.
  - The axes carry their units: `K (m/s)`, `|D_so - D_os| (m)`, `1 - NSElog (-)`.
- A figure that finds while reading the run that it does not apply raises
  `display.figure.FigureNotApplicable`, and the batch skips it with its reason whatever
  `on_error` says. The one-parameter calibration figures do so on a session that sampled
  several parameters together: the composite of example 04 (K and Sy) failed its promotion on
  `downslope_distance_crossing` under `on_error = "raise"`.
- The figures of a run redraw the stream network with the mean recharge its trials scored
  with. The trials averaged the rate the forcing gives each period; the redraw averaged the
  budget, where a steady spin-up period holds the record mean in place of its month (8.656e-9
  against 9.075e-9 m/s on the monthly Nancon), so the drawn network was cut at another
  threshold than the scored one and "The mean recharge moved" was logged for an unchanged
  forcing. Both now apply one rule (`core.stream_recharge`) to the forcing, the redraw reading
  the station forcing the run stores; a real change of data or window still warns.

---

## [v2.0.0a2] - 2026-09-28

### Added
- `[[export]]`: one block per export request (`variables`, `time`, `period`, `format`, `folder`,
  `file`, `crs`, `resolution`, `layer`, `nodata`). The format follows the data: GeoTIFF for a field at
  one date, NetCDF for several dates, CSV for series and the budget, GeoPackage for vector layers.
  The catchment, the mapped networks, `watershed_dem`, the water budget and the virtual field
  `simulated_active_network` become exportable. `format` also takes `package`, `stac`, `rocrate`, `prov`.
- `hmp export SIM_REF [variables...]` speaks the same words (`--time`, `--period`, `--format`, `--file`,
  `--crs`...), and `hmp export SIM_REF --list` prints what a run can export, by kind.
- `hydromodpy.core.time.selection` and `Run.step_at`, `Run.steps_for`, `Run.period_edges`: one
  date-to-stress-period resolver for figures and exports.
- `[display] time` and a per-figure `time` name the instant a map draws as a date, `first` or `last`;
  a steady calibration phase resolves any date of its record, so no phase override is needed.
  `hmp.figure(..., time=...)` and `hmp viz show --time` take it too.
- A network calibration output takes an ISO date in `time`; `normalize_cost = true` on
  `distance_gap` and `distance_mean` divides by the validity length, so phase shares are real shares.
- A calibration ends with a short recap in normal mode (one line per phase, best values with their
  interval, where the best runs are) and writes its methods paragraph to `methods.md`.
- `[geographic.snap_streams]` in `apply` mode reaches every consumer of the mapped network:
  stream burning snaps the map on the raster's own D8 graph before burning it, a mesh built along
  a mapped network (`rivers.source = "file"`) follows the snapped lines, and the network cells,
  metrics, CSV exports and reference-network figures read the snapped map the run stored.
  `diagnose` keeps the raw map everywhere while the snap is computed and reported.
- A calibration session stores its root-search result (`bracket`, or `roots` with both roots,
  Delta and the combined value) in `session.json`; the protocol card and the calibration report
  read it back.
- `hmp calibrate --check` says when stage two of the protocol scores the whole run, spin-up year
  included.
- A network calibration output takes a minimal (permanent) map beside its maximal one, as a file
  (`minimal_stream_geometry_path`) or as the permanent reaches of the hydrography data family
  (`minimal_observed_network = "data.hydrography"`, refused by name when the source says nothing
  about permanence). The maximal map is scored as the union of the two, and
  `frac_minimal_outside_maximal` is published.
- The transient two-bound mode, `[calibration.outputs.<name>.extent]`. For each complete calendar
  year inside the phase's `scoring_window`, the maximal simulated mask holds the cells flowing at
  least `maximal_flowing_steps` timesteps and the minimal one the cells dry at most
  `minimal_dry_steps` timesteps (both 1 by default, counted in timesteps); the years are aggregated
  by `year_quorum` (0.5) and each bound is scored once with the distance criterion. A cell flows
  when it is in the downstream closure of the seepage and its routed discharge reaches
  `visible_flow` ("1 L/s" by default, or a share of the outlet discharge such as "1%").
  `hydromodpy.core.stream_extent` holds this one definition of flowing for the criterion and the
  figures.
- Two bounds, one value: the bisection closes one root per bound on the same trials and returns
  their weighted geometric mean, log K = w_min log K*_min + w_max log K*_max (`weights`, 0.5 each),
  evaluated once so every published number comes from a solve. The report and `hmp calibrate`
  give both roots, both brackets and Delta = log10(K*_max / K*_min); a minimiser's cost is
  w_min |J_min| + w_max |J_max|. `max_iter = "auto"` budgets both roots.
- `[geographic.snap_streams]` (`off` by default, `diagnose`, `apply`) moves the mapped network
  onto the talwegs of the criterion graph, flow-accumulation guided from downstream to upstream,
  within a radius in metres (2 h_obs by default), rejecting what it cannot attach. Trials publish
  the displacement (p50, p90), the rejected share, the length ratio and the floor F, the Doptim of
  the snapped map against the raw one; in `apply` Eq. 4 also bounds the displacement. A run
  stores its snapped map, and two figures, `observed_network_snap_map` and
  `observed_network_snap_histogram`, show what moved.
- `validity_length` on a network output, `"auto"` or a length such as `"150 m"`: Eq. 4 reads
  Doptim <= validity_length. `"auto"` is 2 h, with h = max(h_obs, observed_position_accuracy), and
  h + max(h, F) when a snap floor exists. Each trial publishes the length and what set it.
- `network_extent_bounds_map` draws the maximal and minimal simulated extents of a transient run
  against its two maps, outside any calibration.
- `hydrographic_network_permanence` draws the mapped network split by permanence: the permanent
  reaches (the minimal map) over the reaches the complete map adds, with the length and reach
  count of each class. It needs a hydrography source that says which reaches flow all year.
- Preflight refuses an extent table on a steady search, a minimal map file that does not exist,
  and a `data.hydrography` minimal map without a declared hydrography source.
- `hmp run` on an overview ends on the catchment, its area, the web report and the figures folder;
  `--verbose` keeps the full recap. The overview shows its phases and the data families load
  under one progress bar.

### Changed
- `optimizer_kwargs` is now `method_options`, and the protocol's `*_engine_options` are
  `*_method_options`; the old names load with a warning. Options are checked when the file loads
  and by `hmp calibrate --check`. The rename changes every calibration `params_hash` once.
- The per-figure `timestep` is now `time`; old files load, `hmp doctor --fix-config` rewrites them.
  An unknown key in `[display.overrides.<figure>]` is refused at load.
- An old `[export]` table of format toggles or `[[export.artifacts]]` loads as `[[export]]` blocks.
- `hmp calibrate --check` prints only real departures from the paper; the full record is at `-v`.
  `--expand` prints the whole pasteable section. `--list-phases` prints shares below 1 % and names the
  station a point output observes.
- A scoring window is accepted beside a network output read in one state; it is refused only when
  it does not hold that state. `warmup` and `warmup_periods` move to the expert profile.
- Promoted calibration runs are named `<simulation name>_<phase>` instead of `<method>_iter_NNNN`.
- Figures: `seepage_map` draws two classes; maps open on the catchment in projected metres; titles
  name the period drawn and say `catchment outlet`; the identity card drops its status and id rows
  and wraps long names; the network maps state the seepage threshold in words.
- Normal console: the licence warning prints once per workspace; `Run completed` prints last; the
  figure summary warns only when a config option would have kept a skipped figure; the runoff and
  outlet messages are one sentence each.
- `[geographic].dem_correc_type` defaults to `"fill"`, the paper's FillDepressions, instead of
  `"breach"`. A file that writes `"breach"` keeps it, and the Methods paragraph and
  `hmp calibrate --check` name it as a departure from the paper.
- `matching_hydrographic_network` is version 1.2: the DEM is filled by default, stage two leaves
  the first year of the run out as spin-up unless the file declares a window, and the Eq. 4
  bound is a length. A pin on 1.1 is refused.
- The protocol card reads the keys a trial published: both bounds side by side in the two-bound
  mode, the validation map beside the scored one in a one-state run.
- Example 04: every TOML follows the current code (budget `"auto"`, no retired key, comments on
  the criterion, the maps, the buffer and the protocol version brought up to date), the new
  options shown commented out; the burning of the routing DEM is dropped.
- With both maps, a one-state network output is scored on the minimal map, as the WRR 2025 paper
  calibrates, and the maximal map is published as a validation outside the cost.
- `L_ref`, the length that normalises roptim and sets the interval width of a network search, is
  h_obs, the median distance between neighbouring cell centres over the mapped cells of the
  catchment. Unchanged on a regular grid; the fine cell on a mesh refined along the streams.
- roptim is always Doptim / h_obs, the paper's Eq. 3; a declared `observed_position_accuracy`
  enters the validity length only.
- The persistence figures and `simulated_active_network` in persistence mode count a cell as
  flowing by the criterion's definition, and the stream-network maps redraw with the settings the
  run sealed, so they show the partition the trial scored.
- Toggling `[geographic.snap_streams]` does not invalidate the geographic cache.
- `hmp config template` without `--modules` writes every module, `[calibration]` and
  `[mesh_catchment]` included. They were left out so the template would validate as written,
  which it never did.

### Removed
- `hmp data export`, `hmp data export-package` and `hmp catalog export`: `hmp export` replaces them.
- The `[export]` format toggles, `output_dir`, `[[export.artifacts]]` and `var`, `fmt`, `dest`.
- `roptim_max`. The load-time migration and `hmp doctor --fix-config` drop `roptim_max = 2`, which
  `validity_length = "auto"` reproduces, and refuse any other value with the length to write.
- `geometry_from_run`, replaced by `network_maps_from_run`, which returns every declared map.

### Fixed
- `hmp calibrate --check` names an option a phase-two method refuses, instead of failing after phase
  one spent its budget.
- The network criterion no longer warns that the mean recharge moved on float noise.
- The protocol card of the second promoted run draws the first stage instead of empty panels.
- `flux_timeseries` draws each flux over its own period, not one period late.
- Exported NetCDF files carry the mesh size and ACDD metadata; CSV times are naive ISO times of the
  run clock, observed series are clipped to the simulated window, and the simulated discharge is
  exported under `catchment`, not `_catchment`.
- A renamed configuration key now warns in normal mode.
- The MODFLOW 6 and MODFLOW-NWT routing context falls back on the `[geographic]` default, no
  longer on a hard-coded `"breach"`.
- A delineation refuses a log-transformed accumulation only where its outlets snap. The float32
  ranking bound was read on the whole regional raster, so a filled DEM whose main river drains
  more than a million cells refused an outlet on a tributary (example 04).
- A single-metric phase whose variable names a calibration output keeps that output, so a network
  phase keeps its maps and its extent table.
- `hmp calibrate` migrates legacy keys in memory when it reads a file, as the project loader does.
- A station read back from the data cache keeps the variable its download gave it (`discharge`,
  `groundwater_level`, `lake_level`), not the family name. A Hub'Eau gauge was stored as
  `hydrometry_obs` from its second run on, and the hydrograph figures and the calibration did not
  find it.
- An IGN BD ALTI DEM sets its sea to nodata: the zero-valued regions touching the raster edge or a
  nodata cell. The sea was one flat plateau the breach step could not route in reasonable time.
  `py7zr` is declared, the fallback the BD ALTI archives are extracted with when `7z` is absent.
- A station named in `station_ids` survives the watershed mask, as `nearest = true` already did.
  A piezometer or gauge asked for by id was dropped when it sat outside the catchment.

---

## [v2.0.0a1] - 2026-09-28

### Removed
- `reference_values` from calibration protocols and from `protocol_record`.
- The `hydromodpy.optimizer` entry-point group. A method it listed was refused
  anyway by the closed union of `optim/method_config.py`. Search methods ship
  with HydroModPy; a search of one's own runs from Python, as an object that
  satisfies `Optimizer` handed to `CalibrationEngine(optimizer=...)`.
- `geographic.bottom_path`, which nothing read. `hmp doctor --fix-config` and
  the loader move its path to `[[data.substratum.sources]]` and leave
  `[domain.depth_model]` as it was; a loader that skips the migration accepts
  the key, ignores it and warns. Dropping it from the geographic fingerprint
  rebuilds each geographic cache once.
- `examples/projects/02_nancon_watershed/run_sweep_sy.toml`, a design draft for
  a `sweep` workflow that does not exist, and `run_transient_prototype.py.draft`
  leave the example.
- `examples/projects/19_cheze_reservoir`, the lake test project of the Chèze
  reservoir, the three projects of `examples/projects/new_to_sort`, the Chèze
  diagnostic scripts of `tools/diagnostics/` and `tools/view_mesh_grid_3d.py`
  leave the repository with the lake data only they read. None was cited by a
  test, the documentation or the example manifest.
- The `data-fetch` process, `hydromodpy/data/fetch/` and
  `hydromodpy/schema/processes/data-fetch@1.json`. `data-request` replaces it
  and serves every `[data]` variable instead of six sources. Only the request
  format changes. A `data-fetch` request named one source by a tagged `id`
  with its options beside it, and the extent at the top of `inputs`:

  ```json
  {"process": {"id": "data-fetch", "version": "1.0.0"},
   "inputs": {"source": {"id": "hubeau-piezometry", "product": "level"},
              "mask": {"href": "/jobs/4711/outputs/watershed.gpkg"},
              "period": {"start": "2020-01-01", "end": "2020-12-31"}}}
  ```

  A `data-request` request carries `[data]` sections, written as in a project
  TOML, and the extent under `extent` (`bbox` with `crs`, `mask`, or
  `station_ids`); a plugin source goes under `installed` by `name`:

  ```json
  {"process": {"id": "data-request", "version": "1.0.0"},
   "inputs": {"data": {"piezometry": {"sources": [{"source": "hubeau", "product": "level"}]}},
              "extent": {"mask": {"href": "/jobs/4711/outputs/watershed.gpkg"}},
              "period": {"start": "2020-01-01", "end": "2020-12-31"}}}
  ```

  The report moves from `outputs/fetch.json` to `outputs/request.json`, and
  the payload from one of `outputs/points.parquet`, `fields.nc`,
  `features.gpkg`, `raster.tif` to one `outputs/<variable>_<source>` file per
  variable and source. A chain links the mask as `extent.mask` instead of
  `mask`.
- `HubeauPiezometrySource`, `IgnDemSource` and `Sim2PrecipitationSource`, and
  the source ids `hubeau-piezometry`, `ign-bdalti` and `sim2-precipitation`
  of `hydromodpy.data.source.registry`. Their only caller was `data-fetch`.
  Piezometry, the DEM and SIM2 are asked through their `[data]` section, in a
  project TOML or a data request; a plugin source goes under `installed`. The
  port keeps `BdTopageSource`, `EuHydroSource` and `OsmSource`.
- `hydromodpy.data.DataManagers`, `hydromodpy.data.loading.entry.DataEntry` and
  `hydromodpy.results.catalog.cross_db.entry_used_by`, which nothing called.
  With them go the two layer tolerances `data -> results` and
  `results -> data` that the cross-database bridge needed; `run.input_entries()`
  remains the way from a run to the cache entries it read.
- The 7-name facade of `hydromodpy.calibration.runners`, which nothing
  imported, and `hydromodpy.calibration.protocols.registry.assert_version_is_available`:
  the protocol version is checked in `matching_hydrographic_network.py`
  instead.
- `hydromodpy.display.renderer.save_figure`, `hydromodpy.display.theme.plot_params`,
  `hydromodpy.display.colormaps.check_no_banned_in_call`, the module
  `hydromodpy.display.geo.basemaps`, and `GeoFigureMixin.add_basemap` with the
  `crs` attribute only it read. Nothing called them; a figure is saved by
  `BaseFigure.plot`.
- The module `hydromodpy.display.catchment_report.cli`: the options of
  `hmp report catchment` live in `hydromodpy/cli/commands/report.py`,
  unchanged. `python -m hydromodpy.display.catchment_report.pipeline` and
  `python -m hydromodpy.display.catchment_report.context` go with it: use
  `hmp report catchment <toml>`, or `build_context_from_report_config` from
  Python for the context alone.

### Added
- BD Topage reaches carry a canonical `permanence` column (`permanent`, `intermittent`,
  `ephemeral`, `dry`, `unknown`, vocabulary in `hydromodpy/data/source/permanence.py`) beside
  `PersistanceTH`. The download writes its permanent reaches to
  `hydrography_bdtopage_permanent_<hash>.gpkg` beside `hydrography_bdtopage_<hash>.gpkg`, the run
  clips them to `streams_permanent.shp` beside `streams.shp` and keeps them as the
  `reference_permanent` hydrographic network. A network that says nothing about permanence has no
  permanent part.
- `CatchmentDomainProducts` and the geographic cache manifest record `buffer_rule`,
  `buffer_declared` and `buffer_area_increase`, so a domain says how its margin was drawn.
- A MODFLOW 6 twin validation case for the stream-network criterion. A planar hillslope run at
  a known K draws the mapped network, and a network-only bisection recovers that K within 1 per
  cent, with J at zero and consistent K/R, dsat, T/R and Toptim in the report
  (`tests/validation/calibration/test_twin_matching_stream_network_modflow6.py`, tolerances rows
  76 to 79).
- `observed_rasterization` on a network calibration output. `"crossing"`, the default, keeps a
  cell where a mapped line crosses the segment joining two edge-sharing cell centres: on a grid
  this is WhiteboxTools VectorLinesToRaster, the paper's tool, so a model that reproduces the map
  scores J = 0. `"touch"` replays sessions made before. `line_crossing_cell_mask` serves DIS,
  DISV and Voronoi meshes. The redrawn comparison figures read the same rule, and each trial
  publishes `n_observed_cells` and `n_observed_features_fallback`.
- Secondary network diagnostics, outside the cost: `D_so_over_D_os` and the overlap indices of
  the authors' published code (`overlap_Ea`, `overlap_Sa`, `overlap_Na`, `overlap_E`,
  `n_neither`, `L_sim_m`, `L_obs_m`).
- The calibration report records the Eq. 4 verdict of the returned trial (`roptim_verdict`), the
  final bracket of a bisection (`bracket`) and whether the search met its stopping rule
  (`search`); `hmp calibrate` prints each on one line. The bisection warns at start when
  `max_iter` is below what its bracket needs.
- `hmp calibrate --check` warns when an objective scored only on network outputs moves more
  than one parameter, a T/R ridge. A network search that moves K is refused, at preflight and
  before the first solve, next to an active SFR or LAK, whose conductance does not follow K.
- The staged report and the Methods paragraph publish the steady window stage one averaged the
  recharge over; a window shorter than 365 days warns.
- `matching_hydrographic_network` declares six more departures: the outlet sealed into the
  target of D_so, the `L_cap` saturation and its 5 % guard, the log10 K bisection and its sweep,
  the support of D_os against the authors' published code, `breach` by default and the
  rasterisation rule.
- The aquifer geometry can be calibrated. `[calibration.parameters.thickness]` searches the
  thickness of a `constant_thickness` depth model (log space) and
  `[calibration.parameters.substratum_elevation]` the elevation of a `flat_substratum` one
  (linear space); `hmp config targets` lists whichever the declared depth model carries. The
  file states the bounds. A parameter that reaches a raster depth model, or a field the
  declared kind does not expose, is refused and the error names the kind.
- A stream-network trial publishes the paper's `dsat` as `<output>.d_sat_m`:
  the saturated thickness averaged by area over the catchment, at the state the
  network is read from. Beside it, `d_aquifer_m`, `d_sat_over_d` and
  `d_sat_unset_fraction`. A backend that serves no saturated thickness
  publishes none of them and still scores the network.
- A calibration whose one moved parameter is `flow.param.K.field.value`,
  written as a value and scored on a network output, reports the derived
  values of Table 1 of Abherve et al. (2023): `k_over_r`, `k_optim_m_s`,
  `d_sat_m`, `t_over_r_m` and `t_optim_m2_s`, printed on one line by
  `hmp calibrate`. A search on any other parameter gets none of them.
- A raster substratum: two depth models read the bottom of the aquifer from
  the new `[data.substratum]` variable, one user raster in metres.
  `kind = "raster_substratum"` takes its values as the substratum elevation,
  the raster twin of `flat_substratum`; `kind = "raster_thickness"` subtracts
  them from the top, the raster twin of `constant_thickness`, and takes a
  `scale`. Both take `offset` and `min_thickness`. The raster is reprojected
  onto the grid of the top and must cover every cell of the chosen extent (the
  catchment for `domain_extent = "watershed"`, the buffered box for `"box"`),
  or the run stops and counts the missing cells. The `domain-build` process
  takes it as a `substratum` input, the mask being the extent there.
- The `data-request` process (`hmp process run data-request --job DIR`), the
  job form of `hmp data get`: the managers' cache lives under `$TMPDIR` with an
  in-memory index, a `custom` source is refused before anything is written, a
  variable that fails fails the job with its typed exit code, and the declared
  hosts are those of `hydromodpy/schema/sources.py`. A chain link fills a
  nested member through a dotted path such as `extent.mask`.
- The twelve v1 examples run in the current format, examples 06 to 11 included
  (particle tracking, analytical recession, exponential residence times,
  agricultural transport, PyHelp coupling, a run without plots), with the data
  they read. Example 00 pumps its v1 rates again.
- The stream-network calibration guide gives the protocol and the hand-written
  two-stage calibration of example 04 measured side by side, with the `roptim`
  warning that qualifies the calibrated `K` on this catchment.
- `snap_radius` on a discharge output of `support = "point"` or `"cell"` moves
  the gauge onto the most accumulated cell within that radius, on the drained
  area the solver routes, and logs the distance and the area before and after.
  Off by default: a project that does not write it keeps the cell it had.
- A sealed run or job directory renders its RO-Crate, STAC Item and PROV-O
  views without the catalog, through `hydromodpy.results.export.write_views`,
  with relative hrefs and a WGS84 bbox.
- Progress events reach an NDJSON file named by `HMP_PROGRESS_FILE`, beside
  the terminal renderer, in the fields of the boundary contract (`ts`, `stage`,
  `step`, `of`, `percent`, `message`). A suppressed calibration trial writes
  none, and an unwritable path never stops the run it observes.
- `hydromodpy/schema/sources.py` states the licence of each data source as an
  SPDX id where the provider's terms name one (`etalab-2.0` for BRGM and IGN,
  `ODbL-1.0` for OSM) and leaves the others undetermined, with the reason.
- `-q`, `-v` and `--debug` on `hmp viz`, `report`, `spinup`, `data`, `catalog`
  and `project`, which read only the default and `HMP_VERBOSITY` before.
- `hmp data get` serves data without a project. `hmp data get request.json
  --out DIR` reads a request document (`[data]` sections, one extent among a
  box with its CRS, a mask or station codes, an optional period, plugin
  sources under `installed`); `hmp data get <variable> --bbox ... --crs ...
  --out DIR` builds the same request for one variable. `DIR` receives one
  file per variable and source, cut to the extent and the period whatever the
  cache held, and `request.json`, which lists each file with its sha256, CRS,
  box and period, the empty answers and the failed variables. The engine is
  `hydromodpy.data.run_request` and the document model
  `hydromodpy.data.DataRequest`. A period end without a time keeps its whole
  day. A failed source exits with code 16 once the others are written, and
  leaves no file behind; a request the model refuses exits with code 14, and
  a mask that is not a file with code 10, both before anything is written.
- Public readers in `results` for what `display` read through private
  attributes of a run: `hydromodpy.results.run.particles`
  (`read_particle_tracks`, `particle_time_to_days`, `travel_time`),
  `hydromodpy.results.run.geographic.crs_epsg` and `geographic_metadata`,
  `hydromodpy.results.calibration_trials.calibration_sessions`, and
  `hydromodpy.results.run.array.acting_faces_over_run` and `acting_faces`. Each
  takes the run; `Run` keeps its 50 public attributes.
- `hydromodpy.results.run.particles.has_particle_tracks(run, timed=False)`,
  which says whether at least one particle moved (and, with `timed=True`,
  carries a clock) from the first two steps of each particle.
- `hmp viz list --run <ref>` says, for each figure, whether that run supports
  it or why not (`--workspace` as for `hmp viz show`, `--kind` still filters).
  Without `--run` the listing is unchanged. The Python side is
  `hydromodpy.display.runs.figure_availability(run)`, which returns each figure
  spec with its reason, `None` for a figure the run supports.
- `hydromodpy.display.maps.geo.project_gdf_for_metric_operations`, which puts a
  GeoDataFrame in a metric CRS. `reporting` and the network figures imported it
  under a private name from a figure module. The network figures also share
  `plot_topography_background` under a public name.
- A phase declares `regime = "steady"` or `regime = "transient"` instead of
  overriding the flow regime and the time grid by hand. Steady collapses
  `[simulation.time]` to one period, by default its own extent or the phase's
  `steady_window`; transient restates only the regime and keeps the project's
  own grid. A phase that also overrides one of the paths its regime writes is
  refused. `hmp calibrate --check` catches a steady window given the wrong way
  round, or without both bounds. A protocol now writes `regime` instead of
  computing the five dotted overrides by hand.
- A phase's `objective_blocks` accepts a table, `{ block = share, ... }`,
  instead of a list, giving that phase its own share of each block's cost,
  normalised to sum to one. The list form keeps the block's own declared
  weight, unchanged.
- `[[calibration.phases]]` takes `uncertainty`, with the keys of
  `[calibration.uncertainty]`. The phase wins key by key, and a phase can run
  its own `multistart` or `linearized` width. `hmp calibrate --list-phases`
  prints the width each phase reads and where it comes from, and each phase
  report records the width it used (`extra.interval_width`). `hmp calibrate
  --check` refuses `mode = "relative"` on a phase scored only by network
  distances. The network criterion records one mesh cell per trial
  (`<output>.cell_spacing_m`).
- A calibration report gives the share of the cost each objective block
  actually took (weighted contribution, mean over the finished trials with
  their count, and at the best trial), `CalibrationReport.objective_block_shares`,
  printed by `hmp calibrate` for a phase with two or more blocks, per phase of
  a staged run too (the CLI printed nothing for a staged run before), and
  recomputed for a reused phase from its persisted trials. On the example 04
  by-hand session `20260923-143036`, the best trial takes 37 % hydrograph and
  63 % network for declared shares of 99 % and 1 %.
- `hmp calibrate --list-phases` and `--check` show, per objective block, its
  criterion, share, simulated quantity and observed source (or the
  single-metric route as one row). The first trial of each phase records, per
  output, the dates and pair count it retained (`report.extra["first_trial_pairing"]`).
- `Project.calibrate` accepts `phases=[...]` in Python mode, dictionaries with
  the same keys as `[[calibration.phases]]`, and runs them like a TOML
  calibration that declares phases. Python mode and an embedded declaration on
  a project built in memory write the calibration document the staged run
  reads into the project's `sessions/`, instead of refusing; `hmp calibrate
  <path>` replays it.
- `hmp calibrate FILE --expand` and `hmp.calibrate(FILE, expand=True)` print
  the `[calibration]` section a protocol unfolds into (objective blocks and
  phases), ready to paste into a hand-written file with
  `protocol__delete = true`.

### Changed
- `[[data.hydrography.sources]] source = "bdtopage"` downloads `TronconHydrographique_FXX_Topage2026`,
  every reach, the hydrographic extent. `CoursEau`, the named rivers it read before, left out most
  of the intermittent network (441 of 694 km over the upper Ille). The layer is fixed: `typename`
  is retired, accepted with a warning and ignored so sealed runs replay. The Sandre is asked over a
  Lambert-93 box with `SRSNAME`, in GeoPackage pages of 50 000. Site selection reads the same
  layer.
- A fetched hydrography network is named as every variable names what it fetched,
  `hydrography_<source>_<box hash>.gpkg` (was `<source>_<bbox>.gpkg`), and kept in the CRS the
  source answered in; the stream burn's download is `hydrography_<source>_burn_<box hash>.gpkg`
  (was `burn_<source>_<bbox>.gpkg`). A BD Topage download made before, which holds the named
  rivers, is never served again, and each burn download is fetched once more.
- A bisection counts its budget before the first solve. `max_iter` and the protocol's
  `steady_max_iter` default to `"auto"`, the worst-case count from the bounds, the sweep points,
  `rel_tol` and the bracket expansions (23 on the Nancon, 15 when the root lies inside the
  bounds). A declared number below the nominal count is refused by `hmp calibrate --check` and
  before the first solve; below the worst case it warns. If the budget still runs out, the search
  gets exactly the halvings it lacks, once. Other engines get no extension: a search stopped by its
  budget before its own rule is not converged and freezes nothing.
- A network calibration output reads one state, `time = "last"` or `"first"`. `"all"` and date
  lists, which were accepted and then ignored for the last stress period, are refused at load.
- The stream-network criterion reads one surface. It fills the model top on the mesh graph with a
  priority flood seeded on the border of the domain, snaps the outlet on that graph within two
  cells to the most accumulated cell, and scores the cells upstream of it. The raster polygon only
  builds the domain and places the outlet; each trial publishes `catchment_mismatch`, the share of
  the polygon that differs, and warns above 5 %. Sealing one outlet used to let the seepage of the
  buffer drain into the scored catchment: on a 75 m proxy of the Nancon, 16 % more network cells
  and a root shifted by 24 %.
- `geographic.catchment.buff_area = "N%"` enlarges the catchment area by N per cent, as
  Abherve et al. (2023) describe the domain. The buffer distance is solved on the real polygon,
  then snapped to the DEM grid. On the Nancon the margin falls from 825 m to 150 m and the box
  domain from 151.9 to 120.4 km2. A bare number keeps the v1 rule (N per cent of the square root
  of the area in km2, in km) with a warning, so sealed runs replay their domain. A distance is
  normalised as `"150.0 m"` and a percentage as `"10%"`; `GeographicConfig.from_outlet` and
  `from_polygon` default to `"10%"`.
- The stream-network criterion descends D8 by default (`diagonal_neighbors = true`), the
  paper's reading. On a mesh whose faces are not all quadrilaterals it walks shared edges. The
  comparison, flow-direction and depression figures use the same default.
- Eq. 4 is read once, on the trial the search returns. Trials keep `roptim` and
  `roptim_valid` without warning, and `on_roptim_violation = "error"` raises after the session
  is saved, so a staged calibration freezes nothing.
- A search that reaches `max_iter` before its stopping rule (bisection, SciPy Nelder-Mead)
  gets one extension of half its budget, with a warning. Still open, it is reported not
  converged, its session closes as partial, it freezes nothing and a phase depending on it is
  refused. A SciPy search stopped by SciPy's own `maxiter` or `maxfev` is not converged.
- The fixed-drain-conductance guard refuses only a network search that moves a hydraulic
  conductivity; any other one gets a warning. The criterion compares two networks and can drive
  any parameter, and the docs and messages say so.
- `matching_hydrographic_network` is version 1.1. It says it identifies K/R, attributes stage
  two to Abherve et al. (2025, WRR), and its Methods paragraph lists only the settings that
  differ from the paper, with the solver backend.
- The two protocol stages are named `steady_conductivity` and `transient_storage` across the
  docs, the recipes and examples 10 and 21.
- `d_sat_unset_fraction` splits into `d_sat_dry_fraction` and `d_sat_inactive_fraction` when
  the mesh says which cells are inactive.
- `hydromodpy/data` is reorganised into sub-packages with one job each; its
  map and import rules are `hydromodpy/data/README.md`, enforced by
  `tests/unit/architecture/test_package_layouts.py`. What a TOML says does not
  change; `hydromodpy.data` gains `DataStore`, `DataRequest` and
  `run_request` and loses `DataManagers`. The modules that moved:

  | old path | new path |
  |---|---|
  | `hydromodpy.data.scaffold` | `hydromodpy.data.workspace.scaffold` |
  | `hydromodpy.data.scaffold_examples` | `hydromodpy.data.workspace.example_files` |
  | `hydromodpy.data.auto_scan` | `hydromodpy.data.workspace.custom_scan` |
  | `hydromodpy.data.data_freeze` | `hydromodpy.data.registry.freeze` (writing) and `hydromodpy.data.provenance.lockfile` (reading, frozen mode) |
  | `hydromodpy.data.sidecars`, `hydromodpy.data.derived` | `hydromodpy.data.provenance.sidecars`, `hydromodpy.data.provenance.derived` |
  | `hydromodpy.data.managers.config_schema`, `.planner`, `.plan` | `hydromodpy.data.loading.config_schema`, `.planner`, `.plan` |
  | `hydromodpy.data.managers._base_manager_common` | `hydromodpy.data.managers.base_manager_common` |
  | `hydromodpy.data.variables.timeseries_variable_config` | `hydromodpy.data.managers.timeseries_config` |
  | `hydromodpy.data.common.validation` | `hydromodpy.data.contracts.completeness` |
  | `hydromodpy.data.common.custom_grid_loader`, `custom_point_loader` | `hydromodpy.data.ingest.custom_grids`, `custom_points` |
  | `hydromodpy.data.adapters.asc_to_geotiff`, `csv_to_parquet`, `shp_to_geoparquet` | `hydromodpy.data.ingest.raster`, `tables`, `vector` |
  | `hydromodpy.data.common.administrative.france` | `hydromodpy.spatial.administrative.france` |
  | `hydromodpy.data.variables.<v>.cases` | `hydromodpy.data.cases.<v>` |
  | `hydromodpy.data.variables.geology.cases.common` | `hydromodpy.data.cases.geology.plotting` |
  | `hydromodpy.data.source.bdtopage`, `euhydro`, `osm` | `hydromodpy.data.variables.hydrography.apis.bdtopage`, `euhydro`, `osm` |
  | `hydromodpy.data.variables.sim2`, `sim2_manager`, `common.clients.sim2_variables`, `variables.<v>.apis.sim2` | `hydromodpy.data.common.clients.sim2_products` |
  | `hydromodpy.data.common.clients.hubeau_cache` | the station cache of `BaseVariableManager` |
  | `hydromodpy.data.variables.<v>.custom`, where it only called the shared loader | `load_custom` of the manager base class |
  | `hydromodpy.data.fetch` | `hydromodpy.data.request` |

- `hmp data export --format rocrate|stac|prov` writes the views inside the run
  directory, beside the seal, instead of under `share/`. An explicit
  `--output` still takes them there.
- A sidecar carries the licence of its source, and the licence of a run's Zarr
  and Parquet outputs is the roll-up of its inputs instead of a placeholder. A
  user file counts only through the tracked file that holds its bytes. No
  export writes `CC-BY-4.0` by default any more, and the workspace template no
  longer pre-fills a licence its author did not choose.
- "Run is sealed without creator_name, creator_institution, a determined
  license" is said once per workspace and process at the normal verbosity,
  naming the `workspace.toml` keys to fill; repeats go to `--verbose`.
- `[simulation.time] step_value` without a unit and without `step_unit` is
  refused instead of read as one day, since the documented default is
  `"1 month"`.
- A job records its extent as one typed box in its native CRS, and the
  RO-Crate, STAC and PROV views reproject that box to WGS84. The views no
  longer read a `bbox_wgs84` or a `crs_wkt2` field. A job input set written
  before, which holds a `crs` and no box, is refused by the export.
- Copies derived from a custom geology, DEM, lake abacus, bathymetry or lake
  outline live under `data/blobs/<variable>/custom/`, named after their inputs,
  instead of beside the user file in its `<variable>_custom_*` namespace. A
  scan no longer ingests them as user data, and two domains no longer share one
  clip. Copies made before are not moved.
- `hydromodpy/calibration` closes the import cycle between its optimizer
  registry, its runners and its metrics: six modules and a handful of symbols
  move next to what they serve. Its map and import rules are
  `hydromodpy/calibration/README.md`, enforced by
  `tests/unit/architecture/test_package_layouts.py`. The `[calibration]`
  TOML schema does not change, and logger names follow the new paths. The
  modules and names that moved:

  | old path | new path |
  |---|---|
  | `hydromodpy.calibration.adapters.*` | `hydromodpy.calibration.optim.adapters.*` |
  | `hydromodpy.calibration.adapters._prior_sampling` | `hydromodpy.calibration.optim.prior_sampling` |
  | `hydromodpy.calibration.optim.promotion` | `hydromodpy.calibration.runners.promotion` |
  | `hydromodpy.calibration.metrics.network` | `hydromodpy.calibration.observations.network_cost` |
  | `hydromodpy.calibration.evaluation.pipeline_evaluator` | `hydromodpy.calibration.runners.pipeline_evaluator` |
  | `hydromodpy.calibration.evaluation.scored_forward` | `hydromodpy.calibration.metrics.scored_forward` |
  | `optim.objective.{METRICS, HIGHER_IS_BETTER, LOG_METRICS, clip_negatives_for_log_metric}` | `hydromodpy.calibration.criteria.series` |
  | `optim.objective.{distance_gap, distance_mean}` | `hydromodpy.calibration.criteria.hydrographic_network_distance` |
  | `protocols.matching_hydrographic_network.MatchingHydrographicNetworkOptions` | `hydromodpy.calibration.config` |
  | `runners.state.{default_store_factory, CalibrationStoreFactory}` | `hydromodpy.calibration.persistence` |
  | `hydromodpy.solver.modflow_common.flow_adapter_helpers.WATER_BUDGET_METRIC` | `hydromodpy.simulation.planning.plan` |
- The particle pathline reader moves from
  `hydromodpy.display.figures.particle_tracks` to
  `hydromodpy.results.run.particles` (`read_particle_tracks`,
  `particle_time_to_days`). The map overlay no longer imports a figure, which
  closes the import cycle between `display.figures` and `display.overlays`.
- `hydromodpy.display.catchment_report.block_specs.FigureSpec`, the place of a
  PNG in a catchment report block, is renamed `BlockFigureSpec`, so that
  `FigureSpec` names only the contract of a registered figure.
- The modules of `hydromodpy/display` are grouped by role, so that the tree
  says who does what (`hydromodpy/display/README.md`). What a TOML says and
  `hmp.viz` do not change. The modules that moved:

  | old path | new path |
  |---|---|
  | `hydromodpy.display.banner` | `hydromodpy.cli.banner` |
  | `hydromodpy.display.renderer.matplotlib_backend` | `hydromodpy.display.runs.matplotlib_backend` |
  | `hydromodpy.display.map_axes` | `hydromodpy.display.maps.axes` |
  | `hydromodpy.display.mesh_geometry` | `hydromodpy.display.maps.mesh_geometry` |
  | `hydromodpy.display.ugrid` | `hydromodpy.display.maps.ugrid` |
  | `hydromodpy.display.overlays` | `hydromodpy.display.maps.overlays` |
  | `hydromodpy.display.transect` | `hydromodpy.display.maps.transect` |
  | `hydromodpy.display.geo` | `hydromodpy.display.maps.geo` |
  | `hydromodpy.display.theme` | `hydromodpy.display.style` |
  | `hydromodpy.display.colormaps` | `hydromodpy.display.style` |
  | `hydromodpy.display.legend_placement` | `hydromodpy.display.style` |
  | `hydromodpy.display.viz` | `hydromodpy.display.quicklook.viz` |
  | `hydromodpy.display.scalable` | `hydromodpy.display.quicklook.scalable` |
  | `hydromodpy.display.animation` | `hydromodpy.display.quicklook.animation` |
- A figure names what it shows, not a solver or a provider: `mesh_map` is
  titled "Model mesh" (was "Solver mesh") and `hydrographic_network_reference`
  "Reference hydrographic network" (was "BD Topage hydrographic network", while
  the reference may come from `bdtopage`, `euhydro` or `osm`); the network
  figures draw "Reference network" where they wrote "BD Topage".
  `watershed_id_card` is of `kind` `spatial` (was `comparison`).
  `[display].overrides`, the documented way to set a figure option such as the
  orientation of a section, is a `USER` field (was `EXPERT`), so
  `hmp config template --profile user` shows it.
- `method` in `[calibration]` and in a `[[calibration.phases]]` entry no
  longer defaults to `grid`. Unwritten, it follows from what the search
  scores: `bisection` when it moves one parameter in log space and every one
  of its objective blocks is signed (`distance_gap`), `scipy_nelder_mead`
  otherwise. `hmp calibrate --list-phases` prints the method each phase runs,
  and why when it was chosen. `optimizer_kwargs` without `method` are refused,
  since they belong to an engine the file has to name. No TOML file of the
  repository relied on the old default.
- `[calibration.uncertainty] tolerance` and `mode` left unwritten follow what
  the search scores: one mesh cell, absolute, for a phase (or a calibration
  with no phases) scored only by network distances, five per cent of the best
  cost otherwise. Example 04's `project.toml` drops `[calibration.uncertainty]`:
  K keeps its interval, one 75 m cell, and Sy gets a bounded one instead of
  five per cent of a cost that never reaches the same scale on every project.
- The interval width no longer enters the params hash. A cache, or a
  `reuse_completed_phases` chain, built before this change misses once and
  rebuilds under the new hash.
- A calibration sealed before `regime` existed carries a phase's flow regime
  as `overrides`-only, in the five dotted paths a protocol used to compute by
  hand. Such a session now reloads through `config.fold_a_legacy_regime`,
  which rewrites that spelling into `regime`; before this, rereading one to
  resume it refused the session it had itself written.

### Fixed
- The BD Topage download no longer stops at the first page shorter than requested: the Sandre
  pages over index candidates, so such a page is not the last one, and a box holding more than one
  page lost the rest. Pages are counted against the announced total, and a shortfall or a repeated
  feature raises.
- The hydrography cache no longer serves an answer fetched for another question over the same box
  (another BD Topage vintage, other OSM waterway types): an entry records what it was fetched for.
- A stream comparison redrawn from a run sets its seepage threshold with the mean recharge over
  the run, as the criterion does, instead of the recharge of the last timestep.
- The delineation summary shows `buff_area` as declared, with its distance and area increase,
  instead of a value labelled m2. The reference catchment-delineation case accepts `"20%"` and
  distance strings.
- The bisection returns a trial inside its final bracket; a trial tied on cost outside it is no
  longer returned.
- The guards and preflight see a phase that scores a network output through its own
  `variable`.
- The drain-conductance fallback reads `C = K * cell_area / drain_bed_thickness_m` in messages,
  comments and docs; the theory pages agree that the criterion is implemented.
- `ref_example04.toml` and `run_calibration_k.toml` declare their departures from the v1 script,
  and the cache-key comment of `auto_drn_full.toml` says the key holds the package version.
- A calibration trial that moves the depth model solves the geometry it moved: the substratum
  of the domain the trials share is rebuilt instead of reused from the prefix.
- A run writes the constant aquifer thickness into its parameters table. It read
  `domain.depth_model` instead of `domain.config.depth_model`.
- `k_over_r` reaches the calibration report. It read `R_mean_m_s` without the
  output prefix every network diagnostic carries, so it never appeared, and it
  divided whatever single parameter the search moved, a thickness or a
  multiplier included. The conductivity is now converted from its field unit.
- `Project.simulate(thickness=...)` on a depth model without a thickness raises
  a `ConfigError` naming the kind instead of a raw Pydantic error.
- A custom lake-bathymetry raster without a CRS loads in its `default_crs`, as
  its warning said, instead of failing in the conversion to GeoTIFF. The
  `data/lake_bathymetry/` drop zone describes GeoTIFF and ASC files of its own
  name instead of copying the DEM one.
- A comparison report names the depth model a synthetic case declares instead
  of always printing a constant thickness.
- A station manager no longer reports a station inside its extent as outside
  it: the check reprojects each station to WGS84, the frame the extent
  reaches it in, instead of comparing Lambert-93 metres with degrees. A data
  request served by box now hands station managers their box in WGS84 and
  grid managers theirs in Lambert-93.
- A data mask is read by one loader, `hydromodpy/data/common/source_extent.py`.
  A grid manager (SIM2, SHOM) now refuses a mask that declares no CRS, as the
  DEM and geology managers already did, instead of reading its bounds in an
  unknown frame. The station managers keep the WGS84 polygon they filtered
  with, features reprojected before their union, and still read a mask
  without a CRS as WGS84. `load_mask_geometry` and `load_mask_geometry_wgs84`
  leave `hydromodpy.data.common.geo_helpers`.
- A DuckDB database in memory, such as the index `DataStore()` opens without a
  data root, is migrated without a file lock: it no longer leaves
  `memory.duckdb.lock` in the working directory.
- Cache invalidation, the subsumption that follows a larger fetch, and
  `hmp data prune` and `remove` with file deletion deleted nothing: the path
  was resolved against the working directory and a missing file passed in
  silence. They now delete the downloads and the `data/blobs/` copies they
  name, with their sidecar, and never a user file or a file another entry
  still names.
- A sidecar is deleted with its data file, before it. A scan read a sidecar
  left without its file, such as `geology_custom_GEO1M.gpkg.json`, as a
  GeoJSON and warned on every run. It now reports it once as an orphan, and
  `hmp data check` lists it.
- The data cache answered from where `hmp` was started. A download registered
  by its bare name was stored against the working directory, so a run started
  in `projects/<name>/` recorded `projects/<name>/<file>`, and a sentinel lost
  its meaning the same way. The station, grid and river-network managers then
  read a stored path under `data/<variable>/`, never found a workspace-relative
  one, forgot the entry and fetched again on every run. The catalog now stores
  the file it resolves and a sentinel as written, and every reader, the
  lockfile and `hmp data check --fix` included, resolves a stored path by one
  rule that also decodes `cache://` and `state://`. `check --fix` no longer
  drops a valid entry because it was started outside the workspace.
- Geology is requested over the buffered domain box, not the catchment
  outline. A domain larger than the geology left a frame of cells at K = 0, and
  MODFLOW 6 refused the whole NPF. A zero or non-finite conductivity on an
  active cell is now refused before MODFLOW 6 and MODFLOW-NWT, naming the
  support that did not cover it.
- A synthetic recharge sample on a month, quarter or year end alias (`ME`,
  `QE`, `YE`) is stamped at the start of its period, so a steady run on a
  monthly grid finds the value of its first period.
- A catchment report reads the newest completed run of its name, not the name
  of a run that failed before it. The Vire MODFLOW-NWT run closes at the
  default 1e-4 m head tolerance: at 1e-6 m two drain cells cycled forever.
- The MODFLOW 6 PRT example names the `transport/modflow6_prt` pair, renamed on
  2026-05-20, and the bundled `mf6`. A test holds every example config to the
  registered solver pairs.
- Example configs that named data files nobody ships fetch them instead: the
  Canut intermittency from ONDE, the Bretagne candidates DEM from BD ALTI, the
  workshop ETP from SIM2. The site 18 base mesh declares its DEM and its
  river-network threshold.
- A stress-period stamp is the END of its period. Observations and forcings
  were averaged over a window centred on it, so a monthly run compared January
  with mid-December to mid-January: 0.167 m3/s off on average through the daily
  product, a full month late through `QmM`, on a Nancon mean of 0.97 m3/s. A
  flux (the `time: mean` fields and the discharge) is now compared with the
  mean of `[previous stamp, stamp)`; a state (`time: point`: head, water table,
  concentration, lake stage) with its value at the stamp, as before; and a
  steady stage with its own window taken from the run time grid. Per-run fit
  metrics, calibration scores, figures and the catalog fallback time index
  follow the same rule. On the stored example 04 run the discharge NSE moves
  from 0.531 to 0.665 and the stage-two `nse_log` from 0.595 to 0.731.
- The hourly pandas frequency uses `h`, not the deprecated `H`.
- The `station_ids` description says it selects Hub'Eau stations as well as
  custom ones.
- The example manifest follows example 04 again: its short README, no
  `run_manual.py`, and the current step 4. It still listed the removed files,
  which made `hmp example add 04` fail.
- The DA-MH-GP adapter returns the evaluated trial nearest its posterior mode
  instead of the first accepted one: `tell` now keeps the transformed point of
  each evaluated trial, and the acceptance distance reads it instead of
  `metadata["values"]`, which the engine never wrote.
- `hmp` no longer imports the catchment report, nor `matplotlib.pyplot` with
  it, each time it builds its parser; only `hmp report catchment` does.
- `hmp viz show` refuses a figure the run cannot feed, with the figure's reason
  and exit code 1, instead of drawing it or failing inside the drawing, and
  names the file it wrote: `--output X` writes `X.png` and now says so.
  `hmp.figure`, `hmp viz show` and the capability gallery of the export step
  render one figure through `hydromodpy.display.runs.render_figure`, which
  takes `dpi` and the figure options and returns the figure.
- A figure the run cannot feed is refused with a sentence, never by an error
  from inside its drawing nor by a placeholder PNG. `piper_diagram`,
  `schoeller_diagram` and `stiff_diagram` need hydrochemistry samples,
  `lake_abacus_comparison` a lake abacus, `watershed_id_card` a DEM raster,
  `particle_tracks` and `residence_time_distribution` pathline coordinates
  (an empty `particles` group or release points alone no longer count),
  `sfr_*` stream-reach series,
  `lake_stage_sim_obs` and `lake_volume_sim_obs` a simulated and a gauged lake
  level, `piezo_timeseries_sim_obs` a simulated head series, and `ensemble_band`
  a set of runs. `[display].figures` skips them with that reason.
  `piezo_timeseries_sim_obs` without `station=` names the stations it could
  draw, and `difference_map` and `side_by_side` without `reference=` say so.
- The catchment report reads the cell count from the simulated run, for every
  solver. It read `[modflownwt.sgrid.planar]` and left the count empty for any
  other run. The generated-network context figure it cannot draw is now
  logged with its name and the reason (the missing input at INFO, a failed
  read at WARNING), instead of missing from the report without a word.
- A phase that lists a parameter an earlier phase already calibrated moved it
  again from the parameter's search bounds, silently overwrote the frozen
  value at every trial of the phase, and the report still called the
  parameter frozen. It now starts the search from the passed value, on the
  engines that declare `accepts_a_start_point` (`cma_es`, `scipy_nelder_mead`;
  not `scipy_de`); an engine without one keeps its own start, and
  `--list-phases` says so. Two phases that freeze the same path no longer
  refuse each other: the later one wins, and the report and `--list-phases`
  name both, the later as re-opened.

### Removed
- `[modflownwt.tgrid]` is gone from the schema, following `[modflow6.tgrid]`.
  No backend ever read it back: `apply_explicit_time_window_to_tgrids()`
  overwrote it from `[simulation.time]` and nothing consumed the result, so a
  file could declare `itmuni = "days"` next to a run executing in seconds.
  `hmp doctor --fix-config` drops the section, at the root and under a
  comparison or testbed overlay, which the MODFLOW 6 migration did not reach.
- `hydromodpy/discretization/` was deleted. `[modflownwt.tgrid]` was its last
  importer, through `TMeshConfig`; `TmeshGenerator` and `TimeGrid` had already
  been unreachable since `build_temporal_discretization()` lost its caller.
  Chronicle-driven stress periods (`genmtd = "from_chron"`) and per-period
  `ntsp`/`tsmult` go with it: `[simulation.time]` expresses a regular
  calendar-aware step, and restoring variable periods means extending
  `ResolvedSimulationTimeGrid`, not reviving a parallel temporal model.

### Changed
- `objective=` refuses a value that is not a `module.path:callable` entry
  point, at the entry of every calibration route, instead of ignoring it. It
  has always been an entry point specification on all three routes, so
  `project.calibrate(objective="kge")` on a document declaring `nse` calibrated
  on `nse` and said nothing. The refusal names the value it was handed and the
  three places a metric is actually declared, including
  `objective_blocks=[...]` for `Project.calibrate`, which passes no
  `[calibration]` table. Checked at the entry, not where the value is used: a
  staged run reusing every phase from disk never reached the use site, and a
  refused call used to pay the whole geographic, mesh and data prefix first and
  leave a catalog, a lock and a WAL in a workspace where no calibration ran.
  One caller in the repository passes a metric name this way and now fails,
  `examples/projects/new_to_sort/11_nancon_watershed/python/06_python_calibration.py`,
  which asks for `objective="kge"` beside `variable="discharge"` and was
  calibrating on the default all along. Python mode filters `objective` out of
  the config payload, so the metric goes in `objective_blocks=[...]` there.
  `run_trial_light` keeps its own `objective` argument and is not touched.
- A staged calibration declaring `uncertainty.method = "linearized"` now gets a
  width per phase, taken around that phase's own optimum. It got none at all:
  the dispatch that builds one lives in the non-staged route, so the search was
  paid for in solver hours and nothing came back. Of the three declared
  methods two were already honoured per phase - `cost_profile` inside the core
  the staged route calls, `multistart` reimplemented by the staged runner - and
  `linearized` was orphaned by anatomy, not by meaning.
- A width taken after an earlier phase froze parameters is conditional on that
  freeze, and the Methods paragraph says so instead of reporting it as an
  absolute. It also tells a width that was built and is conditional from one
  that was never built: "Reported parameter uncertainty is conditional on the
  following" covers the first, "No parameter uncertainty was built for" the
  second. A run whose phases were all reused from disk used to claim a reported
  uncertainty where there was none.
- A phase none of whose outputs can name a station keeps its report instead of
  losing it. `CalibOutputNetwork` carries no `observes` field, so the steady
  stage of `matching_hydrographic_network` - the only registered protocol -
  holds an output, holds no station and can never hold one; asking for a width
  there ended the whole staged run after the steady search had been paid for.
  An output that could have named a station and did not is still a document
  mistake and still fails loudly.
- `hmp calibrate --check` counts two refusals on a document declaring phases
  that it did not count before, and exits non-zero where it exited 0. The
  burn-in guard for `method = "linearized"` skipped every phased document,
  since no width was built for one, and now applies phase by phase. And the
  refusal for an output naming no station is raised once per search rather than
  once per file, so a five-phase document says which phase cannot carry a
  width. On a single-metric phase the message names the real mechanism, a phase
  scored on `variable`/`objective` inherits none of the calibration's outputs,
  instead of pointing at an `observes` the schema refuses on that phase.
- `flow_persistence_map` takes a `cycle`, the option `flow_intermittence_map`
  already had, and both maps now name the window they cover in their title
  (`2000-01 to 2002-12`) instead of a step count. The two answer the same
  question over different windows, which reads as a contradiction when only
  one of them says which: on example 04, 787 cells carry flow during the wet
  years and none in the classified one, pale blue on one map and grey on the
  other.
- Example 04 renders eight figures instead of twenty. What went were the
  duplicates, not the diagnostics: four comparison panels folding the same 36
  residuals, a duration curve over 36 monthly points, a boxplot of three
  values per month, a budget bar summing timestep rates, and three network
  maps the confusion map already covers. Every figure drawing one instant now
  draws the same one, October 2002, the driest month, rather than the default
  last timestep, a December whose network is nearly full.
- A NetCDF export writes a layered field as one variable per layer, named
  `<var>` on a single-layer model and `<var>_layer<N>` above it, and no longer
  carries a `layer` dimension. QGIS cannot read a third dimension and most
  catchment models run on one layer. `import_netcdf_fields` stacks the layers
  back, so a round trip through the file is unchanged for everything but a
  single-layer field, which comes back without its layer axis.
- `hmp data export --list` names the fields a run exposes. It listed the
  geographic rasters, the vector features and the runs, but never the field
  names `--var` expects, so the only list that answers "what can I export" was
  the one it did not print. It also says which run it read, and reads the one
  `--sim` names when given, else the last live one: a trashed run was silently
  becoming the source.
- `simulation.time.substeps_per_period` documents what its default costs. One
  backward-Euler step per stress period moves the monthly discharge by 4 to
  28 % against a refined run on a seasonally recharged hillslope drained by DRN
  cells, across the whole plausible bedrock range, and a calibration scored on
  discharge absorbs that into the fitted parameters. The default stays at 1:
  the right count is a property of the model (`tau = L^2 S / (K b)` against the
  period length) and the solver cost is linear in it, so raising it silently
  would rewrite every existing result and multiply every calibration budget.
  A validation case now states the size of the drift.
- A calibration declaring `variable` and `objective` is now refused before its
  session exists rather than at every trial. Two loaded gauges without
  `calibration.observed_station_id` used to build an extractor, write a session
  row, spend the whole search budget and fail each trial with the same message;
  the refusal now names the two candidates while `hmp calibrate` is still
  reading the document.
- A trial that asks a built metric extractor for another `variable` or another
  `objective` is refused instead of silently scored. The producer, the observed
  records and the gauge the search follows are all chosen when the extractor is
  built, so a criterion renamed at call time reported a cost under a key the
  session never recorded.
- A solver serving an empty per-station discharge series now fails the trial
  with the same message the head and lake routes already used, naming the
  station, rather than the `no overlapping samples` message of the alignment
  step. The head and lake messages gain that station name with it, and the
  lake one now says `lake_level` where it said `lake stage`.
- A linearized parameter width is refused when the calibration it is taken
  around drops leading samples. `[calibration].warmup_periods`, and a block's
  own `warmup`, truncate each output before the cost is computed; the residual
  at each observation is not truncated and two blocks may drop different
  counts, so the covariance described a window the search was told to ignore.
  `hmp calibrate --check` names it before anything solves. A search that ran
  anyway keeps its report and loses only the width, the way every other
  no-width path already behaved.

### Fixed
- An objective block scoring several outputs checks each output's length
  against its own record, instead of checking the two concatenated totals. Two
  outputs individually wrong - twenty simulated values against thirty observed,
  then forty against thirty - sum to sixty on both sides and passed, while the
  metric scored the second output's first ten values against the first one's
  last ten. Measured: no block in `examples/projects/`, `tests/validation/` or
  `tests/e2e/` scores more than one output, so no existing result moves. The
  refusal names the output and both lengths, counted after the burn-in, which
  is what the metric receives.
- `flow_intermittence_map` and `flow_persistence_map` cut the record into
  calendar years by reading the year off each timestep's stamp, which is the
  END of its stress period. A monthly run of 2000 to 2002 therefore reported
  four cycles: a 2000 of eleven steps, a 2002 running December to November and
  a 2003 one step long, so the map labelled "2002" classified a year that was
  a month out of phase. The year is now read at the middle of the step, which
  falls inside it whichever bound the solver stamps.
- `hydrograph_log_nse` wrote its note across its own legend: pinned to the
  upper left, its longest line reaches the upper right whatever the axes width.
  The note sits on the log floor, a band the limits leave empty by
  construction.
- A NetCDF export was unusable in QGIS. Three causes, all in
  `results/exporters/netcdf.py`. The file georeferenced itself the CF way, a
  `crs` variable holding `crs_wkt`; MDAL, which is what QGIS opens a UGRID mesh
  with, looks up one variable by name and parses WKT1 only, so it kept no CRS
  and QGIS drew the mesh in the project CRS, nowhere near the catchment. A
  field stored per layer was written as one `(time, layer, face)` array, which
  MDAL ignores outright: `drain` simply did not appear among the dataset
  groups. And the face centroids, undeclared on the mesh variable, read as two
  datasets to plot. Checked against QGIS 3.x: the mesh now loads in EPSG:2154
  with one group per field and 36 steps each.
- Re-exporting a NetCDF onto a file QGIS still had open truncated it to zero
  bytes: netCDF4 truncates before it writes and HDF5 then failed on the lock.
  The write goes to a neighbouring file and is renamed into place, so a failed
  export destroys nothing and an open layer keeps reading what it has.
- `hmp data export` refused every per-cell budget field. Its own field filter
  rebuilt the "what is readable here" rule and looked at the store root and
  `derived/` only, so `drain` and `recharge`, which live under `budget/`, were
  reported as not exportable while `hmp.export()` wrote them without trouble.
  The filter now reads `run.array.list_fields()`, the single source of truth
  the readers already share.
- CI no longer runs the Whitebox-backed tests inside an xdist worker. The native
  binding dies outright when several DEM workflows share one long-lived worker,
  and the `xdist_group` that stops two workers touching the backend at once is
  exactly what puts them on the same node; `Tests / fast marker py3.12` lost
  `gw1` on `main` this way. Every parallel step in `main-ci`, `ci-weekly` and
  `ci-nightly` now excludes them and a serial step runs them, and a contract
  test parses the workflows so the split cannot drift back.
- `test_run_geographic_case_river_network_regression.py` was still listed in the
  Whitebox xdist group after being deleted in 298c08b9d, so the entry guarded
  nothing.

### Fixed
- MODFLOW 6 adaptive time stepping targeted the wrong stress period. FloPy
  converts an ATS `iper` to 1-based when it writes the file and the builder was
  already 1-based, so every record landed one period late and the last one fell
  off the end of the simulation. The first transient period never got ATS at
  all.
- Adaptive time stepping no longer discards the requested sub-stepping. MF6
  ignores the TDIS NSTP of a period ATS covers, and the record declared
  `dt0 = dtmax = perlen`, so a run asking for ten steps per period got one:
  0.0481 m of RMSE against the erfc closed form instead of 0.0035 m. Both bounds
  are now the step `simulation.time.substeps_per_period` asked for, so ATS can
  only cut below it, which is the failure recovery it exists for.
- `hmp doctor --fix-config` reads a config carrying a byte-order mark. tomlkit
  parsed the BOM as an empty key on line 1, so the whole fix aborted and nine
  validation configs in this repository could not be migrated at all.
- Two example report builders read `firstpersteady` from a solver `tgrid`
  section that never held it, and the Nancon sweep script wrote it into the
  configs it generates, producing files the runtime refuses. All three now use
  `[flow].first_period_steady`.
- MODPATH pathline and endpoint times are now converted to the unit the
  `particles` group declares. The MODFLOW-NWT extractor stored raw model time,
  seconds, while labelling it `days`, so every stored travel time and every
  residence-time figure built from it was off by a factor 86400.
- `ITMUNI` is now read from the first non-comment record of a MODFLOW DIS file,
  where it actually sits. The previous reader parsed the LAYCBD line below it
  and always fell through to its default, so a MODFLOW-NWT run declaring
  anything but seconds had its calibration fluxes left unscaled.
- The MODFLOW 6 PRT readers no longer fall back to `DAYS` when a run declares
  no time unit. An undeclared unit now means `SIMULATION_TIME_UNIT`, the unit
  the launcher builds every run in.

### Removed
- `DomainGeographicContext.river_mesh_trace` and the direct
  `CatchmentDelineation.river_mesh_trace` runtime attribute were removed.
  Mesh river constraints now read `GeographicDerivedFeatures.rivers.river_mesh_trace`
  or an explicit `river_trace`; the in-memory mesh config source is now
  `rivers.source = "geographic_features"` instead of `"domain_geographic"`.
- Generic testbed input spellings `[[testbed.variant]]`,
  `[[testbed.variant_from_catalog]]`, `TestbedConfig(variants=...)`, and
  `TestbedConfig(catalog_variants=...)` are no longer supported. Use
  `[[testbed.case]]`, `[[testbed.case_from_catalog]]`,
  `TestbedConfig(case=...)`, and `TestbedConfig(case_from_catalog=...)`.
- Generic testbed outputs no longer write the legacy compatibility keys
  `variant_id`, `variant_label`, `variant_count`, or `variant_from_catalog`.
  Read `case_id`, `case_label`, `case_count`, and `case_from_catalog`
  instead.
- Removed the application-level config compatibility aliases under
  `hydromodpy.core`. Use `hydromodpy.config.HydroModPyConfig` and
  `hydromodpy.config.schema_export` instead.

### Fixed
- The PyHELP NetCDF export is now readable by the data layer it feeds. Its
  recharge variable was named `rechg`, which no data family looks up; it is now
  `recharge`. It also declared no CF grid mapping on its fields and no nodata
  attribute that survives decoding, so the file was refused on load.
- A custom gridded source handed the whole NetCDF downstream instead of the
  variable it names, and the discretization then picked a variable out of it by
  taking the first one. On any CF file that is the scalar grid-mapping
  variable; on a multi-field export it could be any field. A source now carries
  only the variable it declares, and the picker skips grid mappings and
  dimensionless variables.

### Changed
- Simulation identity keys renamed. `[simulation].run_id` and
  `[simulation].on_collision` are removed and now hard-fail under
  `extra="forbid"`. Use `[simulation].name` for the run identity and
  `[simulation].if_exists` for name-collision behaviour. `if_exists`
  defaults to `version` (mint the next `stem.vN`), replacing the old
  `replace` default; `replace` and `fail` remain available. `hmp doctor
  --fix-config FILE.toml` migrates old keys in place.
- Unstructured MODFLOW 6 grids now build a Voronoi/PEBI dual by default
  (exact CVFD orthogonality, about half the cells, XT3D off). The new
  `grid_dual` field controls this; set `grid_dual = "triangle"` to restore
  the previous triangle DISV grid. Upgrading an existing unstructured
  MODFLOW 6 project changes its heads and budgets, and any calibration
  `params_hash` cache must be invalidated after the upgrade to avoid
  reusing stale objectives. MODFLOW-NWT (structured DIS) and Boussinesq
  are unaffected.
- Raster / VTU / shapefile auto-export now defaults to the last timestep
  instead of the first. Set `[export].times = "first"` to keep the previous
  behaviour.
- Documented the release policy for SemVer/PEP 440 versions, alpha/beta/rc
  pre-releases, the new `main` default line, the frozen `archive-v1` branch,
  release branches, tags, and GitHub Releases.
- Prepared the v2 line as `2.0.0a1` and updated project metadata, docs links,
  source links, and GitHub workflow branch filters from `master` to `main`.
- Per-simulation `timeseries`, `budgets`, and `mass_balance` rows now live as
  Parquet files under `simulations/<uuid>.parquet/` instead of DuckDB tables
  inside `hydromodpy.duckdb`. DuckDB views with the original table names
  keep the read surface unchanged - every `SELECT ... FROM timeseries`
  call keeps working. See
  `docs/developers/parquet_lakehouse_architecture.md` for the layout and
  `docs/developers/parquet_lakehouse_concurrency.md` for the retry and
  atomic-rename patterns.
- `SimulationCatalog` now retries on `duckdb.IOException` at both connect
  time (`connect_with_retry`) and execute time (`@with_lock_retry`) on
  every write path. Short-lived cross-process lock contention resolves
  transparently instead of surfacing as an error.
- `hmp run <calibration.toml>` now drives real MODFLOW simulations through
  the new trial primitive (no more analytical mock). Each trial runs in
  `ExecutionRegistry.lightweight=True` mode, skipping Zarr/Parquet writes.
  Only the top-N iterations (via `save_runs = "best_n"`) get promoted to
  full simulations. See `docs/developers/calibration_guide.md`.
- `make_hot_simulator` now returns `(calibration_vector, raw_results)` so
  callers can persist selected series post-calibration without re-running
  the solver. `persist_calibration_result` renamed to `promote_trial`.

### Added
- Four figures join the registry, each one a view the legacy example suite drew
  by hand and nothing in v2 could reproduce: `recession_power_law` (the
  Brutsaert-Nieber log-log plane of `-dQ/dt` against `Q`, with the late-time
  Boussinesq 1904 law overlaid), `residence_time_distribution` (the travel-time
  density of tracked particles against the exponential law of a well-mixed
  store), `mass_balance_error` (the solver's own closure error per timestep),
  and `concentration_boxplot` (the distribution of a solute over the domain,
  timestep by timestep).
- MODFLOW 6 Lake (LAK) package support: model one or several lakes/reservoirs
  as advanced boundary conditions with stage, bathymetry abacus, and bed
  leakance, driven from the `[flow]` boundary configuration. LAK is a
  MODFLOW 6 backend capability.
- Streamflow Routing (SFR) support on the MODFLOW 6 backend, including
  SFR-to-lake water movers (MVR) so routed streamflow can feed a LAK lake.
- Horizontal flow barrier support, including a dam cutoff wall (HFB), to
  reduce flow across a mapped line such as a grouting curtain under a dam.
- Lake bathymetry bed carving: a bathymetry raster can lower the MODFLOW 6
  cell bottoms under a lake so the aquifer grid follows the reservoir bed.
- Lake-level calibration: calibrate against an observed MODFLOW 6 LAK stage
  series (`variable = "lake_level"`) in addition to discharge and head.
- Top-level `[export]` configuration section promoting the raster / VTU /
  shapefile / time-series export toggles to a first-class config block.
- New geographic `domain_extent` option (`box`, `watershed_buff`,
  `watershed`) to select the modelled domain surface, and a mesh
  `lake_refinement` block to refine cells around lakes and dams.
- Calibration refactor - trial primitive plus step auto-invalidation:
  - `hydromodpy.simulation.execution.trial` with `TrialContext`,
    `prepare_trials`, `run_trial_light`, `promote_trial`.
  - `hydromodpy.pipeline.dependencies.earliest_affected_step` computes
    which pipeline step must re-run first from a set of override paths,
    using longest-prefix match on the new `config_sections` class var
    declared by each of the 12 pipeline steps.
  - `hydromodpy.calibration.metrics.build_metric_extractor` - RAM-only
    metric extractor for MODFLOW-NWT discharge (DRAIN budget aggregated)
    and head at observation cells.
  - `ExecutionRegistry.lightweight` flag gates Zarr / Parquet / catalog
    writes in steps 06 and 07.
  - `ParamsHashCache` preload from DuckDB at session start for
    cross-session trial deduplication.
- `hmp report <session_id>` - generates a self-contained HTML report
  under `<workspace>/reports/<session_id>/report.html` embedding the
  calibration session metadata plus the six calibration figures.
- Six calibration figures registered in the Display registry:
  `calibration_convergence`, `calibration_trace`, `calibration_landscape`,
  `calibration_posterior`, `calibration_objective_surface`,
  `calibration_pairplot`.
- Analytical calibration cases ported under `hydromodpy.calibration.cases`:
  `recession_brutsaert` (Brutsaert 1D recession) and `groundwater_1d`
  (Dupuit 1D aquifer). Both ship with synthetic chronicle builders + a
  `calibrate_<name>(method, ...)` dispatcher that hooks into
  `CalibrationEngine`.
- `hydromodpy.calibration.diagnostics` helpers (`convergence_rate`,
  `parameter_correlation`, `iterations_to_dataframe`).
- User guide: `docs/developers/calibration_guide.md` (replaces the two
  refactor prompts under the same directory).
- `hmp doctor` now reports the Parquet layout health (orphan directories,
  leftover legacy tables, per-sim Parquet counts).
- Unit tests covering atomic Parquet writes, view semantics, and 8-worker
  concurrent writes (`tests/unit/results/test_parquet_lakehouse.py`).
- ~130 new calibration tests across `tests/unit/calibration/`,
  `tests/unit/test_calibration_cli.py`, and
  `tests/regression/fast/calibration/` (including the Brutsaert golden
  regression for four optimization methods).

### Removed
- `_default_evaluator` (analytical mock) from the user-facing calibration
  path. Custom metrics are now supplied via the
  `objective = "module.path:fn"` escape hatch.
- `hmp migrate` subcommand.

### Fixed
- `SimulationCatalog.write_*` methods are now tolerant of the DuckDB
  single-writer lock through the new retry decorator, fixing a latent
  bug where `hmp list` running concurrently with `hmp run` could raise
  `IOException`.

---

## [v0.3.3] - 2025-12-03
### Added
- Lightweight conda environment option (`env_hydromodpy_light.yml`) and matching light dependency set in `pyproject.toml` for setups without VTK or Jupyter kernels.

### Changed
- Replaced the former `downslope` helper with `masstransfer` as the single surface routing engine.
- Standardized raster reads on `imageio.v2` and removed deprecation warnings.
- Refactored SIM2 processing for leaner memory use.
- Simplified vedo imports in visualization routines and centralized PyHELP imports inside `watershed_root`.
- HELP3O loading now retries/resolves paths more reliably during PyHELP runs.
- Replace 'imageio' by 'rasterio' to resolve deprecation.

### Fixed
- Pandas warnings in PyHELP CSV ingestion and daily output aggregation (removed deprecated args and axis-based groupby).
- Multiprocessing pools in PyHELP now use a spawn context to avoid fork-in-multithreaded warnings on Python 3.11-3.13.

### Removed
- `hydromodpy.modeling.downslope` module (functionality consolidated into `masstransfer`).

---

## [v0.3.2] - 2025-11-28
### Changed
- Reworked SIM2 workflow: coarse clip without reprojection to trim inputs, resample on that reduced dataset, then final clip/mask with reprojection for clean outputs without wasted time or RAM.
- `disk_clip` now accepts `.shp`, `.gpkg`, and `.geojson`, and SIM2 filename parsing keeps the full variable name before `_SIM2_`.

### Fixed
- `toolbox.load_to_xarray` reprojects when `dst_crs` is provided even without a mask, matching the new SIM2 flow and avoiding extra memory use.
- SIM2 resampling preserves encodings and applies masking with the reprojected DEM consistently.

---

## [v0.3.1] - 2025-11-14
### Changed
- Installation guide reorganized with ready-made command recipes, dual YAML options (runtime vs editable), and clearer guidance for conda-versus-pip setups.
- README now flags v0.3.1 as the stable release and the conda YAMLs pin Python 3.11-3.13 explicitly.
- Add spyder package to the conda environment for users of that IDE.

### Fixed
- `pyproject.toml` now lets setuptools auto-discover all `hydromodpy*` packages so `pip install hydromodpy` (and ReadTheDocs builds) no longer fail if optional submodules such as `hydromodpy.modeling.gr4j` are absent from the current branch.
- Pinned NumPy to >= 2.0 and restricted supported Python to >= 3.11, < 3.14 to avoid incompatibilities with other packages.

---

## [v0.3.0] - 2025-11-06
### Compatibility
- Runtime baseline jumps from Python 3.8.10 to the Python 3.11-3.13 series. Tested on Linux, macOS, and Windows.

### Added
- Logging system with `LogManager` class (replaces all `print()` statements).
- GitHub Actions pipeline for automated builds and PyPI publication.
- Single cross-platform conda environment file (`environment-conda.yml`) for Linux, macOS, and Windows.
- Automatic download of HELP3O binaries on first use (no Fortran compiler needed).
- `MANIFEST.in` for packaging executables, examples, and documentation.
- Pin `PROJ_DATA` and `PROJ_LIB` to the active pyproj data folder to avoid stale `proj.db` files.
- Override external `PROJ_DATA` paths that leave the environment or miss `proj.db` so the environment copy always loads (problem often caused by gdal).
- `pyhelp` CLI now exports `PYHELP_WORKDIR` and `help_example.py --workdir` to stop the Windows crash on Example 10.

### Changed
- Renamed package from `src` to `hydromodpy` following standard Python conventions.
- Replaced GDAL with rasterio for pip-only installation (tested with Python 3.13).
- First version available via `pip install hydromodpy`.
- Conda installation now fully automatic with single environment file (with only conda-forge channels, no pip dependencies).
- Updated all imports in examples (00-11) from `src` to `hydromodpy`.
- PyHELP now downloads pre-compiled binaries instead of requiring Fortran compilation.
- Logging supports three modes: "dev" (DEBUG), "verbose" (INFO), "quiet" (WARNING).
- Replaced deepdish with pickle for serialization.

### Removed
- Platform-specific environment files (`env_pyhelp-0.1_windows.yml`, `environment-crossplatform-3119.yml`).
- Fortran compilation requirements for PyHELP.
- Unused FTP-AQUIFER utility scripts.
- Hard-coded GDAL dependencies.
- Removed obsolete third-party packages (e.g., hydroeval, deepdish) to ensure compatibility with Python 3.11+.

### Fixed
- Normalized example folder names.
- Cross-platform file path handling.
- Suppressed verbose logging from third-party libraries (matplotlib, flopy, etc.).
- PROJ data synchronization in PyHELP NetCDF writer.
- macOS HELP3O binary extraction.

---

## [v0.2.0] - 2025-11-05
### Added
- Added MT3D-USGS support with new `Mt3dms`, `Masstransfer`, and `watershed.transport` modules, included Example 09, and provided executables for Linux, macOS, and Windows.
- Added the GR4J rainfall-runoff calibration toolbox with scripts, figures, and sample data under `src/modeling/gr4j`.
- Added the PyHELP land-surface coupling (API, CLI, preprocessing) together with Example 10 resources and a Windows-only environment file.
- Added Example 11 to run the full workflow from scratch without plots.
- Added the `test/01_test_non-regression` suite and reference outputs for regression testing.
- Added yearly intermittency plus MT3D seepage concentration and accumulated mass to the timeseries exports.
- Added platform-specific conda environment files for HydroModPy 0.1.

### Changed
- Updated `modflow.py` to support elevation-driven decay parameters, optional EVT extinction depth, and creation of the LMT link file when using MT3DMS.
- Updated the hydraulic configuration so it keeps the new decay settings and `exdp` value.
- Updated `modpath.py` particle seeding to center start points, respect `model_folder`, and align forward and backward runs.
- Expanded the `watershed_root` workflow with transport functions, a calibration results folder, MT3DMS helper modules, and the PyHELP preprocessing function.
- Improved `timeseries` handling so recharge and runoff accept scalars, series, or dicts while exposing the new MT3D metrics.
- Updated geographic and hydrography helpers to fall back on existing DEM rasters and clip optional stream inputs.

### Fixed
- SIM2 climate ingestion now uses the current Météo-France variable names and units and exposes the soil drought index.
- Watershed visualisations restore the DEM colour bar, scale bar, and labelled watershed overlay.
---

## [v0.1.0] - 2025-10-31
### Added
- **First official release** of the HydroModPy package.
- Established the initial project structure for hydrological/hydrogeological modeling workflows.
- Defined the versioning convention following **Semantic Versioning (vX.Y.Z)**.

---

[Unreleased]: https://github.com/HydroModPy/HydroModPy/compare/v1.0.0...dev
[v1.0.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.5.0...v1.0.0
[v0.5.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.4.0...v0.5.0
[v0.4.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.4...v0.4.0
[v0.3.4]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.3...v0.3.4
[v0.3.2]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.1...v0.3.2
[v0.3.1]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.0...v0.3.1
[v0.3.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.2.0...v0.3.0
[v0.2.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.1.0...v0.2.0
[v0.1.0]: https://github.com/HydroModPy/HydroModPy/releases/tag/v0.1.0
