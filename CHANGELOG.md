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

### Fixed
- A custom GeoTIFF or NetCDF grid masks its nodata code before its unit is converted (2026-11-01). A
  GeoTIFF read in another unit was refused as declaring no nodata, and a NetCDF `nodata` attribute of
  -9999 mm/day became -9.999 m/day, a value no later step recognised as nodata.
- A `data-request` job, `hmp data get` and `run_request` refuse a mask that is not on disk with
  `JobInputNotFoundError` (`HMPY.E211`), the code `domain-build` and `terrain-delineate` give a
  missing input, instead of a bare `FileNotFoundError` reported as `HMPY.E000` (2026-11-01). The exit
  code stays 10.
- A gridded forcing dataset masks its `nodata`, `_FillValue` or `missing_value` attribute on the cells
  (2026-11-01), so a cell on such a pixel is refused instead of reading -9999 as a rate. Its spatial
  mean, which read only `nodata`, now masks the same three attributes, so the persisted `_watershed`
  series of a dataset that declares its nodata only as `_FillValue` or `missing_value` changes.
- A forcing station whose location is in another CRS than the mesh is refused, naming both CRS,
  instead of being read in the wrong place (2026-11-01). The stations path also passes `idw_power` on,
  which it dropped for the default of 2.
- A GeoTIFF band or a dataset time step that no stress period reads is refused, naming both counts,
  instead of being dropped, and the silent 1000-step cap of a dataset without a simulation window is
  gone (2026-11-01).
- `linear` on a forcing grid of one row or one column and a rotated GeoTIFF forcing are refused by
  name (2026-11-01), instead of raising a raw `QhullError` or reading misplaced pixels.
- Site selection refuses a French territory whose box, read in Lambert-93 (EPSG:2154), lies outside
  the area of use of that CRS, metropolitan France and Corsica (2026-11-01): a DEM without a CRS, a
  `bbox`, a polygon or administrative territory, the station outlets that size the DEM request, and
  the box of the observation request. A territory of another country goes as written. The message
  names the box, says that an overseas territory needs its own CRS and what to write instead.
- A `map_context` layer of the site selection map is read as RFC 7946 (WGS 84 lon/lat), or in the CRS
  its `crs` member names, and moved into the map CRS (2026-11-01). A layer whose coordinates leave the
  degree bounds, hold a position of one number, or name a CRS pyproj cannot read is refused by name
  instead of drawn in the wrong place, and the manifest check no longer asks a context layer for a
  `hydromodpy_coordinate_crs` member.
- An observation point of the site selection is placed the same way in every vector layer
  (2026-11-01). A point without a readable location or CRS is skipped and recorded
  (`hydromodpy_skipped_observations` in the GeoJSON, a log warning for the GeoPackage and GeoParquet
  layers) instead of stopping the GeoJSON or being kept without a CRS, and a point given in another
  CRS is moved into the CRS of the batch instead of being labelled with the first CRS met.
- A geology support whose geology data did not load now stops with a configuration error (HMPY.E102)
  that names `[domain.supports.<id>]` and says to declare `[data.geology]`, instead of a bare
  `ValueError` (2026-11-01).
- `field_param_from_toml` refuses a top-level `[field]` without `id` with a `ConfigMissingError` that
  names the file, instead of a bare `KeyError` (2026-11-01).
- A transient run refuses an active cell whose specific yield (convertible cell) or specific storage
  (confined cell) is zero, negative or not finite, as a heterogeneous Sy gives where no zone of its
  support covers the cell (2026-11-01). The refusal names the property, the layers and the cell count,
  in MODFLOW 6, MODFLOW-NWT and Boussinesq. A steady run is not checked, it reads no storage.
- A runtime property override is checked against its physical range as it was written, so the refusal
  counts the values given and names the layer and the cell (2026-11-01). A steady run no longer
  refuses a Sy or Ss override it does not read.
- Boussinesq refuses a hydraulic conductivity that is zero, negative or not finite on a cell of its
  runtime mesh, as MODFLOW 6 and MODFLOW-NWT do, naming the support when K is heterogeneous
  (2026-11-01).
- A gridded runoff that the watershed-mean reduction refuses, such as a day without any valid pixel,
  now stops the run when its forcings are persisted and fails the calibration trial with its message,
  instead of being dropped with a debug line (2026-11-01).
- A runtime property override of `Project.run(properties=...)` and the cell values a field parameter
  gives the mesh, after its depth profile, are checked against the physical range of the property
  (2026-10-31). An override such as `Sy = 0.8` on one cell, or a profile that takes Sy under 1e-4 at
  depth, reached the solver. The refusal names the property, how many values fall outside and the flat
  index of the first one. A cell that no zone of the support covers is not checked yet.
- The spatial mean of a gridded forcing (the homogeneous series, the scored gridded runoff, the
  persisted watershed mean) reads the valid pixels only (2026-10-31). A GeoTIFF nodata pixel no longer
  enters the mean as -9999, a NaN pixel no longer refuses the whole grid, and a band or a time step with
  no valid pixel is refused naming the file, the slice and the footprint.
- The GeoParquet and GeoPackage layers of a selection write null where the CSV writes `""` (snapped
  coordinates, snap distance, area), so a selection that mixes a snapped and an unsnapped outlet no
  longer fails with `ArrowInvalid` (2026-10-31).
- A `generated_bands` break or a `generated_rings` radius written as a text without a unit in absolute
  mode (`breaks = ["300"]`) is read in metres, like the DEM elevation (2026-10-31). It raised a raw pint
  `DimensionalityError`. A text that is not a number, a unit that is not a length (`"10 %"`, `"1,5"`,
  which pint reads as 15) or a length that is not finite is refused naming the key and the value.
- Two raster codes of a catchment-zone or raster support that carry the same label are one zone
  (2026-10-31). The value of a heterogeneous parameter on that label was counted once per code, so
  K = 1e-5 gave 2e-5 on every cell.
- `domain-build` and `terrain-delineate` refuse an input file that is not on disk with the typed code
  `HMPY.E211` (`hydromodpy.core.exceptions.JobInputNotFoundError`, a `FileNotFoundError`), still under
  exit code 10 (2026-10-31).
  The outcome said `HMPY.E000`, the code of a bug in HydroModPy. Both workers resolve their input files
  with one function, `spatial.job_inputs.resolve_input_file`.
- A geographic tree is reused only when every shapefile keeps its `.prj` (2026-10-31). The cache asked
  for three sidecars, so a tree that had lost a `.prj` reused a polygon without CRS. It is now a miss and
  the tree is rebuilt. The generated `river_network.shp`, which Whitebox wrote without a projection, now
  carries the `.prj` of its CRS.
- With `[geographic.crossings]` on, the snapped outlet of the context, of the runtime attributes and of
  the cache manifest is the one of the second delineation, on the notched ground (2026-10-31). It was the
  one of the first pass, while `outlet_snap.shp` and the catchment came from the second.
- `field_param_from_toml(section=...)` and the `--field-param-section` option of the geology property
  demo read a nested section such as `flow.param.K.field` (2026-10-31). Both failed with "Field required"
  for any section but `field`, because the whole file was checked as one field-parameter table. The table
  that holds the section is now the payload, a nested `[field]` with no `id` takes the key of its parent
  table, and a section that is absent or that names no `[field]` table is refused by name.
- Every value of a field parameter is checked against the physical range of its parameter, in the unit
  it was declared in (2026-10-31). Per-zone values, inline or read from a CSV table, a section with no
  `id` and a `FieldParam` built in code skipped the check, so a K of 1e3 m/s in one zone reached the
  solver. The refusal names the parameter, the zone and the value.
- A geographic raster that declares no nodata is stored with -9999, the nodata of the DEM beside it in
  the geographic group, instead of -99999 (2026-10-31).
- A site selection whose territory writes its country in lower case (`country = "fr"`) asks the
  DEM and the hydrometry stations over that territory (2026-10-28). The candidates were already
  clipped to it, but the DEM request compared the country to `"FR"` exactly and fell back to the
  outlets, or to no extent at all.
- A DEM that the data layer cannot load for `delineate_from_outlets = true` stops
  `hmp site select` with a configuration error that names the data root and the `[data.dem]`
  section to check, as the other input modes already did (2026-10-28). The raw provider error
  came through before, with its own exit code.
- `get_whitebox_backend()` and `delineation.registry.get_backend()` return the same Whitebox
  backend, so a process opens one Whitebox environment (2026-10-28). They returned two objects,
  each with its own environment, and `clear_whitebox_backend_cache()` cleared one of the two
  caches. A backend registered under `whitebox_workflows` is now what both return, and
  `get_whitebox_backend()` still refuses the `"whitebox"` alias.
- `compute_catchment_area_km2` sums every polygon of the watershed (2026-10-28). It read the first
  row only, so a catchment in several parts reported less than the area its domain was built on.
  A numeric `AREA` column still wins over the geometry, and a column of text still leaves the
  geometry in charge.
- `measure_polygon_area_m2` leaves out a polygon row without geometry (2026-10-28). The total
  area of the layer became NaN.
- The forcing refusals of an empty grid or of a non-finite pixel no longer call every variable
  recharge (2026-10-28). They name the gridded or GeoTIFF forcing values, since ETP and the other
  variables read the same path.
- The `geographic` group of a run store opens with `xarray.open_zarr` (2026-10-28). Its rasters
  stored the nodata as a float `_FillValue` attribute, which xarray refuses on a Zarr 3 array, and
  had neither pixel coordinates nor a grid mapping. A raster now holds its nodata as the Zarr
  `fill_value` (GDAL) and as the CF `missing_value` (xarray), an integer raster too when its type
  holds the nodata, gets the axes `<name>_y` and `<name>_x` at its pixel centres, in metres or in
  degrees after its CRS, and a `<name>_crs` grid-mapping variable. The `transform`,
  `crs`, `nodata` and `shape` attributes stay, so `hmp export` and the run API read runs written
  before the same way, and only the rasters are offered for export.
- The `*_long_lat` metadata of a catchment, real or synthetic, is `(longitude, latitude)` as its
  name says (2026-10-28). `read_dem_metadata` stored `(latitude, longitude)`, and the synthetic
  catchment shifted the latitude by 360 degrees where the longitude was meant. The Greenwich copy
  of the centroid now takes its longitude in [0, 360), and the department lookup asks Nominatim
  for `"<latitude>, <longitude>"` with a longitude in [-180, 180]. No production code reads these
  attributes.
- The scripts of `spatial/geographic/cases/` and `spatial/domain/cases/` run from a checkout
  (2026-10-28). `update_geographic_goldens.py` ran pytest from `hydromodpy/` so none of its four
  test paths resolved, `reference_catchment_delineation_case/run_case.py` stopped on
  `KeyError: 'catch_folder'` after its run, and the relative paths of five case TOML files led to
  `hydromodpy/examples/data`, which does not exist. The domain case also drops a `data_path` key
  that no code read and that named a folder removed from the repository.
- The GeoJSON files of the site selection open in the CRS they are written in (2026-10-28). They
  carried their CRS only in the `hydromodpy_coordinate_crs` key, so geopandas, QGIS and
  `hmp sites import` read Lambert-93 coordinates as WGS 84 degrees. The seven writers (selected
  outlets and basins, observation points, candidate outlets, generated network, geology and
  influence evidence) now also write the `crs` member, `urn:ogc:def:crs:EPSG::<code>`, when the CRS
  has an EPSG code. The coordinates and the `hydromodpy_coordinate_crs` key do not change.
- A homogeneous field value is checked against its physical bounds in its declared unit
  (2026-10-28). The check read the number as if it were in the canonical unit, so K = 150 m/day
  was refused as 150 m/s and K = 1e-13 m/day was accepted. The value is now converted first, so a
  K under 8.64e-10 m/day is refused, and so is a unit of another quantity, such as `m-1` for K.
  The 115 homogeneous values of `examples/`, `validation_cases/` and the tests all pass.
- A nodata pixel of a gridded recharge is refused where a cell reads it (2026-10-28). A GeoTIFF
  pixel equal to its declared nodata reached the cell as -9999, and a cell on a NaN pixel took
  its neighbour, because the interpolators drop non-finite pixels. The forcing now refuses, with
  `DataContractViolation`, a cell whose nearest pixel, pixel triangle (`linear`), 16 nearest
  pixels (`idw`) or overlapped pixels (`area`) hold nodata, and a slice with no valid pixel, which
  gave zero recharge. A NetCDF follows the same rule, so a NaN pixel that no cell reads is now
  accepted where the whole grid was refused, and a period mean is nodata on a pixel that is
  nodata on any of its days.
- A `.msh` file written by HydroModPy is a gmsh file, of format 2.2 ASCII (2026-10-27). It was an
  ANSYS Fluent file under the `.msh` name, because meshio takes ANSYS first for that suffix, so
  neither gmsh, `[mesh.triangle] path` nor the reader of the 2.2 format read it; meshio read it
  back only because it tries ANSYS first too. `write_gmsh_2d_mesh`, `write_msh` and
  `save_planar_mesh` write a path ending in `.msh` as gmsh 2.2 ASCII when no `file_format` is
  given, and an explicit `file_format` still wins.
- A Voronoi mesh goes through meshio and VTU (2026-10-27). `to_meshio` handed meshio one polygon
  block of mixed arity, which meshio refuses, so `write_vtu` failed on every Voronoi mesh. A polygon
  block now goes to meshio as its runs of cells of one arity, in its cell order, and `from_meshio`
  and `read_vtu` give back one polygon block with its cell fields. A planar mesh written as VTU reads
  back with x and y only, where it kept the zero z that meshio adds. A mesh with a z that is not
  zero, or with 3D cells, keeps its z.
- The NetCDF export writes the cell centres the model used, `mesh/face_x` and `mesh/face_y` of the
  run store, in place of the mean of the vertices of each cell (2026-10-27). On a Voronoi mesh of
  cells about 20 m wide the mean was up to 14.7 m off the generator. A store written before the
  centres still exports the mean. `export_netcdf()` called on its own writes a mapping attribute,
  such as `hydromodpy_identity`, as JSON text, where it failed before. `hmp export` already did.
- A buffer written as a distance (`[geographic.catchment] buff_area = "1 km"`) is snapped to the
  DEM grid like a percentage (2026-10-26). An off-grid distance put the domain edges, and the
  cells of a regular grid, 25 to 50 m off the pixels of a 75 m DEM, so the ground of a cell moved
  by about 2 m at control points. On a 75 m DEM, 500 m becomes 525 m and 1 km becomes 975 m.
  Example 05 (`"10 m"`) now gets a buffer of one pixel.
- The mesh build no longer warns about the bisection offset on an orthogonal mesh (2026-10-26).
  On a mesh whose 95th percentile of non-orthogonality is under 1 degree, the two-point flux stays
  consistent wherever the line of the two centres crosses the face. The warning fired on 44 to 70
  per cent of the cells of a generated Voronoi mesh. The QA still reports the offset, and a
  non-orthogonal mesh still warns.
- A comparison exports the budget of one zone, and `flux_timeseries` divides each line by the area
  of its own zone (2026-10-26). The budget exports of `hmp report compare` added the `catchment` row
  to the domain row, so a run that carried both counted the water of the catchment twice. On example
  04 the mean recharge was 2.02 m3/s, 54 % above the 1.31 m3/s of the domain.
  `budget_timeseries_long.csv` and `budget_timeseries_wide.csv` hold one zone and a `budget_zone`
  column. `--budget-zone {domain,catchment}` picks the zone, the domain by default, and
  `ComparisonSpec.budget_zone`, `run_comparison` and `compare_runs` take it too. A Boussinesq state
  has no `catchment` zone, so it enters the domain export only, and a catchment export leaves it out
  with a warning. The numerical closure reads the same rows, and the three budget figures of the
  comparison name their zone in the title. `flux_timeseries` in `mm/period` divided the `catchment`
  line by the area of the whole domain, so its depths were 0.54 times too small on example 04 (64.77
  km2 of basin, 120.41 km2 of domain). It divides by the whole cells of the basin of D for the
  `catchment` line and by the active domain for the domain line, and the axis names the zone. A run
  with a `catchment` line and no stored basin is refused, with the advice to plot m3/s. On example
  04 the recharge of the catchment line gives 0.943 mm/d, like the domain line. The CSV of an
  earlier export are not comparable with the new ones (`542595c7d`).
- A lake over a pinched or sloping stack connects to every active cell that faces its water
  (2026-10-26). The bank connections went to the occupied layer index only, and only where the
  neighbour was active in that layer. A neighbour whose layer was pinched out had no bank, and on a
  sloping stack the deeper layers that face the lake were ignored. A bank now joins the water slice
  of a lake column to each active cell of the neighbour column that holds a part of it, whatever its
  layer, and a band thinner than 1 mm is dropped. A flat stack gives the same rows as before. On a
  lake of 20 columns with layers that follow the terrain, the bank rows go from 14 to 27, the
  lake-aquifer exchange rises by 1.6 % (1.7045e-2 to 1.7311e-2 m3/s) and the stage moves from
  103.7300 to 103.7314 m. The balance of the LAK package stays under 0.01 % in these cases. A carved
  lake bed on a stack with pass-through cells keeps them flat, so the first active cell under the
  lake has its top on the carved bed, where the minimum thickness of the carve had put it 0.5 m
  lower than the bed the lake table holds. A lake in the active-shore mode connects to the top
  active cell of the column, where it connected to layer 0, a pass-through cell on a stack pinched
  from the top. The count of bank connections that a cutoff wall seals can drop, because it counts
  the connections that exist (`d0b98e761`).
- MODFLOW-NWT reads a flow `Kv` as the vertical conductivity of UPW (2026-10-26). `Kv` was dropped
  and the vertical conductivity stayed K. The code writes `layvka = 0` and `vka = Kv`, in the time
  unit of the solver like K, because `layvka = 0` is what makes `vka` a conductivity. Without `Kv`
  nothing changes. A `Kv` that is not positive is refused, and so is a `Kv` beside a `vka` other
  than 1, as in MODFLOW 6. The results of an NWT run with a `Kv` change, and a calibration of `Kv`
  under NWT has an effect now. No example sets `Kv` with NWT (`cf15eb392`).
- The warning about disconnected active cells runs on the final grid, after the lake mask
  (2026-10-26). It counts a pass-through cell as a link between the layers above and below it, and a
  lake as a link between the active cells it touches, as MODFLOW 6 does. It no longer reports false
  groups when a whole layer is pinched or when a lake takes the only active cell of its columns. The
  text says `no face, vertical connection or lake joins` (`cf15eb392`).
- A calibration output with `support = "cell"` and no `layer` reads the top active cell of its
  column (2026-10-26), like any point given without a layer. It read layer 0, a pass-through cell on
  a pinched stack. `CalibOutputCell.layer` is optional. The adapter answers through a new method of
  the `CellLocator` protocol, `top_active_layer(ctx, row, col)`, which MODFLOW 6, MODFLOW-NWT and
  Boussinesq implement. A column with no active cell reads layer 0, a row or a column off the grid
  is refused, and so is an adapter that cannot answer, both naming the output. A layer written in
  the file keeps its meaning. A target whose physical range reaches below zero, which today means
  the three angles of the K tensor, is searched as written with a uniform sampling. It inherited the
  log space of K, and a bound such as [-30, 30] stopped the load with `log search space requires
  lower > 0`. `Project.run(properties=...)` takes `Kv`, `K22` and the three angles beside K, Sy and
  Ss, where they were dropped without a word. A name that is no property is refused, and so is a
  property that the solver does not read, such as `K22` under NWT (`f0d4875b9`, `e6084958a`).
- The head series `head_domain_low`, `head_domain_mid` and `head_domain_high` of a comparison pick
  their cells by surface elevation (2026-10-26). They took the cell at the rank 0.2, 0.5 and 0.8 of
  the index in `observables.csv`, which has no relation to elevation. They now draw the median cell
  of the lower, middle and upper third of the active cells of the reference run, sorted by the
  elevation of `mesh/topography`, or the top of `mesh/z_interfaces`. A run whose head map has
  another cell count is left out, where it was read at the same indices. Without a reference run,
  the cells come from the first run that has a head map. A run that stores no elevation draws no
  figure, and the new `head_domain_figures_skipped.json` at the root of the comparison says why. A
  figure whose plot fails is logged. The images written before are not comparable (`2edff003e`).
- Validation cases that failed before the mesh campaign pass again (2026-10-26). A twin observation
  point on a cell edge reads the same cell on the route of the truth and on the route of the trial,
  because both locate it on the polygons of the mesh. The truth route rounded on a regular grid. The
  cost at the true value of the piecewise-K twin on MODFLOW 6 goes from 0.040145 to under 1e-12. The
  loader of the Brutsaert cases reads the boundary flux on the domain row of the budget, since a
  synthetic run carries a `catchment` row beside it, and the truth discharge no longer adds that
  row. The NWT recharge-step case declares `HEADTOL = 1e-9` m and `FLUXTOL = 1e-10` m3/s in its own
  file, so every step closes at 0.00 % where the defaults left up to 1.47 %. The goldens `fast_mf6`
  and `extensive_mf6` take the 15-decimal floats that MODFLOW 6 reads since the DISV input is
  widened (the p50 of the water-table depth moves by 1.15e-4 relative, the mean depth of the
  extensive one from 0.448996 to 0.449116 m), and the offline test of the data seal no longer
  expects the provenance children. No tolerance moves. The benchmark figures of the `modflow6` and
  `modflow_nwt` columns of the twins can move a little (`c7b7fbad2`, `8c19288ac`, `51c14c706`,
  `b1e2a84e1`, `4bb5b0754`).
- A mesh refined by an earlier run replays from that run (2026-10-26). The frozen `config.toml`
  writes the `sim_id` that a `[[mesh.refinement_zone]]` `run` read in place of its name, taken from
  the new `zone_runs` key of the mesh summary. So `hmp catalog rerun` and `hmp run --resume` read
  the same run even after a later version of it exists, and a replay whose source is gone stops with
  a message that names it. The run identity hash reads the `sim_id` of the run that `[flow]
  restart_from` and the zones name (`hydromodpy/results/source_runs.py`). A resume of an interrupted
  run no longer starts from zero, a `.v2` of the source gives another hash, and the three forms of
  `restart_from` (name, table, path) hash alike. The hash of a run with a `restart_from` or a zone
  with `run` changes once, so such a run is recomputed once. A run with neither keeps its hash. The
  message of a river mesh without a network threshold names the zone when a `height_above_stream`
  zone asks for the network (`d3469a487`, `6381a97ae`).
- A run calibrated by a `[calibration] protocol` replays from its own frozen `config.toml`
  (2026-10-19). The load writes `[site] gauge` into each stage and `[metrics] window` into a
  transient stage without one after it expands the protocol, so the frozen stages read as a
  contradiction of the protocol and `hmp catalog rerun` or `hmp run --resume` refused the run.
  Both sides of the comparison now take these project defaults. Another station or another
  window is still refused.
- HydroModPy's own `RuntimeWarning`s reach the log again (2026-10-26). `flopy.plot.plotutil`
  ignores every `RuntimeWarning` when flopy is imported, so an unsettled cyclic spin-up, a
  steady initialisation closed on its budget only, the fixed EVT extinction depth of a routed
  deficit, a lake footprint far from its abacus, a failed GP surrogate fit and a failed HELP3O
  download were silent in a run. Each is now logged as a warning too.
- Calibration audit leftovers fixed on 2026-10-25 (thirteen commits `6feb2dfdc..a07541e77`).
  `Project.best` and `[sites.summary] best = "calibrated"` keep the `evaluated` runs, the calibrated
  runs scored out of their calibration window; `label="calibrated"` keeps the in-window ones only.
  An observed gauge is scored only against the simulated series of its own name, or against the single
  simulated series when it is the station of the metric rule: an upstream gauge is no longer scored
  against the outlet discharge, and a gauge left unscored is logged and sealed as the failed, non-fatal
  check `observations_scored`. A pair dropped because the simulated value is NaN (a dry cell) is
  counted: trial component `<output>.n_sim_nan`, `n_sim_nan` in `objective_samples` of `session.json`,
  and a new column `n_sim_nan` of the run metric rows, `metrics.parquet` and the index, with a warning;
  `[calibration.aggregate] min_samples` applies to every scored output and stays 1. Index schema 9:
  run `hmp catalog reindex`. `units` of a calibrated parameter converts: bounds written in another unit
  of the same quantity are converted into the unit of the target (m/s on a conductivity read in m/day:
  86 400), a unit of another quantity is refused naming both, and `units` beside `mode = "scale"` is
  refused. A lake `bedleak`, SFR `streambed_k`, barrier `hydchr` or `k` and well `flux` is searched in
  the unit its own field names (`bedleak_unit = "1/day"` was read 86 400 times off) and carries a
  physical range; `hmp config targets` prints every range in the unit of its target. A search says why
  it stopped, `rule_met`, `plan_exhausted` or `budget_spent`, sealed as `stop_state` in `session.json`,
  each phase and `checks.calibrated_by`, and printed by the console, the READMEs and the HTML report;
  `converged` is true only in the first two. A phase whose search has no rule of its own (random_search,
  cma_es) still passes its best trial on and says it "froze the best of a budget-only search"; a search
  with a rule stopped by its budget freezes nothing, as before. Every calibration launch (`hmp
  calibrate`, `hmp run` in calibration mode, both `--dry-run`, `hmp.calibrate`, `Project.calibrate`)
  runs the checks of `hmp config check` first, on the effective document and phase by phase,
  overrides included, and stops with exit code 14 before anything is prepared; the checks of the
  prepared model run once, before the session is reserved; a `path` outside the catalogue that reaches
  a value of the config warns instead of refusing. Example 21's `auto_sfr_drn.toml` is no longer
  refused: each phase is checked with its own overrides.
