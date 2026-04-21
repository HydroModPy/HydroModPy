#!/usr/bin/env bash
#
# run_completion.sh — Completion v0.4 -> v0.5 de HydroModPy
#
# Contexte :
#   run_migration.sh (P01-P13)     : migration principale -> commit 04aa3aef (v0.4)
#   run_finalization.sh (F01-F08)  : dettes P03/P06/P07/P08/P10/P12 + rapport d'audit
#   run_completion.sh (CE SCRIPT)  : finir TOUT le reste (v0.5 / v0.5-v0.6 / v0.6+)
#
# Baseline : docs/developers/architecture_conformance_report.md
#   Liste 24 "manquants residuels" repartis en 3 priorites :
#     - haute (v0.5) : 6 items
#     - moyenne (v0.5-v0.6) : 10 items
#     - basse (v0.6+) : 8 items
#   + dette F01 (FlowConfig + sections pint).
#
# Decisions utilisateur actees (GARDEES TELLES QUELLES) :
#   - NWT/MF6 restent SEPARES (flow_to_modflow_adapter.py dupliques, F02).
#   - HYDROMODPY_NO_DISPLAY / HYDROMODPY_NO_SAVE restent SUPPRIMES (F04).
#   - Bump v0.4 -> v0.5 : breaking changes autorises, PAS de DeprecationWarning,
#     PAS de shim de retrocompat, PAS d'alias legacy. On casse tout proprement.
#
# Usage :
#   tmux new-session -s completion './run_completion.sh'   # lance depuis le debut
#   ./run_completion.sh --status                           # etat des phases
#   ./run_completion.sh --phase G05                        # relance phase specifique
#   ./run_completion.sh --resume                           # reprise auto (defaut)
#   ./run_completion.sh --reset                            # DANGEREUX: efface etat
#
# Garanties :
#   - Ne S ARRETE PAS tant que toutes les phases ne sont pas .done
#     (outer while-loop + MAX_RETRIES=100 par phase).
#   - Rate limits Claude : attente jusqu'au reset, max 6h.
#   - Reprise apres crash / deconnexion (etat persistent).
#   - Commits petits et frequents, format "[Gxx] - <few english words>".
#   - ZERO push, ZERO changement de branche, ZERO Co-Authored-By.
#
set -euo pipefail

# ===============================================================
# CONFIGURATION
# ===============================================================
PROJECT="/home/bb/Documents/01_Git_Repository/02-HydroModPy-dev"
SPECS="$PROJECT/architecture_cible"
BASELINE_REPORT="$PROJECT/docs/developers/architecture_conformance_report.md"
FINAL_REPORT="$PROJECT/docs/developers/architecture_conformance_report_v050.md"
TEST_REPORT="$PROJECT/docs/developers/test_status_report.md"
STATE_DIR="$PROJECT/migration_completion"
PHASES_DIR="$STATE_DIR/phases"
LOG="$STATE_DIR/completion.log"
STDOUT_TMP="$STATE_DIR/.stdout_last"
STDERR_TMP="$STATE_DIR/.stderr_last"
MAX_RETRIES=100
MAX_WAIT=21600          # 6h max wait (plan limit reset)
OUTER_LOOP_SLEEP=120    # 2min entre deux rondes exterieures si des phases restent pendantes
BRANCH_AT_START=""
INITIAL_COMMIT=""

ALL_PHASES=(G01 G02 G03 G04 G05 G06 G07 G08 G09 G10 G11)

mkdir -p "$STATE_DIR" "$PHASES_DIR"

# ===============================================================
# ENV — activer le venv uv pour que `pytest` soit dans le PATH
# ===============================================================
if [[ -d "$PROJECT/.venv/bin" ]]; then
    export PATH="$PROJECT/.venv/bin:$PATH"
    export VIRTUAL_ENV="$PROJECT/.venv"
fi

# ===============================================================
# HELPERS — log, notify
# ===============================================================
log() {
    local ts
    ts="[$(date '+%Y-%m-%d %H:%M:%S')]"
    echo "$ts $*" | tee -a "$LOG"
}

notify() {
    notify-send "HydroModPy Completion" "$*" 2>/dev/null || true
}

# ===============================================================
# SECURITE — Garde-fous absolus
# ===============================================================
record_initial_state() {
    BRANCH_AT_START=$(git -C "$PROJECT" rev-parse --abbrev-ref HEAD)
    INITIAL_COMMIT=$(git -C "$PROJECT" rev-parse HEAD)
    echo "$BRANCH_AT_START" > "$STATE_DIR/.branch"
    echo "$INITIAL_COMMIT"  > "$STATE_DIR/.initial_commit"

    if [[ "$BRANCH_AT_START" == "master" || "$BRANCH_AT_START" == "main" ]]; then
        log "FATAL: refuse to run completion on $BRANCH_AT_START branch"
        exit 99
    fi
    log "Initial branch : $BRANCH_AT_START"
    log "Initial commit : $INITIAL_COMMIT"
}

verify_safe_state() {
    local current_branch
    current_branch=$(git -C "$PROJECT" rev-parse --abbrev-ref HEAD)
    if [[ "$current_branch" != "$BRANCH_AT_START" ]]; then
        log "FATAL: branch changed from $BRANCH_AT_START to $current_branch"
        notify "ABORT: branch changed during completion"
        exit 99
    fi
}

check_prerequisites() {
    local missing=0
    for f in 01_structure_packages.md 02_config_pydantic.md 03_data_contracts.md \
             04_storage_ideal.md 05_solver_contracts.md 06_pipeline_execution.md \
             07_calibration.md 08_postprocess_display.md 09_tests_ideaux.md \
             10_ux_cli_api.md 11_frontend_ready.md 12_input_data_rethink.md \
             13_coherence_globale.md 14_plan_migration.md; do
        if [[ ! -s "$SPECS/$f" ]]; then
            log "MISSING SPEC: $SPECS/$f"
            missing=$((missing + 1))
        fi
    done
    if [[ ! -s "$BASELINE_REPORT" ]]; then
        log "MISSING BASELINE REPORT: $BASELINE_REPORT"
        missing=$((missing + 1))
    fi
    for p in P01 P02 P03 P04 P05 P06 P07 P08 P09 P10 P11 P12 P13; do
        if [[ ! -f "$PROJECT/migration/phases/$p.done" ]]; then
            log "MISSING PREREQ: migration/phases/$p.done"
            missing=$((missing + 1))
        fi
    done
    for f in F01 F02 F03 F04 F05 F06 F07 F08; do
        if [[ ! -f "$PROJECT/migration_final/phases/$f.done" ]]; then
            log "MISSING PREREQ: migration_final/phases/$f.done"
            missing=$((missing + 1))
        fi
    done
    if [[ $missing -gt 0 ]]; then
        log "FATAL: $missing prerequisites missing — aborting"
        exit 98
    fi
}

phase_done() {
    [[ -f "$PHASES_DIR/$1.done" ]]
}

phase_mark_done() {
    local name="$1"
    local commit
    commit=$(git -C "$PROJECT" rev-parse HEAD 2>/dev/null || echo "NO_COMMIT")
    cat > "$PHASES_DIR/$name.done" <<EOF
completed_at=$(date -Iseconds)
commit=$commit
EOF
    log "MARK $name done at $commit"
}

all_phases_done() {
    for phase in "${ALL_PHASES[@]}"; do
        if ! phase_done "$phase"; then
            return 1
        fi
    done
    return 0
}

# ===============================================================
# compute_wait — parse stderr/stdout pour decider de l'attente
# ===============================================================
compute_wait() {
    local stderr_file="$1"
    local stdout_file="${2:-}"
    local combined=""
    combined+=$(tail -100 "$stderr_file" 2>/dev/null || true)
    combined+=$'\n'
    combined+=$(tail -50 "$stdout_file" 2>/dev/null || true)

    if [[ -z "$combined" ]]; then
        echo 180
        return
    fi

    # Quota journalier : "hit your limit · resets Xam/pm"
    if echo "$combined" | grep -qi "hit your limit\|plan limit reached\|usage limit"; then
        local now_epoch
        now_epoch=$(date +%s)
        local reset_hour
        reset_hour=$(echo "$combined" | grep -oiP 'resets\s+\K\d+(?=\s*[ap]m)' || echo "")
        local reset_ampm
        reset_ampm=$(echo "$combined" | grep -oiP 'resets\s+\d+\K[ap]m' || echo "am")
        if [[ -n "$reset_hour" ]]; then
            if [[ "$reset_ampm" == "pm" ]] && [[ "$reset_hour" -ne 12 ]]; then
                reset_hour=$(( reset_hour + 12 ))
            elif [[ "$reset_ampm" == "am" ]] && [[ "$reset_hour" -eq 12 ]]; then
                reset_hour=0
            fi
            local reset_epoch
            reset_epoch=$(date -d "today ${reset_hour}:05" +%s 2>/dev/null || echo 0)
            if [[ "$reset_epoch" -le "$now_epoch" ]]; then
                reset_epoch=$(date -d "tomorrow ${reset_hour}:05" +%s 2>/dev/null || echo 0)
            fi
            local wait_until=$(( reset_epoch - now_epoch ))
            [[ "$wait_until" -lt 60 ]] && wait_until=300
            [[ "$wait_until" -gt $MAX_WAIT ]] && wait_until=$MAX_WAIT
            echo "$wait_until"
        else
            echo 1800
        fi
        return
    fi

    # Retry-after header
    local retry_seconds
    retry_seconds=$(echo "$combined" | grep -oiP 'retry.{0,10}after.{0,5}\K\d+' | head -1 || echo "")
    if [[ -n "$retry_seconds" ]] && [[ "$retry_seconds" -gt 0 ]]; then
        local w=$(( retry_seconds + 60 ))
        [[ "$w" -gt $MAX_WAIT ]] && w=$MAX_WAIT
        echo "$w"
        return
    fi

    # Generic rate limit
    if echo "$combined" | grep -qi "rate.limit\|429\|overloaded\|too many\|capacity"; then
        echo 1200
        return
    fi

    # Server / network transient
    if echo "$combined" | grep -qi "server.error\|5[0-9]{2}\b\|connection\|timeout"; then
        echo 240
        return
    fi

    echo 180
}

# ===============================================================
# VERIFICATION des commits : aucun Co-Authored-By / Claude / Anthropic
# ===============================================================
verify_commits_clean() {
    local since="$1"
    if git -C "$PROJECT" log --format="%B" "${since}..HEAD" 2>/dev/null \
         | grep -qiE "co-authored-by|anthropic|claude[[:space:]]*(code|sonnet|opus|haiku)?"; then
        log "FATAL: found forbidden trailer in commits since $since"
        git -C "$PROJECT" log --format="%h %s" "${since}..HEAD" | tee -a "$LOG"
        notify "ABORT: forbidden trailer in commit"
        return 1
    fi
    return 0
}

# ===============================================================
# PROMPT COMMUN — Regles injectees dans chaque phase
# ===============================================================
read -r -d '' COMMON_PROMPT <<'EOPROMPT' || true
===============================================================
  CONTEXTE — Completion v0.4 -> v0.5 de HydroModPy
===============================================================

Le codebase est sur la branche dev-refact_v2, apres :
- run_migration.sh (P01-P13)     : socle v0.4 livre.
- run_finalization.sh (F01-F08)  : dettes audit + rapport conformite.

Ce troisieme et DERNIER script (run_completion.sh) finit TOUT ce qui
restait requalifie en v0.5 / v0.5-v0.6 / v0.6+ dans le rapport :

    docs/developers/architecture_conformance_report.md

LIS CE RAPPORT EN PREMIER quand tu attaques une phase Gxx : la section
"Manquants residuels (a traiter post-v0.4)" liste les 24 items.

===============================================================
  REGLES STRICTES — A NE JAMAIS TRANSGRESSER
===============================================================

