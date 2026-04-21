#!/usr/bin/env bash
#
# run_finalization.sh — Finalisation de la migration HydroModPy (dettes restantes apres run_migration.sh)
#
# Contexte :
#   run_migration.sh a termine les 13 phases P01-P13 le 2026-04-20.
#   Audit de conformite : docs/developers/migration_report_dev_refact_v2.md
#   Dettes restantes ciblees par 8 phases F01-F08 ci-dessous.
#
# Usage:
#   tmux new-session -s finalization './run_finalization.sh'   # lance depuis le debut
#   ./run_finalization.sh --status                             # affiche l'etat
#   ./run_finalization.sh --phase F03                          # relance phase specifique
#   ./run_finalization.sh --resume                             # equivalent au defaut
#   ./run_finalization.sh --reset                              # DANGEREUX: efface l'etat
#
# Gestion automatique identique a run_migration.sh :
#   - Rate limits Claude (attente jusqu'au reset, max 6h)
#   - Reprise apres crash / deconnexion (etat persistent)
#   - Commits petits et frequents (format "[Fxx] - <few english words>")
#   - ZERO push, ZERO changement de branche, ZERO Co-Authored-By
#
set -euo pipefail

# ===============================================================
# CONFIGURATION
# ===============================================================
PROJECT="/home/bb/Documents/01_Git_Repository/02-HydroModPy-dev"
SPECS="$PROJECT/architecture_cible"
AUDIT="$PROJECT/audit_code"
REPORT="$PROJECT/docs/developers/migration_report_dev_refact_v2.md"
STATE_DIR="$PROJECT/migration_final"
PHASES_DIR="$STATE_DIR/phases"
LOG="$STATE_DIR/finalization.log"
STDOUT_TMP="$STATE_DIR/.stdout_last"
STDERR_TMP="$STATE_DIR/.stderr_last"
MAX_RETRIES=15
MAX_WAIT=21600          # 6h max wait (plan limit reset)
BRANCH_AT_START=""
INITIAL_COMMIT=""

ALL_PHASES=(F01 F02 F03 F04 F05 F06 F07 F08)

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
    notify-send "HydroModPy Finalization" "$*" 2>/dev/null || true
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
        log "FATAL: refuse to run finalization on $BRANCH_AT_START branch"
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
        notify "ABORT: branch changed during finalization"
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
    if [[ ! -s "$REPORT" ]]; then
        log "MISSING AUDIT REPORT: $REPORT"
        missing=$((missing + 1))
    fi
    for p in P01 P02 P03 P04 P05 P06 P07 P08 P09 P10 P11 P12 P13; do
        if [[ ! -f "$PROJECT/migration/phases/$p.done" ]]; then
            log "MISSING PREREQ: migration/phases/$p.done — run_migration.sh did not complete"
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
  CONTEXTE — Finalisation de la migration HydroModPy
===============================================================

La migration principale (P01-P13, orchestree par run_migration.sh) est
TERMINEE. Le codebase est sur la branche dev-refact_v2 et passe la suite
de tests unit (1837 passed, 8 skipped, 17 xfail).

Ce second script (run_finalization.sh) cible les dettes residuelles
identifiees par l'audit de conformite :

    docs/developers/migration_report_dev_refact_v2.md

LIS CE RAPPORT EN PREMIER quand tu attaques une phase Fxx : la section
correspondante ("P03 — PARTIEL", "P06 — PARTIEL", etc.) precise
exactement quelle dette tu dois adresser.

===============================================================
  REGLES STRICTES — A NE JAMAIS TRANSGRESSER
===============================================================

AUTORISATIONS COMPLETES sur cette branche :
- Tu peux CREER, MODIFIER, DEPLACER, RENOMMER, SUPPRIMER des fichiers.
- Tu peux SUPPRIMER des dossiers entiers (coquilles vides analysis/display/,
  analysis/postprocess/, etc.).
- Tu peux REECRIRE FROM SCRATCH des fichiers existants si necessaire.
- Tu peux utiliser le Agent tool (subagent_type: general-purpose ou Explore)
  pour paralleliser la recherche et l'analyse de code large.
