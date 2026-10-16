# One case of the plan. The worker is a child of this shell: the scheduler
# signals the shell (--signal=B:TERM@{{TERM_GRACE_S}}), the shell forwards the
# signal and waits. After the worker, the trap step writes `failed` in the run
# directory when the worker exited without writing its own outcome.
# The flags of `hmp run` are the local launcher's, read when the task starts.
cd "$PROJECT_ROOT" || exit 1
CASE_TOML="$("$HMP_PYTHON" -m hydromodpy project case "$JOB" "$SLURM_ARRAY_TASK_ID")" || exit 2
FLAGS_TEXT="$("$HMP_PYTHON" -m hydromodpy.project.launch.slurm task-flags \
    --phase {{PHASE}} --project "$PROJECT_ROOT" --case-toml "$CASE_TOML")" || exit 2
RUN_FLAGS=()
while IFS= read -r flag; do
    if [ -n "$flag" ]; then
        RUN_FLAGS+=("$flag")
    fi
done <<< "$FLAGS_TEXT"
TASK_JOB_ID="${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
TASK_LOG="$JOB_DIR/logs/{{LOG_PREFIX}}-$TASK_JOB_ID.out"

worker=""
forwarded=0
forward_term() {
    if [ -n "$worker" ] && kill -TERM "$worker" 2>/dev/null; then
        forwarded=1
    fi
}
trap forward_term TERM

"$HMP_PYTHON" -m hydromodpy run "$CASE_TOML" ${RUN_FLAGS[@]+"${RUN_FLAGS[@]}"} &
worker=$!
wait "$worker"
status=$?
while [ "$forwarded" -eq 1 ]; do
    forwarded=0
    wait "$worker"
    status=$?
done

"$HMP_PYTHON" -m hydromodpy.project.launch.slurm finish-task \
    --project "$PROJECT_ROOT" \
    --case-toml "$CASE_TOML" \
    --exit-code "$status" \
    --log "$TASK_LOG" \
    --job-id "$TASK_JOB_ID"
