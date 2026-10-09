# Clean up runs and rebuild the index

```{hmp-task}
Task
: Delete runs without losing one by mistake, free disk, and rebuild the index of a project.

Time
: A second per command. `gc --apply` and `reindex` take a few seconds per run.

Needs
: A project with runs, as in {doc}`find-and-compare-runs`. A shell in the project folder, or `-w <project folder>`.

Gives
: A trash you can undo, a plan of what `gc` would remove, and an index that matches the run folders.
```

Disk is the truth and the index is derived. The folder `runs/<name>/` of a run holds
everything needed to read it. The index `.hmp/index.duckdb` makes listing and ranking fast,
and `hmp catalog reindex` builds it again from the folders. So cleaning up is deleting
folders, in two stages, and rebuilding the index when it falls behind.

## 1. Delete a run

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

- `trash` lists the runs by name and `<id8>`. Name a trashed run by its `<id8>`: a bare name
  is looked up among the live runs first ({doc}`find-and-compare-runs`).
- `restore` prints `restored as <name>  [<id8>]`. The run comes back under its old name when
  that name is free, and under a version suffix otherwise. A versioned run can come back one
  version higher than it had (a `.v2` run came back as `.v3` in a check), so read the name
  the message gives.
- `trash --empty` frees the disk for good. It skips pinned runs unless you add `--force`, and
  prints `purged <n> run(s) from trash.`
- `hmp catalog delete --now` skips the trash and removes the folder `runs/<name>/` at once.
  It does not look at the `pinned` tag, so read the reference before you purge. It does not
  touch `share/`, where exports go.

To remove a run and prove that nothing is left, see {doc}`audit-and-purge`.

## 2. Let `gc` trim the history

A project that is run often keeps many versions. `hmp catalog gc` decides what to
trash. It only prints a plan until you add `--apply`:

```bash
hmp catalog gc
hmp catalog gc --keep-versions 3 --apply
```

```text
[plan] superseded_runs: 0 candidate(s)
[plan] expired_runs: 0 candidate(s)
[plan] regenerable_figures: 0 candidate(s)
[plan] expired_trash: 0 candidate(s)
...
Retention policy: 5 version(s) per lineage, no age limit, figures kept, 'pinned' exempt

Plan only. Re-run with --apply to execute.
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
## 3. Rebuild the index

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

## 4. Runs that start at the same time

Runs of one project can run at the same time. Each run works in its own folder
`.hmp/scratch/<config>.p<pid>/`, and the next run of the project removes the folders of
runs that were killed. You can start two `hmp run` in two terminals. {doc}`run-in-the-background`
says how to start a long run and come back to it.

## How to check it worked

- After a `delete`, the run disappears from `hmp catalog ls` and appears in
  `hmp catalog trash`.
- After a `restore`, `hmp catalog ls` lists it again under the name the command printed.
- After a `gc --apply`, `hmp catalog gc` prints `0 candidate(s)` on every line.
- After a `reindex`, `hmp catalog ls` lists every run folder of `runs/`.

## What can go wrong

| What you see | Why, and what to do |
|---|---|
| `Refusing to trash without -y in non-interactive mode.` | A script has no terminal to answer the question. Add `-y`. |
| `Run <id8> is pinned; pass force=True (CLI --force) to act on it.` | The run carries the `pinned` tag. Remove the tag, or add `--force`. |
| `hmp catalog restore <name>` finds nothing | The run is in the trash and a trashed run is reached by its `<id8>`. Take it from `hmp catalog trash`. |
| `restore` brings the run back under another name | The old name was taken, or a versioned name moved up one version. The message `restored as <name>` gives the new one. |
| The disk does not shrink after `delete` | The run is in the trash, with its folder. `hmp catalog trash --empty` frees it. |
| The trash does not empty | A pinned run stays. Add `--force`, or remove the tag. |
| `ls` misses a run that is on disk | The index is behind the folders. Run `hmp catalog reindex`. |
| `skipped <run>: <reason>` after a `reindex` | The folder could not be read. The reason is the error the reader met, for example a folder that is not a complete run. A run folder without `manifest.json` did not finish. |
| The index is locked or corrupt | Run `hmp catalog reindex` before you delete anything. |

## Where to go next

- {doc}`audit-and-purge` removes a run and verifies that nothing is left.
- {doc}`find-and-compare-runs` names, tags and compares runs.
- {doc}`read-the-results` says what a run folder holds.
- The layout of the storage is in {doc}`/contribute/architecture/storage-layout`.