AUTORISATIONS MAXIMALES sur cette branche (BREAKING CHANGES ACTES) :
- Tu peux CREER, MODIFIER, DEPLACER, RENOMMER, SUPPRIMER des fichiers.
- Tu peux CASSER toutes les APIs publiques v0.4 (pas de retrocompat).
- Tu peux SUPPRIMER des packages entiers (ex: watershed/, runners/ top-level).
- Tu peux REECRIRE FROM SCRATCH des fichiers existants si necessaire.
- Tu peux MODIFIER .github/workflows/*.yml pour aligner la CI.
- Tu peux utiliser le Agent tool (subagent_type: general-purpose ou Explore)
  pour paralleliser la recherche, l analyse et la refonte de code large.

INTERDICTIONS ABSOLUES (JAMAIS, SOUS AUCUN PRETEXTE) :
- NEVER run 'git push' — interdit formellement (meme --dry-run).
- NEVER run 'git checkout <other-branch>' ni 'git switch' vers une autre branche.
- NEVER run 'git push --force' ni aucune variante.
- NEVER use '--no-verify', '--no-gpg-sign', ou tout flag qui bypass les hooks.
- NEVER add 'Co-Authored-By' / 'Claude' / 'Anthropic' dans les messages de commit.
- NEVER amend commits (toujours creer de NOUVEAUX commits).
- NEVER run 'git rebase', 'git reset --hard' sauf si explicitement demande par la phase.
- NEVER delete .git/, .github/ (entier), pyproject.toml, setup.cfg.
- NEVER modifier run_migration.sh, run_finalization.sh, ni run_completion.sh.
- NEVER ajouter DeprecationWarning, alias de retrocompat, ou shim legacy.
  La migration v0.4 -> v0.5 est nette. Les renommages sont directs, sans alias.
- NEVER parler d "INRAE" dans le code, docstrings, docs, messages utilisateur :
  la donnee SIM2 est **Meteo-France** (SAFRAN-ISBA reanalyse surface).
- NEVER remettre HYDROMODPY_NO_DISPLAY ou HYDROMODPY_NO_SAVE (decision F04).
- NEVER mutualiser NWT et MF6 flow_to_modflow_adapter.py (decision F02, sunset
  plan post-LAK MF6). Garder les deux adapters separes.

COMMITS — Format OBLIGATOIRE :
- Message EXACT : '[Gxx] - <3 to 7 words in English>'
- Exemples VALIDES :
    [G01] - add core exceptions hierarchy
    [G02] - rename process to physics package
    [G04] - add http client with backoff
    [G07] - add piper diagram figure
- Exemples INVALIDES (JAMAIS faire) :
    Migration of exceptions to core                             (pas de prefixe)
    [G01] - refactor                                            (trop vague)
    Multi-line message with description in body                 (corps interdit)
    Any line containing "Co-Authored-By" or "Claude"            (banni)
- PETITS COMMITS : 1 operation logique = 1 commit.
  Commit tot et souvent. Ne JAMAIS batcher 30 modifications en un seul gros commit.
- Apres CHAQUE commit, verifier avec :
    git log -1 --format="%s%n%b"
  pour s'assurer qu'il n'y a PAS de "Co-Authored-By" ni "Claude" ni "Anthropic".

STRATEGIE DE TRAVAIL :
1. Lire la section correspondante du rapport de conformite :
     docs/developers/architecture_conformance_report.md
2. Lire la ou les specs cibles concernees : architecture_cible/<fichier>.md
3. Lire le code EXISTANT avant de modifier (ne jamais detruire a l aveugle).
4. Utiliser Agent/Task pour la recherche large (subagent_type: Explore) et la
   refonte parallele quand plusieurs modules doivent etre modifies en coherence.
5. Decouper en PETITS commits atomiques (1 intention = 1 commit).
6. Lancer les tests unitaires apres chaque commit substantiel :
     pytest tests/unit/ -q --tb=short --maxfail=10
7. Si un test casse legitimement (code obsolete suite a un rename) :
   - Si le test est encore pertinent : l adapter au nouveau nom / API.
   - Si le test couvre du code supprime : le supprimer franchement (pas skip).
8. Relire tes propres diffs avant de commit :
     git diff --staged
   pour confirmer que le scope correspond au message.

BREAKING CHANGES — Approche :
- Tu CASSES l API v0.4 (renommages directs, suppressions de modules).
- Tu MODIFIES les tests, examples, docs qui s appuyaient sur l ancienne API.
- Tu METS A JOUR CHANGELOG.md (section [Unreleased] ou [v0.5.0]) a chaque
  breaking change : ce sera la reference pour les utilisateurs.
- Tu NE LAISSES PAS de code mort. Si un module est remplace, supprime l ancien
  completement (pas de commentaire "# removed — use ..." ni fichier vide).

IDEMPOTENCE :
- La phase peut etre relancee apres crash. Verifier TOUJOURS l etat courant
  avant d agir. Une operation deja faite ne doit PAS etre refaite ni causer
  d erreur.

CONTEXTE PROJET :
- HydroModPy v0.4 -> v0.5 (bump mineur, nombreux breaking changes actes).
- Branche : dev-refact_v2 (ne JAMAIS en changer).
- Python : 3.11-3.13. Venv uv a la racine : .venv/
- CLI : hmp (entry : hydromodpy/__main__.py, a splitter en _cli/ en G02/G07).
- Tests : pytest tests/unit -q  doit passer a la fin de chaque phase
  (hors xfail documentes en G11).

ENVIRONNEMENT D EXECUTION :
- Le PATH est deja configure avec .venv/bin en prefixe : `pytest`, `python`,
  `hmp` sont directement disponibles. NE PAS chercher pytest avec `find /`
  (scan systeme = plusieurs heures, STRICTEMENT INTERDIT).
- Pour installer une nouvelle dependance : editer pyproject.toml puis
  `uv sync` (pas `pip install` directement).

SIGNALISATION DE FIN :
Quand la phase est COMPLETEMENT terminee (tous les commits passes, tests
utiles pour cette phase passent), imprimer EXACTEMENT cette ligne sur la
DERNIERE ligne de ta sortie :

    PHASE_Gxx_DONE

(remplace xx par le numero de phase). Cette ligne est le signal que le script
bash cherche pour considerer la phase reussie. Sans cette ligne, la phase
sera relancee.

===============================================================
EOPROMPT

# ===============================================================
# run_phase — Execute une phase avec retry / rate-limit handling
# ===============================================================
run_phase() {
    local name="$1"
    local description="$2"
    local prompt_body="$3"

    # Filtre --phase
    if [[ -n "${SINGLE_PHASE:-}" && "$name" != "$SINGLE_PHASE" ]]; then
        return 0
    fi

    if phase_done "$name"; then
        log "SKIP $name ($description) — already done"
        return 0
    fi

    verify_safe_state

    local attempt=1
    local backoff_multiplier=1

    while [[ $attempt -le $MAX_RETRIES ]]; do
        log "START $name: $description (attempt $attempt/$MAX_RETRIES)"
        local start_time
        start_time=$(date +%s)

        local full_prompt="${COMMON_PROMPT}

===============================================================
  PHASE $name — $description
===============================================================

${prompt_body}

===============================================================
  FINALISATION DE LA PHASE $name
===============================================================
- S il reste des changements non commites, faire un dernier petit commit :
    [$name] - final cleanup
- Verifier avec 'git log -30 --oneline' qu aucun commit de cette phase
  ne contient 'Co-Authored-By', 'Claude', ou 'Anthropic'.
- Verifier qu on est toujours sur la meme branche qu au demarrage.
- Verifier que les decisions actees restent respectees :
    * NWT et MF6 flow_to_modflow_adapter.py toujours separes (F02).
    * HYDROMODPY_NO_DISPLAY / HYDROMODPY_NO_SAVE toujours absents (F04) :
        grep -rln 'HYDROMODPY_NO_DISPLAY\\|HYDROMODPY_NO_SAVE' \\
            --include='*.py' --include='*.yml' hydromodpy/ tests/ \\
            validation_cases/ .github/
      NE DOIT RETOURNER AUCUNE LIGNE. Si ca en retourne, purge-les.
- Lancer une derniere fois : pytest tests/unit/ -q --tb=short
  (tolerance sur xfail connus, documentes en G11).
- Imprimer sur la DERNIERE ligne, exactement :
    PHASE_${name}_DONE
"

        set +e
        claude -p "$full_prompt" \
            --permission-mode bypassPermissions \
            --allowedTools "Read Write Edit Glob Grep Bash Agent" \
            > "$STDOUT_TMP" \
            2> "$STDERR_TMP"
        local rc=$?
        set -e

        local elapsed=$(( $(date +%s) - start_time ))

        # Garde-fou : la branche n a pas change
        verify_safe_state

        # Succes : la sortie se termine par PHASE_Gxx_DONE
        if tail -30 "$STDOUT_TMP" | grep -q "PHASE_${name}_DONE"; then
            log "DONE $name (${elapsed}s)"

            # Verif commits propres
            if ! verify_commits_clean "$INITIAL_COMMIT"; then
                log "FATAL: forbidden trailer in commits for $name — aborting"
                return 1
            fi

            phase_mark_done "$name"
            notify "$name done in ${elapsed}s"
            return 0
        fi

        # Echec — analyser l erreur
        local wait_time
        wait_time=$(compute_wait "$STDERR_TMP" "$STDOUT_TMP")
        local err_summary
        err_summary=$(tail -10 "$STDOUT_TMP" 2>/dev/null | tail -1 || echo "rc=$rc")
        if [[ -z "$err_summary" ]]; then
            err_summary=$(tail -5 "$STDERR_TMP" 2>/dev/null | grep -iE "error|limit|fail" | tail -1 || echo "rc=$rc")
        fi
        log "FAIL $name (rc=$rc, ${elapsed}s): $err_summary"

        # Quota journalier : attente directe sans backoff
        if grep -qiE "hit your limit|plan limit reached|usage limit" "$STDOUT_TMP" "$STDERR_TMP" 2>/dev/null; then
            [[ $wait_time -gt $MAX_WAIT ]] && wait_time=$MAX_WAIT
            local wait_h=$(( wait_time / 3600 ))
            local wait_m=$(( (wait_time % 3600) / 60 ))
            log "QUOTA HIT — pause ${wait_h}h${wait_m}m, resume $(date -d "+${wait_time} seconds" '+%Y-%m-%d %H:%M')"
            notify "Quota reached — waiting until $(date -d "+${wait_time} seconds" '+%H:%M')"
            sleep "$wait_time"
            backoff_multiplier=1
            attempt=$((attempt + 1))
            continue
        fi

        # Backoff exponentiel pour les autres erreurs
        wait_time=$(( wait_time * backoff_multiplier ))
        [[ $wait_time -gt $MAX_WAIT ]] && wait_time=$MAX_WAIT
        local wait_min=$(( wait_time / 60 ))
        log "WAIT ${wait_min}min (backoff x$backoff_multiplier) — resume $(date -d "+${wait_time} seconds" '+%H:%M:%S')"

        sleep "$wait_time"

        attempt=$((attempt + 1))
        backoff_multiplier=$(( backoff_multiplier * 2 ))
        [[ $backoff_multiplier -gt 8 ]] && backoff_multiplier=8
    done

    log "GIVE UP on $name after $MAX_RETRIES attempts — will be retried on next outer loop"
    notify "Phase $name exhausted retries, retrying outer loop"
    return 0   # Don't exit script — outer loop will retry
}

# ===============================================================
# CLI — --status / --reset / --phase / --resume
# ===============================================================
show_status() {
    echo ""
    echo "=== Completion HydroModPy v0.4 -> v0.5 — status ==="
    echo "Branch : $(git -C "$PROJECT" rev-parse --abbrev-ref HEAD)"
    echo "HEAD   : $(git -C "$PROJECT" rev-parse --short HEAD)"
    echo ""
    echo "Phases :"
    for phase in "${ALL_PHASES[@]}"; do
        if phase_done "$phase"; then
            local commit
            commit=$(grep '^commit=' "$PHASES_DIR/$phase.done" 2>/dev/null | cut -d= -f2 | cut -c1-8)
            echo "  OK  $phase  (commit $commit)"
        else
            echo "  --  $phase  (pending)"
        fi
    done
    echo ""
}

reset_state() {
    read -r -p "ERASE all completion state? (type 'YES'): " confirm
    if [[ "$confirm" != "YES" ]]; then
        echo "Aborted."
        exit 1
    fi
    rm -rf "$PHASES_DIR"
    mkdir -p "$PHASES_DIR"
    rm -f "$STDOUT_TMP" "$STDERR_TMP"
    echo "State erased. Log preserved at $LOG"
}

SINGLE_PHASE=""
case "${1:-}" in
    --status)
        record_initial_state 2>/dev/null || true
        show_status
        exit 0
        ;;
    --reset)
        reset_state
        exit 0
        ;;
    --phase)
        SINGLE_PHASE="${2:?Missing phase name, e.g. --phase G03}"
        ;;
    --resume|"")
        :
        ;;
    -h|--help)
        sed -n '1,30p' "$0" | sed 's/^# \?//'
        exit 0
        ;;
    *)
        echo "Unknown arg: $1"
        echo "Usage: $0 [--status|--phase Gxx|--resume|--reset|--help]"
        exit 1
        ;;
esac

# ===============================================================
# INITIALISATION
# ===============================================================
record_initial_state
check_prerequisites

log ""
log "================================================================"
log "  COMPLETION HYDROMODPY v0.4 -> v0.5"
log "  Branch   : $BRANCH_AT_START"
log "  HEAD     : $INITIAL_COMMIT"
log "  Start    : $(date '+%Y-%m-%d %H:%M:%S')"
log "  Specs    : $SPECS"
log "  Baseline : $BASELINE_REPORT"
log "  Final    : $FINAL_REPORT"
log "  Tests    : $TEST_REPORT"
if [[ -n "$SINGLE_PHASE" ]]; then
    log "  MODE     : single phase = $SINGLE_PHASE"
else
    log "  MODE     : resume-all (outer loop until all .done)"
fi
log "================================================================"

# ===============================================================
# DEFINITION DES PHASES
# ===============================================================

# ---------- G01 : Core foundations (exceptions, io, logging, version, py.typed) ----------
G01_PROMPT='
OBJECTIF : poser les fondations propres du package core/ :
- hiérarchie d exceptions typées centralisée
- sous-package core/io/ pour les helpers I/O
- sous-package core/logging/ pour LogManager
- core/version.py isole
- marker py.typed (PEP 561)

RAPPORT DE CONFORMITE — Items adresses :
- v0.5 #1 : hydromodpy/core/exceptions.py (hierarchie typee)
- v0.6+ #18 : core/io/, core/logging/, core/version.py scaffolding
- v0.6+ #21 : marker py.typed

SPEC : architecture_cible/01_structure_packages.md §3 (core layout),
       architecture_cible/13_coherence_globale.md §1.5.

TACHES :

1. Creer hydromodpy/core/exceptions.py avec la hierarchie complete :

   class HydroModPyError(Exception):
       """Base exception. Carries optional sim_id / run_id context."""
       def __init__(self, message, *, sim_id=None, run_id=None, **context):
           super().__init__(message)
           self.message = message
           self.sim_id = sim_id
           self.run_id = run_id
           self.context = context

   class ConfigError(HydroModPyError): pass
   class ConfigValidationError(ConfigError): pass
   class ConfigMissingError(ConfigError): pass

   class DataError(HydroModPyError): pass
   class DataContractViolation(DataError): pass
   class DataCacheError(DataError): pass
   class DataSourceError(DataError): pass

   class MeshError(HydroModPyError): pass
   class MeshGenerationError(MeshError): pass

   class SolverError(HydroModPyError): pass
   class SolverDivergedError(SolverError): pass
   class SolverTimeoutError(SolverError): pass
   class SolverBinaryError(SolverError): pass
   class SolverMassBalanceError(SolverError): pass

   class PipelineError(HydroModPyError): pass
   class StepError(PipelineError): pass
   class CheckpointError(PipelineError): pass
   class LedgerError(PipelineError): pass

   class CalibrationError(HydroModPyError): pass
   class ObjectiveError(CalibrationError): pass
   class OptimizerError(CalibrationError): pass

   class DisplayError(HydroModPyError): pass
   class FigureNotFoundError(DisplayError): pass
   class BackendError(DisplayError): pass

   class StorageError(HydroModPyError): pass
   class CatalogError(StorageError): pass
   class ZarrStoreError(StorageError): pass

2. Remplacer les exceptions locales dispersees :
   - grep les TimeSeriesValidationError, TomlLoadError, etc. eparpillees dans
     hydromodpy/data/ et autres, et les reconnecter a la hierarchie (soit
     heriter de la bonne sous-classe, soit rediriger les imports vers
     core/exceptions).
   - Remplacer les ValueError gratuits dans les configs Pydantic par
     ConfigValidationError quand il s agit de contrat non respecte.

3. Creer hydromodpy/core/io/ avec :
   - __init__.py (re-exporte les utilitaires)
   - raster_io.py      (deplacer depuis core/tools/raster_io.py)
   - vector_io.py      (deplacer les helpers geopandas / shapefile)
   - crs.py            (helpers pyproj / crs, deplacer depuis core/tools/geospatial.py)
   - canonical_json.py (helper deterministic JSON dump, used par calibration/cache.py)
   - http_client.py    (scaffold vide, rempli en G04)

4. Creer hydromodpy/core/logging/ avec :
   - __init__.py
   - manager.py  (deplacer LogManager depuis core/tools/log_manager.py)
   Garder le nom public LogManager stable pour les imports courants.

5. Creer hydromodpy/core/version.py :
   - __version__ = "0.5.0.dev0"
   - Suppression du bloc calcule inline dans hydromodpy/__init__.py (lignes
     ~229-236). hydromodpy/__init__.py importe __version__ depuis .version.

6. Creer hydromodpy/py.typed (fichier vide, marker PEP 561).
   Mettre a jour pyproject.toml (packages / include data) pour que py.typed
   soit distribue dans les wheels.

7. Adapter tous les imports downstream (grep + remplacements) :
   - from hydromodpy.core.tools.log_manager import LogManager
     -> from hydromodpy.core.logging import LogManager
   - from hydromodpy.core.tools.raster_io import ...
     -> from hydromodpy.core.io.raster_io import ...
   - etc.

8. Supprimer physiquement les fichiers deplaces (pas d alias, pas de re-export) :
   - hydromodpy/core/tools/log_manager.py (apres migration)
   - hydromodpy/core/tools/raster_io.py
   - etc.

9. Verifier :
     pytest tests/unit/ -q --tb=short
   pas de regression globale.

COMMITS attendus (10-15 petits) :
   [G01] - add core exceptions module
   [G01] - add typed data exceptions
   [G01] - add typed solver exceptions
   [G01] - add typed pipeline exceptions
   [G01] - wire data errors to hierarchy
   [G01] - add core io package scaffold
   [G01] - move raster io to core io
   [G01] - move vector io to core io
   [G01] - add canonical json helper
   [G01] - add core logging package
   [G01] - move log manager to core logging
   [G01] - add core version module
   [G01] - add py typed marker
   [G01] - wire py typed in pyproject
   [G01] - update __init__ to use core version
   [G01] - remove moved tools modules

CRITERES DE SUCCES :
- hydromodpy/core/exceptions.py existe avec 25+ classes.
- hydromodpy/core/io/{raster_io,vector_io,crs,canonical_json,http_client}.py.
- hydromodpy/core/logging/manager.py avec LogManager.
- hydromodpy/core/version.py avec __version__.
- hydromodpy/py.typed existe (fichier vide).
- pyproject.toml inclut py.typed dans le build.
- pytest tests/unit/ -q  passe (peut introduire quelques updates mais 0 regression).

SIGNALISATION : PHASE_G01_DONE
'
run_phase "G01" "Core foundations (exceptions, io, logging, version, py.typed)" "$G01_PROMPT"

# ---------- G02 : Canonical renames (break everything) ----------
G02_PROMPT='
OBJECTIF : appliquer tous les renommages canoniques differes, sans alias, sans
DeprecationWarning, sans shim. On casse tout.

RAPPORT DE CONFORMITE — Items adresses :
- v0.5-v0.6 #19 : SolverAdapter -> SolverRunner, DataManagersPlanner -> DataPlanner,
                   Geographic -> CatchmentDelineation, suppression Watershed facade.
- v0.6+ #20 : process/ -> physics/, simulation/results/ -> simulation/extraction/.
- v0.6+ #17 partiel : watershed/ supprime, runners/ reduit (mais on garde la
                       dispatch CLI jusqu a G07).
- Spec 13 §3.1 : Simulation (facade) vs SimulationView (vue catalogue).

SPECS : 01_structure_packages.md §5, 13_coherence_globale.md §3.

TACHES :

1. Rename process/ -> physics/ :
   - git mv hydromodpy/process hydromodpy/physics
   - Mettre a jour tous les imports (grep "hydromodpy.process" et "from .process").
   - Mettre a jour __init__.py (les symboles sont exposes depuis hmp.physics).
   - Attention : process/base/process_spatial.py contient ProcessSpatial —
     le renommer en PhysicalProcess (ou ProcessSpatial reste, juste le package
     change ; decider selon coherence). Par defaut, laisser ProcessSpatial comme
     nom de classe, seul le package devient physics.
   - Mettre a jour tests, examples, docs, CLAUDE.md (qui reference process/).

2. Rename simulation/results/ -> simulation/extraction/ :
   - git mv hydromodpy/simulation/results hydromodpy/simulation/extraction
   - Mettre a jour les imports (la collision avec le top-level results/ est
     levee ainsi).
   - Mettre a jour tests.

3. Rename SolverAdapter -> SolverRunner :
   - Fichier hydromodpy/solver/base/protocol.py :
       class SolverAdapter(Protocol)  ->  class SolverRunner(Protocol)
   - Idem dans hydromodpy/simulation/adapters/base.py
     (note : ces deux couches seront FUSIONNEES en G09. Pour G02, on se
      contente de renommer proprement les deux).
   - Grep les utilisations, adapter tous les imports et annotations.

4. Rename DataManagersPlanner -> DataPlanner :
   - hydromodpy/data/planner.py  ->  DataManagersPlanner renomme en DataPlanner.
   - Idem pour DataLoadPlan (garder ce nom) et DataManagersConfig (garder).
   - Adapter tous les imports.

5. Rename Geographic -> CatchmentDelineation :
   - hydromodpy/spatial/geographic/geographic.py  :
       class Geographic  ->  class CatchmentDelineation
   - Renommer aussi le fichier :
       git mv hydromodpy/spatial/geographic/geographic.py \\
              hydromodpy/spatial/geographic/catchment_delineation.py
   - Ajuster hmp.Geographic (public API) :
       - Remplacer par hmp.CatchmentDelineation (lazy import).
       - Casser l ancien nom : hmp.Geographic levera AttributeError.
   - Mettre a jour tous les usages dans hydromodpy/, tests/, examples/, docs/.

6. Supprimer la facade Watershed legacy :
   - Supprimer hydromodpy/watershed/ entierement (watershed.py, watershed_config.py, etc.).
   - Retirer l exposition public de Watershed dans hydromodpy/__init__.py.
   - Adapter ou supprimer tests/unit/test_watershed_*.py (selon pertinence).
   - Mettre a jour CHANGELOG (Breaking Changes).

7. Rename Simulation (vue catalogue) -> SimulationView :
   - hydromodpy/results/simulation.py :
       class Simulation  ->  class SimulationView
   - Garder hmp.Simulation (facade programmatique) comme ALIAS NON DEFINI : la
     classe facade se trouve dans project.py sous le nom Simulation et reste
     exportee. La vue catalogue s expose comme hmp.SimulationView.
   - Clarifier l expose public :
       - hmp.Simulation  = project.Simulation (facade)
       - hmp.SimulationView  = results.simulation.SimulationView (ex-Simulation)
   - Mettre a jour __init__.py lazy imports.
   - Mettre a jour tests (results/test_simulation*.py).

8. Assurer core/ feuille du DAG (pas d import hydromodpy.* except hydromodpy.core) :
   - hydromodpy/core/config/hydromodpy_config.py:34 importe DataManagersConfig
     depuis hydromodpy.data.data_managers_config — REFACTORISER pour eviter
     ce cycle. Options :
       (a) DataManagersConfig est deplace dans core/config/data_managers_config.py.
       (b) L import est retarde (TYPE_CHECKING + lazy).
     Choisir (b) pour minimiser le churn.
   - Verifier qu aucun autre from hydromodpy.<non-core> ne subsiste dans core/.
   - Grep command : rg "^from hydromodpy\\.(?!core)" hydromodpy/core.

9. Ajouter extra="forbid" au HydroModPyConfig racine :
   - hydromodpy/core/config/hydromodpy_config.py:63 ConfigDict ajouter extra="forbid".
   - Adapter les tests si des TOMLs d exemple contiennent des cles inconnues.

10. Mettre a jour CHANGELOG.md (section [Unreleased] ou [v0.5.0-dev]) :
    - Breaking: process/ -> physics/
    - Breaking: Geographic -> CatchmentDelineation
    - Breaking: SolverAdapter -> SolverRunner
    - Breaking: DataManagersPlanner -> DataPlanner
    - Breaking: simulation/results/ -> simulation/extraction/
    - Removed: hydromodpy.watershed (facade legacy)
    - Breaking: results.Simulation -> SimulationView
    - Breaking: HydroModPyConfig now forbids extra fields

11. Relancer pytest tests/unit/ -q  apres chaque rename substantiel pour
    attraper les regressions au fur et a mesure.

COMMITS attendus (12-18 petits) :
   [G02] - rename process to physics package
   [G02] - update physics imports everywhere
   [G02] - rename simulation results to extraction
   [G02] - rename solver adapter to runner
   [G02] - rename data managers planner
   [G02] - rename geographic to catchment delineation
   [G02] - delete watershed legacy facade
   [G02] - rename results simulation to simulationview
   [G02] - break core dag from data cycle
   [G02] - add extra forbid to hydromodpyconfig
   [G02] - update tests for renames
   [G02] - update docs for renames
   [G02] - update changelog breaking changes

CRITERES DE SUCCES :
- hydromodpy/process/ n existe plus, hydromodpy/physics/ existe.
- hydromodpy/simulation/results/ n existe plus, hydromodpy/simulation/extraction/ existe.
- hydromodpy/watershed/ n existe plus.
- grep -rn "class SolverAdapter\\|class DataManagersPlanner\\|class Geographic(" \\
       hydromodpy/  ne retourne que la nouvelle classe renommee (pas l ancienne).
- grep -rn "^from hydromodpy\\.(?!core)" hydromodpy/core/  ne retourne rien
  (hors TYPE_CHECKING).
- HydroModPyConfig a model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True).
- pytest tests/unit/ -q  passe.

SIGNALISATION : PHASE_G02_DONE
'
run_phase "G02" "Canonical renames (process->physics, Geographic, SolverRunner, DataPlanner, SimulationView, Watershed removal)" "$G02_PROMPT"

# ---------- G03 : Config refactor (HydroModelBase, pint, Forcing, GridConfig, to_toml) ----------
G03_PROMPT='
OBJECTIF : faire monter la couche Pydantic au niveau cible :
- HydroModelBase racine avec defauts stricts
- FlowConfig et sections migrees vers types pint (dette F01)
- TimeseriesVariableConfig factorisant les 14 configs timeseries
- Forcing discriminated union
- GridConfig unifie (suppression suffixe Schema)
- PHYSICAL_BOUNDS central
- to_toml(profile=...) round-trip via tomlkit

RAPPORT DE CONFORMITE — Items adresses :
- v0.5 #4 : HydroModelBase racine + refonte FlowConfig/Forcing/GridConfig + TimeseriesVariableConfig.
- v0.5 #5 : to_toml(profile=...) via tomlkit.
- Dette F01 : FlowConfig et sections vers pint.

SPEC : architecture_cible/02_config_pydantic.md.

TACHES :

1. Creer hydromodpy/core/config/base.py avec HydroModelBase :

   from pydantic import BaseModel, ConfigDict

   class HydroModelBase(BaseModel):
       """Racine de toutes les configs HydroModPy."""
       model_config = ConfigDict(
           extra="forbid",
           populate_by_name=True,
           validate_assignment=True,
           serialize_by_alias=True,
           ser_json_inf_nan="strings",
       )

   Faire heriter TOUTES les configs de HydroModelBase (grep "class .*BaseModel"
   dans hydromodpy/**/config*.py et remplacer la base).
   HydroModPyConfig herite aussi de HydroModelBase (racine aggregative).

