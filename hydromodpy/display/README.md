# `hydromodpy/display`

`display` draws. It takes a run that is already computed
(`hydromodpy.results.run.Run`) or data that is already loaded, and writes PNG
figures and HTML pages. It never runs a solver, never reads a raw solver file and
never writes into the storage of a run (Zarr, Parquet, DuckDB). Everything a
figure reads from a run goes through the public API of `results`. No module of `display` queries
the run directory by hand.

It holds three things of unequal weight:

1. the figure catalog of a run: the contract `figure.py`, the registry
   `figure_registry.py` and the figures of `figures/` (`hmp viz list` prints
   them);
2. the report engine `report/` (blocks to static HTML pages, the pages of a
   sealed run, of a data overview and of a calibration session, and the
   presets) and `overview/` (data before any simulation). The texts shown
   come from `project/report.py`, never from `display`;
3. shared plotting tools: `maps/` (map axes, mesh, overlays, sections) and
   `style.py` (theme, colormaps, legend placement).

## What a user can rely on

Figures are the part of HydroModPy the user sees most. Every figure follows five
rules.

1. A figure shows a quantity. It draws a field, a flux, a budget,
   a simulated series against an observed one, a mesh or a network, under the
   names of `results/field_registry.py`. It never tests a solver name, and neither
   its name nor its title names a solver or a data provider. The same figure
   works for MODFLOW-NWT, MODFLOW 6 and Boussinesq when the run holds the field.
2. A figure is offered only when the run has what it needs. `spec` declares
   the fields and tables it requires; a need that `spec` cannot express
   (a network, a DEM raster, hydrochemistry, the series of a stream reach, a
   lake or a piezometer, a particle that moved) is checked in the figure's own
   `unavailable_reason`. A figure that cannot draw a run is refused with a
   sentence on every surface: skipped with its reason by `[display].figures`,
   refused by `hmp viz show` and `hmp.figure`, marked as unavailable with its
   reason by `hmp viz list --run`. It never raises from inside `render` and never
   writes a placeholder PNG. A lumped run (GR4J) has no grid, so every map is
   refused and the discharge figures stay offered.
3. An instant is a date. A figure that draws one instant is asked for it by
   `time`: a date, `"first"` or `"last"`, in `[display] time` for the whole
   gallery or in `[display.overrides.<figure>]` for one. `runs._resolve_time`
   is the one place a date meets a run: it calls `run.periods.step_at` and hands the
   figure the step as `timestep`, the internal channel the maps read. The user
   never writes `timestep`. A file that writes it under `[display.overrides.<figure>]`
   was written by a pre-release of 2.0, and the load refuses it with the sentence
   that points to the doctor of a 2.0.x release. A `DisplayConfig` built from a
   dict refuses it as an option the figure does not take.
   A date the run does not hold skips the figure with its reason.
4. An option is a parameter. The keys `[display.overrides.<figure>]` takes
   are the named parameters of the figure's `plot` and `render`, read along the
   MRO while a `**` parameter forwards them (`figure.option_names_of`). A key
   the figure does not take is refused at config load, with the list. A new
   figure option therefore needs no declaration beyond its parameter.
5. A figure has one name, written on every surface:
   `[display].figures`, `hmp viz show <run> <name>` and `hmp.figure(run, "<name>")`.
   A renamed figure keeps its old name in `former_names`, so project files that
   use it still load. `[display]` fields are `USER` when they choose what to
   show (`figures`, `overrides`), `DEV` when they tune
   rendering (`backend`, `dpi`).

Two figures need a second run, which `spec` cannot declare yet: `difference_map`
and `side_by_side`. They are drawn from Python with `reference=<run>` and refuse
with a sentence without it.

## Import rules

Outside the package, `display` imports only `core` and `results`
(`tests/unit/architecture/layer_matrix.yaml`). Inside, a unit (a root module or a
subpackage) imports only what its line allows. The rule that matters: **no shared
tool imports `figures/`**. Data a tool needs lives in the tool or in `results`,
never in a figure.

| unit | may import inside `display` |
|---|---|
| `figure_table`, `style`, `maps`, `png_metadata`, `quicklook`, `figure_options` | nothing |
| `figure` | `png_metadata`, `figure_options` |
| `figure_registry` | `figure`, `figure_table`; the names come from the generated `figure_table`, which imports nothing (no exception left: no module of `figures/` is imported to answer a name) |
| `figures` | `figure`, `figure_options`, `maps`, `style` |
| `config` | `figure_registry`, `figure_table` |
| `cohort` | `figure_registry`, `figure_table` |
| `run_comparison` | `maps` |
| `<init>` (the `__init__.py` docstring) | nothing |
| `runs` | `<init>`, `config`, `figure`, `figure_registry`, `figure_table`, `png_metadata`, `style` |
| `catalog_figures` | `figure_registry`, `figure_table`, `runs` (it parses `--opt NAME=VALUE` against the registry, so it cannot sit under `figure_options`, which the registry already reads) |
| `overview` | `style` |
| `report` | `config`, `figure_registry`, `figure_table`, `runs` (it draws the run figures a page needs and the run did not draw; it never imports `schema`) |

