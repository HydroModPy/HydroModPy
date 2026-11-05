# spatial/forcing

This package puts a forcing on the cells of a mesh. A forcing is a rate that changes in space and
in time, such as recharge or precipitation. It comes as a grid (a NetCDF or GeoTIFF file, or an
xarray dataset) or as time series at stations. The package returns one rate per cell and per
stress period, in m/s. Every solver takes this one path, whatever the mesh engine, so a regular
grid, a triangulation and a Voronoi mesh are served alike.

## How a forcing reaches the cells

1. A solver builder (or the workflow) calls `discretize_fields_on_cells` or
   `discretize_points_on_cells` in `cells.py`. It gives the loaded records, the cell centers, the
   number of stress periods, the simulation window and the interpolation method.
2. `cells.py` turns the window into the bounds of each stress period (`stress_period_bounds`).
3. For a grid, `rasters.py` reads each record. A record whose CRS is not the CRS of the mesh is
   refused, because a grid is never reprojected. When the record or the mesh declares no CRS that
   places it on the Earth (none, an unreadable one, or a local frame), the two cannot be compared
   and the record is read as it is. Two CRS compare through `same_crs` of `hydromodpy/core/io/crs.py`.
   A dataset or a NetCDF file is averaged in time over each period. A GeoTIFF gives one band per
   time step, and a rotated GeoTIFF is refused. With a window, every period takes the same number
   of bands. Without one, each band or time step is one period. A band or a time step that no
   period reads is refused. For stations, `stations.py` refuses a station whose location is in
   another CRS than the mesh, then takes the mean of each series over each period.
4. The coverage rule of `hydromodpy/core/time/coverage.py` says which samples a period takes and
   what happens when the record does not reach the period.
5. `sources.py` refuses a nodata pixel under a cell, then interpolates onto the cells. The
   methods are `nearest`, `linear`, `idw` (in `interpolation.py`) and `area` (in
   `area_weights.py`).
6. The values are multiplied by the unit factor of the record, so they come out in m/s. When
   several records cover one period, the period takes their mean with equal weights.

```text
LoadResult (fields or points) + cell centres + simulation window
        |
        |  cells.py            period bounds, loop over the records
        v
   rasters.py or stations.py   one mean per stress period
        |
        |  sources.py          nodata check, then the interpolation method
        v
   interpolation.py or area_weights.py
        |
        v
   {stress period: array of n_cells}   in m/s
```

A cell must read valid pixels only. A pixel is nodata when it is NaN once decoded, equal to the
nodata of a GeoTIFF, or equal to the `nodata`, `_FillValue` or `missing_value` attribute of a
dataset. If a nodata pixel is under a cell, the
package refuses the forcing and says which cell and which period. It never lets the cell take a
neighbor silently. A slice with no valid pixel is refused too, and so is `linear` on a grid of one
row or one column, which it cannot triangulate.

The method `area` weighs each pixel by the area it shares with the cell polygon. A cell rate times
the cell area is then the integral of the grid over the cell. It needs the planar mesh, because the
cell polygons come from it, and it is refused for stations, which have no pixel.

The same package also gives the spatial mean of a grid (`spatial_mean_from_fields`). This is the
homogeneous series used when a forcing is not spatial. It is the mean of the valid pixels only. A
pixel equal to the nodata of a GeoTIFF, a NaN pixel of a NetCDF and a pixel equal to the `nodata`,
`_FillValue` or `missing_value` attribute of a dataset are left out alike, and a band or a time step with no valid pixel is refused.

## The folder map

```text
forcing/
├── cells.py            the entry points: period bounds, grids and stations to cells, spatial mean
├── rasters.py          xarray, NetCDF and GeoTIFF records, one mean per period, spatial mean
├── stations.py         located time series, one mean per period and per station
├── sources.py          units, the data variable, the X and Y axes, nodata check, "on cells" wrappers
├── area_weights.py     area shared by each pixel and each cell, area-weighted mean
├── recharge_rates.py   the rate a recharge series gives each period, and the mean recharge of a run
└── interpolation.py    nearest, linear and IDW from a grid or points onto target centres
```

## Where to start