- Calibration audit of 2026-10-22, batch q01 (2026-10-22). `hmp calibrate --resume` refuses a
  session whose journal holds trials this document scores another way, and a session a live process
  of this host still writes; each trial row carries its `params_hash` (`8c6c7210d`). The promoted
  run is the trial `session.json` names, a speculative trial never ranking first (`a4a076e5e`). The
  cache preload skips a session journal this version cannot read, with a warning (`483921ff1`). No
  linearized width is reported when a perturbed run fails (`2f67eb2cb`). Bounds written in another
  unit than the target are refused with the converted bounds (`ebf7e1df1`, `00a0881c3`). A declared
  output that no block and no `variable` scores is refused when the file loads (`6270f4095`).
  `[calibration.persistence]` is retired: still read, ignored with a warning (`d0ead4259`).
  `hmp calibrate` and `hmp run` exit with code 21 when the session closed failed, partial or
  aborted, and print the reason `session.json` gives (`c43d85122`). `grid` and `lhs` stop when every
  point of their design is solved: a `max_trials` below the design is refused before the first
  solve and by `hmp config check`, and `"auto"` budgets the design (`8111574df`). The trial cache
  key holds the content of `stream_geometry_path` and `minimal_stream_geometry_path`, sidecars of a
  shapefile included, so a network calibration solves its trials again once and a session written
  before cannot be resumed (`a6531e8cd`). `nse`, `log_nse`, `nse_delta` and `nse_seasonal` give NaN
  when the observed spread is no larger than rounding; the metric rule version is unchanged, so a
  cached cost of such a series stays as it was (`1f54dccc2`). The network protocol is tested on
  MODFLOW-NWT and unsupported on Boussinesq (`55a766eac`). Docstrings and pages corrected: the
  default rasterization `heads`, the validity bound, the default window of the second stage, the
  three rasterization rules, the method how-to and the diagnostics notes (`c41e9c6cf`, `6f60087b9`,
  `a1f2833ae`, `2e6b25de0`). The code identity of the cache key and the release flux Boussinesq
  declares without serving it are not done yet.
- Calibration audit of 2026-10-14, windows (2026-10-20, decisions m03 and m04). A `[metrics]
  window` that shares no day with `[simulation.time]` is refused when a file is loaded, naming both
  periods (`d97ebb8a4`); the frozen config of a run already on disk that carries such a window still
  reads, with a warning, and the run has no score (`b7059b9ea`). Series figures of a run
  (hydrograph, hydrograph_sim_obs, piezometer and lake sim/obs, sfr_reach_timeseries,
  flux_timeseries, residuals) shade what precedes the `[metrics] window` start, read from the run;
  there is no `spinup_end` key (`6d562725e`). The validation window (m05), the single `window` type
  (m06), the refusal of `warmup_periods` (m07) and example 04 split in calibration and validation
  (m24) are not done yet.
- Calibration audit of 2026-10-14, metrics (2026-10-20, decisions m10, m12, m13, m14). One scoring
  route: a calibration written `variable` + `objective` is scored by implicit blocks, one output
  `<variable>@<station>` and one block `<objective>@<station>` per scored station, with the trial
  costs of before; `ScalarObjective` and `ObservationSet` are removed (`814c99829`, `29ce59fdc`).
  The trial components of that form are renamed (`cost:<objective>@<station>` becomes
  `<objective>@<station>.raw_cost`, with `.n_values`, `.n_paired`, `.date_start`, `.date_end`); only
  the gauge `observed_station_id` names is scored; an undefined metric gives the trial an infinite
  cost instead of raising; `aggregate.min_samples` applies to it. `nse_log` clips a negative value
  to zero and counts it, for a run as for the calibration cost, and the run writes `n_clipped` on its
  metric row and in the index (`fc82b7684`). `pbias` is `100 x sum(s - o) / sum(o)`, positive when the
  model overestimates, the sign of `bias` (`91722e2b3`). The metric rule is version 2: runs scored
  under 1 and 2 no longer rank together, and the calibration cache is solved again once. The KGE is
  written as its 2009 form everywhere it is described (`2b0a96d0b`, `67dec1fce`). Index schema 8:
  run `hmp catalog reindex`. The cost naming (m15) is not done yet.
- Calibration audit of 2026-10-14, parameter surface (2026-10-20, decisions m17 to m23 and m28). A
  renamed key in a file is refused with its new name, `hmp doctor --fix-config` rewrites it, and the
  frozen config of a run on disk reads under the new names (`a8d1dc2fb`). Renamed:
  `max_iter` -> `max_trials`, the only search budget (protocol `steady_max_trials`,
  `transient_max_trials`; `Project.calibrate(max_trials=)`); the budget options of the methods
  (`maxfev`, `maxiter`, `max_evaluations`, gp_mapping `max_iter`) are refused, the doctor moves an
  evaluation count into `max_trials`, and da_mh_gp `max_iter` is `chain_length`; gp_mapping and
  cma_es spend `max_trials` (100 under "auto", no longer 30) (`963963e05`). `tolerance` ->
  `precision` (protocol `steady_precision`, `transient_precision`); `uncertainty.tolerance` and
  `mode` -> `cost_margin`, "5%" of the best cost or a length such as "75 m" on a search scored only
  by network distances (`5896f4685`). `parameters.<p>.transform` -> `search_space`, `prior` ->
  `sampling`, `objective_blocks[].transform` -> `cost_transform`, and `Calibrable` follows
  (`2c67560a2`). `extent.maximal_flowing_steps` and `minimal_dry_steps` -> `maximal_flowing_duration`
  and `minimal_dry_duration`, durations converted by the run's step (flowing rounded up, dry rounded
  down); left unwritten they are one time step, as before (`b701911a3`, `627d8db2c`). A phase that
  writes no `method`, `max_trials`, `precision` or `method_options` takes them from `[calibration]`,
  and `--list-phases` says where each comes from (`95690355c`). `hmp calibrate` takes `--set`,
  `--overlay` and `--case`, and a calibration launched with them is named after the user's file or
  `--case`, not after the temporary copy (`c5ab86112`, `87f7206c0`). `[sites.summary] rank_by`
  names the ranking metric (default "nse"); the order of `metrics` no longer chooses it
  (`b94e1e562`). The trial cache is keyed on what changes a cost only: a new method, seed,
  precision, budget, method options, bounds or search space replays the trials already solved;
  params_hash v3 solves every earlier trial again, once (`687cc62f3`). The removal of
  `observed_station_id` (m16) is not done yet.
- Calibration audit of 2026-10-14, methods (2026-10-20, decisions m25 to m30). The GR4J package
  without a model, `hydromodpy.calibration.lumped`, is removed and the docs no longer announce GR4J
  (`2db8dd8b0`, `a41feb5fe`). `da_mh_gp` is described as a sequential search, not a posterior
  (`fc2adb018`, `9704e675c`). A phase may write `bounds` for its parameters, inside the section's
  bounds or the field's range, refused otherwise (`cdc36c404`). The acceptable interval of
  `cost_profile` is read on the total cost only; a block cost drawn alone gets no interval
  (`eca1327b4`, `476e77916`). A MODFLOW-NWT run writes the catchment budget row, so a run without
  the per-cell budget reads its `_catchment` discharge on the catchment and its score matches its
  trial cost (Nançon, session `26952cbc`: KGE 0.24 -> 0.87) (`2876df91d`). Trials are not truncated
  (m31).
- The four decided items of the calibration and score audit of 2026-10-14 are applied: m01, m08,
  m09 and m11 (2026-10-20, eight commits `d2e2dd729..829864b4a`). What changes for a user:
  - A calibration session keeps the periods of its scoring window the way the run scores them:
    a mean counts when its whole period lies in the window, a state when its stamp does
    (`core.time.period_aggregation.periods_in_window`, one rule for both). The session cost is
    now `1 - score` of the run it promotes. Under a start-only window a session scores one pair
    fewer (24 months instead of 25 on example 04, 1827 days instead of 1828) and its cost moves
    slightly. The cache key carries the scoring rule version: every trial cached before is
    solved again, once.
  - `evaluated` needs a score window that shares no day with the calibration window. A window
    that overlaps it without being equal keeps the run `calibrated`, with the reason "scored on
    a window that overlaps the calibration window". The label rules are version 2.
  - The index never ranks two rules together. `Catalog.rank/best/worst`, `@best:`/`@worst:`,
    `find(<metric>_gt=...)`, `Project.runs.best` and `hmp dev rank` raise `MixedWindowsError` on
    scores of different stations, variables, windows or rule versions; `mixed_windows=True`
    (`--mixed-windows` for `hmp dev rank`) ranks them anyway, and a named station
    (`@best:nse@STATION`, `--station`) only needs one window and one version. The CLI verbs that
    take an `@`-selector have no flag: name the run, narrow with `--site`, or resolve it from
    Python. `hmp dev rank` prints each score's window. `v_best_per_project` holds one row per
    project and rule, with the rule columns, and leaves unscored runs out. Index schema 7: run
    `hmp catalog reindex`.
  - A block whose metric rises with the fit (nse, nse_log, kge, nse_delta, nse_seasonal,
    reservoir) over several outputs is refused at load: write one block per output, each with its
    weight, so the costs average per station instead of pooling the stations into one efficiency.
    rmse, mae and the network distances still pool several outputs. No example, documentation
    page or protocol declared such a block.
- The calibration and score audit of 2026-10-14 closes its second batch of fixes that needed no
  decision (2026-10-20, 33 commits `2d77f617a..66cde23bd`). What changes for a user:
  - Search engines. `gp_mapping` with `kappa != 0` no longer stops after three proposals on
    positive costs: it compares the improvement the lower confidence bound still promises to
    `ei_tol`. `scipy_nelder_mead` no longer stops at a hard 100 iterations: with no `maxiter` or
    `maxfev` in `method_options` the session budget `max_iter` is its cap, and a start on an
    upper bound no longer builds a flat initial simplex. `cma_es` with `seed = 0` repeats (cma
    read 0 as "seed from the clock"). `uncertainty = "linearized"` reads the residuals of the
    calibrated point, not of the last trial perturbed by 1 %. The "search did NOT converge"
    warning promises a cache replay only for a larger `max_iter` on the same file: a new
    `tolerance`, `seed`, `method` or `method_options` changes the cache key.
  - Scores. A period the gridded runoff does not cover is a gap in the scored discharge, no
    longer scored as baseflow only (the count is logged once). `normalize_cost` divides by the
    standard deviation of the scored sample, after the burn-in, not of the whole record, and its
    fallback is logged: a normalised block with a burn-in gets a different cost. The nse_log
    epsilon is one rule, `core.metrics.log_floor`; the `hydrograph_log_nse` floor is read on the
    scored sample. The Brutsaert recession case scores with the core kernels (its NSElog takes
    the common epsilon). A score turns into a cost by `METRIC_SENSE` alone (`cost_of`,
    `score_of`); the fit panel of `calibration_progress` frames a transformed efficiency block
    and labels it "lower is better".
  - Index and readers. Metric names come from one list: `METRIC_SENSE` drops `r2`, `mse`,
    `kge_delta`, `objective_best`, `closure_mean_abs_m3_s` and `closure_rmse_m3_s`, which nothing
    produces, and `v_metrics_wide` pivots the run kernels, one row per run, station and
    variable. The index `metrics` table drops `n_samples`, `period_start` and `period_end`;
    runtime numbers (solve time, budget discrepancy) stay in the run facts and the seal but leave
    `hmp catalog show`, `hmp catalog diff`, `compare_pair` and the index (index schema 6: run
    `hmp catalog reindex`). `hmp catalog diff` and `compare_pair` compare per (metric, station,
    variable) and show each side's window and n; the diff JSON rows change shape.
    `Catalog.find(<metric>_gt=...)` refuses an unknown or retired metric name instead of
    returning nothing.
  - "Same rule" is one definition and one exception, `MixedWindowsError` in
    `results.run.sealed` (a `DataError`, no longer a bare `ValueError` from `RunSet.best`).
    `hmp catalog ls --best` without `--by` refuses runs scored at different stations and
    suggests `--by site`.
  - Promotion. With `save_catalog = false` and `save_runs` other than `"none"`, the promotion
    no longer hands out a `sim_id` for a run it never wrote: it is reported as failed with the
    reason, the session closes `partial`, and `hmp project promote` refuses the same way.
  - What a session prints. The cost is labelled with what it is, transform and normalisation
    included (`log10(rmse / sd(observed))`, `1 - nse_log`), in `hmp calibrate`, the `hmp run`
    recap and the session HTML report, which now shows the best cost at all; `session.json`
    records it as `objective_label`. Beside the best cost the console and the HTML print the pairs
    it was scored on (count, first and last period-end stamp, per output) and the declared window;
    `session.json` keeps `objective_window` (the declared window, which `calibrated_by` reads)
    and adds `objective_samples`. The single-metric route counts no pair and says so. The
    `methods.md` of a protocol calibration states each stage's metric and scored pairs instead
    of the generic spin-up sentence. A staged session records as `objective_name` the metric of
    its last phase, the one its value belongs to, not `distance_gap + nse_log`. A session left
    `partial` by a failed trial names the trials, and names the stopping rule only when it was
    not met. A phase that did not converge no longer promises a replay after loosening the
    tolerance.
  - What a check prints. `hmp calibrate --list-phases`, `--dry-run` and `hmp config check` print
    the window each phase scores on, and the check prints `[metrics] window`. `hmp config check`
    compares a protocol `scoring_window` with the window the recipe really scores, `[metrics]
    window` when declared. `lineage.overrides` keeps the case of an `HMP_SET_*` key
    (`flow.param.K`, no longer `flow.param.k`).
- The lake-river stack closes the findings of the 2026-10-14 audit left open on 2026-10-15
  (2026-10-20, nine commits `612011a41..cc6378260`). What changes for a user:
  - Lake outlets run one way. Two WEIR outlets of two lakes toward each other at the same crest
    are refused, naming both outlets: they made the water circulate instead of a sill. A
    spillway without a reach on the dam foot is refused (enable `rectify_on_mesh`) instead of
    falling back on the nearest reach, which sent the release back into the reservoir on the
    Chèze; the SFR link below the dam is kept after the cut at the lake. With a cutoff wall the
    dam foot is chosen downstream of the wall. The guard against a LAK to SFR to LAK loop maps
    the 1-based `terminal_lake` and covers every reach upstream of the lake.
  - Lake series: `outlet_inflow` is published and `outlet` is now a positive outflow (the
    published series changes sign). `seepage_under_dam` is renamed `lake_bed_vertical_exchange`,
    which is what it measures. The flow through a cutoff wall is published as `cutoff_wall_flow`
    (FLOW-JA-FACE summed over the wall faces, per layer, stations `lake:<id>:layer<k>`).
  - `[geographic.dam_carve]` and the `slope`, `buffer_m` and `capture_*` keys of
    `[geographic.enforce_lakes]` are refused: the ramp, the outlet notch and the stream capture
    moved neither the basin, the network nor the drains once the cell drainage D crosses the
    lakes. The lake polygons stay for the crossing notch and the bed regularisation. On the
    Chèze grid the lake stage moves by 1e-5 m and the run budget is unchanged.
  - Calibration: `reject_water_budget_above` defaults to 1.0 % and reads the worst time step of
    the whole-model volume budget, the figure the run checks report, not the lake package. A
    rejected trial is neither ranked nor promoted. A steady phase that fits a lake parameter of
    a model with a lake is refused (its objective is flat). MF6 names are lower case, so flopy
    writes the MVR of a simulation named with capitals, and the steady start reads the listing
    under the name MF6 wrote.
  - `catch_def = "txt"` is refused. A basin past the float32 range of ln(accumulation) is
    delineated. The Hub'Eau gauge area guard runs on the gauge of the run. The crossings box of
    a polygon basin is its bounds plus its buffer, and the bed fit is windowed on the domain
    (8.3 s to 2.0 s on the Chèze grid).
  - The Voronoi engine (2.2.0) closes lake shores: rivers are cut at the lakes, the shore is
    smoothed to the largest shore cell, a shore does not yield to a river, and a cell covered
    for most of its area outside its region goes to the lake. On the Chèze, shore coverage goes
    from 0.54 to 1.0 and the lake footprint over its polygon from 1.88 to 0.96.
  - Each lake of a model without SFR takes the runoff of the ground it drains (D8 areas, not an
    equal share). With `route_drainage = false` the discharge series is the routed series plus
    the basin DRAIN, for calibration and for the published series alike.
  - `route_drainage = false` under a lake in soil mode is refused. A well the solver throttles
    is sealed with the run as the non-fatal validity `wells_pumped` (the report written on
    2026-10-15 never read the budget file). The first-year spin-up message says 52 weeks.
  - An MF6 input error at the API `initialize` raises `SolverInputError` with the end of
    `mfsim.stdout` instead of ending Python (the check runs in a child interpreter first).
  - `hmp doctor --fix-config` migrates `[workspace] project_root`, `if_exists = "replace"`,
    `display.output_dir` and `calibration.rerun_best_with_outputs`; `[site]` stays to write by
    hand.
- `hmp calibrate` names the metric its best cost is, `cost: 0.1234 (1 - nse_log)`, as the phase
  recap of `hmp run` already did (2026-10-20). A bare `cost: 0.12` on an efficiency read as a
  poor score where it is `1 - NSE`.
- A calibration output refuses what nothing reads (2026-10-20). Beside `observes`, a `reducer`
  other than `"none"` is refused: the record is paired with the series step by step and the
  reduced value was overwritten, so `none`, `mean` and `sum` gave the same cost. A list of dates
  in `time` is refused on point, boundary, cell and lake outputs: it was documented as
  selecting steps and read as `"all"`.
- The bounds of a `mode = "scale"` parameter are factors, no longer faced with the physical
  range of the property (2026-10-20). `Sy` scaled by `[0.5, 2]` was refused, "upper bound 2.0
  outside [0.0001, 0.5]", by the load, the name resolution and `hmp config check` alike. The
  product the run writes is still faced with that range.
- `method = "da_mh_gp"` no longer hangs under `parallel > 1` or `batch_size > 1` (2026-10-20).
  The chain proposes its next point only once the previous one is told, and the engine asked
  for several in one batch: the second waited forever. It now returns one point per batch and
  declares `supports_parallel = False`, so `hmp config check` says a parallel setting buys
  nothing.
- `method = "grid"` publishes its counted budget, the product of `points_per_dim`, so
  `max_iter = "auto"` visits every point (2026-10-20). It took the 100 trials of an engine that
  cannot count: a 5 x 5 x 5 grid was cut at 100 points, the last value of the first parameter
  never visited, and the session still reported a converged search. An explicit `max_iter`
  below the grid still truncates it.
- `scatter_one_to_one` and `hydrograph_log_nse` print the scores the run recorded on
  `[metrics] window`, with that window and its sample count, read from the seal or, before it,
  from the facts of the run's store (`hydromodpy.results.run.sealed.metrics_of`) (2026-10-20).
  The scatter computed its own NSE, RMSE and BIAS on every pair sharing a timestamp, spin-up
  included; it now pairs as the run's score does and draws in gray the pairs that score left
  out. The `scoring_window` and `nse_log` options of `hydrograph_log_nse` are removed: typed
  beside the figure, they could disagree with the score the run is ranked on. Examples 04, 19
  and 21 drop their `[display.overrides.hydrograph_log_nse]` tables.
- The best trial of a session, the one promoted and resumed from, is a trial the search read
  (2026-10-20). A speculative engine (Nelder-Mead with `parallel > 1`) solves candidates it then
  leaves unread, and `best_trial` took the minimum over them too, so the promoted run could be a
  point the search never returned. The `speculative_unused` mark is now journaled at every
  `persist_iteration_detail`, `"none"` included.
- `nse_seasonal`, `nse_delta`, `kge_delta` and `reservoir` read the dates of the series, not the
  position in the vector (2026-10-20). The pairing drops the dates where the record has no value,
  so past a gap the harmonics were fitted out of phase and an increment spanned the gap as one
  step: on four daily years with 120 days missing, `nse_seasonal` read 0.98 for 0.31 and
  `nse_delta` 0.95 for 0.48. Both routes hand the paired dates to the kernels, a NaN left in the
  vector is a gap, and month ends are placed at their own dates.
- The single-metric route (`variable` + `objective`) hands the sampling step of the aligned series
  to `nse_seasonal` and `reservoir`, as the block route does (2026-10-20). It passed none, so a
  monthly series was taken as daily: NaN on three years and a refused trial, where the block
  route scored a number. A daily series now reads a year of 365.25 days, not 365 samples.
- `distance_mean` of an empty simulated network is NaN (2026-10-20). The pair of an empty
  network rebuilds `D_so` as `D_os - L_cap`, so `(D_so + D_os) / 2` was negative and ranked the
  empty network below every real one (-1300 m for `D_os = 1200`, `L_cap = 5000`). `distance_gap`
  still reads `L_cap`.
- Example 04: `run_calibration_api_daily.toml` and `step6_soil_reservoir.toml` write
  `[metrics] window` 2016-01-01 to 2020-12-31 (2026-10-20). They ran 2015-2020 and inherited the
  2001-2002 window of `project.toml` through `base_config`, so their runs had no score.
- Under `[calibration.protocol]`, `[metrics] window` reaches the transient stage (2026-10-20). The
  protocol wrote its own default, one year past `[simulation.time].start_datetime` with no end,
  before the project defaults ran, so the stage kept it and scored past the end of
  `[metrics] window`. The protocol now writes `[metrics] window` itself, both bounds, and the
  spin-up default applies only without it. A stage sealed with the spin-up window still replays
  it. Protocol version stays 1.2: no release carried `[metrics]`.
- A flow barrier whose line runs through cell centres is barred again (2026-10-19). Along a row of
  centres, or through them on a diagonal, the line touches the centre-to-centre links at an end
  or lies along them and crosses none, so the crossing rule barred no face: an 80 m regular grid
  gave 0 faces for a 600 m line on a row of centres, 8 for the same line 1 cm off it. The line is
  now tested a millionth of a link to its left whenever a centre lies on it, which bars the faces
  on that side; other lines give the same faces as before. A trace inside one cell through its
  centre now bars the link it crosses, like the same trace beside the centre already did. The
  `regular` engine is 1.1.1: its `barriers` staircase uses the same rule.
- A run with `[flow.sinks_sources.recharge.soil]` passes `prepare_solver` again, and its frozen
  `config.toml` replays (2026-10-19). Since 91de8a43a the frozen configuration spelled out every
  default, so `recharge.values = 0.0` counted as written beside the soil section and was refused,
  on the run and on `hmp catalog rerun`. The frozen document now keeps what the run was given
  (`core/config_kit/written.py`, `to_toml(written_only=True)`): the fields a file, a caller or the
  run set, the fields a validator derived (`step_unit` from `"7 days"`), a value set under a
  section the file never wrote, and the tag of each union member. Chosen over comparing to the
  default inside the validators because `model_fields_set` also decides values, not only
  refusals: in soil mode the ETP `surface_offset` is read only when the file wrote it, and a copy
  that spells out every default replays a soil run with the EVT surface 2 m below the drains
  instead of on them, under the same run hash. A default is no longer frozen: a rerun under a
  version whose defaults moved takes the new ones, and the run hash, still taken on every default,
  tells the two runs apart. On the 81 loadable example and Flume configurations, the frozen copy
  validates back into the same values.
