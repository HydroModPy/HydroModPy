#!/usr/bin/env bash
# run_migration_P01_foundations.sh — Phase P01 : Fondations : exceptions typées, field_registry, canonical_json, renommages P0
# Usage : ./run_migration_P01_foundations.sh   (tmux recommandé)
# Estimation : 24h Claude Code

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_lib.sh"

PHASE_NAME="P01_foundations"
BRANCH="migration/P01-foundations"

log ""
log "================================================================"
log "  MIGRATION HYDROMODPY — $PHASE_NAME"
log "  Début   : $(date '+%Y-%m-%d %H:%M:%S')"
log "  Branche : $BRANCH"
log "  Spec    : architecture_cible/14_plan_migration.md §6"
log "  Estim   : 24h"
log "================================================================"

prepare_branch "$BRANCH"

PROMPT=$(cat <<'PROMPT_EOF'
Tu exécutes la phase P01 du plan de migration HydroModPy.

PROJET : /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev
BRANCHE COURANTE : migration/P01-foundations (déjà créée)
PLAN DE MIGRATION : architecture_cible/14_plan_migration.md — section §6

Lis la section §6 du plan de migration (objectif, fichiers, tests, critère de
succès, prompt détaillé). Le prompt détaillé contenu dans cette section est
ta feuille de route officielle : suis-le à la lettre.

LECTURE OBLIGATOIRE avant de commencer :
1. /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev/CLAUDE.md
2. /home/bb/Documents/01_Git_Repository/02-HydroModPy-dev/architecture_cible/14_plan_migration.md (section §6)
3. Les documents sources référencés dans la section §6 du plan
   (typiquement : un document dans architecture_cible/ + un dans audit_code/).

CONTRAINTES GÉNÉRALES :
- Écrire TOUT en français technique.
- Commits atomiques avec messages "[P01] <action>" en anglais.
- NE JAMAIS utiliser --no-verify, --no-gpg-sign.
- NE JAMAIS force-push.
- Tester après chaque étape significative : pytest tests/unit/ -x -q
- Tester en mode headless : HYDROMODPY_NO_DISPLAY=1 HYDROMODPY_NO_SAVE=1
- En cas d'ambiguïté entre 2 docs architecture_cible/ : 13_coherence_globale.md tranche.
- Si un test existant casse : fixer la cause, ne jamais désactiver.
- Rapporter à la fin : LOC ajoutées, LOC supprimées, tests ajoutés, tests
  cassés (doit être 0), preuves de succès selon critère de la section §6.

CRITÈRE DE SUCCÈS : voir architecture_cible/14_plan_migration.md §6 (sous-section
"Critère de succès"). Tous les tests listés doivent passer.

Commence par lire les documents obligatoires, puis planifie les étapes, puis exécute.
PROMPT_EOF
)

if run_migration "$PHASE_NAME" "$PROMPT"; then
    log "PROMPT OK — validation tests"
    if validate_phase; then
        log "$PHASE_NAME : succès complet"
        log "Merge dans dev-database suggéré :"
        log "    cd $PROJECT && git checkout dev-database && git merge --no-ff $BRANCH"
        notify "$PHASE_NAME complet (validé)"
        exit 0
    else
        log "$PHASE_NAME : prompt OK mais tests KO — intervention manuelle requise"
        exit 2
    fi
else
    log "$PHASE_NAME : échec du prompt après $MAX_RETRIES tentatives"
    exit 1
fi
