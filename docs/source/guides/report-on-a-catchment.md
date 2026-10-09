# Report on a catchment

You have run a model of one catchment and want one web page that shows it: the site, the
hydraulic properties, the stream network, the simulated and observed discharge, the
water budget. `hmp report catchment` builds that page, as blocks of figures and tables,
from one report file. It also writes three more views of the same blocks, from a short
read to a full audit. The page, its titles and its captions are in English.

The report file is not a simulation file. The simulation file makes the outputs. The
report file says where to find them, and which steps to run before the page is built.

```{hmp-task}
Task
: Build one web page of a modelled catchment, and four views of it, from a report file.

Time
: 2 min 17 s when measured on a busy machine, with the overview and the simulation of step 4 run first. Rebuilding the page alone takes 5 s.

Needs
: A simulation file of example 04 that runs (`step4_transient.toml`), and optionally a CSV of observed discharge.

Gives
: `<output_dir>/web/index.html`, four views under `web_review/`, and `block_report_postflight.json` that lists the figures the page expected.
```

## What you need first

- A project with a simulation file that runs, such as `step4_transient.toml` of example 04
  (`examples/projects/04_streamflow_intermittence_in_transient`). The report reads its
  discharge from the run catalog, so no export has to be switched on.
- The run figures the page shows, listed in {toml}`display.figures` of that simulation
  file. Step 1 adds them.
- Optionally, the overview figures of the catchment (identity card, maps, station
  inventory), made by a file with {toml}`workflow.mode` set to `overview`. Step 2 writes it.
- Optionally, a CSV of observed discharge with the columns `datetime` and `value`. It is
  a figure of the report and never an input of the model.

In this guide the report file sits in the project folder, next to the simulation file.
Every relative path in the report file is resolved from the folder that holds it.

## 1. Ask the simulation for the report figures

The page copies figures that a run draws at its end. Write a small file that inherits
`step4_transient.toml`, gives the run a name of its own, and lists the figures. A list
replaces the one it inherits, so the file writes the whole list.

```toml
base_config = "step4_transient.toml"

[simulation]
name = "nancon_report"

[simulation.results.derived]
accumulation_flux = true

[display]
time = "2002-10-15"
figures = [
    "hydrograph",
    "water_budget",
    "piezometric_map",
    "seepage_map",
    "simulated_active_network_reference_overlay",
    "hydrographic_network_reference",
]
```

Save it as `run_report.toml`. Each name is a figure the run writes as
`runs/<run>/figures/<name>.png`. The report reads ten run figures. Example 04 can draw the six
above. The other four compare a network generated from the DEM with the reference one:
`hydrographic_network_generated`, `hydrographic_network_comparison`,
`hydrographic_network_reference_missing_only` and `hydrographic_network_generated_extra_only`.
They need a generated network, which example 04 does not build, so the page shows what it has.
`accumulation_flux` is the derived field that `simulated_active_network_reference_overlay` reads.
A figure whose requirements the run does not meet is skipped with a reason. A figure that
applies but fails while it is drawn follows {toml}`display.on_error`.

```{hmp-params}
display.figures
display.time
display.on_error
simulation.results.derived.accumulation_flux
```

Check the file before any run:

```bash
hmp config check run_report.toml
```

## 2. Make the overview figures

The first blocks of the page (identity card, station inventory, regional map, DEM,
geology, reference hydrography, climate) come from the overview of the catchment. It is a
file with {toml}`workflow.mode` set to `overview` and an {toml}`overview` section.
`hmp run` on it writes the PNG files under `share/figures/overview/` of the project.
{doc}`describe-a-catchment` explains the section and its panels. This file reads the local
data of step 2 of example 04, so it needs no network:

```toml
base_config = "step2_local_data.toml"

[workflow]
mode = "overview"

[overview]
name = "Nancon"
date_start = "2000-01-01"
date_end = "2002-12-31"
```

Save it as `run_overview.toml`. Step 2 loads no geology and no rain, so the geology map and
the climate bars stay empty or absent. Add those families to the file, as
{doc}`describe-a-catchment` shows, to fill them.

If you skip this step, the page is built without those figures. The postflight report
lists them as missing (step 5).

## 3. Write the report file

The report file has two required tables, `[report]` and `[layout]`. `[context]` and
`[pipeline]` are optional. `hmp report catchment` reads this file, not the project loader,
so `hmp config check` does not read it. The command checks it against its own model before
any step runs: a key it does not know, a missing key, a quoted boolean or an unknown preset
stops it at once, with the line of the file, and the exit code 14.