- Tu peux EDITER les fichiers .github/workflows/*.yml (la phase F04 requiert
  de purger HYDROMODPY_NO_DISPLAY/NO_SAVE des CI).

INTERDICTIONS ABSOLUES (JAMAIS, SOUS AUCUN PRETEXTE) :
- NEVER run 'git push' — interdit formellement (meme --dry-run).
- NEVER run 'git checkout <other-branch>' ni 'git switch' vers une autre branche.
- NEVER run 'git push --force' ni aucune variante.
- NEVER use '--no-verify', '--no-gpg-sign', ou tout flag qui bypass les hooks.
- NEVER add 'Co-Authored-By' / 'Claude' / 'Anthropic' dans les messages de commit.
- NEVER amend commits (toujours creer de NOUVEAUX commits).
- NEVER run 'git rebase', 'git reset --hard' sauf si explicitement demande par la phase.
- NEVER delete .git/, .github/ (entier), pyproject.toml, setup.cfg sauf instruction explicite.
- NEVER modifier run_migration.sh ni run_finalization.sh (ces deux scripts sont immuables).
- NEVER ajouter de code de retrocompatibilite ni DeprecationWarning : cette migration
  est un bump majeur (v0.3 -> v0.4). Les renommages sont NETS (pas d'alias).
- NEVER parler d'"INRAE" dans le code, docstrings, docs, messages utilisateur :
  la donnee SIM2 est **Meteo-France** (SAFRAN-ISBA reanalyse surface). INRAE
  est uniquement un distributeur (geosas.fr). Dans les commentaires techniques
  proches de l'URL, on peut mentionner "distributed via geosas.fr" sans nommer
  INRAE.

COMMITS — Format OBLIGATOIRE :
- Message EXACT : '[Fxx] - <3 to 7 words in English>'
- Exemples VALIDES :
    [F01] - migrate flow config to pint
    [F03] - implement derived registry
    [F04] - remove headless env vars
    [F07] - rename sim2 inrae to meteofrance
- Exemples INVALIDES (JAMAIS faire) :
    Migration of flow config to pint annotations                (trop long)
    [F01] - refactor                                            (trop vague)
    Multi-line message with description in body                 (corps interdit)
    Any line containing "Co-Authored-By" or "Claude"            (banni)
- PETITS COMMITS : 1 operation logique = 1 commit.
  Commit tot et souvent. Ne JAMAIS batcher 30 modifications en un seul gros commit.
- Apres CHAQUE commit, verifier avec :
    git log -1 --format="%s%n%b"
  pour s'assurer qu'il n'y a PAS de "Co-Authored-By" ni "Claude" ni "Anthropic".

STRATEGIE DE TRAVAIL :
1. Lire la section correspondante du rapport d'audit :
     docs/developers/migration_report_dev_refact_v2.md
2. Lire la spec cible concernee : architecture_cible/<fichier>.md
3. Lire le code EXISTANT avant de modifier (ne jamais detruire a l'aveugle).
4. Utiliser Agent/Task pour la recherche large (subagent_type: Explore).
5. Decouper en PETITS commits atomiques (1 intention = 1 commit).
6. Lancer les tests unitaires apres chaque commit substantiel :
     pytest tests/unit/ -q --tb=short -x --maxfail=3
7. Si un test casse legitimement (code obsolete) : le desactiver avec un
   commit dedie et un marker pytest.skip avec raison, ne pas juste le supprimer
   sans justification.
8. Relire tes propres diffs avant de commit :
     git diff --staged
   pour confirmer que le scope correspond au message.

IDEMPOTENCE :
- La phase peut etre relancee apres crash. Verifier TOUJOURS l'etat courant
  avant d'agir. Une operation deja faite ne doit PAS etre refaite ni causer
  d'erreur.

CONTEXTE PROJET :
- HydroModPy v0.3.5 -> v0.4 (bump majeur, breaking changes actes).
- Branche : dev-refact_v2 (ne JAMAIS en changer).
- Python : 3.11-3.13. Venv uv a la racine : .venv/
- CLI : hmp (entry : hydromodpy/__main__.py), hydromodpy (alias).
- Tests : pytest tests/unit -q  doit passer a la fin de chaque phase.

ENVIRONNEMENT D EXECUTION :
- Le PATH est deja configure avec .venv/bin en prefixe : `pytest`, `python`,
  `hmp` sont directement disponibles. NE PAS chercher pytest avec `find /`
  (scan systeme = plusieurs heures, STRICTEMENT INTERDIT).
- Pour installer une nouvelle dependance : editer pyproject.toml puis
  `uv sync` (pas `pip install` directement).

SIGNALISATION DE FIN :
Quand la phase est COMPLETEMENT terminee (tous les commits passes, tous les
tests utiles pour cette phase passent), imprimer EXACTEMENT cette ligne sur
la DERNIERE ligne de ta sortie :

    PHASE_Fxx_DONE

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
- S'il reste des changements non commites, faire un dernier petit commit :
    [$name] - final cleanup
- Verifier avec 'git log -20 --oneline' qu'aucun commit de cette phase
  ne contient 'Co-Authored-By', 'Claude', ou 'Anthropic'.
- Verifier qu'on est toujours sur la meme branche qu'au demarrage (ne JAMAIS
  faire git checkout vers une autre branche).
- Lancer une derniere fois : pytest tests/unit/ -q  (tolerance sur xfail connus).
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

        # Garde-fou : la branche n'a pas change
        verify_safe_state

        # Succes : la sortie se termine par PHASE_Fxx_DONE
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

        # Echec — analyser l'erreur
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

    log "ABANDON $name after $MAX_RETRIES attempts"
    notify "FAILED: $name abandoned"
    return 1
}

# ===============================================================
# CLI — --status / --reset / --phase / --resume
# ===============================================================
show_status() {
    echo ""
    echo "=== Finalization HydroModPy — status ==="
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
    read -r -p "ERASE all finalization state? (type 'YES'): " confirm
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
        SINGLE_PHASE="${2:?Missing phase name, e.g. --phase F03}"
        ;;
    --resume|"")
        :
        ;;
    -h|--help)
        sed -n '1,20p' "$0" | sed 's/^# \?//'
        exit 0
        ;;
    *)
        echo "Unknown arg: $1"
        echo "Usage: $0 [--status|--phase Fxx|--resume|--reset|--help]"
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
log "  FINALIZATION HYDROMODPY"
log "  Branch : $BRANCH_AT_START"
log "  HEAD   : $INITIAL_COMMIT"
log "  Start  : $(date '+%Y-%m-%d %H:%M:%S')"
log "  Specs  : $SPECS"
log "  Audit  : $REPORT"
if [[ -n "$SINGLE_PHASE" ]]; then
    log "  MODE   : single phase = $SINGLE_PHASE"
else
    log "  MODE   : resume-all (skip already done)"
fi
log "================================================================"

# ===============================================================
# PHASES
# ===============================================================

# ---------- F01 : Complete Pydantic/pint migration ----------
F01_PROMPT='
OBJECTIF : finaliser la migration Pydantic + pydantic-pint pour les configs
de flow (residual P03 du rapport d audit).

CONTEXTE (lire avant d agir) :
- docs/developers/migration_report_dev_refact_v2.md section "P03 — PARTIEL"
- architecture_cible/02_config_pydantic.md (notamment §12 "types annotes")
- hydromodpy/core/units/types.py et registry.py : deja en place depuis P03.
- hydromodpy/process/flow/physical_properties.py : deja migre en P03 (reference).

ETAT ACTUEL :
- Seul FlowPhysicalProperties utilise les types pint annotes.
- flow_config.py, boundary_conditions_config.py, initial_conditions_config.py
  utilisent encore les helpers legacy normalize_* / parse_to_m.
- 2 tests xfail a resoudre :
    tests/unit/config/test_units_roundtrip.py::test_bare_number_falls_back_to_canonical_unit
    tests/unit/config/test_units_roundtrip.py::test_flow_physical_properties_defaults_and_overrides

TACHES :

1. Auditer les configs sectionnelles de flow (Agent Explore) :
   - hydromodpy/process/flow/flow_config.py
   - hydromodpy/process/flow/boundary_conditions_config.py
   - hydromodpy/process/flow/initial_conditions_config.py
   Noter les champs avec unites (Length, TimeS, FlowRate, etc.) encore en float.

2. Migrer flow_config.py :
   - Remplacer les float nus + field_validator(normalize_length_unit/parse_to_m)
     par les types pint annotes appropries (Length, FlowRate, etc.).
   - Preserver la retrocompat TOML : "50" (sans unite, fallback m) ET "50 m"
     doivent fonctionner (c est l objectif du test xfail
     test_bare_number_falls_back_to_canonical_unit).
   - Si le comportement "bare number fallback" n est pas natif a pydantic-pint,
     creer un validator AnnotatedType custom dans hydromodpy/core/units/types.py
     qui fait : if isinstance(v, (int, float)): v = f"{v} <canonical_unit>".

3. Migrer boundary_conditions_config.py : meme approche.

4. Migrer initial_conditions_config.py : meme approche.

5. Resoudre xfail test_flow_physical_properties_defaults_and_overrides :
   - Les defaults de FlowPhysicalProperties doivent renvoyer des pint.Quantity
     (pas des strings). Verifier que model_dump / defaults passent bien par
     la conversion pint.
   - Retirer le marker xfail une fois passant.

6. Resoudre xfail test_bare_number_falls_back_to_canonical_unit :
   - Implementer le fallback bare-number dans le validator custom (tache 2).
   - Retirer le marker xfail une fois passant.

7. Ne PAS toucher aux autres configs (transport, calibration, etc.) —
   hors scope F01.

8. Verifier : pytest tests/unit/config/ -v  (tous les tests doivent passer
   ou rester xfail sur des points non listes ici).

COMMITS attendus (8-12 petits) :
   [F01] - add bare number fallback validator
   [F01] - migrate flow config to pint
   [F01] - migrate boundary conditions to pint
   [F01] - migrate initial conditions to pint
   [F01] - fix flow physical properties defaults
   [F01] - resolve pint xfail tests
   [F01] - remove legacy normalize helpers

CRITERES DE SUCCES :
- pytest tests/unit/config/ -v  : 0 xfail sur les 2 tests cibles (ils passent).
- pytest tests/unit/ -q  : pas de regression globale.
- flow_config.py n importe plus normalize_length_unit / parse_to_m.

SIGNALISATION : PHASE_F01_DONE
'
run_phase "F01" "Complete Pydantic/pint migration (flow configs)" "$F01_PROMPT"

# ---------- F02 : Document intentional NWT/MF6 duplication ----------
F02_PROMPT='
OBJECTIF : acter officiellement la decision de NE PAS mutualiser NWT et MF6
(residual P06 du rapport d audit).

DECISION UTILISATEUR (actee) :
- MODFLOW-NWT sera supprime dans une release future (post-lake-module).
- Investir dans la mutualisation NWT/MF6 serait du gachis.
- flow_to_modflow_adapter.py reste duplique entre NWT et MF6. Point.

TACHES :

1. Ajouter un header explicatif en tete de ces deux fichiers :
   - hydromodpy/solver/modflow_nwt/flow/flow_to_modflow_adapter.py
   - hydromodpy/solver/modflow6/flow/flow_to_modflow_adapter.py
   Forme suggeree (une ligne commentaire, pas docstring multi-ligne) :

   # Intentional duplication with the other MODFLOW flavour: NWT is scheduled
   # for removal after the lake-module integration lands in MF6 — not worth
   # factoring out. See docs/developers/nwt_sunset_plan.md.

2. Creer docs/developers/nwt_sunset_plan.md (court, 30-60 lignes) :
   - Contexte : decision de ne pas mutualiser NWT/MF6.
   - Raisons : MF6 a une integration propre du package Lake (LAK), NWT ne l a
     qu en DIY. Retirer NWT libere ~1400 lignes de flow_to_modflow_adapter
     plus la branche entiere hydromodpy/solver/modflow_nwt/.
   - Timeline : le retrait se fera apres integration du module Lake (post-v0.4).
   - Impact utilisateur : les workflows NWT restent supportes jusqu a la v0.4
     inclus. Migration vers MF6 documentee a la release suivante.

3. Mettre a jour CHANGELOG.md (section Unreleased / Notes) avec une ligne :
   "Documented intentional MODFLOW-NWT sunset plan — see docs/developers/nwt_sunset_plan.md".

4. Mettre a jour la section correspondante du rapport d audit
   docs/developers/migration_report_dev_refact_v2.md (section P06) pour noter
   que la "dette" est en realite une decision assumee, pas une dette.

5. Ne PAS refactoriser flow_to_modflow_adapter.py. Ne PAS toucher au code.

COMMITS attendus (3-4 petits) :
   [F02] - document nwt sunset plan
   [F02] - annotate intentional modflow duplication
   [F02] - update audit report p06 status
   [F02] - changelog nwt sunset note

CRITERES DE SUCCES :
- docs/developers/nwt_sunset_plan.md existe et est coherent.
- Header explicatif present dans les 2 flow_to_modflow_adapter.py.
- CHANGELOG.md mentionne la decision.
- pytest tests/unit/ -q  : aucune regression (pure doc + commentaires).

SIGNALISATION : PHASE_F02_DONE
'
run_phase "F02" "Document NWT/MF6 intentional duplication (sunset plan)" "$F02_PROMPT"

# ---------- F03 : Implement DerivedRegistry (proper DeriveStep) ----------
F03_PROMPT='
OBJECTIF : implementer un vrai DerivedRegistry pour que DeriveStep ne soit
plus un pass-through placeholder (residual P07 du rapport d audit).

CONTEXTE :
- docs/developers/migration_report_dev_refact_v2.md section "P07 — PARTIEL"
- architecture_cible/06_pipeline_execution.md (step 09_derive)
- Etat actuel : hydromodpy/pipeline/steps/step_09_derive.py est un
  pass-through (# delegated to extractors for now).
- Les calculs derives existent deja dans hydromodpy/results/derived.py
  (watertable_elevation, watertable_depth, seepage_mask, fluxes_from_budget).

DECISION UTILISATEUR :
- Option B : implementer un vrai DerivedRegistry proprement.
- Si vraiment trop complexe/risque : fallback option A (fusion avec ExtractStep,
  suppression de DeriveStep, alignement spec 06). Documenter la decision prise.

TACHES :

1. Creer hydromodpy/pipeline/derived.py :
   - Protocol DerivedComputation avec methode
       compute(sim_zarr: SimulationZarr, **ctx) -> xarray.DataArray
   - class DerivedRegistry : dict[name, DerivedComputation]
     avec register, get, list.
   - Chaque computation declare : output_name, required_inputs (head, budget, etc.),
     description.

2. Enregistrer les derives existants via le registry :
   - watertable_elevation  : lit head
   - watertable_depth      : lit head + dem (via geographic cache)
   - seepage_mask          : lit head + topographic_constraint
   - fluxes_from_budget    : lit cell_budget
   Wrapper autour des fonctions actuelles de hydromodpy/results/derived.py.

3. Refactoriser step_09_derive.py :
   - Consulter le registry.
   - Pour chaque derive enregistree : si les inputs sont presents dans le Zarr,
     calculer et ecrire /derived/<name> dans le store.
   - Respecter l ordre topologique si un derive depend d un autre.
   - Logger clairement quel derive a ete calcule / skippe (input manquant).

4. Exposer le registry via l API publique :
   - hmp.pipeline.derived.registry (singleton).
   - Permettre l enregistrement externe via entry_points si utile (optionnel).

5. Aligner la spec :
   - architecture_cible/06_pipeline_execution.md : mettre a jour §1.1 pour
     refleter les 11 steps effectifs (PAS 14) avec le DeriveStep-registry
     explicite. Laisser les autres sections intactes.

6. Tests :
   - tests/unit/test_derived_registry.py : registry register/get/list, ordre
     topologique, input manquant = skip.
   - Enrichir tests/unit/test_pipeline_basic.py si pertinent.
   - Preserver tests/unit/test_derived_watertable.py (deja en P08).

7. Si BLOQUE (vrai registry trop complexe ou casse des tests regression) :
   - FALLBACK : supprimer step_09_derive.py, fusionner sa logique dans
     step_08_extract.py, retirer "derive" de la liste des steps du pipeline,
     aligner la spec. Commit dedie [F03] - merge derive into extract.
   - Documenter la decision dans le commit message + note au CHANGELOG.

COMMITS attendus (option B) :
   [F03] - add derived protocol and registry
   [F03] - register watertable derivations
   [F03] - register seepage derivation
   [F03] - register fluxes derivation
   [F03] - implement derive step via registry
   [F03] - align pipeline spec on 11 steps
   [F03] - add derived registry tests

CRITERES DE SUCCES :
- pytest tests/unit/test_derived_registry.py  passe (si option B).
- pytest tests/unit/test_pipeline_*  passe.
- pytest tests/regression/fast/test_pipeline_full.py  passe.
- step_09_derive.py n est plus un pass-through vide.
- 06_pipeline_execution.md refete la structure effective.

SIGNALISATION : PHASE_F03_DONE
'
run_phase "F03" "Implement DerivedRegistry for DeriveStep" "$F03_PROMPT"

# ---------- F04 : Display env vars + residual folders cleanup ----------
F04_PROMPT='
OBJECTIF : supprimer DEFINITIVEMENT les env vars HYDROMODPY_NO_DISPLAY /
HYDROMODPY_NO_SAVE et les coquilles vides analysis/display, analysis/postprocess
(residual P08 du rapport d audit).

DECISION UTILISATEUR :
- Suppression nette. PAS de shim de retrocompatibilite. PAS de DeprecationWarning.
- La migration v0.3 -> v0.4 est un bump majeur, cette breaking change est actee.

CONTEXTE :
- 43 fichiers referencent encore HYDROMODPY_NO_DISPLAY / HYDROMODPY_NO_SAVE :
  workflows CI (.github/workflows/linux-boussinesq.yml, docs-gallery-check.yml),
  tests validation (tests/validation/numerical/*/test_boussinesq_*),
  tests regression (tests/regression/launcher_simulation_helpers.py),
  validation_cases/shared/runtime.py,
  install/, tools/investigate_*.py,
  run_migration.sh (a laisser intact — script historique immuable).
