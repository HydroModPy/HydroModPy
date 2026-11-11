# display/overview

The data overview: what the catchment looks like before any simulation. It reads a
`DataOverviewState` (the geography and the loaded data, no run) and the rows of its
data inventory, and draws one PNG per panel switched on in `[overview.panels]` into
`runs/<overview>/figures/`. The page is written after the seal by `display.report`
into `runs/<overview>/report/`, from the sealed directory.

| file | what it does |
|---|---|
| `config.py` | the `[overview]` TOML section and its panels |
| `location.py` | where an overview writes: its name, its run directory, its panels folder |
| `summary.py` | what the panels read: the stats card counts and the station table come from the inventory rows, plus the outlet and the title of the regional map |
| `panels.py` | the drawing of each panel: DEM, regional setting, geology, network, time series, stats card, station table |
| `report.py` | `PANEL_FILES` (panel field to PNG) and `generate_overview_report(state, inventory)`, which draws the panels switched on |

The inventory is `workflow.overview.inventory_rows(state)`. The seal writes it to
`tables.parquet/data_inventory.parquet` (`DATA_INVENTORY_SCHEMA`) and lists the loaded
inputs in `inputs.json`, so every count of the page can be read from the sealed run.
The level pages are always written.

This is the one part of `display` that reads raw files (rasters and shapefiles named
by the state), because no run exists yet. A panel that misses its data draws an
explicit empty state rather than failing.

A new panel is a boolean in `OverviewPanelsConfig`, a drawing function in
`panels.py`, its call in `report.py` and its line in `PANEL_FILES`.