```toml
[report]
site_label = "Nancon"
station_label = "Nancon outlet"
output_dir = "outputs/report"

[layout]
watershed_project_dir = "."
context_outputs_dir = "outputs/context"
simulation_name = "nancon_report"
transient_config_name = "run_report.toml"
overview_config_name = "run_overview.toml"

[pipeline]
run_overview = true
run_simulation = true

[context.observed_discharge]
path = "../../data/hydrometry/hydrometry_custom_NANCON_19820201_20220125_D.csv"
station_id = "NANCON"
```

Save it as `catchment_report.toml`, next to `run_report.toml`. Replace the observed
discharge path by your own CSV. Without the `[context.observed_discharge]` table, or if the
file named by `path` does not exist, the report shows the simulation alone, and a warning
names the file:

```text
[WARNING] Catchment report: observed discharge file <path> not found; the report shows the simulation alone.
```

Every key of the four tables, with its default, its type and its meaning, is in the generated
reference: {doc}`../reference/parameters/report-file`. Four things need a word here.

- {toml}`layout.simulation_name` must be the {toml}`simulation.name` of the simulation file.
  If the name was used before, the run is registered as `<name>.vN`, and the report takes the
  newest completed one. A name written with a version, such as `nancon_report.v2`, is read as
  written. Its default is `transient_nwt`, the name of a run of the example projects: write
  yours.
- {toml}`layout.simulation_workspace_dir` and {toml}`layout.data_overview_project_dir` name the
  project of the run and the project of the overview when they are not the project of the
  simulation file. Both default to {toml}`layout.watershed_project_dir`.
- {toml}`pipeline.run_overview` and {toml}`pipeline.run_simulation` say which runs start before
  the page is built. An option of the command wins over the file, as the table below shows.
  The other keys of `[pipeline]` are `build_context_artifacts`, `build_report_html`, `no_lock`,
  `stream_run_logs` and `strict_figure_postflight`.
- The legend of the geology block is read from a geological map. Without a table, the BRGM
  GeoPackages that the geology loader cached for you are tried, the newest first, until one
  covers the catchment. To name the map, add {toml}`context.geology.path`:

  ```toml
  # not checked: fragment of the report file
  [context.geology]
  path = "geology/map.gpkg"
  ```

## 4. Build the report

```bash
hmp report catchment catchment_report.toml
```

With the file above, the command runs the overview, runs the simulation, checks that the
run is in the catalog and that its figure folder exists, builds the context, builds the
page and writes the postflight report. It prints the paths it wrote, one per line:

```text
overview_config=.../run_overview.toml
simulation_config=.../run_report.toml
context_summary=.../outputs/context/context/nancon_gauged_context_summary.json
html_report=.../outputs/report/web/index.html
postflight_report=.../outputs/report/block_report_postflight.json
```

The logs of the two runs are kept. The command prints the tail of a run that fails, and
nothing from a run that succeeds. `--stream-run-logs` prints everything.

These options pick the steps for one call:

| Option | Effect |
|---|---|
| `--run-overview`, `--no-run-overview` | Run the overview file, or not. |
| `--run-simulation`, `--no-run-simulation` | Run the simulation file, or not. |
| `--context-only` | Build the context files, not the page: `build_context_artifacts` on, `build_report_html` off. |
| `--report-only` | Build the page from the context files that exist: `build_context_artifacts` off, `build_report_html` on. The two runs are skipped unless you name them. |
| `--with-lock` | Do not pass `--no-lock` to the runs. |
| `--stream-run-logs`, `--no-stream-run-logs` | Print the logs of the runs, or keep them (`stream_run_logs`). |
| `--strict-figure-postflight`, `--no-strict-figure-postflight` | Fail on a missing figure, or not (`strict_figure_postflight`). |
| `--preset` | Name the preset, `generic` or `generic_catchment_report`. They are the only two, and the same preset. |

`--context-only` and `--report-only` exclude each other. Once the run is done, rebuild
only the page, after a change of title or label, with:

```bash
hmp report catchment catchment_report.toml --report-only
```

The full list is in the {doc}`reference of the command <../reference/cli/report>`.

## 5. Check that it worked

Open the `html_report` path in a browser. The page has the blocks site, hydraulic
properties, spatial context (DEM and geology), observed and generated hydrographic network,
simulated active network and seepage, fluxes (observed discharge and forcings), and simulated
fluxes. The audit view adds a block of artifacts and limits. For this guide the page carries
these control figures, among others:

```{figure} /_static/figures/guides/hydrograph.webp
:alt: Simulated discharge of the Nançon at its outlet from 2000 to 2003, with a flood in early 2001.
:width: 85%

`hydrograph`: the simulated discharge at the outlet. With an observed CSV, the page draws the observed series beside it.
```