- analysis/display/{figures,report}/ : coquilles vides avec __pycache__.
- analysis/postprocess/{flow,netcdf,timeseries}/ : idem.

TACHES :

1. Lister exhaustivement les fichiers concernes (Agent Explore + grep) :
   grep -rln "HYDROMODPY_NO_DISPLAY\|HYDROMODPY_NO_SAVE" \
       --include="*.py" --include="*.yml" --include="*.md" \
       . | grep -v __pycache__

2. Migrer les fichiers de test et CI vers la config TOML [display] :
   - Tests regression/validation : utiliser la fixture tmp_workspace et
     injecter [display] save = false, interactive = false dans le TOML.
     Ou simplement utiliser le defaut non-interactif.
   - CI yml : retirer les "env: HYDROMODPY_NO_DISPLAY: 1" blocks. Verifier que
     les jobs continuent de passer (DisplayConfig.interactive = False par defaut).
   - validation_cases/shared/runtime.py : retirer la lecture de ces env vars,
     utiliser la config.

3. Purger les dernieres references code interne :
   - hydromodpy/display/config.py : retirer le shim de lecture env vars
     si encore present.
   - hydromodpy/results/display.py : idem.

4. Supprimer physiquement les coquilles vides :
     rm -rf hydromodpy/analysis/display
     rm -rf hydromodpy/analysis/postprocess
   (verifier que c est bien des coquilles vides : ne contient que __pycache__).

