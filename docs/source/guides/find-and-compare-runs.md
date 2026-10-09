# Find and compare the runs of a project

```{hmp-task}
Task
: List the runs of a project, name one in a command, open it, compare two, and run one again with a change.

Time
: A second per command. A rerun costs one full run.

Needs
: A project with a few runs. With example 04, run `step4_transient.toml` and `step5_export.toml` from its folder. A shell in the project folder, or anywhere below it.

Gives
: A name for each run, a diff between two runs, a ranking on a metric, and a new run that records the old one as its parent.
```

Every run of a project is recorded in the catalog of that project. The commands are the
`hmp catalog` family. The same catalog is open from Python with `hmp.open`, shown in step 2.
To free disk and to rebuild the index, see {doc}`clean-and-reindex-runs`. To compare methods
on one case with a comparison file, see {doc}`compare-runs`.

The commands walk up to the first `project.toml` and use that folder as the project. From
elsewhere, pass `-w <project folder>`. The catalog is the file `.hmp/index.duckdb`. It is an
index: the truth is in the folders `runs/<name>/` and `sessions/<name>/`.

## 1. Name the runs so you can find them

A run takes its name from {toml}`simulation.name`. When the key is empty, the name is the
file name without `.toml` and without a leading `run_`. {toml}`simulation.tags` attaches
tags when the run is registered.

```toml
base_config = "step4_transient.toml"

[simulation]
name = "nancon_k_test"
tags = ["k-test"]
```

```{hmp-params}
simulation.name
simulation.tags
simulation.if_exists
```

What happens when you run a file again depends on whether the run is the same.

- **Nothing changed.** `hmp run` finds a completed run with the same identity and does not
  compute again. It prints two lines on the error stream and exits with code 0:

  ```text
  Config identical to completed run 'nancon_k_test' [9c41aa02]; nothing to do.
  Re-run with --force to run it again.
  ```

  `hmp run --force` computes anyway. `hmp.run(path)` and `hmp.run(cfg)` return the existing
  `Run` and log the same sentence, followed by `Pass force=True to run it again.`
- **Something changed.** A new run is registered. If the name is taken, the new run gets the
  next free version of it: `nancon_k_test`, then `nancon_k_test.v2`, then `nancon_k_test.v3`.
  The first run keeps the bare name for good.

The identity of a run is the resolved configuration without the per-run scratch folder, the
name of the run, and the parameter overrides of `Project.simulate`. Two names make two runs.
A run recorded by an older version of HydroModPy carries an older hash, so its first rerun
computes once. Only the simulation workflow skips. A partial run (`--resume`, `--from`,
`--until`, `--dry-run`) always proceeds, and so does every `Project.simulate` call, so a
sweep or a calibration loop keeps computing.

Change K and run the file again to see the second case. Example 04 gives K this value:

```{hmp-resolved} flow.param.K.field.value
:config: step4_transient.toml
```

```toml
base_config = "step4_transient.toml"

[flow.param.K.field]
value = 2e-5
```

The number only makes the file differ from the first run.

{toml}`simulation.if_exists` chooses what happens to the older run when the new one is
different. The default `"version"` keeps every run. `"replace"` sends the older run to the
trash and registers the new run under the next free version, as example 04 does in
`project.toml`. `"fail"` refuses to register a name that is taken.

```toml
base_config = "step4_transient.toml"

[simulation]
if_exists = "replace"
```

Check the file before you run it:

```bash
hmp config check step4_transient.toml
```

## 2. List the runs

::::{tab-set}
:::{tab-item} Command line
```bash
hmp catalog ls
```

The output has one block per project and one line per run, newest first:

```text
# project: <project folder name>
  <name>  [<id8>]  solver=<solver>  status=<status> <duration>s
```
:::
:::{tab-item} Python
```python
import hydromodpy as hmp

cat = hmp.open(".")                      # read-only by default
done = cat.frame[cat.frame["status"] == "completed"]
print(done[["name", "flow_regime", "n_timesteps", "duration_s"]])
```

`hmp.open` raises `FileNotFoundError` when the folder has no index. Given a workspace root
instead of a project folder, it names the projects under it that have a catalog. A
read-only catalog can be open while a run is solving.
:::
::::

`<id8>` is the first eight characters of the run id. It is the surest way to name a run in
the next commands. Filters combine:

