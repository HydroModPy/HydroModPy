# Find, compare and clean runs

Every run of a project is recorded in the catalog of that project. This guide shows how to
list the runs, open one, compare two, re-run one with a change, and delete what you no
longer need without losing something by mistake.

The commands are the `hmp catalog` family. The same catalog is open from Python with
`hmp.open`, shown in step 2.

## What you need first

- A project with a few runs. With example 04, run two files from its folder:
  `hmp run step4_transient.toml`, then `hmp run step5_export.toml`.
- A shell in the project folder, or anywhere below it. The commands walk up to the first
  `project.toml` and use that folder as the project. From elsewhere, pass
  `-w <project folder>`.

The catalog is the file `.hmp/index.duckdb`. It is an index: the truth is in the folders
`runs/<name>/` and `sessions/<name>/`, and {ref}`step 8 <catalog-reindex>` rebuilds the
index from them.

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

What happens when you run a file again depends on whether the resolved configuration
changed.

- **Nothing changed.** `hmp run` finds a completed run with the same resolved
  configuration and does not compute again. It prints
  `Config identical to completed run '<name>' [<id8>]; nothing to do.` and
  `Re-run with --force to run it again.` Only the simulation workflow does this, and
  `hmp run --force` computes anyway.
- **Something changed.** A new run is registered. If the name is taken, the new run gets
  the next free version of it: `nancon_k_test`, then `nancon_k_test.v2`, then
  `nancon_k_test.v3`. The first run keeps the bare name for good.

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

{toml}`simulation.if_exists` chooses what happens to the older run. The default `"version"`
keeps every run. `"replace"` sends the older run to the trash and registers the new run
under the next free version, as example 04 does in `project.toml`. `"fail"` refuses to
register a name that is taken.

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

```bash
hmp catalog ls
```

The output has one block per project and one line per run, newest first:

```text
# project: <project folder name>
  <name>  [<id8>]  solver=<solver>  status=<status> <duration>s
```

`<id8>` is the first eight characters of the run id. It is the surest way to name a run in
the next commands. Filters combine:

| Option | Keeps |
|---|---|
| `--solver mf6` | runs of one solver. `mf6` and `nwt` are accepted for `modflow6` and `modflow_nwt`. |
| `--status completed` | runs with this status: `completed`, `running`, `failed`, `trashed`. |
| `--tag k-test` | runs that carry exactly this tag. |
| `--catchment <text>` | runs whose study area name contains the text. |
| `--limit 10` | the first ten rows. |

Trashed runs are hidden unless you ask for `--status trashed`. `--format json` and
`--format csv` print a fixed set of twelve columns, for scripts.

In Python, the same list is a table:

```python
import hydromodpy as hmp

cat = hmp.open(".")                      # read-only by default
done = cat.frame[cat.frame["status"] == "completed"]
print(done[["name", "flow_regime", "n_timesteps", "duration_s"]])
```

`hmp.open` raises `FileNotFoundError` when the folder has no index. A read-only catalog can
be open while a run is solving. The script `py5_catalog.py` of example 04 goes on from
there.

## 3. Name a run in a command

Every command that acts on one run takes a reference. These forms work:

| You write | It means |
|---|---|
| `nancon_k_test.v2` | the run with exactly this name |
| `nancon_k_test` | the run with exactly this name, else the newest live version of it. See the warning below. |
| `9c41aa02` | the run whose id starts with these characters, at least four. It must be unique. |
| the full id | that run |
| `@last`, `@last~1` | the newest completed run, the one before it |
| `@best:nse`, `@worst:nse` | the completed run with the highest, or the lowest, value of the metric at the outlet |
| `@running` | the newest run that is still running |

```{warning}
A bare name is looked up as an exact name first. While the first run of a name is live, it
owns the bare name, so `hmp catalog delete nancon_k_test` trashes that first run, not the
newest one. The newest version is reached only when no live run has the exact name. That
is the case after the first run went to the trash, which `if_exists = "replace"` does. To
act on one run for sure, write its `<id8>` or its `.vN` name.
```

