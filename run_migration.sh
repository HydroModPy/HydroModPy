#!/usr/bin/env bash
#
# run_migration.sh — Restructuration complete de HydroModPy vers architecture_cible/
#
# Usage:
#   tmux new-session -s migration './run_migration.sh'        # lance depuis le debut
#   ./run_migration.sh --status                               # affiche l'etat
#   ./run_migration.sh --phase P05                            # relance phase specifique
#   ./run_migration.sh --resume                               # equivalent au defaut
#   ./run_migration.sh --reset                                # DANGEREUX: efface l'etat
#
# Gestion automatique :
#   - Rate limits Claude (attente jusqu'au reset, max 6h)
#   - Reprise apres crash / deconnexion (etat persistent)
#   - Commits petits et frequents (format "[Pxx] - <few english words>")
#   - ZERO push, ZERO changement de branche, ZERO Co-Authored-By
#
set -euo pipefail

# ===============================================================
# CONFIGURATION
# ===============================================================
PROJECT="/home/bb/Documents/01_Git_Repository/02-HydroModPy-dev"
SPECS="$PROJECT/architecture_cible"
AUDIT="$PROJECT/audit_code"
STATE_DIR="$PROJECT/migration"
PHASES_DIR="$STATE_DIR/phases"
LOG="$STATE_DIR/migration.log"
STDOUT_TMP="$STATE_DIR/.stdout_last"
STDERR_TMP="$STATE_DIR/.stderr_last"
MAX_RETRIES=15
MAX_WAIT=21600          # 6h max wait (plan limit reset)
BRANCH_AT_START=""
INITIAL_COMMIT=""

ALL_PHASES=(P01 P02 P03 P04 P05 P06 P07 P08 P09 P10 P11 P12 P13)

mkdir -p "$STATE_DIR" "$PHASES_DIR"

# ===============================================================
# HELPERS — log, notify
# ===============================================================
log() {
    local ts
    ts="[$(date '+%Y-%m-%d %H:%M:%S')]"
    echo "$ts $*" | tee -a "$LOG"
}

notify() {
    notify-send "HydroModPy Migration" "$*" 2>/dev/null || true
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
        log "FATAL: refuse to run migration on $BRANCH_AT_START branch"
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
        notify "ABORT: branch changed during migration"
        exit 99
    fi
}

check_specs_present() {
    local missing=0
    for f in 01_structure_packages.md 02_config_pydantic.md 03_data_contracts.md \
             04_storage_ideal.md 07_calibration.md 11_frontend_ready.md \
             12_input_data_rethink.md 14_plan_migration.md; do
        if [[ ! -s "$SPECS/$f" ]]; then
            log "MISSING SPEC: $SPECS/$f"
            missing=$((missing + 1))
        fi
    done
    if [[ $missing -gt 0 ]]; then
        log "FATAL: $missing spec files missing — aborting"
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
  REGLES STRICTES — A NE JAMAIS TRANSGRESSER
===============================================================

AUTORISATIONS COMPLETES sur cette branche :
- Tu peux CREER, MODIFIER, DEPLACER, RENOMMER, SUPPRIMER des fichiers.
- Tu peux SUPPRIMER des dossiers entiers (examples_legacy/, ancien code, etc.).
- Tu peux REECRIRE FROM SCRATCH des fichiers existants si necessaire.
- Tu peux utiliser le Agent tool (subagent_type: general-purpose ou Explore)
  pour paralleliser la recherche et l'analyse de code large.

INTERDICTIONS ABSOLUES (JAMAIS, SOUS AUCUN PRETEXTE) :
- NEVER run 'git push' — interdit formellement (meme --dry-run).
- NEVER run 'git checkout <other-branch>' ni 'git switch' vers une autre branche.
- NEVER run 'git push --force' ni aucune variante.
- NEVER use '--no-verify', '--no-gpg-sign', ou tout flag qui bypass les hooks.
- NEVER add 'Co-Authored-By' / 'Claude' / 'Anthropic' dans les messages de commit.
- NEVER amend commits (toujours creer de NOUVEAUX commits).
- NEVER run 'git rebase', 'git reset --hard' sauf si explicitement demande par la phase.
- NEVER delete .git/, .github/, pyproject.toml, setup.cfg sauf instruction explicite.
- NEVER modifier ce script run_migration.sh lui-meme.

COMMITS — Format OBLIGATOIRE :
- Message EXACT : '[Pxx] - <3 to 7 words in English>'
- Exemples VALIDES :
    [P01] - delete legacy examples folder
    [P02] - add pydantic-pint units module
    [P03] - rename whitebox backend
    [P04] - clean old climatic folder
- Exemples INVALIDES (JAMAIS faire) :
    Migration of whitebox from core to spatial module       (trop long)
    [P01] - refactor                                         (trop vague)
    Multi-line message with description in body              (corps interdit)
    Any line containing "Co-Authored-By" or "Claude"         (banni)
- PETITS COMMITS : 1 operation logique = 1 commit.
  Commit tot et souvent. Exemples de bonne granularite :
    * Apres avoir deplace un dossier              -> 1 commit
    * Apres avoir supprime un fichier mort         -> 1 commit
    * Apres avoir cree une nouvelle classe         -> 1 commit
  Ne JAMAIS batcher 30 modifications en un seul gros commit.
- Apres CHAQUE commit, verifier avec :
    git log -1 --format="%s%n%b"
  pour s'assurer qu'il n'y a PAS de "Co-Authored-By" ni "Claude" ni "Anthropic".
- NE PAS faire de --amend, NE PAS faire de rebase interactive.

STRATEGIE DE TRAVAIL :
1. Lire la spec : architecture_cible/<fichier>.md
2. Consulter l'audit si utile : audit_code/<fichier>.md
3. Lire le code EXISTANT avant de supprimer (ne jamais detruire a l'aveugle).
4. Utiliser Agent/Task pour la recherche large (subagent_type: Explore).
5. Decouper en PETITS commits atomiques (1 intention = 1 commit).
6. Lancer les tests unitaires apres chaque commit substantiel :
     pytest tests/unit/ -v --tb=short -x --maxfail=3
7. Si un test casse legitimement (code obsolete) : le desactiver avec un
   commit dedie et un marker pytest.skip avec raison, ne pas juste le supprimer
   sans justification.
8. Relire tes propres diffs avant de commit :
     git diff --staged
   pour confirmer que le scope correspond au message.

IDEMPOTENCE :
- La phase peut etre relancee apres crash. Verifier TOUJOURS l'etat courant
  avant d'agir :
    if [[ ! -d "old_path" ]]; then
        echo "already migrated, skipping"
    fi
- Une operation deja faite ne doit PAS etre refaite ni causer d'erreur.

CONTEXTE GENERAL :
- Projet : HydroModPy, toolbox hydrogeologique Python (license EPL-2.0).
- Specs cible : architecture_cible/ (lu attentivement avant action)
- Audit existant : audit_code/ (contexte de ce qui existe)
- Code : hydromodpy/  |  Tests : tests/unit, tests/regression/{fast,extensive}, tests/validation
- CLI : hmp (entry : hydromodpy/__main__.py), hydromodpy (alias)
- Python : 3.11-3.13, conda env 'hmp', pip install -e .
- Conventions existantes dans CLAUDE.md (lire si besoin).

SIGNALISATION DE FIN :
Quand la phase est COMPLETEMENT terminee (tous les commits passes, tous les
tests utiles pour cette phase passent), imprimer EXACTEMENT cette ligne sur
la DERNIERE ligne de ta sortie :

    PHASE_Pxx_DONE

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
- Verifier avec 'git log -10 --oneline' qu'aucun commit de cette phase
  ne contient 'Co-Authored-By', 'Claude', ou 'Anthropic'.
- Verifier qu'on est toujours sur la meme branche qu'au demarrage (ne JAMAIS
  faire git checkout vers une autre branche).
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

        # Succes : la sortie se termine par PHASE_Pxx_DONE
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
    echo "=== Migration HydroModPy — status ==="
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
    read -r -p "ERASE all migration state? (type 'YES'): " confirm
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
        SINGLE_PHASE="${2:?Missing phase name, e.g. --phase P05}"
        ;;
    --resume|"")
        :
        ;;
    -h|--help)
        sed -n '1,15p' "$0" | sed 's/^# \?//'
        exit 0
        ;;
    *)
        echo "Unknown arg: $1"
        echo "Usage: $0 [--status|--phase Pxx|--resume|--reset|--help]"
        exit 1
        ;;