| Option | Keeps |
|---|---|
| `--solver mf6` | runs of one solver. `mf6` and `nwt` are accepted for `modflow6` and `modflow_nwt`. |
| `--status completed` | runs with this status: `completed`, `running`, `failed`, `trashed`. |
| `--tag k-test` | runs that carry exactly this tag. |
| `--catchment <text>` | runs whose study area name contains the text. |
| `--project <name>` | one project of a workspace root. |
| `--limit 10` | the first ten rows. |

Trashed runs are hidden unless you ask for `--status trashed`. `--format json` and
`--format csv` print a fixed set of twelve columns, for scripts. The script `py5_catalog.py`
of example 04 goes on from the Python side. To list the runs of many projects at once, see
{doc}`several-projects`.

## 3. Name a run in a command

Every command that acts on one run takes a reference. These forms work:

| You write | It means |
|---|---|
| `nancon_k_test.v2` | the run with exactly this name |
| `nancon_k_test` | the run with exactly this name, else the newest live version of it. See the warning below. |
| `9c41aa02` | the run whose id starts with these characters, at least four. It must be unique. |
| the full id | that run |
| `@last`, `@last~1` | the newest completed run, the one before it |
| `@best:<metric>`, `@worst:<metric>` | the completed run with the best, or the worst, value of the metric at the outlet. Best follows the direction of the metric, see below. |
| `@running` | the newest run that is still running |

```{warning}
A bare name is looked up as an exact name first. While the first run of a name is live, it
owns the bare name, so `hmp catalog delete nancon_k_test` trashes that first run, not the
newest one. The newest version is reached only when no live run has the exact name. That
is the case after the first run went to the trash, which `if_exists = "replace"` does. To
act on one run for sure, write its `<id8>` or its `.vN` name.
```

`@best` and `@worst` read the direction of the metric from a table of the catalog, so
`@best:rmse` is the lowest error and `@best:nse` the highest score:

| The best value is | Metrics |
|---|---|
| the highest | `nse`, `nse_log`, `nse_delta`, `nse_seasonal`, `kge`, `kge_delta`, `kge_r`, `r2`, `correlation`, `reservoir` |
| the lowest | `rmse`, `mae`, `mse`, `objective_best`, the `closure_*` metrics |
| the closest to zero | `bias`, `pbias` |
| the closest to one | `kge_alpha`, `kge_beta` |

A metric that is not in the table is refused, instead of taking the highest value of an
error under the name of the best run. A value that is missing or not finite never ranks.

A reference that matches nothing stops with exit code 10 and a message that suggests the
closest names:

```text
Reference 'nancon_k_tset' not found. Run `hmp catalog ls` to list known runs. Closest: nancon_k_test.
```

A reference that matches several runs stops with exit code 20 and lists them:

```text
Reference '<text>' is ambiguous; matches <n> simulations:
```

## 4. Open one run

```bash
hmp catalog show nancon_k_test.v2
```

It prints the id, the project, the solver, the status, the duration, the number of cells and
of time steps, the exports, the version, the start of the config hash, the tags, the notes,
the metrics and the parameters. `--detail` adds the path and the groups of the Zarr store.
`--format json` prints the same facts for a script.

Tags and notes are yours. They are kept in the run folder, so they survive a rebuild of the
index.

```bash
hmp catalog tag nancon_k_test.v2 pinned --rm draft
hmp catalog note nancon_k_test.v2 "K lowered after the dry summer of 2001"
hmp catalog rename nancon_k_test.v2 nancon_k_low
```

- `pinned` is a reserved tag. It exempts the run from `hmp catalog gc`, and makes
  `hmp catalog delete` and `hmp catalog trash --empty` refuse it without `--force`.
  `hmp catalog delete --now` does not check it ({doc}`clean-and-reindex-runs`).
- `rename` moves the folder `runs/<old>/` to `runs/<new>/`. The new name must be free. A
  taken name stops the command with `Simulation '<name>' already exists in project
  '<project>' (existing sim_id <id8>). Use if_exists='replace' or 'version' to proceed.`
  The last sentence of that message is about runs, not about `rename`: choose a free name.

## 5. Compare runs

`hmp catalog diff` prints only what differs between two runs, their parameters and their
outlet metrics:

```bash
hmp catalog diff nancon_k_test nancon_k_test.v2
```