- A lake cutoff wall lies on the lake shore (2026-10-19): no cell is left between the reservoir
  and the wall. On the synthetic catchment, trace 12 m off the dam shore, the non-lake cells on the
  lake side of the HFB faces of the shore section went from 19 (triangle) and 17 (voronoi) to 0,
  and every such face touches a lake cell (one cell size left out at each corner of the section).
  The choices:
  - Geometry before the mesh: `snap_wall_to_shore` (`physics/flow/cutoff_wall_shore.py`, pure
    shapely) runs right after the trace is resolved, explicit or `auto`. The shore section is the
    lake outline nearest to the trace points within `snap_tolerance` and seen within 45 degrees of
    the trace normal, so it stops at the corners of the dam shore instead of folding back along a
    bank. Its ends join their feet on the trace; the wings beyond are kept as declared. A trace
    that crosses the lake cuts the footprint, the largest piece stays the lake and the dropped area
    is logged. A trace farther than `snap_tolerance` (new field of `CutoffWallConfig`, default
    50 m), or facing no shore, is refused naming the lake and the gap. The payload carries the
    wall (`cutoff_wall_line`, lake on its left), its shore section, the declared trace (its
    vertices keep the depths) and the cut footprint, which the mesh step reads for the lake ring
    and the dam refinement. Without a bound footprint the trace stays as declared, with a warning.
  - HFB faces (`spatial/mesh/ops/flow_barrier.py:cutoff_wall_faces`): every face between a lake
    cell and a cell across the wall (the staircase on `regular`, the shore faces on `triangle` and
    `voronoi`), plus the faces the wall line crosses: the wings, the joints and the corners where
    the cells round the shore (without them `voronoi` leaked at the corners). A face between two
    lake cells is never barred. HFB rows still go only where both cells are active (9a53b1dbd), so
    a lake face is barred below the bed and sealed by LAK in the lake layers.
  - LAK seal and drop: the HORIZONTAL connections are cut across exactly the faces the HFB bars,
    and the lake cells dropped are those across the wall within its span, the side read at the
    nearest point of the wall. The infinite chord through the trace ends is gone
    (`_wall_endpoints`, `_cell_behind_wall`).
  - Gate (`check_cutoff_wall_seal`, after the HFB in `build.py`): per lake with a wall, no
    lake-side cell is reached from downstream along the wall, no LAK bank connection reaches a
    cell across it, every lake face across it has its HFB rows, and no wall face of the shore
    section leaves a non-lake cell on the lake side; otherwise `SolverInputError` names the lake
    and the counts.
- Mesh zone labels (2026-10-19): the `voronoi` engine (2.0.1) no longer leaves every cell at
  zone `-1` when a river makes a geology contact yield its pair; the groups are cut at the
  cells the yielded segment crosses and at the edges it touches, so only those mixed cells stay
  `-1` (synthetic catchment: 103 to 2388 of 2390 cells named). The `regular` engine (1.0.1) nodes
  a contact clipped to the domain into the domain boundary, so the contact splits the domain:
  its staircase faces exist and no cell takes the zone of the other side. `K` was right before
  (area fractions); `face_zone` of the run and the `geology` face family were not.
- Outputs and orchestration, real user tour of 2026-10-16 (129 commands of the documented path run
  from an empty home; the defects it found):
  - The seal no longer records a product of the run scratch (`_preprocessing/`) as an input, so
    `hmp publish --with inputs` and `hmp replay` work for a run that loaded the hydrographic
    network; a declared folder input is copied whole under `inputs/<sha256>/`; the replay points
    the inputs of `[[data.*.sources]]` lists too, refuses by name an input that `inputs/` does not
    hold, and `hmp replay` prints the full command with `-w <project>`; the `--frozen` pre-check of
    `hmp run` that refused every custom input is gone (the rule lives in the replay payload).
  - The directory digest of the identity hash leaves out the provenance sidecars a load writes next
    to a file, so `hmp.run(cfg)` and `hmp run` on an unchanged configuration return the sealed run
    instead of computing a `.v2`.
  - `mesh_engine` of the index comes from the seal (schema 4, rebuilt by `hmp catalog reindex`);
    `hmp catalog import` builds the missing index; `hmp catalog show --format json` writes `null`
    for a missing score; `summary/by_case` and `by_site` carry every parameter of the seal under
    its own name and the overrides of the recipe; `by_site` carries `best_reason`, and
    `Project.best()` and `hmp catalog ls --best` say why a site has no best run (on stderr for a
    machine format); `hmp project show .` reads the project of the current directory; a campaign
    copy written by `hmp publish .` carries a root `PUBLICATION.json` of kind `project` listing its
    members, `hmp publish --verify` checks them one by one and names a missing one, and
    `hmp catalog import` refuses a project copy by name; the complete `hmp config template` passes
    `hmp config check` up to the catchment it cannot invent (a field with a default factory is
    written with its value, a required field of a disabled section is written commented).
  - `HMP_SET_<key>` keeps the case of the key (`HMP_SET_flow__param__K__field__value`); a window
    that stops before `setup_process` says that no run directory is written; `hmp config template`
    writes no `[sites]` unless asked; a reference answered by a missing index names `-w`; the SLURM
    scripts call `"$HMP_PYTHON" -m hydromodpy`, never a bare `hmp`.
- Outputs and orchestration, closing pass of 2026-10-16 (adverse review of the whole campaign, seven
  high findings, all fixed):
  - A run name that already carries `.vN` (`--case a.v2`, `[simulation] name = "a.v2"`) no longer
    bypasses the trash and the tombstones: `[simulation] name` refuses a version suffix by name, a
    versioned reference on the command line is accepted only for a live version (`--resume a.v2`
    resumes it in place), and a held name is never given again.
  - A dead calibration worker of a `[sites]` campaign closes its session as well as its outcome
    (`failed`, exit code and signal), so `hmp project status` reads `failed` and the case is relaunched;
    a relaunched calibration reopens its session (`--resume`) when the session recorded the plan's
    hash, and `--fresh` opens `sessions/<case>.v2`; `hmp run` accepts a bare `--resume` on a
    calibration file.
  - The solve budget of a launch counts the width of a calibration case (the widest `[calibration]
    parallel` of its phases): a case wider than `[sites.run] parallel`, than the measured ceiling or
    than the cores is refused without `--force`.
  - `hmp project plan` refuses to rewrite the plan while a calibration session is `running`, as it
    already did for a run.
  - `hmp publish` never copies `summary/published.jsonl`; `_refuse_leaks` scans `.jsonl`, `.csv`,
    `.tsv`, `.toml`, `.md`, `.html`, `.txt` and `.json`; CSV and TSV cells go through `redact()`; a
    Parquet column that holds an absolute path refuses the publication by file and column;
    `summary/by_case` and `by_site` write paths relative to the project root; `hmp publish .` stages
    every run and the summary together and moves them at once (`publish_project`), so a refused
    member leaves nothing behind.
  - `simulation.parquet` and `parameters.parquet` of the seal carry the same footer as every other
    table of the run (`run_parquet_footer()`: identity, licence, `sim_id`, `hydromodpy_version`,
    extent); the seal resolves the projection of the catchment into `crs_wkt` and `crs_epsg`, lost
    since the writer of the index left.
  - The evaluator contract and the step-artefact characterization follow the current surface
    (`run_calibration_core` with an open session, the run journal read before the seal); the twin
    calibration benchmarks of `validation_cases/` no longer write `[workspace] project_root`, read
    the session journal instead of the index, compare projections with `pyproj` and read the trial
    `params` column.
  - The local CI doctest list no longer names `core/state/global_index.py`; `hmp workspace clean
    --scratch` aims at the project scratch folders only; the default `[sites.run] parallel` bends to
    the cores of the machine instead of being refused.
- Lake-river stack, correction of the audit of 2026-10-14 (seven lots integrated on 2026-10-15):
  - MODFLOW 6 API path: a solve that does not converge raises `SolverDivergedError`
    [HMPY.E401] like the executable path, libmf6 is finalized on every exception,
    ATS is refused under the API (C-02, API-2, API-3).
  - `[modflow6.runtime] mf6_backtracking_number` (None = preset, 0 cuts IMS
    backtracking); the E401 message names `mf6_enable_xt3d = false` when the NPF
    carries XT3D (C-03, TRI-XT3D).
  - LAK HORIZONTAL banks in marnage cover [carved lake cell top, neighbour top], never
    the carved bed; the table bottom is compared to the connection floor (warning);
    a lake connected to a CHD cell is refused; slivers below 1e-6 of the cell area
    are dropped; the implicit seal behind a cutoff wall is a WARNING with its count
    (C-01, LAK-7, CHD, BV-2, HFB-3).
  - HFB: every layer cut by the wall is barred on both cells of the link, face
    `hydchr` weighted by trace length over face chain length, `hydchr <= 0`
    refused under XT3D, open length at each end reported (HFB-1, HFB-4, HFB-5).
  - Soil + lake: per-period forcings are averaged for the steady initial
    condition; `spinup = first_year` accepted on 52 weekly periods; two lakes
    without SFR share the basin runoff once (SOL-2, SPIN, LAK-6).
  - Mesh: WARNING when a size term asks less than the DEM pixel; sill zone contour
    simplified before the buffer; DISV vertices written with 15 decimals (C-06, C-07,
    DISV-PREC).
  - SFR: the routed outflow counts lake outlets and refuses an all-zero series;
    `route_drainage` defaults to true with SFR; DRN movers to a lake are counted
    (C-08, SFR-4, BC-1).
  - Config: lake, outlet and SFR csv forcings resolve against `data/`; `runtime_reuse`
    removed and its key refused; throttled wells (AUTO_FLOW_REDUCE) reported; DRAINC
    break dated 2015-07-31 (CSV, REUSE, WEL-1, RCH-0).
  - `tests/integration/test_two_lake_voronoi_stack_e2e.py`: two lakes, Voronoi mesh,
    HFB, SFR routed drainage, WEIR + mover, real mf6 solve (TST-1).

### Added
- A GeoJSON feature without a readable CRS, or in a local frame that cannot go to WGS 84, stops the
  export with an `ExportError` that names the file,
  the feature and the CRS, and an observation without a provider CRS is listed in
  `hydromodpy_skipped_observations` (`missing_provider_crs`) (2026-10-31). A snapped-outlet GeoJSON whose
  coordinates are not longitudes and latitudes is refused with a `DataContractViolation`.
- `validate_physical_array` in `hydromodpy.core.units.physical_bounds` checks one value per cell against
  the range of a parameter (2026-10-31). It counts the values outside, not-a-number included, and names
  the first one.
- The mesh of a run opens in xugrid as it is stored (2026-10-27). `mesh/` of `fields.zarr` holds
  `node_x` and `node_y` beside `vertices`, and the topology names them in `node_coordinates`.
  `face_node_connectivity` declares `_FillValue = -1`, the coordinates carry the CF
  `standard_name`, and on a run with a CRS the group holds a copy of the root `crs`, which the
  topology and the coordinates name in `grid_mapping`. The arrays are additive, so
  `zarr_schema_version` stays at 3, and a run sealed before them reads in HydroModPy as it did.
  The NetCDF export names its coordinates the same way.
- A VTU export carries the run id, the CRS (WKT and EPSG code), the licence and the HydroModPy
  version in the `FieldData` of the grid, which ParaView and PyVista keep (2026-10-27). A text is
  stored as UTF-8 bytes, read back with `bytes(array).decode()`, because meshio refuses a file
  holding a VTK string array.
- `write_gmsh_2d_mesh` takes a `crs` and writes its WKT to `<name>.prj` next to the mesh, since a
  `.msh` file carries none, and `read_gmsh_2d_mesh` reads it back into `GmshMeshData.crs_wkt`
  (2026-10-27). `save_planar_mesh` and `GmshPlanarMesh2D.to_file` pass it on. The mesh bundle
  format states its version, `BUNDLE_SCHEMA_VERSION` (`mesh_catchment_bundle_v1`), and the columns
  of each CSV file with their unit, `BUNDLE_COLUMNS`, in `catchment_mesh_bundle_reader.py`. A test
  checks every committed bundle against them.
- Mesh refinement where the water table is shallow (2026-10-26). A `[[mesh.refinement_zone]]` table
  takes a criterion `where` in place of a vector layer `path`, with a threshold `below` or `above`
  and, for a field of an earlier run, `run`. `where = "height_above_stream"` refines the DEM pixels
  less than `below` metres above the stream they drain to (HAND, on the DEM of the mesh grid and the
  network traced from it with `[geographic.river_network]`). A mapped network never enters, and such
  a zone turns the traced network on. `where = "watertable_depth"` and `where = "seepage"` read the
  field in the `fields.zarr` of the sealed run that `run` names, at any time step. The minimum over
  time is compared to `below` and the maximum to `above`, and the seepage is the drain outflow per
  cell area in mm/d. A zone is a term of the size field, with its `cell_size` inside and a ramp at
  `max_slope` over `buffer` outside. The `regular` engine ignores the zones and the mesh QA says so.
  `MeshRequest` carries `source_runs`, the sorted `sim_id` of the runs read. It enters the hash of
  the request when it is not empty, so the existing meshes keep their hash. A table with neither or
  both of `path` and `where` is refused. On the Nançon (25 m DEM, network threshold 0.05 km2), the
  zone below 2 m covers 20 % of the catchment. A Voronoi mesh of 75 m with that zone at 25 m holds
  40 043 cells, against 14 897 at 75 m and 134 074 at 25 m (`abed303ff`).
- The outlet can snap by the Jenson rule (2026-10-26). `[geographic.catchment] snap_method` is
  `"window"` (default) or `"jenson"`. `window` moves the outlet to the cell of the largest flow
  accumulation inside the square window of width `snap_dist`, and it can jump onto a larger stream
  that lies beside the declared one. `jenson` takes the nearest cell of the stream network drawn
  from the DEM, so it stays on the nearest stream, and it refuses an outlet with no stream cell in
  its window. It needs the threshold of `[geographic.river_network]`, `threshold_area_km2` or
  `threshold_cells`. The section need not be enabled, and the load refuses a file without the
  threshold. A mapped network is never read. The terrain port `delineate` takes `snap`, `"window"`
  or `JensonSnap`, and an engine that cannot serve it raises `TerrainCapabilityError`. The
  description of `snap_dist` said a maximum distance, and it is the width of the window. The default
  and the cache fingerprint of a project at `window` do not change. On example 04 (window of 3 by 3
  cells), `window` moves the outlet by 130 m and gives 11 488 cells (64.620 km2), and `jenson` moves
  it by 36 m and gives 11 483 cells (64.592 km2). With a window of 900 m, `window` gives 64.851 km2
  and `jenson` still 64.592 km2 (`85836796d`).
- `parameter_map` and `parameter_section` draw K22, K33 and the three angles of the K tensor
  (2026-10-26): `hydraulic_conductivity_k22`, `hydraulic_conductivity_k33` and
  `conductivity_tensor_angle1` to `3`. K22 and K33 take the scale rule of K, and the conductivity
  panels of a `parameter_section` share one scale. `angle1` is in degrees on a full turn, from 0 to
  360, with the cyclic colour map `twilight` and a tick every 90 degrees. `angle2` and `angle3` are
  linear. The `cmap` of both figures defaults to `None`, which is viridis, and `twilight` for
  `angle1`. Without `variables`, `parameter_section` adds K22 and the angles when the run holds
  them, and K33 only when it differs from K. A variable that the run does not hold is refused by
  name with `FigureNotApplicable`, where `parameter_section` dropped it without a word, and so is a
  variable that is not an aquifer property, such as `head` (`8105d417f`).
- The catchment fraction (2026-10-26). A run with a delineated polygon stores
  `mesh/catchment_fraction`, the share of the area of each face inside the polygon, from 0 to 1, and
  the `mesh_cells` layer of `hmp export` carries it as `catchment_fraction`. The share is exact for
  the cells that the outline cuts. The basin of D stays all or nothing, and so do the `catchment`
  row of the budget, the discharge at the outlet and the calibration. `views.catchment_weights(run)`
  returns the shares, and `views.catchment_total(run, variable)` sums a per-cell budget term, such
  as `recharge` or `drain`, with them: the recharge and the seepage over the catchment, per time
  step. The shares also cover the cells outside the basin that the polygon touches, because weights
  limited to the basin lose the part of the polygon in the neighbouring cells. On a distorted disc
  over a grid of 75 m, a mask by cell centre misses the area by -0.03 % (standard deviation 0.13 %)
  at a radius of 3 km and by -0.06 % (0.45 %) at 1 km, and weights limited to the basin by -0.67 %
  and -2.0 %. The array is optional, so the Zarr schema stays 3, and a run sealed without it counts
  the whole cells of its basin and says so. On example 04 the grid is the DEM, so no cell is cut and
  every share is 0 or 1. The recharge over the catchment is 0.23 % below the `catchment` row and the
  seepage 1.2 % below, because the basin of D and the polygon disagree on 34 and 8 whole cells
  (`2b4ac4f0b`).
- The cell shape in the mesh QA, and a build warning (2026-10-26). `MeshQA` gains
  `bisection_offset` (quantiles over the interior faces longer than `min_face_length_m`, and
  `n_cells_gt_0_25`, the cells with a face above `BISECTION_OFFSET_WARNING`), `min_angle_deg` and
  `max_angle_deg` (quantiles over the cells of their smallest and largest corner, and
  `n_triangles_lt_20`, the triangles with a corner under `MIN_ANGLE_WARNING_DEG`) and
  `n_concave_cells` (a corner beyond 180 degrees plus `STRAIGHT_CORNER_DEG`). The mesh step logs
  one warning per threshold a mesh crosses: triangles with a corner under 20 degrees, cells with a
  face crossed more than 0.25 of its length from its middle, concave cells. A mesh is never refused
  for them. A mesh cache entry stored before keeps its schema (`hydromodpy.mesh_cache.v1`) and
  gets these entries measured on its stored mesh and centres when read, so the frozen gmsh mesh of
  a project is kept. A fourth per-cell field, `mesh_max_angle`, the largest interior angle of the
  cell, joins the computed quality fields, and the `mesh_cells` layer of `hmp export` carries it
  as `max_angle_deg`. On the stored Flume meshes the largest angle is 148 degrees at the 95th
  percentile on the v2 Voronoi and 90 on the regular grid.
- `[modflow6.runtime] mf6_reordering_method` (2026-10-26) exposes the IMS `REORDERING_METHOD`
  (`"none"`, `"rcm"` for reverse Cuthill-McKee, `"md"` for minimum degree). It reaches the flow IMS
  and the transport IMS through `optional_ims_kwargs`. The default `"none"` writes nothing, so the
  IMS file of a current project is unchanged. Measured on Voronoi DISV meshes of 14 400 to
  144 000 cells (shuffled or row-sorted numbering) and on the steady Flume v2 solve (73 400 cells),
  `rcm` and `md` added 3 to 73 per cent inner iterations and did not cut the wall time.
- Input checks on the mesh and on located points. The solver grid build now counts the groups of
  active cells that no face or vertical connection joins, and warns with their number and sizes
  when there is more than one; it never refuses the grid. A triangulation imported through
  `[mesh.triangle] path` is refused when it holds a T-junction, a vertex lying inside an edge of a
  triangle that does not hold it, and the message gives its coordinates; vertices closer than
  1e-9 of the mesh extent are reported with a warning. Locating a point on the mesh (gauges,
  piezometers, calibration outputs) no longer takes the nearest cell without bound: a point
  outside the mesh takes the nearest cell only within one cell size of it (the square root of
  its area), and farther out it gets no cell and a warning that names it. This holds on MODFLOW 6,
  MODFLOW-NWT and Boussinesq alike.
- Area-weighted forcings (2026-10-26): `interpolation_method = "area"` in
  `[flow.sinks_sources.recharge]` and `[flow.sinks_sources.etp]` puts a gridded recharge or ETP on
  the cells by weighting each pixel with the area it shares with the cell polygon, so a cell rate
  times its area is the integral of the grid over the cell and the volume over the domain equals
  the integral of the grid (to 1e-9 relative in the tests, where `nearest` misses it by 1e-4 to
  1e-2). The weights are an exact clip of each cell by each pixel its box reaches, computed once per
  source grid and reused for every period and band; a cell no finite pixel reaches takes the nearest
  pixel. MODFLOW 6, MODFLOW-NWT and Boussinesq pass their planar mesh to the one forcing path
  (`discretize_fields_on_cells(mesh=...)`). A station source refuses `"area"`, and so does the
  centre-grid interpolation of `spatial_interpolation`. The default stays `"nearest"`, so a run of
  a current project is unchanged.
- The mesh planner cleans the geometry first (2026-10-26). A new step,
  `spatial/mesh/planning/cleanup.py`, runs at the start of `plan_mesh_request` for every engine
  except a triangulation read from a file. At a tolerance of a tenth of the DEM pixel
  (`CLEANUP_PIXEL_SHARE`), it merges the vertices of a line or ring closer than the tolerance to
  the previous one (the ends of open lines stay), snaps the end of a river, barrier or contact that
  misses another line or ring by less than the tolerance onto it (on its nearest vertex when one
  is that close), and first cuts that end back when it ran along the other line for more than two
  tolerances. Only the domain and the families `[mesh.families]` asks for are cleaned. The drop of
  the holes smaller than one local cell squared moves into the same step. Each kind of change is
  counted in one journal line and one note of the mesh QA. What touches exactly or lies farther
  than the tolerance is left alone, so a clean input gives the same request as before.
- The cell size of the `triangle` and `voronoi` engines follows the gap between face lines
  (2026-10-26). A new module, `spatial/mesh/sizing/gap.py`, samples every face line (lake
  shores, barriers, geology contacts, catchment boundary) and the domain outline every half
  DEM pixel, on the lines simplified at a quarter pixel. At each sample the gap is the
  distance to the nearest point of another line, or of the same line when the way along it
  is more than twice as long (the two shores of a narrow lake arm, a corner sharper than 53
  degrees). Two lines that touch count the way through the place they touch, so a
  right-angle junction is not a gap; a line that lies on another, such as a catchment
  boundary equal to the domain outline, counts once; a gap outside the domain is skipped.
  The chord of the gap is sized the gap divided by the new DEV key `[mesh] gap_cells`
  (default 2, 0 switches it off), never finer than the DEM pixel, and the size grows away
  from it at `max_slope` like the other terms. The sizes are rounded down to levels a fourth
  root of 2 apart, one size term per level. Rivers stay out. A generated Voronoi mesh with
  lakes picks the shores it follows on the field without gaps, then sizes the gaps of those
  shores, so an arm the smoothing leaves out takes no cells. The request carries one note
  with the number of gaps and the finest size. The `triangle` engine moves to 1.1.0 and the
  `voronoi` engine to 2.3.0.
- Layers by surfaces (2026-10-26). `[domain.layers]` takes `genmtd_lay = "surfaces"` beside
  `constant`, `decay` and `list`: each `[[domain.layers.layer]]` table names a layer and gives
  its base with one key, `thickness` (below the base of the layer above, or below the terrain
  for the first layer), `depth` (below the terrain), `elevation`, or `surface`, the name of an
  elevation raster declared under the new `[[data.layer_base.sources]]` (`name`, `path`,
  `default_crs`). The last layer gives no base and ends on the base of `[domain.depth_model]`.
  Each layer has a `min_thickness` (0.1 m by default), and `pinch_out` says what a thinner cell
  becomes: `pass_through` (the default) turns it into a vertical pass-through cell,
  `idomain = -1`, whose thickness goes to the active cell below it, or above it at the base of
  the column; `keep_min_thickness` moves its base down, the layers below and the base of the
  aquifer with it. A base is kept between the base of the aquifer and the base of the layer
  above. The domain places every base raster on the grid of its top and refuses one that
  leaves a cell without value; the discretization samples it at the cell centres or resamples
  it to a regular grid, so both meshes read it. MODFLOW-NWT has no pass-through cell: the
  configuration load refuses `pinch_out = "pass_through"` with it, and its build refuses a grid
  that holds one. The load also refuses a base surface `[data.layer_base]` does not declare, and
  a declared base no layer reads. A run stores `vertical_layout = "surfaces"` on `mesh/`.
  Drains, constant heads and the evapotranspiration surface already read the top active cell,
  and the computational top T' stays on the columns whose top active cell is in the top layer,
  so a pinched column keeps its interfaces. RCHA and the EVTA of the soil reservoir now write a
  layer array (`IRCH`, `IEVT`) with the top active layer when the stack holds a pass-through cell,
  because MODFLOW 6 drops the flux of a pass-through top cell instead of moving it down. A stack without one
  writes the same files as before.
- A vertical profile of K on fewer than five layers is warned about at load: one layer sums the
  profile up by K at mid-column, off by -22 % to +75 % of the transmissivity at H/d = 2.5 as
  the water table moves, and five equal layers bring it near -1 %.