2. Migrer hydromodpy/physics/flow/flow_config.py vers pint :
   - Remplacer les float nus + field_validator(normalize_length_unit/parse_to_m)
     par les types pint annotes appropries (Length, FlowRate, Time, etc.).
   - Verifier coherence avec physical_properties.py (deja en place depuis P03).

3. Migrer boundary_conditions_config.py et initial_conditions_config.py
   (hydromodpy/physics/flow/) vers pint.

4. Creer TimeseriesVariableConfig (hydromodpy/data/timeseries_variable_config.py) :
   - Un unique BaseConfig pour les 14 configs timeseries (etp, precipitation,
     humidity, wind, pressure, radiation, temperature, etc.).
   - Champs : variable_name, source, unit, aggregation, validation_rules, etc.
   - Les 14 configs existantes deviennent des instances/specialisations minimales
     de TimeseriesVariableConfig, ou disparaissent au profit d une declaration
     unique parametree.
   - Adapter le TOML pour la nouvelle structure : [timeseries.<variable>] blocks
     au lieu de [etp], [precipitation], etc.

5. Creer hydromodpy/physics/flow/forcing.py avec Forcing discriminated union :

   from typing import Literal, Union, Annotated
   from pydantic import Field

   class ConstantForcing(HydroModelBase):
       kind: Literal["constant"] = "constant"
       value: FlowRate

   class SyntheticForcing(HydroModelBase):
       kind: Literal["synthetic"] = "synthetic"
       pattern: str
       amplitude: FlowRate
       period: Time

   class CsvForcing(HydroModelBase):
       kind: Literal["csv"] = "csv"
       path: Path
       column: str
       unit: str | None = None

   Forcing = Annotated[
       Union[ConstantForcing, SyntheticForcing, CsvForcing],
       Field(discriminator="kind"),
   ]

   Integrer dans FlowRuntimeConfig (nouveau dataclass frozen si absent).

6. Unifier GridConfig et supprimer les suffixes "Schema" :
   - Chercher toutes les classes *Schema dans hydromodpy/**/config*.py
     (31 d apres l audit).
   - Renommer sans le suffixe : SGridConfigSchema -> SGridConfig (si
     SGridConfig existe deja, fusionner).
   - Pour GridConfig specifiquement : fusionner SGridConfig et toute autre
     forme de GridConfig en UN SEUL GridConfig unifie (champs : origin_x, origin_y,
     cell_size, n_rows, n_cols, crs, etc.).
   - Supprimer les doublons historiques.

7. Creer hydromodpy/spatial/field/core/physical_bounds.py :

   PHYSICAL_BOUNDS = {
       "hydraulic_conductivity": (1e-12, 1e2, "m/s"),
       "specific_storage":       (1e-8, 1e-2, "1/m"),
       "specific_yield":         (0.0, 1.0, "-"),
       "porosity":               (0.0, 1.0, "-"),
       "elevation":              (-500.0, 9000.0, "m"),
       "recharge":               (0.0, 10.0, "m/year"),
       # ... etc pour 15-20 grandeurs physiques classiques
   }

   def validate_physical_value(name: str, value: float, unit: str = None):
       """Leve ConfigValidationError si value hors bornes."""
       ...

   Cabler validate_physical_value dans les configs section-level (flow,
   transport, physical_properties).

8. Implementer to_toml(profile=...) via tomlkit :
   - hydromodpy/core/config/hydromodpy_config.py : methode
       def to_toml(self, path: Path, *, profile: Literal["user","dev","expert"] = "user") -> None
   - Utiliser tomlkit pour round-trip preservant les commentaires.
   - Filtrer les champs selon ParamLevel et le profile (user voit user+moins,
     dev voit user+dev, expert voit tout).
   - Test : from_toml -> to_toml -> from_toml doit donner le meme config.

9. Ajouter model_validator cross-section dans HydroModPyConfig :
   - solver.engine == packages.engine (coherence)
   - flow_regime == "transient" implique initial_conditions defini
   - data.inference_mode == "strict" implique au moins un data manager declare

10. Resoudre xfail tests s il en reste dans tests/unit/config/.

11. Dependance : verifier que tomlkit est dans pyproject.toml core deps
    (pas optional). Sinon l ajouter.

