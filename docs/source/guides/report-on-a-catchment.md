# Report on a catchment

You have run a model of one catchment and want one web page that shows it: the site, the
hydraulic properties, the river network, the simulated and observed discharge, the
water budget. `hmp report catchment` builds that page, as blocks of figures and tables,
from one report file. It also writes three more views of the same blocks, from a short
read to a full audit.

The report file is not a simulation file. The simulation file makes the outputs. The
report file says where to find them, and which steps to run before the page is built.

## What you need first

- A project with a simulation file that runs, such as `step4_transient.toml` of example 04
  (`examples/projects/04_streamflow_intermittence_in_transient`). The report reads its
  discharge from the run catalog, so no export has to be switched on.
- The run figures the page shows, listed in {toml}`display.figures` of that simulation
  file. Step 1 adds them.
- Optionally, the overview figures of the catchment (identity card, maps, station
  inventory), made by a file with {toml}`workflow.mode` set to `overview`. Step 2 writes it.
- Optionally, a CSV of observed discharge with the columns `datetime` and `value`.

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

[display]
time = "2002-10-15"
figures = [
    "hydrograph",
    "water_budget",
    "piezometric_map",
    "seepage_map",
    "simulated_active_network_reference_overlay",
    "hydrographic_network_reference",
    "hydrographic_network_generated",
    "hydrographic_network_comparison",
    "hydrographic_network_reference_missing_only",
    "hydrographic_network_generated_extra_only",
]
```

Save it as `run_report.toml`. Each name is a figure the run writes as
`runs/<run>/figures/<name>.png`. These ten are the only run figures the report reads. A
figure whose requirements the run does not meet is skipped with a reason, and the page
shows what it has. A figure that applies but fails while it is drawn follows
{toml}`display.on_error`.

```{hmp-params}
display.figures
display.time
display.on_error
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

The report file has two required sections, `[report]` and `[layout]`. `[pipeline]` and
`[context.observed_discharge]` are optional. `hmp report catchment` reads this file, not
the project loader, so `hmp config check` does not read it and the site has no card for
its keys. This page is their reference.