Every import counts: module level, inside a function, under `TYPE_CHECKING`.
`tests/unit/architecture/display_layout.yaml` holds the table and
`tests/unit/architecture/test_package_layouts.py` checks it. No module of `display` reads a `_private` attribute of another module;
ruff rule SLF001 checks it.

## Tree

```
hydromodpy/display/
├── __init__.py            docstring only; every name is imported from the module that defines it
│
│   the figure catalogue of a run
├── figure.py              contract: FigureSpec (metadata), BaseFigure (plot, render, unavailable_reason),
│                          the title and show_run_name options every figure takes (run_suffix), options_of
├── figure_options.py      what each figure option means: Opt on the parameter, shared aliases,
│                          describe_options; figure.options_of gives the catalog type, default, unit
├── figure_registry.py     figures (the registry instance on the common engine), get, resolve, names,
│                          list_figures, figure_option_names; it reads the table and imports nothing
│                          to answer a name
├── figure_table.py        the generated table: FIGURES, FORMER_NAMES, OPTIONS, PYTHON_ONLY_OPTIONS;
│                          literals only, regenerated by `python -m tools.figure_table`
├── figures/               one figure per file, flat, each named by the spec its class carries
│   ├── scalar_face_map.py    base of the "one value per mesh face" maps
│   ├── _stream_comparison.py, _flow_persistence.py, _trial_diagnostics.py,
│   │   _calibration_session.py, _hydrochem.py, _cohort.py, _observed.py,
│   │   _instant.py (how a title names the period it draws)
│   │                          helpers shared between figures (private to figures/)
│   ├── lake_level_fit.py      public helper, no spec, not a figure
│   └── <name>.py              the figures
│
│   rendering the figures of a run ([display])
├── config.py              DisplayConfig, the [display] TOML section
├── runs.py                render_figures_for_run (a run, the [display] list), render_figure (one figure),
│                          figure_options_from_run (the [display] a run was drawn with),
│                          figure_availability (what a run supports, and why not the rest),
│                          matplotlib_backend (Agg or interactive for the length of a render);
│                          _resolve_time turns a date into the stress period the run stored
├── catalog_figures.py     the verbs of `hmp viz` and `hmp export --figures` on a run found in the index:
│                          render one figure, draw again what a run recorded, list what it can feed,
│                          parse_figure_options
├── cohort.py              cohort figures of a campaign summary: names, draw_cohort_figures, ledger entry
├── run_comparison.py      the series and map figures of `hmp report compare`: draw_series, draw_maps
├── png_metadata.py        provenance written into each PNG (sim_id, field, step, EPSG, version,
│                          identity block of the run and its visible footer, which names the
│                          label, the rule and the date, or "unlabelled" without a seal)
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
│   └── geo.py                 scale_bar and north_arrow for a vector map on metric axes
│
│   reports
├── report/                the report engine (an `__init__` docstring, no README)
│   ├── engine.py              no domain: Metric, Picture, Table, Link, Prose, Block, LEVELS,
│   │                          write_pages (index.html, review/{compact,standard,audit,by_block}/,
│   │                          figures/, report.json)
│   ├── pages.py               run_blocks, sheet_blocks, overview_blocks, session_blocks,
│   │                          draw_named_figures; builds blocks, writes no HTML
│   └── presets.py             ReportTexts, PRESETS (research, management), preset_figures
├── overview/              panels of the data before any simulation ([overview])
│
└── quicklook/             a quick look at data, outside the catalogue; unrelated to `hmp viz`
    ├── viz.py                 viz.show(data): an xarray array, a series or a GeoDataFrame
    ├── scalable.py            datashader rasterisation for viz.py
    └── animation.py           GIF, MP4 or plotly slider from PNG already rendered
```

## Template of a figure

A figure is a class in `figures/<name>.py`. The file name does not start with `_`
(only helpers do). Nothing registers it by hand: `BaseFigure.__init_subclass__`
takes the name from the `spec` the class carries, and the generated table
`figure_table.py` is the list. After adding or renaming a figure, regenerate it:

```bash
python -m tools.figure_table
```