- Vertical contracts before v2. A run now stores the vertical geometry of every cell: the
  interfaces `mesh/z_interfaces`, shape (layer interface, face), where they used to be the column
  of cell 0, the `idomain` of the solved model `mesh/idomain` (layer, face) in int8 with 1 active,
  0 inactive and -1 vertical pass-through, and a `vertical_layout` attribute on `mesh/` that says
  how the layers were built (`column_fractions` for shares of the thickness, `surfaces` for
  the base surfaces of `[domain.layers]`). `zarr_schema_version` moves to `"3"`; a
  store of schema 2 is refused on open like any other version. MODFLOW 6, MODFLOW-NWT (from IBOUND)
  and Boussinesq write them. `idomain` is a static field served by `Run.field` and the exports,
  and `run.mesh.z_interfaces` is always one column per cell. Layers are counted from 0
  everywhere: NetCDF and VTU name a layered field `<var>_layer0`, `<var>_layer1`, and the
  constant-head refusal of both MODFLOW backends names layer, row and column from 0. The solver
  mesh holds an integer `idomain` in place of its boolean mask, a cell is active when it is above
  0, and one function gives the top active layer of each column: drains, constant-head supports,
  the computational top, the evapotranspiration surface, the closed-depression mask, the lake
  footprint, the saturated thickness of the calibration, the layered maps and the cell of a point
  all read the top active cell of the column, and a lake footprint stays closed to them. A point,
  a well or an observation without a layer goes to the top active cell of its column; the
  `layer` of a coordinate well is now optional. Constant heads are written only on active cells.
  The layer interfaces are checked once built: an active cell with its top at or below its bottom
  is refused. Results of current projects do not change.
- K tensor in MODFLOW 6 (2026-10-26). Four new flow parameters complete the
  conductivity tensor beside `K` and `Kv`: `K22`, the conductivity along the
  second axis (MODFLOW 6 takes K when it is left out), and `angle1`, `angle2`,
  `angle3` in degrees (zero when left out). `angle1` turns the first axis from east
  towards north, so a compass azimuth N30E is `angle1 = 60`; `angle2` raises that
  axis above the horizontal; `angle3` turns the tensor about it. Each is a `[flow.param.<id>]` like K, homogeneous or per zone,
  and `K22` takes a vertical profile like K. They reach the NPF package only when
  the flow sets them, so a run without them writes the same files as before. A
  non-zero `angle2` or `angle3` turns XT3D on, because MODFLOW 6 reads these two
  angles only under XT3D; a written `mf6_enable_xt3d` is still obeyed, with a
  warning. A dip or a rotation writes the three angles, the missing ones as zero,
  since MODFLOW 6 refuses ANGLE2 without ANGLE3. The load refuses `K22` or an
  angle with MODFLOW-NWT or Boussinesq, which would drop them, an angle with a
  vertical profile, and an `angle2` outside [-90, 90] degrees. `K22` is checked
  positive on every active cell like K. The run store now keeps K33 as
  `derived/hydraulic_conductivity_k33` for every MODFLOW 6 run, and
  `derived/hydraulic_conductivity_k22` and `derived/conductivity_tensor_angle1..3`
  when the flow sets them; all are fields of `Run.field`.
- Two validation cases check the K tensor against Darcy's law (2026-10-26):
  `k_tensor_rotated_plan_2d` (`angle1` of plus and minus 30 degrees, `K22 = K/10`) and
  `k_tensor_tilted_section_2d` (`angle2` of plus and minus 20 degrees, `Kv = K/10`). A long
  strip with a head at each end carries a plane head far from the ends, whose direction and
  flow follow from the tensor. Heads match to 1e-8 m and the end flows to 4e-7, and a wrong
  sign or axis fails every case. A unit test also holds the median seed offset of a graded
  `voronoi` mesh under a quarter of `max_slope`, the floor of a graded Voronoi mesh.
- Three more mesh quality fields per cell (2026-10-22), computed on read like the four before.
  `mesh_bisection_offset` measures where the line joining two cell centres crosses their face,
  from the face middle, over the face length: 0 for a bisected face, 0.5 through a face end, and
  a cell takes the largest value of its faces. `mesh_min_angle` is the smallest interior angle of
  the cell. `mesh_concavity` is the excess of the largest interior angle over 180 degrees, 0 for a
  convex cell; a corner within `STRAIGHT_CORNER_DEG` (0.1 degree) of 180 is straight. The
  `mesh_cells` layer of `hmp export` carries them as `bisection_offset`, `min_angle_deg` and
  `concavity_deg`. A run sealed before the cell-mesh layout serves the angle and the concavity
  and refuses the bisection offset, which needs the cell centres. On the stored Flume meshes the
  smallest angle is 64 degrees at the first percentile (29 at worst) on the v2 Voronoi and 21
  (9.5) on the d2 triangles, and no cell is concave. `MeshQA` is unchanged: adding them to its
  quantiles changes the schema of the mesh cache.
- A `barriers` face family in the mesh (2026-10-19): the `triangle` and `voronoi` faces follow
  each lake cutoff wall and each `[flow.sinks_sources.flow_barriers]` line exactly, wings,
  joints and free ends included; `regular` publishes the staircase of the faces the line crosses.
  Switch: `[mesh.families] barriers = "face"` (default) or `"none"`. On the reservoir of the
  cutoff-wall tests (trace 12 m off the shore, then across the lake) every family face lies on
  the wall within 1 mm, the family covers the whole wall, and no cell on the lake side is reached
  from downstream across it. The choices:
  - The shore stretch is meshed once. The planner cuts each barrier line where it runs along a
    lake ring, resamples the pieces with the stretch ends as fixed nodes, and welds the resampled
    ring vertices back in, so the stretch has the ring's vertices bit for bit
    (`planning/barrier_lines.py`). `triangle` meshes a shared edge once and gives it to both
    families; `voronoi` leaves the stretch to the lake line (one mirror pair per segment) and
    publishes its faces in both families, oriented along each line.
  - A barrier keeps its corners: a vertex turning by more than 20 degrees is a fixed node of the
    resampling, unless one of its segments is shorter than half the finest size of the field (a
    2 m fold no cell can resolve); a line already resampled keeps them through the second pass
    of `voronoi`. Each corner stretch shorter than the background size refines
    the cells within one stretch length to that length (`barrier_corner:<k>` size terms), so a
    12 m joint between the trace and the shore keeps its Berge pairs without
    `[mesh.lake_refinement]`.
  - Junctions: a wing meets the shore in a T junction of the two families; a free end gets its
    tip seed. In `voronoi` the priority is now lakes, barriers, geology, watershed boundary: a
    contact beside a barrier yields to it.
  - A barrier never yields to a river (`voronoi`): the crossing segment's pair joins the chain as
    for any face line, a barrier mirror seed in the Gabriel disk of a chain link joins the chain
    instead of yielding, and a chain seed inside a barrier ball or within half a cell of a barrier
    mirror seed goes, the river passing through the nearest barrier cell. The chain crosses the
    barrier once, through a barrier face between two chain cells (G3 holds); measured without a
    yielded segment for crossings from 90 down to 5 degrees.
  - Engine versions: `voronoi` 2.1.0, `regular` 1.1.0. `triangle` stays 1.0.0: its code is
    unchanged, and a request with barriers has another hash.
- Share a simulation with its data (2026-10-19), step 1, the package of a run:
  - One install index for an example, a published run and an exported project
    (`hydromodpy/core/payload/`): `INSTALL.toml`, schema `hydromodpy.install.v1`, refused by name
    in another version; `[[file]]` names each file by `dest`, `size` and `sha256` (the keys of
    `[[example.file]]`) plus its variable, provider, request, licence, sidecar digest and, for a
    file a provider delivered, the row of `data/cache.duckdb` that serves it; `[[station]]` is a
    registry row like `[[example.station]]`, `[[site]]` a row of the site catalog. `ExampleFile`
    and `ExampleStation` are gone: the catalog of examples uses `PayloadFile` and `PayloadStation`,
    and `hmp example add` places its files through the same planner (`plan_files`,
    `plan_stations`), which every package uses.
  - `hmp publish --with inputs` carries every file the run read, built by
    `hydromodpy.catalog.share.run_bundle` from `inputs.json` and the declared files: user station
    files, the DEM, a GeoPackage, the files Hub'Eau, SIM2 or BD Topage delivered with their
    sidecars, stored by content under `inputs/<sha256><suffix>` and `inputs/<sha256>.json`, with
    `INSTALL.toml` at the root of the copy. A declared folder is never copied whole any more: the
    station files the run read in it are, with their registry rows. `--public` with inputs refuses
    by name an input whose licence does not allow redistribution.
  - `inputs.json` names every file the run read: a series read from the data cache carries its
    file (`PointRecord.file_path`, `FieldRecord.metadata["source_path"]`), a hydrographic network
    names the files of its sources and their provider (`INPUT_FILES_KEY`) instead of the raster of
    the scratch, so BD Topage is recorded under its own licence, and a declared file no load names
    (the DEM a catchment is cut from) enters with the provider and licence of its sidecar.
  - `manifest.inputs` records each declared file relative to the workspace root
    (`data/dem/...`), its `declared_path` in the form the frozen configuration writes
    (`portable_declared_path`): no absolute path of the machine in a seal any more.
  - `hmp run <copy>/config.toml --frozen` reads the install index: a declared folder is rebuilt
    under `<project>/.hmp/replay/<copy>/` from the files of the index in it, and a file a provider
    delivered refuses the replay with the import that installs it instead.
- Share a simulation with its data, step 2, the import (`hydromodpy/catalog/install.py`):
  `hmp catalog import <copy> -w <project>` installs every file of the install index into the
  `data/` of the workspace (or the project for a project file) before the run enters `runs/`.
  Identical bytes already there cost nothing, an absent file comes with its sidecar, the same path
  with other bytes is refused by name with both sha256; station rows merge into
  `data/<variable>/<prefix>_<provider>_LOC.csv`; a file a provider delivered is registered in
  `data/cache.duckdb` with its provider and key (sidecar kept, `write_sidecar=False`), so a run
  finds it instead of fetching it again, and a station the cache serves from other bytes is
  refused; the `[site]` merges into `data/sites/catalog.csv`, a name held with another outlet or an
  outlet close to another site refused by name. Any conflict refuses the whole import and writes
  nothing. The command prints what it installed, then `hmp catalog rerun <run>` and
  `hmp catalog diff <run> <run>.v2`.
- Share a simulation with its data, step 3, the replay is identical: the frozen `config.toml`
  writes each input file in the form that resolves back to it in any copy of the workspace
  (`portable_declared_path`: a bare name found in `data/<role>/` or `data/`, a path relative to the
  project root, `../../data/...` for another file of the workspace), never a path of the machine;
  the identity hash reads every path of the workspace relative to the project root, sidecars left
  out, so two workspaces holding the same data hash a configuration alike;
  `HydroModPyConfig.from_snapshot` reads a snapshot that names its project the way its file is
  read, and `hmp catalog rerun` reads the frozen configuration from the project `-w` names, not
  from the current directory. `tests/e2e/test_share_a_run_with_its_data.py` runs step 5 of example
  04 (DEM, GeoPackage network, station series), publishes it with its inputs and results,
  imports it into an empty workspace under another HOME, reruns it and finds identical
  parameters, metrics that differ by the solve time only, and the same heads.
- Share a simulation with its data, step 4, a whole project on the same brick:
  `hmp project export <project> --to X.tar [--with runs] [--with sessions] [--with mesh]
  [--with fetched]` (`hydromodpy/results/export/project_package.py`) writes the files the author
  wrote (root TOML files, scripts, README, `sites.csv`, `site_overrides/`) and every data file the
  TOML files reference, resolved by the resolver of the example catalog, now
  `hydromodpy/core/payload/resolve.py` (`project_data`), on one `INSTALL.toml`; on demand the
  sealed runs (published with their results and the user files they read), the sessions, the
  `.hmp/mesh_cache/<key>/` entries the runs read (matched on the request hash and engine build
  their mesh records, since gmsh does not redraw the same mesh) and the files the providers
  delivered with their data cache rows. `PUBLICATION.json` of kind `project` lists every file, so
  `hmp publish --verify` checks a package. `hmp project import X.tar -w <workspace> [--as name]`
  (`hydromodpy/catalog/install.py`) installs it as `projects/<name>`, data under the rules of
  `hmp catalog import`, runs under their own names, built beside its destination and renamed into
  place; a name already taken is refused without `--as`, and `hmp catalog import` names
  `hmp project import` for a project package.
- The local launcher of a `[sites]` project (`hydromodpy/project/launch/`): `hmp run project.toml`
  takes the lease `.hmp/launcher.lease` (one `O_EXCL` file with host, pid and date, taken over when
  its process is dead or under `--force`), prepares the data once per data request with a pool of
  `prepare_parallel` (`hmp run <case> --until load_data`, the only writer of `cache.duckdb`,
  `hydromodpy.lock` written once at the end), then runs one process per case
  (`hmp run plan/<hash>/<case>.toml --frozen`) within a budget of `parallel` solves (a case at
  `[calibration] parallel = 5` counts five), journals every event in `jobs/<stamp>-local/journal.jsonl`,
  merges the private data cache of each child and indexes after every end; `--only` (status words,
  case ids, globs), `--site`, `--parallel`, `--until data`, bare `--resume`, `--fresh`, `--force`,
  `-w`; exit 23 when a case did not complete. `hmp project plan | status | log | case` read the plan,
  the outcomes and the heartbeats, never the index; `project_status()` computes `planned`,
  `invalid`, `skipped` and `stale_plan` from the plan and reads the attempt states from disk.
  `HMP_THREADS_PER_CASE` bounds the threads of a worker (`threadpoolctl` and the BLAS variables),
  `HMP_RUN_SCRATCH` and `HMP_SET_*` leave the environment of the children. Budgets measured on 22
  cores and 62 GiB (`mesures/MESURES.md`): `parallel` defaults to 8 (bent to the cores of the
  machine when the key is not written),
  refuses more than 16 without `--force`, two concurrent calibrations at most;
  `prepare_parallel` defaults to 2, 8 at most, and one case per site is prepared at a time.
- `hmp project array . --scheduler slurm` (`project/launch/slurm.py`, templates under
  `project/launch/templates/`): writes `jobs/<stamp>-slurm/{prepare.sh, array.sh, cases.txt}`
  frozen from the plan, `--signal=B:TERM@600`, `--cpus-per-task` from `threads_per_case`,
  `HMP_SCRATCH_ROOT=$SLURM_TMPDIR`, a trap that writes `failed` with the exit code, the signal, the
  log tail and `written_by = "trap"`; each task takes its `hmp run` flags from the launcher at
  start; `hmp project case <job> N` names the case of a task; `hmp project status` reads `sacct`
  when it is there and marks a task the scheduler ended without an outcome as `failed`. Never run on
  a real cluster: the scripts are checked by `bash -n`, by their content and by a stand-in `hmp`.
- `hmp project collect` (`project/summary.py`): `summary/{by_case, by_site}.{parquet,csv}`,
  `by_site.gpkg`, `catalog.csv` (`--write-sites`), cohort figures `map` and `distribution` under
  `summary/figures/` with `index.json`, `[[sites.export]]` with the vocabulary of `[[export]]` under
  `summary/exports/`, `report/index.html`, a dated `README.md` and `ro-crate-metadata.json`;
  `best = "calibrated"` by default, mixed scoring windows refused without `--mixed-windows`;
  `hmp catalog ls --by site`, `--best METRIC`, the `overrides` column; `hmp report compare --by site`.
- `hmp.open(path)` returns a `Project` (root or `project.toml`), a `Run` (sealed directory, read
  without the index), a `Session` (session directory) or a `Workspace` (workspace root);
  `Project.cases`, `.sites`, `.best(metric, by="site")`, `.runs(site=)`, `.sessions[...]`,
  `.plan()`, `.run(parallel=, only=)`, `.status()`, `.collect()`, `.publish(to=)`, `.store`
  (the reader `Catalog`); `Session.trials`, `.best`, `.phases`, `.config`, `.dir`;
  `hmp.index()` returns the `Workspace` above the current directory and `.runs(site=)` reads the
  sealed tables of every project; `Run.site`, `Run.checks`, `Run.inputs`, `Run.exports`,
  `Run.figures`. The API reference is generated from these objects.
- `hmp project promote <case> --trial N [--as NAME]`, `hmp project prune <case> --keep best`,
  `hmp project new | list | show | delete`, `hmp replay <ref> --into DIR` (a published copy and the
  command that replays it), `hmp catalog show` prints the README and the annotations of a run;
  every verb that takes a workspace offers `-w` and none falls back on `~/hydromodpy`;
  `tests/unit/cli/test_cli_surface_matches_the_target.py` lists the verbs of the target.
- The overview mode runs through the attempt protocol: `runs/<name>/` claimed, `outcome.json`,
  heartbeat, frozen `config.toml`, a `RunRecord` without solver tables (`solver = "overview"`),
  README, `.vN` on a second overview.
- `hmp run <copy>/config.toml --frozen` replays a published copy from its `inputs/<sha256><suffix>`
  (every tracked input of the seal checked by digest; a missing, tampered or API-loaded input is
  refused by name); `hmp publish --with inputs` copies the files the configuration declared;
  `tests/e2e/test_replay_from_archive_without_workspace.py` with its tolerance row.
- `[flow] restart_from` accepts the table form `{ sim_id = ..., path = ... }` (`RestartReference`);
  the frozen `config.toml` writes it. Boussinesq VI diagnostics land in
  `runs/<run>/exports/solver_diagnostics/`. A promoted run closes its attempt, carries its recipe,
  its objective, `calibrated = true` on the calibrated parameter, `converged`, `bounds_hit` and the
  window of its calibration.
- Example `19_many_catchments` (two Breton catchments from the APIs, recipes `base` and
  `calibration`, `sites.csv`, `site_overrides/`, `[sites.summary]`, `[[sites.export]]`); example 09
  listed with it as a campaign; example 04 declares `[site]` and `[metrics]`, its scripts read
  `runs/<run>/exports/` and `hmp.open(HERE).cases`, `py4_sweep_k.py` is three `hmp.run` lines;
  `tests/unit/examples/test_example_sites_projects.py`.
- Documentation: `get-started/concepts.md` on the six words of the target, the pages
  `many-catchments` and `cluster`, the glossary entries attempt, case, gauge, plan, recipe, run,
  run label, session, site, summary; the generated reference marks a `site_scoped` field as
  « varies by site »; the site selection file has its own parameter page.
- The run writes itself without the index (`hydromodpy/results/storage/`): `RunStore(run_dir)` holds
  the Zarr and Parquet writers of the former Catalog, its facts in `<run>/.hmp/checkpoints/facts.json`
  and the identity and licence in every Parquet footer; `claim_run_directory()` claims `runs/<name>`
  by one `mkdir` (`.vN` after a completed run, a stale claim reclaimed when its process is dead or
  under `--force`, a name held by the trash or a tombstone never given again, `if_exists = "fail"`
  honoured); `seal_completed()` writes the record, the tables, the README and `manifest.json` last,
  then `close_sealed_attempt()` removes `<run>/.hmp/`; a failed, aborted or partial attempt keeps its
  outcome, README and tables and never a manifest, and `Project.run(until_step=...)` reads such a
  run from its directory. The pipeline gains a 13th step, `SealStep`, journals under the run
  directory (`WorkflowJournal(run_dir)`, `ResolvedRunManifest` and the data description beside the
  checkpoints) and resumes a killed run from that journal; `project/attempt.py` drives the claim,
  the heartbeat and the outcome; `Project.execute()` is the worker verb and `Project.run()` indexes
  afterwards. `[simulation.results] keep_solver_files` keeps the solver folder under
  `runs/<run>/solver/`, outside the manifest inventory. `hmp run --fresh`, `--case`, `--force`.
- The index is derived (`hydromodpy/results/catalog/indexer.py`): `rebuild_index()` and
  `index_new_runs()` diff the run and session directories by `rel_dir`, key and mtime into a staged
  DuckDB file renamed over the open one; attempts, outcomes without a manifest (`effective_status`),
  annotations and the label of the day are indexed; `Catalog(project_root)` is a reader only;
  `hmp catalog reindex` rebuilds `.hmp/index.duckdb`, `hmp catalog status` and `hmp catalog watch`
  never open it; `read_workspace_runs()` reads several projects at once; `hmp doctor
  --cross-catalog` compares the sealed runs with the index rows.
- Names and the trash on disk (`results/catalog/registration.py`, `discovery.py`, `results/trash.py`):
  a bare name is `runs/<name>` exactly, `@last`, `@best:<metric>` and ids resolve on the index,
  `hmp catalog delete` moves to `trash/` and lists what it moves (`--now` leaves a tombstone),
  `restore`, `rename` (run and session), `gc` reads the tree (dead attempts marked aborted, old
  versions trashed, expired trash removed); `hmp catalog import <DIR|TAR>` imports a run written by
  `hmp publish`; `next_version_dirname()` names the `.vN` a dry run would take. `Run.tag`,
  `Run.note`, `hmp catalog tag` and `hmp catalog note` write `runs/<run>/annotations.json`
  (`hydromodpy/results/annotations.py`). The identity hash of a run is computed on project-relative
  paths, so two copies of one project share their `config_hash`.
- Outputs in the run (`results/exporters/request.py`, `results/export/`): a `[[export]]` request
  writes under `runs/<run>/exports/` and records `exports/index.json`, a variable the run does not
  hold is refused with what it holds, read from the run directory; figures land in
  `runs/<run>/figures/` with `figures/index.json`; every file carries the identity block of its run
  (`run_identity.py`, `ledgers.py`); `hmp publish <run|summary|project> [--format dir|tar]
  [--with results]` copies out of the tree with `PUBLICATION.json` and the redaction rules of
  `[publication]`; `hmp.export()` and `hmp.render_figure()` follow. A `Run` opened on a run
  directory reads its tables (`results/run/tables.py`), periods and time axis there, never from the
  index. The calibration report is `sessions/<session>/report/index.html`.
- Calibration sessions on disk (`hydromodpy/calibration/`, `results/session/`): the search writes
  `sessions/<case>/session.json`, `phases/<p>/session.json` and `trials.jsonl`, numbers the trials
  of a batch in the order of the optimiser, resumes from them (`hmp calibrate --resume`, `--phase`),
  promotes a trial by moving it under `runs/` with the version of its session (`pair_with`) and seals
  it with `lineage` and `calibrated_by`; `hmp report` reads a session directory; SIGTERM promotes the
  best trial then aborts. A calibration never opens the index. `lineage_of(run)` reads where a run
  comes from (facts while it runs, the seal afterwards).
- The metric rule (`results/metric_rule.py`, `results/fit_metrics.py`): `MetricRule.from_config()`
  takes `[metrics] station`, else `[site] gauge`, else the gauge deduced from the single station of
  the run, and `[metrics] window`; `fit_metrics(run_dir, rule=...)` scores a run from its own
  `timeseries.parquet` on the declared window only, writes the rows of the manifest and the headline
  NSE at the rule station (`nse_station`, `nse_variable` in `simulation.parquet` and in the index);
  the seal records the gauge the run used; `Run.metrics` and `RunSet.metrics` read the seal, named
  by metric, without a station suffix; `@best` and `metric_sense()` rank on the headline under the
  rule.
- The sites x recipes plan (`hydromodpy/config/sites/`): `expand_plan()` resolves `[sites]` and
  `[sites.recipes]` into immutable `plan/<hash>/` drafts with cell-level errors (`hmp config check`
  groups them), `bind`, `site_scoped` precedence, `--set` and `HMP_SET_*` through
  `core/toml_io/overrides.py` (a plan case refuses `HMP_SET_*`), `plan_budget()`; `hmp run
  --dry-run` prints the plan of a `[sites]` project and `hmp run project.toml` launches it
  (the local launcher above);
  `resolve_single_site()` checks a `[site]` project against the workspace site catalogue.
- The workspace site catalogue and the gauge (`hydromodpy/data/sites/`): `read_catalog`,
  `write_catalog`, `nearest_site`, `hmp site add | import | select | ls | show`; `apply_site_gauge()`
  fills the station sources from `[site] gauge` and refuses a conflicting station list;
  `gauge_of_run()` is written in the seal. Site selection runs by `hmp site select <file>`
  (`spatial/site_selection/runner.py`), its HTML report by `write_report_html`.
- `hmp report compare <run>...` (`reporting/comparison/compare.py`): a comparison over sealed runs
  (tables, figures, network metrics) written under `summary/compare/<stamp>/`, no launcher.
- Tests named by the target: `test_run_store`, `test_sealing`, `test_two_workers_one_case`,
  `test_a_failed_run_is_sealed`, `test_a_refused_claim_leaves_the_live_run_alone`,
  `test_a_deleted_name_is_never_claimed_again`, `test_a_killed_attempt_is_claimed_again`,
  `test_a_partial_run_is_read_from_its_directory`, `test_kept_solver_files_outlive_the_seal`,
  `test_reindex`, `test_internal_dir_is_reconstructible` (by `hmp catalog reindex`),
  `test_discovery`, `test_registration`, `test_a_bare_name_skips_the_trash`,
  `test_a_purge_never_guesses_between_live_and_trash`, `test_two_copies_of_a_project_hash_alike`,
  `test_identity`, `test_publish_contents`, `test_publish_redaction`,
  `test_a_run_store_exports_without_the_index`, `test_the_ledgers_replay`, `test_metric_rule`,
  `test_fit_metrics`, `test_group`, `test_the_seal_names_the_gauge_the_run_used`,
  `test_a_tie_names_the_same_trial_in_a_replay`, `test_sites_plan`, `test_sites_tables`,
  `test_single_site_against_the_catalog`, `test_toml_overrides`, `test_run_guards_a_sites_project`,
  `test_gauge_is_the_single_source`, `test_report_compare_over_runs`,
  `tests/e2e/test_a_run_never_opens_the_index.py`, `test_every_writer_targets_the_run.py`,
  `test_a_calibration_never_opens_the_index.py`, `test_a_promoted_trial_is_not_solved_again_e2e.py`.
  The unit tests of results, simulation, display, launchers, calibration and the integration and
  regression tiers write their runs through `RunStore` and seal them (`tests/_helpers/run_stores.py`,
  `sealed_runs.py`).