12. Mettre a jour CHANGELOG.md :
    - Added: HydroModelBase root config class
    - Added: Forcing discriminated union (constant/synthetic/csv)
    - Added: TimeseriesVariableConfig factorisation
    - Added: PHYSICAL_BOUNDS central + validate_physical_value
    - Added: to_toml(profile=...) round-trip via tomlkit
    - Breaking: FlowConfig / BoundaryConditionsConfig / InitialConditionsConfig
      migres vers types pint annotes
    - Breaking: suffixe Schema retire de 31 classes config
    - Breaking: TimeseriesVariableConfig remplace les 14 configs specifiques

COMMITS attendus (12-20 petits) :
   [G03] - add hydromodelbase root config
   [G03] - rebase all configs on hydromodelbase
   [G03] - migrate flow config to pint types
   [G03] - migrate boundary conditions to pint
   [G03] - migrate initial conditions to pint
   [G03] - add timeseries variable config factorisation
   [G03] - migrate 14 timeseries configs
   [G03] - add forcing discriminated union
   [G03] - wire forcing into flow runtime
   [G03] - unify gridconfig variants
   [G03] - drop schema suffix from config classes
   [G03] - add physical bounds registry
   [G03] - wire validate physical value
   [G03] - implement to_toml via tomlkit
   [G03] - add cross section validator
   [G03] - update tests for config refactor
   [G03] - changelog v050 config breaking

CRITERES DE SUCCES :
- HydroModelBase existe, herite par TOUTES les configs (grep ConfigDict check).
- flow_config.py importe les types pint (Length, FlowRate, etc.).
- TimeseriesVariableConfig existe et remplace les 14 ex-configs.
- Forcing union + discriminator fonctionne (test from TOML).
- PHYSICAL_BOUNDS dans spatial/field/core/physical_bounds.py, 15+ entrees.
- to_toml round-trip test passe (write + read -> equality).
- 0 classe *Schema restante dans hydromodpy/ (hors JSON Schema classes qui
  restent pour le frontend).
- pytest tests/unit/config/ -v  passe entierement (0 xfail restant).
- pytest tests/unit/ -q  passe.

SIGNALISATION : PHASE_G03_DONE
'
run_phase "G03" "Config refactor (HydroModelBase, pint, Forcing, GridConfig, PHYSICAL_BOUNDS, to_toml)" "$G03_PROMPT"

# ---------- G04 : Data modernization ----------
G04_PROMPT='
OBJECTIF : moderniser completement la couche data :
- HTTPClient unique (backoff, Retry-After, SHA-256 streaming, token bucket)
- Contrats pandera + DataContractViolation
- InputCatalog refactore (7 tables : artifacts/provenance/stations/coverage/failures/validation_reports/entries)
- Lockfile hydromodpy.lock + commandes hmp lock
- hmp data {remove, prune, export, import, check --fix}
- runtime_loader.py -> loader.py pur
- Suppression base_field_manager.py

RAPPORT DE CONFORMITE — Items adresses :
- v0.5 #6 : HTTPClient unique.
- v0.5-v0.6 #11 : data/schemas/ pandera + DataContractViolation.
- v0.5-v0.6 #12 : cache DuckDB 6 tables (on fera 7 en alignement OVERRIDE).
- v0.5-v0.6 #13 : hmp data remove/prune/export/import + check --fix.
- v0.5-v0.6 #14 : Lockfile hydromodpy.lock + hmp lock.

SPEC : architecture_cible/03_data_contracts.md + 12_input_data_rethink.md.

TACHES :

1. Implementer hydromodpy/core/io/http_client.py (scaffold pose en G01) :
   class HTTPClient:
       - session persistante (requests.Session + httpx option).
       - backoff exponentiel + jitter configurable.
       - respect Retry-After.
       - timeout defaut 30s.
       - token bucket pour limiter concurrency par host.
       - stream() yields chunks tout en calculant SHA-256.
       - get_json() + validation via Pydantic model fournie.
       - hooks avant/apres pour instrumentation (logging).

   Integrer dans hydromodpy/data/common/clients/sim2_meteofrance.py
   (remplacer les appels directs requests par HTTPClient).
   Faire de meme pour les autres clients (hydrometry, BDlisa, etc.).

2. Creer hydromodpy/data/schemas/ (pandera) :
   - __init__.py
   - timeseries.py     : TimeSeriesSchema (columns date, value, validation rules)
   - stations.py       : StationCollectionSchema (station_id, lat, lon, z, name)
   - dem.py            : DEMContract (2D grid, CRS, resolution >= 1m, valid range)
   - lithology.py      : LithologyTableSchema (zone_id, conductivity, porosity, layer_thickness)
   - catchment.py      : CatchmentPolygonSchema (geometry, area_km2, crs, outlet)

   Importer pandera dans pyproject.toml (ajouter a dependencies si absent).

   Cabler les schemas dans les managers correspondants : apres _fetch_from_source,
   appeler Schema.validate(df) qui leve pandera.errors.SchemaError si non
   conforme, que l on re-leve comme DataContractViolation (deja definie en G01).

3. Refactor InputCatalog (hydromodpy/data/registry/catalog_duckdb.py) :

   Creer les tables suivantes (SQL exec) :
   - entries              : (id, variable, source, is_custom, path, file_mtime, ...) — existe
   - artifacts            : (id, sim_id, artifact_type, path, sha256, size, created_at)
   - provenance           : (artifact_id, input_hash, tool_name, tool_version, parameters_json)
   - stations             : (station_id, variable, lat, lon, z, name, source, first_valid, last_valid)
   - coverage             : (variable, region_geom, period_start, period_end, n_stations)
   - failures             : (id, variable, source_ref, error_type, message, occurred_at)
   - validation_reports   : (id, artifact_id, schema_name, passed, errors_json, validated_at)

   Ajouter les methodes write_provenance, write_failure, write_validation_report,
   write_artifact, etc.
   Utiliser des transactions pour les insertions en bulk.

   Integrer SHA-256 quand on veut tracer l integrite : calculer via HTTPClient
   streaming, stocker dans artifacts.sha256 ET provenance.input_hash.
   (NB : l invalidation du CACHE reste basee sur mtime selon OVERRIDE F06 ;
    le SHA-256 sert uniquement a la tracabilite/provenance, pas a l invalidation.)

4. Creer hydromodpy/data/lockfile.py :
   - Serialize (TOML) : pour chaque variable+source, enregistrer
     (url, sha256, fetched_at, file_mtime, size_bytes).
   - Methodes : write_lockfile(catalog, dest), read_lockfile(path),
     verify_frozen(catalog, lockfile) -> list of mismatches.

   Ajouter sous-commande CLI hmp lock (dans __main__.py ou _cli/ selon G07) :
   - hmp lock update       : scanne le catalog, ecrit hydromodpy.lock.
   - hmp lock archive      : creer archive tar.zst de tous les artifacts + lockfile.
   - hmp lock restore      : applique une archive + verifie SHA-256.

   Ajouter flag --frozen a hmp run / hmp data add :
   - --frozen : refuse de telecharger si le lockfile existe et qu une entree
     manque ; rejette toute divergence SHA-256.

5. Etendre la CLI hmp data :
   - hmp data remove <variable>           : purge une variable du cache + fichiers.
   - hmp data prune [--older-than N]      : purge les caches anciens non utilises.
   - hmp data export <out.tar.zst>        : exporte tout le cache (pour partage).
   - hmp data import <in.tar.zst>         : importe un cache partage.
   - hmp data check --fix                 : tente de reparer les entrees
     inconsistantes (re-scan, re-hash, repair index).

   Cabler dans __main__.py ou _cli/data.py.

6. Refondre runtime_loader.py en loader.py pur :
   - hydromodpy/data/loader.py          : fonctions pures (fetch / cache / load)
     sans etat partage. Interface :
       def load_variable(variable_name, catalog, config, context) -> LoadResult
   - Supprimer hydromodpy/data/runtime_loader.py (891 lignes) apres migration
     de tous les callers.

7. Supprimer base_field_manager.py (386 lignes) :
   - Les managers qui en heritaient doivent heriter directement de
     BaseVariableManager ou d une nouvelle base factoree.
   - Si des helpers sont utiles, les integrer dans data/common/base_manager.py
     directement.

8. Flatten data/common/ :
   - hydromodpy/data/common/base_manager.py   -> hydromodpy/data/base_manager.py
   - hydromodpy/data/common/base_config.py    -> hydromodpy/data/base_config.py
   - hydromodpy/data/common/clients/           reste tel quel (sous-dossier utile).
   - Adapter tous les imports.

9. Introduire Protocol DataSource + @register_source :
   - hydromodpy/data/sources.py (ou data/source_protocol.py) :
       class DataSource(Protocol):
           variable_type: str
           source_name: str
           def fetch(ctx) -> LoadResult: ...
   - Migrer les managers vers ce protocole (optionnel mais recommande).
   - Pour simplifier v0.5 : garder BaseVariableManager ABC pour les managers
     complexes, utiliser DataSource pour les sources simples (entry_points).

10. Mettre a jour CHANGELOG.md :
    - Added: HTTPClient unique with backoff / Retry-After / SHA-256 streaming.
    - Added: pandera schemas + DataContractViolation.
    - Added: InputCatalog 7 tables (artifacts/provenance/stations/coverage/failures/validation_reports).
    - Added: Lockfile hydromodpy.lock + hmp lock subcommands.
    - Added: hmp data {remove, prune, export, import, check --fix}.
    - Removed: hydromodpy/data/runtime_loader.py (replaced by loader.py).
    - Removed: hydromodpy/data/base_field_manager.py.

COMMITS attendus (15-22 petits) :
   [G04] - implement http client core
   [G04] - wire http client in sim2 client
   [G04] - wire http client in other clients
   [G04] - add data schemas package scaffold
   [G04] - add timeseries pandera schema
   [G04] - add stations pandera schema
   [G04] - add dem contract
   [G04] - add lithology pandera schema
   [G04] - wire pandera in managers
   [G04] - refactor input catalog to 7 tables
   [G04] - add provenance tracking
   [G04] - add lockfile module
   [G04] - add hmp lock subcommand
   [G04] - add frozen mode flag
   [G04] - extend hmp data subcommands
   [G04] - add pure data loader
   [G04] - remove runtime loader
   [G04] - remove base field manager
   [G04] - flatten data common structure
   [G04] - add data source protocol
   [G04] - update tests for data refactor
   [G04] - changelog v050 data breaking

CRITERES DE SUCCES :
- hydromodpy/core/io/http_client.py implemente + utilise dans les clients.
- hydromodpy/data/schemas/ contient 5 fichiers + __init__.
- Tables InputCatalog etendues a 7 : verifiable via DuckDB query.
- hydromodpy/data/lockfile.py existe + hmp lock CLI fonctionnel.
- hmp data --help liste remove/prune/export/import/check avec --fix.
- hydromodpy/data/runtime_loader.py supprime.
- hydromodpy/data/base_field_manager.py supprime.
- pytest tests/unit/ -q  passe.
- pytest tests/unit/data_managers/ -v  passe.

SIGNALISATION : PHASE_G04_DONE
'
run_phase "G04" "Data modernization (HTTPClient, pandera, InputCatalog 7 tables, lockfile, hmp lock)" "$G04_PROMPT"

# ---------- G05 : Storage upgrades (CF-UGRID Zarr, DuckDB tables/views, .hmp tar.zst, FieldRegistry) ----------
G05_PROMPT='
OBJECTIF : finir le scope storage :
- 4 nouvelles tables DuckDB : runs_environment, tags, stations, observations
- Vues denormalisees
- CF-1.11 / UGRID-1.0 metadonnees Zarr
- SimulationZarr.to_xarray + SimulationGroup.to_xarray(variable, dim="sim")
- Format .hmp tar.zst + manifest.json + SHA-256
- FieldRegistry (results/field_registry.py)
- Chunking balanced option

RAPPORT DE CONFORMITE — Items adresses :
- v0.5 #2 : field_registry.py + FieldDescriptor + 18 CF entries.
- v0.5-v0.6 #9 : CF-1.11 / UGRID-1.0 Zarr.
- v0.5-v0.6 #10 : 4 nouvelles tables DuckDB + vues denormalisees.
- v0.6+ #22 : format .hmp tar.zst + manifest.json.

SPEC : architecture_cible/04_storage_ideal.md + 13_coherence_globale.md §1.3.

TACHES :

1. Ajouter 4 tables DuckDB dans hydromodpy/results/catalog_schema.py :

   CREATE TABLE runs_environment (
       sim_id UUID NOT NULL,
       python_version VARCHAR,
       hydromodpy_version VARCHAR,
       platform VARCHAR,
       hostname VARCHAR,
       user_name VARCHAR,
       cpu_info JSON,
       memory_gb DOUBLE,
       git_commit VARCHAR,
       env_packages JSON,
       recorded_at TIMESTAMPTZ,
       PRIMARY KEY (sim_id)
   );

   CREATE TABLE tags (
       sim_id UUID NOT NULL,
       tag VARCHAR NOT NULL,
       added_at TIMESTAMPTZ,
       added_by VARCHAR,
       PRIMARY KEY (sim_id, tag)
   );

   CREATE TABLE stations (
       station_id VARCHAR NOT NULL,
       name VARCHAR,
       latitude DOUBLE,
       longitude DOUBLE,
       elevation DOUBLE,
       variable_type VARCHAR NOT NULL,
       source VARCHAR,
       active BOOLEAN DEFAULT TRUE,
       first_valid DATE,
       last_valid DATE,
       metadata JSON,
       PRIMARY KEY (station_id, variable_type)
   );

   CREATE TABLE observations (
       station_id VARCHAR NOT NULL,
       variable_type VARCHAR NOT NULL,
       datetime TIMESTAMPTZ NOT NULL,
       value DOUBLE,
       unit VARCHAR,
       quality VARCHAR,
       PRIMARY KEY (station_id, variable_type, datetime)
   );

   Mettre a jour TABLE_NAMES list (16 tables au total).
   Mettre a jour les tests test_catalog_schema.py.

2. Ajouter vues denormalisees :

   CREATE VIEW v_simulation_summary AS
     SELECT s.sim_id, s.project, s.status, s.created_at,
            m.nse, m.kge, m.rmse
     FROM simulations s
     LEFT JOIN (SELECT sim_id, MAX(value) FILTER (WHERE metric_name = nse) AS nse, ...)
     ...
     ;

   CREATE VIEW v_best_per_project AS
     SELECT project, sim_id, nse, kge, rmse
     FROM v_simulation_summary
     QUALIFY ROW_NUMBER() OVER (PARTITION BY project ORDER BY nse DESC NULLS LAST) = 1
     ;

   CREATE VIEW v_params_wide AS
     PIVOT parameters ON param_name USING FIRST(value)
     ;

   CREATE VIEW v_metrics_wide AS
     PIVOT metrics ON metric_name USING FIRST(value)
     ;

   (syntaxe DuckDB, adapter si la version utilisee a des limitations).

