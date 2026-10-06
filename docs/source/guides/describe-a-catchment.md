# Describe a catchment

The overview workflow draws the identity card of a catchment before any model exists. It
delineates the catchment, loads the data you list, and writes maps, time series, a station
table and one web page. It runs no solver, so it costs seconds, not hours.

Use it to answer three questions before you build a model. Is this the basin I mean? What
data exist inside it? Do the layers agree in space and in time?

## What you need first

- A project folder and a TOML file. The overview reads the same sections as a simulation
  for the catchment and the data, and the same `hmp run` command starts it.
- An outlet and a DEM, or a DEM source. They are the first two things the overview needs.
- A network connection if a data family comes from an API. Nothing else is needed: no
  MODFLOW binary, no `[simulation]` section.

The blocks below inherit step 3 of example 04, which holds the catchment of Nançon, its
DEM, its BD Topage network and its Hub'Eau gauge. In a project of your own, those sections
sit in your file. Put the blocks in a file next to the step files, for example
`overview.toml`.

## 1. Select the overview workflow

Set {toml}`workflow.mode` to `"overview"`. The mode is what `hmp run` reads to choose the
workflow. The presence of an `[overview]` section does not choose it.

```toml
base_config = "step3_api_data.toml"

[workflow]
mode = "overview"
```

```{hmp-params}
workflow.mode
```

## 2. Place the catchment

The overview delineates the catchment exactly as a simulation does, from the keys of
`[geographic.catchment]`. Example 04 gives these values to them:

```{hmp-resolved} geographic.catchment.catch_def
:config: step1_minimal.toml
```

```{hmp-resolved} geographic.catchment.x_outlet
:config: step1_minimal.toml
```

```{hmp-resolved} geographic.catchment.y_outlet
:config: step1_minimal.toml
```

```{hmp-resolved} geographic.catchment.dem_init_path
:config: step1_minimal.toml
```

The cards of the keys you will touch first:

```{hmp-params}
geographic.catchment.catch_def
geographic.catchment.dem_init_path
geographic.catchment.x_outlet
geographic.catchment.y_outlet
geographic.catchment.snap_dist
geographic.catchment.buff_area
geographic.crs_project
```

The DEM can also come from a source declared in `[[data.dem.sources]]` instead of a local
file. The overview resolves it the same way a simulation does.

## 3. Name the card and give it a window

Add the `[overview]` section. {toml}`overview.name` is the title of the card. Without it, the
card takes the name of the project folder.

{toml}`overview.date_start` and {toml}`overview.date_end` are the window of the card, and they
play a second role. Overview mode has no `[simulation.time]`, so every `[data.<type>]`
section that declares no window of its own inherits this one. A section that declares a
window keeps it. Declare the two dates together.

```toml
base_config = "step3_api_data.toml"

[workflow]
mode = "overview"

[overview]
name = "Nançon"
date_start = "2000-01-01"
date_end = "2002-12-31"
regional_context_label = "Location in the Armorican Massif"
```

{toml}`overview.regional_context_label` is the title of the location map. The map is
always drawn when the DEM and the watershed exist, and no panel toggle controls it. Without a
label, the title comes from the DEM file name.

```{hmp-params}
overview.name
overview.date_start
overview.date_end
overview.regional_context_label
```

## 4. List the data the card reads

The overview loads the families listed in {toml}`data.types`, and only those. It infers
nothing from other sections, so a family you forget is a family the card does not show.
Each family needs its `[data.<type>]` section, as in a simulation. The page
{doc}`Get the data of a catchment <get-the-data>` says how to declare a source.

Step 3 lists `hydrography` and `hydrometry`. This block adds the SIM2 rain and ETP, so the
climate panel has something to draw. A list replaces the list of the parent file, so all
four families are written out.

```toml
base_config = "step3_api_data.toml"

[workflow]
mode = "overview"

[overview]
name = "Nançon"
date_start = "2000-01-01"
date_end = "2002-12-31"

[data]
types = ["hydrography", "hydrometry", "precipitation", "etp"]

[[data.precipitation.sources]]
source = "sim2"

[[data.etp.sources]]
source = "sim2"
```

The two SIM2 sections declare no window, so they read the `[overview]` window. The gauge of
step 3 declares its own window and keeps it. No box is written: the loader asks each source
over the delineated catchment, as in a simulation.

```{hmp-params}
data.types
```

## 5. Choose the panels

Each key of `[overview.panels]` switches one panel on or off. All of them are on by
default. A panel that is on and has no data is still drawn, as an empty figure that says
there are no records. The geology map is the exception: without geology it is not drawn.
Switch off the panels of the families you do not load.

| Panel | Reads | What it shows |
|---|---|---|
| {toml}`overview.panels.map_dem` | the delineated catchment | The DEM clipped around the catchment, buffer included, with the watershed outline, the outlet, the loaded reaches and the stations. |
| {toml}`overview.panels.map_geology` | `geology` | The DEM with the geology polygons over it. |
| {toml}`overview.panels.map_hydrography` | `hydrography` | The DEM with the river network and the outlet. |
| {toml}`overview.panels.stats_card` | everything loaded | A table: name, area, period, number of reaches, number of stations by family. |
| {toml}`overview.panels.timeseries_discharge` | `hydrometry` | One line per gauge, observed discharge. |
| {toml}`overview.panels.timeseries_piezometry` | `piezometry` | One line per piezometer, with a dashed line at the ground level of each one that gives it. |
| {toml}`overview.panels.timeseries_intermittency` | `intermittency` | One strip per ONDE station, one tick per observation, on the row of its flow state. |
| {toml}`overview.panels.timeseries_water_quality` | `water_quality` | One strip per parameter, one line per station. |
| {toml}`overview.panels.climatic_summary` | `precipitation`, `etp` | Mean monthly precipitation and ETP, as bars. |
| {toml}`overview.panels.station_inventory` | `hydrometry`, `piezometry`, `intermittency`, `water_quality` | One row per station: type, id, coordinates, first and last date. |