- `[site]`, `[sites]`, `[metrics]` and `[publication]` root sections (`hydromodpy/core/site/`,
  `hydromodpy/config/sites/models.py`, `config/metrics_config.py`, `config/publication_config.py`):
  a real catchment names its site (`name`, `label`, `gauge`, `uri`), a project of N sites declares its
  table, recipes (`[sites.recipes]`, three forms, `recipes_table`), `bind`, `[sites.run]`,
  `[sites.summary]` and `[[sites.export]]`; `[site]` and `[sites]` never coexist. `SiteRow` fixes the
  columns of the workspace site catalogue; `site_fingerprint()` is a pure function of the declaration;
  `resolve_gauge()` names a conflict between `[site] gauge` and a station key. Fields proper to one
  catchment carry `field_metadata(site_scoped=True)` (`core.config_kit.introspect.site_scoped_paths`).
- One dotted-path analyser for `--set`, `HMP_SET_*`, `bind` and inline `set`
  (`hydromodpy/core/toml_io/paths.py`: `parse`, `assign`, `lookup`, `resolve_field`), quoted keys
  accepted by the TOML error locator.
- Project layout names of the target in `core/state/paths.py` (`trash/`, `jobs/`, `plan/`, `summary/`,
  `site_overrides/`, `tombstones.txt`, `launcher.lease`, the run-internal `scratch`, `locks`,
  `checkpoints`, `data-cache.duckdb`, `HMP_SCRATCH_ROOT`) and the two forms of a relative run directory
  (`run_dir_rel`, `session_dir_rel`, `trial_dir_rel`, `parse_rel_dir`), their only declared holders.
- The sealed formats of a run and a session as single-module Pydantic models under `hydromodpy/results/`:
  `RunRecord` (the seal built in memory and written without SQL, `manifest.json` last and durable),
  `Outcome` (`outcome.json`, `effective_status` with the written precedence), `HeartbeatThread`
  (`logs/heartbeat.json` by `os.replace`), `Checks` and `Validity`, `ValidityRules` with
  `known_issues.toml` shipped in the wheel and `label_for()` (`exploratory`, `calibrated`, `evaluated`,
  `failed` derived on read), `Identity` and its applicators (Zarr attributes, Parquet metadata,
  `gpkg_metadata`, PNG metadata and footer, `<file>.meta.json`), `Ledger` (`figures/index.json`,
  `exports/index.json`), README generators with the sha256 of the manifest in the footer, `Lineage` by
  ids, `results/session/` (`session.json` v3, `phases/<p>/session.json`, `trials.jsonl` with one trial
  number per case), `plan_store` (immutable `plan/<hash>/`, `plan/current`), `Publication`
  (`PUBLICATION.json`, `published.jsonl`, one `redact()`), `MetricRule` and `score()` on a declared
  window (`nse_window_start`, `nse_window_end`, `nse_n`, `metric_rule_version`, `objective_*`). JSON
  schemas under `hydromodpy/schema/results/`. `simulation.parquet` and `parameters.parquet` schemas carry
  `site`, `case_id`, `rel_dir`, `attempt`, the flattened checks, `origin` and `calibrated`.
- `reserve_version_dirname()`: the `.vN` of a run or session is computed on disk (live, trashed and
  tombstoned versions) and claimed by one atomic `mkdir`; a deleted name is never given out again; a
  promoted run takes the version of its session (`pair_with`). `hydromodpy/results/trash.py`: the
  trash is a move to `trash/<rel_dir>@<stamp>/`, with `restore`, `gc` and `tombstones.txt`.
- `tests/unit/results/test_run_layout_contract.py` rewritten on the target layout,
  `test_internal_dir_is_reconstructible.py`, `test_a_name_is_never_reassigned.py`, `test_trash_move.py`,
  `test_heartbeat_is_atomic.py`, `test_validity_rules.py`, `test_metric_rule.py`, `test_site_fingerprint.py`.
- Mesh engines behind one port (`spatial/mesh/port.py`, `registry.py`, entry-point group
  `hydromodpy.mesh.engine`): `regular`, `triangle` and `voronoi` are built in, a third-party engine
  is reached by entry point and proven by `tests/contract/test_mesh_engine_contract.py` and
  `test_mesh_conformance_reaches_an_installed_engine.py`. One planner (`spatial/mesh/planning/`)
  turns the project into a `MeshRequest` (lines with a `cell` or `face` intent, resampled at the
  local step); the size field (`spatial/mesh/sizing/`) is a slope-bounded ramp from a distance
  transform on the DEM grid. The `triangle` engine is a new gmsh CDT driver with the lines
  embedded.
- The `voronoi` engine generates its own cell generators (engine version 2.0.0). It puts one
  generator per river vertex (cell chains), Berge mirror pairs along the face lines (geology
  contacts, lake shores, catchment boundary) so that a cell face lies on each line, generators
  on the domain boundary, then fills the rest with a seeded draw weighted by the size field and
  relaxes it with a weighted Lloyd iteration (25 iterations at most, developer key
  `[mesh.voronoi] lloyd_tolerance`). GEOS tessellates in a local frame, so Lambert-93
  magnitudes no longer reach the geometry code, and seven gates (one cell per seed, Berge balls, mirror
  faces, chain continuity, area, degenerate cells, short faces) stop an invalid mesh instead of
  warning. One request and
  one seed give one mesh, bit for bit; the engine asks for no cache. `[mesh.voronoi] seeds =
  "triangulation"`, the default when `[mesh.triangle] path` is given, takes the generators from
  that triangulation and keeps its dual, with the same faces as the former Voronoi mesh. At equal
  size parameters the generator makes about half the cells of the dual of a triangulation. Flume
  v2 size parameters: 21 655 cells instead of 36 697, neighbour pairs above a size ratio of 1.5
  from 13 % to 4.8 %, the seed-to-centroid offset p50 at 0.095 of the cell size. Flume v2
  weekly run against its gmsh reference: NSE 0.8350 to 0.8373, KGE 0.897 to 0.913, mean
  discharge -3.66 %, layer-1 heads mean absolute difference 0.475 m, seepage area -11.8 %,
  solver time 5 068 s to 2 927 s. 200 000 cells are generated in 47 s and built in 3 s.
  Examples 06 and 10 give no seeds and so change mesh: 826 to 344 cells and 303 to 144 cells.
  The cell count changes the shape of every per-cell field, so the comparison is by signature
  statistic: head p50 relative difference 5.3e-2 on 06, head mean relative difference 2.1e-2 on
  10.
- `[mesh]` section: `engine`, `cell_size`, `river_cell_size`, `river_band`, `[mesh.families]`,
  `[mesh.triangle] path` (reads an existing `.msh`), `[[mesh.refinement_zone]]`,
  `[mesh.lake_refinement]`; developer keys `seed`, `outside_factor`, `transition_distance`,
  `max_slope`, `[mesh.regular] shape`, `[mesh.triangle] algorithm`, `[mesh.voronoi] seeds`,
  `[mesh.voronoi] lloyd_tolerance`. Without `[mesh]` the grid is the DEM pixels, as before.
- Each flow adapter declares `accepted_meshes`; the configuration refuses a solver and mesh pair
  before any meshing (MODFLOW-NWT: `regular`; Boussinesq: `triangle`; MODFLOW 6: any planar
  engine).
- Engines that are not reproducible (gmsh) cache their mesh under `<project>/.hmp/mesh_cache/`,
  keyed on the request hash and the engine and gmsh versions; resume and `restart_from` read it.
- `PlanarCellMesh` (`spatial/mesh/model/`): a planar `HydroMesh` with one centre rule for every
  consumer (`centers`, `center_kind`), a required CRS, cell chains and face families, zone labels,
  the engine identity and a `MeshQA`. Its `DerivedGeometry` (areas, area centroids, edge table,
  CSR adjacency, -1 padded connectivity) is computed once and vectorised: 1.5 s for 200 000
  Voronoi cells against 10.8 s for the per-consumer functions. The engines return it; a regular
  grid (`cell_mesh_from_regular_grid`) and a Boussinesq bundle (`cell_mesh_from_bundle`) are
  read into it by an adapter.
- A characterization net freezes the triangle and Voronoi meshes before the mesh refactor
  (`tests/regression/mesh/mesh_net/`): cell count, areas and quality quantiles of the triangle
  mesh and of the Voronoi dual of its triangulation on two frozen bundles, and MF6 steady heads
  on the island with an asymmetric recharge; bands in `tests/TOLERANCES.md` rows 162 to 169.
- The patch test on skewed triangles and the piecewise-K circular island also run on a generated
  Voronoi mesh (`voronoi_generated` variant), with their own tolerances at twice the measure
  (rows 175 and 176 of `tests/TOLERANCES.md`); every existing Voronoi tolerance is unchanged,
  the triangulation-seeded variants measure as before.
- The validation page marks a solver that cannot run a case `n/a`, with the reason the test
  file declares in `NOT_APPLICABLE`; a unit gate refuses a matrix cell that is neither run nor
  declared.
- Validation variants for every solver able to run a case: MF6 Voronoi on the fourteen 1D
  strip cases; MODFLOW-NWT, MF6, triangles and Voronoi on the hillslope interception cases and
  the seepage limit; Boussinesq on the seepage limit, and with the PETSc engine on the two
  linearized drainage cases; NWT, triangles and Voronoi on Theis, Hantush, Ogata-Banks and PRT;
  LAK grid equivalence on the Voronoi dual; stress-period substepping on NWT and Boussinesq;
  grid convergence on triangles, Voronoi and Boussinesq; patch test on Voronoi and Boussinesq
  PETSc; twin calibrations on NWT, triangles, Voronoi and Boussinesq.
- `[modflow6.runtime] mf6_preconditioner_levels` and `mf6_preconditioner_drop_tolerance`
  set the fill and the drop tolerance of the IMS ILUT preconditioner; unset keeps the preset.
- Every solver reads the cell mesh through the same helpers, whatever the engine:
  `spatial/mesh/ops/family_cells.py` (cells of a side, of the river, of a label),
  `cell_location.py` (`locate_cells`), `spatial/mesh/forcing/` (gridded and station forcing on the
  cell centres), `spatial/field/zone_fractions.py`, `family_interior.py` (lake cells on
  shore faces), `line_on_chain.py` (a reach on the river chain of the mesh) and `side_offset.py`
  (the `side_center_offset_m_p50` QA of the engines).
  `tests/integration/test_one_cell_mesh_gives_every_solver_the_same_recharge_and_k.py` proves
  that MODFLOW 6, MODFLOW-NWT and Boussinesq get the same K, Sy and recharge, to the byte, from
  one mesh.
- The cell mesh is written once, before the run, under `mesh/` of the Zarr store: vertices
  (float64, the coordinates of the cell mesh; they are no longer read back from the MODFLOW 6
  grid file, which flopy rounds to nine significant digits above 1e5 m: on a Lambert project a
  vertex moved by up to 5e-3 m, and the island mesh area by 1.5 m2 in 131 650), cell rows, cell
  centres (`face_x`, `face_y`), `face_family` and `edge_family` bit fields (CF `flag_masks`),
  `face_zone`, and the UGRID edge tables (`edge_node_connectivity`, `edge_face_connectivity`,
  dimensions `edge` and `two`, fill -1). Group attributes record the engine, its version and
  seed, the CRS, the request hash, the QA and the gmsh, scipy, shapely and GEOS versions. Two
  Parquet tables, `mesh_cell_families` and `mesh_face_families`, hold the river and lake chains
  and the face families. `Run.array.dataset()` hands the stored edges to xugrid; `Run.mesh`
  gains `identity`, `crs_source`, `layout` and `layout_note`;
  `hydromodpy.results.run.mesh_families.mesh_families(run)` reads the two tables.
- Four mesh quality fields, computed on read and never stored: `mesh_cell_area`,
  `mesh_neighbour_ratio`, `mesh_center_offset`, `mesh_nonorthogonality`. A run sealed before the
  layout serves the first two and refuses the other two with the reason. `hmp.read` serves them
  like `Run.field`, one value per cell whatever `time` says.
- `mesh_engine`, derived from the stored configuration, in `list_simulations`,
  `v_simulation_summary`, `find(mesh_engine=...)` and the manifest (`geometry.mesh_engine`,
  `geometry.mesh_engine_version`). NULL for a run sealed before the `[mesh]` section. No
  migration: the index is rebuilt from `runs/`. `hmp catalog ls` prints it (`mesh=-` when NULL).
- `hmp export` writes the GeoPackage layers `mesh_cells`, `mesh_seeds` and `mesh_family_faces`
  in one file per request, in the CRS stored with the mesh. The four quality fields are
  exportable by name and left out of `variables = "all"`, since `mesh_cells` holds them as
  columns. A run sealed before the cell-mesh layout is refused with the reason.
- The MODFLOW 6 extractor checks the solved DISV grid against the stored mesh, to half the
  rounding step flopy writes, ring order and counts included; MODFLOW-NWT checks shape, ring
  pattern and vertices (1e-6 of the largest side); Boussinesq checks the cell count. A grid that
  is not the stored one raises `IncompatibleMeshError`.
- `restart_from` refuses a source store solved on another mesh and names both mesh identities.
- The characterization comparator accepts the closed list of members the cell-mesh layout adds
  (`ADDITIVE_MEMBERS`) when the older run predates that layout, and lists them in its report.

### Changed
- The demos of the six `cases/` folders left the `hydromodpy` package (2026-11-02), with no alias.
  The spatial and data demos run from `tools/cases/<part>/` (`python -m tools.cases.field.review_cases`),
  the data of the intermittency and oceanic goldens sits next to their tests, and the two calibration
  demonstrators are `validation_cases.calibration.unconfined_interface_1d.experiment` and
  `validation_cases.calibration.recession_hillslope_aquifer.experiment`. The library does not change.
- The site selection is a layer of its own: `hydromodpy.spatial.site_selection` is now
  `hydromodpy.site_selection`, with the same sub-packages and names (2026-11-01). It picks the
  catchments a study can use and reads `spatial`, which never reads it. The `terrain-delineate`
  capability keeps its identifier, version and outputs, at `hydromodpy.site_selection.hydrology`.
- `CatchmentZonesField`, the catchment zonation kept in `Domain.zones`, is imported from
  `hydromodpy.spatial.geographic.core.catchment_zones_field` instead of
  `hydromodpy.spatial.catchment_zones_field` (2026-11-01), beside the code that computes its codes.
  The lazy name `hydromodpy.spatial.CatchmentZonesField` is unchanged.