Two models cover nearly everything.

Map of a field, one value per mesh face is a subclass of `ScalarFaceMap`, with no
`render` to write. Model: `figures/piezometric_map.py`.

```python
from hydromodpy.display.figure import FigureSpec
from hydromodpy.display.figures.scalar_face_map import ScalarFaceMap


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

Time series, chart and anything else is a `BaseFigure` and a `render(subject, ax, **opts)`
method that draws on the axes it gets and returns them. Model: `figures/hydrograph.py`.
`FigureSpec.subject` says what the figure draws: `run` (the default),
`session` (a calibration session) or `runset` (several runs). `runs._subject_for`
resolves it once, before any refusal. A session figure asked on a run receives
`Session.of_run(run)` and `promoted=run`. When the run was not promoted, or the
subject is of the wrong kind, the figure is refused with `NOT_PROMOTED_REASON`,
`NOT_A_RUNSET_REASON` or `NOT_A_RUN_REASON`. `hmp viz list` shows the subject.
`BaseFigure.plot` builds the matplotlib figure, calls `render` and writes the PNG
with its provenance. A figure that lays out its own figure may define its own
`plot`: `BaseFigure.__init_subclass__` wraps it so that it still takes the common
`title` and `show_run_name` options, with nothing to write for them.

What `spec` declares decides whether the figure applies to a run:
`required_fields` (Zarr fields) and `required_tables` (tables).
A need `spec` cannot express goes into an `unavailable_reason` override that calls
the base first and returns a sentence (model: `figures/lake_abacus_comparison.py`).
`render` may then assume the data is there.

## What each part answers

| part | question it answers |
|---|---|
| `figure.py` | what is a figure, and when does it apply to a run? |
| `figure_registry.py` | which class carries this figure name (or this former name)? |
| `figure_options.py` | what does each option of a figure do, in which unit, with which default? |
| `figures/` | how is figure `<name>` drawn? |
| `config.py` | what does the `[display]` section of the project ask for? |
| `catalog_figures.py` | how are the figures of a run found through the index of a project drawn, listed and given typed options? |
| `runs.py` | which figures does this run support, which to render, where to write them, which were skipped and why, under which matplotlib backend? |
| `png_metadata.py` | where does this PNG come from? |
| `maps/axes.py`, `maps/mesh_geometry.py`, `maps/ugrid.py`, `maps/transect.py` | how to draw a field on the mesh, a map, a section? |
| `maps/overlays.py` | which named layer to draw on this map? |
| `maps/geo.py` | how to put a scale bar and a north arrow on a vector map? |
| `style.py` | which theme, which color, where does the legend go? |
| `report/` | how to assemble blocks, figures and tables into one HTML page? |
| `overview/` | what does the catchment look like before any simulation? |
| `project/report.py` (outside `display`) | which texts and pages make the report of a run or a session? |
| `quicklook/viz.py`, `quicklook/scalable.py` | how to look quickly at an xarray array, a series or a GeoDataFrame? |
| `quicklook/animation.py` | how to chain PNG into an animation? |

## How data flows

Figures of a run.

```
TOML [display]  ->  DisplayConfig (config.py; names checked by figure_registry.resolve)
finished run    ->  runs.render_figures_for_run(run, DisplayConfig)
                      for each name: figure_registry.get(name)
                      unavailable_reason(subject)? skipped, reason kept in FigureRenderReport
                      else BaseFigure.plot(subject) -> render(subject, ax) -> PNG + provenance
                      png_metadata.stamp_png_identity: footer + identity text chunk
                ->  runs/<run>/figures/<name>.png, recorded in runs/<run>/figures/index.json