5. Purger aussi install/, tools/investigate_*.py : retirer les references
   env vars (ou supprimer le fichier si mort).

6. Mettre a jour docs/ et CLAUDE.md :
   - CLAUDE.md section "Environment Variables" : supprimer HYDROMODPY_NO_DISPLAY
     et HYDROMODPY_NO_SAVE de la liste.
   - docs/ : meme traitement si mentions.
   - Mentionner le breaking change dans CHANGELOG.md (section Removed ou
     Breaking Changes).

7. Relancer :
     pytest tests/unit/ -q
     pytest tests/regression/fast/ -q
   Tous doivent passer.

EXCEPTIONS (fichiers a NE PAS modifier) :
- run_migration.sh (script historique immuable).
- run_finalization.sh (ce script).
- docs/developers/migration_report_dev_refact_v2.md (rapport d audit fige).
- CHANGELOG.md entries deja presentes (on peut ajouter des lignes, pas modifier).

COMMITS attendus (6-10 petits) :
   [F04] - remove env vars from ci workflows
   [F04] - remove env vars from validation tests
   [F04] - remove env vars from regression helpers
   [F04] - remove env vars from validation cases
   [F04] - remove env vars from tools and install
   [F04] - remove display env vars shim
   [F04] - delete empty analysis display folder
   [F04] - delete empty analysis postprocess folder
   [F04] - update claude md env vars section
   [F04] - changelog display breaking change