- `Subbasin` writes under `output/` of the working directory by default, created on demand, instead of
  a folder named `output\` inside the installed package (2026-11-01).
- `mesh_crs` is a required argument of `discretize_fields_on_cells` and `discretize_points_on_cells`,
  and `same_crs` also matches two CRS equal up to axis order or identified by pyproj as the same EPSG
  code (2026-11-01), so a proj4 Lambert-93 GeoTIFF without datum is no longer refused.
- An empty forcing grid or one without X and Y axes raises `ForcingGridError` (`HMPY.E201`, still a
  `ValueError`) naming the source (2026-11-01).
- A `[site_selection.territory]` in mode `admin_regions` or `admin_departments` is refused at read
  time when `country` is not `"fr"`, naming the mode and the country, instead of giving no search
  geometry (2026-11-01). The DEM request no longer falls back to the outlets for such a territory.
- The geology property demo (`hydromodpy.data.cases.geology.run_geology_property_case`) runs without
  arguments on the Brittany gallery TOML files it ships (2026-11-01). Its defaults named files that do
  not exist.
- A calibration trial refused by a `PhysicalBoundsError` on a quantity the search moves, such as a
  scaled candidate past the physical ceiling, is infeasible (2026-11-01). Its error starts with
  "infeasible", the optimizer gets the failed cost, and the consecutive-failure watch leaves it out of
  its streak. The refusal of a fixed value stays a failure the watch counts, and a search that has
  scored no point after 50 infeasible trials is stopped with a named refusal.
- The Whitebox delineation chains its tools on the rasters in memory (2026-10-31). The terrain engine
  hands the conditioned DEM, the D8 pointer and the accumulation it just wrote to its next step, the
  river network reads the corrected DEM, the pointer and the watershed once, and the watershed contour
  is burned on the clipped DEM in memory. Every product is still written once, at the same path. Its
  pixels and its live TIFF tags are the same, and `dem_direc.tif`, `dem_acc.tif` and
  `watershed_contour.tif` are 20 to 104 bytes shorter, because they no longer carry an unreferenced
  TIFF directory left behind when the CRS was rewritten.
- A gridded forcing (GeoTIFF, NetCDF or dataset) whose CRS differs from the CRS of the mesh is refused
  with a `DataContractViolation` naming the variable, the file and both CRS, since the forcing never
  reprojects a grid (2026-10-31). The MODFLOW 6, MODFLOW-NWT and Boussinesq recharge builders pass the
  mesh CRS. A grid or a mesh with no CRS, an unreadable one or a local frame is read as before.
- The coverage messages of the gridded and station forcing name the variable read ("Coverage check
  failed for etp: ...") instead of "Recharge coverage check failed" for every variable (2026-10-31).
- Every GeoJSON of a site selection, and the `outlets_snapped.geojson` of `terrain-delineate`, follows
  RFC 7946: WGS 84 longitude and latitude, no `crs` member (2026-10-31). `hydromodpy_coordinate_crs` reads
  `OGC:CRS84` and the new `hydromodpy_project_crs` names the CRS the features came from. The GeoPackage
  and GeoParquet layers keep the project CRS. GDAL rounds the coordinates of `outlets_snapped.geojson`
  to 7 decimals, about a centimetre. `hmp site import --layer` on a GeoJSON gives its sites in
  EPSG:4326, on a GeoPackage in the project CRS.
- The snapped outlet of a site is read in the CRS of its outlet, a GeoJSON as RFC 7946 lon/lat or in its
  `crs` member, and the control map draws every layer in the CRS of its DEM, else in the project CRS
  (2026-10-31).
- The catchment area is read on the geometry everywhere (2026-10-31). `compute_catchment_area_km2`
  preferred a numeric `AREA` column of the shapefile, so a polygon with a stale column gave one run two
  areas. The column is now only compared, and a gap above 1 % is a warning that names the file, both
  areas and the gap. A watershed in a geographic CRS is refused with `TerrainProductError`, as the domain
  polygons refuse it. `catchment_area_m2` loses its `area_field` argument.
- `PhysicalBoundsError` is a `ConfigValidationError` as well as a `ValueError` (2026-10-31), so a value
  out of its physical range raised outside a config load exits with the configuration code. Its message
  names where the value sits and the unit it was written in.
- Both terrain engines write `outlet.shp` and `outlet_snap.shp` with the same columns, `outlet_id`, `x`
  and `y`, the coordinates of the point each layer holds, and both create the parent folder
  (2026-10-31). The numpy engine wrote `value`, and the Whitebox snapped layer carried empty `x` and `y`.
- `Subbasin` delineates through the terrain port, with the engine the geographic run routed with
  (`geographic.terrain_engine`) and on its regional flow products (2026-10-31). It used to call the
  Whitebox backend whatever the engine, and now snaps on raw counts where the ln accumulation cannot
  order the snap window. A runtime without flow products is refused with a `TerrainProductError`.
- A `[site_selection.territory]` that names no country is France everywhere (2026-10-31). `country`
  defaults to `"fr"`, printed in the reference page, and the DEM request, the search geometry, the
  French region check and the default CRS (EPSG:2154) all read it. Before, only the DEM request took a
  missing country as France. A territory outside France writes its own code.
- The DEM table of `[site_selection]` is `SiteSelectionDemConfig`, no longer a second `DemConfig`
  beside the one of `[data]` (2026-10-31). The keys do not change, only the class name and the title
  of its exported schema.
- The re-grade of a mesh column around a carved lake bed moves from `spatial.lake_bed.carve_math` to
  `solver.modflow6.builders.lake_column_regrade`, beside its only caller `carve_lake_bed` (2026-10-31).
  The names `regrade_column_to_bed` and `regrade_column_active_top` do not change.
- The members `WhiteboxComponent` shares with the Whitebox sub-backends (`env`, `run`, `read_raster`,
  `write_raster`, `read_vector`, `write_vector`, `run_depression_tool`) and the members of
  `WhiteboxRasterBackend` they read (`env`, `verbose`, `silence_stdio`, `run_env_operation`) are public, and
  `spatial.terrain.whitebox_engine.read_point` is public (2026-10-28).
- The vertical profile of a field parameter, with its `SUPPORTED_VERTICAL_PROFILE_*` constants, moves from
  `spatial.field.field_param` to `spatial.field.vertical_profile`. `FieldParam` keeps `vertical_factor` and
  `has_vertical_variation` (2026-10-28).
- `build_site_selection_from_point_records` and `build_site_selection_from_generated_network` take a
  required `reference_network_fetcher`, and `load_reference_network_for_outlets` a required `fetcher`,
  called as `fetcher(bbox_wgs84, page_size=...)` instead of an optional one called with a
  `HydrographySourceConfig`. The BD Topage one is `hydromodpy.data.sites.importers.fetch_bdtopage_reference_network`,
  so `spatial` no longer imports `data` and the `spatial -> data` tolerance of the layer matrix is gone (2026-10-28).
- The site-selection candidate generators (`generate_network_candidate_outlets`,
  `generate_dem_area_light_candidate_outlets`, `ensure_raw_accumulation_cells`,
  `build_generated_network_candidates`, `build_dem_area_light_candidates`) take a `FlowProducts` instead of a
  `SiteSelectionFlowProducts`, and a `raw_accumulation_builder` receives a `FlowProducts` (2026-10-28).
- The `terrain-delineate` worker helpers `dem_extent_of`, `terrain_inputset` and
  `refuse_an_engine_this_installation_does_not_serve` are public (2026-10-28).
- A `[geographic.catchment]` table with `catch_def = "txt"` and `dem_resolution` is refused with the
  message that `txt` is not implemented, instead of a message about the grid said twice (2026-10-28).
- `derive_catchment_domain` and `buffer_distance_m` called by hand with a percentage `buff_area` of zero
  or less raise `the area increase must be > 0.` instead of `buff_area percentage must be > 0` (2026-10-28).
- `geographic_cache_fingerprint`, `required_geographic_cache_artifacts` and `GeographicProducts` of
  `spatial.geographic.geographic_cache`, `CatchmentDelineation.buffer_label` and `build_case_specs` of the
  reference catchment case are public, their underscore names are gone (2026-10-28).
- `spatial.geographic.core.ground_bed.domain_bounds` is public, it was `_domain_bounds` (2026-10-28).
- The helpers one module of `spatial` or `workflow.site_selection` imports from a sibling module are
  public (2026-10-28), such as `domain.active_cells.active_cell_mask`,
  `domain.domain_document.ResolvedDomainRequest` and `build_domain_document`, the cache readers and
  writers of `geographic.geographic_cache`, the evidence readers of `site_selection.evidence.geology_layers`
  and the path helpers of `workflow.site_selection.config_paths`. Their bodies do not change.
- The two regenerators of the spatial cases moved to `tools/spatial/`:
  `update_geographic_goldens.py` and `build_reduced_geology_inputs.py`, the old
  `domain/cases/build_reduced_inputs.py` (2026-10-28). The synthetic case is
  `run_geographic_synthetic_case.py`, and the two case TOMLs no script read are removed, since their
  neighbour holds the same tables. The `cases/` packages no longer re-export.
- The site selection runner moved from `spatial.site_selection` to `workflow.site_selection`, since
  it collects data before the spatial selection runs (2026-10-28). `runner` is `selection_run`, with
  the plan in `selection_plan`, the TOML builders in `build_from_toml`, the CSV selection in
  `catchments_csv`, the loaders in `data_loading` and the DEM request in `dem_request`.
- `spatial.administrative` no longer re-exports `france`, whose functions are imported from
  `spatial.administrative.france` (2026-10-28).
- The site selection modules each hold one thing (2026-10-28). `config.models` is cut into
  `site_selection_config`, `value_types`, `strategy_config`, `dem_config`, `outlets_config` and
  `criteria_config`, and the `$id` of the JSON schema of `SiteSelectionConfig` and of its
  `DemConfig` follows the new module. `CandidateOutlet`, `DelineatedCatchment`, `station_influence`,
  `refs` and `watershed` sit in `site_selection.domain`, `reference_network` in `hydrology`, the
  writers of evidence, decisions and generated candidates in `outputs` (`evidence_files`,
  `decision_files`, `candidate_files`), and the piezometer layers in `evidence.piezometer_layers`.
  `evidence.context` is `evidence.geology_layers`, `domain.observations` is
  `domain.observation_evidence`, `decisions.evidence` is `decisions.evidence_records`, and
  `hydrology.pipeline`, `outputs.artifacts` and `outputs.pipeline` join `hydrology.delineation`,
  `outputs.manifest` and `outputs.writer`. The packages `site_selection`, `config`, `decisions` and
  `evaluation.criteria` no longer re-export. Five helpers of candidate generation and evidence lose
  their leading underscore.
- `abacus_sim` and `reconcile` of `spatial.lake_bed` are one module, `lake_bed.abacus`, and
  `reconstruct_lake_bed` moved to `lake_bed.regrid` (2026-10-28). The package no longer re-exports
  them.
- The geographic modules are cut one per job (2026-10-28). Each table of `geographic_config` has its
  own file (`catchment_config`, `river_network_config`, `enforce_lakes_config`, `crossings_config`,
  `capped_breach_config`, `bed_regularization_config`), `synthetic.config` is
  `geographic.synthetic_config` and `synthetic.synthetic_geographic` is `synthetic.catchment`. The
  cache leaves `pipeline` for `geographic_cache`, which takes `artifacts`, and the cleanup leaves
  `store_ingestion` for `preprocessing_cleanup`. In `geographic.core`, the notch leaves
  `ground_corrections` for `crossing_notch`, `bed_regularization_raster` is `ground_bed` with its
  fit in `channel_bed_fit`, `lake_enforcement` is `ground_inputs`, the vector side of
  `river_network` is `river_network_vector`, the metric measures of `hydrographic_network` are
  `metric_crs`, and `catchment_from_polygon` and `catchment_metrics` join `catchment_from_point` and
  `catchment_domain`. `geographic_io` is gone: the backend lookup is in `delineation.registry` and
  the shapefile writer in `catchment_from_point`. `regional_flow_copy` joins `regional_flow_job`.
  `build_river_mesh_trace_from_network_gdf` loses its leading underscore.
- `spatial.delineation` keeps `get_whitebox_backend`, `clear_whitebox_backend_cache` and its lazy
  backend names, and no longer re-exports `available_backends`, `get_backend` and
  `register_backend`, imported from `delineation.registry` (2026-10-28). The Whitebox depression
  child is `depression_child.py`, and the part the sub-backends share is
  `whitebox_workflows_backend.component`.
- `spatial.domain` no longer re-exports its classes, which are imported from their module
  (2026-10-28). `zone_arming` joins `domain.build`, the four support fields of `spatial_support`
  move to `domain.support_fields`, and the active-cell mask and the document of the domain worker
  move to `domain.active_cells` and `domain.domain_document`.
- The field package is flat (2026-10-28). `spatial.field.core` and `spatial.field.geology` are gone
  and their modules sit in `spatial.field`, where `field_param_config` takes the two private
  resolution modules, `field_spatial` the weighted discretization and `geology_field` the geology
  mesh. `physical_bounds` moved to `core.units`, `geology_config` to `spatial.field`, and the field
  and the mesh of the unit square left `cases/` as `spatial.field.two_zone_field` and
  `spatial.field.unit_square_mesh`. Names are unchanged and the lazy names of `spatial.field` still
  work. `load_values_mapping_csv` and `resolve_relative_to` lose their leading underscore.
- The `area` interpolation of a forcing called from Python without the polygons of the cells is
  refused with one message, which asks for the planar mesh of the cells (2026-10-28). Two texts
  said the same thing before. No TOML reaches this refusal.
- The heads view of a mapped stream network skips a part that is not a line, such as a polygon,
  where it stopped on `NotImplementedError` (2026-10-28).
- `read_raster_data_and_meta` moved from `spatial.geographic.geographic_io` to
  `spatial.geographic.store_ingestion`, which reads the run rasters through it (2026-10-28). It
  returns the affine transform the store takes, and `None` when neither the backend cache nor the
  disk holds the raster. A raster read from the backend cache no longer comes back with the sign
  of its pixel height flipped.
- The lake bed read from a bathymetry raster no longer counts a pixel whose centre lies exactly on
  a cell edge in the cell to its east or north (2026-10-28). Such a pixel now counts for no cell,
  as `shapely.contains_xy` replaces a hand-written ray cast. With pixel centres on the edges a
  cell bed can move by half a pixel of slope (12.5 m on a 25 m ramp in the test). The identity
  harness of the clean-up sees no change.
- A `HydroMesh` holds its cells one way (2026-10-28). Each `CellBlock` keeps one `(n_cells, k)`
  int table, and a polygon block (a Voronoi mesh) pads the rows of its smaller cells with `-1`,
  where it held one node array per cell. A polygon block still takes one node array per cell and
  pads it, and refuses a row with a free slot before a node. `flat_connectivity` is always one
  table, blocks of two widths padded to the widest. A script that walks the rows of a polygon mesh
  drops the `-1` slots (`row[row >= 0]`). `cell_data["disv_cell_center"]`, which copied
  `PlanarCellMesh.centers`, goes: the Voronoi engines and `voronoi_planar_mesh` no longer write it,
  and `HydroMesh.cell_centroids()` gives the mean of the cell vertices. `connection_nonorthogonality_deg`
  and `nonorthogonality_summary` take the cell centres as `centers`, the vertex means when left
  out. The meshes, the QA, the VTU export and the store are unchanged, and a new cache entry of a
  Voronoi mesh holds the same arrays less `cell_data/disv_cell_center`. A mesh cached before keeps
  that entry, which nothing reads.
- The DISV export and the XT3D advice read the Voronoi generators from the cell mesh (2026-10-28),
  since a `HydroMesh` no longer carries them. `to_flopy_disv_args` takes the cell centres to write
  as `centers`, the vertex means when left out, and `SolverMesh.to_disv_kwargs` passes
  `SolverMesh.generator_centers`, the centres of a mesh centred on its generators and `None`
  otherwise. The XT3D advice measures its angles from the same centres. The DISV file and the
  advice are unchanged. The solver mesh helpers of the tests and of the validation cases take the
  generators of a hand-built Voronoi mesh as `centers`.
- Boussinesq reads its arrays from the cell mesh (2026-10-28). `BoussinesqMesh.from_cell_mesh`
  takes the cells, edges, areas and lengths of `cell_mesh.geometry` in a few vector operations,
  instead of building a `CatchmentMeshBundle` node by node and reading it back. The arrays are the
  same to the bit, the edge order and the error messages too, except a conductivity or a storage
  of the wrong size, which now says "Boussinesq cell values must contain exactly one value per
  cell". A quadrilateral or Voronoi mesh is
  refused by the message on triangular cells, where a Voronoi mesh raised `AttributeError`. The
  bundle folder of the validation cases keeps its path, `BoussinesqMesh.from_bundle`.
  `build_runtime_bundle_from_cell_mesh` becomes `mesh_arrays_from_cell_mesh`, and
  `_mesh_geometry.py` joins `_mesh_builders.py`.
- `SolverMesh.cell_centroids()` becomes `SolverMesh.cell_centers()` (2026-10-28), because it
  returns the centres MODFLOW 6 sees, the generator seeds on a Voronoi mesh, and not the
  centroids. The network criterion of the calibration reads the new name, and its error on a mesh
  without centres names `cell_centers`. `HydroMesh` keeps `cell_centroids()`. The helpers
  `discretization_spatial.py` reads from `top_sampling.py`, and `flow_directions.py` from
  `catchment_basin.py`, become public.
- The mesh modules take names a reader guesses (2026-10-28). In `hydromodpy.spatial.mesh`,
  `model/derived_geometry.py` becomes `model/geometry.py` and `model/mesh_qa.py` becomes
  `model/quality.py`. The folder `ops/` becomes `cells/`, because each of its modules answers
  which cells or which faces: `cell_location.py` becomes `locate.py`, `family_cells.py` and
  `side_offset.py` join in `boundary.py`, `flow_barrier.py` becomes `barrier_faces.py`,
  `vector_cell_mask.py` becomes `in_polygons.py`, and `family_regions` and `components_without`
  leave `engines/face_families.py` for `cells/regions.py`, so the solver no longer imports the
  engines. In `planning/`, `cleanup.py` becomes `geometry_cleanup.py`, `geology.py`
  becomes `geology_contacts.py`, `input_mesh.py` becomes `input_triangulation.py` and
  `refinement.py` becomes `refinement_zones.py`. In `engines/`, `triangle/gmsh_cdt.py` becomes
  `triangle/gmsh_triangulation.py`, and the Voronoi engine names its modules as the two other
  engines and its config do: `generated.py` becomes `from_seeds.py`, `line_families.py`
  `families.py`, `frame.py` `local_coords.py` and `gates.py` `checks.py`. A script imports
  from the new paths, the old ones are gone. Inside the code, a few names change too. `CdtResult`
  becomes `Triangulation` and its graph `LineGraph`. A lake structure is a `LakeStructure`
  (`kind`, `name`, `geometry`, `size_m`, `buffer_m`, and the `label` the size terms keep) instead
  of a four-member tuple. The Voronoi constraints drop their jargon (`BALL_SHRINK` becomes
  `CIRCLE_SHRINK`, `SeedRole.TIP` `SeedRole.FREE_END`, `tip_seeds` `free_end_seeds`), and the
  names one module of the mesh reads from another become public. The QA keys, the store keys,
  the messages and the value `"generated"` of `[mesh.voronoi] seeds` keep their names, and nothing
  a run computes or writes changes. A logger named after a module takes the new module path.
- The mesh code checks each fault at one stage (2026-10-28). `[mesh]`, `[mesh.voronoi]`,
  `[mesh.lake_refinement]` and `[[mesh.refinement_zone]]` refuse an infinite number and name the
  key. An infinite size, band, factor or transition used to be refused later by the size field,
  without the key, and an infinite `gap_cells`, `lloyd_tolerance`, `below` or `above` was taken.
  The request refuses what no engine can mesh and no longer checks the type of its members. The
  engines trust the request: the `voronoi` engine takes the generators of the triangulation the
  request carries, the `regular` engine reads `shape` and the `triangle` engine `algorithm`
  without checking them again. `SizeTerm`, `OutsideCoarsening`, `build_size_field`,
  `RunFieldEnvelope.passing` and `GeologyLines` no longer check what `[mesh]`, the planner or the
  size field already hold, and a size term on no pixel refines nothing. A request built by hand
  with a member of the wrong type, or with options `[mesh]` would refuse, now fails in the engine
  or is taken as it is. Nothing a run computes or writes changes.
- `resolve_domain_surfaces` no longer checks the type and the shape of the domain surfaces, since
  the domain builds its substratum on the grid of its top surface (2026-10-28). It still compares
  their CRS and extent, which a planar mesh relies on.
- The descent of a solver mesh and the top sampling of the solver grid are cut along their steps
  (2026-10-28). `solver/modflow_common/mesh_descent.py` and `catchment_support.py` become
  `flow_directions.py` (D, `build_solver_mesh_descent`, `resolve_dam_foot_cells`),
  `channel_tree.py` (the river network A and its pinned receivers), `catchment_basin.py`
  (`run_basin`, the polygon support and `catchment_cell_mask`) and `descent_store.py` (the
  `.descent.npz` sidecar, `DescentRecord`, unchanged on disk). The zonal top of
  `discretization_spatial.py` moves to `solver/modflow_grid/top_sampling.py`, and
  `SolverGridContext` and `grid_reference_from_solver_mesh` move from `grid_context.py` to
  `discretization_spatial.py`. Nothing a run computes or writes changes.
- The large mesh modules are cut along their steps, and the Voronoi chain loses its relays
  (2026-10-28). The constraint seeds of the Voronoi generator become the package
  `engines/voronoi/constraints/` (`plan`, `state`, `lines`, `rivers`, `face_pairs`, which takes in
  `mirror.py`, `conflicts`, `boundary_seeds`). The dual of a read triangulation lives in one
  module, `engines/voronoi/from_triangulation.py`, which replaces `triangulation_seeds.py` and
  `dual_families.py`. The face family rows the engines share move from `engines/triangle/families.py`
  to `engines/face_families.py` (`FamilyEdges`, `EdgeLookup`, `edge_lookup`, `oriented_rows` and
  `without_repeats`, now public, `request_zone_names`, `components_without`, `box_side_edges`,
  `face_table`), and the physical groups of a read `.msh` to `engines/triangle/msh_groups.py`.
  `family_regions` moves there from the MODFLOW 6 lake builder, and it shares one component count
  with `components_without`, each keeping its own cut. `planning/plan.py` keeps the orchestration and
  hands the line families to `planning/families.py` and the size terms to `planning/size_terms.py`.
  `line_crossing_cell_mask` moves to `ops/crossed_by_lines.py`. `check_gates` reads the constraint
  plan (`plan=`) and computes the Berge balls and the mirror faces itself, `relax` takes the hard and
  protection disks that `constraint_disks(plan)` gives, and `ConstraintPlan.chains` holds `CellChain`
  directly. `BergeBalls`, `MirrorFaces`, `LloydInvariants`, `lloyd_invariants`, `ChainPlan` and the
  three extractors of `ConstraintPlan` are gone. `face_family_columns` of the regular engine calls two
  named functions. The meshes do not change, bit for bit, QA and store keys included.
- Each plane geometric fact of the mesh has one home, so a fix is made in one place (2026-10-28).
  `hydromodpy.spatial.mesh.model.derived_geometry` holds the padded cell rows (`padded_rows`), the
  shoelace area (`cell_areas`), the polygon of a cell (`cell_polygons`, which moves there from
  `ops.vector_cell_mask`), the edge joining two vertices or shared by two cells
  (`DerivedGeometry.edge_ids`, `DerivedGeometry.edge_between`), the side of the vertex box a
  boundary edge lies on (`BOX_SIDES`, `box_side_of_edges`), the rings of a polygon
  (`polygon_rings`) and the millimetre key of a vertex (`vertex_keys`, and `VERTEX_MERGE_M`, which
  moves there from the Voronoi tessellation). `connection_nonorthogonality_deg` and
  `nonorthogonality_summary` move from `ops/mesh_orthogonality.py` to `model/mesh_qa.py` and
  compute the angle of the QA, vectorised. On the 1 645 meshes the tests build, the angles move by
  1.5e-6 degree at most and the XT3D choice does not change. The angles follow the edge table, and
  a mesh with an edge shared by three cells raises `ValueError` where the edge was skipped.
  `mesh_qa.mixed_cells` gives the cells a line crosses, for the QA and the Voronoi engine.
  `FaceFamilyTable.stack` assembles a face family table, `PlanarCellMesh.with_qa` copies a mesh with
  another QA, `RasterGridSpec.transform` gives the affine transform of the DEM grid and
  `descent_sidecar_path` finds the descent the build left. `MeshRequest` and `PlanningInputs` read
  their CRS from their grid: `crs_wkt` is a property and no longer an argument, and the request
  hash does not change. The cell areas of the map figures (`face_areas`), of the Boussinesq mesh
  and of the transient network truth are taken relative to the first corner of each cell, as the
  run store takes them. They were summed in absolute coordinates, which lost up to 5e-3 m2 on a
  cell of 0.13 m2 in Lambert-93. The edge lookups of the flow barriers no longer take a boundary
  edge of the next cell for the face between the last cell and another; no build measured reached
  it. No mesh, family, QA key, store key, request hash or `engine_version` changes.
- The size rules of the lake structures move from the mesh step to
  `hydromodpy.spatial.mesh.planning.lake_structures` (2026-10-27). `lake_structures` takes the
  cutoff wall lines and the lake footprints by lake id, the declared outlet and the
  `[mesh.lake_refinement]` table, and `sill_zone` gives the zone between two lakes. The mesh step
  still reads the lake table of the run and hands these geometries over, and
  `hydraulic_feature_geometries` and `lake_structures` leave
  `hydromodpy.workflow.steps.mesh_inputs`. The structures, their order, sizes and buffers do not
  change, and no result, TOML key, schema or mesh changes.
- `hmp export` writes its VTU files through `write_vtu` of `hydromodpy.spatial.mesh.io.vtu`, the one
  VTU writer of HydroModPy, and its own converter to meshio goes (2026-10-27). The file of a regular
  or a triangle run is the same byte for byte. In the file of a Voronoi run the cells follow the
  order of the run store, so cell `i` of the file is cell `i` of the run, where they were grouped by
  node count, and a cell of three or of four nodes is a VTK polygon, where it was a triangle or a
  quad; the points, the nodes of each cell, its values and the run metadata do not change.
  `write_vtu` takes the run metadata as `field_data`, and `read_vtu_field_data` reads it back, a
  text as text and a number as a number. An empty text is left out of the `FieldData`, since meshio
  could not read a file holding one.
  `to_meshio` hands meshio 32-bit node indices when the nodes fit, as the run store keeps them. The
  family bit fields of the store are computed in `hydromodpy.results.zarr_store.mesh_layout`, where
  a script reads `cell_family_bits`, `cell_family_names`, `edge_family_bits`, `edge_family_names`,
  `face_row_edges` and `MAX_FAMILIES`; the store keys and the bits do not change.
- The exchange formats of the mesh gather in `spatial/mesh/io/`, one module per format, and depend
  on the mesh model only (2026-10-27). A script reads `write_vtu` and `read_vtu` from
  `hydromodpy.spatial.mesh.io.vtu`, `to_meshio` and `from_meshio` from
  `hydromodpy.spatial.mesh.io.meshio_bridge`, the `.msh` reader and writer (`read_gmsh_2d_mesh`,
  `write_gmsh_2d_mesh`, `GmshMeshData`, `projection_path`) from `hydromodpy.spatial.mesh.io.msh`,
  and the bundle reader, `cell_mesh_from_bundle`, `BUNDLE_COLUMNS` and `BUNDLE_SCHEMA_VERSION` from
  `hydromodpy.spatial.mesh.io.bundle`. `read_msh` and `write_msh` read a `.msh` file into a
  `HydroMesh` and write a planar one back, with its `.prj` file when a CRS is given, and
  `GmshMeshData.line_groups` holds the lines of the named physical groups, the name of a line
  coming from the `$PhysicalNames` entry of dimension 1 of its tag, so two tags of one name gather
  their lines.
  `voronoi_planar_mesh` moves to `hydromodpy.spatial.mesh.engines.voronoi.tessellation` and
  `domain_polygon_from_mesh` to `hydromodpy.spatial.mesh.planning.input_mesh`. The file of
  `[mesh.triangle] path` is read once, through `io/msh.py`, and gives the same vertices, triangles
  and edge labels on the 42 `.msh` files of the repository that it reads. Its format line is read
  first, so a binary file is refused with a `MeshRequestError` like a file of format 4. A file the
  reader refuses stops the run with a `MeshRequestError` that names the file and gives the reason
  of the reader, where some came out as a bare `ValueError`, and the message for a file without a
  `$Nodes` or `$Elements` section is the reader's. A `$Nodes` section that holds more lines than it
  announces is read as gmsh and meshio read it, with the announced count, where it was refused. No
  result, TOML key, schema or mesh changes.
- The field meshes leave the mesh package for `spatial/field/meshes/` (2026-10-27), so the mesh
  no longer imports `spatial/field`. They are removed on 2026-10-28, see Removed. In place of
  `load_planar_as_hydro_mesh` a script calls `read_msh` of `hydromodpy.spatial.mesh.io.msh`, and in place
  of `save_hydro_mesh_vtu` and `load_hydro_mesh_vtu` it calls `write_vtu` and `read_vtu` of
  `hydromodpy.spatial.mesh.io.vtu`, since these three go (see Removed). No result, TOML key, schema
  or mesh changes.
- The free ends of a mapped stream network leave the mesh package for `spatial/geographic/`
  (2026-10-27). A script reads `network_head_candidates` from
  `hydromodpy.spatial.geographic.core.network_heads`, and `line_parts`, the split of a map into its
  lines that the crossing rule of `spatial/mesh/ops/vector_cell_mask.py` also reads, is public
  there. The window helpers `maximize_figure_window` and `maximize_figure_windows` leave
  `spatial/mesh/plot_window_utils.py` for `hydromodpy.spatial.geographic.cases.plotting_utils`,
  which the geographic, domain and field cases read. No result, TOML key, schema or mesh changes.
- The projection of a vector layer into the frame of a mesh moves down to `core` (2026-10-27).
  `to_mesh_crs` and `require_crs`, private helpers of `spatial/mesh/ops/vector_cell_mask.py` until
  now, are public in `hydromodpy.core.io.crs`, with the `CrsLike` type of their arguments. The
  mesh overlays and the free ends of a mapped network read them there, and a missing frame is
  refused with the same message. No result, TOML key, schema or mesh changes.
- What only a MODFLOW solver reads leaves the mesh package for `solver/` (2026-10-27). A script
  reads `SolverSGridConfig` and `TopSamplingConfig` from
  `hydromodpy.solver.modflow_grid.sgrid_config`, `StructuredGridBuilder` and `StructuredGridSpec`
  from `hydromodpy.solver.modflow_grid.discretization_spatial`, and `to_flopy_disv_args` from
  `hydromodpy.solver.modflow_grid.solver_mesh`. `spatial/mesh/structured_grid/` and
  `adapters/flopy_adapter.py` go. The cells a lake owns (`polygon_overlap`, `interior_cells`,
  `family_regions`) and the faces of a cutoff wall (`downstream_of_wall`, `lake_shore_faces`,
  `cutoff_wall_faces`, `wall_leaks`) move to `solver/modflow6/builders/_lake_geometry.py`, the
  share of a reach among the cells (`LinePiece`, `chain_pieces`, `crossing_pieces`) to
  `_sfr_network.py`, and the open ends of a barrier trace (`mesh_footprint`, `trace_end_gaps`) to
  `builders/flow_barrier.py`, so `ops/family_interior.py` and `ops/line_on_chain.py` go. No
  result, TOML key, schema, mesh or MODFLOW input file changes.
- The forcing on the cells leaves the mesh package for `spatial/forcing/` (2026-10-27). A script
  reads `discretize_fields_on_cells`, `discretize_points_on_cells`, `spatial_mean_from_fields` and
  `stress_period_bounds` (which leaves `periods.py`) from `hydromodpy.spatial.forcing.cells`. The
  private modules take plain names, `sources.py`, `rasters.py`, `stations.py`, `area_weights.py`
  and `spatial_mean.py`, and `spatial_interpolation` is now `hydromodpy.spatial.forcing.interpolation`.
  `spatial/field/aggregation.py` goes, so `extract_homogeneous_series_from_fields` is now
  `spatial_mean_from_fields`. The mesh never imports the forcing. No result, TOML key, schema or
  store name changes.
- Behaviour change: a gridded forcing in an unknown format stops the run (2026-10-27). A record
  whose data is neither an xarray Dataset nor a file path, or a file whose suffix is not `.nc`,
  `.nc4`, `.netcdf`, `.tif` or `.tiff`, gave a zero forcing on every cell with a warning. It now
  raises `DataContractViolation`, which names the type or the suffix received and the formats read.
- The mesh package is flat and re-exports nothing (2026-10-27). `[mesh]` is read by
  `spatial/mesh/mesh_config.py`, and `[mesh.lake_refinement]` and `[[mesh.refinement_zone]]` by
  `spatial/mesh/refinement_config.py`. The size field, its gap terms (`gap_size.py`), the height
  above the stream and the field of an earlier run join `spatial/mesh/planning/`, `resample.py`
  moves up to `spatial/mesh/`, and `RegularGrid` with `cell_mesh_from_regular_grid` lives in
  `spatial/mesh/model/regular_grid.py`. `sample_size_field(field, xy)` is now `SizeField.sample(xy)`.
  No `__init__.py` of `spatial/mesh` re-exports a name any more, so a script imports each name from
  the module that defines it, for example `from hydromodpy.spatial.mesh.request import MeshRequest`,
  and the same holds for `planning`, `adapters`, `forcing`, `gmsh_grid`, `io` and
  `structured_grid`. `hydromodpy.HydroMesh` and the lazy names of `hydromodpy.spatial` keep
  working. `project/phases.py` switches `[geographic.river_network]` on from
  `MeshConfig.requires_river_trace`, the config having refused a missing threshold when it loaded,
  so `planning/geographic.py` goes. No mesh, TOML key, schema or store name changes.
- The main CI measures the branch coverage of `spatial/mesh` and fails under a floor that only goes
  up, 98.2 % after the mesh tests were filed by module, then 98.4 % once the dead import fallbacks
  left, then 98.5 % once the mesh package was flattened, then 99.1 % once the forcing, the solver grid and the field meshes left it (2026-10-27), then 99.15 % once each geometric fact had one home (2026-10-28), then 99.2 % once the large modules were cut (2026-10-28), then 99.25 % once each mesh fault was checked at one stage (2026-10-28). The coverage report no longer drops a whole function whose signature holds
  `...`, as in `tuple[str, ...]`. Only a stub body is excluded now. The old rule left about 1 400 lines of `spatial/mesh` out of the count.
- Catchment totals read the outline the mesh followed (2026-10-26). When a `triangle` or
  `voronoi` mesh follows the smoothed catchment outline, the catchment area fraction, the polygon
  fallback of the discharge support, the outlet search of the build and the polygon mask of the
  network criterion read that outline instead of the staircase. On the Nançon the cells cut by the
  outline go from 281 to 0. The declared outlet stays on the smoothed outline when it lies on it,
  also with `[mesh.families] rivers = "none"`. Boussinesq applies a `Project.run(properties=...)`
  override of K and Sy and refuses Kv, Ss, K22 and the angles by name.
- `mesh.cell_size` means the same for the three engines (2026-10-26): the side of the square that
  has the mean area of a cell. The `triangle` engine gave it to Gmsh as an edge length and made 2.6
  times the cells of `A / cell_size^2` on a uniform field and 3.09 times on the Flume. The adapter
  multiplies each size by a factor measured for the algorithm, 1.62 for `delaunay`, 1.58 for
  `meshadapt` and 1.52 for `frontal`, and it resamples the lines of a sized request at that edge. A
  square of 4 km at 100 m gives 1600 cells for `regular` and `voronoi` and 1652 for `triangle`. The
  engine contract checks it within 10 % for every engine, plugins included (row 182 of
  `tests/TOLERANCES.md`). A generated triangle mesh changes resolution at equal `cell_size`: it has
  2.3 to 2.6 times fewer cells (65 876 become 28 866 on the Flume v2 sizes), and the cached triangle
  meshes are rebuilt, since the engine moves to 1.2.0. With lines to follow, Gmsh adds cells around
  them, so `triangle` stays 11 % above the integral of the size field with one river and 35 % on the
  dense network of the Flume. The `regular` and `voronoi` engines, a `.msh` read and the validation
  cases, which read a file, do not change. The size of the triangle fixtures in the tests is divided
  by the factor (`50aad8403`, `85ca68f1d`).
- The planner smooths the pixel staircase of the catchment outline before meshing (2026-10-26). It
  does so for the `triangle` and `voronoi` engines, where the mesh follows the outline:
  `mesh.families.watershed_boundary = "face"`, or `geographic.domain_extent` at `"watershed"` or
  `"watershed_buff"`. Each step corner is cut at half a pixel and the line is simplified at half a
  pixel, so no point lies more than one pixel from the staircase. The end of a river, the end of a
  barrier and a vertex of a lake shore that touch the outline stay on it. A box, `regular` and a
  triangulation read from a file keep their outline. No key changes, but the request hash does, so
  the cached meshes of such a request are rebuilt. A cell that touches the outline can change side
  on a band of 0.8 pixel at most. On example 04 the outline goes from 423 to 160 vertices and the
  area moves by -0.08 %. With the catchment as the domain, the Voronoi cells with an isoperimetric
  quotient under 0.6 go from 118 to 5 out of about 7300. With the buffer as the domain, the
  `triangle` mesh goes from 27 918 to 24 002 cells and the triangles under 20 degrees from 144 to 0.
  With the catchment or a box as the domain, the `triangle` count does not change (`cc2eb8443`).
- A view that says catchment reads the catchment (2026-10-26). `views.catchment_mean` averages a
  variable over the delineated catchment, weighted by the share of each face inside the polygon and
  by its area. It was an unweighted mean over the active domain. It refuses a synthetic run and a
  run with no basin of D, and no public view averages a field over the active domain now (read
  `run.field`). On example 04 the mean depth of the water table is 10.74 m on the catchment against
  11.17 m on the domain. `drainage_density`, `cell_field_active_metrics` and the overlap and
  distance metrics of the simulated network count the active cells of the basin of D, whole, and the
  key `catchment_cell_count` is that count. A run with no stored basin of D keeps the active domain
  and logs it. On example 04 the count goes from 21 406 to 11 514 cells and the mean drainage
  density from 5.3 % to 6.2 %. The precision of the simulated cells against the reference network
  goes from 0.375 to 0.596 and the F1 from 0.447 to 0.575, because the 403 active cells outside the
  catchment no longer count as false positives. The coverage of the reference stays at 0.555.
  `saturated_fraction` and `recharge_forcing` keep the active domain, the cells with a finite top,
  and their docstrings say so. The CSV written before are not comparable (`542595c7d`, `8f061a194`,
  `92b66ffa0`).
- A synthetic domain has no catchment (2026-10-26). `catchment_outline` gives nothing for a
  synthetic geography, and the box stays the domain. The basin of D is the largest basin of the
  domain, and no `catchment` row is written in the budget. It held 12 cells of 960 on the flat
  Brutsaert case, with the warning `Watershed polygon and basin of D: 12 basin cells against 960`.
  The `_catchment` series of a MODFLOW synthetic run carry the whole domain, the discharge
  observable sums every cell with an INFO line, and the stream criterion closes on the largest basin
  of its own graph. The `_catchment` numbers of a synthetic run sealed before are not comparable
  with the new ones (`2b4ac4f0b`).
- A lake column with no active cell under the lake is refused at build (2026-10-26). The message
  names the lake, the number of columns and the first cell, and three ways out: fewer
  `occupied_layers`, a smaller `min_thickness` of the `[[domain.layers.layer]]` under the lake, or
  `pinch_out = "keep_min_thickness"`. The run passed before, with the lake resting on the base of
  the model. A carved bed on a column whose layers under the top one are all pass-through cells is
  refused too (`d0b98e761`).
- XT3D on triangle cells under Newton warns that it can cycle (2026-10-26). MODFLOW 6 scales the
  XT3D face area by the saturation of the upstream cell, but the cross term of XT3D is not zero at
  equal heads, so the discrete system can have no root. The steady Nançon on triangles stops with
  E401 after 500 outer iterations, in MODFLOW 6.6.3 and 6.8.1, whatever the IMS options, the
  starting heads or the size of the cells, and ghost nodes (GNC) cycle in the same way. The build
  logs a warning with two ways out. The `voronoi` engine needs no XT3D and converges on the same
  inputs in 21 outer iterations. `mf6_enable_xt3d = false` converges in 23, with heads about 0.1 m
  RMSE from XT3D. The cost wording is measured: XT3D costs from about 1.5 times the MODFLOW 6 run
  time on one layer to about 10 times on ten, and the description of `mf6_enable_xt3d` and the
  tensor warning say so (`7970fb843`).
- `hmp dev lock archive` and `hmp data archive` write `zarr_schema_version = "3"` in the lockfile of
  the archive (2026-10-26). A default of `"2"`, which the `data` layer could not read from
  `results`, was stale. `write_lockfile` and `archive_lockfile` take `zarr_schema_version` and
  `parquet_schema_version` as arguments with no default (`cf15eb392`, `14e8065a3`).
- The page of TOML changes shows a moved table as a rename (2026-10-26).
  `config_migration.MOVED_TABLES`, a list of `TableMove(old, new)`, declares
  `modflow6.sgrid.vertical` and `modflownwt.sgrid.vertical` going to `domain.layers` once, and the
  migration and the page both read it. The page lists them under Renamed with the note that they
  still load, and the dotted override of a phase goes from `modflow6.sgrid.vertical.<key>` to
  `domain.layers.<key>`. The keys that kept their name are compared from one release to the next, so
  a change of default, profile, shape or unit shows under Changed. Against 2.0.0a4, the page has two
  Renamed lines where it had two Removed and one Added, and four more Changed lines. No config
  changes (`ae94557b9`).
- The Voronoi validation tolerances are twice the measured error (2026-10-26). Of 103 lines
  remeasured on 58 tests, 41 are tightened (38 values in 15 `tolerances_modflow6_voronoi*.toml`
  files), 8 were already at twice the error, 30 stay on a numerical floor, 21 stay as twin noise and
  3 share a value with the other meshes. The Voronoi leg of the Brutsaert thin case reads its own
  new file instead of the band shared with the structured grid and NWT: 0.05 becomes 0.0406 on the
  coefficient, 0.01 becomes 1.57e-3 on the exponent and 0.04 becomes 0.033 on the late RMSE. The two
  azimuth spreads of the islands on a triangulation seed stay on a floor, because they follow the
  iteration path and moved from 5.2e-5 to 4.0e-6 m between two runs. No run result changes. A
  Voronoi validation test fails when its error passes twice the value of 2026-10-26 (`5cb6f2efc`).
- XT3D turns on by itself for a K tensor off the mesh axes (2026-10-26): a `K22` different
  from K on a cell whose `angle1` is not a multiple of 90 degrees, or on any cell of an
  unstructured mesh, beside the tilted tensor (`angle2` or `angle3`). The two-point flux drops
  the cross terms of such a tensor: around a well with `K22 = K/10` and `angle1 = 30`, the head
  error is a third of the drawdown and does not shrink when the cells are halved, while XT3D
  converges. Both cases raise a `RuntimeWarning`, also logged, that XT3D costs from about 1.5
  times the MODFLOW 6 run time on one layer to about 10 times on ten. `mf6_enable_xt3d = true`
  silences it, and `false` on such a tensor warns that the result is inconsistent. Triangles and
  a non-orthogonal mesh turn XT3D on as before.
- Boussinesq refuses a `[domain.layers]` it would ignore (2026-10-26): more than one layer in
  any mode, and the `surfaces` mode. It solves one layer and reads K and Sy at the top of the
  aquifer. A phase override under `domain.layers` is checked on load, and the old dotted
  overrides `modflow6.sgrid.vertical.*` and `modflownwt.sgrid.vertical.*` now migrate to
  `domain.layers.*` like the tables do. A sealed run still reads, with a warning.
- `hydromodpy.spatial.mesh.cartesian_grid` is `hydromodpy.spatial.mesh.structured_grid`
  (2026-10-26), with no alias, and `spatial_interpolation` moves to
  `hydromodpy.spatial.mesh.forcing`, where the forcing readers use it.
- The layering is `[domain.layers]` (2026-10-26): the split of the aquifer between the top and the
  base of `[domain.depth_model]` (`genmtd_lay`, `nlay`, `lay_decay`, `lay_proportions`, `nodata`)
  is one table that MODFLOW 6 and MODFLOW-NWT both read, so a project has one layering whatever
  solver runs it. `[modflow6.sgrid.vertical]` and `[modflownwt.sgrid.vertical]` are refused with the
  table to write instead; `sgrid` keeps only `top_sampling`. `build_spatial_discretization` takes
  the layering as `vertical_config`, and the comparison report reads `domain.layers.nlay`.
  The migration (`config_migration._move_the_layering`, run on load and by
  `hmp doctor --fix-config`) moves the old tables. When both exist it keeps the one of the flow
  solver (first solver of the first flow process, else `solver.backend`, else MODFLOW 6) and says
  for the other whether it held other values; an existing `[domain.layers]` wins over both, and the
  emptied `sgrid` and solver tables go. A run of a current project is unchanged.
- A barrier wing next to a lake shore stretch is left out when it is shorter than half the
  local cell size where it leaves the shore, and no longer half the finest size of the whole
  field (2026-10-26).
- The Lloyd relaxation of the generated `voronoi` engine stops on the root mean square of
  the free generator moves, as a share of their local size, and no longer on the largest
  move (2026-10-26). `[mesh.voronoi] lloyd_tolerance` keeps its default of 0.01 and the
  cap of 25 iterations stays. The mesh QA adds `lloyd_move_rms` to the `lloyd_*` extras and
  keeps the largest move in `lloyd_move_max`. On the Flume and on the test square the
  relaxation still reaches the cap, with a root mean square of 0.0100 and 0.0116, so these
  meshes do not change. A mesh whose moves settle earlier stops earlier. The `voronoi`
  engine moves to 2.4.0.
- Flow barriers on the barrier family faces (2026-10-19): on `triangle` and `voronoi` the HFB rows
  of a lake cutoff wall and of each `[flow.sinks_sources.flow_barriers]` line go on the faces of the
  `barriers` family that lie on the line (`spatial/mesh/ops/flow_barrier.py:barrier_edges`, a face
  midpoint within half its length of the line); the faces the line crosses only fill a stretch the
  family leaves uncovered, within one face length of it, or a mesh without the family. `regular`
  keeps its staircase. The LAK seal cuts the same faces, and `check_cutoff_wall_seal` stays green.
  On the reservoir of the cutoff-wall tests the HFB faces are the family faces, no more, no less
  (triangle 40 and 20 faces, voronoi 26 and 20, trace 12 m off the shore, then across it), all on
  the wall: the crossing-rule zigzag of the wings is gone. On a 35 degree oblique trace the
  `voronoi` wing passes 9.5 m from the bank in 15 m cells, one wing segment yields to the lake
  ring, and three crossed faces close it, with no leak.
- Every stored document carries its version (`version` or `schema` id) and a reader refuses an
  unknown one naming the version it read and what to do (`hmp catalog reindex` for the index, the
  HydroModPy version that wrote a sealed document); `hmp doctor --fix-config <file>` rewrites a
  TOML of the previous grammar in place (`config_migration.py` is the one migration kept: a
  configuration file, never stored data).
- `[sites.run] parallel`, `prepare_parallel` and `threads_per_case` carry the measured budgets in
  their descriptions; `hmp run --until data` prepares without solving; `hmp project status` after
  a failed prepare shows the case `failed`; a re-run of `hmp run project.toml` leaves a finished
  calibration alone (the session hash is compared, not the promoted run's).
- `Project` carries eighteen methods (the launch verbs of D6); `Run` stays at fifty public
  attributes and loses `summary`, `created_at`, `duration_s`, `solver_category` and `parent`
  (`Run.record` holds them); `lineage_of(run)` reads where a run comes from.
- `hmp catalog reindex`, `hmp catalog watch` and `hmp doctor --cross-catalog` take `-w`; `hmp
  workspace clean --results` moves the runs and sessions of every project to their trash (names
  stay taken); `hmp catalog watch` shows `dead` for a local attempt whose process is gone.
- The private data cache of a launched case lives under `jobs/<stamp>-local/caches/<case>.<phase>/`
  and is merged by the launcher; `cache.duckdb` retries on a WAL lock (`TransactionException`).
- The capability layer keeps its three descriptions without an invocation block.
- `Catalog(project_root)` is a reader (no `create`, no `read_only`), reached as `Project.store`; `Run.export`,
  `Run.delete`, `Run.tag`, `Run.note` work on the run directory; `Run.input_entries` is `Run.inputs`;
  `Run.metrics` has the column `metric` (was `metric_name`) and reads sealed runs only; an id that
  is no UUID is not found rather than a conversion error; `RunNotSealedError` lives in
  `hydromodpy.results.errors`.
- `hmp workspace` is `init`, `list` (a scan of the tree) and `clean`; `hmp catalog ls`, `show`,
  `delete`, `restore`, `rename`, `gc`, `import` read and move directories; `hmp doctor` has no
  `--migrate*`; `hmp viz gallery` is `hmp viz regen`; `hmp calibrate --check` is `hmp config check`;
  `hmp report catchment` has no `--with-lock` and `[pipeline] no_lock` is refused.
- `[calibration] save_runs` / `save_best_n` replace `rerun_best_with_outputs`; candidates live in
  `sessions/<case>/candidates/` (`candidates_root` refused); `hmp calibrate --resume` replaces
  `reuse_completed_phases`; `objective_block_fractions` replaces `objective_block_shares`.
- `[workspace]` keeps `root`, `catalog_path`, `data_dir` and the DEV keys; `output_root`,
  `solver_scratch_folder`, `share_folder` and `catch_name` are refused with their replacement (the
  solver scratch is `HMP_SCRATCH_ROOT`, outputs live in `runs/<run>/`, the catchment name is
  `[site] name`); `[analysis]`, `[site_selection]` and a root `[hydrometry]` are refused by name.
- The capability descriptions (`hydromodpy/schema/processes/*.json`) carry no invocation block: a
  capability is driven by `hmp data get`, the domain step of `hmp run` and `hmp site select`.
- Example 09 is a `[sites] x [sites.recipes]` project of three cases compared by `hmp report compare`;
  example 04 reads its exports under `runs/<run>/exports/` and writes its own figures under
  `summary/figures/`; example 14 carries its base configuration.
- `[workflow] mode` is optional and limited to `simulation`, `calibration` and `overview`; left unset it
  follows from the sections (`hydromodpy.workflow.dispatch.infer_workflow`, one helper for `hmp run` and
  `hmp.run`). A retired mode (`comparison`, `testbed`, `site_selection`) is refused with its replacement.
- `[workspace] project_root` is refused in a TOML file (the project root is the directory of
  `project.toml`, or of the root file of the `base_config` chain) and leaves the config hash;
  `[workspace]` is a DEV section. `if_exists` keeps `version` and `fail` only.
- `docs/source/contribute/architecture/storage-layout.rst` describes the target: one artefact in the
  directory of its producer, two state roots, the attempt protocol, the status precedence, versions
  computed on disk, the trash by move.
- `[site] name` is required when `geographic.catchment.catch_def` declares a real catchment, in the
  TOML and in the Python API; the example, validation and test configurations name their site.
- `hmp run --set` and `HMP_SET_*` go through the shared dotted-path analyser.
- `[mesh.lake_refinement] enabled` is refused: the table being present switches the refinement
  on. Both `enabled = true` and `enabled = false` raise "[mesh.lake_refinement] has no
  'enabled' key: the table being present switches the lake refinement on. Remove the key, or
  remove the table to mesh without lake refinement." A stored configuration is read as it was
  written (no stored-configuration migration): one that holds the key is refused the same way. The
  `run_identity_hash` of a run that has a `[mesh.lake_refinement]` table changes once, because
  the dump no longer holds `enabled = true`; a rerun of such a run is a new run.
- `BoussinesqMesh` always holds a cell mesh. `BoussinesqMesh.from_bundle` reads a bundle as a
  `PlanarCellMesh` through `gmsh_grid/bundle_cell_mesh.py::cell_mesh_from_bundle`; a bundle
  must declare its CRS in its metadata (the 16 committed bundles do: EPSG:2154). No measured
  difference: 495 validation metrics are bit-identical. The cell of a point lying on an edge to
  rounding follows the exact GEOS predicate of `locate_cells`.
- `spatial/domain/cases/run_domain_case.py` builds its context through the one geographic
  pipeline (`CatchmentDelineation`, or `build_synthetic_geographic` for a synthetic config).
- The three layering helpers are public in `cartesian_grid/sgrid_generation.py`
  (`coerce_vertical_config`, `layer_proportions`, `assert_bottom_below_top`); the copy in
  `solver/modflow_grid/discretization_spatial.py` is gone. The arithmetic is unchanged.
- Spatial forcings (heterogeneous recharge) on a Boussinesq bundle are sampled at the cell
  centres of `nodes.csv` rather than of the bundle's `mesh_2d.msh` (vertex means differ by at
  most 5e-6 m; the 495 validation metrics are bit-identical).
- The `viewer3d` extra (`pyvista`) is removed: the only reader, the interactive 3D viewer, left
  with the prism stack. `hmp doctor` and `_api` no longer list `pyvista` as an optional
  dependency.
- Reading a configuration no longer imports the mesher: `import
  hydromodpy.config.hydromodpy_config` loads neither `zone_meshing` nor a launcher.
- The mesh planner drops a hole of the domain, of a lake or of the catchment whose area is
  below the square of the local cell size, for every engine, with one INFO line. A bathymetry
  polygonised from a 1 m raster no longer breaks the Voronoi tessellation. A larger hole that
  touches the outer ring or another hole at one point still stops the Voronoi engine at its
  area gate, which says so.
- MODFLOW 6: XT3D is on by default for triangle cells, and an explicit `mf6_enable_xt3d` wins
  with a warning; other cells follow the non-orthogonality rule as before. On a `voronoi` mesh,
  the top of a river-chain cell whose centre lies off the river line (a river crossing a
  contact, a cell two thalwegs share, a river end near the boundary) is the zonal minimum of
  the DEM pixels it covers, also in `centroid` mode.
- The contacts of the `generated_bands` and `generated_rings` supports are face lines for an
  engine that generates its mesh with exact faces, so no cell straddles two zones.
  `[mesh.triangle] algorithm` is no longer read by `voronoi`.
- Mesh engine contract: a deterministic engine reports `seed = None` or the seed of the request,
  and the same seed returns the same mesh. `CellChain.offset_m` carries the lateral offset of a
  chain cell to its river line and fills the `offset_m` column of `mesh_cell_families`. The mesh
  QA reports `share_gt_30` of the non-orthogonality, `mixed_cells` of each face family and
  `size_fidelity`.
- `shapely>=2.1,<3` is required (`voronoi_polygons(ordered=True)`).
- The catchment of a MODFLOW run is the basin of its descent D, computed once per build
  (`core.descent.descent_basin`) and stored as `mesh/descent_basin` with its outlet and rule: the
  budget zone `catchment`, the `_catchment` discharge and its runoff area, the discharge
  observable and its runoff area in a calibration, the drainage routing, the `catchment_mismatch`
  diagnostic of the network criterion and `Run.catchment_mask` read it. A run sealed before keeps
  its old support and says so. `Run.catchment_mask` is one boolean per mesh face, no longer the
  raster `watershed_dem > 0`. On a domain that is the catchment (`domain_extent = "watershed"`), D
  is flooded from the outlet, so the basin holds the whole domain (99.89 % before on example 04).
  Example 04: basin 64.77 km2 against the 64.62 km2 of the polygon, mean discharge +1.05 %, NSE
  0.671 to 0.680, KGE 0.670 to 0.677. Flume d2 (2019): basin 91.54 km2 against 93.26 km2 for the
  discharge observable, mean discharge +0.04 %. Heads, per-cell budgets and D do not move; the K
  and the cost of the example 12 network calibration do not either. Discharge scores and
  calibrated K from before are not comparable. Examples 03 `run_manual.py` and 10
  `generate_nwt_flux_testbed_web_report.py` read `catchment_mask` as a raster and fail on a new
  run.
- The case-by-solver matrix of the Validation page shows how far each solver lands from the
  known reference: the error as a share of a scale of the case (head range, largest drawdown,
  initial discharge), in four classes, red when the test fails, a red mark when the error grew
  by more than 20 % since the previous run. The share of the threshold moves to the case
  sections; the snapshot merge keeps each test's previous values.
- The solver builds a regular grid from the `regular` engine's cell mesh, bit for bit the grid of
  before (vertices, DIS of MODFLOW-NWT, DISV of MODFLOW 6); the flopy round trip is gone. The
  Voronoi dual is built by the `voronoi` engine, no longer inside the solver.
- Every example, fixture and validation TOML moved to `[mesh]`. Meshes generated by gmsh change
  (new driver, resampled lines, no hotspot policy, no interface refinement): examples 06, 09, 10,
  18, 20. The `nearest` resampling of the 09 and 10 overlays falls back to bilinear. Geology
  contacts are reprojected to the project CRS; a geology map without a CRS is refused.
- The solvers take a `PlanarCellMesh` (`setup.cell_mesh`) instead of a `GmshPlanarMesh2D`
  (`setup.mesh_planar` is gone). The calibration `mesh_fingerprint` now hashes the cell centres
  with the true cell count (it hashed a (2, n) tuple and counted 2 cells): calibration caches of
  gmsh runs miss once. Example 02 `run_cellular.py` still reads `setup.mesh_planar` and fails.
- Zone fractions of a cell are exact for a vector geology source (polygon areas, one function
  for all solvers); `generated_rings`, `generated_bands` and raster sources keep their sampling,
  so `cell_samples_per_axis` applies to those only. Example 06 changes: the K of 207 of its 826
  cells (the dual of a triangulation, before the Voronoi generator) moves (up to 98 %), head RMSE
  0.11 m on a 7 to 215 m range, mean K +0.6 %. In example 10 the fractions move (up to 0.89) and
  K does not (uniform). Cell areas are computed relative to the first vertex: up to 1e-5 relative
  less rounding on triangle and Voronoi meshes far from the origin.
- K, Sy and Ss reach MODFLOW 6, MODFLOW-NWT and Boussinesq through one mapping,
  `map_flow_properties` (`solver/field_property_mapping.py`). A `Kv` field is now mapped on a
  regular MODFLOW 6 grid (it was ignored and `k33 = hk / vka` used). A Boussinesq mesh bundle
  that carries K or Sy refuses a `[flow.param]` for the same property instead of overwriting it.
- Reaches (SFR), lakes (LAK) and barriers (HFB) read the cell mesh. On a mesh with river
  chains each chain cell goes to the nearest parent reach and the length is conserved by
  construction (on triangles the chain is one bank, so the reaches change: the former split
  counted 3 % extra bed on a shared edge); without chains the reach is cut at the cell edges,
  as before. On `exact_faces` triangles with a `lakes` face family a lake owns the cells its
  shore faces enclose (225 cells against 241 on the pentagon test, the same area). A well, a
  side or a stream boundary is located by the cell mesh; `[lay, row, col]` addressing of a well
  or an SFR reach is refused (exit code 14) on every engine but `regular`.
- `Run.field(bbox=)` and `to_xarray_batch(bbox=)` select cells by the centres of the run's own
  mesh. The default GeoTIFF resolution of an export is the side of the smallest cell, refused
  above 1e8 pixels. A map of a structured run is drawn from the `structured_shape` attribute of
  its stored mesh and no longer flips north and south (`origin="upper"`).
- MODFLOW-NWT defaults to `options = "MODERATE"`. Under chi-MD, the default linear solver
  since 2.0.0a5, `"COMPLEX"` runs BiCGSTAB on a level-15 incomplete factorization: on the
  ten-layer example 12 regression model it diverged at the first solve and NWT stopped on a
  core dump. `"MODERATE"` (Orthomin, level 1) converges in 60 outer iterations at most, every
  budget within 0.08 %, where the former GMRES default left -148 % and +91 % in two periods.
  The Brutsaert recession case gives the same metrics under both presets, and the NWT
  validation profile keeps `"COMPLEX"`. On the fast example 12 regression the outputs move by
  0.02 % (0.12 % on one percentile), the mean water-table depth by 0.9 mm.
- The run identity hash covers the mesh engine and its version (`__mesh_engine__`), and the mesh
  cache key covers the gmsh, scipy, shapely and GEOS versions. The `config_hash` of every earlier
  run changes once, so the first relaunch recomputes, and cached triangle meshes are regenerated
  once. An unknown engine never matches a previous run.
- The compact network comparison reads the reference river from `mesh_cell_families`.

### Removed
- The lazy re-exports of `hydromodpy.spatial.field`, `hydromodpy.spatial.geographic` and
  `hydromodpy.spatial.geographic.synthetic` (2026-10-31). Import each name from the module that defines
  it, for example `GeographicConfig` from `spatial.geographic.geographic_config` and
  `build_synthetic_geographic` from `spatial.geographic.synthetic.catchment`. `hydromodpy.spatial` and
  `hydromodpy.spatial.terrain` keep theirs.
- `hydromodpy.core.io.crs.geojson_crs_member`, replaced by the constant `RFC7946_CRS` (2026-10-31).
- `SpatialSupportProvider.required_data_types` and its four implementations, which no code called
  (2026-10-31). The geology provider already refuses a missing geology where it reads it.
- `read_dem_metadata`, `build_geographic_runtime_context` and `CatchmentDelineation` no longer ask
  Nominatim for a French department code (2026-10-31). The reverse geocoding waited up to 120 s at every
  build of the geographic context, a cache hit included, and no code read `dep_code`. The attribute, the
  `locator_factory` argument and the geopy and certifi imports are gone.
- The in-memory raster cache of the Whitebox backend (`set_cache_rasters`, `get_cached_raster_numpy`,
  `get_cached_raster_metadata`, `clear_raster_cache`) (2026-10-31). Nothing ever switched it on, so every
  reader already read the file on disk.
- The `default_country` argument of `site_selection.candidates.pipeline.territory_geometry`
  (2026-10-31). The `country` of the territory decides alone.
- The copies the clean-up of `spatial/` merged into one function each (2026-10-28). The module
  `spatial.forcing.spatial_mean` is folded into `spatial.forcing.rasters`, names unchanged.
  `SUPPORTED_PARAM_UNITS` of `spatial.field.core.field_param` gives way to
  `SUPPORTED_PARAMETER_UNITS` of the field unit table. In site selection, the geology and influence
  evidence writers (`write_{geology,influence}_evidence_{geojson,geopackage,geoparquet}`,
  `{geology,influence}_evidence_gdf`) give way to `outputs.evidence_layers.write_evidence_layer`
  with a `role`, and `write_observation_points_{geopackage,geoparquet}` to
  `outputs.geospatial.write_vector_layer`.
- The field meshes, a second mesh system older than `PlanarCellMesh` (2026-10-28). `BaseFieldMesh`,
  `FieldMesh`, `StructuredFieldMesh`, `TriangularStructuredFieldMesh`,
  `TriangularUnstructuredFieldMesh`, `PolygonFieldMesh`, `GeologyStructuredMesh` and
  `GmshPlanarMesh2D` go, with `load_planar_mesh`, `save_planar_mesh`, `from_field_mesh`,
  `from_gmsh_planar`, `to_field_mesh` and the folder `spatial/field/meshes/`. A support samples the
  cells of a `PlanarCellMesh`, `Field.on_mesh(cell_mesh, *, cell_samples_per_axis=...)`, and
  `FieldDiscretization.mesh` and `MeshWithValues.mesh` hold it. `mesh_cells` and `cell_values` of
  `spatial/field/core/mesh_cells.py` give the cells of a mesh and check one value per cell, and
  `MeshCell` and `MeshWithValues` live there. `plot_cell_values` moves to `spatial/field/plotting.py`
  and draws a `PlanarCellMesh` or a `HydroMesh`. `FieldMeshSquare` returns a `PlanarCellMesh` of the
  unit square, and `regular_cell_mesh_over_bounds` of `spatial/field/geology/geology_mesh.py`
  replaces `GeologyStructuredMesh.from_bounds`. `read_msh` and `write_msh` read and write a `.msh`
  file as a `HydroMesh`. `plot_cell_values(ax, mesh, values)` names its mesh `mesh`, where it was
  `hydro_mesh`. `FieldParam.to_mesh_field` gives one flat value per cell, where a structured field
  mesh gave a `(nrow, ncol)` table. Zone fractions, mapped properties and demo values are unchanged
  to the bit.
- `save_hydro_mesh_vtu` and `load_hydro_mesh_vtu` of `spatial/mesh/gmsh_grid/exchange_api.py`,
  which only called `write_vtu` and `read_vtu`, and `load_planar_as_hydro_mesh`, which `read_msh`
  replaces (2026-10-27). The checks for a missing meshio, a required dependency, go too.
- The mesh code no longer guards against a missing scipy, xarray or rasterio (2026-10-27). They are
  required dependencies, so these branches never ran, and had they run they would have given a
  uniform or zero recharge with a mere warning. `_idw_brute_force`, the inverse distance weighting
  without scipy, goes with them. `StructuredGridSpec` keeps `top`, `botm`, `nlay` and `idomain`.
  Its nine planar fields (`delc`, `delr`, `xoff`, `yoff`, `nrow`, `ncol`, `xvertices`, `yvertices`,
  `crs`) go, since the planar grid comes from the mesh engine and the only caller read the vertical
  part. A support with a step at or below zero is still refused. `require_gmsh` has one home,
  `spatial/mesh/engines/triangle/gmsh_cdt.py`, and raises `MeshError` naming the `mesh` extra.
  The refusal of a mapped river trace for `where = "height_above_stream"` goes too, since only the
  traced network reaches the mesh step. No mesh changes.
- The bundle reader of a run and what lived on it (2026-10-26). `resolve_bundle_cells` is
  `resolve_run_cells(store, sim_id, *, expected_size=None)` and reads the mesh stored in
  `fields.zarr` only. Nothing writes `<run>/mesh/mesh_catchment_bundle/cells.csv` since the exporter
  left on 14 October. `RUN_MESH_BUNDLE_RELPATH` and `bundle_cells_from_dir` go, and
  `load_variable_series` and `mask_depth_series_from_head_nodata` no longer take `run_folder`. The
  bundle was the only source of `storage_coefficient`, `z_top` and `z_bottom` of a cell, so the
  three fields of `CellCentroidTable` go, with the export `boussinesq_obstacle_diagnostics.csv` of a
  comparison, which was empty for every sealed run. The columns `surface_top_m` and
  `surface_bottom_m` of `observables.csv` and `timeseries_long.csv`, always empty, go with the
  surface lines of the series figures. `catchment_mesh_bundle_reader` stays, because the 16
  committed bundles of the validation cases are read by it. No TOML key changes (`5861d49d7`).
- `[calibration.aggregate]` `weighting`, `nested_gauges` and `on_member_failure`, and
  `[calibration]` `lightweight_extraction` and `persist_model_distribution`, leave the schema
  (2026-10-20). Nothing read them: `weighting = "error"` or `on_member_failure = "drop"` gave the
  same cost as the defaults. They are retired, accepted and ignored with a warning, so a run
  sealed while the frozen configuration spelled out every default keeps replaying.
- `examples/projects/09_capability_gallery/` (figures and manifests of the retired documentation
  gallery, whose producers no longer exist; a copy lives outside the tree) and the always-skipped
  `tests/unit/solver/test_boussinesq_stationary_robust_solver_matrix.py`, which loaded a script of the
  retired example 10.
- The `~/hydromodpy` fallback of every verb, `cli/commands/site/_workspace.py`, the `results` group
  of `hmp workspace clean` that deleted
  `runs/` without a tombstone, `open_indexed_run` (network metrics open the run from its directory).
- The DuckDB-bound writer of the Catalog (`results/catalog/{writes,writes_zarr,writes_parquet,
  writes_helpers,writes_duckdb,lifecycle,reindex,package_io,audit}.py`, `register_simulation`,
  `finalize`, `if_exists = "replace"`, the `audit_log` table, `trash.json`, `trash_marker.py`,
  `session_journal.py`, `results/catalog/migrations/`, `core/state/migrations/`,
  `core/state/global_index.py`, `HMP_AUTO_REGISTER_PROJECT` and `hmp workspace
  register | forget | prune | search`), the index-bound heartbeat and event stream
  (`workflow/tracking/{heartbeat,events}.py`, `workflow/run_catalog.py`), `MANIFEST_SCHEMA_VERSION`
  and the v1 manifest writer, `WorkflowContext.attempt_id`, `ProjectRunner.sweep`, the post-run
  lockfile and `hmp run --no-lock`, `hmp audit`.
- `share/`, `reports/`, `figures/` at a project root, `SHARE_DIRNAME`, `REPORTS_DIRNAME`,
  `share_dir_for`, `reports_dir_for`, `running_sidecar_*`, `INDEX_FILENAME`, the `.hmp` exchange
  package (`exporters/hmp_package.py`, `importers/hmp_package_inputs.py`, `hmp data import`,
  `hmp export --format package`), the capability gallery hook and `[analysis.capability_gallery]`,
  `[analysis]` as a root section, `OUTLET_STATION` and the `<metric>_<station>` pivot.
- The `testbed` and `comparison` launchers (`hydromodpy/analysis/testbed/`, `analysis/comparison/
  {dispatch,experiment_config,experiment_launcher,child_materialization,run_backend,descriptions,
  stability}.py`, `analysis/comparison/audit/`, `workflow/regional_lab_materialization.py`,
  `reporting/comparison/compact_network/`), the `hmp process` family, the `regional_lab` CSV,
  `hmp site-selection` and the `workflow/site_selection*.py` modules, `[site_selection]` and
  `[hydrometry]` as root sections, `hmp calibrate --check`, the in-memory GR4J path
  (`simulation/extraction/calibration_bridge.py`), `simulation/extraction/derivation/fit_metrics.py`,
  `simulation/extraction/ARCHITECTURE.md`.
- Examples `10_testbed_workflow`, `17_site_selection_workflow`, `18_site_selection_to_testbed` and the
  former `09_comparison_workflow` left the repository (runnable copies in the HydroModPy workspace
  `workspace-anciens-exemples/` outside the tree).
- The `analysis -> reporting` tolerance of the layer matrix.
- `[testbed]`, `[simulation] study_area_name`, `outlet_x`, `outlet_y`, `if_exists = "replace"`,
  `[workspace] project_root` in a file, the `testbed`, `comparison` and `site_selection` workflow modes and
  their `DISPATCH` routes, `ProjectTestbedRunnerProvider`.
- `hydromodpy/config/stored_config_migration.py` and its tests: a stored configuration is read as it was
  written, a run is replayed with the version that produced it.
- `geographic_fingerprint` from the new sealed formats: `site.fingerprint` is the only fingerprint.
- `[mesh_catchment]`, `[mesh_catchment_batch]`, `[mesh_input]`, `[modflow6.sgrid.planar]`,
  `[modflownwt.sgrid.planar]`, `grid_dual`, `linear_constraint_snap_tolerance`,
  `rivers.snap_tolerance`: a TOML that declares one is refused with its replacement (the message
  of `[mesh_catchment]` and `[mesh_catchment_batch]` names `[mesh]`); a stored configuration that
  declares one is refused the same way. The K of a gmsh bundle no longer fills invalid cells: K
  comes from `[flow.param.K]` only.
- The batch mesh launcher and its configuration: `spatial/mesh/launcher/`,
  `workflow/pipelines/mesh.py`,
  `spatial/mesh/config/{main,batch,rivers,watershed,hydraulic}.py` (`MeshCatchmentConfig` and
  its sub-models) and `spatial/mesh/runtime_description.py`.
- The standalone Gmsh zone mesher `spatial/mesh/gmsh_grid/zone_meshing/` (42 modules: the
  conformal planner, the hotspot policy and the embedded curves), its reference cases
  `gmsh_grid/cases/` and `gmsh_grid/examples/`, the 3D extruded-prism stack (`extruded_*`,
  `_prism_*`, `interactive_3d_viewer.py`), the catchment bundle exporter
  (`catchment_mesh_bundle.py`, `bundle_export_contracts.py` and the geology, hydraulic
  properties and river exporters), `trace.py`, `plotting_utils.py`. The bundle reader
  (`catchment_mesh_bundle_reader`) and `load_catchment_mesh_bundle` stay, since the Boussinesq
  validation cases read bundles.
- The standalone Cartesian path of `cartesian_grid/`: `SGridConfig`, `PlanarGridConfig`, the
  `Bottom*` and `Layering*` models, `load_sgrid_toml`, `validate_sgrid_config_data`,
  `build_sgrid_from_config`, `sgrid_fieldparam_discretization`, `sgrid_mesh_adapter`,
  `PlanarDiscretizer`, `cartesian_grid/examples/` and `utils/`. `SolverSGridConfig`,
  `VerticalGridConfig`, `TopSamplingConfig`, `StructuredGridBuilder` and `StructuredGridSpec`
  stay.
- `GmshSupportMetadata`, `build_gmsh_support_metadata`, `support_on_planar_mesh`,
  `support_from_cell_mesh` (`gmsh_grid/runtime_support.py`) and the adapters
  `cell_mesh_from_triangulation` and `cell_mesh_from_voronoi_dual`.
- `spatial/mesh/ops/mesh_flow.py`, the `Grid` and `GridTopology` protocols
  (`model/protocol.py`), `from_flopy_structured` (it lives on as a test oracle in
  `tests/_helpers/`) and `from_extruded_prism`. `RegularGrid` stays.
- The legacy MODFLOW 6 post-processing, which had no caller: `solver/modflow6/postprocess/`,
  `solver/modflow6/support/diagnostics.py`, `Modflow6.post_processing`,
  `Modflow6Transport.post_processing`, `Modflow6._to_export_array`. The unused
  `native_mesh_npz`, `native_mesh_csv`, `native_mesh_vtu` and `native_mesh_png` fields of
  `ModflowPostprocessOptions` leave with it.
- `spatial/geographic/core/domain_geographic_pipeline.py` (`build_domain_geographic_context`,
  `build_geographic_derived_features`) and its `breach` to `fill` retry after an empty
  catchment: `hmp run` uses the other pipeline. `DomainGeographicContext` now lives in
  `spatial/geographic/core/derived_features.py`.
- `BoussinesqMesh.river_cell_indices`, `support_metadata` and the bounding-box and
  point-in-triangle branches; the Boussinesq extractor no longer stores `mesh/descent_receiver`
  (no Boussinesq run has a raster mesh; readers rebuild D from the stored top).
- Environment variables `HMP_MESH_TRACE_FILE`, `HMP_GMSH_VERBOSE` and `HMP_UPDATE_GOLDEN`.
- Public names of the `gmsh_grid` facade (17 remain), of the `cartesian_grid` facade (4 remain)
  and of `spatial.geographic` (`build_domain_geographic_context`,
  `build_geographic_derived_features`), in this pre-release.
- `ops/voronoi.voronoi_cells`, `ops/voronoi.voronoi_dual_of_mesh` (call
  `voronoi_planar_mesh(vertices, domain)` with the triangulation vertices) and the
  `vertex_decimals` argument: the tessellation merges vertices at 1 mm in `cell_topology`.
- The horizontal-anisotropy hook of the XT3D advisor: the NPF package never received an
  anisotropy.
- `watershed_drainage_cell_mask` (`solver/modflow6/builders`) and the polygon masks of the
  MODFLOW 6 build: the drainage routing and the catchment readers take the basin of D.
- `sgrid_field_discretization` and its four helpers, `planar_forcing_discretization`,
  `modflow6/support/forcing_discretization`, `builders/vertex_grid.py` and the `GridIntersect`
  calls of LAK and SFR, `spatial/mesh/model/cell_adjacency.py`, `SolverMesh.from_sgrid`,
  `Grid.cell_centers_xy`, `setup.mesh_support`, `SolverGridContext.mesh_support`,
  `model.solver_mesh_support` and the `river_trace` argument of `BoussinesqMesh.from_cell_mesh`.
  The solvers read the cell mesh instead.
- The extractors no longer rewrite `mesh/` after a run (MODFLOW 6, MODFLOW-NWT): vertices,
  connectivity and the synthesized NWT quad are gone, with `_padded_face_connectivity`,
  `_structured_face_connectivity`, `_structured_shape_from_vertices` and
  `_structured_mesh_geometry_from_shape`.
- The `river::trace` fallback of the compact network (`gmsh_physical_lines`, the `.msh` read).
  A run sealed before the family tables draws no reference line.

### Fixed
- A polygon cell whose zonal top falls so far under its centre sample that less than
  `min_thickness_m` or a tenth of the column is left (a coarse cell on the flank of a quarry)
  kept a column of a few centimetres, which MODFLOW 6 could not solve under Newton: the Flume v2
  run on a generated Voronoi mesh diverged at period 27. Its bottom now follows the top and the
  column keeps the thickness of the centre sample. The regular grid keeps raising the top. The
  tenth is an empirical threshold; on the frozen Flume d2 mesh it moves one cell (NSE +6.6e-5
  over 53 weeks), on the Flume v2 gmsh reference none.
- Lake cells: a mesh whose `lakes` faces follow only part of the shore (arms narrower than a
  cell, 54 % on the two-lake Cheze at 80 m) resolves the lake cells by overlap, like a mesh
  without shore faces, instead of refusing the mesh.
- A gridded recharge or ETP (SIM2, several stations, the soil reservoir EVTA) on a regular
  grid read its values north-south mirrored: the cell centres handed to the sampler put row 0 at
  the south, while MODFLOW puts it at the north. Hit MF6 on a regular grid and every NWT run with
  a heterogeneous recharge or ETP; triangles and Voronoi were right. Example 04
  `step6_soil_reservoir.toml`: 28.8 % of the cells change recharge, mean discharge -0.10 %, NSE
  0.75249 to 0.75248, heads |dh| mean 4.6 cm, max 0.68 m. Runs sealed before this fix on such a
  grid are not comparable to later ones.
- The strip validation comparisons read MF6 Voronoi heads at the bundle nodes. They read the
  mean of the polygon vertices: 0.46 m RMSE on a case solved to 7 mm. A polygon mesh read without
  its nodes now raises.
- Twin calibrations read the truth and the trials in the same cell. On triangles and Voronoi the
  truth took a raster index or a vertex mean, so a noise-free twin did not return to zero.
- The transient hillslope interception comparison bins the reference with the model's cell
  areas; on triangles the unweighted reference hid a one-period onset lag.
- In the case-by-solver matrix, PETSc variants sit in the Boussinesq column and MF6 control
  variants in their MF6 column, not in `other`; a test that gains parameters drops its old
  snapshot record on merge.
- On Windows, a MODFLOW 6 run whose files sit past 259 characters fails with `HMPY.E406`
  naming the path and its length, instead of mf6's `Could not open ... IOSTAT 29`.
- Depression removal no longer ends the Python process. whitebox-workflows 1.3.5 can lose a
  thread race in `fill_depressions` ("Error unwrapping 'output'"), even on one worker, and
  its panic hook then calls `exit(1)`: a run or a test session stopped with no traceback.
  The fill and breach tools now run in a child interpreter; a child that lost that race is
  run again, at most three times, with a warning, and any other failure raises
  `TerrainError`. The output is bit-identical to the in-process call.
- A failed MODFLOW 6 run quotes the lines of `mfsim.lst` that say why it stopped in its
  `HMPY.E401` message, or says that `mfsim.lst` was never written.
- A resume of a killed run (`hmp run --resume`) works in the scratch folder of the run it
  continues, instead of letting the sweep of killed runs delete it: the delineation and the
  mesh are reused, not generated again. A `<run>.holder` file keeps the sweep of other runs
  away while the resume runs.
- On Windows, the scratch folders of killed runs are swept too. Liveness is read from the
  process exit code; `os.kill(pid, 0)` is not used there.
- `bootstrap_proj()`, run by every `hmp` command, no longer points `PROJ_DATA` at the
  database of pyproj when a bundled rasterio, pyogrio or fiona ships a newer one. On Windows
  with Python 3.11 (pyproj 3.7.2, rasterio 1.4.4) every rasterio CRS lookup after the
  bootstrap failed with "DATABASE.LAYOUT.VERSION.MINOR = 4 whereas a number >= 5 is
  expected", in the process and in its workers.
- Export plans and the step 0 refusal of two `[[export]]` blocks writing one file name the
  files with forward slashes on every OS, as the TOML spells them. Windows printed
  backslashes.
- On Windows, `hmp run` and `hmp calibrate --list-phases` print the paths under the working
  directory with forward slashes; a broken catalog index error names the file as it is
  spelled on disk; a `file:///C:/...` input of a capability job resolves to that file
  instead of a path under the job directory.
- Example files check out with LF line endings on Windows too, so their size and sha256
  match the example catalog.
- A console log line no longer fails with "--- Logging error ---" when the stderr stream
  its handler was opened on has been closed since.
- On Python 3.11, a solver adapter whose metaclass answers every attribute is refused, as on
  3.12 and later: the members are read statically.
- The page check of the docs no longer reports valid `{doc}` links as dead on Windows.
- The example 12 regression goldens follow the code. Both extensive cases read
  `buff_area = "20%"` as 20 % more area since 2.0.0a4, so their domain went from 6 468 to
  4 148 cells; the accumulation flux sums the descent D since 2.0.0a5; the NWT case now
  converges. MODFLOW 6 and MODFLOW-NWT agree on the new domain: mean head 122.686 against
  122.685 m, drain outflow 0.06307 against 0.06305 m3/s, where the GMRES golden stood 0.5 m
  below MODFLOW 6.

## [v2.0.0a5] - 2026-10-13

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
- With the whole per-cell budget kept, `[[export]] variables = "all"` and `hmp export --list`
  offer every budget term and every field rebuilt from it (`outflow_drain`, `release_flux`,
  the accumulation fluxes, `simulated_active_network`, the storage terms), a portable `.hmp`
  package carries the budget group, and the testbed tables of a MODFLOW run gain
  `outflow_drain_*` and `accumulation_flux_*` columns. Left as they were, and not covered by
  this change: the legacy solver post-processing that carries the same field names without a
  caller (`modflow_common/options.py`, `modflow6/postprocess/`, `nwt/_post_processing.py`,
  `mt3dms.py`), the float64 `boussinesq_state` histories that duplicate `budget/`, the testbed
  reader of `recharge_flux` and the comparison series mapped to `seepage_areas` (names no store
  holds), and the Boussinesq adapter that declares `release_flux` for a calibration and refuses
  it at extraction.
- The example projects, the regression fixtures and the validation cases no longer declare
  `[simulation.results.derived]` or `[simulation.results.budget]`: they keep the whole
  per-cell budget by default, and example 11 says a run without figures has nothing to
  declare.
- A calibration that saves runs (`save_runs = "best_n"` or `"all"`) writes the best run with
  the results options of the project file, and every other saved run with
  `keep_per_cell_budget = false`: those keep only the per-cell terms their figures, exports,
  calibration outputs and observation points read.
- A figure, a map overlay or a reader skipped because the run did not keep a per-cell budget
  term now says which terms the run kept, which ones the field needs and that
  `[simulation.results] keep_per_cell_budget = true` (the default) keeps them; a run that
  kept every term the solver produced and has no drain, stream, lake or surface excess is
  still told the model has no such exit. The geometric seepage fallback of a surface-excess
  solver names the run's policy the same way. `hmp viz` and the calibration loader read a
  sealed `runs/<name>/config.toml` through the stored migration.
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
