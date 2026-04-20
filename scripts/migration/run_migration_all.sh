#!/usr/bin/env bash
# run_migration_all.sh — orchestrateur complet, exécute les 13 phases dans l'ordre
# avec respect des dépendances. Parallélisme disponible via flags.
#
# Usage :
#   ./run_migration_all.sh                  # mode séquentiel complet
#   ./run_migration_all.sh --start P05      # reprend à partir de P05
#   ./run_migration_all.sh --only P03,P04   # seulement ces phases
#   ./run_migration_all.sh --parallel       # lance en parallèle là où possible
#   ./run_migration_all.sh --dry-run        # affiche le plan sans exécuter

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_lib.sh"

# Ordre et dépendances (ligne = phase, format : NAME:DEPS)
# DEPS vide = aucun prérequis
declare -a PHASES_ORDER=(
    "P01:"            # fondations
    "P02:P01"
    "P03:P01"
    "P04:P01,P02,P03"
    "P05:P01,P02,P03"
    "P06:P01,P02,P03,P04,P05"
    "P07:P01,P02,P05,P06"
    "P08:P01,P02,P03,P05,P06"
    "P09:P01,P03,P08"
    "P10:P01,P02,P07,P08"
    "P11:P01"         # transverse mais démarrable tôt
    "P12:P03,P08,P09"
    "P13:P01,P02,P03,P04,P05,P06,P07,P08,P09,P10,P11,P12"
)

declare -A COMPLETED
DRY_RUN=0
PARALLEL=0
START_FROM=""
ONLY_PHASES=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --parallel) PARALLEL=1; shift ;;
        --start) START_FROM="$2"; shift 2 ;;
        --only) ONLY_PHASES="$2"; shift 2 ;;
        -h|--help)
            head -15 "$0"
            exit 0
            ;;
        *) echo "Option inconnue : $1" >&2; exit 2 ;;
    esac
done

run_one() {
    local phase="$1"
    local script
    script=$(ls "$SCRIPT_DIR/run_migration_${phase}_"*.sh 2>/dev/null | head -1)
    if [[ -z "$script" ]]; then
        log "ERR   Script manquant pour $phase"
        return 1
    fi
    if [[ $DRY_RUN -eq 1 ]]; then
        log "DRY   $script"
        return 0
    fi
    log "EXEC  $script"
    if bash "$script"; then
        COMPLETED[$phase]=1
        return 0
    else
        log "FAIL  $phase"
        return 1
    fi
}

deps_ok() {
    local deps="$1"
    [[ -z "$deps" ]] && return 0
    IFS=',' read -ra arr <<< "$deps"
    for d in "${arr[@]}"; do
        [[ -z "${COMPLETED[$d]:-}" ]] && return 1
    done
    return 0
}

should_run() {
    local phase="$1"
    if [[ -n "$ONLY_PHASES" ]]; then
        [[ ",$ONLY_PHASES," == *",$phase,"* ]] || return 1
    fi
    if [[ -n "$START_FROM" ]]; then
        [[ "$phase" < "$START_FROM" ]] && return 1
    fi
    return 0
}

log "================================================================"
log "  MIGRATION HYDROMODPY — orchestrateur global"
log "  Mode : $([ $PARALLEL -eq 1 ] && echo parallèle || echo séquentiel)"
log "  Dry-run : $DRY_RUN"
log "================================================================"

if [[ $PARALLEL -eq 1 ]]; then
    # Vague par vague : toutes les phases dont les deps sont satisfaites lancent en parallèle
    remaining=("${PHASES_ORDER[@]}")
    while [[ ${#remaining[@]} -gt 0 ]]; do
        wave=()
        new_remaining=()
        for entry in "${remaining[@]}"; do
            phase="${entry%%:*}"
            deps="${entry#*:}"
            if should_run "$phase" && deps_ok "$deps"; then
                wave+=("$phase")
            else
                new_remaining+=("$entry")
            fi
        done
        [[ ${#wave[@]} -eq 0 ]] && break
        log "VAGUE : ${wave[*]}"
        pids=()
        for p in "${wave[@]}"; do
            run_one "$p" &
            pids+=($!)
        done
        wait "${pids[@]}"
        for p in "${wave[@]}"; do COMPLETED[$p]=1; done
        remaining=("${new_remaining[@]}")
    done
else
    for entry in "${PHASES_ORDER[@]}"; do
        phase="${entry%%:*}"
        deps="${entry#*:}"
        should_run "$phase" || { log "SKIP  $phase"; continue; }
        if ! deps_ok "$deps"; then
            log "BLOQUÉ $phase (deps manquantes : $deps)"
            exit 3
        fi
        run_one "$phase" || exit 1
    done
fi

log ""
log "================================================================"
log "  MIGRATION TERMINÉE"
log "  Phases complétées : ${!COMPLETED[@]}"
log "  Fin : $(date '+%Y-%m-%d %H:%M:%S')"
log "================================================================"
notify "Migration HydroModPy : toutes phases complétées"