CRITERES DE SUCCES :
- grep -rln "HYDROMODPY_NO_DISPLAY\|HYDROMODPY_NO_SAVE" \
       --include="*.py" --include="*.yml" .  ne retourne QUE run_migration.sh
   (et le CHANGELOG pour mentionner la suppression).
- hydromodpy/analysis/display/ et hydromodpy/analysis/postprocess/ n existent plus.
- pytest tests/unit/ -q  passe.
- pytest tests/regression/fast/ -q  passe.

SIGNALISATION : PHASE_F04_DONE
'
run_phase "F04" "Remove headless env vars + delete empty analysis folders" "$F04_PROMPT"

# ---------- F05 : API naming + CLI completion ----------
F05_PROMPT='
OBJECTIF : renommer proprement les methodes catalog.* et ajouter les entries
__all__ manquantes (residual P10 du rapport d audit).

DECISION UTILISATEUR :
- Rename NET (pas d alias, pas de DeprecationWarning). Breaking change acte.

CONTEXTE :
- docs/developers/migration_report_dev_refact_v2.md section "P10 — PARTIEL"
- architecture_cible/10_ux_cli_api.md §2.3 et §3.1

TACHES :

1. Renommages API publique (hydromodpy/results/catalog.py) :
   - SimulationCatalog.export_simulation(sim_id, dst)  ->  SimulationCatalog.export(sim_id, dst)
   - SimulationCatalog.import_simulation(src)          ->  SimulationCatalog.import_package(src)
   Grep l ensemble du codebase pour ces deux methodes, appliquer le rename
   (tests, docs, examples, runners, CLI, __init__).

2. Ajouter SimulationPlan a __all__ (hydromodpy/__init__.py) :
   - Ajouter l entree _LAZY_IMPORTS si absente.
   - Ajouter dans __all__.
   - Verifier que hmp.SimulationPlan est importable.

3. CLI : rien a modifier obligatoirement. Si des sous-commandes hmp doctor /
   hmp inspect sont triviales a ajouter, optionnel. NE PAS forcer.

4. Adapter les tests :
   - tests/unit/test_api_public.py : assert nouveaux noms.
   - tests/unit/test_cli_help.py : ok si inchange.
   - Tout test qui appelle export_simulation / import_simulation : renommer.

5. Mettre a jour docs :
   - CLAUDE.md : exemple API fluent doit utiliser catalog.export / import_package.
   - README.md : idem si mention.
   - docs/developers/ : idem.
   - examples/ : appels eventuels.

6. CHANGELOG : section Breaking Changes (ou Changed) :
   "Renamed catalog.export_simulation -> catalog.export,
    renamed catalog.import_simulation -> catalog.import_package."

COMMITS attendus (4-6 petits) :
   [F05] - rename catalog export simulation
   [F05] - rename catalog import simulation
   [F05] - add simulationplan to public all
   [F05] - update tests for catalog rename
   [F05] - update docs for catalog rename
   [F05] - changelog catalog rename

