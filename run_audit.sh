#!/usr/bin/env bash
#
# Audit complet du code HydroModPy par Claude Code
# Usage: tmux new-session -s audit './run_audit.sh'
#
set -euo pipefail

PROJECT="/home/bb/Documents/01_Git_Repository/02-HydroModPy-dev"
OUTPUT="$PROJECT/audit_code"
LOG="$OUTPUT/audit.log"
STDERR_TMP="$OUTPUT/.stderr_last"
MAX_RETRIES=12

mkdir -p "$OUTPUT"

# ── Helpers ──────────────────────────────────────────────────

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

notify() {
    # Desktop notification (visible au reveil)
    notify-send "HydroModPy Audit" "$*" 2>/dev/null || true
}

# Parse stdout + stderr pour determiner le temps d'attente
compute_wait() {
    local stderr_file="$1"
    local stdout_file="$2"

    # Combine stdout + stderr pour la detection
    local combined=""
    combined+=$(tail -50 "$stderr_file" 2>/dev/null || true)
    combined+=$'\n'
    combined+=$(tail -10 "$stdout_file" 2>/dev/null || true)

    if [[ -z "$combined" ]]; then
        echo 120
        return
    fi

    # Quota journalier epuise : "You've hit your limit · resets Xam/pm"
    if echo "$combined" | grep -qi "hit your limit\|hit.your.limit"; then
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
            if [[ "$wait_until" -lt 60 ]]; then wait_until=120; fi
            echo "$wait_until"
        else
            echo 300
        fi
        return
    fi

    # Rate limit temporaire : cherche "retry after N"
    local retry_seconds
    retry_seconds=$(echo "$combined" | grep -oiP 'retry.{0,5}after.{0,5}\K\d+' | head -1 || echo "")
    if [[ -n "$retry_seconds" ]] && [[ "$retry_seconds" -gt 0 ]]; then
        echo $(( retry_seconds + 60 ))
        return
    fi

    # Cherche "try again in Xh Ym" ou "Xm Ys"
    local hours minutes seconds
    hours=$(echo "$combined" | grep -oiP '\d+(?=\s*h)' | head -1 || echo "0")
    minutes=$(echo "$combined" | grep -oiP '\d+(?=\s*m)' | head -1 || echo "0")
    seconds=$(echo "$combined" | grep -oiP '\d+(?=\s*s)' | head -1 || echo "0")
    local parsed_wait=$(( ${hours:-0} * 3600 + ${minutes:-0} * 60 + ${seconds:-0} ))
    if [[ "$parsed_wait" -gt 60 ]]; then
        echo $(( parsed_wait + 60 ))
        return
    fi

    # Rate limit sans temps explicite
    if echo "$combined" | grep -qi "rate.limit\|429\|overloaded\|too many\|capacity"; then
        echo 1200
        return
    fi

    # Erreur transitoire (serveur, connexion)
    if echo "$combined" | grep -qi "server.error\|500\|502\|503\|connection\|timeout"; then
        echo 180
        return
    fi

    # Erreur inconnue : attente courte
    echo 120
}

run_phase() {
    local name="$1"
    local prompt="$2"
    local outfile="$OUTPUT/${name}.md"
    local attempt=1
    local backoff_multiplier=1

    # Skip si deja complete
    if [[ -f "$outfile" ]] && [[ -s "$outfile" ]]; then
        local existing_lines
        existing_lines=$(wc -l < "$outfile")
        if [[ "$existing_lines" -gt 20 ]]; then
            log "SKIP  $name (deja complete: $existing_lines lignes)"
            return 0
        fi
        log "WARN  $name existe ($existing_lines lignes) mais semble incomplet, relance..."
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

        # Succes : fichier cree et substantiel
        if [[ -f "$outfile" ]] && [[ -s "$outfile" ]]; then
            local lines
            lines=$(wc -l < "$outfile")
            if [[ "$lines" -gt 20 ]]; then
                log "DONE  $name ($lines lignes, ${elapsed}s) -> $outfile"
                notify "$name termine ($lines lignes)"
                return 0
            fi
        fi

        # Analyse de l'erreur (stdout + stderr)
        local wait_time
        wait_time=$(compute_wait "$STDERR_TMP" "$OUTPUT/.stdout_last")

        # Log l'erreur
        local err_summary
        err_summary=$(cat "$OUTPUT/.stdout_last" 2>/dev/null | head -1 || true)
        if [[ -z "$err_summary" ]]; then
            err_summary=$(tail -3 "$STDERR_TMP" 2>/dev/null | grep -i "error\|limit\|fail" | tail -1 || echo "exit code $rc")
        fi
        log "FAIL  $name (rc=$rc, ${elapsed}s): $err_summary"

        # Quota journalier : pas de backoff, on attend direct jusqu'au reset
        if echo "$err_summary" | grep -qi "hit your limit\|hit.your.limit"; then
            log "QUOTA JOURNALIER EPUISE — attente jusqu'au reset"
            local wait_h=$(( wait_time / 3600 ))
            local wait_m=$(( (wait_time % 3600) / 60 ))
            log "      Pause: ${wait_h}h${wait_m}m — resume prevue: $(date -d "+${wait_time} seconds" '+%Y-%m-%d %H:%M')"
            sleep "$wait_time"
            # Reset le backoff apres un quota wait
            backoff_multiplier=1
            attempt=$((attempt + 1))
            continue
        fi

        # Backoff exponentiel pour les autres erreurs
        wait_time=$(( wait_time * backoff_multiplier ))
        # Cap a 5h max
        if [[ "$wait_time" -gt 18000 ]]; then
            wait_time=18000
        fi

        local wait_min=$(( wait_time / 60 ))
        log "WAIT  ${wait_min}min avant retry (backoff x${backoff_multiplier})..."
        log "      Resume prevue: $(date -d "+${wait_time} seconds" '+%H:%M:%S')"

        sleep "$wait_time"

        attempt=$((attempt + 1))
        backoff_multiplier=$(( backoff_multiplier * 2 ))
        # Cap le multiplier a x8
        if [[ "$backoff_multiplier" -gt 8 ]]; then
            backoff_multiplier=8
        fi
    done

    log "ABANDON $name apres $MAX_RETRIES tentatives"
    notify "ECHEC: $name abandonne apres $MAX_RETRIES tentatives"
    return 1
}