```toml
# not checked: report file
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
discharge path by your own CSV. If the file named by `path` does not exist, the report is
built without observed discharge and no message says so.

### The `[report]` section

| Key | Needed | Meaning |
|---|---|---|
| `site_label` | yes | Catchment name used in titles. |
| `station_label` | yes | Gauge or outlet name used in the site block. |
| `output_dir` | yes | Folder of the report. The page is `<output_dir>/web/index.html`. |
| `title` | no | Replaces the title of the page. |
| `preset` | no | `generic_catchment_report`, or its alias `generic`. These are the only presets. |

### The `[layout]` section

| Key | Needed | Meaning |
|---|---|---|
| `watershed_project_dir` | yes | Project folder that holds the simulation file. |
| `context_outputs_dir` | yes | Folder that receives the context files, under `context/` and `web/assets/`. |
| `data_overview_project_dir` | no | Project that holds the overview figures and the overview file. Default: `watershed_project_dir`. |
| `simulation_workspace_dir` | no | Project that holds the run catalog and the run. Default: `watershed_project_dir`. |
| `simulation_name` | no | Name of the run to describe. Default: `transient_nwt`. |
| `context_summary_name` | no | File name of the context summary under `<context_outputs_dir>/context`. Default: the only `*_gauged_context_summary.json` found there, else a name derived from `site_label`. |
| `transient_config_name` | no | Simulation file, under `watershed_project_dir`. Default: `run_<simulation_name>.toml`. |
| `overview_config_name` | no | Overview file, under `data_overview_project_dir`. Default: `config_overview.toml`. |

`simulation_name` must be the {toml}`simulation.name` of the simulation file. If the name
was used before, the run is registered as `<name>.vN`, and the report takes the newest
completed one. A name written with a version, such as `nancon_report.v2`, is read as
written.

### The `[pipeline]` section

It says which steps run when the command has no option. An option on the command line
wins over the file.

| Key | Default | Meaning |
|---|---|---|
| `run_overview` | `false` | Run the overview file first. |
| `run_simulation` | `false` | Run the simulation file first. |
| `build_context_artifacts` | `true` | Build the context summary, its page and its images. |
| `build_report_html` | `true` | Build the report page. |
| `no_lock` | `true` | Pass `--no-lock` to the two runs above. |
| `stream_run_logs` | `false` | Print the logs of the two runs instead of keeping them. |
| `strict_figure_postflight` | `false` | Fail the command if an expected figure is missing. |

A value that is not `true` or `false` stops the command with
`Catchment report config key 'run_simulation' must be a boolean.`, with the key you wrote.

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
| `--context-only` | Build the context files, not the page. |
| `--report-only` | Build the page from the context files that exist. The two runs are skipped unless you name them. |
| `--with-lock` | Do not pass `--no-lock` to the runs. |
| `--stream-run-logs`, `--no-stream-run-logs` | Print the logs of the runs, or keep them. |
| `--strict-figure-postflight`, `--no-strict-figure-postflight` | Fail on a missing figure, or not. |
| `--preset` | Name the preset, `generic` or `generic_catchment_report`. |

`--context-only` and `--report-only` exclude each other. Once the run is done, rebuild
only the page, after a change of title or label, with:

```bash
hmp report catchment catchment_report.toml --report-only
```

The full list is in the {doc}`reference of the command <../reference/cli/report>`.

## 5. Check that it worked

Open the `html_report` path in a browser. The page has the blocks site, hydraulic
properties, spatial context, hydrographic network, simulated network and seepage,
discharge and forcings, simulated fluxes, and, at the audit level, the artifacts and
limits. The titles and captions of the page are written in French.

The same run writes four more views under `<output_dir>/web_review`:

- `compact/index.html` for a fast read;
- `standard/index.html`, the same content as the main page;
- `audit/index.html` for sources, detailed tables and artifact links;
- `by_block/index.html` to choose the level block by block.

Then open `block_report_postflight.json`, next to `block_report_manifest.json`. It lists
the figures the page expected, those it found, those it did not find (`missing_count`),
and those whose file is gone (`dangling_count`). Both counts should be 0.

A `missing_count` above 0 does not fail the command, unless the strict postflight is on:
`strict_figure_postflight = true` in `[pipeline]`, or `--strict-figure-postflight`. The
expected list holds every figure of the preset, the ones a block marks as optional
included, so a strict run needs all of them.

## What can go wrong

**The report file is incomplete.** The command exits with code 14 and prints one of:

- `Missing [layout] section in catchment report config.` (or `[report]`);
- `Missing required catchment report config key: 'output_dir'.`

**A file or a run is not found.** The preflight stops before any step and exits with
code 10:

```text
Catchment report preflight failed. Required inputs were not found:
- simulation config: .../run_report.toml
- simulation run 'nancon_report': .../.hmp/index.duckdb
```

Read each line. `simulation config` is the file named by `transient_config_name`. The
`simulation run` line says the catalog has no run of that name: run the simulation first,
or set `run_simulation = true`, or check that `simulation_name` equals the name in the
simulation file and that `simulation_workspace_dir` is the project that ran it.
`--report-only` asks for a `context summary` instead, which `--context-only` or a full
build writes.

**The simulation ran but its outputs are not where the report looks.** The command
raises `Simulation completed but the catchment report expected outputs were not found:`
and lists the run in the catalog and the `figures` folder of the run. The report file and
the simulation file do not point to the same project or the same name.

**A run of the pipeline fails.** The command prints the tail of its output under
`--- hydromodpy run stdout (last N lines) ---` and the same for stderr, then stops. Run
the file alone with `hmp run run_report.toml` and fix it there.

**A strict postflight fails.** The command raises
`Catchment report figure postflight failed. Missing expected figures:` and the list, then
`Postflight report:` with the path. The page and the JSON are written first, so you can
read what is missing. A missing figure comes from one of three places:

- a run figure that step 1 did not list, or that the run skipped with a reason;
- an overview figure, if step 2 did not run;
- a context image, if the context step was skipped.

**Two options at once.** `--context-only and --report-only are mutually exclusive.`,
exit code 14.

**Unknown preset.** The option takes `generic` or `generic_catchment_report`. In the
file, any other name stops the command with
`Unknown catchment report preset 'x'. Choices: generic, generic_catchment_report.`

**An empty geology table.** The legend of the geology block is read from a BRGM
GeoPackage (`geology_brgm_50k_*.gpkg`, else `geology_brgm_1m_*.gpkg`) under
`examples/data/geology/` of the HydroModPy tree. Without one, the table is left out.

## Where to go next

- {doc}`Compare runs <compare-runs>` for a side-by-side of two runs.
- {doc}`Describe a catchment <describe-a-catchment>` for the data the overview reads.
- {doc}`Results and exports <results-and-exports>` for what a run writes and how the
  catalog holds it.
- {doc}`Troubleshooting <troubleshooting>` for a run that fails before the report.
