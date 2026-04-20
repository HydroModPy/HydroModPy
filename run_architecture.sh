#!/usr/bin/env bash
#
# Conception de l'architecture ideale HydroModPy
# S'appuie sur l'audit (audit_code/) + le code actuel (hydromodpy/, tests/)
# Produit des specifications detaillees + un plan de migration phase
#
# Usage: ./run_architecture.sh
#
set -euo pipefail

PROJECT="/home/bb/Documents/01_Git_Repository/02-HydroModPy-dev"
AUDIT="$PROJECT/audit_code"
OUTPUT="$PROJECT/architecture_cible"
LOG="$OUTPUT/architecture.log"
STDERR_TMP="$OUTPUT/.stderr_last"
MAX_RETRIES=12

mkdir -p "$OUTPUT"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
notify() { notify-send "HydroModPy Architecture" "$*" 2>/dev/null || true; }

compute_wait() {
    local stderr_file="$1"
    local stdout_file="${2:-}"
    local combined=""
    combined+=$(tail -50 "$stderr_file" 2>/dev/null || true)
    combined+=$'\n'
    combined+=$(tail -10 "$stdout_file" 2>/dev/null || true)
    if [[ -z "$combined" ]]; then echo 120; return; fi
    # Quota journalier epuise — parser l'heure de reset depuis le message
    if echo "$combined" | grep -qi "hit your limit\|hit.your.limit"; then
        local now_epoch; now_epoch=$(date +%s)
        # Extraire l'heure de reset (ex: "resets 5am", "resets 12am", "resets 3pm")
        local reset_hour
        reset_hour=$(echo "$combined" | grep -oiP 'resets\s+\K\d+(?=\s*[ap]m)' || echo "")
        local reset_ampm
        reset_ampm=$(echo "$combined" | grep -oiP 'resets\s+\d+\K[ap]m' || echo "am")
        if [[ -n "$reset_hour" ]]; then
            # Convertir en 24h
            if [[ "$reset_ampm" == "pm" ]] && [[ "$reset_hour" -ne 12 ]]; then
                reset_hour=$(( reset_hour + 12 ))
            elif [[ "$reset_ampm" == "am" ]] && [[ "$reset_hour" -eq 12 ]]; then
                reset_hour=0
            fi
            # Calculer le prochain reset (aujourd'hui ou demain)
            local reset_epoch
            reset_epoch=$(date -d "today ${reset_hour}:05" +%s 2>/dev/null || echo 0)
            if [[ "$reset_epoch" -le "$now_epoch" ]]; then
                reset_epoch=$(date -d "tomorrow ${reset_hour}:05" +%s 2>/dev/null || echo 0)
            fi
            local wait_until=$(( reset_epoch - now_epoch ))
            if [[ "$wait_until" -lt 60 ]]; then wait_until=120; fi
            echo "$wait_until"
        else
            # Pas d'heure trouvee, attente courte (le quota est peut-etre deja reset)
            echo 300
        fi
        return
    fi
    local retry_seconds
    retry_seconds=$(echo "$combined" | grep -oiP 'retry.{0,5}after.{0,5}\K\d+' | head -1 || echo "")
    if [[ -n "$retry_seconds" ]] && [[ "$retry_seconds" -gt 0 ]]; then echo $(( retry_seconds + 60 )); return; fi
    if echo "$combined" | grep -qi "rate.limit\|429\|overloaded\|too many\|capacity"; then echo 1200; return; fi
    if echo "$combined" | grep -qi "server.error\|500\|502\|503\|connection\|timeout"; then echo 180; return; fi
    echo 120
}

run_phase() {
    local name="$1"
    local prompt="$2"
    local outfile="$OUTPUT/${name}.md"
    local attempt=1
    local backoff_multiplier=1

    if [[ -f "$outfile" ]] && [[ -s "$outfile" ]]; then
        local existing_lines
        existing_lines=$(wc -l < "$outfile")
        if [[ "$existing_lines" -gt 20 ]]; then
            log "SKIP  $name (deja complete: $existing_lines lignes)"
            return 0
        fi
    fi

    while [[ $attempt -le $MAX_RETRIES ]]; do
        log "START $name (tentative $attempt/$MAX_RETRIES)"
        local start_time
        start_time=$(date +%s)

        set +e
        claude -p "$prompt" \
            --permission-mode bypassPermissions \
            --allowedTools "Read Glob Grep Bash Write" \
            > "$OUTPUT/.stdout_last" \
            2> "$STDERR_TMP"
        local rc=$?
        set -e

        local elapsed=$(( $(date +%s) - start_time ))

        if [[ -f "$outfile" ]] && [[ -s "$outfile" ]]; then
            local lines
            lines=$(wc -l < "$outfile")
            if [[ "$lines" -gt 20 ]]; then
                log "DONE  $name ($lines lignes, ${elapsed}s) -> $outfile"
                notify "$name termine ($lines lignes)"
                return 0
            fi
        fi

        local wait_time
        wait_time=$(compute_wait "$STDERR_TMP" "$OUTPUT/.stdout_last")
        local err_summary
        err_summary=$(cat "$OUTPUT/.stdout_last" 2>/dev/null | head -1 || true)
        if [[ -z "$err_summary" ]]; then
            err_summary=$(tail -3 "$STDERR_TMP" 2>/dev/null | grep -i "error\|limit\|fail" | tail -1 || echo "exit code $rc")
        fi
        log "FAIL  $name (rc=$rc, ${elapsed}s): $err_summary"

        # Quota journalier : attente directe sans backoff
        if echo "$err_summary" | grep -qi "hit your limit\|hit.your.limit"; then
            log "QUOTA JOURNALIER EPUISE — attente jusqu'au reset"
            local wait_h=$(( wait_time / 3600 )); local wait_m=$(( (wait_time % 3600) / 60 ))
            log "      Pause: ${wait_h}h${wait_m}m — resume: $(date -d "+${wait_time} seconds" '+%Y-%m-%d %H:%M')"
            sleep "$wait_time"
            backoff_multiplier=1
            attempt=$((attempt + 1))
            continue
        fi

        wait_time=$(( wait_time * backoff_multiplier ))
        if [[ "$wait_time" -gt 18000 ]]; then wait_time=18000; fi

        log "WAIT  $((wait_time / 60))min (backoff x${backoff_multiplier}) -> resume $(date -d "+${wait_time} seconds" '+%H:%M:%S')"
        sleep "$wait_time"

        attempt=$((attempt + 1))
        backoff_multiplier=$(( backoff_multiplier * 2 ))
        if [[ "$backoff_multiplier" -gt 8 ]]; then backoff_multiplier=8; fi
    done

    log "ABANDON $name apres $MAX_RETRIES tentatives"
    notify "ECHEC: $name abandonne"
    return 1
}

