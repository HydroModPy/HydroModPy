# display/overview

The data overview: what the catchment looks like before any simulation. It reads a
`DataOverviewState` (the geography and the loaded data, no run) and writes one PNG
per panel switched on in `[overview.panels]`, then a web page. Everything lands in
the run directory of the overview, `runs/<overview>/figures/` and
`runs/<overview>/report/`.

| file | what it does |
|---|---|
| `config.py` | the `[overview]` TOML section and its panels |
| `location.py` | where an overview writes, and whether the review pages are asked for (`HMP_OVERVIEW_HTML_REVIEW_LEVELS`) |
| `summary.py` | what both the panels and the page read off the loaded data: the stats card, the station inventory, the outlet, the title of the regional map |
| `panels.py` | the drawing of each panel: DEM, regional setting, geology, network, time series, stats card, station table |
| `report.py` | `generate_overview_report`, which draws the panels switched on and writes the page |
| `web.py` | the blocks of the web page at the compact, standard and audit levels |

This is the one part of `display` that reads raw files (rasters and shapefiles named
by the state), because no run exists yet. A panel that misses its data draws an
explicit empty state rather than failing.

A new panel is a boolean in `OverviewPanelsConfig`, a drawing function in
`panels.py`, and its call in `report.py`.
