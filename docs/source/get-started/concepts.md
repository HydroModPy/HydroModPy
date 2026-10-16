# Concepts

Six words name the things on disk. This page is the whole mental model you need before the
{doc}`staircase <staircase/index>`.

```text
~/hydromodpy/                          workspace
├── workspace.toml
├── data/                              inputs shared by every project
│   ├── dem/
│   ├── hydrometry/
│   ├── sites/catalog.csv              the sites you declared, optional
│   └── ...                            one folder per variable
└── projects/
    ├── example/                       a project: the synthetic demo
    │   ├── project.toml               marks the root of the project
    │   ├── run_demo.toml              a file you run
    │   ├── runs/demo/                 a run
    │   └── .hmp/index.duckdb          the catalog, rebuilt from runs/ and sessions/
    └── 04_streamflow_intermittence_in_transient/
        ├── project.toml               [site] names the catchment
        ├── step1_minimal.toml ...
        ├── runs/                      one folder per run
        ├── sessions/                  one folder per calibration
        └── trash/                     what you deleted, until you empty it
```

**Workspace.** A folder made by `hmp workspace init`, `~/hydromodpy` by default. It holds
the input data in `data/`, one flat folder per variable, and your projects in `projects/`.
Several projects share the same `data/`. A workspace is optional: a project folder alone
also works, with its input data in a `data/` folder next to `project.toml`. HydroModPy takes
the first of: {toml}`workspace.root` or {toml}`workspace.data_dir` in the file, the
`HMP_WORKSPACE` environment variable, the workspace that holds the project under
`projects/`, and the project folder itself.

**Project.** A folder that has a `project.toml`: that file marks the root. In a workspace it
is a subfolder of `projects/`. The project holds the TOML files you run and everything those
runs write. Create one with `hmp project new <name>`; list them with `hmp project list`. A
relative path written in any file of the project is read from this root.

**Site.** The catchment a file models: its name, and optionally a label, the gauge at its
outlet and a stable code. A file that models a real catchment declares it in `[site]`, with
{toml}`site.name` required. The gauge, {toml}`site.gauge`, is the station every observed
series and every score reads unless a section names another one. A project of many
catchments replaces `[site]` with `[sites]` and a table, one row per site
({doc}`many-catchments`).

**Run.** One execution of one TOML file. It writes a folder `runs/<name>/`, where `<name>`
is the {toml}`simulation.name` of the file, or the name of the file. The folder holds the
frozen resolved config (`config.toml`), the fields (`fields.zarr`), the tables
(`tables.parquet`), the inputs it read (`inputs.json`), its figures, exports and report, a
generated `README.md` and, written last, `manifest.json`. These are open formats: `xarray`,
`zarr` and `pandas` read a run without HydroModPy. Running an unchanged file again does
nothing; an edited file, or the same file with `--set`, makes `<name>.v2`. A run that failed
keeps its folder, with `outcome.json` saying why, and the next attempt resumes there.

**Session.** The record of one calibration, `sessions/<name>/`: its frozen configuration,
one line per trial in `trials.jsonl`, and the best trial. That best trial is promoted to a
run of the same name, `runs/<name>/`, which you read like any other run.

**Catalog.** The index of the runs and sessions of one project, a DuckDB file at
`.hmp/index.duckdb`. `hmp catalog ls` lists the runs. The disk is the truth and the catalog
is derived from it: `hmp catalog reindex` rebuilds it from `runs/` and `sessions/`, and
deleting `.hmp/` loses nothing. {doc}`Its reference <../reference/cli/catalog>` lists the
commands. Deleting a run moves it to `trash/`; a deleted name is never given out again.

## Reading a TOML file

- The sections say what `hmp run` does: a file with `[calibration]` calibrates, a file with
  `[overview]` and no `[simulation]` draws the overview, any other file simulates.
  {toml}`workflow.mode` names the operation when you want to write it out.
- Each section is a request: what to model or produce, when, where. The
  {doc}`parameter reference <../reference/parameters/index>` groups the sections by the
  question they answer, and marks each key for the user, the developer or the expert (the
  [profiles](../reference/parameters/grammar.md#profiles)).
- A file names a parent with `base_config` and writes only what changes. The staircase is
  built this way. The merge rules are in the {doc}`grammar <../reference/parameters/grammar>`.

Next: the {doc}`quick start <index>`, or the {doc}`staircase <staircase/index>` if you have
already run the demo.
