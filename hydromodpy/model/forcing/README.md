# model/forcing

How a loaded series or grid becomes the rate a solver reads. A forcing is a rate that changes in space
and in time, such as recharge or precipitation. It comes as a series, as a grid (a NetCDF or GeoTIFF
file, or an xarray dataset) or as time series at stations. The package aligns a series to the stress
periods, and puts a grid or stations on the cells of a mesh as one rate per cell and per stress period,
in m/s. Every solver takes this one path, whatever the mesh engine, so a regular grid, a triangulation and
a Voronoi mesh are served alike.

## How a forcing reaches the cells

1. A solver builder or the workflow calls `discretize_fields_on_cells` or `discretize_points_on_cells` in
   `cells.py`. It gives the loaded records, the cell centers, the number of stress periods, the
   simulation window and the interpolation method.
2. `cells.py` turns the window into the bounds of each stress period (`stress_period_bounds`).
3. For a grid, `rasters.py` reads each record. A record whose CRS is not the CRS of the mesh is refused,
   because a grid is never reprojected. A dataset or a NetCDF file is averaged in time over each period.
   A GeoTIFF gives one band per time step, and a rotated GeoTIFF is refused. For stations, `stations.py`
   refuses a station whose location is in another CRS than the mesh, then takes the mean of each series
   over each period.
4. The coverage rule of `core/time/coverage.py` says which samples a period takes and what happens when
   the record does not reach the period.
5. `sources.py` refuses a nodata pixel under a cell, then interpolates onto the cells. The methods are
   `nearest`, `linear`, `idw` (`interpolation.py`) and `area` (`area_weights.py`).
6. The values are multiplied by the unit factor of the record, so they come out in m/s. When several
   records cover one period, the period takes their mean with equal weights.

A cell reads valid pixels only. If a nodata pixel is under a cell, the package refuses the forcing and
says which cell and which period. The method `area` weighs each pixel by the area it shares with the cell
polygon, so a cell rate times the cell area is the integral of the grid over the cell. It needs the
planar mesh and is refused for stations. The package also gives the spatial mean of a grid
(`spatial_mean_from_fields`), the homogeneous series used when a forcing is not spatial.

A series that does not go through a mesh follows another path. `forcing_bridge.resolve_forcing` turns a
loaded record into the series the flow keeps. `time_alignment.py` gives it one value per stress period of
`[simulation.time]`, each monthly or yearly sample weighed by its length. `steady_periods.py` is the rule
every solver shares for a steady period. `time_forcing.py` resolves a dated forcing to one value per
period, and the solvers call it.

## Modules

| module | answers |
|---|---|
| `area_weights.py` | Area-weighted mean of a gridded source over the cells of a mesh |
| `cells.py` | Forcing fields and station series on the cells of a mesh |
| `dated_forcing.py` | The dated forcing of a boundary or a sink (`TimeSeriesForcing` and its readings) |
| `forcing_bridge.py` | Turns a loaded record into a forcing (`resolve_forcing`) |
| `interpolation.py` | Shared spatial interpolation utilities for structured grids |
| `rasters.py` | Xarray and file-based fields on cell centers, and their spatial mean |
| `recharge_rates.py` | The mean recharge the stream-network criterion divides by |
| `sources.py` | Readers of a gridded or located source, shared by the forcing discretizers |
| `stations.py` | Point-record discretization on cell centers |
| `steady_periods.py` | The rate a steady stress period takes: one rule for every solver |
| `synthetic.py` | Synthetic precipitation, inflow and recharge series for demonstrators and tests |
| `time_alignment.py` | Gives a series one value per stress period of `[simulation.time]` |
| `time_forcing.py` | Resolves a dated forcing to one value per stress period |
| `types.py` | Three small aliases: the spatial mode, the `first_clim` keyword and the interpolation method |
| `validation.py` | Numeric checks of a forcing payload |

## Where to start

| To change | Open first |
|---|---|
| the bounds of the stress periods | `cells.py`, `stress_period_bounds` |
| how several records of one period are combined | `cells.py`, `discretize_fields_on_cells` |
| how a NetCDF, xarray or GeoTIFF source is read | `rasters.py` |
| the station mean of a period | `stations.py`, `period_means` |
| the unit of a record, or which variable of a dataset is the field | `sources.py` |
| the refusal of a nodata pixel | `sources.py`, `refuse_nodata_under_cells` |
| the `area` method | `area_weights.py` |
| the mean recharge a run is scored on | `recharge_rates.py` |
| how a loaded record becomes a series | `forcing_bridge.py` |
| the rate of a steady period, and a negative recharge | `steady_periods.py` |
| the alignment of a series to the periods | `time_alignment.py`, `time_forcing.py` |

## Rules between the modules

- `cells.py` is the entry point of the cells path. It reads `rasters.py`, `sources.py` and `stations.py`.
  `rasters.py` and `stations.py` read `sources.py`. `sources.py` reads `area_weights.py` and
  `interpolation.py`, which import no other module of the package.
- `recharge_rates.py` imports `core` only. `solver`, `results` and `calibration` read it so that the
  trials that score a run and the figures that redraw it use one mean recharge. A period before the first
  sample has no data, so `forcing_period_rates` gives it NaN and `criterion_mean_recharge` gives it no
  weight.
- On the series path, `forcing_bridge.py` reads `time_alignment.py`, `types.py` and `model/contracts.py`.
  `time_forcing.py` reads `dated_forcing.py` and `time_alignment.py`, and `steady_periods.py` reads
  `types.py`. `time_alignment.py` reads only `core.time`.
- Outside the package, `area_weights.py` reads `derive_geometry` from `spatial/mesh/model/geometry.py`
  until `spatial` is emptied. `HydroMesh` and `ResolvedSimulationTimeWindow` are imported for type hints
  only.
- xarray, rasterio, pyproj and the scipy interpolators are imported inside the functions that use them, so
  a run without a grid forcing does not load them.

## What lives outside the package

The recharge and ETP packages of the solvers call the cells path (`solver/modflow6/builders/recharge.py`,
`solver/modflow_nwt/nwt/payloads/recharge_etp.py` and `solver/boussinesq/forcing/recharge_resolution.py`).
The workflow step `workflow/steps/prepare_solver/forcings.py`, the hook registered in
`hydromodpy/_bootstrap.py` and `calibration/metrics/series.py` use the spatial mean. `interpolation.py`
is also used by the Explore2 client in `data/common/clients/explore2_files.py`.

## Changing the code

The unit tests are in `tests/unit/model/forcing/`, and a test file carries the name of the module it
tests. They build their cell centers, gridded records, stations and windows with
`tests/_helpers/forcing_cases.py`. The CI job `mesh-coverage` in `.github/workflows/main-ci.yml` keeps a
coverage floor for the cells path, and the floor only goes up.

```bash
pytest tests/unit/model/forcing -q
```

`docs/source/theory/forcing.md` explains the periods, the coverage rule and the cell methods, and points
to this package in its table "In the code".
