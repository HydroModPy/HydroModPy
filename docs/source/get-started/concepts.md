# Concepts

Four words name the things on disk. Three ideas explain every TOML file. This page is the
whole mental model; the rest of the documentation assumes it.

## Workspace, project, run, catalog

```text
~/hydromodpy/                          workspace
├── workspace.toml
├── data/                              inputs shared by every project
│   ├── dem/
│   ├── hydrometry/
│   └── ...                            one folder per variable
└── projects/
    └── 04_streamflow_intermittence_in_transient/    a project
        ├── project.toml               marks the root of the project
        ├── step1_minimal.toml         files you run
        ├── runs/
        │   └── nancon_step1_minimal/  a run
        ├── share/                     exports, one folder per run
        ├── sessions/                  calibration sessions
        └── .hmp/index.duckdb          the catalog
```

**Workspace.** A folder made by `hmp workspace init`, `~/hydromodpy` by default. It holds
the input data in `data/`, one flat folder per variable, and your projects in `projects/`.
Several projects share the same `data/`. A workspace is optional: a project folder with a
`project.toml` also works alone. The input data then sit in a `data/` folder next to
`project.toml`. HydroModPy looks for the data folder in this order and takes the first match:
{toml}`workspace.root` or {toml}`workspace.data_dir`, the `HMP_WORKSPACE` environment
variable, the workspace that holds the project under `projects/`, and last the project itself.

**Project.** A folder that has a `project.toml`: that file marks the root. In a workspace it is a subfolder of `projects/`.
The project holds the TOML files you run and everything those runs write. Create one with
`hmp project new <name>`; list them with `hmp project list`.

**Run.** One execution of one TOML file. It writes a folder `runs/<name>/`, where `<name>`
is the {toml}`simulation.name` of the file; without a name, runs are numbered `run_0001`,
`run_0002` and so on. The folder holds the frozen resolved config
(`config.toml`), the fields (`fields.zarr`), the tables (`tables.parquet`), the figures
and, written last, `manifest.json`. Everything is in open formats: `xarray`, `zarr` and
`pandas` read a run without HydroModPy.

**Catalog.** The index of the runs of one project, a DuckDB file at `.hmp/index.duckdb`.
`hmp catalog ls` lists the runs and `hmp catalog show <name> --detail` describes one. The
disk is the truth and the catalog is derived from it: delete the file and
`hmp catalog reindex` rebuilds it from `runs/` and `sessions/`. What no run folder carries
is lost in that rebuild: the audit log, the deletion records, the export log, the
workflow journal (an interrupted run can no longer be resumed), and the observation series
with their stations (the next run reads them again from the data files).

## The workflow mode picks the operation

Every file starts with a `[workflow]` table whose key {toml}`workflow.mode` is required.
`hmp run <file>.toml` reads it and starts the matching operation. Without it, `hmp run`
stops with a configuration error.

```{hmp-params}
workflow.mode
```

| Mode | What it does | Where to read more |
|---|---|---|
| `simulation` | One forward run. It writes one run folder. | {doc}`staircase/index` |
| `calibration` | Proposes parameters, runs candidate simulations and records the history. | {doc}`../guides/calibrate` |
| `overview` | Loads the geographic and data context and draws review maps. No solver runs. | {doc}`../guides/describe-a-catchment` |
| `comparison` | Runs several child simulations from one shared base and compares their observables. | {doc}`../guides/compare-runs` |
| `testbed` | Expands a case matrix, hands each case to a runner and collects evidence. | {doc}`../guides/test-a-method` |
| `site_selection` | Keeps or rejects candidate catchments and writes an HTML review report. | {doc}`../guides/select-catchments` |

`hmp run <file>.toml --dry-run` prints the mode it read and the sections of the file without
executing anything. Options such as `--resume` and `--force` apply to the `simulation` mode
only.

## A section is a request

A HydroModPy file is not a list of options. Each section is a request: **what** to model
or produce, **when**, **where**. Read a file as a set of requests and it makes sense without
knowing the code.

::::{tab-set}

:::{tab-item} Where
The catchment, cut out of a DEM upslope of an outlet point.

```{hmp-toml}
:file: step1_minimal.toml
:tables: geographic.catchment
```
:::

:::{tab-item} When
The simulated window, cut into stress periods of {toml}`simulation.time.step_value`.

```{hmp-toml}
:file: step4_transient.toml
:tables: simulation.time
```
:::

:::{tab-item} What
What the run writes, and for which instant. One `[[export]]` block per request.

```{hmp-toml}
[[export]]
variables = ["watertable_depth", "seepage_mask"]
time = "last"
```
:::

::::

The same idea runs through the sections: {toml}`display.figures` asks for figures,
{toml}`data.types` asks for data, {toml}`flow.param.K.field.value` asks for a value of K.
The {doc}`parameter reference <../reference/parameters/index>` groups the sections by the
question they answer.

## A file can inherit another one

A run file rarely repeats a whole model. It names a parent with `base_config` and writes
only what changes. The path is read from the folder of the file. The staircase of example
04 is built this way: step 2 inherits step 1, step 4 inherits step 2, and so on.

```{hmp-toml}
base_config = "step1_minimal.toml"

[simulation]
name = "nancon_k_1e-4"

[flow.param.K.field]
value = 1e-4

[[export__append]]
variables = "watershed_dem"
```

This file is a complete run: step 1 with another name, a K of 1e-4 instead of 5e-5, and
one more export. The merge follows five rules.

| You write | Result |
|---|---|
| a key the parent has | the parent's value is replaced |
| a table the parent has | the tables are merged, key by key |
| a list | it replaces the parent's list |
| `key__append = [...]` or `[[key__append]]` | the items are added to the parent's list |
| `key__delete = true` | the key is removed from the result, with everything under it |

Two lists of tables of the same length are merged table by table instead of replaced. The
{doc}`../reference/parameters/grammar` page gives the whole grammar, and
{doc}`../guides/inheritance` shows how to build a family of files from one parent.

## Profiles: user, dev, expert

Every field has a profile that says who needs it.

| Profile | For | Examples of what it holds |
|---|---|---|
| `user` | the hydrogeologist | physics, paths, project input and output |
| `dev` | the developer | tolerances, backends, cache flags |
| `expert` | the expert | internals of MODFLOW, Boussinesq, units |

The profiles are cumulative: `dev` shows the `user` fields and its own. A terminal command
takes the level, for example `hmp config template --profile user`, and the reference marks
the `dev` and `expert` fields with a badge. The {toml}`workflow.profile` key is a different
thing: it profiles the speed of a run.