esac

# ===============================================================
# INITIALISATION
# ===============================================================
record_initial_state
check_specs_present

log ""
log "================================================================"
log "  MIGRATION HYDROMODPY"
log "  Branch : $BRANCH_AT_START"
log "  HEAD   : $INITIAL_COMMIT"
log "  Start  : $(date '+%Y-%m-%d %H:%M:%S')"
log "  Specs  : $SPECS"
log "  Audit  : $AUDIT"
if [[ -n "$SINGLE_PHASE" ]]; then
    log "  MODE   : single phase = $SINGLE_PHASE"
else
    log "  MODE   : resume-all (skip already done)"
fi
log "================================================================"

# ===============================================================
# PHASES
# ===============================================================

# ---------- P01 : Foundations ----------
P01_PROMPT='
OBJECTIF : poser les fondations (clean slate, glossaire, docs migration).

SPECS A LIRE :
- architecture_cible/01_structure_packages.md
- architecture_cible/13_coherence_globale.md
- architecture_cible/14_plan_migration.md

TACHES :

1. Inventaire preliminaire (utiliser Agent Explore) :
   - Lister le contenu de examples_legacy/ (si present).
   - Lister les .md obsoletes dans reporting/ (avant le audit recent).
   - Noter ce qui est du code vs ce qui est obsolete.

