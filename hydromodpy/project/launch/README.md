# `hydromodpy/project/launch`

The launcher of a project that declares `[sites]`: many cases (catchments, recipes)
planned once, prepared once, solved as separate processes, then collected into
`summary/`. It runs on your machine (`local.py`) or writes SLURM array scripts
(`slurm.py`). It never opens a `Project`: it starts `hmp run plan/<hash>/<case>.toml
--frozen` processes and reads what they leave on disk.

## Import rules

`launch/` sits inside `hydromodpy/project`, which is above the layer matrix
(`tests/unit/architecture/layer_matrix.yaml`), so it may import any layer. It never imports
`Project`; nothing in `launch/` or `exchange/` does. `local.py` and `slurm.py`
do not import each other: what they share lives in `selection.py`. The module
`hydromodpy.project.launch.slurm` keeps its name and path, because the frozen
scripts in `templates/*.sh` (and the copies users keep in `jobs/`) call it with
`python -m hydromodpy.project.launch.slurm`.

## Modules, in the order a launch calls them

| module | what it answers |
|---|---|
| `sites/` | the plan, sites x recipes resolved into cases, written once under `plan/<hash>/`, and its budget. See [sites/README.md](sites/README.md) |
| `lease.py` | who holds the project right now: `.hmp/launcher.lease`, one launcher per project (`acquire_lease`, `launcher_lease`) |
| `selection.py` | which cases start, with which worker flags, within which budget of solves (`select_cases`, `worker_flags`, `effective_parallel`) |
| `env.py` | the environment and thread budget of a case process (`child_environment`, `apply_thread_budget`) |
| `children.py` | the cases as the launcher sees them (`planned_cases`), the worker processes it starts (`start_child`), the three environment options each worker line carries (`worker_command`), and what a silent death leaves (`close_dead_child`) |
| `prepare.py` | the data of every case, fetched before any solve into the one `data/` folder of the project, where each station is written under its own lock (`prepare_cases`, `write_lockfile_once`) |
| `lockfile.py` | `write_project_lockfile`: the `hydromodpy.lock` written once after the prepare phase, from the sidecars |
| `local.py` | the local launcher: plan, prepare, one process per case, count, index (`plan_project`, `run_plan`) |
| `journal.py` | `jobs/<stamp>-<scheduler>/`, its `journal.jsonl` and the frozen `cases.txt` (`new_job_dir`, `Journal`, `read_journal`, `case_for_task`) |
| `slurm.py` | the SLURM array of a plan: `write_slurm_array`, and the commands the scripts call (`task_flags`, `write_lock`, `finish_task`, `main`) |
| `slurm_script.py` | the text of the scripts: `#SBATCH` lines, walltime, worker block (`directives`, `walltime_seconds`, `render`, `worker_block`) |
| `sacct.py` | what `sacct` says of the array tasks (`scheduler_states`) |
| `status.py` | where each case stands, read from the disk and never from the index (`project_status`, `case_state`, `plan_is_stale`) |
| `summary_tables.py` | the tables `by_case` and `by_site` of a collect (`by_case_table`, `by_site_table`) |
| `summary_exports.py` | the `[[sites.export]]` requests written under `summary/exports/` (`check_exports`, `write_exports`) |
| `summary.py` | `collect_project`: `summary/` of the whole project, regenerated from the run directories |

`templates/` holds `prepare.sh`, `array.sh` and `worker.sh`, the frozen shell scripts
that `slurm_script.py` fills.

## Tree

```
launch/
  lease.py  selection.py  env.py  children.py        who runs, which cases, how
  prepare.py  lockfile.py                            data before any solve
  local.py  journal.py                               the local launch and its trace
  slurm.py  slurm_script.py  sacct.py  templates/    the SLURM array (slurm.py name is frozen)
  status.py                                          the state of each case
  summary_tables.py  summary_exports.py  summary.py  the collect into summary/
```

## Where to add what

| to add | where |
|---|---|
| a rule that picks cases or sets a worker flag | `selection.py`, so the local and the SLURM launch agree |
| a variable of a case process environment | `env.py` |
| a state a case can be in | `status.py` (`case_state`) |
| a scheduler other than SLURM | a module next to `slurm.py`; share the rules through `selection.py` and `journal.py`, do not import `slurm.py` |
| a command a SLURM script calls | a function in `slurm.py`, a branch in its `main`, a line in the template; keep the module path |
| a column of `by_case` or `by_site` | `summary_tables.py` |
| an export kind of `[[sites.export]]` | `summary_exports.py` |
| a figure, a page or the RO-Crate of a collect | not here: `display/cohort.py` and `results/export/campaign_summary.py` |
