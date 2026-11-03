#!/usr/bin/env bash
#SBATCH --job-name={{JOB_NAME}}
#SBATCH --array=1-{{N_CASES}}
#SBATCH --cpus-per-task={{CPUS_PER_TASK}}
#SBATCH --signal=B:TERM@{{TERM_GRACE_S}}
#SBATCH --chdir={{PROJECT_ROOT}}
#SBATCH --output={{JOB_DIR}}/logs/array-%A_%a.out
{{DIRECTIVES}}
#
# Solves of plan {{PLAN_HASH}}: task N runs line N of cases.txt with
# `hmp run <case>.toml`, --frozen when hydromodpy.lock exists, --resume on a
# simulation an earlier attempt left unfinished. {{CPUS_PER_TASK}} cpus per task:
# threads_per_case {{THREADS_PER_CASE}} x {{MAX_SOLVES}} solve(s) side by side in the largest case.
# Written by `hmp campaign array` on {{STAMP}}; frozen, never rewritten.
# Submit after the prepare phase:
#   sbatch --dependency=afterok:$prep {{JOB_DIR}}/array.sh
# Not verified on a cluster yet.

set -u
JOB={{JOB}}
JOB_DIR={{JOB_DIR}}
PROJECT_ROOT={{PROJECT_ROOT}}
HMP_PYTHON_DEFAULT={{PYTHON}}
HMP_PYTHON="${HMP_PYTHON:-$HMP_PYTHON_DEFAULT}"
export {{THREADS_ENV}}={{THREADS_PER_CASE}}
export {{LAUNCHED_ENV}}={{LAUNCHED_BY}}
if [ -n "${SLURM_TMPDIR:-}" ]; then
    export HMP_SCRATCH_ROOT="$SLURM_TMPDIR"
fi

{{WORKER}}
exit "$status"