CRITERES DE SUCCES :
- grep -rn "export_simulation\|import_simulation" hydromodpy/ tests/ examples/  ne retourne rien
  (hors CHANGELOG qui documente).
- pytest tests/unit/test_api_public.py tests/unit/test_cli_*  passe.
- pytest tests/unit/ -q  pas de regression.
- hmp.SimulationPlan importable.

SIGNALISATION : PHASE_F05_DONE
'
run_phase "F05" "API rename catalog.export/import_package + SimulationPlan exposure" "$F05_PROMPT"

# ---------- F06 : Integration tests folder + validation_cases repair ----------
F06_PROMPT='
OBJECTIF : creer tests/integration/, ajouter les fixtures manquantes, reparer
les 3 tests skipes du a validation_cases/shared/ (residual P12 du rapport
d audit).

CONTEXTE :
- docs/developers/migration_report_dev_refact_v2.md section "P12 — PARTIEL"
- architecture_cible/09_tests_ideaux.md
- 3 tests skipes :
    tests/unit/tools/test_doc_gallery_calibration_cases.py
    tests/unit/tools/test_doc_gallery_extensions.py
    tests/unit/tools/test_doc_gallery_validation_cases.py
  Raison commune : "cannot import name load_last_npy_array_on_expected_grid
  from validation_cases.shared".

DECISION UTILISATEUR :
- Reparer absolument validation_cases/shared/.

TACHES :

1. Reparer validation_cases/shared/ :
   - Lire validation_cases/shared/__init__.py pour voir l etat actuel.
   - Restaurer (ou creer) la fonction load_last_npy_array_on_expected_grid.
     Signature attendue (a deduire des appelants) :
         load_last_npy_array_on_expected_grid(case_dir: Path, *, expected_grid=None) -> np.ndarray
     Logique : trouve le .npy le plus recent dans case_dir, charge, verifie que
     la shape correspond a expected_grid (optionnel), retourne l array.
   - Verifier que les 3 tests passent maintenant :
       pytest tests/unit/tools/test_doc_gallery_*.py -v
     Ils ne doivent plus etre skippes.

2. Creer tests/integration/ :
   - tests/integration/__init__.py (vide)
   - tests/integration/conftest.py minimal (fixtures communes si pertinent)
   - Ne pas forcer la migration de tests depuis unit/. Juste le scaffold
     pour que les prochains tests cross-module y trouvent leur place.
   - Documenter le scope dans tests/README.md :
       unit/          — 1 module isole, < 2s, pas d IO reel
       integration/   — cross-module, fixtures partagees, < 10s
       regression/    — via launcher/run, golden files
       validation/    — benchmarks scientifiques

3. Ajouter fixtures au conftest.py racine (tests/conftest.py) :
   - tmp_workspace(tmp_path) : cree un workspace HMP initialise (via hmp init
     programmatic ou setup manuel des dossiers attendus). Yield le chemin.
   - minimal_config() : fixture qui cree un HydroModPyConfig minimal valide
     (Pydantic pret a l emploi, sans IO).
   Ces fixtures doivent etre utilisables par tous les sous-dossiers.

4. Preferer les migrations "safes" : si un test de tests/unit/ est en realite
   cross-module et bouge le store ou le pipeline complet, on peut le deplacer
   vers tests/integration/. Maximum 3-5 migrations prudentes. Ne pas forcer.

5. Mettre a jour .github/workflows/coverage.yml :
   - Ajouter un job integration (tests/integration) si integration/ contient
     au moins 1 test. Sinon, skip (ne rien ajouter).

6. Mettre a jour docs/developers/migration_report_dev_refact_v2.md section
   P12 : noter la resolution (3 tests plus skipes, fixtures ajoutees, dossier
   integration/ scaffold).

COMMITS attendus (5-8 petits) :
   [F06] - restore load last npy array helper
   [F06] - unskip doc gallery validation tests
   [F06] - add integration tests scaffold
   [F06] - add tmp workspace fixture
   [F06] - add minimal config fixture
   [F06] - document test tiers
   [F06] - migrate cross module tests to integration
   [F06] - update coverage workflow

CRITERES DE SUCCES :
- pytest tests/unit/tools/test_doc_gallery_*.py -v  : PASSED (pas SKIPPED).
- tests/integration/ existe avec conftest.py.
- Fixtures tmp_workspace et minimal_config disponibles depuis conftest racine.
- pytest tests/unit/ -q  pas de regression.

SIGNALISATION : PHASE_F06_DONE
'
run_phase "F06" "Repair validation_cases/shared + integration tier + fixtures" "$F06_PROMPT"

# ---------- F07 : Docs polish + Meteo-France rename + glossary ----------
F07_PROMPT='
OBJECTIF : cleanup documentaire final :
- Rename "INRAE" -> "Meteo-France" partout (code + docs + file names).
- Glossary 15+ termes.
- CLAUDE.md corrige (Length/Time, pas LengthM/TimeS).
- CHANGELOG aligne sur Keep-a-Changelog avec Breaking Changes explicites.
- roadmap v0.4.

REGLE DURE (utilisateur insistant) :
- La donnee SIM2 est **Meteo-France** (SAFRAN-ISBA reanalyse surface).
- INRAE (via geosas.fr) est uniquement le DISTRIBUTEUR. Aucune mention a INRAE
  dans le code public, docstrings, docs utilisateur, file names.
- Seul le commentaire technique proche de l URL peut dire "via geosas.fr
  distributor" SANS nommer INRAE.

CONTEXTE :
- docs/developers/migration_report_dev_refact_v2.md sections "P01" et "P13".
- hydromodpy/data/common/clients/sim2_inrae.py  -> a renommer sim2_meteofrance.py.
- CLAUDE.md:221 mentionne LengthM, TimeS qui n existent pas (seuls Length, Time
  existent dans hydromodpy/core/units/types.py).