# ══════════════════════════════════════════════════════════════
# ETAPE 0 : Rafraichir l'audit si obsolete
# ══════════════════════════════════════════════════════════════

refresh_audit() {
    log ""
    log "================================================================"
    log "  RAFRAICHISSEMENT AUDIT (code modifie depuis le dernier audit)"
    log "================================================================"

    # Archiver les anciens fichiers audit pour forcer la regeneration
    local old_count=0
    old_count=$(find "$AUDIT" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l || echo 0)
    if [[ "$old_count" -gt 0 ]]; then
        local archive_dir="$AUDIT/archive_$(date +%Y%m%d_%H%M%S)"
        mkdir -p "$archive_dir"
        find "$AUDIT" -maxdepth 1 -name "*.md" -exec mv {} "$archive_dir/" \;
        log "Archive de $old_count anciens fichiers audit"
    fi

    # Archiver aussi les anciens fichiers architecture (ils referencent l'ancien audit)
    local old_arch=0
    old_arch=$(find "$OUTPUT" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l || echo 0)
    if [[ "$old_arch" -gt 0 ]]; then
        local arch_archive="$OUTPUT/archive_$(date +%Y%m%d_%H%M%S)"
        mkdir -p "$arch_archive"
        find "$OUTPUT" -maxdepth 1 -name "*.md" -exec mv {} "$arch_archive/" \;
        log "Archive de $old_arch anciens fichiers architecture"
    fi

    # Lancer run_audit.sh
    local audit_script="$PROJECT/run_audit.sh"
    if [[ -x "$audit_script" ]]; then
        log "Lancement de run_audit.sh..."
        bash "$audit_script"
        local audit_rc=$?
        local audit_done
        audit_done=$(find "$AUDIT" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l)
        log "Audit termine: $audit_done fichiers generes (rc=$audit_rc)"
    else
        log "ERREUR: $audit_script introuvable ou non executable"
        exit 1
    fi
}

# Detecter si l'audit est incomplet ou obsolete
AUDIT_NEEDS_RUN=false

# Cas 1 : pas assez de fichiers audit (on attend 11)
audit_count=$(find "$AUDIT" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l)
if [[ "$audit_count" -lt 11 ]]; then
    AUDIT_NEEDS_RUN=true
    log "Audit incomplet ($audit_count/11 fichiers) — lancement necessaire"
fi

# Cas 2 : le code a ete modifie apres le dernier audit
if [[ "$AUDIT_NEEDS_RUN" == "false" ]]; then
    latest_code=$(find "$PROJECT/hydromodpy" -name "*.py" -newer "$AUDIT/01_architecture_globale.md" -print -quit 2>/dev/null || true)
    if [[ -n "$latest_code" ]]; then
        AUDIT_NEEDS_RUN=true
        log "Code modifie apres le dernier audit — rafraichissement necessaire"
    fi
fi

if [[ "$AUDIT_NEEDS_RUN" == "true" ]]; then
    # Ne pas archiver — run_audit.sh skip les phases deja completes
    log "Lancement de run_audit.sh (les phases completes seront skippees)..."
    if [[ -x "$PROJECT/run_audit.sh" ]]; then
        bash "$PROJECT/run_audit.sh"
        audit_count=$(find "$AUDIT" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l)
        log "Audit termine: $audit_count/11 fichiers"
    else
        log "ERREUR: run_audit.sh introuvable"
        exit 1
    fi
else
    log "Audit complet ($audit_count/11) et a jour — skip"
fi

# ══════════════════════════════════════════════════════════════
# PHASES ARCHITECTURE
# ══════════════════════════════════════════════════════════════

log ""
log "================================================================"
log "  ARCHITECTURE CIBLE HYDROMODPY"
log "  Debut   : $(date '+%Y-%m-%d %H:%M:%S')"
log "  Audit   : $AUDIT"
log "  Output  : $OUTPUT"
log "================================================================"

COMMON="
CONTEXTE:
- Le projet HydroModPy est a $PROJECT
- L'audit complet du code existant est dans $AUDIT (11 rapports .md). Lis-les pour comprendre l'etat actuel.
- Le code source est dans $PROJECT/hydromodpy/ et $PROJECT/tests/