2. Nettoyage :
   - Supprimer examples_legacy/ SI il contient uniquement du code obsolete
     non reference par examples/ ni par tests/.
   - Supprimer les caches DuckDB de test a la racine (pas ceux dans ~/hydromodpy/
     du user, seulement dans le repo). Typiquement tests/data/*.duckdb.
   - NE PAS toucher a docs/, CLAUDE.md, README.md, pyproject.toml, tests/.

3. Creer la structure docs de migration :
   - docs/developers/schema_evolution.md : documenter les principes futurs
     (table _schema_version a ajouter si besoin plus tard, pattern ALTER
     TABLE, tests de round-trip v(n) -> v(n+1) -> v(n)).
     Preciser : ces principes s appliquent aux evolutions FUTURES, pas a
     la base existante qui est clean slate.
   - docs/developers/glossary.md : definitions uniformes pour Project,
     Workspace, Simulation, Run, Catalog, Plan, Pipeline, Step, Adapter,
     Backend, Variable, Manager, Source (extraire de
     architecture_cible/13_coherence_globale.md).

4. Verifier que les entry points CLI fonctionnent encore (smoke test) :
     hmp --help
     hydromodpy --help
   Si casses, faire un commit minimal de reparation dans ce scope.

COMMITS attendus (petits, atomiques) :
   [P01] - delete legacy examples folder
   [P01] - add schema evolution docs
   [P01] - add glossary
   [P01] - smoke test cli entrypoints

CRITERES DE SUCCES :
- hmp --help retourne code 0
- docs/developers/schema_evolution.md et docs/developers/glossary.md existent
- Tests unit continuent de passer : pytest tests/unit/ -q
- Aucun commit avec Co-Authored-By

SIGNALISATION : PHASE_P01_DONE
'
run_phase "P01" "Foundations: cleanup + glossary + migration docs" "$P01_PROMPT"

# ---------- P02 : Storage ----------
P02_PROMPT='
OBJECTIF : refondre le stockage (DuckDB schema clean + Zarr layout + geographic fingerprint).

SPEC A LIRE : architecture_cible/04_storage_ideal.md

TACHES :

1. Lire le code actuel hydromodpy/results/ en entier (utiliser Agent Explore
   si volumineux) : catalog.py, zarr_store.py, catalog_schema.py, config.py,
   exporters/, provenance.py, simulation.py, simulation_group.py.

2. Refactorer hydromodpy/results/catalog_schema.py :
   - Implementer le nouveau schema DuckDB (12 tables selon spec).
   - PAS de table _schema_version (clean slate).
   - Ajouter colonne config_snapshot JSONB (ou TEXT avec contenu JSON)
     dans simulations. Pas de colonnes eparses par parametre.
   - PKs/FKs conformes au spec.

3. Creer hydromodpy/results/geographic_cache.py :
   - Class GeographicCache avec fingerprint SHA-256 des inputs resolus
     (DEM path+sha, geology path+sha, bbox, resolution, crs).
   - Stockage dans workspace/geographic/<fingerprint>.zarr/.
   - API : fingerprint_of(spatial_config), is_cached(fp), load(fp), save(fp, data).
   - Ecrit dans workspace level (pas par simulation).

4. Modifier hydromodpy/results/zarr_store.py :
   - SimulationZarr stocke un geographic_fingerprint en metadonnees.
   - Ne PAS dupliquer les rasters dans chaque sim Zarr par defaut.
   - sim.geographic lit via le cache (resout fingerprint).

5. Modifier les exporters pour materialiser geographic/ dans le .hmp (zip)
   depuis le cache : hydromodpy/results/exporters/hmp_package.py (ou equivalent).

6. Tests unitaires minimaux :
   - tests/unit/test_storage_catalog.py : creer catalog, insert sim, read sim.
   - tests/unit/test_geographic_cache.py : fingerprint stable pour meme inputs.

NE PAS inclure de logic de migration depuis l ancienne DB : clean slate.

COMMITS attendus :
   [P02] - define new duckdb schema
   [P02] - add config snapshot column
   [P02] - add geographic fingerprint cache
   [P02] - update zarr store with fingerprint
   [P02] - materialize geographic on export
   [P02] - add catalog unit tests
   [P02] - add geographic cache tests

CRITERES DE SUCCES :
- pytest tests/unit/test_storage_catalog.py passe
- pytest tests/unit/test_geographic_cache.py passe

SIGNALISATION : PHASE_P02_DONE
'
run_phase "P02" "Storage: new DuckDB schema + geographic fingerprint cache" "$P02_PROMPT"

# ---------- P03 : Config (Pydantic + pydantic-pint) ----------
P03_PROMPT='
OBJECTIF : config system avec pydantic-pint et JSON Schema enrichi.

SPEC A LIRE : architecture_cible/02_config_pydantic.md

TACHES :

1. Ajouter pydantic-pint aux dependances :
   - Editer pyproject.toml : ajouter pydantic-pint a la liste dependencies
     (pas en extra, en core — confirme par utilisateur).

2. Creer hydromodpy/core/units/ :
   - registry.py : registry pint avec unites hydrogeologiques
     (m, m/s, mm/day, m3/s, m3/day, -, degC, Pa·s, etc.).
   - types.py : types Pydantic annotes :
       HydraulicConductivity, SpecificYield, SpecificStorage,
       Length, FlowRate, Area, Volume, Time, Dimensionless.
   - Supprimer hydromodpy/core/units/normalize*.py / conversions.py
     ancien si remplace entierement.

3. Refactorer les modeles Pydantic CRITIQUES (pas tous en une phase) :
   - hydromodpy/core/config/flow_config.py et proprietes (k_aquifer,
     specific_yield, specific_storage).
   - Remplacer les float nus par types annotes pint.
   - Retrocompat TOML : accepter "1e-4" (sans unite, fallback m/s)
     ou "0.0001 m/s".

4. Ajouter annotations riches pour JSON Schema :
   - widget_type (slider/input/select/checkbox/file)
   - unit, display_name_fr, help_text_fr, display_min, display_max
   - Utiliser json_schema_extra sur chaque Field important.

5. Creer hydromodpy/core/config/schema_export.py :
   - Fonction export_schema(model_cls) -> dict.
   - CLI : hmp config schema [--section flow] > schema.json

6. Tests :
   - tests/unit/test_units_registry.py
   - tests/unit/test_units_roundtrip.py (pint value -> TOML -> pint value)
   - tests/unit/test_schema_export.py

NE PAS tenter de refactorer TOUS les configs d un coup : cette phase se
concentre sur les fondations (units + flow config). Les autres configs
suivront en P04-P09.

COMMITS attendus (10-15 petits) :
   [P03] - add pydantic-pint dependency
   [P03] - add units registry
   [P03] - add pint annotated types
   [P03] - migrate flow config to units
   [P03] - add rich field annotations
   [P03] - add schema export module
   [P03] - add config schema cli
   [P03] - add units tests

CRITERES DE SUCCES :
- pytest tests/unit/test_units_* passe
- hmp config schema > /tmp/s.json puis jq . /tmp/s.json fonctionne

SIGNALISATION : PHASE_P03_DONE
'
run_phase "P03" "Config: Pydantic + pydantic-pint + JSON Schema" "$P03_PROMPT"

# ---------- P04 : Data layer ----------
P04_PROMPT='
OBJECTIF : finaliser data layer (drag-and-drop scaffold + preservation INRAE).

SPECS A LIRE : architecture_cible/12_input_data_rethink.md, architecture_cible/03_data_contracts.md

TACHES :

1. Preserver l API INRAE avant toute suppression :
   - Lire hydromodpy/data/climatic/sim2_API.py en entier : noter l URL INRAE
     exacte, les endpoints, le mapping des variables.
   - Lire hydromodpy/data/common/clients/sim2_edr.py : verifier qu il pointe
     aussi vers INRAE (sinon, corriger pour pointer vers INRAE, pas
     meteo.data.gouv.fr).
   - Si necessaire, creer hydromodpy/data/common/clients/sim2_inrae.py
     comme le client canonique INRAE.

2. Supprimer hydromodpy/data/climatic/ en ENTIER seulement apres (1) :
   - safransurfex.py, driasclimat.py, driaseau.py, sim2.py, climatic.py,
     sim2_API.py.
   - Verifier qu aucun import du reste du code ne reference ce dossier.
   - Utiliser Agent Explore pour chercher les imports restants.

3. Finaliser le scaffold drag-and-drop :
   - hydromodpy/data/scaffold.py existe : l ameliorer.
   - Au hmp init : creer ~/hydromodpy/{variable}_custom/ pour chaque variable
     de la liste VARIABLES dans scaffold.py.
   - Ajouter un README.md dans chaque dossier custom avec le format attendu.
   - Ajouter un fichier example_locations.csv avec header prerempli commente.

4. Creer hydromodpy/data/auto_scan.py :
   - Fonction scan_custom(workspace_path) -> List[Artifact].
   - Detecte fichiers nouveaux ou modifies (mtime > last_indexed_at du
     data/cache.duckdb artifacts table).
   - Valide le schema (colonnes attendues pour stations vs chroniques).
   - Convertit en format pivot (Parquet pour timeseries, GeoParquet pour geo).
   - Enregistre dans cache.duckdb avec provider="custom".
   - Hook automatique au debut de hmp run et aux imports initiaux.

5. Adapters d ingestion :
   - hydromodpy/data/adapters/csv_to_parquet.py (timeseries, stations)
   - hydromodpy/data/adapters/shp_to_geoparquet.py (geometries)
   - hydromodpy/data/adapters/asc_to_geotiff.py (rasters)
   - L utilisateur ne voit jamais Parquet/GeoParquet : conversion interne.

6. CLI :
   - hmp data check [--variable X] : valide sans ingerer, affiche erreurs schema.
   - hmp data list : liste artefacts indexes (provider, variable, path,
     indexed_at).
   - hmp data add FILE [--type X] : commande power-user, optionnelle.

7. Tests :
   - tests/unit/test_data_scaffold.py
   - tests/unit/test_data_autoscan.py
   - tests/unit/test_csv_to_parquet.py
   - tests/unit/test_sim2_inrae_smoke.py (avec mock HTTP, pas d appel reseau).

COMMITS attendus :
   [P04] - preserve inrae sim2 client
   [P04] - delete climatic legacy folder
   [P04] - enhance custom data scaffold
   [P04] - add auto scan module
   [P04] - add csv to parquet adapter
   [P04] - add shp to geoparquet adapter
   [P04] - add data check cli
   [P04] - add data list cli
   [P04] - add data add cli
   [P04] - add data layer tests

CRITERES DE SUCCES :
- pytest tests/unit/test_data_* passe
- hmp init cree les dossiers custom
- hmp data list fonctionne sur un workspace vide

SIGNALISATION : PHASE_P04_DONE
'
run_phase "P04" "Data layer: scaffold + auto-scan + INRAE preservation" "$P04_PROMPT"

# ---------- P05 : Spatial & Delineation ----------
P05_PROMPT='
OBJECTIF : deplacer whitebox vers spatial/delineation/ multi-backend +
recuperer BV synthetiques.

SPECS A LIRE : architecture_cible/01_structure_packages.md

TACHES :

1. Creer hydromodpy/spatial/delineation/ :
   - base.py : Protocol DelineationBackend avec methodes
       flow_accumulation(dem) -> array
       flow_direction(dem) -> array
       stream_network(dem, threshold) -> geodataframe
       catchment_from_outlet(dem, x, y) -> polygon
   - whitebox_cli_backend.py : migration de core/backends/whitebox_backend.py
   - whitebox_workflows_backend.py : migration de core/backends/whitebox_workflows_backend.py
   - registry.py : dict name -> backend_class + get_backend(name) avec
     fallback gracieux si dependance manquante.

2. Chercher les BV synthetiques dans le projet (utiliser Agent Explore) :
   - Mots-cles : "synthetic", "auto-generated", "headwater_100km2",
     "procedural", "random dem", "synthetic catchment".
   - Regarder dans validation_cases/, examples/, hydromodpy/spatial/,
     hydromodpy/watershed/.
   - Si trouve : creer synthetic_backend.py qui implemente le Protocol.
   - Sinon : stub minimal avec NotImplementedError et TODO.

3. Creer pysheds_backend.py : stub initial avec NotImplementedError
   (backend futur, non prioritaire).

4. Mettre a jour les imports dans tout le code :
   - Utiliser Agent Explore pour chercher les `from hydromodpy.core.backends.whitebox*`
   - Remplacer par `from hydromodpy.spatial.delineation import get_backend`
   - Garder shim de retrocompat temporaire dans core/backends/__init__.py
     avec DeprecationWarning (a supprimer en P13).

5. Tests :
   - tests/unit/test_delineation_protocol.py
   - tests/unit/test_whitebox_cli_backend.py (si existait deja, le deplacer)
   - tests/unit/test_delineation_registry.py

COMMITS attendus :
   [P05] - add delineation protocol
   [P05] - migrate whitebox cli backend
   [P05] - migrate whitebox workflows backend
   [P05] - add delineation registry
   [P05] - add synthetic backend
   [P05] - stub pysheds backend
   [P05] - update spatial imports
   [P05] - add backends compat shim
   [P05] - add delineation tests

CRITERES DE SUCCES :
- pytest tests/unit/test_delineation_* passe
- pytest tests/regression/fast -k "spatial or delineation or watershed" passe
- Imports du code hors hydromodpy/spatial/delineation/ ne referencent
  plus core/backends/whitebox (sauf shim).

SIGNALISATION : PHASE_P05_DONE
'
run_phase "P05" "Spatial: delineation multi-backend + synthetic" "$P05_PROMPT"

# ---------- P06 : Solvers ----------
P06_PROMPT='
OBJECTIF : refondre les contrats solveur (Protocol) + mutualiser via
modflow_common/ + nettoyer code obsolete.

SPEC A LIRE : architecture_cible/05_solver_contracts.md

TACHES :

1. Creer/renforcer hydromodpy/solver/base/ :
   - protocol.py : Protocol SolverAdapter avec methods
       setup(config) -> None
       build(plan) -> None
       run() -> RunResult
       extract(store) -> None
       cleanup() -> None
   - registry.py : registry par (process_type, solver_name) -> adapter_cls.

2. Renforcer hydromodpy/solver/modflow_common/ (existant deja) :
   - flow_translator.py : factoriser mapping BC -> packages MODFLOW commun
     NWT/MF6.
   - boundary_packages.py : RIV, GHB, DRN, CHD, WEL factorises.
   - forcing_discretization.py : recharge, EVT (stress periods).
   - binary_reader.py : lecture HDS, CBC, FHD (endianness robuste).
   - grid_mapping.py : HydroMesh -> DIS/DISV (unifie).

3. Simplifier hydromodpy/solver/modflow_nwt/ :
   - Garder solver.py, solver_config.py, translator.py (etend flow_translator),
     extractor.py, modpath/modpath.py.
   - Supprimer code duplique avec MF6 (passe dans modflow_common).

4. Simplifier hydromodpy/solver/modflow6/ :
   - Garder solver.py, solver_config.py, translator.py, extractor.py,
     gwt.py (transport).

5. Simplifier hydromodpy/solver/boussinesq/ :
   - Garder solver.py, solver_config.py, extractor.py, runtimes/ (dense/sparse).

6. Supprimer toute reference a MODFLOW-2000 ou MODFLOW-USG non supporte :
   - Utiliser Agent Explore pour identifier.
   - Supprimer en commits atomiques par module.

7. Tests :
   - tests/unit/test_solver_protocol.py
   - tests/unit/test_solver_registry.py
   - tests/regression/fast/test_solver_boussinesq_smoke.py (1 config minimale)
   - tests/regression/fast/test_solver_nwt_smoke.py
   - tests/regression/fast/test_solver_mf6_smoke.py

COMMITS attendus :
   [P06] - add solver protocol
   [P06] - add solver registry
   [P06] - factor flow translator
   [P06] - factor boundary packages
   [P06] - factor forcing discretization
   [P06] - factor binary reader
   [P06] - simplify nwt solver
   [P06] - simplify mf6 solver
   [P06] - simplify boussinesq solver
   [P06] - remove modflow 2000 references
   [P06] - add solver smoke tests

CRITERES DE SUCCES :
- pytest tests/unit/test_solver_* passe
- pytest tests/regression/fast -m "nwt or mf6" passe
- pytest tests/regression/fast -k boussinesq passe

SIGNALISATION : PHASE_P06_DONE
'
run_phase "P06" "Solvers: Protocol + modflow_common mutualization" "$P06_PROMPT"

# ---------- P07 : Pipeline & Checkpointing ----------
P07_PROMPT='
OBJECTIF : orchestration Pipeline unique avec checkpointing + reprise crash.

SPEC A LIRE : architecture_cible/06_pipeline_execution.md

TACHES :

1. Creer hydromodpy/pipeline/ :
   - pipeline.py : class Pipeline avec steps: List[Step], run(state) -> State.
   - step.py : Protocol Step avec run(state_in) -> state_out.
   - state.py : PipelineState frozen dataclass (serializable).
   - checkpoint.py : serialize/deserialize state (pickle + zstd) dans
     workspace/.hmp/checkpoints/<run_id>/<step_index>_<step_name>.pkl.zst.
   - ledger.py : gestion table DuckDB steps(run_id, step_index, step_name,
     status, started_at, ended_at, elapsed_ms, error_message).

2. Convertir les steps existants (hydromodpy/workflow/steps/) au nouveau
   Protocol, dans l ordre du pipeline standard :
   - 00_validate : config validation
   - 01_resolve : resolve paths, compute fingerprints
   - 02_load_data : ingest custom + APIs
   - 03_build_geographic : via fingerprint cache (lit ou build)
   - 04_build_mesh : idem, fingerprint-keyed
   - 05_setup_process : Flow/Transport/Particles
   - 06_prepare_solver : translator + adapter setup
   - 07_run_solver : via SolverAdapter
   - 08_extract_results : via extractor
   - 09_derive : watertable, seepage, flux
   - 10_export : Zarr + DuckDB

3. Implementer la reprise :
   - Au demarrage : lire ledger.steps, trouver le premier status != completed.
   - Restaurer letat depuis le checkpoint correspondant (ou precedent).
   - Reprendre a partir de ce step.
   - CLI : hmp run config.toml --resume RUN_ID.

4. Remplacer progressivement l ancienne orchestration (project.py,
   workflow/pipelines/, runners/). Les entry points existants doivent
   continuer a fonctionner via shim qui delegue au nouveau Pipeline.

5. Tests :
   - tests/unit/test_pipeline_basic.py : pipeline linear minimal.
   - tests/unit/test_pipeline_checkpoint.py : crash simule + resume.
   - tests/regression/fast/test_pipeline_full.py : 1 run bout-en-bout rapide.

COMMITS attendus :
   [P07] - add pipeline base class
   [P07] - add step protocol
   [P07] - add state dataclass
   [P07] - add checkpoint serialization
   [P07] - add steps ledger
   [P07] - port validate step
   [P07] - port resolve step
   [P07] - port load data step
   [P07] - port build geographic step
   [P07] - port build mesh step
   [P07] - port setup process step
   [P07] - port run solver step
   [P07] - port extract step
   [P07] - port derive step
   [P07] - port export step
   [P07] - add resume cli flag
   [P07] - add pipeline tests

CRITERES DE SUCCES :
- pytest tests/unit/test_pipeline_* passe
- pytest tests/regression/fast/test_pipeline_full.py passe
- hmp run config.toml --resume fonctionne sur un run interrompu simule

SIGNALISATION : PHASE_P07_DONE
'
run_phase "P07" "Pipeline: orchestration + checkpointing + resume" "$P07_PROMPT"

# ---------- P08 : Post-process & Display ----------
P08_PROMPT='
OBJECTIF : figures et post-traitement solver-agnostiques.

SPEC A LIRE : architecture_cible/08_postprocess_display.md

TACHES :

1. Creer hydromodpy/display/ :
   - figure.py : Protocol Figure avec render(sim, **kwargs) -> mpl.Figure.
   - catalog.py : registry des figures disponibles.
   - figures/ : un fichier par type de figure :
       piezometric_map.py, hydrograph.py, cross_section.py,
       recharge_map.py, seepage_map.py, particle_tracks.py,
       concentration_map.py, water_budget.py, difference_map.py.
   - Chaque figure lit le store (SimulationZarr), PAS le solveur.
     Fonctionne pour DIS et DISV (via grille unifiee).

2. Deplacer metriques dans hydromodpy/results/metrics.py :
   - nse, kge, rmse, bias, correlation, log_nse, pbias.
   - Formules explicites + tests unitaires (comparaison avec
     valeurs de reference publiees).

3. Deplacer calculs derives dans hydromodpy/results/derived.py :
   - watertable_elevation, watertable_depth, seepage_mask,
     fluxes (from budget).
   - Fonctions pures xarray-based.

4. Supprimer ancien code hydromodpy/analysis/display/ et
   hydromodpy/analysis/postprocess/ une fois migre (imports
   residuels a traquer via Agent Explore).

5. Supprimer les env vars magiques HYDROMODPY_NO_DISPLAY et
   HYDROMODPY_NO_SAVE. Remplacer par config TOML :
     [display]
     save = true
     interactive = false
     output_dir = "figures"

6. Tests :
   - tests/unit/test_metrics_nse.py (avec cas connus : NSE=1 identique,
     NSE<0 pire que moyenne, etc.)
   - tests/unit/test_metrics_kge.py
   - tests/unit/test_derived_watertable.py
   - tests/unit/test_figure_catalog.py

COMMITS attendus :
   [P08] - add figure protocol
   [P08] - add figure catalog
   [P08] - port piezometric map
   [P08] - port hydrograph
   [P08] - port cross section
   [P08] - port recharge map
   [P08] - port seepage map
   [P08] - port particle tracks
   [P08] - add metrics module
   [P08] - add derived calculations
   [P08] - remove display env vars
   [P08] - delete old analysis display
   [P08] - add display tests

CRITERES DE SUCCES :
- pytest tests/unit/test_metrics_* passe
- pytest tests/unit/test_figure_* passe
- hmp display <sim_id> piezometric_map produit un PNG

SIGNALISATION : PHASE_P08_DONE
'
run_phase "P08" "Post-process & display: solver-agnostic figures + metrics" "$P08_PROMPT"

# ---------- P09 : Calibration ----------
P09_PROMPT='
OBJECTIF : calibration avec Optuna principal, lightweight mode, TOML simplifie.

SPEC A LIRE : architecture_cible/07_calibration.md

TACHES :

1. Ajouter optuna aux dependances pyproject.toml (core, pas extra).

2. Creer hydromodpy/calibration/ :
   - engine.py : CalibrationEngine qui orchestre.
   - optimizer.py : Protocol Optimizer avec ask() -> params,
       tell(params, metric) -> None, suggest_next() -> params.
   - objective.py : Protocol Objective avec evaluate(sim) -> float | dict.
   - parameters.py : decouverte automatique des parametres calibrables
     depuis annotations Pydantic (Annotated[float, Calibrable(bounds,
     transform, prior)]).
   - adapters/scipy_adapter.py : scipy.optimize (wrap existant).
   - adapters/optuna_adapter.py : Optuna (NOUVEAU).
   - adapters/grid_adapter.py : grid search simple.

3. Modes save_runs :
   - "none" (defaut) : chaque iteration = 1 ligne calibration_iterations
     (params + metrics). Aucun Zarr cree.
   - "best_n" : apres calibration, les N meilleures iterations promues
     en vraies simulations completes (Zarr + export).
   - "all" : 1 Zarr par iteration (lourd, opt-in).
   - Lecture depuis [calibration] save_runs, save_best_n.

4. Cache content-addressable :
   - params_hash = SHA-256(canonical_json des parametres resolus apres
     transform).
   - Si params_hash existe deja : retourne sim_id cached, skip simulation.
   - Table DuckDB calibration_iterations (existe deja) enrichie avec
     params_hash.

5. Integration avec geographic_fingerprint (P02) et pipeline checkpoint
   (P07) : en calibration, geographic et mesh ne sont builded qu une fois
   par fingerprint. Seul le solver tourne a chaque iteration.

6. TOML simplifie :
     [calibration]
     method = "optuna"
     max_iter = 200
     save_runs = "best_n"
     save_best_n = 10

     [calibration.parameters]
     K_aquifer  = { bounds = [1e-6, 1e-3], transform = "log" }
     Sy_main    = { bounds = [0.02, 0.30] }
     drain_cond = { bounds = [1e-4, 1e-1], transform = "log" }
   Le path dans HydroModPyConfig et la prior sont derives des annotations
   Pydantic Calibrable() sur les Field.

7. CLI : hmp calibrate config.toml avec progress bar (rich).

8. Migrer hydromodpy/analysis/calibration/ (ancien code scipy + simplex)
   vers le nouveau hydromodpy/calibration/ :
   - Utiliser Agent Explore pour inventaire.
   - Preserver les methodes qui fonctionnent (simplex comme adapter grid).
   - Supprimer les duplicats.

9. Retirer references PEST++/pyemu du scope. Garder une ligne dans
   docs/roadmap.md : "PEST++ : adapter optionnel via entry_points, post-P13".

10. Tests :
    - tests/unit/test_calibration_parameters.py
    - tests/unit/test_calibration_cache.py (params_hash)
    - tests/unit/test_optuna_adapter.py (si optuna install)
    - tests/unit/test_save_runs_modes.py

COMMITS attendus :
    [P09] - add optuna dependency
    [P09] - add calibration engine
    [P09] - add optimizer protocol
    [P09] - add objective protocol
    [P09] - add calibrable annotations
    [P09] - add scipy optimizer adapter
    [P09] - add optuna adapter
    [P09] - add grid adapter
    [P09] - add save runs none mode
    [P09] - add save runs best n mode
    [P09] - add params hash cache
    [P09] - simplify calibration toml
    [P09] - add calibrate cli
    [P09] - migrate legacy calibration
    [P09] - add calibration tests

CRITERES DE SUCCES :
- pytest tests/unit/test_calibration_* passe
- hmp calibrate examples/calibration/toy.toml termine un run court
- 200 iterations en lightweight mode : 200 lignes DuckDB, 0 Zarrs

SIGNALISATION : PHASE_P09_DONE
'
run_phase "P09" "Calibration: optuna + lightweight + simplified TOML" "$P09_PROMPT"

# ---------- P10 : Python API + CLI ----------
P10_PROMPT='
OBJECTIF : finaliser API publique hmp.* + CLI hmp sous-commandes.

SPEC A LIRE : architecture_cible/10_ux_cli_api.md

TACHES :

1. Refactorer hydromodpy/__init__.py :
   - Lazy imports propres via __getattr__.
   - __all__ complet : open, run, Simulation, Catalog, SimulationGroup,
     Workspace, Geographic, Modflow, Boussinesq, calibrate, compare.
   - _repr_html_ sur Simulation/Catalog/SimulationGroup pour Jupyter.

2. API fluent :
   - sim = catalog.best("canut", metric="nse")
   - sim.field("head").at(timestep=5).plot()
   - sim.timeseries("head", station="P01").plot()
   - group = catalog.find(project="canut", nse_gt=0.7)
   - group.to_dataframe(params=["K","Sy"], metrics=["nse","kge"])
   - catalog.export(sim_id, "sim.hmp")
   - catalog.import_package("sim.hmp")

3. CLI hmp unifie :
   - hmp init
   - hmp new <project>
   - hmp run <config.toml> [--resume RUN_ID]
   - hmp calibrate <config.toml>
   - hmp list [project] [--workspace PATH]
   - hmp show <sim_id>
   - hmp compare <sim_id_a> <sim_id_b>
   - hmp export <sim_id> <destination.hmp>
   - hmp import <source.hmp>
   - hmp config generate <output.toml> [--profile user|dev|expert]
   - hmp config schema [--section X] > schema.json
   - hmp config check <config.toml>
   - hmp config wizard   (interactif)
   - hmp data check
   - hmp data list
   - hmp data add <file> [--type X] [--crs X]
   - hmp display <sim_id> <figure_name>
   - hmp test unit|regression|validation [--fast|--extensive]

4. Exit codes standardises : 0 succes, 1 config invalide, 2 run failed,
   3 not found, 4 user abort.

5. Progress bars (rich) sur commandes longues : run, calibrate, import,
   export, data add.

6. Tests :
   - tests/unit/test_api_public.py
   - tests/unit/test_cli_help.py (toutes les --help fonctionnent)
   - tests/unit/test_cli_exit_codes.py

COMMITS attendus :
   [P10] - refactor public init lazy
   [P10] - add fluent api simulation
   [P10] - add fluent api group
   [P10] - add repr html jupyter
   [P10] - unify cli subcommands
   [P10] - add run resume flag
   [P10] - add config wizard
   [P10] - add data subcommands
   [P10] - add display subcommand
   [P10] - standardize exit codes
   [P10] - add api tests

CRITERES DE SUCCES :
- pytest tests/unit/test_api_* tests/unit/test_cli_* passe
- hmp --help liste toutes les sous-commandes
- import hydromodpy as hmp puis hmp.open("~/hydromodpy") fonctionne

SIGNALISATION : PHASE_P10_DONE
'
run_phase "P10" "API Python + CLI unified" "$P10_PROMPT"

# ---------- P11 : Frontend hooks ----------
P11_PROMPT='
OBJECTIF : exposer hooks frontend (JSON Schema + annotations), SANS serveur.

SPEC A LIRE : architecture_cible/11_frontend_ready.md (IGNORER sections FastAPI)

TACHES :

1. Creer hydromodpy/schema/ :
   - export.py : fonction export_full_schema(output_dir) ecrit :
       schema/config.json : JSON Schema complet de HydroModPyConfig.
       schema/config_meta.json : metadonnees (sections TOML, ordre, groupes UI).
       schema/field_validators.json : mapping field_path -> validator_type.
   - Utilise pydantic.TypeAdapter(Model).json_schema().

2. Partial field validator :
   - hydromodpy/schema/partial_validator.py.
   - Fonction validate_field(path, value, context) -> ValidationResult
     avec {valid, error, warnings, dependent_fields_affected}.
   - Objectif latence : < 50ms.

3. CLI :
   - hmp schema export [--output schema/]
   - hmp schema validate-field <path> <value> [--context config.toml]

4. Documentation :
   - docs/developers/frontend_hooks.md : comment consommer le schema
     depuis Streamlit, Angular, React (code snippets).
   - docs/examples/streamlit_app.py : exemple minimal d une app Streamlit
     qui charge schema/config.json et genere un formulaire.
     PAS d ajout aux dependencies : juste fichier exemple.

5. INTERDICTIONS :
   - NE PAS ajouter FastAPI, uvicorn, websockets, httpx server.
   - Le serveur reste strictement externe au projet.

6. Tests :
   - tests/unit/test_schema_export.py
   - tests/unit/test_partial_validator.py (latence < 100ms)
   - tests/unit/test_schema_annotations.py (widget_type, unit, etc. presents).

COMMITS attendus :
   [P11] - add schema export module
   [P11] - add partial validator
   [P11] - add schema cli
   [P11] - add frontend hooks docs
   [P11] - add streamlit example
   [P11] - add schema tests

CRITERES DE SUCCES :
- pytest tests/unit/test_schema_* tests/unit/test_partial_validator.py passe
- hmp schema export --output /tmp/schema/ produit 3 fichiers json valides
- python docs/examples/streamlit_app.py ne crash pas au demarrage

SIGNALISATION : PHASE_P11_DONE
'
run_phase "P11" "Frontend hooks: JSON Schema + field validator (no server)" "$P11_PROMPT"

# ---------- P12 : Tests ----------
P12_PROMPT='
OBJECTIF : suite de tests compacte, rapide, maintenable.

SPEC A LIRE : architecture_cible/09_tests_ideaux.md

TACHES :

1. Audit tests existants (Agent Explore) :
   - Compter tests par categorie (unit/regression/validation).
   - Identifier les redondances (meme scenario 5x).
   - Identifier les tests trop lents pour leur valeur.
   - Identifier les tests d implementation (cassent a chaque refacto).

2. Strategie cible :
   - unit/ 80% : < 2s chacun, isolation, pas d IO reel.
   - regression/ 15% : interfaces entre composants, fixtures.
   - validation/ 5% : benchmarks analytiques (Dupuit, Theis, Hantush).

3. Nettoyage agressif (commits par categorie) :
   - Supprimer tests de code mort (cross-check avec P13 cleanup preview).
   - Fusionner tests redondants via parametrize.
   - Supprimer tests d implementation non-pertinents.

4. Golden files :
   - Verifier determinisme cross-platform (float precision, endianness).
   - Preferer numpy.testing.assert_allclose avec rtol documentee.
   - Documenter le process update-goldens dans tests/README.md.

5. conftest.py :
   - Fixtures bien scopees (session/module/function).
   - tmp_workspace fixture (tmp_path + hmp init).
   - minimal_config fixture (Pydantic pret a l emploi).
   - Retirer les fixtures mortes.

6. Markers clairs : regression, validation, analytical, steady, transient,
   fast, slow, nwt, mf6, integration, coverage.

7. Documenter CI :
   - .github/workflows/coverage.yml a jour.
   - Tier fast : unit + regression/fast (~5 min).
   - Tier full : unit + regression + validation (~30 min).

8. Objectif chiffre : -30% a -50% de lignes de code tests, couverture
   preservee. Verifier avec coverage report avant/apres.

COMMITS attendus :
   [P12] - remove dead code tests
   [P12] - merge redundant unit tests
   [P12] - remove obsolete regression tests
   [P12] - parametrize solver tests
   [P12] - improve conftest fixtures
   [P12] - document golden process
   [P12] - update ci workflow
   [P12] - tests cleanup

CRITERES DE SUCCES :
- pytest tests/unit/ -q passe (rapide, < 60s)
- pytest tests/regression/fast -q passe (< 5 min)
- Couverture >= baseline (measure avant/apres)

SIGNALISATION : PHASE_P12_DONE
'
run_phase "P12" "Tests: compact + maintainable" "$P12_PROMPT"

# ---------- P13 : Cleanup final ----------
P13_PROMPT='
OBJECTIF : suppression code mort, renommages finaux, doc a jour.

SPECS A LIRE :
- architecture_cible/13_coherence_globale.md
- architecture_cible/14_plan_migration.md
- audit_code/11_synthese_finale.md (pour la liste des renommages consensuels)

TACHES :

1. Dead code (Agent Explore) :
   - Imports inutilises (ruff-check simule manuellement, ou simple grep).
   - Fonctions jamais appelees (cross-ref dans le codebase).
   - Classes avec un seul heritier inutile.
   - Branches unreachable.
   - Fichiers .py jamais importes.
   - Supprimer en petits commits par categorie.

2. Renommages finaux :
   - Verifier le tableau audit_code/11_synthese_finale.md section 8.
   - Appliquer ceux qui sont consensuels ET sans breakage.
   - Garder des alias deprecies sur l API publique (hmp.*) avec
     DeprecationWarning pour 1 release.

3. Supprimer les shims de retrocompatibilite :
   - core/backends/__init__.py shim ajoute en P05.
   - Tout shim ajoute dans les phases precedentes.
   - Commits atomiques par shim.

4. Documentation :
   - CLAUDE.md : mettre a jour la section "Architecture" (refleter etat final).
   - README.md : verifier exemple "getting started".
   - docs/developers/ : documenter les 10 patterns principaux :
     Protocol Solver, Pipeline Step, Figure, Delineation Backend,
     Data Manager, Config Annotated (pint + rich), Calibration Adapter,
     Objective, Metric, Figure Protocol.

5. Examples :
   - Creer examples/getting_started/ minimal :
     project.toml, run.toml, run_sim.py (3 fichiers, commente).
   - Verifier que examples/projects/01_canut/ marche sur nouvelle API
     (update ses TOML si besoin).
   - Supprimer examples obsoletes (examples_legacy/ restant).

6. CHANGELOG.md a la racine du repo :
   - Sections Breaking Changes, Renommages, Nouvelles Fonctionnalites.
   - Comment migrer un ancien TOML (quick guide).

7. Tests finaux complets :
   - pytest tests/unit/ tests/regression/fast/ -v
   - hmp --help, hmp run exemple minimal, hmp calibrate exemple minimal.

COMMITS attendus (15-25 petits) :
   [P13] - remove unused imports
   [P13] - remove dead functions
   [P13] - remove unreachable code
   [P13] - remove orphan files
   [P13] - apply final renames
   [P13] - add deprecation aliases
   [P13] - remove backends compat shim
   [P13] - remove other compat shims
   [P13] - update claude md
   [P13] - refresh readme
   [P13] - document patterns
   [P13] - add getting started example
   [P13] - update canut example
   [P13] - add changelog
   [P13] - delete remaining legacy

CRITERES DE SUCCES :
- pytest tests/unit/ tests/regression/fast/ -q passe
- hmp run examples/getting_started/run.toml termine un run court
- CHANGELOG.md existe a la racine
- CLAUDE.md Architecture section reflete la nouvelle structure

SIGNALISATION : PHASE_P13_DONE
'
run_phase "P13" "Cleanup: dead code + renames + docs" "$P13_PROMPT"

# ===============================================================
# RECAP FINAL
# ===============================================================
log ""
log "================================================================"
log "  MIGRATION TERMINEE"
log "  End    : $(date '+%Y-%m-%d %H:%M:%S')"
log "  Branch : $(git -C "$PROJECT" rev-parse --abbrev-ref HEAD)"
log "  HEAD   : $(git -C "$PROJECT" rev-parse --short HEAD)"
log "================================================================"
show_status
notify "Migration complete"