```

Cohort figures. `figures/cohort_map.py` and `figures/cohort_distribution.py`
draw one table with one row per site, not a run; `figures/_cohort.py` reads
the columns they share. `hmp campaign collect` (`project/launch/summary.py`) draws them with `cohort.py`
under `summary/figures/` for each name of `[sites.summary] figures`.

`hmp export <run> --regen figures` replays `figures/index.json` (`runs.regen_figures`).
`hmp viz show` and `hmp.figure(...)` go through `runs.render_figure`, which
renders one figure after the same applicability check and stamps a saved PNG
with the identity of its run. `hmp viz list --run <ref>` calls
`runs.figure_availability(run)`.

The figures are drawn after the seal (step order: derive, export, seal,
display). `DisplayStep` opens the run by `open_run_dir`, so every figure carries
the labelled identity in its footer: `<site> · <period> · HydroModPy <v> · <label>,
rule <n>, <date>`, or `unlabelled` without a seal.

Overview. `workflow/overview.py` builds a `DataOverviewState`
(geography and loaded data, no run); `overview.generate_overview_report` renders
one PNG per panel enabled in `[overview.panels]`, under `runs/<overview>/figures/`.
The inventory of the loaded data is written at the seal to
`tables.parquet/data_inventory.parquet`. The page is written after the seal
under `runs/<overview>/report/` by `report.pages.overview_blocks` and
`report.engine.write_pages`.

Reports. `hmp report catchment RUN` reads a sealed run. `project/report.py`
(`report_run`, `report_session`) is the one place that assembles the texts
(`results/method.py`, `schema/phrases.py`) and the pages: it hands `display.report`
the texts and the blocks, and `engine.write_pages` writes
`runs/<run>/report/index.html`, its review pages under `report/review/`, the
figures under `report/figures/` and `report.json`. A figure of the preset that
cannot be drawn is logged with its reason. `hmp report render` and
`hmp calibrate` call `report_session` for a calibration session.

## Where to add what

1. A map of a field, one value per face: create `figures/<name>.py` on the
   model of `piezometric_map.py`, then run `python -m tools.figure_table`:
   a test regenerates the table in memory and fails while the file is stale.
2. A time series or a chart: create `figures/<name>.py` on the model of
   `hydrograph.py`: `spec`, `render`. Dates on the x axis:
   `maps.axes.style_date_axis`. Regenerate the table. If the figure
   needs something `spec` cannot declare, override `unavailable_reason`;
   `tests/unit/display/test_every_figure_refuses_an_empty_run.py` fails otherwise.
3. Rename a figure: change `spec.name`, put the old name in
   `spec.former_names`, regenerate the table. Project files that write the
   old name still load, with a warning.
4. A helper shared by several figures is a module `figures/_<name>.py`. If a
   shared tool or another layer needs it too, it does not belong in `figures/`: a
   root tool if it draws, `results` if it reads or computes.
5. A layer drawn on maps: a function `draw_<name>(ax, sim, *, timestep)` and a
   key in `maps.overlays.OVERLAYS`. Raise `OverlayUnavailable` when the run lacks the
   data: the layer is skipped, not the map.
6. A panel of the overview: a boolean in `OverviewPanelsConfig`
   (`overview/config.py`), the drawing function in `overview/panels.py`, its
   conditional call in `overview/report.py:generate_overview_report`.
7. A block of a report page: a function of `report/pages.py` that returns
   `Block` objects, called by `run_blocks`, `session_blocks` or
   `overview_blocks`. The figures a preset draws are in `report/presets.py`.
   The words shown are a field of `ReportTexts`, filled in `project/report.py`.
8. A read of a run that a figure needs goes in `results`, never in `display`: an
   existing public method of `Run`, else a module function of `results` that takes
   the run (models: `results/run/particles.py`, `results/calibration_trials.py`,
   `results.run.geographic.crs_epsg`).
   `Run` itself is capped at 50 public attributes
   (`tests/unit/results/test_run_surface.py`).
9. An import rule is a line in `tests/unit/architecture/display_layout.yaml`.

A new figure appears in the figure catalog of the documentation at the next
build: `tools/docs/catalogs.py` reads `list_figures()`.

## What other layers import

Another package of `hydromodpy/` imports only these modules (the `public` list of
`display_layout.yaml`):

| module | for |
|---|---|
| `hydromodpy.display.figure` | `BaseFigure`, `FigureSpec` |
| `hydromodpy.display.config` | `DisplayConfig` |
| `hydromodpy.display.figure_registry` | `get`, `resolve`, `names`, `figure_option_names` |
| `hydromodpy.display.runs` | rendering the figures of a run, and their availability |
| `hydromodpy.display.cohort` | the cohort figures `hmp campaign collect` draws under `summary/figures/` |
| `hydromodpy.display.run_comparison` | the figures of `hmp report compare` (`analysis`) |
| `hydromodpy.display.maps.axes`, `hydromodpy.display.maps.ugrid`, `hydromodpy.display.maps.geo` | map tools reused by other layers |
| `hydromodpy.display.report.*` | the report engine, the pages and the presets (`project/report.py`) |
| `hydromodpy.display.overview`, `hydromodpy.display.overview.config` | overview and `OverviewConfig` |
| `hydromodpy.display.figures.lake_level_fit` | lake-level fit chart from two series |

`calibration` does not import `display`. Tests and examples are not checked.

## HTML block reports

`report/engine.py` is the common renderer of static reports built from reusable
blocks. It knows no run. `report/pages.py` builds `Block` objects (with `Metric`,
`Picture`, `Table`, `Link` and `Prose` inside them) from a sealed run, a data
overview or a calibration session. `report/presets.py` holds `ReportTexts` and the
two presets, `research` and `management`, with the figures each one names.
`write_pages(out, *, title, subtitle, blocks, levels=True, lang="en", label="",
rendered)` writes `index.html`, `review/{compact,standard,audit,by_block}/`,
`figures/` and `report.json`. With `levels=True` each page shows the detail
levels `compact`, `standard` and `audit` of `LEVELS`.

The words on a page come from `project/report.py`, because `display` never
imports `schema`. The engine is used by the overview, the catchment report, the
calibration session report and the network and transient calibration page of
`validation_cases/calibration/network_transient_b0/`.

## Figure contract

```python
@dataclass(frozen=True, slots=True)
class FigureSpec:
    name: str
    title: str
    former_names: tuple[str, ...] = ()
    # spatial, section, timeseries, balance, particles, table, comparison, animation
    kind: FigureKind = "spatial"
    required_fields: tuple[str, ...] = ()
    optional_fields: tuple[str, ...] = ()
    required_tables: tuple[str, ...] = ()
    default_figsize: tuple[float, float] = (7.0, 5.0)
    subject: FigureSubject = "run"  # run, session or runset