INSTRUCTIONS:
- Ecris TOUT en francais technique.
- Ne modifie AUCUN fichier existant. Ecris uniquement dans le fichier de sortie indique.
- Tu concois l'architecture IDEALE, pas un patch de l'existant. Si il faut tout repenser, fais-le.
- Sois CONCRET : noms de fichiers, noms de classes, signatures de methodes, types exacts, schemas SQL, layouts Zarr.
- Chaque specification doit etre implementable directement par un developpeur sans ambiguite.
- Quand tu proposes un design, montre un EXEMPLE DE CODE (squelette Python) de ce a quoi ca ressemblerait.
- Compare avec les meilleures pratiques des projets de reference du domaine.
- Indique pour chaque element : NOUVEAU (n'existe pas) / RENOMME (existe sous un autre nom) / REFACTORE (existe mais doit changer) / CONSERVE (existe et est bien).
"

# ─────────────────────────────────────────────────────────────
# PHASE 1 : Structure de packages ideale
# ─────────────────────────────────────────────────────────────
run_phase "01_structure_packages" "
Tu es un ARCHITECTE LOGICIEL SENIOR qui a concu la structure de projets comme scikit-learn, xarray, et FloPy. Tu dois concevoir la structure de packages IDEALE pour HydroModPy.

Lis l'audit d'architecture ($AUDIT/01_architecture_globale.md) et le code actuel (tous les __init__.py, la structure des repertoires).

Concois la structure IDEALE en respectant ces principes:
- Chaque package a UNE responsabilite claire
- Pas de dependances circulaires (dessine le graphe de dependances autorise)
- Un nouveau developpeur comprend la structure en 5 minutes
- L'ajout d'un solveur, d'un type de donnees, ou d'un format d'export ne touche qu'un seul package
- Le nommage suit les conventions Python scientifique (pas de noms generiques comme 'common', 'utils', 'helpers')

Produis:
1. ARBRE COMPLET des packages/modules avec description 1 ligne de chaque fichier
2. GRAPHE DE DEPENDANCES autorise (qui peut importer quoi, en ASCII art)
3. API PUBLIQUE : ce que 'import hydromodpy as hmp' expose, avec exemples d'utilisation
4. POINTS D'ENTREE CLI : commandes, sous-commandes, arguments
5. COMPARAISON actuel vs cible : tableau fichier par fichier (actuel -> cible, action: conserver/renommer/deplacer/supprimer/creer)
6. CONVENTIONS : nommage des modules, classes, fichiers de config, tests associes

$COMMON
Ecris le resultat dans: $OUTPUT/01_structure_packages.md
"

# ─────────────────────────────────────────────────────────────
# PHASE 2 : Systeme de configuration Pydantic ideal
# ─────────────────────────────────────────────────────────────
run_phase "02_config_pydantic" "
Tu es un EXPERT PYDANTIC V2 qui a concu des systemes de configuration pour des applications scientifiques (Hydra, dynaconf, OmegaConf). Tu dois concevoir le systeme de configuration IDEAL pour HydroModPy.

Lis l'audit Pydantic ($AUDIT/10_pydantic_models.md, $AUDIT/02_core_config.md) et les fichiers *_config.py actuels.

Concois le systeme IDEAL en respectant:
- TOML comme format utilisateur (lisible par un hydrogeologue non-informaticien)
- Pydantic v2 strict : types precis (Literal, Annotated, Path), validators physiques (K>0, 0<Sy<1)
- Defaults physiquement sensibles pour chaque parametre
- Separation claire : config utilisateur (simplifie) vs config developpeur (tout expose)
- JSON Schema auto-genere pour la validation et l'auto-completion IDE
- Round-trip TOML -> Pydantic -> TOML sans perte

Produis:
1. ARBRE D'HERITAGE des configs : chaque modele, ses champs avec types exacts et defaults
2. MAPPING TOML complet : chaque section TOML -> quel modele Pydantic, avec exemple TOML
3. SQUELETTES DE CODE : pour les 5 modeles les plus importants (code Python complet avec Field, validators, ConfigDict)
4. VALIDATION PHYSIQUE : tableau de chaque parametre avec contrainte physique et message d'erreur
5. SYSTEME DE PROFILS : comment gerer user/dev/expert simplement (pas de ParamLevel si c'est du over-engineering)
6. COMPARAISON : tableau modele actuel -> modele cible, action (conserver/simplifier/fusionner/supprimer)

$COMMON
Ecris le resultat dans: $OUTPUT/02_config_pydantic.md
"

# ─────────────────────────────────────────────────────────────
# PHASE 3 : Contrats de donnees et formats unifies
# ─────────────────────────────────────────────────────────────
run_phase "03_data_contracts" "
Tu es un EXPERT DATA ENGINEERING specialise en donnees geoscientifiques. Tu connais CF-conventions, UGRID, xarray, pandas, Arrow/Parquet, GeoParquet, et les APIs hydrologiques francaises (Hub'Eau, ADES, BRGM). Tu dois concevoir les contrats de donnees IDEAUX pour HydroModPy.

Lis l'audit data ($AUDIT/03_data_layer.md) et le code actuel dans hydromodpy/data/.

Le probleme central : les donnees d'entree et de sortie doivent etre dans des formats STANDARDS, directement utilisables par:
- Un chercheur en IA qui veut entrainer un modele sur les resultats (pandas/xarray/parquet)
- Un hydrogeologue qui veut visualiser dans QGIS
- Un etudiant qui veut comparer des simulations dans un notebook Jupyter
- Un framework de validation (great_expectations, pandera)

Concois:
1. CONTRATS D'ENTREE : pour chaque type de donnee (DEM, geologie, recharge, piezometrie, hydrographie, oceanique, etc.) :
   - Format d'entree accepte (standard: GeoTIFF, GeoParquet, CSV avec schema documente)
   - Schema exact (colonnes, types, unites, CRS)
   - Validation a l'entree (pandera DataFrameSchema ou equivalent)
   - Exemple concret de fichier d'entree

2. CONTRATS DE SORTIE : pour chaque type de resultat :
   - Format de sortie (standard: CF-NetCDF, GeoParquet, Zarr avec metadata)
   - Schema exact
   - Utilisable DIRECTEMENT par xarray.open_dataset() sans adapter custom

3. REPRESENTATION UNIFIEE DES GRILLES : comment stocker de la MEME maniere :
   - Grille reguliere (DIS MODFLOW)
   - Grille non-structuree (DISV/triangles)
   - Pour que la chaine de post-traitement soit UNIQUE quel que soit le type de grille
   - Convention proposee : UGRID ? xarray avec MultiIndex ? Schema Zarr custom ?
   - Squelette de code montrant comment lire/ecrire un champ sur les deux types de grille avec la meme API

4. PATTERN DATA MANAGER : simplification du pattern actuel BaseVariableManager
   - Interface minimale qu'un manager doit implementer
   - Exemple de code pour ajouter un nouveau type de donnees en 20 lignes

5. CACHE ET REGISTRE : design du cache de donnees (DuckDB ou autre)
   - Schema exact des tables
   - Invalidation
   - Requetes types

$COMMON
Ecris le resultat dans: $OUTPUT/03_data_contracts.md
"

# ─────────────────────────────────────────────────────────────
# PHASE 4 : Stockage DuckDB + Zarr ideal
# ─────────────────────────────────────────────────────────────
run_phase "04_storage_ideal" "
Tu es un EXPERT EN DATA LAKEHOUSE et STOCKAGE SCIENTIFIQUE. Tu connais DuckDB, Zarr, Parquet, Delta Lake, Iceberg, et tu as concu des schemas de bases de donnees pour des plateformes de simulation (comme Pangeo, ESGF, Copernicus CDS). Tu dois concevoir le systeme de stockage IDEAL pour HydroModPy.

Lis l'audit storage ($AUDIT/07_results_storage.md) et le code actuel dans hydromodpy/results/.

L'objectif : un stockage qui est a la fois :
- PERFORMANT pour ecrire les resultats de simulation (streaming par timestep)
- REQUETABLE par un data scientist (SQL sur DuckDB, filtres, aggregations, pivots)
- INTEROPERABLE (ouvrable par xarray, pandas, QGIS, ParaView sans code custom)
- COMPARATIF (comparer 100 simulations sur un parametre en une requete)
- PORTABLE (exporter/importer des simulations entre machines)
- ROBUSTE (pas de corruption, concurrent-safe, migrations de schema)

Concois:
1. SCHEMA DUCKDB COMPLET :
   - Chaque table avec CREATE TABLE exact (colonnes, types, PKs, FKs, indexes, contraintes)
   - Pourquoi chaque table existe (pas de table inutile)
   - Requetes SQL d'exemple pour les cas d'usage typiques :
     * Trouver la meilleure simulation par NSE
     * Comparer K et NSE sur 200 simulations
     * Exporter les series temporelles d'une station
     * Dataset pour ML : (params, metrics) en DataFrame
   - Mecanisme de migration de schema (version table + scripts ALTER)

2. LAYOUT ZARR :
   - Structure exacte des groupes et arrays
   - Chunking optimal justifie (quels acces sont prioritaires ?)
   - Metadata CF obligatoires sur chaque array
   - Comment le meme layout fonctionne pour DIS et DISV (representation unifiee)
   - Compression : quel codec, quel level, pourquoi

3. API PYTHON du store :
   - Interface complete de SimulationCatalog (toutes les methodes avec signatures)
   - Exemples d'utilisation en notebook Jupyter
   - Comment un chercheur ML accede aux donnees :
     catalog.to_dataframe(params=['K','Sy'], metrics=['nse','kge'])
     catalog.to_xarray(sim_id, variables=['head','concentration'])

4. EXPORT/IMPORT :
   - Format du package portable (.hmp ou mieux)
   - Versionning du format
   - Partial export (juste les metadata, ou metadata + 1 variable)

$COMMON
Ecris le resultat dans: $OUTPUT/04_storage_ideal.md
"

# ─────────────────────────────────────────────────────────────
# PHASE 5 : Contrats d'interface solveur (plug-and-play)
# ─────────────────────────────────────────────────────────────
run_phase "05_solver_contracts" "
Tu es un EXPERT EN DESIGN D'INTERFACES et ARCHITECTURE PLUGIN. Tu as concu des systemes extensibles comme les estimators scikit-learn, les backends Keras, ou les drivers de base de donnees SQLAlchemy. Tu dois concevoir les contrats d'interface IDEAUX pour les solveurs HydroModPy.

Lis l'audit solver ($AUDIT/05_process_solver.md, $AUDIT/06_simulation_engine.md) et le code actuel dans hydromodpy/solver/, hydromodpy/simulation/adapters/.

L'objectif : ajouter un nouveau solveur (ex: FEFLOW, HYDRUS, ParFlow) en implementant UNIQUEMENT des interfaces clairement definies, sans toucher au reste du code. Le solveur s'integre et toute la chaine fonctionne : config -> run -> extraction -> post-traitement -> figures.

Concois:
1. PROTOCOL SOLVEUR : l'interface exacte qu'un solveur doit implementer
   - Code Python complet du Protocol (structural subtyping, pas ABC)
   - Chaque methode avec docstring, signature exacte, types de retour
   - Separation : setup() / build() / run() / extract() / cleanup()
   - Gestion des erreurs : que retourner si le solveur diverge ?

2. PROTOCOL PROCESSUS : l'interface pour definir un processus physique
   - Flow, Transport, Particles : quelles methodes, quels inputs/outputs
   - Comment un solveur declare quels processus il supporte

3. REGISTRE DE SOLVEURS :
   - Comment enregistrer un nouveau solveur (decorator ? entry_point ? config ?)
   - Auto-decouverte des solveurs installes
   - Fallback si un solveur n'est pas disponible

4. CONTRAT D'EXTRACTION : l'interface pour extraire les resultats
   - Meme schema de sortie quel que soit le solveur (la grille est unifiee)
   - Champs obligatoires vs optionnels
   - Comment gerer les differences (ex: MODFLOW a des budgets par face, Boussinesq non)

5. EXEMPLE COMPLET : squelette d'un nouveau solveur fictif 'MySolver' en ~100 lignes
   - Montre comment implementer les Protocols
   - Montre comment s'enregistrer
   - Montre que la config TOML, les figures, et les exports fonctionnent automatiquement

6. COMPARAISON SOLVEURS : tableau des capacites par solveur actuel et ce que le nouveau design permettrait d'ajouter facilement

$COMMON
Ecris le resultat dans: $OUTPUT/05_solver_contracts.md
"

# ─────────────────────────────────────────────────────────────
# PHASE 6 : Pipeline d'execution et orchestration
# ─────────────────────────────────────────────────────────────
run_phase "06_pipeline_execution" "
Tu es un EXPERT EN ORCHESTRATION DE WORKFLOWS (Prefect, Dagster, Luigi) et en PIPELINES SCIENTIFIQUES (Snakemake, Nextflow). Tu dois concevoir le pipeline d'execution IDEAL pour HydroModPy.

Lis l'audit simulation ($AUDIT/06_simulation_engine.md) et le code actuel dans hydromodpy/simulation/, hydromodpy/workflow/.

L'objectif : un pipeline lineaire, reproductible, avec des points de reprise, qui gere aussi bien une simulation unique qu'un batch de 1000 simulations pour de la calibration ou du sensitivity analysis.

Concois:
1. PIPELINE STEPS : chaque etape avec inputs/outputs types
   - Config -> Validation -> DataLoad -> MeshBuild -> SolverSetup -> Run -> Extract -> Derive -> Aggregate -> Export -> Display
   - Chaque step est independant et testable unitairement
   - Diagramme de sequence complet

2. REPRODUCTIBILITE : comment garantir qu'une simulation est reproductible
   - Hashing de la config + des inputs -> run_id deterministe
   - Lockfile des versions de packages
   - Provenance complete

3. BATCH ET CALIBRATION :
   - Comment lancer N simulations avec des parametres differents
   - Interface pour un optimiseur externe (scipy.optimize, optuna, PEST)
   - Parallelisation (multiprocessing, dask, ou simple boucle ?)

4. GESTION D'ERREURS ET REPRISE :
   - Que se passe-t-il si ca crash au step 6/10 ?
   - Checkpointing : peut-on reprendre a partir du dernier step reussi ?
   - Logs structures (pas juste print)

5. CONTEXT MANAGER ideal : cycle de vie complet de Simulation
   - Code squelette avec __enter__/__exit__
   - Combien de responsabilites ? (1 seule idealement)

$COMMON
Ecris le resultat dans: $OUTPUT/06_pipeline_execution.md
"

# ─────────────────────────────────────────────────────────────
# PHASE 7 : Calibration, sensitivity analysis, optimisation
# ─────────────────────────────────────────────────────────────
run_phase "07_calibration" "
Tu es un EXPERT EN CALIBRATION DE MODELES HYDROGEOLOGIQUES et OPTIMISATION. Tu connais PEST/PEST++, OSTRICH, scipy.optimize, optuna, CMA-ES, les methodes bayesiennes (DREAM, emcee), et les frameworks de sensitivity analysis (SALib). Tu as calibre des modeles MODFLOW en production. Tu dois concevoir l'architecture de calibration IDEALE pour HydroModPy.

Lis l'audit ($AUDIT/05_process_solver.md, $AUDIT/06_simulation_engine.md) et le code actuel dans hydromodpy/analysis/calibration/.

L'objectif : un systeme de calibration qui soit :
- MODULAIRE : n'importe quel optimiseur (scipy, optuna, PEST, CMA-ES, custom) s'integre via un contrat simple
- EFFICIENT : ne relance pas tout a chaque iteration (cache des etapes couteuses, warm start)
- TRACABLE : chaque iteration est stockee dans le catalog (parametres testes, metriques, convergence)
- ANALYSABLE : un data scientist peut charger l'historique de calibration comme un DataFrame pour du ML

Concois:
1. ARCHITECTURE CALIBRATION :
   - Separation claire : objectif (quoi optimiser) / optimiseur (comment optimiser) / evaluateur (comment mesurer)
   - Protocol Optimizer : interface qu'un optimiseur doit implementer (ask/tell pattern comme optuna)
   - Protocol Objective : interface pour definir la fonction cout (multi-objectif supporte)
   - Comment le CalibrationEngine orchestre le tout
   - Diagramme de sequence d'une calibration complete

2. PARAMETRES CALIBRABLES :
   - Comment declarer qu'un parametre Pydantic est calibrable (bornes, distribution prior, log-transform)
   - Annotation dans le TOML : [calibration.parameters] avec bounds, transform, initial
   - Mapping parametres continus -> parametres physiques discrets (zones geologiques)

3. METRIQUES ET OBJECTIFS :
   - Metriques standard : NSE, KGE, RMSE, log-NSE, bias — formules exactes
   - Multi-site : comment combiner les metriques de plusieurs stations
   - Multi-objectif : Pareto front, weighted sum, epsilon-constraint

4. STOCKAGE DES ITERATIONS :
   - Schema DuckDB pour calibration_sessions et calibration_iterations
   - Comment requeter : 'donne-moi les 10 meilleures iterations triees par NSE'
   - Export DataFrame pour analyse ML : params + metrics en colonnes
   - Visualisation : convergence plot, parameter evolution, dotty plots, parallel coordinates

5. SENSITIVITY ANALYSIS :
   - Integration SALib (Sobol, Morris, FAST)
   - Comment generer les echantillons et stocker les resultats
   - Lien avec la calibration (screening avant calibration)

6. WARM START ET REPRISE :
   - Comment reprendre une calibration interrompue
   - Cache des simulations deja evaluees (meme parametres = meme resultat)
   - Parallelisation des evaluations (N simulations en parallele)

7. INTERFACE UTILISATEUR :
   - TOML : section [calibration] avec parametres, objectifs, methode
   - CLI : hmp calibrate config.toml — avec progress bar, meilleur score courant
   - API Python : hmp.calibrate(config, method='cma-es', max_iter=200)

$COMMON
Ecris le resultat dans: $OUTPUT/07_calibration.md
"

# ─────────────────────────────────────────────────────────────
# PHASE 8 : Post-traitement et figures solver-agnostiques
# ─────────────────────────────────────────────────────────────
run_phase "08_postprocess_display" "
Tu es un EXPERT EN VISUALISATION SCIENTIFIQUE specialise en hydrogeologie. Tu connais matplotlib, PyVista, cartopy, plotly, et les conventions de visualisation dans les publications scientifiques (Water Resources Research, Journal of Hydrology). Tu dois concevoir le systeme de post-traitement et visualisation IDEAL pour HydroModPy.

Lis l'audit display ($AUDIT/08_analysis_display.md) et le code actuel dans hydromodpy/analysis/.

L'objectif : des figures de qualite publication qui fonctionnent IDENTIQUEMENT quel que soit le solveur (Boussinesq, MODFLOW-NWT, MODFLOW 6), grace a la representation unifiee des resultats.

Concois:
1. CATALOGUE DE FIGURES : chaque type de figure avec :
   - Nom, description, inputs requis (quels champs du store)
   - Fonctionne sur DIS et DISV ? (oui obligatoirement grace a la grille unifiee)
   - Exemple de la figure attendue (description textuelle)
   - Figures standard hydrogeologie : carte piezometrique, coupe, hydrogramme, bilan, carte de recharge, zones de suintement, trajectoires de particules, carte de concentration

2. INTERFACE DE FIGURE :
   - Protocol/ABC qu'une figure doit implementer
   - render(sim, **kwargs) -> Figure
   - Separation donnees / rendu (les donnees viennent du store, pas du solveur)
   - Comment ajouter une nouvelle figure en 30 lignes

3. COMPARAISON MULTI-SIMULATIONS :
   - Comment afficher 2 simulations cote a cote
   - Difference maps (sim_a - sim_b)
   - Scatter plot parametres vs metriques sur N simulations

4. POST-TRAITEMENT NUMERIQUE :
   - Calculs derives : watertable, depth, seepage, flux, bilan
   - Metriques : NSE, KGE, RMSE, bias, correlation — formules exactes, implementation
   - Ou vivent ces calculs (dans results/ pas dans analysis/) ?

5. EXPORT DES FIGURES :
   - Formats : PNG, SVG, PDF
   - Resolution et taille pour publication
   - Batch export de toutes les figures d'une simulation

6. MODE HEADLESS :
   - Design propre sans variable d'environnement magique
   - Configuration dans le TOML, pas dans l'OS

$COMMON
Ecris le resultat dans: $OUTPUT/08_postprocess_display.md
"

# ─────────────────────────────────────────────────────────────
# PHASE 8 : Architecture de tests ideale
# ─────────────────────────────────────────────────────────────
run_phase "09_tests_ideaux" "
Tu es un EXPERT QA pour logiciels de simulation numerique. Tu connais pytest, hypothesis, les strategies MMS (Method of Manufactured Solutions), et tu as mis en place des suites de test pour des codes comme OpenFOAM, TOUGH2, FEFLOW. Tu dois concevoir la suite de tests IDEALE pour HydroModPy.

Lis l'audit tests ($AUDIT/09_tests_audit.md) et les tests actuels dans tests/.

L'objectif : une suite de tests COMPACTE, RAPIDE, et FIABLE qui donne confiance sans etre un fardeau de maintenance.

Concois:
1. STRATEGIE : pyramide de tests avec ratio ideal
   - Unit (80%) : <2s chacun, pas d'I/O, pas de solveur, testent la logique
   - Integration (15%) : testent les interfaces entre composants, fixture-based
   - Validation (5%) : benchmarks analytiques, lents, optionnels en CI rapide

2. TESTS UNITAIRES CRITIQUES : les 20 tests unitaires les plus importants
   - Pour chaque : quoi tester, inputs, outputs attendus, fixture necessaire
   - Couvrir : config validation, grid unified, property mapping, metric calculation

3. TESTS D'INTEGRATION : les 5 scenarios d'integration essentiels
   - Config -> Run -> Results (pour chaque solveur, en micro)
   - Data loading pipeline
   - Export round-trip

4. BENCHMARKS ANALYTIQUES : les 3 cas de validation obligatoires
   - Solution analytique, critere de convergence, tolerance

5. GOLDEN FILES : simplification
   - Faut-il garder les golden files ou les remplacer par des assertions numeriques ?
   - Si on les garde : format, process de mise a jour, determinisme cross-platform

6. INFRASTRUCTURE :
   - conftest.py ideal (fixtures, markers, parametrize)
   - Organisation des repertoires
   - CI pipeline (fast / full, quand lancer quoi)
   - Comment supprimer 50% des tests actuels sans perdre de confiance

$COMMON
Ecris le resultat dans: $OUTPUT/09_tests_ideaux.md
"

# ─────────────────────────────────────────────────────────────
# PHASE 9 : UX — CLI, API Python, TOML, import hydromodpy as hmp
# ─────────────────────────────────────────────────────────────
run_phase "10_ux_cli_api" "
Tu es un EXPERT UX DEVELOPER TOOLS et DESIGN D'API PYTHON. Tu as concu des CLI comme poetry, ruff, httpie et des API Python comme pandas, xarray, scikit-learn. Tu sais ce qui fait qu'un outil scientifique est AGREABLE a utiliser vs frustrant. Tu dois concevoir l'experience utilisateur IDEALE de HydroModPy.

Lis l'audit architecture ($AUDIT/01_architecture_globale.md), le code actuel de hydromodpy/__init__.py, hydromodpy/__main__.py, hydromodpy/project.py, et les specs deja produites dans $OUTPUT/ (01 a 08).

L'objectif : un utilisateur (hydrogeologue, etudiant, data scientist) doit pouvoir utiliser HydroModPy sans lire le code source. L'API doit etre intuitive, decouvrable, et coherente.

Concois:
1. API PYTHON PUBLIQUE ('import hydromodpy as hmp') :
   - Tout ce que hmp.* expose, organise par domaine
   - Exemples de sessions interactives completes (notebook Jupyter) :
     * Ouvrir un workspace, lister les simulations, charger des resultats
     * Creer une simulation from scratch en Python (sans TOML)
     * Comparer deux simulations, exporter les differences
     * Charger les resultats dans un DataFrame pour du ML
   - Nommage : hmp.open(), hmp.run(), hmp.Simulation, hmp.Catalog — chaque nom justifie
   - Auto-completion IDE : __all__, type hints, docstrings format numpy
   - Conventions : ce qui retourne un DataFrame, ce qui retourne un xarray, ce qui retourne un Path

2. CLI ('hmp') :
   - Arbre complet des commandes et sous-commandes avec exemples :
     hmp init, hmp new, hmp run, hmp list, hmp show, hmp compare, hmp export, hmp config, hmp test
   - Chaque commande : arguments, options, defaults, output attendu
   - Progress bars (tqdm/rich), couleurs, messages d'erreur humains
   - Tab-completion (bash/fish/zsh)
   - Exit codes standardises
   - Compare avec les CLI de reference : poetry, dvc, mlflow, ruff

3. CONFIGURATION TOML user-friendly :
   - Un TOML minimal qui marche (5 lignes pour une simulation basique)
   - Un TOML complet avec commentaires explicatifs en francais
   - Nommage des sections et cles : ce qu'un hydrogeologue s'attend a voir
   - Erreurs de config : messages clairs avec suggestion de correction (comme ruff)
   - Commande 'hmp config check' qui valide le TOML avant de lancer
   - Commande 'hmp config wizard' interactive pour generer un TOML

4. NOMMAGE DU PROJET ET DES CONCEPTS :
   - 'Project' vs 'Workspace' vs 'Simulation' vs 'Run' — definir chaque concept clairement
   - Glossaire des termes utilises dans l'API et le TOML
   - Coherence : si on dit 'simulation' dans l'API, on dit 'simulation' dans le TOML et le CLI, pas 'run' ou 'project' selon le contexte

5. PROTOTYPAGE INTERACTIF :
   - Comment un chercheur prototype dans un notebook avant de passer en TOML production
   - API fluent : sim.field('head').at(timestep=5).plot() — est-ce un bon pattern ?
   - Repr HTML pour Jupyter (_repr_html_ sur les objets principaux)

$COMMON
Ecris le resultat dans: $OUTPUT/10_ux_cli_api.md
"

# ─────────────────────────────────────────────────────────────
# PHASE 10 : Frontend-ready — branchement Angular/web
# ─────────────────────────────────────────────────────────────
run_phase "11_frontend_ready" "
Tu es un EXPERT FULLSTACK qui a concu des API REST/GraphQL pour des applications scientifiques web (Jupyter Hub, Streamlit, Grafana, Apache Superset). Tu connais FastAPI, Pydantic, JSON Schema, OpenAPI, et Angular. Tu dois concevoir l'architecture qui permet de brancher un frontend Angular sur HydroModPy.

Lis les specs deja produites dans $OUTPUT/ (01 a 09), notamment la config Pydantic (02) et l'API Python (09).

L'objectif : une interface Angular peut se brancher sur HydroModPy pour :
- Editer une config TOML avec validation dynamique en temps reel (via JSON Schema genere depuis Pydantic)
- Lancer des simulations et suivre la progression
- Naviguer dans les resultats (catalog, simulations, figures)
- Comparer des simulations interactivement

Concois:
1. COUCHE API REST/HTTP (FastAPI) :
   - Endpoints complets avec methode, path, request body, response schema
   - POST /simulations/run — lancer une simulation
   - GET /simulations — lister avec filtres
   - GET /simulations/{id}/fields/{name}?timestep=5 — champ spatial en GeoJSON ou array
   - GET /simulations/{id}/timeseries/{station} — serie temporelle en JSON
   - GET /config/schema — JSON Schema Pydantic pour le formulaire Angular
   - POST /config/validate — validation dynamique d'un TOML partiel
   - POST /config/validate-field — validation d'UN SEUL champ (1 modif = 1 requete, reponse <50ms)
   - GET /calibration/{session_id}/progress — progression calibration en temps reel
   - WebSocket /simulations/{id}/progress — progression simulation en temps reel
   - GET /calibration/{session_id}/iterations — historique complet pour plotting frontend
   - Authentification : aucune (local-first) ou token simple

2. VALIDATION CHAMP-PAR-CHAMP (CRITIQUE pour le frontend Angular) :
   - Le frontend envoie UNE modification de valeur a la fois (ex: K passe de 1e-4 a 1e-3)
   - Le backend valide CE champ dans le contexte du modele Pydantic complet
   - Reponse JSON : {valid: bool, error: string|null, warnings: string[], dependent_fields_affected: string[]}
   - Les validators Pydantic cross-field doivent pouvoir s'executer sur un modele PARTIEL
   - Latence cible : <50ms par validation (pas de re-parsing du TOML complet)
   - Comment structurer les modeles Pydantic pour que model_validate sur un champ unique soit possible
   - Pattern : le frontend maintient l'etat complet, envoie le delta, le backend valide le modele mis a jour
   - Exemple concret : l'utilisateur change Sy de 0.1 a 1.5 -> erreur 'Sy doit etre < 1' en temps reel

3. JSON SCHEMA DEPUIS PYDANTIC :
   - Comment generer automatiquement le schema pour chaque section de config
   - Metadata pour le frontend : labels FR, unites, min/max, description, enum values, step (pour les sliders)
   - Annotations Pydantic specifiques (json_schema_extra) pour le frontend :
     * widget_type: 'slider' | 'input' | 'select' | 'checkbox' | 'file'
     * unit: 'm/s', 'm', 'days', etc.
     * display_name_fr: 'Conductivite hydraulique'
     * help_text_fr: 'Valeur typique pour un sable: 1e-4 a 1e-2 m/s'
   - Exemple de schema genere pour la section [flow] avec toutes ces annotations

3. SEPARATION BACKEND / FRONTEND :
   - HydroModPy reste un package Python pur (pas de dependance web)
   - FastAPI est un package OPTIONNEL (hydromodpy[web] ou package separe hydromodpy-api)
   - Le frontend Angular est un repo separe qui consomme l'API
   - Le package Python et l'API HTTP ont exactement la meme semantique

4. STREAMING DES RESULTATS :
   - Comment servir un champ spatial de 100k cellules efficacement (Arrow IPC, MessagePack, ou JSON chunks)
   - Pagination des series temporelles longues
   - Cache HTTP pour les resultats immutables

5. IMPACT SUR L'ARCHITECTURE :
   - Quels changements dans le design des phases precedentes pour rendre le tout frontend-ready ?
   - Les modeles Pydantic doivent-ils changer ? Les noms de champs doivent-ils etre compatible REST ?
   - Le store doit-il exposer des methodes supplementaires ?

$COMMON
Ecris le resultat dans: $OUTPUT/11_frontend_ready.md
"

# ─────────────────────────────────────────────────────────────
# PHASE 11 : Donnees d'entree — repenser la gestion locale/API
# ─────────────────────────────────────────────────────────────
run_phase "12_input_data_rethink" "
Tu es un EXPERT EN GESTION DE DONNEES GEOSCIENTIFIQUES et DATA PIPELINES. Tu connais les APIs hydrologiques francaises (Hub'Eau, ADES, BRGM, Meteo-France, SHOM, data.gouv.fr), les systemes de fichiers scientifiques (THREDDS, OPeNDAP, STAC), et les patterns de cache/registry (intake, fsspec, DVC). Tu dois repenser TOUTE la logique de gestion des donnees d'entree de HydroModPy.

Lis l'audit data ($AUDIT/03_data_layer.md) et le code actuel dans hydromodpy/data/.

Le probleme actuel : les donnees d'entree sont gerees par des dossiers sur le filesystem de l'utilisateur, avec une logique relationnelle maison entre dossiers. C'est fragile, mal documente, et difficile a utiliser.

Concois la solution IDEALE :
1. ARCHITECTURE DATA LAYER :
   - Option A : tout via API (Hub'Eau, BRGM, etc.) avec cache local intelligent
   - Option B : fichiers locaux structures avec registre/catalogue
   - Option C : hybride API-first avec fallback fichiers locaux
   - Pour chaque option : avantages, inconvenients, complexite, robustesse
   - RECOMMANDATION ARGUMENTEE : quelle option choisir et pourquoi

2. SI API-FIRST :
   - Quelles donnees viennent de quelle API (tableau exhaustif)
   - Cache : ou, combien de temps, invalidation, offline mode
   - Rate limiting et resilience reseau
   - Donnees qui N'EXISTENT PAS en API (geologie locale, donnees custom) : comment les integrer

3. SI FICHIERS LOCAUX :
   - Structure de repertoires prescrite (pas libre — convention over configuration)
   - Registre/catalogue des fichiers disponibles (STAC-like ? intake catalog ? simple JSON ?)
   - Validation automatique a l'ajout (format, CRS, emprise, resolution)
   - Comment l'utilisateur ajoute ses propres donnees (drag & drop conceptuel)

4. DONNEES CUSTOM (le cas le plus important) :
   - L'utilisateur a ses propres mesures piezometriques, sa propre geologie, son propre DEM
   - Comment les integrer SIMPLEMENT sans comprendre l'architecture interne
   - Format d'entree standardise (CSV avec header precis ? GeoPackage ? Parquet ?)
   - Commande CLI : hmp data add --type piezometry my_wells.csv
   - Validation et feedback immediat

5. BASE DE DONNEES D'ENTREE vs DOSSIERS :
   - Faut-il un DuckDB pour les donnees d'entree aussi (pas juste les resultats) ?
   - Ou est-ce que des fichiers bien organises + un manifest JSON suffisent ?
   - Risques de corruption, de desynchronisation, de migration
   - Ce que font les autres : SWAT (fichiers texte structures), MODFLOW (fichiers formats fixes), MIKE (base proprietaire)

6. REPRODUCTIBILITE :
   - Comment garantir qu'une simulation utilise les memes donnees 2 ans plus tard
   - Versioning des donnees (hash, timestamp, provenance)
   - Lockfile des sources de donnees (comme poetry.lock mais pour les geodonnees)

$COMMON
Ecris le resultat dans: $OUTPUT/12_input_data_rethink.md
"

# ─────────────────────────────────────────────────────────────
# PHASE 12 : Verification de coherence globale
# ─────────────────────────────────────────────────────────────
run_phase "13_coherence_globale" "
Tu es un ARCHITECTE SYSTEME SENIOR qui doit verifier que toutes les pieces conques dans les phases 01-12 s'emboitent parfaitement. Tu es le gardien de la coherence.

Lis TOUS les documents d'architecture deja produits dans $OUTPUT/ (01 a 12).

Verifie et corrige:
1. COHERENCE DES INTERFACES : les types de retour du solveur (phase 05) correspondent-ils aux inputs du store (phase 04) ? Les contrats de donnees (phase 03) sont-ils compatibles avec le layout Zarr (phase 04) ? Les figures (phase 07) lisent-elles des champs qui existent dans le store ? L'API Python (phase 09) expose-t-elle les bons objets ? L'API REST (phase 10) a-t-elle la meme semantique que l'API Python ?

2. GRILLE UNIFIEE : la representation unifiee proposee en phase 03 est-elle utilisee PARTOUT de la meme maniere (solveurs, store, figures, exports, API REST, frontend) ? Y a-t-il un endroit ou on retomberait dans du code specifique DIS vs DISV ?

3. NOMMAGE GLOBAL : les noms de classes/modules sont-ils coherents entre TOUTES les phases ? Pas de 'SimulationResult' dans une phase et 'RunOutput' dans une autre. Les noms dans le CLI (phase 09), l'API REST (phase 10), l'API Python (phase 09), et le TOML (phase 02) sont-ils IDENTIQUES ?

4. FLUX DE DONNEES COMPLET : trace le chemin d'une donnee de l'entree (CSV/API Hub'Eau via phase 11) jusqu'a la sortie (figure PDF, DataFrame ML, endpoint REST) en passant par TOUS les composants. Chaque transformation est-elle explicite ?

5. CAS D'USAGE VALIDES :
   - Scenario 1 : hydrogeologue lance sa premiere simulation en 5 commandes CLI
   - Scenario 2 : data scientist charge 200 simulations dans un DataFrame pour du ML
   - Scenario 3 : developpeur ajoute un nouveau solveur en 1 journee
   - Scenario 4 : etudiant compare 2 simulations (NWT vs MF6) sur le meme domaine
   - Scenario 5 : frontend Angular affiche les resultats avec validation config temps reel
   - Scenario 6 : utilisateur reprend une simulation de 2 ans depuis le store, regenere des figures
   - Scenario 7 : chercheur exporte ALL d'une simulation en sous-dossiers structures
   - Scenario 8 : utilisateur ajoute ses propres donnees piezometriques custom
   Pour chaque scenario : le design permet-il de le faire simplement ? Si non, que manque-t-il ?

6. DONNEES D'ENTREE (phase 11) vs STORE (phase 04) : les deux systemes de donnees sont-ils coherents ? La provenance trace-t-elle les inputs jusqu'aux sources (API ou fichier local) ?

7. EXPORT STRUCTURE : quand un utilisateur fait 'hmp export --all sim_id /path/output/', la structure de sortie est-elle definie ? Proposer l'arborescence exacte du dossier exporte.

8. RISQUES ET COMPROMIS : quels sont les choix techniques controverses ? Quelles alternatives ont ete ecartees ?

9. TABLEAU DE SYNTHESE : chaque composant (phases 01-12) avec status (coherent / incoherence / a clarifier)

$COMMON
Ecris le resultat dans: $OUTPUT/13_coherence_globale.md
"

# ─────────────────────────────────────────────────────────────
# PHASE 10 : Plan de migration phase
# ─────────────────────────────────────────────────────────────
run_phase "14_plan_migration" "
Tu es un TECH LEAD qui doit transformer l'architecture actuelle de HydroModPy en l'architecture cible conque dans les phases 01-13. Tu dois produire un plan de migration EXECUTABLE, divise en phases independantes, chacune pouvant etre lancee comme un script Claude Code.

Lis TOUS les documents d'architecture ($OUTPUT/ phases 01 a 12) et l'audit ($AUDIT/).

Produis:
1. PHASES DE MIGRATION (ordonnees par dependances) :
   Pour chaque phase :
   - Nom et objectif en 1 ligne
   - Pre-requis (quelles phases doivent etre terminees avant)
   - Fichiers a creer / modifier / supprimer (liste exacte)
   - Tests a ecrire / modifier pour valider la phase
   - Critere de succes (quel test doit passer)
   - Estimation en heures de travail Claude Code
   - Risque de regression (faible/moyen/fort)
   - Peut etre fait en parallele avec quelles autres phases ?

   Phases suggerees (adapte selon le design) :
   P1 - Fondations : grille unifiee, contrats de base, glossaire des concepts
   P2 - Store : nouveau schema DuckDB + Zarr layout (resultats ET entrees)
   P3 - Config : nouveau systeme Pydantic avec JSON Schema pour frontend
   P4 - Data input : nouveau systeme de donnees d'entree (API-first + custom local)
   P5 - Solveurs : nouveaux contrats d'interface, migration des 3 solveurs
   P6 - Pipeline : nouvelle orchestration avec checkpointing
   P7 - Post-traitement : figures solver-agnostiques, metriques
   P8 - API Python : 'import hydromodpy as hmp', API fluent, repr Jupyter
   P9 - CLI : nouvelle interface hmp avec sous-commandes, wizard, completion
   P10 - Export structure : architecture d'export ALL avec sous-dossiers
   P11 - Tests : nouvelle suite compacte, suppression des redondants
   P12 - API REST (optionnel) : FastAPI pour branchement Angular
   P13 - Nettoyage : suppression code mort, renommages finaux, documentation

2. POUR CHAQUE PHASE, un PROMPT CLAUDE CODE pret a l'emploi :
   - Le prompt exact a donner a Claude Code pour executer cette phase de migration
   - Incluant : contexte complet, specs de reference (quel document $OUTPUT/ lire), fichiers source a modifier, tests a lancer apres
   - Format : pret a copier-coller dans 'claude -p \"...\"'
   - Chaque prompt doit etre AUTONOME (ne depend pas de la conversation precedente)

3. SCRIPT BASH RUNNER : un script run_migration_P01.sh ... run_migration_P13.sh
   - Chaque script lance le prompt claude -p correspondant
   - Avec gestion d'erreur et retry (comme run_audit.sh)
   - L'utilisateur peut lancer les phases une par une ou en batch

4. DIAGRAMME DE GANTT en ASCII art montrant l'ordre et les parallelismes possibles

5. STRATEGIE DE ROLLBACK : pour chaque phase, comment revenir en arriere (git branch par phase)

6. METRIQUES DE PROGRES : comment mesurer l'avancement (tests qui passent, coverage, lignes de code, API endpoints fonctionnels)

$COMMON
Ecris le resultat dans: $OUTPUT/14_plan_migration.md
"

# ══════════════════════════════════════════════════════════════

completed=$(find "$OUTPUT" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l)
log ""
log "================================================================"
log "  ARCHITECTURE CIBLE TERMINEE"
log "  Fin     : $(date '+%Y-%m-%d %H:%M:%S')"
log "  Phases  : $completed/14 completees"
log "  Fichiers:"
find "$OUTPUT" -maxdepth 1 -name "*.md" -exec ls -lh {} \; 2>/dev/null | tee -a "$LOG"
log "================================================================"

notify "Architecture cible terminee ! $completed/13 phases. Voir architecture_cible/"
