# On a cluster

A project of {doc}`many catchments <many-catchments>` runs on a Slurm cluster from its plan.
HydroModPy writes the job scripts; you submit them with `sbatch`, as any other job. Each
task of the array runs one case, the same `hmp run plan/<hash>/<case>.toml` the local
launcher runs.

```{warning}
Nothing on this page is verified on a cluster. The scripts are tested for their content
and their shell syntax, and run under stand-in `hmp` and `sacct` commands, never under a
real scheduler. Read them before the first submission, and run a small plan first.
```

## Write the scripts

```bash
hmp project plan .
hmp project array . --scheduler slurm
```

`hmp project array` writes a folder `jobs/<stamp>-slurm/` with three files, frozen when they
are written:

| File | What it holds |
|---|---|
| `cases.txt` | One case per line, the cases of the current plan. Task N of the array reads line N. |
| `prepare.sh` | An array that fetches the data of each case, `hmp run <case> --until load_data`, with `--set workflow.mode=simulation` for a calibration case. It is the only job that adds to the input cache of the workspace. |
| `array.sh` | The array of the solves, `hmp run <case> --frozen`, one task per case, plus `--resume <case>` on a simulation that an earlier attempt left unfinished. |

Each task finds its case with `hmp project case <job> <N>`, which reads the frozen
`cases.txt` of its own job, and chooses the flags of `hmp run` when it starts, from the
state its case is in: a resubmitted task resumes its case. `HMP_PYTHON` overrides the
interpreter the scripts call. A new plan, written while an array waits in the queue, does not
change what its tasks run; `hmp project plan` refuses to write one while a case of the
current plan is running.

`--partition`, `--time` and `--threads-per-case` set the partition, the wall time and the
threads of each case; the {doc}`command reference <../reference/cli/project>` lists the
options. A task asks for {toml}`sites.run.threads_per_case` CPUs times the solves of the
largest case, since a calibration solves several trials side by side, and the worker limits
its own threads to that budget.

## Submit

```bash
sbatch jobs/20261020-143000-slurm/prepare.sh
sbatch --dependency=afterok:<id of prepare> jobs/20261020-143000-slurm/array.sh
```

Each task runs in the scratch of its node: `array.sh` sets `HMP_SCRATCH_ROOT` to
`$SLURM_TMPDIR` when the node has one. The folder of the case, under `runs/`, receives the
results.

A task ends with an outcome in every case. Slurm sends `SIGTERM` ten minutes before the
wall time (`--signal=B:TERM@600`), and the worker writes `aborted` before it stops. When the
worker dies without writing anything (a native crash, an out-of-memory kill), a `trap` in
the script writes `failed` with the exit code, the signal and the end of the log, marked
`written_by = "trap"`. The log of a task is written under `jobs/<stamp>-slurm/logs/`, and
the trap copies it to `runs/<case>/logs/job-<id>.out`.

A task that Slurm resubmits, or a job submitted twice, never makes a `.v2`: the claim of an
attempt is atomic, so the second worker on a case leaves, and a case that failed resumes in
place.

## Follow and collect

```bash
hmp project status .
hmp project log . --failed
hmp catalog reindex -w . --incremental
hmp project collect .
```

`hmp project status` reads the `outcome.json` and the heartbeat of each case. When `sacct`
is on the path, it also asks Slurm which jobs ended: a task whose job ended while its outcome
still says running shows as failed instead of stale. `hmp project log` rebuilds the journal of the job from the
outcomes. No task opens the index of the project: rebuild it once the array is done, then
write the summary.

## Limits

The layout assumes a file system where `mkdir`, `rename` and file locks behave as on a local
disk. A network file system depends on its mount options, and HydroModPy does not test any:
keep the input cache and the project where the cluster documents these operations as safe,
and keep the solver scratch on the node.
