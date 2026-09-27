# `hydromodpy/display`

`display` draws. It takes a run that is already computed
(`hydromodpy.results.run.Run`) or data that is already loaded, and writes PNG
figures and HTML pages. It never runs a solver, never reads a raw solver file and
never writes into the storage of a run (Zarr, Parquet, DuckDB). Everything a
figure reads from a run goes through the public API of `results`. One reader is
left over: the catchment report context (`catchment_report/context.py`) still
queries three Parquet tables of the run directory with DuckDB (runtime,
provenance counts, network segment counts).

It holds three things of unequal weight:

1. the figure catalogue of a run: the contract `figure.py`, the registry
   `figure_registry.py` and the figures of `figures/` (`hmp viz list` prints
   them);
2. two reports: `overview/` (data before any simulation) and `catchment_report/`
   (catchment report, `hmp report catchment`), which share the HTML engine
   `report_blocks/`;
3. shared plotting tools: `maps/` (map axes, mesh, overlays, sections) and
   `style.py` (theme, colormaps, legend placement).

## What a user can rely on

Figures are the part of HydroModPy the user sees most. Every figure follows three
rules.

1. **A figure shows a quantity, not a tool.** It draws a field, a flux, a budget,
   a simulated series against an observed one, a mesh or a network, under the
   names of `results/field_registry.py`. It never tests a solver name, and neither
   its name nor its title names a solver or a data provider. The same figure
   works for MODFLOW-NWT, MODFLOW 6 and Boussinesq when the run holds the field.
2. **A figure is offered only when the run has what it needs.** `spec` declares
   the fields, tables and solvers it requires; a need that `spec` cannot express
   (a network, a DEM raster, hydrochemistry, the series of a stream reach, a
   lake or a piezometer, a particle that moved) is checked in the figure's own
   `unavailable_reason`. A figure that cannot draw a run is refused with a
   sentence on every surface: skipped with its reason by `[display].figures`,
   refused by `hmp viz show` and `hmp.figure`, marked as unavailable with its
   reason by `hmp viz list --run`. It never raises from inside `render` and never
   writes a placeholder PNG. A lumped run (GR4J) has no grid, so every map is
   refused and the discharge figures stay offered.
3. **One name on every surface.** A figure has one name, written in
   `[display].figures`, `hmp viz show <run> <name>` and `hmp.figure(run, "<name>")`.
   A renamed figure keeps its old name in `former_names`, so project files that
   use it still load. `[display]` fields are `USER` when they choose what to
   show and where (`figures`, `output_dir`, `overrides`), `DEV` when they tune
   rendering (`backend`, `dpi`).

Two figures need a second run, which `spec` cannot declare yet: `difference_map`
and `side_by_side`. They are drawn from Python with `reference=<run>` and refuse
with a sentence without it.

## Import rules

Outside the package, `display` imports only `core`, `schema` and `results`
(`tests/unit/architecture/layer_matrix.yaml`). Inside, a unit (a root module or a
subpackage) imports only what its line allows. The rule that matters: **no shared
tool imports `figures/`**. Data a tool needs lives in the tool or in `results`,
never in a figure.

| unit | may import inside `display` |
|---|---|
| `report_blocks`, `style`, `maps`, `png_metadata`, `scalable`, `animation` | nothing |
| `figure` | `png_metadata` |
| `figure_registry` | `figure`; and `figures` by its name written as text, on first lookup (the one exception, which keeps `import hydromodpy.display` light) |
| `figures` | `figure`, `figure_registry`, `maps`, `style` |
| `config` | `figure_registry` |
| `<init>` (the `__init__.py` facade) | `figure`, `figure_registry` |
| `runs` | `<init>`, `config`, `figure`, `style` |
| `viz` | `scalable` |
| `overview` | `report_blocks`, `style` |
| `catchment_report` | `overview`, `report_blocks` |

Every import counts: module level, inside a function, under `TYPE_CHECKING`.
`tests/unit/architecture/display_layout.yaml` holds the table and
`tests/unit/architecture/test_package_layouts.py` checks it. No module of `display` reads a `_private` attribute of another module;
ruff rule SLF001 checks it.

## Tree