3. Renommer parameters.zone_id DEFAULT "_homogeneous" -> "__global__" :
   - Aligner avec la convention spec 04 §2.2 L357.
   - Mettre a jour les inserts dans persistence.py et tests.

4. Creer hydromodpy/results/field_registry.py :

   @dataclass(frozen=True)
   class FieldDescriptor:
       name: str                 # nom court (head, recharge, etc.)
       standard_name: str        # CF standard_name
       long_name: str            # descriptif humain
       units: str                # pint-compatible
       cell_methods: str         # CF cell_methods
       grid_mapping: str         # CF grid_mapping ref
       coordinates: tuple        # dims (time, layer, cell) etc.

   FIELD_REGISTRY: dict[str, FieldDescriptor] = {
       "head":                FieldDescriptor("head", "subsurface_head", ...),
       "recharge":            FieldDescriptor("recharge", "recharge_flux", ...),
       "watertable_elevation": FieldDescriptor(...),
       "watertable_depth":    FieldDescriptor(...),
       "seepage_mask":        FieldDescriptor(...),
       "fluxes_from_budget":  FieldDescriptor(...),
       "drain":               FieldDescriptor(...),
       "well":                FieldDescriptor(...),
       "river":               FieldDescriptor(...),
       "topography":          FieldDescriptor(...),
       "hydraulic_conductivity": FieldDescriptor(...),
       "specific_yield":      FieldDescriptor(...),
       "specific_storage":    FieldDescriptor(...),
       "porosity":            FieldDescriptor(...),
       "layer_thickness":     FieldDescriptor(...),
       "cell_budget":         FieldDescriptor(...),
       "storage_change":      FieldDescriptor(...),
       "concentration":       FieldDescriptor(...),
   }  # 18 entrees min

   def get(name) -> FieldDescriptor: ...
   def all_names() -> list[str]: ...

5. Cabler FIELD_REGISTRY dans Zarr writes :
   - hydromodpy/results/zarr_store.py : quand on ecrit un field, attacher
     les attrs CF (standard_name, long_name, units, cell_methods, grid_mapping,
     coordinates) depuis FIELD_REGISTRY.get(field_name).
   - Ajouter zarr.consolidate_metadata(store) a la fin de chaque simulation.

6. Implementer metadata UGRID-1.0 dans le groupe mesh/ :
   - attributs : Conventions="CF-1.11 UGRID-1.0"
   - variable mesh topology virtuelle avec cf_role="mesh_topology",
     topology_dimension=2, node_coordinates="node_x node_y",
     face_node_connectivity="face_node_connectivity".
   - write_time function pour ecrire la variable time avec units CF
     ("seconds since <epoch>") et calendar.
   - scalar crs variable avec attributs grid_mapping_name,
     semi_major_axis, inverse_flattening, etc.

7. Implementer SimulationZarr.to_xarray() :
   - Retourne un xr.Dataset avec tous les fields consolides (time, layer, cell)
     + attrs CF/UGRID.

8. Implementer SimulationGroup.to_xarray(variable, dim="sim") :
   - Concatene les xr.Dataset.variable de chaque simulation sur une dimension
     "sim" (sim_id comme coord).

9. Refactor hmp_package exporter :
   - hydromodpy/results/exporters/hmp_package.py :
     Produire un VRAI tar.zst contenant :
       manifest.json          # sim_id, versions, creation_date, file_list, sha256
       catalog_snapshot.db    # copy of hydromodpy.duckdb filtered to sim_id
       simulation.zarr/       # copy of the Zarr store
       README.md              # description
     Chaque fichier a sa ligne dans manifest.json avec son sha256.
   - Import : verifier signatures + decompresser + enregistrer dans
     SimulationCatalog.
   - Garder l API catalog.export_package / import_package (rename F05).

10. Chunking Zarr balanced :
    - Ajouter option balanced=True a SimulationZarr init qui calcule
      un chunk target size ~1 MiB en equilibrant (time_chunk, layer_chunk,
      cell_chunk). Par defaut garder (1, n_layers, n_cells).

11. Mettre a jour CHANGELOG :
    - Added: 4 new DuckDB tables (runs_environment, tags, stations, observations).
    - Added: 4 denormalized views (v_simulation_summary, v_best_per_project,
      v_params_wide, v_metrics_wide).
    - Added: FieldDescriptor registry in results/field_registry.py (18 CF entries).
    - Added: CF-1.11 / UGRID-1.0 metadata on Zarr stores.
    - Added: SimulationZarr.to_xarray() + SimulationGroup.to_xarray(variable, dim="sim").
    - Added: .hmp portable package (tar.zst + manifest.json + SHA-256).
    - Breaking: parameters.zone_id default renamed _homogeneous -> __global__.

COMMITS attendus (14-20 petits) :
   [G05] - add runs environment table
   [G05] - add tags table
   [G05] - add stations table
   [G05] - add observations table
   [G05] - add simulation summary view
   [G05] - add best per project view
   [G05] - add wide pivot views
   [G05] - rename zone id default global
   [G05] - add field registry module
   [G05] - populate field registry 18 entries
   [G05] - wire field registry in zarr writes
   [G05] - add cf ugrid metadata to zarr
   [G05] - consolidate zarr metadata at finalize
   [G05] - implement zarr to xarray
   [G05] - implement group to xarray sim dim
   [G05] - rewrite hmp package exporter tarzst
   [G05] - verify manifest sha256 on import
   [G05] - add balanced chunking option
   [G05] - update tests storage layer
   [G05] - changelog v050 storage

CRITERES DE SUCCES :
- hydromodpy.duckdb (nouveau catalog) liste 16 tables + 4 vues.
- hydromodpy/results/field_registry.py : 18+ FieldDescriptor.
- Zarr stores ont Conventions="CF-1.11 UGRID-1.0" en attribut racine.
- SimulationZarr(sim_id).to_xarray() retourne un Dataset valide.
- catalog.export_package produit un .hmp qui est un fichier tar.zst.
- Test import/export hmp : round-trip equal.
- pytest tests/unit/ -q  passe.

SIGNALISATION : PHASE_G05_DONE
'
run_phase "G05" "Storage upgrades (DuckDB tables+views, CF-UGRID Zarr, .hmp tar.zst, FieldRegistry)" "$G05_PROMPT"

# ---------- G06 : Display infrastructure + extended figures ----------
G06_PROMPT='
OBJECTIF : completer le scope display :
- Theme + colormaps banlist + renderer BackendManager
- display/geo/ (GeoFigureMixin)
- core/units/labels.py
- DisplayConfig enrichi (enabled/backend/preset/show/overrides)
- Corpus figures etendu : duration_curve, recession, Piper, Stiff, Schoeller,
  seasonal_boxplot, side_by_side, ensemble_band, calibration plots (convergence,
  pairplot), watershed_id_card.
- Tests d interdiction (no banned cmap, no matplotlib side effects, display
  never writes to Zarr).

RAPPORT DE CONFORMITE — Items adresses :
- v0.5-v0.6 #15 : infrastructures display cibles.
- v0.5-v0.6 #16 : corpus figures etendu.

SPEC : architecture_cible/08_postprocess_display.md §3.3–§3.5 / §6 / §8 / §9.

TACHES :

1. Creer hydromodpy/display/theme.py :
   @dataclass(frozen=True)
   class Theme:
       name: str
       palette: list[str]           # couleurs par defaut
       grid_alpha: float
       font_family: str
       font_size_base: int
       title_weight: str
       background: str
       foreground: str

   THEMES = {
       "default": Theme("default", ["#1f77b4","#ff7f0e",...], 0.3, "sans-serif", 10, "bold", "white", "black"),
       "print":   Theme("print", ["#000","#555",...], 0.5, "serif", 9, "normal", "white", "black"),
       "dark":    Theme("dark", ["#8aa","#ed8",...], 0.3, "sans-serif", 10, "bold", "#222", "white"),
   }

   apply_theme(theme_name) : configure matplotlib.rcParams.

2. Creer hydromodpy/display/colormaps.py :
   BANNED_CMAPS = {"jet", "rainbow", "hsv", "nipy_spectral", "gist_rainbow"}
   PREFERRED_CMAPS = {
       "sequential": "viridis",
       "diverging":  "RdBu_r",
       "cyclic":     "twilight",
   }
   def get_cmap(name, kind="sequential"):
       if name in BANNED_CMAPS: raise ValueError(f"{name} banni (perceptual).")
       return matplotlib.cm.get_cmap(name)
   def check_no_banned_in_call(call_args): ...  # pour les tests

3. Creer hydromodpy/display/renderer.py :
   class BackendManager:
       def __init__(self, interactive: bool, dpi: int = 150):
           self.interactive = interactive
           self.dpi = dpi
       def __enter__(self):
           import matplotlib
           matplotlib.use("Agg" if not self.interactive else "default")
           ...
       def __exit__(self, exc_type, exc, tb):
           import matplotlib.pyplot as plt
           plt.close("all")

   def save_figure(fig, path, dpi=150, fmt="png"): ...

4. Creer hydromodpy/display/geo/ :
   - __init__.py
   - mixin.py : GeoFigureMixin (pour figures geo : basemap, CRS, scale bar)
   - basemaps.py : helpers contextily / stamen (optionnel).

5. Creer hydromodpy/core/units/labels.py :
   AXIS_LABELS = {
       "head":      "Hydraulic head (m)",
       "recharge":  "Recharge (m/y)",
       "discharge": "Discharge (m^3/s)",
       ...
   }
   def axis_label(field_name: str, unit: str = None) -> str: ...

6. Enrichir DisplayConfig (hydromodpy/display/config.py) :
   - enabled: bool = True
   - backend: Literal["agg", "qt5agg", "auto"] = "auto"
   - preset: Literal["default", "print", "dark"] = "default"
   - show: bool = False     # interactive affichage
   - save: bool = True
   - output_dir: Path | None = None
   - dpi: int = 150
   - figures: list[FigureSpec] = []   # liste cherry-pick de figures a generer
   - overrides: dict[str, dict] = {}  # overrides par figure (fg, color, etc.)
   - cmap: str = "viridis"

   Cabler preset via apply_theme au demarrage de display session.

7. Implementer 11 nouvelles figures dans hydromodpy/display/figures/ :

   duration_curve.py       : @register DurationCurveFigure
   recession.py            : @register RecessionCurveFigure
   piper_diagram.py        : @register PiperDiagramFigure
   stiff_diagram.py        : @register StiffDiagramFigure
   schoeller_diagram.py    : @register SchoellerDiagramFigure
   seasonal_boxplot.py     : @register SeasonalBoxplotFigure
   side_by_side_map.py     : @register SideBySideMapFigure
   ensemble_band.py        : @register EnsembleBandFigure (pour SimulationGroup)
   calibration_convergence.py : @register CalibrationConvergenceFigure
   calibration_pairplot.py    : @register CalibrationPairplotFigure
   watershed_id_card.py    : @register WatershedIdCardFigure (multi-panel)

   Chacune herite de BaseFigure, implemente plot(sim, save_path=None).
   Piper/Stiff/Schoeller prennent un Simulation OU un DataFrame hydrochimie.
   ensemble_band prend un SimulationGroup.
   watershed_id_card combine 4-6 sous-figures dans un GridSpec.