TACHES :

1. Rename file :
   - git mv hydromodpy/data/common/clients/sim2_inrae.py hydromodpy/data/common/clients/sim2_meteofrance.py
   - Adapter tous les imports (grep "sim2_inrae" dans le codebase).
   - Adapter tous les tests (tests/unit/data_managers/test_sim2_inrae_smoke.py ->
     test_sim2_meteofrance_smoke.py).

2. Purger toute mention a "INRAE" dans le code et les docs utilisateur :
   - grep -rn "INRAE\|inrae" --include="*.py" --include="*.md" --include="*.toml" .
   - Remplacer par "Meteo-France" (ou retirer si redondant avec le nom du produit SIM2).
   - Exceptions autorisees : commentaire technique unique au dessus de l URL
     api.geosas.fr, forme : "# SIM2 data distributed via geosas.fr" (pas INRAE).
   - docstring des classes client : "SIM2 (Meteo-France SAFRAN-ISBA surface reanalysis)".
   - Messages CLI user-facing : idem.

3. Corriger CLAUDE.md :
   - Remplacer LengthM -> Length et TimeS -> Time dans les exemples.
   - Verifier que les autres alias listes correspondent aux types effectivement
     exposes par hydromodpy/core/units/types.py.
   - Mettre a jour la section Environment Variables si pas fait en F04.

4. Enrichir docs/developers/glossary.md :
   - Ajouter les 2 termes manquants en H3 : sim_id, run_id (definitions breves).
   - Ajouter tout autre terme utile apparu depuis P01 : PipelineState,
     Checkpoint, Ledger, DerivedRegistry (F03), ParamsHashCache, etc.
   - Objectif : 16+ termes H3 clairs.

5. CHANGELOG.md consolidation :
   - Section [Unreleased] -> [0.4.0] - 2026-04-XX (date du run).
   - Sous-sections explicites :
       ### Breaking Changes
       ### Added
       ### Changed
       ### Removed
       ### Fixed
       ### Migration Guide
   - Migration Guide : 5-10 lignes sur comment migrer un ancien TOML :
       * [display] section remplace les env vars HYDROMODPY_NO_*
       * catalog.export / import_package (nouveau nom)
       * section [calibration] simplifiee
       * SIM2 client renomme
   - Factoriser les entrees existantes P01-F07 dans le format Keep-a-Changelog.

6. roadmap.md (creer ou mettre a jour docs/roadmap.md) :
   - v0.4 (imminent) : end of migration, breaking changes listed.
   - v0.5 : Lake module integration (MF6), NWT sunset begins.
   - v0.6 : NWT removal, PEST++ optional adapter via entry_points.

7. Relancer pytest tests/unit/ -q pour s assurer aucun import casse.

COMMITS attendus (6-10 petits) :
   [F07] - rename sim2 inrae to meteofrance
   [F07] - purge inrae mentions from code
   [F07] - purge inrae mentions from docs
   [F07] - fix claude md unit aliases
   [F07] - extend glossary with pipeline terms
   [F07] - consolidate changelog v040
   [F07] - add migration guide section
   [F07] - update roadmap v040 and beyond

CRITERES DE SUCCES :
- grep -rn "INRAE\|inrae" --include="*.py" --include="*.md" --include="*.toml" .
   ne retourne QUE le commentaire technique unique au dessus de l URL geosas.fr
   (max 1-2 occurrences) + eventuellement CHANGELOG entry documentant le rename.
- hydromodpy/data/common/clients/sim2_inrae.py  n existe plus.
- docs/developers/glossary.md  a >= 16 termes H3.
- CLAUDE.md  ne mentionne plus LengthM / TimeS.
- CHANGELOG.md  a les sections Breaking Changes / Migration Guide.
- pytest tests/unit/ -q  passe.

SIGNALISATION : PHASE_F07_DONE
'
run_phase "F07" "Docs polish: Meteo-France rename + glossary + CHANGELOG" "$F07_PROMPT"