The geology polygons are coloured by the column of the geology file named `CODE_LEG`,
`code_leg`, `litho`, `LITHO` or `LITH`. With another column name, the polygons are drawn
in one colour. The map reads the vector file again, so it needs a vector source.

The block below keeps the maps, the gauge, the stats card and the station table. It drops
the panels of the families step 3 does not load: geology, piezometry, intermittency, water
quality and climate. Keep `climatic_summary` on when you add the SIM2 rain and ETP of section 4.

```toml
base_config = "step3_api_data.toml"

[workflow]
mode = "overview"

[overview]
name = "Nançon"
date_start = "2000-01-01"
date_end = "2002-12-31"

[overview.panels]
map_geology = false
timeseries_piezometry = false
timeseries_intermittency = false
timeseries_water_quality = false
climatic_summary = false
```

```{hmp-params}
overview.panels.map_dem
overview.panels.map_geology
overview.panels.map_hydrography
overview.panels.stats_card
overview.panels.timeseries_discharge
overview.panels.timeseries_piezometry
overview.panels.timeseries_intermittency
overview.panels.timeseries_water_quality
overview.panels.climatic_summary
overview.panels.station_inventory
```

## 6. Check the file, then run it

Validate the file first. It catches a wrong key or a window in the wrong order without
touching the network.

```bash
hmp config check overview.toml
hmp run --dry-run overview.toml
```

`hmp config check` prints `OK:` and the path of the file, or each error with the key it
concerns.
`hmp run --dry-run` prints the workflow it resolved, here `overview`, and the sections of
the file. Then run it:

```bash
hmp run overview.toml
```

The run has three phases that show on the console: delineating the catchment, loading the
data, drawing the report. At the end it prints the name and the area of the catchment, the
path of the web page and the folder of the figures. `-v` lists every file written.

A new run overwrites the files of the previous one. The overview has no run name and no
catalog entry.

## 7. Read the result

The files go under the `share/` folder of the project. The project is the folder named by
{toml}`workspace.project_root`, or by {toml}`workspace.output_root` when it is set.

| File | Content |
|---|---|
| `share/web/index.html` | The report page: identity, location, river network, inventory of the data families, observations, recharge and pumping. |
| `share/figures/overview/map_regional_context.png` | The location of the catchment on the regional DEM. |
| `share/figures/overview/<panel>.png` | One file per panel that is on, named after its key. |

Open the maps first, in this order:

1. `map_dem.png`: does the outline enclose the basin you mean, and does the outlet sit on
   the stream?
2. `map_hydrography.png`: does the network fall inside the outline and meet the outlet?
3. `map_geology.png`, if you loaded geology: do the zones cover the basin?
4. `station_inventory.png`: which stations are inside the box, and over which dates?
5. The time series: do the dates cover the window of the card?

The web page shows the DEM, the location and the river network, the inventory tables and the
observation series. It does not carry the geology map, the stats card or the climate
bars; open those as PNG files.

At this version, the map titles, the stats card, the date headers of the station table
and the web page are written in French. The time-series figures carry English titles.

If a map is wrong, stop here. Fix the outlet, the DEM, the CRS or the window before you
build a model on it.

## What can go wrong

**`overview.date_end is missing: declare date_start and date_end together`.**
`hmp config check` refuses a window with one bound. Add the other one. The mirror message is
`overview.date_start is missing: declare date_start and date_end together`.

**`overview.date_start must be before overview.date_end`.** The two dates are in the
wrong order, or equal.

**`overview.panels.map_foo: Extra inputs are not permitted`.** A key of `[overview.panels]`
is spelled wrong. The ten names are in the table of step 5.

**`catch_def='from_outlet_coord' requires 'dem_init_path'`.** The catchment has no DEM. Set
{toml}`geographic.catchment.dem_init_path`, or declare a DEM source in `[data]`. When
`dem_init_path` names a file that does not exist and no DEM source is declared, the run
stops with `No dem_init_path and no [data.dem] source configured.`

**The run ends and no figure appears.** The file has no `[overview]` section. The
workflow returns without a report. With `-v`, the log shows
`[overview] No [overview] section - skipping report generation.` Add the section, even with
only a name.

**`Failed to load data manager '<type>'` followed by a reason.** A family you listed in
{toml}`data.types` did not load. For `dem`, `geology` and `hydrography` the run stops. For
any other family the message is logged as `[ERROR] Load of '<type>' failed: ...`, the run
goes on, and the panel of that family comes out empty. Read the console after the loading
phase. Remove the family, or fix its source. If the reason says that a source needs a period and
the request carries none, add {toml}`overview.date_start` and {toml}`overview.date_end`.

**A panel is on but empty.** The figure says there are no records, or no stations. The
family is not loaded, or no station falls inside the box in the window. Switch the panel
off, or widen the window.

## Where next

- {doc}`Get the data of a catchment <get-the-data>`: declare a source for each family.
- {doc}`Use your own files <use-your-own-files>`: read a DEM, a network or a gauge from
  disk.
- {doc}`Report on a catchment <report-on-a-catchment>`: the HTML report built with
  `hmp report catchment`, which is a different tool from this workflow.
- {doc}`Time and initial state <time-and-initial-state>`: once the card looks right, set
  the window of the simulation.