8. Ajouter tests d interdiction (tests/unit/display/) :
   - test_no_banned_cmap_in_display.py : grep AST tous les display/figures/*.py
     pour matplotlib cmap calls, reject si BANNED.
   - test_no_matplotlib_side_effects.py : importer hydromodpy.display ne doit
     PAS modifier rcParams au module level.
   - test_display_never_writes_to_zarr.py : import hydromodpy.display,
     instancier chaque figure, verifier qu aucune ecriture vers Zarr (mock).

9. Implementer _repr_html_ sur les classes restantes :
   - HydroMesh (hydromodpy/spatial/mesh/?)     : table stats + thumbnail SVG.
   - CatchmentDelineation (ex-Geographic)       : table + outlet/area.
   - SimulationPlan                             : table des ProcessRun planifies.
   - Simulation (facade project.py)             : resume run + status + metric summary.

10. Mettre a jour CHANGELOG :
    - Added: display/theme.py + apply_theme.
    - Added: display/colormaps.py with BANNED_CMAPS.
    - Added: display/renderer.py BackendManager.
    - Added: display/geo/ mixin.
    - Added: core/units/labels.py.
    - Added: 11 new figures (duration_curve, recession, Piper, Stiff, Schoeller,
      seasonal_boxplot, side_by_side, ensemble_band, calibration_convergence,
      calibration_pairplot, watershed_id_card).
    - Added: _repr_html_ on HydroMesh / CatchmentDelineation / SimulationPlan / Simulation.
    - Added: DisplayConfig enriched (enabled, backend, preset, show, overrides, cmap).

COMMITS attendus (18-25 petits) :
   [G06] - add display theme module
   [G06] - add display colormaps banlist
   [G06] - add display renderer backend manager
   [G06] - add display geo mixin
   [G06] - add core units labels
   [G06] - enrich display config
   [G06] - add duration curve figure
   [G06] - add recession curve figure
   [G06] - add piper diagram figure
   [G06] - add stiff diagram figure
   [G06] - add schoeller diagram figure
   [G06] - add seasonal boxplot figure
   [G06] - add side by side map figure
   [G06] - add ensemble band figure
   [G06] - add calibration convergence figure
   [G06] - add calibration pairplot figure
   [G06] - add watershed id card figure
   [G06] - add repr html on hydromesh
   [G06] - add repr html on catchment delineation
   [G06] - add repr html on simulationplan
   [G06] - add repr html on simulation facade
   [G06] - test no banned cmap in display
   [G06] - test no matplotlib side effects
   [G06] - test display never writes zarr
   [G06] - changelog v050 display

CRITERES DE SUCCES :
- hydromodpy/display/theme.py + colormaps.py + renderer.py + geo/ + labels.py existent.
- display/figures/ contient 20 figures (9 canoniques + 11 nouvelles).
- DisplayConfig champs : enabled, backend, preset, show, save, output_dir, dpi,
  figures, overrides, cmap.
- 3 tests d interdiction passent.
- _repr_html_ present sur les 4 classes cibles (grep check).
- pytest tests/unit/display/ -q  passe.
- pytest tests/unit/ -q  passe.

SIGNALISATION : PHASE_G06_DONE
'
run_phase "G06" "Display infrastructure + extended figures corpus + _repr_html_ extras" "$G06_PROMPT"

# ---------- G07 : CLI completion (_cli/ refactor, missing subcommands, pipeline flags) ----------
G07_PROMPT='
OBJECTIF : completer la CLI :
- Refactor hydromodpy/__main__.py (1890 lignes) -> _cli/ package modulaire.
- Ajouter les sous-commandes manquantes : doctor, inspect, best, worst, delete,
  completion, --version.
- Ajouter hmp config {check, template} sous-parsers.
- Ajouter hmp run --until/--from/--dry-run/--no-checkpoint.
- Supprimer le top-level runners/ (absorbe dans _cli/).

RAPPORT DE CONFORMITE — Items adresses :
- v0.5 #3 : sous-commandes manquantes.
- v0.5-v0.6 #13 : hmp data extras (fait en G04).
- v0.6+ #17 : refactor _cli/ + hmp config {check, template}.
- v0.6+ #24 : CLI --until/--from/--dry-run/--no-checkpoint (spec 06 §5.4).

SPEC : architecture_cible/10_ux_cli_api.md §5.1 + 01_structure_packages.md §3 + 06_pipeline_execution.md §5.4.

TACHES :

1. Creer hydromodpy/_cli/ package :
   - __init__.py                (expose main)
   - main.py                    (argparse top-level, dispatch)
   - commands/
       - __init__.py
       - init.py                (hmp init)
       - new.py                 (hmp new)
       - config_cmd.py          (hmp config + sous-parsers check/template)
       - run.py                 (hmp run + flags --until/--from/--dry-run/--no-checkpoint/--resume)
       - display.py             (hmp display)
       - list.py                (hmp list)
       - export.py              (hmp export)
       - show.py                (hmp show)
       - compare.py             (hmp compare)
       - import_cmd.py          (hmp import)
       - calibrate.py           (hmp calibrate)
       - schema.py              (hmp schema export + validate-field)
       - test.py                (hmp test unit / regression / --fast / --extensive / --update-goldens)
       - data.py                (hmp data {check, list, add, remove, prune, export, import, check --fix})
       - lock.py                (hmp lock {update, archive, restore})
       - doctor.py              (hmp doctor - NOUVEAU)
       - inspect.py             (hmp inspect <sim_id> - NOUVEAU)
       - best.py                (hmp best <project> --metric nse - NOUVEAU)
       - worst.py               (hmp worst <project> --metric nse - NOUVEAU)
       - delete.py              (hmp delete <sim_id> - NOUVEAU)
       - completion.py          (hmp completion bash/zsh/fish - NOUVEAU)
   - helpers.py                 (exit codes, error formatting, output helpers)

   Chaque fichier commands/*.py expose une fonction register(subparsers)
   qui ajoute son sous-parser et une fonction cmd_*(args) qui execute.

2. Implementer les sous-commandes NOUVELLES :

   - hmp doctor :
       Check environnement (Python, OS, deps, venv activation),
       test import hydromodpy, test DuckDB, test solvers disponibles,
       report table (OK / KO + conseils).
       Reutiliser hydromodpy/core/diagnostics/ (creer si absent).

   - hmp inspect <sim_id> :
       Affiche metadata sim + status + mesh summary + files present.
       Format table ASCII ou --json.

   - hmp best <project> [--metric nse] :
       Lists top 1 sim pour <project> selon metric.

   - hmp worst <project> [--metric nse] :
       Lists bottom 1 sim.

   - hmp delete <sim_id> :
       Supprime la sim (DuckDB row + Zarr store). Demande confirmation,
       skipable avec -y.

   - hmp completion [bash|zsh|fish] :
       Genere le script completion pour le shell demande (utiliser
       argcomplete ou genere manuellement depuis les sous-parsers).

   - hmp --version / hmp -V :
       Imprime __version__ + core Python + platform + commit Git.

3. Implementer hmp config {check, template} :
   - hmp config check <file.toml> :
       Valide un TOML contre le schema. Exit 0 si OK, exit EXIT_CONFIG si KO
       avec liste detaillee des violations.
   - hmp config template <out.toml> [--profile user|dev|expert] :
       Existant a renommer en sous-parser (actuel hmp config = template).

4. Ajouter flags au hmp run :
   - --until STEP       : s arreter apres le step STEP.
   - --from STEP        : reprendre au step STEP (precise).
   - --dry-run          : afficher le plan, ne pas executer.
   - --no-checkpoint    : desactiver l ecriture des checkpoints.
   - --resume RUN_ID    : existant, a preserver.

5. Supprimer hydromodpy/runners/ (top-level) :
   - Les shells simulation.py, overview.py, mesh.py, calibration.py, batch.py
     sont absorbes dans _cli/commands/.
   - Adapter hydromodpy/_cli/commands/run.py qui dispatche vers les workflows
     (logique detect_workflow deplacee dans _cli/commands/run.py ou
     simulation/dispatch.py).

6. Mettre a jour pyproject.toml :
   - [project.scripts]
       hmp = "hydromodpy._cli:main"
       hydromodpy = "hydromodpy._cli:main"

   Verifier que pip install -e . re-expose correctement.

7. Ajouter codes d erreur etendus :
   - EXIT_OK=0
   - EXIT_CONFIG=1
   - EXIT_RUN_FAILED=2
   - EXIT_NOT_FOUND=3
   - EXIT_USER_ABORT=4
   - EXIT_DATA_ERROR=5
   - EXIT_SOLVER_ERROR=6

   Cabler dans les sous-commandes en retournant le bon code selon le type d erreur.

8. Tests :
   - tests/integration/test_cli_subcommands.py :
       Test chaque nouvelle sous-commande via subprocess (hmp --help doit
       lister doctor/inspect/best/worst/delete/completion/lock).
   - tests/integration/test_ux_acceptance.py :
       Cycle complet : hmp init -> hmp config template -> hmp run -> hmp list -> hmp inspect -> hmp export.

9. Mettre a jour CHANGELOG :
    - Added: hmp doctor / inspect / best / worst / delete / completion / --version.
    - Added: hmp config check / template subparsers.
    - Added: hmp run --until / --from / --dry-run / --no-checkpoint.
    - Added: hmp lock {update, archive, restore} (subcommands G04).
    - Breaking: hydromodpy/__main__.py replaced by hydromodpy/_cli/ package.
    - Removed: hydromodpy/runners/ (absorbed into _cli/).
    - Changed: extended exit codes (EXIT_DATA_ERROR=5, EXIT_SOLVER_ERROR=6).

COMMITS attendus (15-22 petits) :
   [G07] - scaffold cli package
   [G07] - move init command to cli
   [G07] - move run command to cli
   [G07] - add run until from flags
   [G07] - add run dry run flag
   [G07] - add run no checkpoint flag
   [G07] - move display command to cli
   [G07] - move list command to cli
   [G07] - move export command to cli
   [G07] - move calibrate command to cli
   [G07] - move schema command to cli
   [G07] - move data command to cli
   [G07] - move test command to cli
   [G07] - add config check subparser
   [G07] - add config template subparser
   [G07] - add doctor subcommand
   [G07] - add inspect subcommand
   [G07] - add best subcommand
   [G07] - add worst subcommand
   [G07] - add delete subcommand
   [G07] - add completion subcommand
   [G07] - add version flag
   [G07] - remove runners top level
   [G07] - wire pyproject scripts to cli
   [G07] - extend exit codes
   [G07] - add cli integration tests
   [G07] - add ux acceptance test
   [G07] - changelog v050 cli

CRITERES DE SUCCES :
- hydromodpy/_cli/ existe avec main.py + commands/*.
- hydromodpy/__main__.py reduit a un re-export de _cli.main OU supprime
  (les entry points pointent vers _cli:main).
- hydromodpy/runners/ supprime.
- hmp --help liste : init, new, config, run, display, list, export, show,
  compare, import, calibrate, schema, test, data, lock, doctor, inspect,
  best, worst, delete, completion.
- hmp --version imprime la version.
- pytest tests/integration/test_cli_subcommands.py + test_ux_acceptance.py passent.

SIGNALISATION : PHASE_G07_DONE
'
run_phase "G07" "CLI completion (_cli/ refactor + 8 new subcommands + pipeline flags)" "$G07_PROMPT"

# ---------- G08 : Pipeline + solver typing (typed errors, state hierarchy, merged registry, entry_points) ----------
G08_PROMPT='
OBJECTIF : finir le typage et la consolidation du pipeline + solver :
- Hierarchie PipelineError typee (StepError, CheckpointError, etc.).
- Hierarchie d etats frozen par step (ValidatedState, ResolvedState, ExecutedState).
- Step Protocol generique TIn/TOut.
- Typed solver exceptions (SolverDivergedError etc. — deja en G01, reliees).
- Fusion des deux registres solver : solver/base/registry + simulation/adapters/registry.
- Plugin entry_points hydromodpy.solver pour decouverte dynamique.

RAPPORT DE CONFORMITE — Items adresses :
- v0.5-v0.6 #15 partiel (deja en G01).
- v0.6+ #23 : fusion registres solver/base + simulation/adapters.
- v0.6+ #24 : hierarchie PipelineError + typed state + Step generic.

SPECS : 05_solver_contracts.md §4, 06_pipeline_execution.md §1.3–§1.4.

TACHES :

1. Typed state hierarchy dans hydromodpy/pipeline/state.py :
   @dataclass(frozen=True)
   class PipelineState(Generic[T]):
       run_id: str
       data: T

   @dataclass(frozen=True)
   class ValidatedState:
       config: HydroModPyConfig
       workspace: Path

   @dataclass(frozen=True)
   class ResolvedState(ValidatedState):
       data_plan: DataLoadPlan
       sim_plan: SimulationPlan

   @dataclass(frozen=True)
   class LoadedState(ResolvedState):
       loaded_context: LoadedDataContext

   @dataclass(frozen=True)
   class MeshedState(LoadedState):
       mesh_context: MeshContext

   @dataclass(frozen=True)
   class SetupState(MeshedState):
       setup_context: SetupContext

   @dataclass(frozen=True)
   class OpenStoreState(SetupState):
       sim_zarr: SimulationZarr

   @dataclass(frozen=True)
   class SolverRanState(OpenStoreState):
       solver_result: RunResult

   @dataclass(frozen=True)
   class ExtractedState(SolverRanState):
       extraction_summary: dict

   @dataclass(frozen=True)
   class DerivedState(ExtractedState):
       derived_names: list[str]

   @dataclass(frozen=True)
   class ExportedState(DerivedState):
       export_paths: list[Path]

   Adapter Pipeline pour accepter ces types au lieu de PipelineState.data: Mapping[str, Any].
   Permettre aussi un mode "generic" (PipelineState[dict[str, Any]]) pour retrocompat
   stricte (mais pas d alias).

2. Step Protocol generique dans hydromodpy/pipeline/step.py :

   from typing import Protocol, TypeVar, runtime_checkable

   TIn = TypeVar("TIn", contravariant=True)
   TOut = TypeVar("TOut", covariant=True)

   @runtime_checkable
   class Step(Protocol[TIn, TOut]):
       name: str
       def run(self, state: TIn) -> TOut: ...

   Adapter les 11 steps existants pour declarer leurs TIn/TOut :
   - Step00Validate: Step[None, ValidatedState]
   - Step01Resolve: Step[ValidatedState, ResolvedState]
   - Step02LoadData: Step[ResolvedState, LoadedState]
   - Step03Mesh: Step[LoadedState, MeshedState]
   - Step04Setup: Step[MeshedState, SetupState]
   - Step05OpenStore: Step[SetupState, OpenStoreState]
   - Step06SolverRun: Step[OpenStoreState, SolverRanState]
   - Step07Extract: Step[SolverRanState, ExtractedState]
   - Step08Validate (post) : reusable
   - Step09Derive: Step[ExtractedState, DerivedState]
   - Step10Export: Step[DerivedState, ExportedState]

3. Hierarchie PipelineError (reliee a core/exceptions.py de G01) :

   class PipelineError(HydroModPyError): pass
   class StepError(PipelineError):
       def __init__(self, step_name, cause, *, run_id=None, **ctx):
           super().__init__(f"step {step_name} failed: {cause}", run_id=run_id, **ctx)
           self.step_name = step_name
           self.cause = cause
   class CheckpointError(PipelineError): pass
   class LedgerError(PipelineError): pass
   class ResumeError(PipelineError): pass

   Dans Pipeline._execute_step : catch Exception -> relever comme StepError,
   stocker cause, step_name, run_id.
   Le except BaseException actuel a supprimer — on ne doit pas attraper
   KeyboardInterrupt silencieusement.

4. Fusion des registres solver :
   - hydromodpy/solver/base/registry.py : garder comme canonique (SolverRunner).
   - hydromodpy/simulation/adapters/registry.py : supprime ou devenu un thin wrapper
     qui appelle solver/base/registry. La logique execute(ctx) devient un helper
     qui cree le SolverRunner via solver/base et appelle setup/build/run/extract/cleanup.

5. Plugin entry_points hydromodpy.solver :
   - pyproject.toml :
     [project.entry-points."hydromodpy.solver"]
     modflow_nwt_flow = "hydromodpy.solver.modflow_nwt.flow.flow_to_modflow_adapter:ModflowNwtFlowAdapter"
     modflow6_flow   = "hydromodpy.solver.modflow6.flow_to_modflow_adapter:Modflow6FlowAdapter"
     boussinesq_flow = "hydromodpy.solver.boussinesq.flow.boussinesq_adapter:BoussinesqFlowAdapter"
   - hydromodpy/solver/base/registry.py : au startup, importer via
     importlib.metadata.entry_points et enregistrer dynamiquement.
     Eviter side-effect au module level : exposer une fonction load_plugins()
     appelee par le pipeline au demarrage.

6. Mettre a jour les tests :
   - tests/unit/solver/test_solver_protocol.py : adapter au rename (SolverRunner).
   - tests/unit/solver/test_solver_registry.py : adapter + test load_plugins.
   - tests/unit/pipeline/test_step_protocol.py : nouveau, teste TIn/TOut.
   - tests/unit/pipeline/test_pipeline_state_types.py : nouveau.
   - tests/unit/pipeline/test_pipeline_errors.py : nouveau, teste StepError etc.

7. Mettre a jour CHANGELOG :
    - Added: typed state hierarchy in pipeline (ValidatedState / ResolvedState / ...).
    - Added: Step Protocol generic TIn/TOut.
    - Added: PipelineError hierarchy (StepError / CheckpointError / LedgerError / ResumeError).
    - Added: plugin entry_points hydromodpy.solver.
    - Breaking: SolverAdapter renamed to SolverRunner (G02 reminder).
    - Breaking: merged solver/base and simulation/adapters registries into one.
    - Removed: PipelineState.data: Mapping[str, Any] as default — now typed.

COMMITS attendus (12-18 petits) :
   [G08] - add typed pipeline state hierarchy
   [G08] - wire validated state in step 00
   [G08] - wire resolved state in step 01
   [G08] - wire loaded state in step 02
   [G08] - wire meshed state in step 03
   [G08] - wire setup state in step 04
   [G08] - wire open store state in step 05
   [G08] - wire solver ran state in step 06
   [G08] - wire extracted state in step 07
   [G08] - wire derived state in step 09
   [G08] - wire exported state in step 10
   [G08] - add generic step protocol
   [G08] - add pipeline error hierarchy
   [G08] - narrow exception catching in pipeline
   [G08] - merge solver registries
   [G08] - add solver entry points
   [G08] - load plugins in solver registry
   [G08] - update solver tests for runner rename
   [G08] - add pipeline state type tests
   [G08] - add pipeline error tests
   [G08] - changelog v050 pipeline typing

CRITERES DE SUCCES :
- hydromodpy/pipeline/state.py : 10 states frozen dataclass.
- hydromodpy/pipeline/step.py : Step[TIn, TOut] generic.
- Les 11 steps declarent leur TIn/TOut.
- PipelineError + sous-classes heritent de HydroModPyError.
- Un seul registre solver (solver/base/registry.py).
- pyproject.toml [project.entry-points."hydromodpy.solver"] liste les 3 adapters.
- pytest tests/unit/pipeline/ -v  passe.
- pytest tests/unit/solver/ -v  passe.

SIGNALISATION : PHASE_G08_DONE
'
run_phase "G08" "Pipeline + solver typing (typed state, Step generic, errors, merged registry, entry_points)" "$G08_PROMPT"

# ---------- G09 : Test infrastructure (e2e, _helpers, TOLERANCES, pytest.ini, seeds) ----------
G09_PROMPT='
OBJECTIF : professionnaliser l infrastructure de tests :
- tests/e2e/ : scenarios end-to-end.
- tests/_helpers/ : renommage depuis tests/support/ + modules fixtures_mesh /
  fixtures_catalog / fixtures_config / fixtures_data / strategies / signatures /
  assertions.
- tests/TOLERANCES.md : justifications numeriques.
- tests/pytest.ini : config dediee (sorti de pyproject.toml).
- tests/unit/conftest.py : hook anti-subprocess.
- Fixture autouse _deterministic_seeds + BLAS single-thread.
- Markers supplementaires : boussinesq, network, binary, gpu.

RAPPORT DE CONFORMITE — Items adresses :
- v0.5-v0.6 #7 : tests/e2e/, tests/_helpers/, TOLERANCES.md, pytest.ini.
- Complements : hook anti-subprocess, seeds autouse, markers.

SPEC : architecture_cible/09_tests_ideaux.md.

TACHES :

1. Creer tests/e2e/ avec 3-5 scenarios end-to-end :
   - test_full_simulation_cycle.py :
       hmp init -> hmp config template -> hmp run (sur synthetic small) ->
       hmp list -> hmp inspect -> hmp export -> import back.
       Verifie que le round-trip preserve les donnees.
   - test_calibration_cycle.py :
       Calibration 2 params Optuna 3 trials -> catalog contient iterations ->
       best sim identifiable.
   - test_resume_after_interrupt.py :
       Lance pipeline, simule crash au step 05, relance avec --resume,
       verifie que le run termine sans reexecuter les steps 00-05.
   - test_display_golden.py (optionnel) :
       Genere 3 figures canoniques, compare aux goldens (tests/goldens/e2e/).
   - test_export_hmp_roundtrip.py :
       Export .hmp -> import dans workspace propre -> equality.

   Conftest : tests/e2e/conftest.py avec fixture autouse e2e_workspace
   (tmp_path isole par test, avec HydroModPyConfig minimal synthetic).

2. Renommer tests/support/ -> tests/_helpers/ :
   - git mv tests/support tests/_helpers
   - Organiser en sous-modules :
     - tests/_helpers/fixtures_mesh.py      (cartesian small, voronoi small)
     - tests/_helpers/fixtures_catalog.py    (empty catalog, populated catalog, calibration catalog)
     - tests/_helpers/fixtures_config.py     (minimal, flow_steady, flow_transient, calibration)
     - tests/_helpers/fixtures_data.py       (synthetic timeseries, synthetic DEM, synthetic catchment)
     - tests/_helpers/strategies.py           (Hypothesis strategies pour configs/fields)
     - tests/_helpers/signatures.py           (inspect fonction signatures pour enforcer APIs)
     - tests/_helpers/assertions.py           (assert_dataarray_close, assert_dataframe_equal_modulo_dtype)
   - Adapter tous les imports dans tests/*/test_*.py : from tests.support -> from tests._helpers.