class BaseFigure(ABC):
    name: ClassVar[str]
    spec: FigureSpec

    @abstractmethod
    def render(self, subject: Run | Session | RunSet, ax: Axes, **opts) -> Axes: ...

    def unavailable_reason(self, subject: Run | Session | RunSet) -> str | None: ...
```

`optional_fields` lists fields the figure reads when they are there. The rule
is the membership: every `BaseFigure` subclass of a public module of
`figures/` is in the generated table under its `spec.name`, and the registry
finds the class from it. The list of figures is
generated from the table into the figures page of the documentation, and
`hmp viz list` prints the live list. A run reaches data only through `Run`
(`run.field`, `run.timeseries`, `run.budget`) or a module function of `results`.

## Vocabulary

| word | meaning here |
|---|---|
| figure | a `BaseFigure` subclass of `figures/` that draws one thing from a run; its name is the one of `[display].figures` |
| `spec` | the static metadata of a figure: name, title, `kind`, what it requires from the run |
| `kind` | the plotting family (`spatial`, `section`, `timeseries`, `balance`, `particles`, `table`, `comparison`, `animation`); the hydrological domain stays out of it |
| unavailable | a figure the run cannot feed; it is refused or skipped with a sentence |
| overlay | a named drawing put on an existing map, skipped when the run lacks the data |
| panel | one image of the overview, drawn without a run |
| block | one section of a `report/engine.py` HTML page: text, figures, tables |
| subject | what a figure draws: `run`, `session` or `runset` |
| detail level | `compact`, `standard` or `audit`: what a block shows depending on the reader |
| face | one cell of the 2D mesh; `ugrid` draws one value per face |

## Key public symbols

- `hydromodpy.display.figure.{BaseFigure, FigureSpec}`
- `hydromodpy.display.figure_registry.{get, resolve, names, list_figures,
  figure_option_names}` and the registry instance
  `hydromodpy.display.figure_registry.figures`
- `hydromodpy.display.figure_options.Opt` and `hydromodpy.display.figure.options_of`
- `hydromodpy.display.runs.{render_figures_for_run, render_figure,
  figure_availability}`
- `hydromodpy.display.config.DisplayConfig`
- `hydromodpy.display.report.engine.{Block, Metric, Picture, Table, Link, Prose,
  LEVELS, write_pages}`
- `hydromodpy.display.report.pages.{run_blocks, sheet_blocks, overview_blocks,
  session_blocks, draw_named_figures}`
- `hydromodpy.display.report.presets.{ReportTexts, PRESETS, preset_figures}`

## Layer neighbors

`display` imports `core` and `results`
(`tests/unit/architecture/layer_matrix.yaml`), never `data`, `model`,
`solver`, `calibration` or `catchment`. A figure of the stream criterion or of the routing surface only draws:
the network, the extents, the routing surface and the depression floods are computed in
`results/derive/stream/`. The root facade, `config`, `analysis`,
`workflow`, `project` and `cli` import it, each through the modules of the
`public` list of `display_layout.yaml`.

## Reading path

1. `figure.py` for the contract, then `figure_registry.py` and the generated
   `figure_table.py`.
2. One simple figure, `figures/hydrograph.py`, and one map,
   `figures/piezometric_map.py`.
3. `report/engine.py` for the HTML contract.
4. `report/pages.py` for the blocks of a run, then `project/report.py` for the
   texts and the call that writes a whole report.