Each line has the form `name: <value in a> -> <value in b>`, and a block with no
difference prints `identical`.

To rank all completed runs on one score, query the view `v_simulation_summary`. It has
one row per run, with `nse`, `kge`, `rmse` and `r2` at the outlet:

```bash
hmp catalog query "SELECT name, nse, kge FROM v_simulation_summary WHERE status = 'completed' ORDER BY nse DESC"
```

Query the view, not the table `simulations`: the table stores keys, the view resolves them
into readable columns. The query is read-only.

In Python, a group of runs ranks itself on a metric:

```python
group = cat.find(status="completed", flow_regime="transient")
print(group.compare("nse", station="NANCON"))   # highest first
best = cat["@best:nse"]                          # the same selector as the command line
```

To compare a value inside the model, read the same cell in several runs with
`hmp catalog point`. {doc}`Read a value at a point <read-a-value-at-a-point>` shows how. To
compare two solvers or two settings on one case, build the runs from a comparison file:
{doc}`compare-runs`.

## 6. Run again with one change

`hmp catalog rerun` starts a new run from the configuration saved in a run folder
(`runs/<name>/config.toml`), after applying `--set` overrides:

```bash
hmp catalog rerun nancon_k_test --set flow.param.K.field.value=2e-4 --name nancon_k_high
```

`--set` takes a dotted path of the configuration and a value. A number is read as a number,
`true` and `false` as booleans, anything else as text. A path that does not exist stops the
command with a message that lists what the parent holds.

Without `--name`, the new run is called `<name>_rerun`, and the usual versioning applies
if that name is taken. The command ends with `reran as <name>  [<id8>]`. The new run
records the original as its parent. From Python, `hmp.Project.rerun` does the same, see
{doc}`drive-from-python`.

## How to check it worked

- Run the same file twice. The second `hmp run` prints `Config identical to completed run`
  and `hmp catalog ls` still shows one run.
- Edit a value and run again. `hmp catalog ls` shows the new run under the next `.vN`, and
  `hmp catalog diff` names the value you changed.
- `hmp catalog show <name>` prints the tags and the note you wrote.

## What can go wrong

| What you see | Why, and what to do |
|---|---|
| `No indexed project found under <path>` from `ls` | No `.hmp/index.duckdb` below this folder. Move to the project, pass `-w`, or run `hmp catalog reindex` if the folder has runs ({doc}`clean-and-reindex-runs`). |
| `No catalog at <path>` | Same cause for the other commands. |
| `skipping <project>: schema behind (run 'hmp doctor --migrate')` | The index was written by an older version. Run the command it names. |
| ``Reference '<text>' not found. Run `hmp catalog ls` to list known runs.`` (exit 10) | The name is misspelled, or the run is in the trash. The message lists the closest names. |
| `Reference '<text>' is ambiguous; matches <n> simulations:` (exit 20) | An id prefix or a name matches several runs. Write more of the id. |
| `'@best:<m>': Metric '<m>' has no declared direction, so best and worst are undefined for it.` (exit 10) | The metric is not in the table of step 3. Name one that is, or rank with `hmp catalog query`. |
| `Run <id8> is pinned; pass force=True (CLI --force) to act on it.` | The run carries the `pinned` tag. Remove the tag, or add `--force`. |
| `Nothing to do: pass tags to add or --rm TAG to remove.` | `tag` was called with no tag. |
| The run you delete is the wrong one | A bare name hits the first version. See the warning in step 3 and use the `<id8>`. |
| `hmp run` prints `nothing to do` and you wanted a new run | The run is identical to a completed one. Change the file, give it another name, or add `--force`. |
| `hmp run` computes again, although you changed nothing | The earlier run was recorded by an older version, or you started a partial run. The next identical run is skipped. |
| `ls` misses a run that is on disk | The index is behind the folders. Run `hmp catalog reindex`. |

The exit codes are listed in {doc}`/reference/cli/exit-codes`.

## Where to go next

- {doc}`clean-and-reindex-runs` deletes runs, frees disk and rebuilds the index.
- {doc}`share-a-run` hands a run to a colleague.
- {doc}`read-a-value-at-a-point` compares one cell across runs.
- {doc}`read-the-results` says what each run folder holds.
- {doc}`calibrate` creates many runs at once and promotes the best ones.
- The options of every command are in the {doc}`CLI reference </reference/cli/catalog>`.