```
hydromodpy/display/
├── __init__.py            facade: BaseFigure, Figure, FigureSpec, get, list_figures, names, register
│
│   the figure catalogue of a run
├── figure.py              contract: FigureSpec (metadata), BaseFigure (plot, render, unavailable_reason)
├── figure_registry.py     register, get, resolve, names, list_figures; imports figures/ on first lookup
├── figures/               one figure per file, flat, discovered automatically
│   ├── _scalar_face_map.py    base of the "one value per mesh face" maps
│   ├── _stream_comparison.py, _routing_surface.py, _flow_persistence.py, _trial_diagnostics.py,
│   │   _observed.py, _memo.py
│   │                          helpers shared between figures (private to figures/)
│   ├── lake_level_fit.py      public helper, not registered, read by reporting
│   └── <name>.py              the registered figures
│
│   rendering the figures of a run ([display])
├── config.py              DisplayConfig, the [display] TOML section
├── runs.py                render_figures_for_run (a run, the [display] list), render_figure (one figure),
│                          figure_availability (what a run supports, and why not the rest),
│                          matplotlib_backend (Agg or interactive for the length of a render)
├── png_metadata.py        provenance written into each PNG (sim_id, field, step, EPSG, version)
│
│   shared tools
├── style.py               how every figure looks: default, print and dark themes (apply_theme),
│                          banned and preferred colormaps (get_cmap), legend placement (place_legend)
├── maps/                  map tools, used by the figures; none imports a figure
│   ├── axes.py                axes in metres or relative km, catchment outline, date axis of time series
│   ├── mesh_geometry.py       face polygons, centroids and areas
│   ├── ugrid.py               render_face_field: one value per face; last_timestep
│   ├── overlays.py            named layers drawn on a map: watershed, seepage, particles, network, wells, outlet
│   ├── transect.py            a field sampled along a line (sections)
│   └── geo/                   vector layers: GeoFigureMixin (scale bar, north arrow),
│                              project_gdf_for_metric_operations (metric projection of a GeoDataFrame)
│
│   reports
├── report_blocks/         HTML engine with no domain: blocks, figures, tables, detail levels
├── overview/              report on the data before any simulation ([overview])
├── catchment_report/      catchment report (hmp report catchment <toml>)
│
│   outside the catalogue
├── viz.py                 hmp.viz.show(data): quick look at an array; unrelated to `hmp viz`
├── scalable.py            datashader rasterisation for viz.py
└── animation.py           GIF, MP4 or plotly slider from PNG already rendered
```

## Template of a figure

A figure is a class in `figures/<name>.py`. The file name does not start with `_`
(discovery skips those). Two models cover nearly everything.

**Map of a field, one value per mesh face**: a subclass of `ScalarFaceMap`, with no
`render` to write. Model: `figures/piezometric_map.py`.

```python
from hydromodpy.display.figure import FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._scalar_face_map import ScalarFaceMap


@register
class PiezometricMap(ScalarFaceMap):
    spec = FigureSpec(
        name="piezometric_map",  # the name written in [display].figures
        title="Water-table elevation",  # a quantity, never a solver or a provider
        kind="spatial",
        required_fields=("watertable_elevation",),
    )
    default_cmap = "viridis"
    default_overlays = ("watershed", "outlet")
```

**Time series, chart, anything else**: `BaseFigure` and a `render(sim, ax, **opts)`
method that draws on the axes it gets and returns them. Model: `figures/hydrograph.py`.
`BaseFigure.plot` builds the matplotlib figure, calls `render` and writes the PNG
with its provenance.

What `spec` declares decides whether the figure applies to a run:
`required_fields` (Zarr fields), `required_tables` (tables), `required_solvers`.
A need `spec` cannot express goes into an `unavailable_reason` override that calls
the base first and returns a sentence (model: `figures/lake_abacus_comparison.py`).
`render` may then assume the data is there.

## What each part answers

| part | question it answers |
|---|---|
| `figure.py` | what is a figure, and when does it apply to a run? |
| `figure_registry.py` | which class carries this figure name (or this former name)? |
| `figures/` | how is figure `<name>` drawn? |
| `config.py` | what does the `[display]` section of the project ask for? |
| `runs.py` | which figures does this run support, which to render, where to write them, which were skipped and why, under which matplotlib backend? |
| `png_metadata.py` | where does this PNG come from? |
| `maps/axes.py`, `maps/mesh_geometry.py`, `maps/ugrid.py`, `maps/transect.py` | how to draw a field on the mesh, a map, a section? |
| `maps/overlays.py` | which named layer to draw on this map? |
| `maps/geo/` | how to dress a vector map and project it to metres? |
| `style.py` | which theme, which colour, where does the legend go? |
| `report_blocks/` | how to assemble blocks, figures and tables into one HTML page? |
| `overview/` | what does the catchment look like before any simulation? |
| `catchment_report/` | which catchment report to build from a report TOML? |
| `viz.py`, `scalable.py` | how to look quickly at an xarray array, a series or a GeoDataFrame? |
| `animation.py` | how to chain PNG into an animation? |

## How data flows

**Figures of a run.**

```
TOML [display]  ->  DisplayConfig (config.py; names checked by figure_registry.resolve)
finished run    ->  runs.render_figures_for_run(run, DisplayConfig)
                      for each name: figure_registry.get(name)
                      unavailable_reason(run)? skipped, reason kept in FigureRenderReport
                      else BaseFigure.plot(run) -> render(run, ax) -> PNG + provenance
                ->  runs/<run>/<display.output_dir>/<name>.png
```

`hmp viz gallery` takes the same path. `hmp viz show`, `hmp.figure(...)` and the
export step go through `runs.render_figure`, which renders one figure after the
same applicability check. `hmp viz list --run <ref>` calls
`runs.figure_availability(run)`.

**Overview.** `workflow/pipelines/overview.py` builds a `DataOverviewState`
(geography and loaded data, no run); `overview.generate_overview_report` renders
one PNG per panel enabled in `[overview.panels]`.