`@best` takes the highest value. For a score where lower is better, such as `rmse`, use
`@worst`.

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
of timesteps, the exports, the version, the start of the config hash, the tags, the notes,
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
  `hmp catalog delete --now` does not check it (step 7).
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
```

To compare a value inside the model, read the same cell in several runs with
`hmp catalog point`. {doc}`Read a value at a point <read-a-value-at-a-point>` shows how.

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
records the original as its parent.

## 7. Clean up

Deleting is in two stages. Nothing is lost at the first.

```bash
hmp catalog delete 9c41aa02 -y
```

The run goes to the trash. Its folder stays where it is, with a `trash.json` file. The name
leaves the index, but the folder still holds `runs/<name>/`, so a new run of that name is
registered as the next `.vN`. The command prints how to undo it:

```text
moved to trash [9c41aa02]. Bytes freed at 'hmp catalog trash --empty'. Restore: hmp catalog restore 9c41aa02
```

Without `-y`, the command asks. In a script without a terminal it stops with
`Refusing to trash without -y in non-interactive mode.`

List the trash, bring a run back, or empty it:

```bash
hmp catalog trash
hmp catalog restore 9c41aa02
hmp catalog trash --empty
```

- A trashed run has no name, so name it by its `<id8>`, the one `trash` prints.
- `restore` gives the run its old name. If the name was taken meanwhile, the run comes back
  under the next free version.
- `trash --empty` frees the disk for good. It skips pinned runs unless you add `--force`.
- `hmp catalog delete --now` skips the trash and removes the folder `runs/<name>/` at
  once. It does not look at the `pinned` tag, so read the reference before you purge. It
  does not touch `share/`, where exports go.

### Let `gc` trim the history

A project that is run often keeps many versions. `hmp catalog gc` decides what to
trash. It only prints a plan until you add `--apply`:

```bash
hmp catalog gc
hmp catalog gc --keep-versions 3 --apply
```

Three rules select runs. Their defaults are on the card of the command in the
{doc}`CLI reference </reference/cli/catalog>`.

| Option | What it selects |
|---|---|
| `--keep-versions N` or `all` | every version of one name beyond the `N` newest. `nancon_k_test`, `nancon_k_test.v2` and `nancon_k_test.v3` are one lineage. `all` turns the rule off. |
| `--max-age-days DAYS` | runs created more than `DAYS` days ago. |
| `--purge-figures` | the `figures/` folder of each run, which can be drawn again. |

A selected run goes to the trash, so `hmp catalog restore` undoes the decision. Selected
figures and orphan run stores are moved to `.hmp/trash/<stamp>/`. A trashed run that has
been there for 30 days is purged for good by the next `gc --apply`. A run tagged `pinned`
is never selected, trashed or purged. A run that is still running is never selected either.

`gc --apply` also does upkeep. It marks as failed the runs whose heartbeat stopped, replays
interrupted purges, deletes temporary Parquet files and an orphan geographic cache, drops
calibration sessions whose best run is gone, and compacts the DuckDB files and the Zarr
metadata.

`hmp catalog watch` lists the runs that are running now, with the age of their heartbeat.
A run flagged `STALE` has a process that died: `gc --apply` marks it failed.

(catalog-reindex)=
## 8. Rebuild the index

```bash
hmp catalog reindex
```

The command reads every sealed run under `runs/` and every session under `sessions/`, and
builds `.hmp/index.duckdb` again. The old index stays readable until the new one replaces
it in one step, and two rebuilds give the same index. Use it when the index is stale,
locked or corrupt, after you move a project, restore a backup or copy a run folder in.
Deleting `.hmp/index.duckdb` first is not needed.

It prints the runs and sessions it indexed and the number of rows per table. A run folder it
cannot read is reported as `skipped <run>: <reason>` and left out.

A rebuild keeps what the run folders carry: the runs, their tags and notes, their trash
state, the calibration sessions. It cannot restore what only the index held:

- the audit log and its hash chain: a new chain starts;
- the record of deletions and of exports;
- the journal of the workflow and its events: an interrupted run can no longer be resumed;
- the observation series and their stations: the next run reads them again from the data
  files its configuration names.

## Several runs at once

Runs of one project can run at the same time. Each run works in its own folder
`.hmp/scratch/<config>.p<pid>/`, and the next run of the project removes the folders of
runs that were killed. You can start two `hmp run` in two terminals.

## How to check it worked

- `hmp catalog ls` shows the new run, or a message that the config is identical.
- After a `delete`, the run disappears from `hmp catalog ls` and appears in
  `hmp catalog trash`.
- After a `reindex`, `hmp catalog ls` lists every run folder of `runs/`.

## What can go wrong

| What you see | Why, and what to do |
|---|---|
| `No indexed project found under <path>` from `ls` | No `.hmp/index.duckdb` below this folder. Move to the project, pass `-w`, or run `hmp catalog reindex` if the folder has runs. |
| `No catalog at <path>` | Same cause for the other commands. |
| `skipping <project>: schema behind (run 'hmp doctor --migrate')` | The index was written by an older version. Run the command it names. |
| `Run <id8> is pinned; pass force=True (CLI --force) to act on it.` | The run carries the `pinned` tag. Remove the tag, or add `--force`. |
| `Nothing to do: pass tags to add or --rm TAG to remove.` | `tag` was called with no tag. |
| The run you delete is the wrong one | A bare name hits the first version. See the warning in step 3 and use the `<id8>`. |
| `hmp catalog restore <name>` finds nothing | A trashed run has no name. Use the `<id8>` from `hmp catalog trash`. |
| `ls` misses a run that is on disk | The index is behind the folders. Run `hmp catalog reindex`. |

The exit codes are listed in {doc}`/reference/cli/exit-codes`.

## Where to go next

- {doc}`Read a value at a point <read-a-value-at-a-point>` compares one cell across runs.
- {doc}`Results and exports <results-and-exports>` says what each run folder holds.
- {doc}`Calibrate <calibrate>` creates many runs at once and promotes the best ones.
- The options of every command are in the {doc}`CLI reference </reference/cli/catalog>`.