# ── Phases ───────────────────────────────────────────────────

log ""
log "================================================================"
log "  AUDIT COMPLET HYDROMODPY"
log "  Debut   : $(date '+%Y-%m-%d %H:%M:%S')"
log "  Output  : $OUTPUT"
log "  Phases  : 11"
log "================================================================"

MERGE_REPORT="$PROJECT/reporting/audit_merge_dev_refact_2026-04-17.md"

COMMON_INSTRUCTIONS="
INSTRUCTIONS GENERALES:
- Ecris TOUT en francais technique.
- Ne modifie AUCUN fichier existant du projet. Ecris uniquement dans le fichier de sortie indique.
- IMPORTANT: Le code a subi un merge majeur recemment (899 fichiers changes, 487 ajoutes). Le rapport de merge est dans $MERGE_REPORT — lis-le AVANT de commencer ton analyse pour comprendre ce qui a change (nouveaux modules, renommages, suppressions).
- Ignore les fichiers .md existants dans le projet (ne les lis pas, ne t'en inspire pas).
- ADOPTE UN REGARD CRITIQUE D'EXPERT du domaine concerne. Tu n'es PAS un descripteur passif, tu es un auditeur senior qui juge.
- Pour chaque element analyse, donne un VERDICT : conforme aux standards / acceptable / a ameliorer / non-standard / problematique.
- Compare TOUJOURS aux standards de l'industrie et aux bonnes pratiques reconnues (PEP, design patterns, conventions du domaine scientifique/hydrogeologie).
- Quand quelque chose est mal nomme, dis comment ca DEVRAIT s'appeler et pourquoi.
- Quand une structure est non-standard, montre ce que font les projets de reference (xarray, pandas, scikit-learn, FloPy, PyGMT, etc.).
- Signale le code mort, les abstractions inutiles, le over-engineering, le under-engineering.
- Pour les formats de donnees : dis si c'est un format standard (CF-conventions, UGRID, OGC, etc.) ou un format maison, et ce que ca implique pour l'interoperabilite.
- Pour les grilles (regulieres vs irregulieres) : evalue si le code gere correctement les deux cas, si les conventions MODFLOW/DISV/DIS sont respectees.
- Utilise des tableaux markdown pour les recapitulatifs.
- Chaque section doit avoir : Description | Verdict | Justification | Recommandation.
- Sois direct et sans complaisance. Si c'est bien fait, dis-le. Si c'est mal fait, dis-le aussi clairement.
- OPTIMISATION : signale tout code qui pourrait etre significativement plus rapide (vectorisation numpy vs boucles Python, copies inutiles, allocations repetees, I/O synchrone vs batch).
- DUPLICATION : traque impitoyablement le code duplique (copier-coller entre modules, logiques repetees sous des noms differents, fonctions qui font la meme chose). Donne les fichiers et lignes concernes et propose une factorisation.
- VERBOSITE : signale le code inutilement verbeux (classes avec une seule methode qui devrait etre une fonction, abstractions a un seul heritier, wrappers qui n'ajoutent rien, fichiers __init__.py qui re-exportent tout sans raison). Moins de code = moins de bugs.
- TESTS EXCESSIFS : si des tests sont redondants, trop lents pour ce qu'ils verifient, ou testent des details d'implementation au lieu du comportement, dis-le. Propose des fusions ou suppressions. Un bon test suite est compact et rapide, pas massif.
- DEAD CODE : fonctions jamais appelees, imports inutilises, branches unreachable, fichiers legacy qui trainent. Tout ce qui peut etre supprime doit etre signale.
"

# ------ PHASE 1 : Architecture globale ------
run_phase "01_architecture_globale" "
Tu es un ARCHITECTE LOGICIEL SENIOR specialise en toolboxes scientifiques Python. Tu as 15 ans d'experience sur des projets comme scikit-learn, xarray, FloPy, PyGMT. Audite le projet HydroModPy a $PROJECT.

Lis les fichiers suivants pour comprendre la structure globale:
- hydromodpy/__init__.py (API publique, lazy imports)
- hydromodpy/__main__.py (CLI, points d'entree)
- hydromodpy/project.py (classe Simulation, context manager)
- hydromodpy/runners/ (dispatch CLI)
- hydromodpy/exceptions.py
- Tous les __init__.py de chaque sous-package

Produis un audit CRITIQUE couvrant:
1. ARCHITECTURE DES PACKAGES : arbre de dependances, qui importe quoi. Est-ce que la structure suit les conventions des toolboxes scientifiques Python ? Compare avec FloPy, xarray, scikit-learn. Le decoupage est-il logique ou arbitraire ?
2. CLI : le design argparse est-il standard (sous-commandes, help, completion) ? Compare avec des CLI bien faites (httpie, poetry, ruff). Les exit codes sont-ils corrects ?
3. API PUBLIQUE : ce qui est expose dans __init__.py est-il coherent ? Le lazy import pattern est-il correctement implemente ? Est-ce que l'API est intuitive pour un hydrogeologue ?
4. NOMMAGE : les noms de modules/classes/fonctions suivent-ils PEP8 et les conventions du domaine ? Signale tout ce qui est mal nomme avec ta proposition de renommage.
5. CYCLE DE VIE : de la config TOML au resultat, le flux est-il lineaire et comprehensible ou spaghetti ? Y a-t-il des couplages caches ?
6. ANTI-PATTERNS detectes : God classes, circular dependencies, leaky abstractions, feature envy, etc.
7. DIAGRAMME de dependances en ASCII art.

$COMMON_INSTRUCTIONS
Ecris le resultat dans le fichier: $OUTPUT/01_architecture_globale.md
"

# ------ PHASE 2 : Core & Config ------
run_phase "02_core_config" "
Tu es un EXPERT PYDANTIC et ARCHITECTE DE CONFIGURATION pour applications scientifiques. Tu connais parfaitement Pydantic v2, TOML, les patterns de configuration de Hydrus, SWAT, MODFLOW. Audite le package core/ de HydroModPy a $PROJECT.

Lis TOUS les fichiers .py dans:
- hydromodpy/core/ (config, state, time, tools, units, workspace)

Produis un audit CRITIQUE couvrant:
1. SYSTEME PYDANTIC : les modeles utilisent-ils correctement Pydantic v2 (model_validator vs validator, ConfigDict vs Config, Field vs fields) ? Le pattern ParamLevel est-il une bonne idee ou du over-engineering ? Compare avec des approches standard (dynaconf, hydra-core, OmegaConf).
2. HYDROMODPYCONFIG : la config agregateur est-elle maintenable ? Le mapping TOML<->Pydantic est-il 1:1 ou y a-t-il des transformations cachees ? Les defaults sont-ils sensibles physiquement ?
3. STATE MANAGEMENT : WorkflowContext/SetupContext/LoadedDataContext — est-ce un bon pattern ou un God Object deguise ? Compare avec le pattern Context/Registry de scikit-learn Pipeline ou Prefect. Le scoping est-il clair ?
4. SYSTEME D'UNITES : est-ce que ca reinvente la roue vs pint/unyt/cf-units ? Les conversions sont-elles correctes et completes ? Risque d'erreurs d'unites silencieuses ?
5. WORKSPACE : la structure de repertoires est-elle standard ou maison ? Compare avec les conventions cookiecutter-data-science, DVC, MLflow.
6. TIME MANAGEMENT : TimeWindow gere-t-il correctement les fuseaux horaires, les annees bisextiles, les pas de temps irreguliers ? Compare avec pandas DatetimeIndex, xarray CFTimeIndex.
7. OUTILS : log_manager — est-ce standard (logging module) ou reinvente ? raster_io — pourquoi pas rioxarray directement ?
8. TABLEAU RECAPITULATIF de chaque modele Pydantic : nom, fichier, champs, types, verdict (bien fait / a revoir / non-standard).

$COMMON_INSTRUCTIONS
Ecris le resultat dans le fichier: $OUTPUT/02_core_config.md
"

# ------ PHASE 3 : Data layer ------
run_phase "03_data_layer" "
Tu es un EXPERT DATA ENGINEERING et HYDROGEOLOGUE specialise en donnees hydrologiques (Hub'Eau, Banque Hydro, ADES, BRGM). Tu connais les formats standard (WaterML, OGC SensorThings, CF-conventions, INSPIRE). Audite le package data/ de HydroModPy a $PROJECT.

Lis TOUS les fichiers .py dans:
- hydromodpy/data/ (common, contracts, variables, registry, plan, planner, runtime_loader)

Produis un audit CRITIQUE couvrant:
1. PATTERN MANAGER : BaseVariableManager est-il un bon pattern ou trop rigide ? Compare avec intake, pangeo-forge, ou le pattern ETL classique (extract/transform/load). Le cycle de vie est-il clair ?
2. CONTRACTS (LoadResult, Location, SpatialField, TimeSeries) : suivent-ils des standards ? SpatialField devrait-il etre un xarray.DataArray ? TimeSeries devrait-il etre un pandas.Series avec DatetimeIndex ? Les types sont-ils corrects pour de l'hydrogeologie (unites, precision float32 vs float64, coordonnees) ?
3. INFERENCE DES DONNEES : le systeme d'inference automatique (DataManagersPlanner) est-il robuste ou fragile ? Que se passe-t-il si l'inference se trompe ? Le mode strict vs warn est-il suffisant ?
4. CACHE DUCKDB : le schema est-il normalise ? Y a-t-il des risques de corruption ? L'invalidation du cache est-elle correcte (donnees mises a jour en amont) ?
5. APIS EXTERNES (Hub'Eau, BRGM, SHOM) : les clients gerent-ils correctement les erreurs reseau, la pagination, le rate limiting, les changements d'API ? Les donnees sont-elles validees a l'entree ?
6. FORMATS D'ENTREE : les CSV custom sont-ils documentes ? Le format attendu est-il standard ou proprietaire ? Pourquoi pas GeoJSON, GeoPackage, ou Parquet ?
7. FORMATS DE SORTIE : les donnees sont-elles exportees dans des formats interoperables (CF-NetCDF, CSV avec metadata, WaterML) ou dans un format maison ?
8. GESTION DES CRS : les projections sont-elles gerees correctement partout ? Y a-t-il des transformations CRS implicites dangereuses ?
9. TABLEAU par type de donnee : variable, config Pydantic, manager, source API, format entree, format sortie, verdict.

$COMMON_INSTRUCTIONS
Ecris le resultat dans le fichier: $OUTPUT/03_data_layer.md
"

# ------ PHASE 4 : Spatial & Mesh ------
run_phase "04_spatial_mesh" "
Tu es un EXPERT EN MAILLAGE NUMERIQUE et GEOMATIQUE specialise en hydrogeologie. Tu connais parfaitement MODFLOW DIS/DISV/DISU, UGRID, gmsh, Triangle, TetGen, les conventions FloPy, et les standards OGC pour les donnees geospatiales. Audite les packages spatial/ et mesh de HydroModPy a $PROJECT.

Lis TOUS les fichiers .py dans:
- hydromodpy/spatial/ (geographic, domain, field, mesh, surface)
- hydromodpy/solver/utils/mesh/ (cartesian_grid, gmsh_grid, zone_meshing)

Produis un audit CRITIQUE couvrant:
1. GRILLES REGULIERES vs IRREGULIERES : le code gere-t-il correctement les deux cas ? La transition DIS (structured) -> DISV (vertex) -> DISU (unstructured) est-elle propre ? Y a-t-il du code qui suppose implicitement une grille reguliere alors qu'il recoit une grille DISV ?
2. DELINEATION DE BASSIN : le pipeline DEM->catchment est-il robuste ? Compare avec pysheds, richdem, whitebox-tools. Les algorithmes de flow direction/accumulation sont-ils corrects pour les DEMs a faible resolution ?
3. CONVENTIONS MODFLOW : les indices de cellules sont-ils 0-based ou 1-based partout ? Le mapping (layer, row, col) vs (layer, cell2d) est-il coherent ? Les nodata/inactive cells sont-ils geres uniformement (IDOMAIN, IBOUND) ?
4. MESH GMSH : l'integration gmsh est-elle propre (API Python vs fichiers .geo) ? Le conformal meshing respecte-t-il les frontieres geologiques ? La qualite du maillage est-elle verifiee (aspect ratio, skewness) ?
5. DISCRETISATION DES CHAMPS : comment les proprietes (K, Sy, Ss) sont-elles discretisees du champ continu au maillage ? Interpolation nearest/bilinear/conservatrice ? Est-ce correct pour des proprietes comme la conductivite hydraulique (moyenne harmonique vs arithmetique) ?
6. FORMATS : les maillages sont-ils exportables en UGRID, VTK, Shapefile ? Les conventions CF sont-elles respectees pour les coordonnees ?
7. SURFACE/TOPOGRAPHIE : le traitement de la surface topographique (DEM -> z_interfaces) est-il correct ? Gestion des couches inclinees, des pinch-outs ?
8. NOMMAGE ET ORGANISATION : les classes et modules sont-ils bien nommes pour le domaine ? Compare avec FloPy (Modflow, ModflowDis, ModflowDisv) et meshio.
9. TABLEAU : chaque composant spatial avec verdict.

$COMMON_INSTRUCTIONS
Ecris le resultat dans le fichier: $OUTPUT/04_spatial_mesh.md
"

# ------ PHASE 5 : Process & Solver ------
run_phase "05_process_solver" "
Tu es un EXPERT EN MODELISATION HYDROGEOLOGIQUE et METHODES NUMERIQUES. Tu connais les equations de Boussinesq, Richards, l'advection-dispersion. Tu maitrises MODFLOW-NWT, MODFLOW 6, MT3DMS, MODPATH. Tu as implemente des solveurs Newton-Raphson en Python. Audite les packages process/ et solver/ de HydroModPy a $PROJECT.

Lis TOUS les fichiers .py dans:
- hydromodpy/process/ (base, flow, transport, forcing)
- hydromodpy/solver/ (base, modflow6, modflow_nwt, boussinesq, modflow_common, utils/temporal)

Produis un audit CRITIQUE couvrant:
1. ABSTRACTION PROCESSUS : ProcessSpatial[T] est-il une bonne abstraction ? Le generique sur les InitialConditions est-il justifie ou du over-engineering ? Compare avec le design de FloPy (qui n'abstrait PAS les processus) et celui de FEHM/TOUGH2.
2. CONDITIONS LIMITES : les BC (Dirichlet, Neumann, Cauchy/Robin) sont-elles correctement implementees ? Le mapping des BC hydrologiques (drain, river, well, recharge, ocean) aux BC MODFLOW (DRN, RIV, WEL, RCH, GHB, CHD) est-il correct physiquement ?
3. SOLVER BOUSSINESQ MAISON : le Jacobien (semi-analytique et FD) est-il correct ? La formulation mixed complementarity est-elle validee ? Le solveur scipy.sparse est-il le bon choix vs PETSc/MUMPS ? Quelles sont les limites de stabilite ?
4. INTEGRATION MODFLOW-NWT : le wrapper FloPy est-il utilise correctement ? Les options NWT (solver settings, convergence criteria) sont-elles exposees proprement ? Le postprocess des outputs binaires est-il robuste (HEAD, BUDGET, CBB) ?
5. INTEGRATION MODFLOW 6 : les packages sont-ils tous supportes ? Le couplage GWF-GWT est-il correct ? Les INFORMATION warnings de FloPy sont-ils geres ?
6. TRANSPORT : le couplage flow->transport est-il one-way ou two-way ? MT3DMS vs MF6-GWT : les differences sont-elles bien gerees ? La dispersion est-elle correctement parametrisee ?
7. DISCRETISATION TEMPORELLE : les stress periods et time steps sont-ils generes correctement ? Gestion des forcages variables dans le temps (recharge mensuelle, marees) ?
8. PROPERTY MAPPING : K est-il mappe avec la bonne moyenne (harmonique pour les faces, arithmetique pour les cellules) ? Sy et Ss sont-ils physiquement coherents ? Les unites sont-elles converties correctement ?
9. COMPARAISON DES 3 SOLVEURS : tableau comparatif capacites/limites/performance/precision.

$COMMON_INSTRUCTIONS
Ecris le resultat dans le fichier: $OUTPUT/05_process_solver.md
"

# ------ PHASE 6 : Simulation engine ------
run_phase "06_simulation_engine" "
Tu es un EXPERT EN DESIGN PATTERNS et ORCHESTRATION DE WORKFLOWS scientifiques. Tu connais Prefect, Airflow, Luigi, Dask Delayed, et les patterns Command/Strategy/Observer. Audite les packages simulation/ et workflow/ de HydroModPy a $PROJECT.

Lis TOUS les fichiers .py dans:
- hydromodpy/simulation/ (adapters, execution, planning, results/extractors)
- hydromodpy/workflow/ (pipelines, steps, context)
- hydromodpy/project.py

Produis un audit CRITIQUE couvrant:
1. PATTERN ADAPTER (SolverAdapter Protocol) : est-ce un vrai Protocol (structural subtyping) ou un ABC deguise ? Le registre est-il propre (dispatch dict, entry_points, ou plugin system) ? Compare avec le pattern Strategy de scikit-learn (estimators).
2. PLAN IMMUTABLE (SimulationPlan, frozen dataclass) : bon pattern. Mais est-il vraiment immutable ? Y a-t-il des mutations cachees via des references mutables ? Le plan est-il serialisable/reproductible ?
3. EXECUTION (SimulationRunner) : les callbacks sont-ils un bon pattern ou faudrait-il des hooks/events ? La gestion d'erreurs est-elle robuste (que se passe-t-il si le solver crash a mi-parcours) ? Y a-t-il du cleanup correct (fichiers temporaires, connexions DB) ?
4. WORKFLOW STEPS : sont-ils composables et reutilisables ou monolithiques ? Compare avec le pipeline pattern de scikit-learn ou les DAGs de Prefect. Les dependances entre steps sont-elles explicites ?
5. EXTRACTORS : chaque extracteur (MF6, NWT, Boussinesq, MT3DMS, MODPATH) a-t-il la meme interface ? Les formats binaires MODFLOW sont-ils lus correctement (big-endian, precision, record markers) ? Y a-t-il du code duplique entre extracteurs ?
6. DERIVED VARIABLES : compute_derived() est-il extensible ? Les calculs sont-ils physiquement corrects (watertable = head at uppermost saturated layer, seepage = wt >= topo) ? La gestion des NaN/nodata est-elle coherente ?
7. CLASSE SIMULATION (project.py) : est-ce une God class ? Le context manager est-il correct (__enter__/__exit__, cleanup garanti) ? Combien de responsabilites a-t-elle ?
8. DIAGRAMME de sequence : TOML -> Config -> Plan -> Run -> Extract -> Derive -> Export.

$COMMON_INSTRUCTIONS
Ecris le resultat dans le fichier: $OUTPUT/06_simulation_engine.md
"

# ------ PHASE 7 : Results & Storage ------
run_phase "07_results_storage" "
Tu es un EXPERT EN STOCKAGE DE DONNEES SCIENTIFIQUES et BASES DE DONNEES. Tu connais parfaitement DuckDB, Zarr v2/v3, HDF5, NetCDF-4, les conventions CF, UGRID, et les patterns de data lakehouse (Delta Lake, Iceberg). Audite le package results/ de HydroModPy a $PROJECT.

Lis TOUS les fichiers .py dans:
- hydromodpy/results/ (catalog, zarr_store, config, catalog_schema, exporters, provenance, spatial_index, virtual_fields)

Produis un audit CRITIQUE couvrant:
1. CHOIX DUCKDB + ZARR : est-ce le bon choix vs SQLite + HDF5 (plus mature), ou Parquet + Zarr (plus cloud-native) ? Quels sont les risques de corruption, de concurrent access, de migration de schema ?
2. SCHEMA DUCKDB : les 12 tables sont-elles normalisees correctement (3NF) ? Les PKs et FKs sont-ils corrects ? Y a-t-il des colonnes qui devraient etre dans une autre table ? Les types SQL sont-ils les bons (VARCHAR vs TEXT, FLOAT vs DOUBLE, timestamp avec timezone) ? Y a-t-il un mecanisme de migration de schema ?
3. ZARR LAYOUT : le chunking (1, n_layers, n_cells) est-il optimal pour les acces typiques (timeseries a un point, carte a un instant) ? La compression BLOSC-ZSTD clevel=3 est-il le bon compromis ? Zarr v2 ou v3 ? Les metadata CF sont-elles presentes ?
4. FORMATS D'EXPORT : le NetCDF suit-il les conventions CF-1.8 et UGRID ? Le VTU est-il lisible par ParaView ? Le GeoTIFF a-t-il les bonnes metadata (CRS, nodata, bands) ? Le CSV a-t-il un header standard ?
5. PROVENANCE : le tracking SHA-256 est-il suffisant pour la reproductibilite scientifique ? Compare avec les standards W3C PROV, ou les approches de DVC/MLflow. Les inputs sont-ils tous traces ?
6. INTEROPERABILITE : un utilisateur peut-il ouvrir les resultats directement avec xarray, pandas, QGIS, ParaView sans passer par l'API HydroModPy ? Si non, c'est un probleme.
7. CONCURRENCE : que se passe-t-il si deux simulations ecrivent en meme temps dans le meme DuckDB ? Le locking est-il correct ?
8. PACKAGE .hmp : le format est-il documente ? Est-ce un zip, un tar, un format custom ? Est-il versionne ?
9. DIAGRAMME du schema DuckDB en ASCII art + diagramme du layout Zarr.

$COMMON_INSTRUCTIONS
Ecris le resultat dans le fichier: $OUTPUT/07_results_storage.md
"

# ------ PHASE 8 : Analysis & Display ------
run_phase "08_analysis_display" "
Tu es un EXPERT EN VISUALISATION SCIENTIFIQUE et POST-TRAITEMENT. Tu connais matplotlib, cartopy, PyVista, holoviews, plotly, et les conventions de visualisation en hydrogeologie (coupes, cartes piezometriques, hydrogrammes). Audite le package analysis/ de HydroModPy a $PROJECT.

Lis TOUS les fichiers .py dans:
- hydromodpy/analysis/ (display, postprocess)

Produis un audit CRITIQUE couvrant:
1. ARCHITECTURE DISPLAY : le pattern suite/orchestration est-il un bon design ou un monolithe ? Compare avec le design de matplotlib (Figure/Axes/Artist) ou holoviews (Element/Layout/Overlay). Est-ce testable sans display ?
2. QUALITE DES FIGURES : les figures produites sont-elles de qualite publication ? Les axes ont-ils des labels avec unites ? Les colormaps sont-elles perceptuellement uniformes (viridis, pas jet) ? Les echelles sont-elles coherentes ?
3. TYPES DE FIGURES : manque-t-il des visualisations standard en hydrogeologie ? (cartes piezometriques avec lignes de courant, coupes geologiques, diagrammes de Piper, roses des vents, hyetogrammes, courbes de recession)
4. POSTPROCESS : les calculs de post-traitement (matching streams, intermittency) sont-ils dans le bon package ? Devraient-ils etre dans process/ ou results/ plutot que analysis/ ?
5. NETCDF EXPORT : suit-il les conventions CF-1.8 ? Les coordonnees, dimensions, attributs sont-ils corrects ? Le fichier est-il lisible par ncview, Panoply, xarray sans configuration ?
6. TIMESERIES : les series temporelles sont-elles correctement extraites (interpolation, aggregation) ? Les metriques (NSE, KGE, RMSE) sont-elles calculees correctement (formules standard) ?
7. HEADLESS MODE : le pattern HYDROMODPY_NO_DISPLAY/NO_SAVE est-il propre ? Compare avec matplotlib.use('Agg'). Y a-t-il des imports matplotlib au top-level qui cassent en headless ?
8. REPORT/OVERVIEW : est-ce utile ou du bloat ? Compare avec des outils de reporting standard (jupyter-book, quarto, sphinx-gallery).
9. TABLEAU : chaque composant display avec verdict.

$COMMON_INSTRUCTIONS
Ecris le resultat dans le fichier: $OUTPUT/08_analysis_display.md
"

# ------ PHASE 9 : Tests ------
run_phase "09_tests_audit" "
Tu es un EXPERT EN QUALITE LOGICIELLE et TESTING specialise en logiciels scientifiques. Tu connais les frameworks pytest, hypothesis, tox, nox, et les strategies de test pour les codes numeriques (MMS, benchmark analytique, convergence). Audite la suite de tests de HydroModPy a $PROJECT.

Lis TOUS les fichiers .py dans:
- tests/ (conftest.py, unit/, regression/, validation/, support/)

Produis un audit CRITIQUE couvrant:
1. STRATEGIE DE TEST : le decoupage unit/regression/validation est-il standard ? Compare avec la pyramide de tests (unit >> integration >> e2e). Le ratio est-il correct ou y a-t-il trop de tests e2e et pas assez d'unitaires ?
2. TESTS UNITAIRES : sont-ils vraiment unitaires (isolement, pas d'I/O, rapides) ou des tests d'integration deguises ? Les mocks sont-ils utilises correctement ou excessivement ? Les edge cases sont-ils testes (grilles 1x1, pas de temps unique, proprietes nulles) ?
3. TESTS DE REGRESSION : le pattern golden file est-il robuste ? Que se passe-t-il quand les sorties changent legitimement ? Le processus update-goldens est-il documente et sur ? Les signatures npy sont-elles deterministes cross-platform (float precision, endianness) ?
4. TESTS DE VALIDATION : les benchmarks analytiques sont-ils les bons (Dupuit, Theis, Hantush) ? Les criteres de convergence sont-ils documentes ? Compare avec les benchmarks standard MODFLOW (MacDonald & Harbaugh, Zheng & Wang).
5. COUVERTURE : quels modules n'ont AUCUN test ? Quels chemins critiques ne sont pas testes ? La couverture est-elle mesuree correctement (le coverage_runner.py a des bugs — SystemExit non capture) ?
6. FIXTURES : les fixtures conftest.py sont-elles bien scopees (function/class/module/session) ? Y a-t-il des effets de bord entre tests (fichiers temporaires, DB partagee) ? Les tests sont-ils parallelisables (pytest-xdist) ?
7. INFRASTRUCTURE : golden_utils et launcher_simulation_helpers — sont-ils maintenables ou du code spaghetti ? Les helpers sont-ils testes eux-memes ?
8. CI : le pipeline CI est-il rapide et fiable ? Quels tests flaky as-tu detectes ? Les timeouts sont-ils corrects ?
9. RECOMMANDATIONS PRIORISEES : top 5 des tests manquants les plus critiques.

$COMMON_INSTRUCTIONS
Ecris le resultat dans le fichier: $OUTPUT/09_tests_audit.md
"

# ------ PHASE 10 : Pydantic models inventory ------
run_phase "10_pydantic_models" "
Tu es un EXPERT PYDANTIC V2 et DESIGN D'API DE CONFIGURATION. Tu connais parfaitement les best practices Pydantic (discriminated unions, computed fields, model serialization, JSON Schema generation). Fais l'inventaire COMPLET et CRITIQUE de tous les modeles Pydantic du projet HydroModPy a $PROJECT.

Cherche tous les fichiers *_config.py dans hydromodpy/ et lis-les tous.
Cherche aussi toute classe heritant de BaseModel ou BaseConfig dans tout le projet.

Produis un document exhaustif contenant:
1. INVENTAIRE COMPLET : pour CHAQUE modele Pydantic trouve :
   - Nom de la classe et fichier source (chemin complet)
   - Classe parente
   - Tous les champs avec: nom, type, default, description, ParamLevel si present
   - Validators (field_validator, model_validator)
   - ConfigDict options (extra=forbid, etc.)
   - Relations avec d'autres modeles (composition, heritage)
   - VERDICT : bien concu / a simplifier / mal type / non-standard
2. CRITIQUE DU DESIGN : les modeles utilisent-ils correctement Pydantic v2 ? Y a-t-il des patterns Pydantic v1 obsoletes (validator au lieu de field_validator, Config au lieu de ConfigDict) ? Les types sont-ils precis (Literal vs str, Annotated, Path vs str pour les chemins) ?
3. ARBRE D'HERITAGE : est-il trop profond ? Y a-t-il de l'heritage diamant ? Faudrait-il de la composition au lieu de l'heritage ?
4. VALEURS PAR DEFAUT : les defaults sont-ils physiquement sensibles pour l'hydrogeologie ? (ex: K=1e-4 m/s est-il un bon default ? Sy=0.1 est-il raisonnable ?)
5. VALIDATION : les validators verifient-ils les contraintes physiques (K > 0, 0 < Sy < 1, Ss > 0) ? Y a-t-il des validations manquantes qui pourraient causer des erreurs silencieuses ?
6. SERIALIZATION : le round-trip TOML -> Pydantic -> TOML est-il sans perte ? Les champs optionnels sont-ils geres correctement ?
7. MAPPING TOML <-> PYDANTIC : est-ce un mapping 1:1 ou y a-t-il des transformations ? Les noms TOML sont-ils ceux attendus par un utilisateur hydrogeologue ?

$COMMON_INSTRUCTIONS
Ecris le resultat dans le fichier: $OUTPUT/10_pydantic_models.md
"

# ------ PHASE 11 : Synthese finale ------
run_phase "11_synthese_finale" "
Tu es un CTO / LEAD ARCHITECT qui doit presenter un audit technique au board d'un projet open-source scientifique. Tu as lu les 10 rapports d'audit precedents. Produis la synthese finale de l'audit du projet HydroModPy a $PROJECT.

Lis les fichiers d'audit deja produits dans $OUTPUT/ (01 a 10) pour en faire la synthese.

Produis un document EXECUTIF et ACTIONNABLE couvrant:
1. SCORECARD GLOBAL : note /10 par domaine (architecture, code quality, tests, storage, documentation, interoperabilite, maintenabilite) avec justification en 1 ligne.
2. TOP 10 FORCES : ce qui est bien fait et qu'il faut preserver. Avec reference au rapport source.
3. TOP 10 DETTES TECHNIQUES : classees par impact (bloquant / majeur / mineur) et effort (facile / moyen / hard). Avec reference au rapport source.
4. PROBLEMES CRITIQUES : ce qui doit etre corrige AVANT toute release publique (bugs potentiels, pertes de donnees, resultats incorrects).
5. CODE MORT : fichiers, classes, fonctions qui ne sont plus utilises et devraient etre supprimes.
6. INCONSISTANCES INTER-MODULES : nommage incoherent entre modules, conventions differentes, interfaces incompatibles.
7. CONFORMITE AUX STANDARDS : pour chaque domaine, est-on conforme (CF-conventions, UGRID, PEP8, MODFLOW conventions, OGC) ? Tableau avec status par standard.
8. RENOMMAGES NECESSAIRES : tableau avec nom actuel, nom propose, justification.
9. REORGANISATION SUGGEREE : si tu devais reorganiser les packages, que changerais-tu ? Arbre propose vs arbre actuel.
10. PLAN D'ACTION 3 MOIS : sprint 1 (quick wins, 2 semaines), sprint 2 (refactoring moyen, 1 mois), sprint 3 (changements structurels, 1.5 mois). Avec effort estime en jours-developpeur.
11. CONCLUSION : en 5 phrases, l'etat du projet et sa trajectoire.

$COMMON_INSTRUCTIONS
Ecris le resultat dans le fichier: $OUTPUT/11_synthese_finale.md
"

# ── Fin ──────────────────────────────────────────────────────

completed=$(find "$OUTPUT" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l)
log ""
log "================================================================"
log "  AUDIT TERMINE"
log "  Fin     : $(date '+%Y-%m-%d %H:%M:%S')"
log "  Phases  : $completed/11 completees"
log "  Fichiers:"
find "$OUTPUT" -maxdepth 1 -name "*.md" -exec ls -lh {} \; 2>/dev/null | tee -a "$LOG"
log "================================================================"

notify "Audit termine ! $completed/11 phases completees. Voir audit_code/"
