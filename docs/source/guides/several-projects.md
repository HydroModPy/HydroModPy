# Work with several projects

```{hmp-task}
Task
: Keep several projects in one workspace, find a run in any of them, and move a run from one to another.

Time
: Five minutes.

Needs
: HydroModPy installed, and at least one project with a run.

Gives
: A workspace layout, the list of registered projects, a search across all of them.
```

A project is one folder with its own `project.toml`, its run files, its runs and its index. A
workspace is the folder above: it holds several projects and the data they share. This page covers
the commands that work across projects. The commands that work inside one project are in
{doc}`find-and-compare-runs` and {doc}`clean-and-reindex-runs`.

## 1. Lay out a workspace

```bash
hmp workspace init ~/hydromodpy --project-name lab
hmp project new streams --workspace ~/hydromodpy
hmp project new wells --workspace ~/hydromodpy
```

```text
Project created: /home/me/hydromodpy/projects/wells

Files:
  /home/me/hydromodpy/projects/wells/project.toml   <- shared settings
  /home/me/hydromodpy/projects/wells/run_demo.toml   <- executable run
```

The layout is:

```text
hydromodpy/
  workspace.toml        who made it, the licence, the geographic scope
  data/<variable>/      the files and the cache shared by every project
  projects/
    streams/            project.toml, run files, runs/, share/, .hmp/index.duckdb
    wells/
```

What is shared is `data/`. A file you put in `data/dem/` is read by every project, and the cache of
downloaded data is filled once. What is not shared is everything else: each project has its own
runs and its own index, so a run belongs to one project.

```bash
hmp project list --workspace ~/hydromodpy
hmp project show streams --workspace ~/hydromodpy
```

```text
# workspace projects (2):
  streams  [project.toml, 3 run(s)]
  wells  [project.toml, 0 run(s)]
```

`3 run(s)` counts the run files (`run_*.toml`) of the project. `hmp project show` lists the run
files and the runs of its catalog, newest first.

`hmp project delete NAME` removes a project and its runs, and asks first. `-y` skips the question.

## 2. Register the projects

Commands that need to find a project outside the folder you are in read a machine-wide index of
projects. A project joins it when `hmp workspace init` scaffolds the workspace, and when a run
starts in it. `hmp project new` alone does not register a project.

```bash
hmp workspace list
hmp workspace register ~/hydromodpy
hmp workspace forget <project_id>
hmp workspace prune
```

`hmp workspace list` prints one row per project: `project_id`, `label`, `project_uri`,
`created_at` and `last_scanned_at`. `--json` gives the same rows as data. `register` takes a
project folder, or a workspace folder, which it expands into the projects it holds, and `--label`
names the registration. It prints the `project_id` of each project added. `forget` takes a
`project_id` from the list and leaves the files alone. `prune` drops the registrations whose index
has gone.

A project that never ran has no index yet. Every command that reads the index then prints one
line per such project:

```text
[WARNING] Skipping project 1d9b69f5-6b49-4fd1-a706-2b04e2fdc57a: catalog file missing at /…/projects/example/.hmp/index.duckdb
```

It is harmless. It stops when the project runs once, or when `hmp workspace prune` drops the
registration.

## 3. Find a run in any project

```bash
hmp workspace search nancon --limit 5
```

```text
# columns cut
project_id                           sim_id                               name                         project                                  description
02ef28ee-568b-49ac-8f59-e6b13e76d2d2 496ccc49-f00a-40de-bd6f-e50f71e59673 nancon_soil_reservoir_daily 04_streamflow_intermittence_in_transient Nancon, daily 2015-2020, …
```

The search reads the description of the run, the `[simulation] description` key of its file. A
run without a description has no text to find: search by name from Python instead.

```python
import hydromodpy as hmp

index = hmp.index()
df = index.find(name_like="sweep_k%", status="completed")
print(df[["project", "name", "sim_id", "duration_s"]])
```