| To change | Open first |
|-----------|------------|
| the bounds of the stress periods | `cells.py`, `stress_period_bounds` |
| how several records of one period are combined | `cells.py`, `discretize_fields_on_cells` |
| how a NetCDF, xarray or GeoTIFF source is read | `rasters.py` |
| how a GeoTIFF with several bands maps to the periods | `rasters.py`, `discretize_geotiff` |
| the station mean of a period | `stations.py`, `period_means` |
| the unit of a record, or which variable of a dataset is the field | `sources.py` |
| the refusal of a nodata pixel | `sources.py`, `refuse_nodata_under_cells` |
| the `area` method | `area_weights.py` |
| the mean recharge a run is scored on, and the rate of each period | `recharge_rates.py` |
| nearest, linear or IDW | `interpolation.py` |
| the names of the methods in the config | `InterpolationMethod` in `hydromodpy/core/config_kit/types.py` |

## Rules between the folders

The package is flat, so the rules are between its modules and with the rest of HydroModPy.

- `cells.py` is the entry point. It reads `rasters.py`, `sources.py` and `stations.py`.
- `rasters.py` and `stations.py` read `sources.py`.
- `sources.py` reads `area_weights.py` and `interpolation.py`.
- `area_weights.py` and `interpolation.py` import no other module of the package.
- `recharge_rates.py` imports `core` only. It is not part of the path above: `simulation`, `results` and `calibration` read it so that the trials that score a run and the figures that redraw it use one mean recharge. A period before the first sample has no data, so `forcing_period_rates` gives it NaN and `criterion_mean_recharge` gives it no weight.
- Outside the package, it imports `hydromodpy.core` (config types, exceptions, logging, units, the
  time window, the coverage rule, the nodata mask and the CRS comparison) and one name of `spatial/mesh`, `derive_geometry` from
  `hydromodpy/spatial/mesh/model/geometry.py`, in `area_weights.py`. `HydroMesh` is imported only
  for type hints, under `TYPE_CHECKING`, and so is `ResolvedSimulationTimeWindow`.
- `mesh/` never imports this package.
- `build_simulation_time_boundaries` is imported inside `stress_period_bounds`. xarray, rasterio,
  pyproj and the scipy interpolators are imported inside the functions that use them, so a run without a
  grid forcing does not load them.

The rules between HydroModPy layers are checked by `tests/unit/architecture/`.

## What lives outside the package

The package answers the question "what is the rate on each cell". Other code decides which forcing
to ask for and what to do with the answer.

- The recharge and ETP packages of the solvers call it: `hydromodpy/solver/modflow6/builders/recharge.py`,
  `hydromodpy/solver/modflow_nwt/nwt/payloads/recharge_etp.py` and
  `hydromodpy/solver/boussinesq/forcing/recharge_resolution.py`.
- The workflow step `hydromodpy/workflow/steps/prepare_solver/forcings.py` and the hook registered in
  `hydromodpy/_bootstrap.py` use the spatial mean, and so does
  `hydromodpy/calibration/metrics/series.py`.
- `interpolation.py` is also used by the Explore2 client in
  `hydromodpy/data/common/clients/explore2_files.py`.
- The series themselves (alignment on periods, units, steady periods) are in `hydromodpy/physics/forcing/`.

## Changing the code

The tests follow the layout of the code. A module is tested in `tests/unit/forcing/test_<module>.py`,
for example `area_weights.py` in `tests/unit/forcing/test_area_weights.py`. The tests build their
cell centers, gridded records, stations and windows with `tests/_helpers/forcing_cases.py`. The
forcing is also exercised by `tests/unit/physics/test_forcing_spatial_config.py`,
`tests/unit/physics/test_time_alignment.py` and `tests/unit/workflow/steps/prepare_solver/test_forcings.py`.
No contract or regression test is specific to this package.

The CI job `mesh-coverage` in `.github/workflows/main-ci.yml` fails when the coverage of
`hydromodpy/spatial/forcing/*` is under 99.7. The floor only goes up.

```bash
pytest tests/unit/forcing -q
```

```bash
pytest tests/unit/architecture -q
```

## Documentation

`docs/source/theory/forcing.md` explains the periods, the coverage rule and the cell methods, and
points to this package in its table "In the code". `docs/source/contribute/architecture/mesh/mesh-pivot.rst`
lists the forcing among the consumers of the mesh.
