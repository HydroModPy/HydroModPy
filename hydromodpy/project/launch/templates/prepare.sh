#!/usr/bin/env bash
#SBATCH --job-name={{JOB_NAME}}
#SBATCH --array=1-{{N_CASES}}%{{PREPARE_PARALLEL}}
#SBATCH --cpus-per-task={{THREADS_PER_CASE}}
#SBATCH --signal=B:TERM@{{TERM_GRACE_S}}
#SBATCH --chdir={{PROJECT_ROOT}}
#SBATCH --output={{JOB_DIR}}/logs/prepare-%A_%a.out
{{DIRECTIVES}}
#
# Prepare phase of plan {{PLAN_HASH}}: the geography and the data of each case
# (`hmp run <case>.toml --until load_data`, a calibration case as a simulation;
# {{N_CASES}} cases, {{PREPARE_PARALLEL}} side by side), the only phase that
# writes the shared data cache. The task that completes the phase writes
# hydromodpy.lock, which the solves verify with --frozen.
# Written by `hmp campaign array` on {{STAMP}}; frozen, never rewritten.
# Submit:  prep=$(sbatch --parsable {{JOB_DIR}}/prepare.sh)
# Not verified on a cluster yet.

set -u
JOB={{JOB}}
JOB_DIR={{JOB_DIR}}
PROJECT_ROOT={{PROJECT_ROOT}}
N_CASES={{N_CASES}}
HMP_PYTHON_DEFAULT={{PYTHON}}
HMP_PYTHON="${HMP_PYTHON:-$HMP_PYTHON_DEFAULT}"
export {{THREADS_ENV}}={{THREADS_PER_CASE}}
export {{LAUNCHED_ENV}}={{LAUNCHED_BY}}

{{WORKER}}
if [ "$status" -eq 0 ]; then
    : > "$JOB_DIR/prepared/$SLURM_ARRAY_TASK_ID"
    prepared=$(find "$JOB_DIR/prepared" -type f | wc -l)
    if [ "$prepared" -ge "$N_CASES" ]; then
        "$HMP_PYTHON" -m hydromodpy.project.launch.slurm write-lock \
            --project "$PROJECT_ROOT" --case-toml "$CASE_TOML" || status=$?
    fi
fi
exit "$status"