`find` filters on `scientific_objective`, `solver`, `status` and `name_like`, and on any other
column of the table by keyword. A suffix gives a comparison: `duration_s_gt`, `duration_s_lte`
and so on, with `_gt`, `_gte`, `_lt`, `_lte` and `_like`. A keyword that is not a column is
dropped without a message, so check `df.columns`. The columns are `project_id`, `sim_id`, `name`, `project`, `status`, `solver`,
`solver_category`, `flow_regime`, `mesh_topology`, `study_area_name`, `scientific_objective`,
`description`, `contact_email`, `principal_id`, `bbox_xmin`, `bbox_ymin`, `bbox_xmax`, `bbox_ymax`,
`period_start`, `period_end`, `created_at`, `updated_at`, `duration_s`, `nse`, `kge`, `rmse` and
`r2`. Trashed runs are hidden unless `status="trashed"` is given.

The four score columns hold the scores of the head series at the station `__outlet__`. A run
scored on a gauged discharge, as the runs of example 04 are, leaves them empty, so `nse_gt=0.6`
finds nothing there. Read such scores run by run, with `run.metrics`, or rank them inside one
project with `@best:nse`.

To open a run you found, open its project and ask it for the run:

```python
projects = {p.project_id: p for p in index.list_projects()}
row = df.iloc[0]
catalog = hmp.open(projects[row.project_id].project_uri)
run = catalog[row.sim_id]
```

Open the index and the catalog of a project one after the other, and close each when you are done.
The index is read-only by default.

## 4. Move a run to another project

A run belongs to the project that made it. To copy it to another, write a package and import it
there. The two projects can sit in the same workspace:

```bash
hmp export nancon_step1_minimal all --format package -w ~/hydromodpy/projects/streams
hmp catalog import ~/hydromodpy/projects/streams/share/nancon_step1_minimal/nancon_step1_minimal.hmp \
    -w ~/hydromodpy/projects/wells --as streams_copy
```

```text
imported 1 run(s): a7c951a6
```

The copy keeps the `sim_id` of the original. `--as` names the project label of the copy. It is
needed when the receiving project already holds a run with that label. {doc}`share-a-run` explains
the package, what it holds, and what to check before you send one.

Both copies show up in a search, with their own `project_id`.

## 5. Clean up

```bash
hmp workspace clean --workspace ~/hydromodpy --results --dry-run
```

```text
Dry-run, would delete 4 path(s) in /home/me/hydromodpy:
  /home/me/hydromodpy/projects/streams/.hmp/index.duckdb
  /home/me/hydromodpy/projects/streams/runs
  /home/me/hydromodpy/projects/wells/.hmp/index.duckdb
  /home/me/hydromodpy/projects/wells/runs
Re-run with --yes to delete.
```

The groups are `--results` (the index and `runs/`), `--data-cache`, `--runtime` (`.hmp/`),
`--share`, `--scratch`, `--figures` and `--all`. Without `-y` the command only lists. It needs at
least one group. `--results` and `--runtime` delete the audit log with the index: read
{doc}`audit-and-purge` first.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `[WARNING] Skipping project <id>: catalog file missing at <path>/.hmp/index.duckdb` | The project is registered but never ran, or its folder moved | Run it once, or `hmp workspace prune` |
| `No catalog at <workspace>/.hmp. Run a workflow there first, or pass create=True to initialise an empty catalog. This folder holds projects with a catalog: … Open one of them.` | `hmp.open` was given the workspace folder | Open one of the project folders it lists |
| `No matches for 'x'.` | The term is not in any description | Give runs a `[simulation] description`, or use `hmp.index().find(name_like=...)` |
| `Project '<name>' already exists in this workspace. Use \`--as <new_name>\` to import under a different project name.` | A run of the same origin project is already in the receiving project | Add `--as NAME` to `hmp catalog import` |
| `Select at least one cleanup group, or pass groups={'all'}.`, exit 14 | `hmp workspace clean` without a group | Name a group, such as `--results`, or `--all` |
| `Reference 'x' not found.`, exit 10 | The run is in another project | Run the command with `-w` on the project that holds it |
| `The index '<path>' is already open in this process in another mode. …`, exit 12 | Two catalogs of one project open at once in a script, one read-only and one for writing | Close the first before opening the second. The file is not damaged |

## Next

- Hand a run to a colleague: {doc}`share-a-run`.
- Compare runs inside one project: {doc}`compare-runs`.
- Every option of the commands: {doc}`../reference/cli/workspace` and {doc}`../reference/cli/project`.