# ---------- F08 : VERIFY — Full architecture conformance report ----------
F08_PROMPT='
OBJECTIF : balayer EXHAUSTIVEMENT les 14 specs architecture_cible/*.md et
produire un rapport de conformite final :

    docs/developers/architecture_conformance_report.md

Ce rapport remplace (ou complete) le migration_report_dev_refact_v2.md : il
atteste, a la fin de la finalisation, que tout ce qui etait demande a bien
ete fait, OU documente les ecarts assumes.

CONTEXTE :
- 14 specs dans architecture_cible/ (de 01_structure_packages.md a
  14_plan_migration.md + 13_coherence_globale.md + CHANGELOG.md).
- Etat precedent : docs/developers/migration_report_dev_refact_v2.md
  (audit apres P13). A utiliser comme baseline.

APPROCHE :

Pour CHAQUE spec (traitees une par une, parallelisation via Agent OK) :

1. Lire integralement le fichier architecture_cible/XX_*.md.

2. Extraire une liste de CHECKPOINTS concrets (contrats testables) :
   - "Fichier X doit exister"
   - "Classe Y doit exposer methode Z(args) -> type"
   - "CLI `hmp ...` doit retourner code 0"
   - "Table DuckDB <name> doit avoir colonnes (a, b, c)"
   - "Import from module.path doit fonctionner"
   Viser 10-30 checkpoints par spec selon la densite.

3. Pour chaque checkpoint, VERIFIER contre le code reel (pas contre git log,
   pas contre le rapport d audit). Utiliser :
   - Read/Glob/Grep pour les fichiers.
   - Bash pour pytest / hmp CLI / python -c "import ...".
   - Agent Explore pour les recherches larges.

4. Enregistrer le verdict :
   - [OK]        : conforme, avec file:line comme preuve.
   - [ECART]     : divergence mineure ou decision assumee (ex. doc : NWT/MF6
                   duplication conservee via F02). Expliquer en 1-2 lignes.
   - [MANQUANT]  : spec non satisfaite. Expliquer + proposer une tache de
                   suivi concrete (nom de fichier, methode a ajouter).

STRUCTURE DU RAPPORT (docs/developers/architecture_conformance_report.md) :

# Rapport de conformite architecture — HydroModPy v0.4

**Date :** <date-du-run>
**Branche :** dev-refact_v2 au commit <HEAD-short>
**Base :** run_migration.sh (P01-P13) + run_finalization.sh (F01-F08)

## Executive summary

| Spec | OK | Ecart | Manquant | Verdict global |
|------|----|-------|----------|----------------|
| 01_structure_packages.md | N | N | 0 | OK |
| 02_config_pydantic.md | ... | ... | ... | ... |
| ...                  | ... | ... | ... | ... |
| 14_plan_migration.md | ... | ... | ... | ... |
| **TOTAL**            | ... | ... | ... | ... |

## Detail par specification

### 01_structure_packages.md
**Resume :** <1 phrase>
**Checkpoints :** N au total, OK=N, Ecart=N, Manquant=N.

| # | Checkpoint | Verdict | Preuve / Note |
|---|------------|---------|---------------|
| 1 | `hydromodpy/core/` existe | OK | ls hydromodpy/core |
| 2 | `DelineationBackend` Protocol | OK | hydromodpy/spatial/delineation/base.py:23 |
| 3 | ... | ... | ... |

**Ecarts assumes :** (decisions F02 NWT sunset, etc.)

**Manquants :** (si applicable — toute tache de suivi)

### 02_config_pydantic.md
... (meme structure)

### ...

## Ecarts globaux assumes (decisions architecture)

1. **NWT/MF6 duplication conservee** — F02 documentation.
   Raison : MODFLOW-NWT sera retire post-lake-module.
   Impact : ~1400 lignes dupliquees dans flow_to_modflow_adapter.py
   volontaires jusqu a la v0.5.

2. ... (autres decisions documentees)

## Manquants residuels (a traiter post-v0.4)

1. ... (avec ticket / tache de suivi proposee)
2. ...

## Conclusion

- Specs integralement conformes : N/14.
- Specs avec ecarts assumes mais alignees : N/14.
- Specs avec manquants : N/14.
- Verdict final : MIGRATION <TERMINEE | PARTIELLE>.

---

TACHES :

1. Creer le squelette du rapport.

2. Parcourir les 14 specs UNE PAR UNE. Pour chaque :
   - Lire integralement.
   - Extraire les checkpoints.
   - Verifier.
   - Ecrire la section.
   - Committer (commit atomique par spec) :
       [F08] - verify spec 01
       [F08] - verify spec 02
       ...
       [F08] - verify spec 14

3. Synthetiser l executive summary (tableau global).

4. Lister les ecarts assumes (verifier que les phases F02, etc. sont bien
   documentees).

5. Lister les manquants residuels (tout ce qui resterait apres F01-F07).

6. Verifier une derniere fois :
   - pytest tests/unit/ -q
   - pytest tests/regression/fast/ -q
   - hmp --help
   - import hydromodpy as hmp; hmp.open  (smoke)

7. Commit final :
       [F08] - add final conformance report

8. Si tout est vert, un commit :
       [F08] - mark migration complete v040

REGLES DE RIGUEUR :
- PAS de paraphrase du migration_report_dev_refact_v2.md. Cet audit est
  obsolete : re-verifier TOUT a partir du code reel apres F01-F07.
- Preuves concretes uniquement : file:line ou sortie de commande. Pas de
  "je suppose que".
- Si un checkpoint ne peut pas etre verifie (env manquant, donnees reseau),
  le noter "NON VERIFIE" avec raison.

COMMITS attendus (15-20 petits) :
   [F08] - scaffold conformance report
   [F08] - verify spec 01 structure packages
   [F08] - verify spec 02 config pydantic
   [F08] - verify spec 03 data contracts
   [F08] - verify spec 04 storage ideal
   [F08] - verify spec 05 solver contracts
   [F08] - verify spec 06 pipeline execution
   [F08] - verify spec 07 calibration
   [F08] - verify spec 08 postprocess display
   [F08] - verify spec 09 tests ideaux
   [F08] - verify spec 10 ux cli api
   [F08] - verify spec 11 frontend ready
   [F08] - verify spec 12 input data rethink
   [F08] - verify spec 13 coherence globale
   [F08] - verify spec 14 plan migration
   [F08] - summarize conformance report
   [F08] - mark migration complete v040

CRITERES DE SUCCES :
- docs/developers/architecture_conformance_report.md existe, complet, avec
  des preuves concretes (file:line ou commande).
- Executive summary tableau rempli pour les 14 specs.
- Liste d ecarts assumes coherente avec les decisions F02/F03/etc.
- pytest tests/unit/ -q  passe.

SIGNALISATION : PHASE_F08_DONE
'
run_phase "F08" "VERIFY — Full architecture conformance report" "$F08_PROMPT"

# ===============================================================
# RECAP FINAL
# ===============================================================
log ""
log "================================================================"
log "  FINALIZATION TERMINEE"
log "  End    : $(date '+%Y-%m-%d %H:%M:%S')"
log "  Branch : $(git -C "$PROJECT" rev-parse --abbrev-ref HEAD)"
log "  HEAD   : $(git -C "$PROJECT" rev-parse --short HEAD)"
log "================================================================"
show_status
notify "Finalization complete"
