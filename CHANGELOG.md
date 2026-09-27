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

---

## [v2.0.0a1] - 2026-09-21

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