3. Creer tests/TOLERANCES.md :
   Tableau des tolerances numeriques utilisees dans les tests + justifications :
   - Flow head convergence       : 1e-6 m        (MODFLOW default + 2 OoM safety).
   - Flow budget closure         : 1% relative   (IMS/PCG solver tolerance).
   - Calibration NSE vs baseline : 0.01 absolute (stochastic optimizer noise).
   - Analytical Theis            : 1% relative   (Leaky approximation).
   - MMS Laplacian convergence   : O(h^2)        (second-order FV).
   - ... etc pour 15-20 tolerances.

4. Creer tests/pytest.ini (extraire la config depuis pyproject.toml tool.pytest) :
   [pytest]
   markers =
       regression: golden regression tests
       validation: scientific benchmarks
       analytical: analytical solutions
       steady: steady flow
       transient: transient flow
       fast: < 10s
       slow: >= 10s
       nwt: MODFLOW-NWT specific
       mf6: MODFLOW 6 specific
       integration: cross-module
       coverage: run under coverage
       extensive: extensive regression tier
       petsc: requires PETSc
       boussinesq: Boussinesq solver
       network: requires network access
       binary: requires solver binary
       gpu: requires GPU
   testpaths = tests
   addopts = --strict-markers --tb=short
   ...

   Retirer la section [tool.pytest.ini_options] de pyproject.toml (migration vers
   pytest.ini est plus conforme spec 09 §3).

5. Creer tests/unit/conftest.py avec hook anti-subprocess :

   @pytest.fixture(autouse=True)
   def _no_subprocess_in_unit_tests(monkeypatch):
       """Unit tests doivent tourner sans subprocess / requests externes."""
       def _deny(*args, **kwargs):
           raise RuntimeError("subprocess forbidden in unit tests")
       import subprocess
       monkeypatch.setattr(subprocess, "run", _deny)
       monkeypatch.setattr(subprocess, "Popen", _deny)
       monkeypatch.setattr(subprocess, "check_call", _deny)
       monkeypatch.setattr(subprocess, "call", _deny)

       # Deny requests / urllib network access
       try:
           import requests
           monkeypatch.setattr(requests, "get", _deny)
           monkeypatch.setattr(requests, "post", _deny)
       except ImportError:
           pass

   Autoriser exceptions par test via un marker @pytest.mark.allow_subprocess.

6. Fixture autouse _deterministic_seeds dans tests/conftest.py (racine) :

   @pytest.fixture(autouse=True)
   def _deterministic_seeds():
       import random, numpy as np, os
       random.seed(42)
       np.random.seed(42)
       os.environ.setdefault("PYTHONHASHSEED", "42")
       yield
       # no teardown

7. BLAS single-thread dans tests/conftest.py :
   - Au module-level (avant fixtures) :
     import os
     for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
         os.environ.setdefault(v, "1")

8. Auto-tag par chemin + timeouts :
   - tests/conftest.py : dans pytest_collection_modifyitems, ajouter
     automatiquement les markers integration/regression/validation/e2e selon
     le chemin.
   - Timeouts par layer : pytest-timeout marker sur les layers (regression: 300s,
     validation: 900s, e2e: 1800s).

9. Ajouter markers manquants (boussinesq/network/binary/gpu) dans pytest.ini
   et les appliquer aux tests correspondants.

10. Mettre a jour CHANGELOG :
    - Added: tests/e2e/ with 5 end-to-end scenarios.
    - Renamed: tests/support/ -> tests/_helpers/.
    - Added: tests/TOLERANCES.md with 15+ numerical tolerances justified.
    - Added: tests/pytest.ini (migrated from pyproject.toml).
    - Added: tests/unit/conftest.py anti-subprocess guard.
    - Added: autouse _deterministic_seeds fixture + BLAS single-thread.
    - Added: markers boussinesq / network / binary / gpu.

COMMITS attendus (12-18 petits) :
   [G09] - scaffold tests e2e directory
   [G09] - add full simulation cycle e2e
   [G09] - add calibration cycle e2e
   [G09] - add resume after interrupt e2e
   [G09] - add hmp package roundtrip e2e
   [G09] - rename tests support to helpers
   [G09] - split fixtures into topic modules
   [G09] - add hypothesis strategies helper
   [G09] - add signatures helper
   [G09] - add assertions helper
   [G09] - add tolerances documentation
   [G09] - migrate pytest config to pytest ini
   [G09] - add anti subprocess hook in unit
   [G09] - add deterministic seeds autouse
   [G09] - set blas single thread in conftest
   [G09] - add auto tag by path
   [G09] - add per layer timeouts
   [G09] - add boussinesq network binary gpu markers
   [G09] - update tests imports for helpers rename
   [G09] - changelog v050 test infra

CRITERES DE SUCCES :
- tests/e2e/ contient au moins 4 tests passants.
- tests/_helpers/ remplace tests/support/ (import tests.support erreur).
- tests/TOLERANCES.md >= 50 lignes.
- tests/pytest.ini existe + [tool.pytest.ini_options] retire de pyproject.toml.
- tests/unit/conftest.py a le hook anti-subprocess.
- tests/conftest.py a _deterministic_seeds autouse.
- pytest tests/ -q  passe (tous tiers).

SIGNALISATION : PHASE_G09_DONE
'
run_phase "G09" "Test infrastructure (e2e, _helpers, TOLERANCES, pytest.ini, guardrails)" "$G09_PROMPT"

# ---------- G10 : Analytical benchmarks + MMS ----------
G10_PROMPT='
OBJECTIF : ajouter les benchmarks scientifiques :
- Theis (transient confined)
- Hantush (transient leaky)
- Ogata-Banks (1D advection-diffusion transport)
- MMS (Method of Manufactured Solutions) : Laplacien 1D + diffusion transitoire

RAPPORT DE CONFORMITE — Items adresses :
- v0.5-v0.6 #8 : benchmarks analytiques + MMS.

SPEC : architecture_cible/09_tests_ideaux.md §5.

TACHES :

1. Theis benchmark :
   - tests/validation/analytical/transient/test_theis.py
   - Solution analytique : s(r, t) = Q/(4*pi*T) * W(u), u = r^2*S/(4*T*t)
   - Well function W(u) via scipy.special.exp1.
   - Setup : nappe captive homogene 2D, puits central pompe Q = 100 m^3/day,
     T = 100 m^2/day, S = 1e-4, duration = 10 days.
   - Modeliser avec MODFLOW 6 + IMS, comparer h(r, t) a la solution analytique
     a r = 10, 50, 100 m et t = 1, 3, 10 days.
   - Tolerance : 1% relative (justifie dans TOLERANCES.md).
   - Marker : @pytest.mark.validation @pytest.mark.analytical @pytest.mark.transient.

2. Hantush benchmark :
   - tests/validation/analytical/transient/test_hantush.py
   - Solution analytique : s(r, t) = Q/(4*pi*T) * W(u, r/B), B = sqrt(T*b /K_aquitard)
   - Well function W(u, r/B) via scipy integration ou scipy.special approximations.
   - Setup : aquifere semi-captif + aquitard + recharge constante au-dessus.
   - Comparer head au puits et a 2-3 distances radiales.
   - Tolerance : 2% relative.

3. Ogata-Banks benchmark :
   - tests/validation/analytical/transient/test_ogata_banks.py
   - Solution 1D advection-diffusion :
     c(x, t) = c0/2 * (erfc((x - v*t)/(2*sqrt(D*t))) + exp(v*x/D) * erfc((x + v*t)/(2*sqrt(D*t))))
   - Setup : colonne 1D, c0 injection a x=0, v = 0.1 m/day, D = 0.01 m^2/day.
   - Modeliser avec MT3DMS ou equivalent transport solver (si disponible).
   - Tolerance : 3% relative.
   - Si le solver transport n est pas disponible dans l env test, skip avec
     raison claire (marker @pytest.mark.transport).

4. MMS Laplacien 1D :
   - tests/validation/mms/test_mms_laplacian_1d.py
   - Solution manufacturee : h(x) = sin(pi*x) sur [0, 1] avec Dirichlet 0/0 et
     source term f(x) = pi^2 * sin(pi*x).
   - Modeliser avec FV1D steady, maillage raffine (N = 10, 20, 40, 80).
   - Verifier convergence L2 : ||h_num - h_exact||_2 = O(h^2).
   - Estimer l ordre de convergence empirique par regression log-log ;
     attendu entre 1.8 et 2.2.
   - Tolerance : |ordre - 2| < 0.2.

5. MMS diffusion transitoire 1D :
   - tests/validation/mms/test_mms_diffusion_transient.py
   - Solution : h(x, t) = exp(-pi^2 * D * t) * sin(pi*x).
   - Source term : f(x, t) = 0 (solution exacte de l edp homogene).
   - Condition initiale : h(x, 0) = sin(pi*x).
   - Dirichlet 0/0.
   - Verifier convergence en espace (h fixe en temps a t = 0.1) : ordre 2.
   - Verifier convergence en temps (h fixe en espace) : ordre 1 (Euler implicite).

6. Creer tests/validation/mms/conftest.py avec helpers :
   - run_mms_convergence(case_fn, Ns, metric) -> ordre, errors.
   - Adaptable aux 2D si besoin.

7. Documenter dans tests/TOLERANCES.md :
   - Theis : 1% relative justification.
   - Hantush : 2% relative.
   - Ogata-Banks : 3% relative.
   - MMS Laplacien : |ordre - 2| < 0.2.
   - MMS diffusion transient espace : |ordre - 2| < 0.2.
   - MMS diffusion transient temps : |ordre - 1| < 0.2.

8. Mettre a jour CHANGELOG :
    - Added: Theis analytical benchmark (transient confined aquifer).
    - Added: Hantush analytical benchmark (transient leaky aquifer).
    - Added: Ogata-Banks analytical benchmark (1D advection-diffusion).
    - Added: MMS Laplacian 1D convergence test (order 2).
    - Added: MMS diffusion transient 1D convergence test (order 2 space, order 1 time).

COMMITS attendus (6-9 petits) :
   [G10] - add theis analytical benchmark
   [G10] - add hantush analytical benchmark
   [G10] - add ogata banks benchmark
   [G10] - add mms laplacian 1d benchmark
   [G10] - add mms diffusion transient benchmark
   [G10] - add mms convergence helpers
   [G10] - document analytical tolerances
   [G10] - changelog v050 benchmarks

CRITERES DE SUCCES :
- tests/validation/analytical/transient/ contient test_theis.py,
  test_hantush.py, test_ogata_banks.py.
- tests/validation/mms/ existe avec test_mms_laplacian_1d.py et
  test_mms_diffusion_transient.py + conftest.py.
- pytest tests/validation/analytical/transient/test_theis.py -v  passe (sous
  solver dispo) ou skipe proprement.
- pytest tests/validation/mms/ -v  passe.
- tests/TOLERANCES.md liste ces 5 benchmarks.

