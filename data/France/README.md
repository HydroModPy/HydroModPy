# France Data Layout

This directory is organized by data type to make datasets easier to discover
and reuse across workflows.

## Structure

- `data/France/geology/`
  - geology layers for lithology classes (GEO1M.*)
- `data/Brittany/dem/`
  - topography grids (current DEM: `regional dem.tif`)
- `data/France/climate/`
  - climate tabular inputs (`_climate_REANALYSIS.csv`)
- `data/France/hydrometry/`
  - hydrometric stations
- `data/France/onde/`
  - ONDE/intermittency stations
- `data/France/docs/`
  - auxiliary notes/documentation

## Notes

- DEM was moved to `data/Brittany/dem/` because the available `regional dem.tif` covers Brittany.
- Paths in `hydromodpy/field/cases/geology/geology_config.toml` already target
  this new structure.
- This layout is intentionally thematic-first (geology, dem, climate, etc.),
  not format-first (vector/raster/tabular).
- If a legacy script expects files directly under `data/France/`, update
  paths to the thematic subdirectories above.