**Catchment report.** `hmp report catchment <toml>` (options in
`hydromodpy/cli/commands/report.py`) calls
`catchment_report.pipeline.run_catchment_report_pipeline`. When asked, the pipeline
runs the overview and the simulation (subprocess `hydromodpy run`). It then builds
the context (`context.py`), copies the expected figures (`artifacts.py`), fills the
blocks (`block_specs.py`, `blocks.py`) and writes the page with `report_blocks`. A
context figure that cannot be drawn is logged with its reason.

## Where to add what

1. **A map of a field, one value per face.** Create `figures/<name>.py` on the
   model of `piezometric_map.py`. Add its line to `REGISTRY_CONTRACT` in
   `tests/unit/display/test_figure_registry_completeness.py` (class, `kind`,
   `required_fields`): the test refuses a figure missing from that table.
2. **A time series or a chart.** Create `figures/<name>.py` on the model of
   `hydrograph.py`: `@register`, `spec`, `render`. Dates on the x axis:
   `maps.axes.style_date_axis`. Same line in `REGISTRY_CONTRACT`. If the figure
   needs something `spec` cannot declare, override `unavailable_reason`;
   `tests/unit/display/test_every_figure_refuses_an_empty_run.py` fails otherwise.
3. **Rename a figure.** Change `spec.name`, put the old name in
   `spec.former_names`, update `REGISTRY_CONTRACT`. Project files that write the
   old name still load, with a warning.
4. **A helper shared by several figures.** A module `figures/_<name>.py`. If a
   shared tool or another layer needs it too, it does not belong in `figures/`: a
   root tool if it draws, `results` if it reads or computes.
5. **A layer drawn on maps.** A function `draw_<name>(ax, sim, *, timestep)` and a
   key in `maps.overlays.OVERLAYS`. Raise `OverlayUnavailable` when the run lacks the
   data: the layer is skipped, not the map.
6. **A panel of the overview.** A boolean in `OverviewPanelsConfig`
   (`overview/config.py`), the drawing function in `overview/panels.py`, its
   conditional call in `overview/report.py:generate_overview_report`.
7. **A block or a figure of the catchment report.** The declaration in
   `catchment_report/block_specs.py` (`ReportBlockSpec`, and one `BlockFigureSpec`
   per figure), the content in `blocks.py` (a function in `_CONTENT_BUILDERS`),
   the expected PNG in `artifacts.py` (`artifact_spec`).
8. **A read of a run that a figure needs.** In `results`, not in `display`: an
   existing public method of `Run`, else a module function of `results` that takes
   the run (models: `results/run/particles.py`, `results/calibration_trials.py`,
   `results.run.geographic.crs_epsg`).
   `Run` itself is capped at 50 public attributes
   (`tests/unit/results/test_run_surface.py`).
9. **An import rule.** A line in `tests/unit/architecture/display_layout.yaml`.

After a figure is added, the docs inventory regenerates with
`python -m tools.doc_figures` (the Sphinx build runs it too).

## What other layers import

Another package of `hydromodpy/` imports only these modules (the `public` list of
`display_layout.yaml`):

| module | for |
|---|---|
| `hydromodpy.display` | `get`, `list_figures`, `names`, `register`, `BaseFigure`, `FigureSpec` |
| `hydromodpy.display.config` | `DisplayConfig` |
| `hydromodpy.display.figure_registry` | `get`, `resolve`, `names` |
| `hydromodpy.display.runs` | rendering the figures of a run, and their availability |
| `hydromodpy.display.viz` | `hmp.viz` |
| `hydromodpy.display.maps.axes`, `hydromodpy.display.maps.ugrid`, `hydromodpy.display.maps.geo` | map tools reused by `reporting` |
| `hydromodpy.display.report_blocks` | HTML engine (`reporting`, and `calibration` through a tolerance) |
| `hydromodpy.display.overview`, `hydromodpy.display.overview.config` | overview and `OverviewConfig` |
| `hydromodpy.display.catchment_report`, `...catchment_report.pipeline` | catchment report |
| `hydromodpy.display.figures.lake_level_fit` | lake-level fit chart, read by `reporting` |

`calibration` reaches `display` only through the tolerance of `layer_matrix.yaml`,
and only `hydromodpy.display.report_blocks`. Tests and examples are not checked.

## Vocabulary

| word | meaning here |
|---|---|
| figure | a registered class that draws one thing from a run; its name is the one of `[display].figures` |
| `spec` | the static metadata of a figure: name, title, `kind`, what it requires from the run |
| `kind` | the plotting family (`spatial`, `section`, `timeseries`, `balance`, `particles`, `table`, `comparison`, `animation`), not the hydrological domain |
| unavailable | a figure the run cannot feed; it is refused or skipped with a sentence |
| overlay | a named drawing put on an existing map, skipped when the run lacks the data |
| panel | one image of the overview, drawn without a run |
| block | one section of a `report_blocks` HTML page: text, figures, tables |
| detail level | `compact`, `standard` or `audit`: what a block shows depending on the reader |
| face | one cell of the 2D mesh; `ugrid` draws one value per face |