SIGNALISATION : PHASE_G10_DONE
'
run_phase "G10" "Analytical benchmarks (Theis, Hantush, Ogata-Banks) + MMS (Laplacian, diffusion)" "$G10_PROMPT"

# ---------- G11 : VERIFY FINAL — Conformance report v0.5 + Test triage report ----------
G11_PROMPT='
OBJECTIF : finalisation et livrables :
- Rapport de conformite v0.5 (docs/developers/architecture_conformance_report_v050.md)
  qui remplace l ancien v0.4 et atteste que toutes les dettes G01-G10 sont
  closes ou documentees.
- Rapport de triage des tests (docs/developers/test_status_report.md)
  qui explique POURQUOI chaque test failed / skipped / xfail et COMMENT le
  reparer.
- Pytest complet final.
- Commit "mark migration complete v050".

RAPPORT DE CONFORMITE BASELINE : docs/developers/architecture_conformance_report.md.

TACHES :

=== PARTIE 1 : Rapport de conformite v0.5 ===

1. Creer docs/developers/architecture_conformance_report_v050.md :

   # Rapport de conformite architecture — HydroModPy v0.5

   **Date :** <aujourd hui>
   **Branche :** dev-refact_v2 au commit <HEAD-short>
   **Base :**
     - run_migration.sh (P01-P13, livre v0.4)
     - run_finalization.sh (F01-F08, rapport audit v0.4)
     - run_completion.sh (G01-G11, finalisation v0.5)

   ## Executive summary

   | Spec | OK | Ecart | Manquant | Verdict global |
   ...

   (14 lignes + TOTAL).

   Pour chaque spec, refaire un scan comme dans le rapport precedent mais en
   partant du CODE REEL apres G01-G10, PAS d une paraphrase.

2. Methodologie :
   - Pour chaque spec (Agent Explore paralleles OK), extraire 15-30 checkpoints.
   - Verifier chaque checkpoint par Read/Grep/Bash.
   - Les items listes dans v0.5 (priorite haute) doivent etre OK (ou Ecart
     assume) : G01-G10 les ont adresses.
   - Les items en v0.5-v0.6 (priorite moyenne) : doivent etre OK egalement.
   - Les items en v0.6+ (priorite basse) : doivent etre OK pour la plupart
     apres G07+G08, sauf tres rares exceptions documentees.
   - Les decisions actees (NWT/MF6 separes, HYDROMODPY_NO_* purges) restent
     des ecarts assumes, PAS des manquants.

3. Sections Ecarts globaux assumes (decisions architecture) :
   - NWT/MF6 separes (F02).
   - HYDROMODPY_NO_DISPLAY/NO_SAVE purges (F04).
   - Layout calibration/ plat (vs sous-packages detailles spec 07).
   - Autres decisions editoriales justifiees.

4. Section Manquants residuels (a traiter post-v0.5) :
   - Tout ce qui n a pas pu etre implemente doit etre liste avec ticket
     de suivi v0.6-<slug>.
   - Idealement vide ou quasi vide.

5. Conclusion : MIGRATION TERMINEE (v0.5) ou PARTIELLE avec liste des
   manquants persistants.

=== PARTIE 2 : Rapport de triage des tests ===

6. Lancer une passe pytest complete, exhaustive, avec sortie detaillee :

   pytest tests/ -v --tb=long --no-header -rN --capture=no 2>&1 | tee /tmp/pytest_full.log

   Options explainees :
   - -v              : verbeux (un test par ligne).
   - --tb=long       : traceback long pour les failures.
   - --no-header     : pas de banner pytest.
   - -rN             : aucun summary special (on parse nous-meme).
   - --capture=no    : ne pas capturer stdout (pour voir prints eventuels).

7. Extraire tous les tests ayant un statut non-PASSED :
   - FAILED        : le test a echoue.
   - SKIPPED       : saute pour une raison.
   - XFAIL         : attendu comme fail, bien fail.
   - XPASS         : attendu comme fail, a reussi (probleme de marker).
   - ERROR         : erreur avant / pendant execution (collection / fixture).

   Pour chaque test, collecter :
   - Path du test (tests/xxx/test_yyy.py::test_zzz)
   - Statut
   - Raison (skip reason, xfail reason, ou extract du traceback).
   - Classification de la cause (voir step 8).

8. Creer docs/developers/test_status_report.md avec la structure suivante :

   # Rapport de statut des tests — HydroModPy v0.5

   **Date :** <aujourd hui>
   **Branche :** dev-refact_v2 au commit <HEAD-short>
   **Total tests :** passed=<N>, skipped=<N>, xfail=<N>, xpass=<N>, failed=<N>, error=<N>.

   ## Resume executif

   | Statut   | Nombre | % |
   |----------|--------|---|
   | PASSED   | ...    |...|
   | SKIPPED  | ...    |...|
   | XFAIL    | ...    |...|
   | XPASS    | ...    |...|
   | FAILED   | ...    |...|
   | ERROR    | ...    |...|

   ## Groupe 1 — Tests FAILED

   Pour chaque test failed :
   ### `tests/unit/foo/test_bar.py::test_baz`
   - **Statut :** FAILED
   - **Cause :** (un des types ci-dessous)
       * API non implementee  (Fix: implementer X dans module Y)
       * Contrat evolue       (Fix: adapter le test a la nouvelle API)
       * Dependance manquante (Fix: installer / skip selon env)
       * Bug identifie        (Fix: corriger la fonction X)
       * Non-determinisme     (Fix: fixer seed / mock)
   - **Stack trace (extrait) :**
     ```
     E       assert actual == expected
     E       <diff>
     ```
   - **Fix recette :**
     1. Ouvrir <fichier>:<ligne>.
     2. <operation concrete>.
     3. Verifier via pytest <test_path> -v.

   ## Groupe 2 — Tests SKIPPED

   Pour chaque test skipped :
   ### `tests/xxx/test_yyy.py::test_zzz`
   - **Statut :** SKIPPED
   - **Raison (du marker) :** <str>
   - **Classification :**
       * Env manquant         (ex: PETSc non installe, solver binary absent)
       * Donnees reseau       (ex: test reseau non desire dans CI)
       * Feature post-v0.5    (ex: hmp lock archive pas encore implemente)
       * Plateforme specific  (ex: Windows-only, Linux-only)
   - **Fix recette :**
     - Si env manquant : comment configurer l env (apt install, etc.).
     - Si feature manquante : renvoyer au ticket de suivi.
     - Si plateforme : rien a faire (conforme).

   ## Groupe 3 — Tests XFAIL

   Pour chaque xfail :
   ### `tests/xxx/test_yyy.py::test_zzz`
   - **Statut :** XFAIL
   - **Raison (du marker) :** <str>
   - **Classification :**
       * Spec non implementee (v0.6+)
       * Bug solver externe   (ex: MF6 issue #xxx)
       * Incompatibilite numpy/scipy version
   - **Fix recette :**
     <etapes pour implementer la feature OU patcher le solver externe>.

   ## Groupe 4 — Tests XPASS

   Pour chaque xpass (probleme : le marker xfail doit etre retire) :
   ### `...`
   - **Fix recette :** retirer @pytest.mark.xfail sur <fichier>:<ligne>.

   ## Groupe 5 — Tests ERROR

   Pour chaque erreur pendant collection / fixture :
   ### `...`
   - **Statut :** ERROR
   - **Cause :** (erreur d import, fixture manquante, conflit de marker).
   - **Fix recette :**
     <commande ou edition a faire>.

   ## Synthese et priorisation

   - Critical (a reparer avant v0.5 release) : <liste des failed bloquants>.
   - Important (a reparer en v0.5.x patch) : <liste des xfail critiques>.
   - Nice to have : <xpass, skips mineurs>.

   ---

9. Parse approche suggeree (en Bash ou Python) :

   # En Python :
   import re, sys
   log = open("/tmp/pytest_full.log").read()
   for line in log.splitlines():
       # "FAILED tests/unit/foo/test_bar.py::test_baz - <msg>"
       # "SKIPPED [1] tests/... reason"
       # "XFAIL tests/... reason"
       ...

   Ou utiliser pytest --json-report :
   pip install pytest-json-report
   pytest tests/ --json-report --json-report-file=/tmp/pytest.json
   python -c "import json; d = json.load(open(\"/tmp/pytest.json\")); ..."

   Choisir la methode qui permet d extraire proprement tous les cas.

10. Pour chaque test non-PASSED, Claude DOIT :
    - Lire le code du test (Read).
    - Lire le marker xfail/skip (raison).
    - Lire le code cible teste (Read).
    - Deduire la cause ET proposer un fix recette concret.
    - Ecrire la section correspondante dans test_status_report.md.

11. Ne PAS auto-fixer les tests (sauf xpass evident) : le rapport est la
    DOCUMENTATION des dettes restantes. Si tu peux reparer facilement,
    tu peux — sinon tu documentes.

=== PARTIE 3 : Finalisation ===

12. Lancer une passe pytest une fois le rapport ecrit :
    pytest tests/unit/ -q --tb=short  : doit passer (hors xfail).
    pytest tests/integration/ -q      : doit passer.
    pytest tests/regression/fast/ -q  : doit passer.

13. hmp --help doit lister toutes les sous-commandes (init, new, config,
    run, display, list, export, show, compare, import, calibrate, schema,
    test, data, lock, doctor, inspect, best, worst, delete, completion,
    --version).

14. Verifier qu aucune regression n a ete introduite :
    - grep -rln "HYDROMODPY_NO_DISPLAY\\|HYDROMODPY_NO_SAVE" \\
        --include="*.py" --include="*.yml" hydromodpy/ tests/ \\
        validation_cases/ .github/  : ne doit rien retourner.
    - Les deux flow_to_modflow_adapter.py (NWT + MF6) existent toujours
      et ont l en-tete F02.
    - grep -ri "inrae" hydromodpy/ : 0 occurrence.

15. Update CHANGELOG.md :
    - Deplacer [v0.5.0-dev] / [Unreleased] vers [0.5.0] - <today>.
    - Ajouter section Migration Guide v0.4 -> v0.5.
    - Liste exhaustive des breaking changes introduits par G01-G10.

16. Commit final :
    - [G11] - add conformance report v050
    - [G11] - add test status report
    - [G11] - changelog release v050
    - [G11] - mark completion done v050

COMMITS attendus (12-18 petits) :
   [G11] - scaffold conformance report v050
   [G11] - verify spec 01 structure packages
   [G11] - verify spec 02 config pydantic
   [G11] - verify spec 03 data contracts
   [G11] - verify spec 04 storage ideal
   [G11] - verify spec 05 solver contracts
   [G11] - verify spec 06 pipeline execution
   [G11] - verify spec 07 calibration
   [G11] - verify spec 08 postprocess display
   [G11] - verify spec 09 tests ideaux
   [G11] - verify spec 10 ux cli api
   [G11] - verify spec 11 frontend ready
   [G11] - verify spec 12 input data rethink
   [G11] - verify spec 13 coherence globale
   [G11] - verify spec 14 plan migration
   [G11] - summarize conformance report v050
   [G11] - scaffold test status report
   [G11] - triage failed tests
   [G11] - triage skipped tests
   [G11] - triage xfail tests
   [G11] - summarize test status report
   [G11] - changelog release v050
   [G11] - mark completion done v050

CRITERES DE SUCCES :
- docs/developers/architecture_conformance_report_v050.md existe, bien
  structure, avec tableau + details par spec + conclusion.
- docs/developers/test_status_report.md existe avec 5 groupes
  (FAILED/SKIPPED/XFAIL/XPASS/ERROR), chacun avec cause + fix recette.
- pytest tests/unit/ -q  passe (quelques xfail tolerables, documentes).
- pytest tests/integration/ -q  passe.
- pytest tests/regression/fast/ -q  passe.
- grep HYDROMODPY_NO_DISPLAY / NO_SAVE dans le codebase : 0 match.
- Les deux flow_to_modflow_adapter.py NWT/MF6 toujours distincts.
- CHANGELOG.md a section [0.5.0] - <date> + Migration Guide.
- Commit final "[G11] - mark completion done v050".

SIGNALISATION : PHASE_G11_DONE
'
run_phase "G11" "VERIFY FINAL — conformance report v0.5 + test triage report" "$G11_PROMPT"

# ===============================================================
# OUTER LOOP — reprend toute phase encore pendante jusqu a completion
# ===============================================================
outer_iteration=0
while true; do
    outer_iteration=$((outer_iteration + 1))

    if all_phases_done; then
        log ""
        log "================================================================"
        log "  ALL PHASES DONE (after $outer_iteration outer iteration(s))"
        log "================================================================"
        break
    fi

    if [[ -n "$SINGLE_PHASE" ]]; then
        # Single-phase mode : n itere pas en boucle
        log "Single-phase mode: stopping after one pass."
        break
    fi

    log ""
    log "OUTER ITERATION $outer_iteration — some phases still pending. Relancing."
    log "Pending phases:"
    for phase in "${ALL_PHASES[@]}"; do
        phase_done "$phase" || log "  - $phase"
    done

    sleep "$OUTER_LOOP_SLEEP"

    # Relancer TOUTES les phases pendantes (le skip .done les ignore)
    for phase in "${ALL_PHASES[@]}"; do
        if ! phase_done "$phase"; then
            case "$phase" in
                G01) run_phase "G01" "Core foundations (exceptions, io, logging, version, py.typed)" "$G01_PROMPT" ;;
                G02) run_phase "G02" "Canonical renames" "$G02_PROMPT" ;;
                G03) run_phase "G03" "Config refactor" "$G03_PROMPT" ;;
                G04) run_phase "G04" "Data modernization" "$G04_PROMPT" ;;
                G05) run_phase "G05" "Storage upgrades" "$G05_PROMPT" ;;
                G06) run_phase "G06" "Display infrastructure + extended figures" "$G06_PROMPT" ;;
                G07) run_phase "G07" "CLI completion" "$G07_PROMPT" ;;
                G08) run_phase "G08" "Pipeline + solver typing" "$G08_PROMPT" ;;
                G09) run_phase "G09" "Test infrastructure" "$G09_PROMPT" ;;
                G10) run_phase "G10" "Analytical benchmarks + MMS" "$G10_PROMPT" ;;
                G11) run_phase "G11" "VERIFY FINAL" "$G11_PROMPT" ;;
            esac
        fi
    done
done

# ===============================================================
# RECAP FINAL
# ===============================================================
log ""
log "================================================================"
log "  COMPLETION TERMINEE"
log "  End      : $(date '+%Y-%m-%d %H:%M:%S')"
log "  Branch   : $(git -C "$PROJECT" rev-parse --abbrev-ref HEAD)"
log "  HEAD     : $(git -C "$PROJECT" rev-parse --short HEAD)"
log "  Conform. : $FINAL_REPORT"
log "  Tests    : $TEST_REPORT"
log "================================================================"
show_status
notify "Completion v0.5 done"
