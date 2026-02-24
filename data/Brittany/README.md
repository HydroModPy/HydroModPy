# Brittany Data Layout

This directory is organized by data type to make datasets easier to discover
and reuse across workflows.

## Structure

- `data/Brittany/geology/`
  - geology layers for lithology classes (GEO1M.*)
- `data/Brittany/dem/`
  - topography grids (current DEM: `regional dem.tif`)
- `data/Brittany/climate/`
  - climate tabular inputs (`_climate_REANALYSIS.csv`)
- `data/Brittany/hydrometry/`
  - hydrometric stations
- `data/Brittany/onde/`
  - ONDE/intermittency stations
- `data/Brittany/docs/`
  - auxiliary notes/documentation

## Notes

- Paths in `hydromodpy/field/cases/geology/geology_config.toml` already target
  this new structure.
- This layout is intentionally thematic-first (geology, dem, climate, etc.),
  not format-first (vector/raster/tabular).
- If a legacy script expects files directly under `data/Brittany/`, update
  paths to the thematic subdirectories above.
