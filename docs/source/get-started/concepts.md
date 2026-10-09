# Concepts

Four words name the things on disk. This page is the whole mental model you need before the
{doc}`staircase <staircase/index>`.

```text
~/hydromodpy/                          workspace
├── workspace.toml
├── data/                              inputs shared by every project
│   ├── dem/
│   ├── hydrometry/
│   └── ...                            27 folders, one per variable
└── projects/
    ├── example/                       a project: the synthetic demo
    │   ├── project.toml               marks the root of the project
    │   ├── run_demo.toml              a file you run
    │   ├── runs/demo/                 a run
    │   ├── share/demo/                its exports
    │   └── .hmp/index.duckdb          the catalog
    └── 04_streamflow_intermittence_in_transient/
        ├── project.toml
        ├── step1_minimal.toml ...
        └── sessions/                  calibration sessions
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
runs write. Create one with `hmp project new <name>`; list them with `hmp project list`.

**Run.** One execution of one TOML file. It writes a folder `runs/<name>/`, where `<name>`
is the {toml}`simulation.name` of the file. The folder holds the frozen resolved config
(`config.toml`), the fields (`fields.zarr`), the tables (`tables.parquet`), the figures and,
written last, `manifest.json`. These are open formats: `xarray`, `zarr` and `pandas` read a
run without HydroModPy. Running an unchanged file again does nothing; an edited file makes
`<name>.v2` (see {doc}`staircase/index`).

**Catalog.** The index of the runs of one project, a DuckDB file at `.hmp/index.duckdb`.
`hmp catalog ls` lists the runs. The disk is the truth and the catalog is derived from it:
`hmp catalog reindex` rebuilds it from `runs/` and `sessions/`, and
{ref}`the guide <catalog-reindex>` says what a rebuild cannot restore.

## Reading a TOML file

- {toml}`workflow.mode` is required. It picks the operation that `hmp run` starts:
  `simulation`, `calibration`, `overview`, `comparison`, `testbed` or `site_selection`. The
  {doc}`guides <../guides/index>` take one task each.
- Each section is a request: what to model or produce, when, where. The
  {doc}`parameter reference <../reference/parameters/index>` groups the sections by the
  question they answer, and marks each key for the user, the developer or the expert (the
  [profiles](../reference/parameters/grammar.md#profiles)).
- A file names a parent with `base_config` and writes only what changes. The staircase is
  built this way. The merge rules are in the {doc}`grammar <../reference/parameters/grammar>`
  and {doc}`../guides/inheritance` shows how to build a family of files.

Next: the {doc}`quick start <index>`, or the {doc}`staircase <staircase/index>` if you have
already run the demo.