```{figure} /_static/figures/guides/simulated_active_network_reference_overlay.webp
:alt: Map of the Nançon catchment with the simulated active cells in light blue and the reference river network in dark red. The legend gives the overlap scores.
:width: 85%

`simulated_active_network_reference_overlay`: the cells the model keeps active, against the mapped network, with the overlap scores of the legend.
```

The same run writes four more views under `<output_dir>/web_review`:

- `compact/index.html` for a fast read;
- `standard/index.html`, the same content as the main page;
- `audit/index.html` for sources, detailed tables, artifact links and limits;
- `by_block/index.html` to choose the level block by block.

Then open `block_report_postflight.json`, next to `block_report_manifest.json`. It lists
the figures the page expected, those it found, those it did not find (`missing_count`),
and those whose file is gone (`dangling_count`). `dangling_count` should be 0. With the files
of this guide, 22 figures are expected, 17 are present, and `missing_count` is 5: the geology map
(step 2 loads no geology) and the four figures of a generated network (the run has none). To
have 0, load geology in the overview file and give the run a generated network.

A `missing_count` above 0 does not fail the command, unless the strict postflight is on:
`strict_figure_postflight = true` in `[pipeline]`, or `--strict-figure-postflight`. The
expected list holds every figure of the preset, the ones a block marks as optional
included, so a strict run needs all of them.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `1 validation error(s) in <file>:` then `layout: Field required` (exit 14) | A required table is missing. | Add it. `[report]` and `[layout]` are required. |
| `report.output_dir: Field required` (exit 14) | A required key is missing in a table. The line of the file is given. | Add the key. |
| `layout.simulation_nam: Extra inputs are not permitted` (exit 14) | A key is misspelled. A table the model does not know is refused the same way. | Fix the key. The reference page lists them. |
| `pipeline: Value error, run_simulation = 'true' is quoted, so it is a string and not a boolean. TOML writes booleans unquoted: write run_simulation = true or run_simulation = false.` (exit 14) | A boolean is written between quotes. | Remove the quotes. |
| `report.preset: Input should be 'generic' or 'generic_catchment_report'` (exit 14) | The preset name is unknown. `--preset` accepts the same two names. | Use one of the two. |
| `context.observed_discharge.path: Field required` (exit 14) | The table `[context.observed_discharge]` exists and has no `path`. | Give the CSV, or remove the table. |
| `--context-only and --report-only are mutually exclusive.` (exit 14) | Two options at once. | Pick one. |
| `Catchment report preflight failed. Required inputs were not found:` then `- simulation config: <file>` or `- simulation run '<name>': <folder>/.hmp/index.duckdb` (exit 10) | `simulation config` is the file named by `transient_config_name`. The `simulation run` line says the catalog has no run of that name. `--report-only` asks for a `context summary` instead. | Run the simulation first, or set `run_simulation = true`. Check that `simulation_name` equals the name in the simulation file and that `simulation_workspace_dir` is the project that ran it. For `--report-only`, run `--context-only` or a full build first. |
| `Simulation completed but the catchment report expected outputs were not found:` followed by the run in the catalog and the `figures` folder of the run | The report file and the simulation file do not point to the same project or the same name. | Align `watershed_project_dir`, `simulation_workspace_dir` and `simulation_name`. |
| `--- hydromodpy run stdout (last N lines) ---`, then the same for stderr | A run of the pipeline failed. | Run the file alone with `hmp run run_report.toml` and fix it there. |
| `Catchment report figure postflight failed. Missing expected figures:` then the list and `Postflight report: <path>` (exit 16) | The strict postflight is on and a figure is missing. The page and the JSON are written first. | A missing figure comes from a run figure that step 1 did not list or that the run skipped with a reason, an overview figure if step 2 did not run, or a context image if the context step was skipped. |
| `[WARNING] Catchment report: observed discharge file <path> not found; the report shows the simulation alone.` | The CSV of `[context.observed_discharge]` is not there. | Check the path: it is read from the folder of the report file. |
| `[WARNING] Catchment report: no geology file to build the legend from; set [context.geology] path in the report file or load geology once.` | No `[context.geology]` table, and the user cache holds no BRGM map. The legend table is left out. | Add the table, or load geology once with a BRGM source. |
| `[WARNING] Catchment report: no geology legend, <files> do not cover the catchment.` | The maps tried do not cover the catchment. | Name a map that does. |

## Where to go next

- {doc}`Compare runs <compare-runs>` for a side-by-side of two runs.
- {doc}`Describe a catchment <describe-a-catchment>` for the data the overview reads.
- {doc}`Read the results of a run <read-the-results>` for what a run writes and how the
  catalog holds it.
- {doc}`Troubleshooting <troubleshooting>` for a run that fails before the report.
