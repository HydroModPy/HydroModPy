#!/usr/bin/env bash
# _lib.sh — helpers communs aux scripts run_migration_PXX.sh
# Copié/adapté depuis run_audit.sh

PROJECT="${PROJECT:-/home/bb/Documents/01_Git_Repository/02-HydroModPy-dev}"
OUTPUT="$PROJECT/reporting/migration"
LOG="$OUTPUT/migration.log"
MAX_RETRIES="${MAX_RETRIES:-8}"

mkdir -p "$OUTPUT"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

notify() {
    notify-send "HydroModPy Migration" "$*" 2>/dev/null || true
}

compute_wait() {
    local stderr_file="$1"
    local stdout_file="$2"
    local combined=""
    combined+=$(tail -50 "$stderr_file" 2>/dev/null || true)
    combined+=$'\n'
    combined+=$(tail -10 "$stdout_file" 2>/dev/null || true)
    [[ -z "$combined" ]] && { echo 120; return; }

    if echo "$combined" | grep -qi "hit your limit"; then
        local now_epoch reset_hour reset_ampm reset_epoch
        now_epoch=$(date +%s)
        reset_hour=$(echo "$combined" | grep -oiP 'resets\s+\K\d+(?=\s*[ap]m)' || echo "")
        reset_ampm=$(echo "$combined" | grep -oiP 'resets\s+\d+\K[ap]m' || echo "am")
        if [[ -n "$reset_hour" ]]; then
            if [[ "$reset_ampm" == "pm" ]] && [[ "$reset_hour" -ne 12 ]]; then
                reset_hour=$(( reset_hour + 12 ))
            elif [[ "$reset_ampm" == "am" ]] && [[ "$reset_hour" -eq 12 ]]; then
                reset_hour=0
            fi
            reset_epoch=$(date -d "today ${reset_hour}:05" +%s 2>/dev/null || echo 0)
            if [[ "$reset_epoch" -le "$now_epoch" ]]; then
                reset_epoch=$(date -d "tomorrow ${reset_hour}:05" +%s 2>/dev/null || echo 0)
            fi
            local wait_until=$(( reset_epoch - now_epoch ))
            [[ "$wait_until" -lt 60 ]] && wait_until=120
            echo "$wait_until"
        else
            echo 300
        fi
        return
    fi

    local retry_seconds
    retry_seconds=$(echo "$combined" | grep -oiP 'retry.{0,5}after.{0,5}\K\d+' | head -1 || echo "")
    if [[ -n "$retry_seconds" ]] && [[ "$retry_seconds" -gt 0 ]]; then
        echo $(( retry_seconds + 60 ))
        return
    fi

    if echo "$combined" | grep -qi "rate.limit\|429\|overloaded\|too many\|capacity"; then
        echo 1200
        return
    fi
    if echo "$combined" | grep -qi "server.error\|500\|502\|503\|connection\|timeout"; then
        echo 180
        return
    fi
    echo 120
}

# run_migration <phase_name> <prompt> <success_marker_regex>
run_migration() {
    local phase_name="$1"
    local prompt="$2"
    local success_regex="${3:-}"
    local attempt=1
    local backoff=1
    local stdout_file="$OUTPUT/${phase_name}.stdout"
    local stderr_file="$OUTPUT/${phase_name}.stderr"

    while [[ $attempt -le $MAX_RETRIES ]]; do
        log "START $phase_name (tentative $attempt/$MAX_RETRIES)"
        local start_time
        start_time=$(date +%s)

        set +e
        claude -p "$prompt" \
            --permission-mode bypassPermissions \
            --allowedTools "Read Glob Grep Bash Write Edit" \
            > "$stdout_file" \
            2> "$stderr_file"
        local rc=$?
        set -e

        local elapsed=$(( $(date +%s) - start_time ))

        if [[ $rc -eq 0 ]]; then
            if [[ -z "$success_regex" ]] || grep -qE "$success_regex" "$stdout_file"; then
                log "DONE  $phase_name (${elapsed}s)"
                notify "$phase_name terminé"
                return 0
            fi
        fi

        local wait_time
        wait_time=$(compute_wait "$stderr_file" "$stdout_file")
        log "FAIL  $phase_name (rc=$rc, ${elapsed}s)"

        if echo "$(tail -3 "$stderr_file")" | grep -qi "hit your limit"; then
            log "QUOTA EPUISE — attente jusqu'au reset ($((wait_time/60)) min)"
            sleep "$wait_time"
            backoff=1
            attempt=$((attempt + 1))
            continue
        fi

        wait_time=$(( wait_time * backoff ))
        [[ "$wait_time" -gt 18000 ]] && wait_time=18000
        log "WAIT  $((wait_time/60))min avant retry (backoff x${backoff})"
        sleep "$wait_time"
        attempt=$((attempt + 1))
        backoff=$(( backoff * 2 ))
        [[ "$backoff" -gt 8 ]] && backoff=8
    done

    log "ABANDON $phase_name après $MAX_RETRIES tentatives"
    notify "ECHEC : $phase_name abandonné"
    return 1
}

# prepare_branch <branch_name> <base_branch>
prepare_branch() {
    local branch="$1"
    local base="${2:-dev-database}"
    cd "$PROJECT"
    git fetch origin "$base" --quiet || true
    if git show-ref --verify --quiet "refs/heads/$branch"; then
        log "WARN  Branche $branch existe déjà — checkout"
        git checkout "$branch"
    else
        log "INFO  Création branche $branch depuis $base"
        git checkout -b "$branch" "$base"
    fi
}

# validate_phase : lance les tests post-phase
validate_phase() {
    cd "$PROJECT"
    log "VALIDATE tests/unit/ + tests/regression/fast/"
    if HYDROMODPY_NO_DISPLAY=1 HYDROMODPY_NO_SAVE=1 \
        pytest tests/unit/ tests/regression/fast/ -q --timeout=120 \
        > "$OUTPUT/validate_${PHASE_NAME}.log" 2>&1; then
        log "VALIDATE OK"
        return 0
    else
        log "VALIDATE FAIL — voir $OUTPUT/validate_${PHASE_NAME}.log"
        return 1
    fi
}
