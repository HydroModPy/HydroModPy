# Audit HydroModPy — Synthèse exécutive finale

**Document** : synthèse du board d'audit technique
**Auditeur principal** : CTO / Lead Architect — toolboxes scientifiques Python, hydrogéologie numérique
**Périmètre** : 10 rapports d'audit thématiques (≈ 7 200 lignes) + rapport de merge `dev-refact → dev-database` (899 fichiers, +867 k insertions)
**Branche** : `dev-database` (HEAD `74b62878`, post-merge `2026-04-17`)
**Date de synthèse** : 2026-04-18

> **Intention du document** : fournir au board une image exécutive et actionnable — verdicts chiffrés, trajectoire, plan de sprints. Les 10 rapports sources conservent la preuve détaillée. Cette synthèse **juge**, ne décrit pas.

---

## 0. Verdict synthétique en 5 lignes

HydroModPy est un **projet scientifique de maturité intermédiaire** qui porte une **vision architecturale ambitieuse** (Simulation Catalog DuckDB+Zarr, Protocol adapters, planner immutable, 3 solveurs unifiés) mais paie une **exécution en accrétion** : le merge `dev-refact` a introduit 487 fichiers de code-cible sans avoir nettoyé le code-source équivalent, produisant un repo où **trois générations** (Watershed legacy → launchers → runners/Project) cohabitent. Le noyau scientifique est **solide** (corpus analytique Brutsaert/Dupuit/Polubarinova-Kochina, MCP Fischer-Burmeister correcte, stockage moderne) mais se fissure sur **deux axes toxiques** : des **bugs physiques silencieux** (BC `stream→CHD`, `ocean→CHD`, moyenne K arithmétique au lieu d'harmonique, confusion porosité/Sy, conductance drain `K·A` sans épaisseur) et une **conformité aux standards scientifiques partielle** (CF-1.8 absent sur NetCDF, UGRID non respecté, Zarr v3 fermant QGIS/ParaView, pas de MMS, pas de Theis/Hantush/Ogata-Banks). **Le projet n'est pas publiable en l'état** pour un usage certifié (décision BRGM, stockage déchets, alimentation eau potable) mais il est **très proche** : 3 mois d'effort ciblé suffiront à lever les bloquants et transformer la vision en produit défendable.

---

## 1. Scorecard global

Note /10, pondération implicite critique > importance.

| Domaine | Note | Justification lapidaire |
|---|:---:|---|
| **Architecture packages & dépendances** | **5/10** | DAG annoncé « core feuille » violé : `core/config/hydromodpy_config.py` importe 13 modules depuis 7 packages. Inversions `data → analysis`, `spatial → solver`. 3 générations de code cohabitent. Rapport 01. |
| **CLI & API publique** | **6/10** | `runners/` respectent la règle des thin shells (12–29 lignes), lazy imports PEP 562 propres, mais `__main__.py` = 1 223 lignes (God module) et `project.py` abrite la classe `Simulation` (dissonance flagrante). Rapport 01. |
| **Code quality (code mort, duplication, verbosité)** | **4/10** | ~2 700 lignes climatic legacy, ~700 lignes dupliquées dans `boussinesq.py` post-refactor, ~800 lignes de `data/variables/*/config.py` à 95 % copiées, 10 God modules > 1 500 lignes, `exceptions.py` 100 % mort. Rapports 01, 02, 03, 05, 06, 07, 10. |
| **Validation (Pydantic) & sécurité config** | **6/10** | Pydantic v2 correctement adopté. **Mais aucune validation physique** sur K, Sy, Ss, n, vka — un utilisateur peut saisir `K = -1 m/s` et passer. `extra="forbid"` absent sur l'agrégateur racine. Rapport 10. |
| **Couche données & APIs externes** | **3/10** | `urllib.request.urlretrieve` **sans timeout** (BRGM, IGN), pas de handling HTTP 429 Hub'Eau, `resp.json()` non protégé, pas de validation Pydantic des payloads. Format CSV station propriétaire, non WaterML/SensorThings. Rapport 03. |
| **Spatial & maillage** | **6/10** | `HydroMesh` pivot solide, FloPy DISV correct, intégration Gmsh native propre. **Mais** : moyenne K arithmétique au lieu d'harmonique (bug physique), aucun contrôle qualité maillage (CCW, angle min), `zone_meshing/` sur-fragmenté (27 fichiers, 7 façades stériles). Rapport 04. |
| **Process & solveurs** | **5/10** | 3 solveurs intégrés, Boussinesq MCP mathématiquement correcte. **Bugs physiques** : `stream→CHD` (doit être RIV), `ocean→CHD` (doit être GHB), conductance drain sans épaisseur, confusion porosité/Sy transport, MODPATH 6 (bloque DISV). Rapport 05. |
| **Moteur de simulation & orchestration** | **5/10** | `SimulationPlan` frozen, `SolverAdapter` Protocol, runners thin shells. **Mais** : classe `Simulation` God class (16 responsabilités), bypass du planner dans `_run_with_overrides`, duplication extracteurs MF6/NWT ~70 %, heuristique `n_per ∈ [12,6,4,3,2,1]` bugguée. Rapport 06. |
| **Stockage résultats (catalog + Zarr)** | **5/10** | DuckDB+Zarr = bon choix moderne. **Mais** : 5 tables sans PK (doublons silencieux possibles), aucune FK, `period_start` en VARCHAR, migrations vides, Zarr v3 coupe QGIS/ParaView, bug `_split_cell_data` VTU (mesh mixte), bug `import_simulation` if/else identique. Rapport 07. |
| **Analysis & display** | **5/10** | `figures/flow_synthesis.py` référence-qualité. **Mais** : 6 `cmap='jet'` dans du code actif (contre-indication Crameri 2020), aucun cartopy/CRS/scalebar, NetCDF non CF-1.8, side-effects d'import (`plt.style.use`, `rcParams`), 2 640 lignes legacy, duplication suites/posthoc à 80 %. Rapport 08. |
| **Tests & CI** | **5/10** | Infra saine (markers riches, goldens statistiques, scratch externalisé) mais pyramide inversée (20 % unit réels, 55 % intégration déguisée en unit). Absences critiques : Theis, Hantush, Ogata-Banks, MMS, tests unit `solver/boussinesq/runtimes/`. Test Boussinesq cassé par imports post-merge. Rapport 09. |
| **Documentation & interopérabilité** | **4/10** | Capability gallery riche, README et ARCHITECTURE présents. **Mais** : formats CSV stations propriétaires, Zarr v3 non lu par QGIS/Panoply, pas d'export WaterML 2.0, NetCDF non CF, pas de `manifest.json` dans `.hmp`, tolérances non justifiées. Rapports 03, 07, 08, 09. |
| **Maintenabilité** | **5/10** | Deux patterns bien établis (`*_config.py` / `*_manager.py`, runners thin shells) mais cohabitation de 3 générations de code, 10 God modules, refactor inachevé post-merge qui laisse la duplication. Rapports 01, 05, 06. |

**Note globale pondérée : 5,0/10 — « Acceptable pour recherche, insuffisant pour certification. »**

---

## 2. Top 10 forces — à préserver absolument

| # | Force | Rapport | Pourquoi c'est précieux |
|---|---|:---:|---|
| 1 | **Simulation Catalog (DuckDB + Zarr par simulation)** | 07 | Choix moderne aligné sur Earthmover/Pangeo, séparation metadata/data propre, unique source de vérité au niveau workspace. La meilleure décision architecturale du projet. |
| 2 | **Pattern `SolverAdapter` (Protocol PEP 544)** | 06 | Duck typing structurel, extensibilité pour de nouveaux solveurs, registre clair `(process_type, solver_name)`. Mieux que FloPy qui n'a pas cette abstraction. |
| 3 | **`SimulationPlan` / `ProcessRun` immuables (`frozen=True`)** | 06 | Dataclasses frozen avec tuples, sérialisables par accident. Le planner préserve l'ordre TOML et valide unicité + dépendances. 115 lignes testables. |
| 4 | **Lazy imports PEP 562 au top-level** | 01 | `hydromodpy/__init__.py` utilise `__getattr__` avec cache `globals()`. Pattern identique à scipy/sklearn/xarray. |
| 5 | **Validation calibration exemplaire** (`analysis/calibration/cases/`) | 10 | `Groundwater1DChronicleSchema` vérifie bornes hydrauliques (K>0, Sy∈]0,1[), domaine (0<xi<L), recharge_mode littéral. **Le savoir-faire existe — il faut le propager ailleurs.** |
| 6 | **Corpus de validation analytique gravitaire solide** | 05, 09 | ~15 cas Brutsaert / Dupuit / Polubarinova-Kochina / Boussinesq 1904, multi-solveurs (NWT+MF6+Boussinesq). Couvre steady & transient unconfined correctement. |
| 7 | **MCP Fischer-Burmeister dans Boussinesq** | 05 | `φ(a,b) = √(a²+b²) - a - b` mathématiquement correcte (Facchinei-Pang 2003). Gère proprement zones sèches et seepage. Jacobien semianalytique via factorisation triplets. |
| 8 | **`SGridConfig` & `ZoneMeshingSettings`** | 10 | Références-qualité du projet : `Literal` partout, cross-field validation exhaustive, `lay_proportions` vérifiée à 1e-6 près. Ce que tous les modèles Pydantic devraient ressembler. |
| 9 | **Workspace auto-discovery + `output_root` séparable** | 02 | Pattern proche cookiecutter-data-science, walk-up pour trouver la racine, redirection des gros outputs vers `/scratch`. Workflow HPC-aware. |
| 10 | **Goldens statistiques robustes aux plateformes** | 09 | Signatures `{count, mean, p50, p95, shape, sum}` finite-only avec tolérances explicites. Résistent à BLAS/endianness/threads. Mécanisme `--update-goldens` documenté. |

---

## 3. Top 10 dettes techniques — classées par impact × effort

Échelle impact : **bloquant** (empêche usage correct) / **majeur** (dégrade sérieusement) / **mineur** (polish).
Échelle effort : **facile** (<1 j-dev) / **moyen** (1–5 j-dev) / **hard** (>5 j-dev).

| # | Dette | Impact | Effort | Rapport | Action ciblée |
|---|---|:---:|:---:|:---:|---|
| 1 | **BC `stream→CHD` / `ocean→CHD` / drain sans épaisseur de lit** | **Bloquant** | Moyen | 05 | `stream→RIV`, `ocean→GHB`, `C_drain = K·A/b`. Touche `solver/modflow_common/forcing_discretization.py`. Bug de bilan de masse sur bassin côtier. |
| 2 | **Moyenne K arithmétique dans `WeightedAverageFieldDiscretization`** | **Bloquant** | Facile | 04 | Ajouter paramètre `aggregation: Literal["arithmetic","harmonic","geometric"]`. Pour K vertical en strates, erreur d'un ordre de grandeur sur K_eff quand K₁/K₂ > 100. |
| 3 | **Confusion porosité effective ↔ Sy en transport** | **Bloquant** | Facile | 05 | MT3DMS et MF6-GWT reçoivent `Sy` comme porosité. Pour un sable Sy≈0.20 vs n_e≈0.30 → 50 % d'erreur sur vitesses advectives, donc sur temps de transit (contamination). |
| 4 | **APIs réseau non durcies (urlretrieve sans timeout, pas de 429, `resp.json()` nu)** | **Bloquant** | Moyen | 03 | Wrapper `HTTPClient` unique avec `Retry(status_forcelist=[429,500,502,503,504])` + timeout + validation Pydantic. Sinon batch régional inexploitable. |
| 5 | **Tests unit `solver/boussinesq/runtimes/` cassés par imports post-merge** | **Bloquant** | Facile | 05, 09 | `test_boussinesq_backend.py` importe `jacobian_fd`, `local_runtime`, `petsc_runtime` (renommés en `jacobian/fd`, `runtimes/local`, `runtimes/petsc_mixed`). **Le cœur numérique n'a plus de filet unitaire.** |
| 6 | **Duplication `boussinesq.py` vs `forcing/` + `runtime_summary.py` (~700 lignes)** | Majeur | Moyen | 05 | Le refactor a extrait les sous-modules sans nettoyer le monolithe. `_resolve_recharge`, `_record_surface_threshold_summary`, etc. vivent en double. |
| 7 | **Duplication `data/variables/*/config.py` (~800 lignes)** | Majeur | Moyen | 10 | 6 fichiers (etp, humidity, runoff, soil_moisture, temperature, wind) à 95 % identiques. Créer `TimeseriesSourceConfig` + mixins → gain ~800 lignes. |
| 8 | **Classe `Simulation` (project.py) : God class, bypass du planner** | Majeur | Hard | 06 | 16 responsabilités en 705 lignes. `_run_with_overrides` construit un `SimulationPlan` à la main en contournant le `SimulationPlanner`. À réduire à un wrapper mince sur `execute_simulation()`. |
| 9 | **NetCDF non CF-1.8 + UGRID non respecté** | Majeur | Moyen | 07, 08 | Pas de `Conventions="CF-1.8"`, `standard_name`, `grid_mapping`, `units="Meter"` invalide UDUnits. UGRID cell-based est format maison. Bloque THREDDS, Panoply strict, xugrid. |
| 10 | **`core/config/hydromodpy_config.py` importe 13 modules de 7 packages** | Majeur | Hard | 01 | Viole la règle « core feuille » annoncée. Cycle latent. Rendre `core` réellement feuille via imports lazy dans fabriques. |

**Lot bonus** (dettes secondaires chiffrées mais pas top-10) :
- Bug `exporters/vtu.py:_split_cell_data` — mesh mixte tri/quad, données associées aux mauvaises cellules ParaView (rapport 07).
- Heuristique `n_per ∈ [12,6,4,3,2,1]` dans `catchment_aggregation.py` — casse sur 7/11/13 périodes (rapport 06).
- 5 tables DuckDB sans PK (`timeseries`, `budgets`, `mass_balance`, `observation_points`, `provenance`) — doublons silencieux (rapport 07).
- ~3 700 lignes dead code dans `spatial/` (`geographic/pipeline.py`, `synthetic/`, `cartesian_grid/examples/`) — rapport 04.

---

## 4. Problèmes critiques — bloquants avant toute release publique

> Un **bloquant pre-release** est un défaut qui produit des résultats scientifiquement faux, une perte de données, une exposition à un bug silencieux, ou un crash prévisible.

### 4.1 Bugs physiques — résultats faux possibles

| # | Bug | Preuve | Conséquence |
|---|---|---|---|
| **C1** | `stream → CHD` (doit être RIV) | `solver/modflow_common/forcing_discretization.py` — rapport 05 §2.2 | Débit rivière incorrect dès que nappe > stage. Bilan de masse faux sur bassin versant. |
| **C2** | `ocean → CHD` (doit être GHB) | idem | Pas d'oscillation tidale amortie, pas d'inversion drain/recharge selon marée. Modèle côtier non représentatif. |
| **C3** | Conductance drain `C = K·A` (doit être `K·A/b`) | `solver_mesh.py` — rapport 05 §2.2 | Surestime la conductance d'un facteur 1/b. Débits drain faux. |
| **C4** | Moyenne K arithmétique au lieu d'harmonique | `spatial/field/core/field_param.py:745-749` — rapport 04 §5.1 | Pour K₁/K₂ = 100, erreur > 10× sur K équivalent vertical. Pire dans aquifères stratifiés granite/alluvion. |
| **C5** | `porosity = Sy` dans MT3DMS / MF6-GWT | `solver/modflow_nwt/mt3dms/mt3dms.py`, `solver/modflow6/modflow6.py` — rapport 05 §8.3 | 50 % d'erreur sur vitesses advectives = temps de transit faux = décisions contamination faussées. |
| **C6** | Convention VKA non unifiée NWT (rapport Kh/Kv ou valeur) vs MF6 (toujours valeur) | rapport 05 §8.1 | Discordance potentielle d'un facteur 10⁰ à 10⁴ entre runs NWT et MF6 sur le même TOML. |
| **C7** | `bf.HeadFile(...)` sur fichier `.tif` | `solver/modflow6/modflow6.py:2861` — rapport 05 §4.2 | Copier-coller erroné. Crash à l'exécution transport. |
| **C8** | `mass_accumulated = cumsum(mass_seepage)` sans multiplication par `dt` | `simulation/results/extractors/derived.py` — rapport 06 §6.1 | Masse cumulée dimensionnellement fausse quand timesteps non uniformes. |

### 4.2 Bugs silencieux — pertes de données / résultats faux non détectés

| # | Bug | Preuve | Conséquence |
|---|---|---|---|
| **C9** | `exporters/vtu.py:_split_cell_data` associe mauvaises cellules dans ParaView | rapport 07 §4.2 | Visualisation fausse sans erreur. Mesh mixte tri/quad obligatoire dès qu'il y a contraintes gmsh. |
| **C10** | Heuristique `n_per ∈ [12,6,4,3,2,1]` dans `catchment_aggregation.py` | `simulation/results/extractors/catchment_aggregation.py` — rapport 06 §5.7 | Si `n_head = 7` (mensuel sur 7 mois), aucun diviseur ne matche → `nstp=1, n_per=7` mais faux pour substeps. |
| **C11** | 5 tables DuckDB sans PK (`timeseries`, `budgets`, `mass_balance`, `observation_points`, `provenance`) | `results/catalog_schema.py` — rapport 07 §2.1 | Re-run d'une sim insère des doublons silencieux qui faussent toutes les agrégations. |
| **C12** | `import_simulation` branches if/else identiques | `results/catalog.py:831-838` — rapport 07 §8.2 | Intention `.zarr.zip` vs `.zarr` directory perdue. Import packagé partiellement cassé. |
| **C13** | `_SENTINEL_THRESHOLD = -50.0` dans `derived.py` | rapport 06 §6.2 | Bassin côtier (DEM négatif, Pays-Bas, polders) : WT elevation tronqué silencieusement. |
| **C14** | `_watertable_elevation` fallback `z_interfaces[0]` (valeur constante) | `results/virtual_fields.py` — rapport 07 §9.1 | Si `surface_top` manque, calcule `watertable_depth` faux sans erreur. |
| **C15** | Validation physique absente sur K, Sy, Ss, n, vka | rapport 10 §12 | `K = -1 m/s` ou `Sy = 2.0` acceptés par Pydantic. Divergence au solveur avec message obscur. |
| **C16** | Exceptions avalées (`except Exception: pass`, ~20 occurrences) | rapports 03, 05, 06, 07 | Bugs masqués partout (BRGM download, catalog write, VTU export, derived computation). Debug catastrophique. |

### 4.3 Risques opérationnels

| # | Risque | Preuve | Conséquence |
|---|---|---|---|
| **C17** | `urllib.request.urlretrieve` sans timeout (BRGM 50k/1M, IGN BD ALTI) | `variables/geology/apis/brgm_*.py`, `variables/dem/apis/ign_bdalti.py` — rapport 03 §5 | Blocage infini sur serveur lent. CI qui pend. |
| **C18** | Pas de HTTP 429 sur Hub'Eau (limite ~1 000 req/jour) | rapport 03 §5.1 | Batch régional (>10 bassins) plante sur rate-limit sans retry. |
| **C19** | DuckDB sans `BEGIN/COMMIT` explicite dans les écritures | rapport 03 §4.3, rapport 07 §7 | Crash mid-write en batch multi-processus → corruption cache. |
| **C20** | Pas de `schema_version` sur `data/cache.duckdb`, MIGRATIONS dict vide sur `hydromodpy.duckdb` | rapport 03, rapport 07 §2.5 | Tout upgrade schéma casse les workspaces existants silencieusement. |

**Verdict section 4** : **les points C1–C8 rendent le projet non-publiable pour un usage certifié** (aide à la décision réglementaire). C9–C16 exigent correction avant toute publication ESSD/HESS. C17–C20 bloquent le déploiement multi-utilisateur / HPC.

---

## 5. Code mort — à supprimer

Inventaire consolidé. Les chiffres (lignes) sont des estimations de suppression nette sans perte fonctionnelle.

| # | Élément | Chemin | Lignes | Rapport | Action |
|---|---|---|:---:|:---:|---|
| 1 | `hydromodpy/exceptions.py` | racine | 30 | 01 | Zéro `raise`, zéro import. **Supprimer.** |
| 2 | `hydromodpy/data/climatic/climatic.py` | data | 618 | 03 | Déprécié avec warning explicite. **Supprimer.** |
| 3 | `hydromodpy/data/climatic/sim2_API.py` | data | 282 | 03 | Helper du précédent. **Supprimer.** |
| 4 | `hydromodpy/data/climatic/driasclimat.py` + `driaseau.py` + `safransurfex.py` | data | 845 | 03 | Référencés uniquement par `watershed.py` legacy. **Archiver.** |
| 5 | `hydromodpy/core/tools/folder_root.py` | core | 149 | 02 | `input()` bloquant, `HYDROMODPY_RESULTS` non-documenté, blocs commentés. **Supprimer.** |
| 6 | `hydromodpy/core/tools/io_utils.setup_paths` + `extract_watershed` + `load_simulation_results` | core | ~200 | 02 | Hardcode `examples_legacy/`, format pré-Simulation-Catalog, wrapper legacy. **Supprimer.** |
| 7 | `hydromodpy/core/tools/visualization.py` | core | 315 | 02 | Plots d'example (cmap jet, années hardcodées). **Déplacer** vers `examples/shared/`. |
| 8 | `hydromodpy/spatial/geographic/pipeline.py` | spatial | 521 | 04 | Wrapper legacy redondant avec `core/domain_geographic_pipeline.py`. **Fusionner ou supprimer.** |
| 9 | `hydromodpy/spatial/geographic/synthetic/*` | spatial | ~300 | 04 | Non référencé dans tests de régression. **Supprimer** ou publier cas régression. |
| 10 | `solver/utils/mesh/cartesian_grid/examples/*` | solver | ~2 700 | 04 | Aucun import production. **Déplacer** vers `docs/examples/`. |
| 11 | `solver/utils/mesh/gmsh_grid/zone_meshing/_gmsh_driver.py` | solver | 35 | 04 | Façade pure (ré-export). **Supprimer.** |
| 12 | `solver/utils/mesh/gmsh_grid/zone_meshing/_geometry_cleaning.py` | solver | 68 | 04 | Façade pure. **Supprimer.** |
| 13 | `solver/utils/mesh/gmsh_grid/zone_meshing/_refinement_policy.py` | solver | 40 | 04 | Façade pure. **Fusionner** dans `_refinement_resolution.py`. |
| 14 | `solver/boussinesq/smoothing.py` | solver | 170 | 05 | Zéro appel depuis `assembly/` ou `jacobian/`. **Supprimer.** |
| 15 | Duplication `_resolve_*` dans `solver/boussinesq/boussinesq.py` | solver | ~700 | 05 | Extraction post-merge non nettoyée. **Supprimer** dans le monolithe, conserver dans `forcing/`. |
| 16 | `solver/contracts.py` + `process/contracts.py` | solver/process | ~50 | 05 | Re-export purs, 2 consommateurs, 4 chemins d'import parallèles. **Unifier.** |
| 17 | `solver/modflow6/flow_to_modflow_adapter.py` | solver | ~200 | 05 | Fonctions jamais appelées (dupliquées dans les méthodes de classe). **Supprimer ou utiliser.** |
| 18 | `solver/base/Solver.validate_config/get_results/cleanup` | solver | ~30 | 05 | Hooks jamais appelés. **Supprimer.** |
| 19 | `hydromodpy/workflow/pipelines/process_simulation.py` | workflow | 33 | 06 | Re-exports uniquement, commentaire explicite « has been removed ». **Supprimer.** |
| 20 | `hydromodpy/simulation/adapters/display/stub.py` + `postprocess/stub.py` | simulation | 72 | 06 | Jamais enregistrés dans `_ADAPTERS`. **Supprimer.** |
| 21 | `hydromodpy/simulation/adapters/registry.register_adapter` | simulation | ~20 | 06 | API publique jamais appelée. **Supprimer ou utiliser.** |
| 22 | `hydromodpy/results/resample.py` | results | 31 | 07 | Contenu entier = `NotImplementedError`. **Supprimer.** |
| 23 | `hydromodpy/results/Simulation.rerun()` | results | ~40 | 07 | Construit `HydroModPyConfig` puis lève `NotImplementedError`. **Supprimer.** |
| 24 | Alias `record_provenance`, `project_path`, paramètre `mode` inutilisé dans `open_zarr_group` | results | ~5 | 07 | Aliases morts. **Supprimer.** |
| 25 | `hydromodpy/analysis/display/orchestration.py` | analysis | 18 | 08 | Façade de compat une fois `suites.py` stabilisée. **Supprimer.** |
| 26 | `hydromodpy/analysis/display/visualization_results.py` | analysis | 914 | 08 | Monolithe legacy, `plt.switch_backend` à chaud. **Supprimer** après migration 3 cas restants. |
| 27 | `hydromodpy/analysis/display/visualization_watershed.py` | analysis | 469 | 08 | Side-effects globaux à l'import (`plt.style.use`, `rcParams`). **Supprimer.** |
| 28 | `hydromodpy/watershed/` | racine | ~500 | 01, 02 | Façade historique Watershed. **Déprécier puis supprimer** (pair avec mort de `launchers/`). |
| 29 | `__getattr__` de `process/__init__.py` (eager imports rendent la deprecation morte) | process | ~20 | 01 | Inopérant. **Supprimer eager imports** ou supprimer `__getattr__`. |
| 30 | `--normal` flag CLI + suites de goldens `normal/` | CLI + tests | ~50 | 01, 09 | Alias déprécié. **Supprimer.** |
| 31 | `hmp test` sous-commande entière | __main__ | ~300 | 01 | Réinvente pytest. Les tests `test_hmp_regression_cli.py` deviennent obsolètes. **Supprimer.** |
| 32 | `pytest_ignore_collect` dans `tests/conftest.py` | tests | 6 | 09 | Toujours `return False`. **Supprimer.** |
| 33 | Patterns `omit = [hydromodpy/calibration_legacy/*, hydromodpy/calibration2/*]` | pyproject.toml | 2 | 09 | Chemins inexistants. **Nettoyer config coverage.** |

**Total estimé supprimable / déplaçable** : **≈ 9 600 lignes** (≈ 12 % du Python non-test).

---

## 6. Inconsistances inter-modules

### 6.1 Nommage incohérent

| Inconsistance | Endroits | Effet |
|---|---|---|
| **Fichier `project.py` contient la classe `Simulation`** | `hydromodpy/project.py` ; attributs internes `self._project_name` ; usage `with Simulation(...) as project`. 4 mots qui se recouvrent (project, simulation, run, catalog). | Débutant perdu. Import confus. |
| **Deux packages `results/`** | `hydromodpy/results/` (catalog DuckDB+Zarr) vs `hydromodpy/simulation/results/` (extracteurs) | Confusion d'import certaine. |
| **Deux registres d'adapters** | `simulation/adapters/registry.py` (exécution, clé `(proc, solver)`) vs `results/post_run.py::_ADAPTER_REGISTRY` (extracteurs, clé `solver`) | Un solveur ajouté dans l'un sans l'autre = extraction silently skipped. |
| **`type` de BoundaryCondition : majuscule vs minuscule** | `process/base/BoundaryCondition.type = "Dirichlet"` vs `FlowBoundaryConditionConfig.type = Literal["dirichlet",...]` | Conversion casse silencieusement via `model_dump()`. |
| **Nommage `runtime*.py` vs `*_runtime.py`** | `spatial/mesh/runtime*.py` vs `solver/boussinesq/runtime_*.py` | Choisir un suffixe. |
| **Deux noms pour DB workspace** | `workspace/config.discover_workspace_root` cherche `catalog.duckdb` / `catalog.db` ; réalité = `hydromodpy.duckdb` | Workspace detection basée sur `data/` fallback au lieu de la DB attendue. |
| **Convention VKA NWT ≠ MF6** | NWT : rapport Kh/Kv si LAYVKA=1, valeur sinon ; MF6 : toujours valeur | Même TOML donne résultats différents NWT/MF6. |
| **`Geographic` (classe ambiguë)** | Pas de distinction avec `geopandas.Geographic`. Pysheds nomme `Grid`. Whitebox nomme `WatershedDelineation`. | Nom ne décrit pas la fonction. |
| **`SpatialSupport` vs `RasterSupport`** | 2 abstractions proches, noms proches. | Confusion. |
| **`_derive_run_id_from_filename` dupliqué** | `__main__.py` + `core/config/hydromodpy_config.py` | Deux sources de vérité pour la même logique. |

### 6.2 Conventions différentes

| Thème | Incohérence | Exemple |
|---|---|---|
| **Typage dates** | Parfois `str`, parfois `datetime`, parfois `pd.Timestamp` naïf | `simulations.period_start VARCHAR` vs `timeseries.timestamp TIMESTAMP` DuckDB. `BaseVariableConfig.date_start: str`. `SimulationTimeConfig.start_datetime: datetime`. |
| **Typage CRS** | `str` partout (jamais `pyproj.CRS`) | `StationLocation.crs: str`, `FieldRecord.crs: str`, `SyntheticGridConfig.crs = "EPSG:2154"` codé en dur. Typo passe silencieusement. |
| **Unités** | Système maison 5 modules (1085 lignes) vs pint vs cf-units | `length.py` importe pint mais seul 1/7 module l'utilise. Aucune dimensional analysis globale. |
| **Sérialisation Path** | `model_dump(mode="python")` → `PosixPath`, `mode="json")` → str absolu | Round-trip TOML casse si on déplace le TOML. |
| **Gestion exceptions** | `except Exception: pass` vs `except Exception: logger.debug` vs `except SpecificError` | Debug catastrophique partout (rapports 03, 05, 06, 07). |
| **Validation physique** | Exemplaire dans `analysis/calibration/cases/` ; absente dans `spatial/field/core/field_param_config.py` | Savoir-faire présent mais non propagé. |
| **Module config** | Convention `*_config.py` bien respectée dans `data/variables/*/` ; cassée dans `core/config/hydromodpy_config.py` (préfixe manquant) | À aligner. |
| **Signature `extract(...)` des extracteurs** | NWT a `hdry`, `hnoflo` kwargs ; Boussinesq n'a pas `budget_spatial_fields` ; fallback `try/except TypeError` | Masque les vrais TypeError. |

### 6.3 Interfaces incompatibles

| Interface | Problème | Rapport |
|---|---|---|
| `process/base/ProcessSpatialConfig` | `ic`, `bc`, `param`, `sinks_sources` tous en `object`/`dict[str, object]` → Flow et Transport redéfinissent 100 % des champs | 10 |
| `Transport` vs `ProcessSpatial` | `Transport` utilise `Field(exclude=True)` pour désactiver les champs hérités. Pattern *inheritance-then-exclude* = aveu de mauvaise base | 05 |
| `process/contracts.py` | 29 lignes de re-export pur. Appelé par 2 modules sur 4 | 05 |
| `SolverAdapter` Protocol | Déclare `execute` ; `validate`/`cleanup` documentés mais jamais appelés par runner | 06 |
| `Store` duck-typé | Passé comme `Any` dans extracteurs. Pas de Protocol typé | 01, 06 |
| `ProcessCallbacks.after_run(run, result, state)` | Paramètres typés vaguement, contrat implicite | 01 |

---

## 7. Conformité aux standards — tableau par domaine

| Standard | Status | Preuve / justification | Rapport |
|---|:---:|---|:---:|
| **PEP 8** (nommage) | 🟡 Acceptable | Quelques noms discutables (`SinkSource`, `HydroModPyConfig` ok). Pas de ruff/black configuré. | 01 |
| **PEP 257** (docstrings) | 🟡 Acceptable | Classes publiques couvertes, fonctions internes nues. | 01 |
| **PEP 561** (typing) | 🔶 À améliorer | `Any` fréquent (`store: Any`, `**overrides`), pas de `py.typed`, Protocols manquants. | 01, 06 |
| **PEP 562** (`__getattr__` module) | ✅ Conforme | Utilisé correctement 5× ; un bug inopérant dans `process/__init__.py`. | 01 |
| **PEP 621** (`pyproject.toml`) | ✅ Conforme | `[project]`, `[project.scripts]`, `[tool.setuptools]` OK. | 01 |
| **PEP 544** (Protocol) | ✅ Conforme | `SolverAdapter` vrai structural typing. | 06 |
| **SemVer** | 🟡 Acceptable | `0.3.5` format OK. Changelog structuré absent. | 01 |
| **PROV-O (W3C)** | 🔴 Non-standard | Provenance = SHA-256 sur tobytes() post-parsing (≠ fichier source). Pas de `wasDerivedFrom`, `wasAttributedTo`. | 07 |
| **FAIR principles** | 🔶 À améliorer | Pas de DOI, pas de versioning schéma, pas de licence dans metadata. | 07 |
| **CF-conventions 1.8 (NetCDF)** | 🔴 Non-conforme | Pas de `Conventions="CF-1.8"`, pas de `standard_name` sur variables, `units="Meter"` invalide UDUnits, pas de `grid_mapping`. | 07, 08 |
| **UGRID 1.0 (maillages non structurés)** | 🔶 Partiel | Zarr `mesh/` a la bonne structure (`face_node_connectivity`, `_FillValue=-1`) mais attributs CF (`cf_role="mesh_topology"`, `topology_dimension`) absents. Export NetCDF cell-based = format maison. | 04, 07, 08 |
| **OGC SensorThings API** | 🔴 Non-standard | Stations en CSV LOC propriétaire. Pas de `Thing`/`Location` GeoJSON. | 03 |
| **OGC GeoPackage** | 🔴 Non-adopté | Shapefile utilisé (obsolète 1994). Troncature noms DBF > 10 chars silencieuse. | 03, 07 |
| **WaterML 2.0** | 🔴 Non-adopté | Aucun export. Pour partage hydro standard : manque critique. | 03 |
| **Frictionless Data Package** | 🔴 Non-adopté | CSV sans `datapackage.json` ni header metadata. | 03, 07 |
| **MODFLOW-6 DIS/DISV** | ✅ Conforme | Adapter FloPy MF6 respecte 0-based indexing, ordre CW vertices. | 04 |
| **MODFLOW-6 DISU** | 🔶 Partiel | Non implémenté. `_recarray_to_grid` suppose DIS/DISV uniquement. | 04, 06 |
| **MODFLOW-NWT (options)** | 🟡 Acceptable | `headtol`, `fluxtol`, `thickfact`, `linmeth`, `options SIMPLE/MODERATE/COMPLEX` exposés. `momfact`, `backflag` partiels. | 05 |
| **MODFLOW standard packages** | 🔶 Partiel | CHD/DRN/WEL/RCH/EVT OK. **Absents** : RIV (critical bug), GHB (critical bug), MAW, LAK, SFR, UZF, MVR. | 05 |
| **MODPATH 7** | 🔴 Non-adopté | MODPATH 6 only. Bloque DISV + MF6 pour particle tracking. | 05 |
| **Crameri 2020 (colormaps perceptuelles)** | 🔴 Non-conforme | 6 `cmap='jet'` dans code actif (seepage, WTD, residence times, pathlines). | 08 |
| **Pangeo / ERA5 (chunking Zarr)** | 🔶 Partiel | BLOSC-ZSTD clevel=3 conforme. Chunking `(1, n_layers, n_cells)` optimisé carte, pathologique timeseries. Pas de byte-shuffle. Zarr v3 ferme QGIS/ParaView. | 07 |
| **Method of Manufactured Solutions (MMS)** | 🔴 Absent | Aucune validation d'ordre de convergence. Tolérances fittées a posteriori. | 09 |
| **Benchmarks MODFLOW classiques** | 🔶 Partiel | Dupuit/Boussinesq/Brutsaert présents. **Absents** : Theis (1935), Hantush-Jacob (1955), Boulton (1963), Neuman (1972), Ogata-Banks transport. | 09 |
| **CF-NetCDF via xarray** | 🔶 Partiel | `NetcdfWriter` attache CRS via `rioxarray.write_crs` ; manque les attributs CF globaux. Décodage manuel au lieu de `xarray.decode_cf`. | 02, 08 |
| **DuckDB FK / migrations** | 🔴 Non-adopté | Zéro FK déclarée (DuckDB 0.9+ les supporte). `MIGRATIONS` dict vide. | 07 |
| **POSIX exit codes CLI** | 🟡 Acceptable | 0/1/2 respectés par hasard, pas documentés. | 01 |
| **HTTP retry/backoff/timeout** | 🔴 Problématique | `urllib.request.urlretrieve` sans timeout, pas de 429 Hub'Eau, `resp.json()` nu. | 03 |
| **Pydantic v2 idioms** | ✅ Conforme | `field_validator`, `model_validator`, `ConfigDict` systématiques. Aucun reste v1. | 10 |

**Verdict conformité** : le projet **adopte les standards modernes du langage Python** (PEP) mais **échoue largement sur les standards métier** (CF, UGRID, WaterML, OGC, PROV-O) et partiellement sur les standards hydrogéologiques (MODFLOW packages manquants, MODPATH 7, MMS). Pour un outil qui prétend à l'interopérabilité scientifique, **c'est la principale dette stratégique**.

---

## 8. Renommages nécessaires

| # | Nom actuel | Nom proposé | Justification |
|---|---|---|---|
| 1 | `hydromodpy/project.py` (contenant `class Simulation`) | `hydromodpy/simulation/api.py` (ou déplacer dans le package `simulation/` existant) | Dissonance fichier/classe. Le fichier s'appelle `project`, la classe `Simulation`, l'attribut `self._project_name`, l'usage `with Simulation() as project`. Quatre mots qui se recouvrent. |
| 2 | `hydromodpy/simulation/results/` | `hydromodpy/simulation/extraction/` ou `simulation/postrun/` | Conflit sémantique avec `hydromodpy/results/` (catalog). |
| 3 | `Geographic` (classe) | `CatchmentDelineation` ou `CatchmentGeographicPipeline` | Nom vague, faux ami avec `geopandas`. Pysheds=`Grid`, whitebox=`WatershedDelineation`. |
| 4 | `SpatialSupport` | `GriddedFieldSupport` | Lever l'ambiguïté avec `RasterSupport`. |
| 5 | `hydromodpy/core/backends/` | `hydromodpy/core/whitebox/` | Pluriel qui ne tient pas (un seul backend). |
| 6 | `runners/templates/` | `analysis/calibration/templates/` | Contenu métier, pas thin shell CLI. |
| 7 | `solver/modflow6/flow_to_modflow_adapter.py` + `solver/modflow_nwt/...` | `flow_to_modflow_translator.py` + factorisation `modflow_common/flow_translator.py` | Homonymie dangereuse avec adapters `(Process, Solver)`. |
| 8 | `SinkSource` (process.base) | `SourceTerm` | Standard PDE. Plus conforme conventions mathématiques. |
| 9 | `process/` (top-level) | `process/` garder OU `physics/` | « Process » polysémique (Python multiprocessing). « Physics » DDD-aligné. Choix éditorial. |
| 10 | Préfixe `Schema` (`FieldHomogeneousSectionSchema`, `ZoneMeshingSettings...Schema`) | Retirer le suffixe → `…Config` | Reliquat Pydantic v1 où `Schema()` remplaçait `Field()`. Décoratif. |
| 11 | `fast` / `extensive` markers pytest | `tier_short` / `tier_full` | Marker `fast` avec timeout=3600 s est mensonger. |
| 12 | `catch_name` property de `WorkspaceConfig` | `project_name` | Relique « catchment » dans classe généraliste. |
| 13 | `hydromodpy_config.py` (dans `core/config/`) | `aggregate_config.py` ou `root_config.py` | Convention `foo_config.py` cassée. |
| 14 | `rmse_manual`, `nse_manual`, `kge_manual` | `rmse`, `nse`, `kge` | Suffixe `_manual` suggère versions non-manuelles inexistantes. |
| 15 | `core/config/hydromodpy_config.py:__DEM_API_BOOTSTRAP__` (sentinelle magique) | `dem_bootstrap: bool = False` + `Optional[Path]` | Casse la sémantique du type `Path`. |
| 16 | `_ensure_simulation_block` | Déplacer vers `SimulationConfig.ensure_defaults()` | Nom de kludge. |
| 17 | `workspace.catalog.duckdb` vs `hydromodpy.duckdb` | Harmoniser sur `hydromodpy.duckdb` partout | Workspace discovery regarde le mauvais nom. |
| 18 | `display/orchestration.py` (façade) | Supprimer, exposer `suites.py` directement | Compat layer dormante. |
| 19 | `Modflow6SpecifParams` / `ModflowSpecifParams` dataclasses | Supprimer au profit de `model.model_dump()` | Dupliquent les Pydantic configs. |
| 20 | `simulations.solver_category` colonne DuckDB | Vue SQL `view_solver_category` | Dénormalisation non justifiée. |

---

## 9. Réorganisation suggérée

### 9.1 Arbre actuel (simplifié, post-merge)

```
hydromodpy/
├── __init__.py              (lazy imports PEP 562, 250 l)
├── __main__.py              (God module CLI, 1 223 l) ❌
├── project.py               (class Simulation, 705 l) ❌
├── exceptions.py            (code mort, 30 l) ❌
├── watershed/               (façade historique legacy) ❌
├── core/                    (infrastructure... mais feuille violée)
│   ├── config/              (hydromodpy_config.py importe 13 modules ❌)
│   ├── state/, time/, units/, tools/, workspace/, backends/
│   └── tools/               (fourre-tout : io_utils, visualization, folder_root ❌)
├── data/
│   ├── climatic/            (legacy) ❌
│   ├── common/, registry/
│   └── variables/
│       ├── dem/, hydrography/ (hors BaseVariableManager)
│       ├── geology/           (ad-hoc)
│       └── {etp,humidity,...}  (95 % copiés)
├── spatial/
│   ├── geographic/          (3 pipelines parallèles ❌)
│   ├── domain/, field/, mesh/, surface/
│   └── synthetic/           (non testé) ❌
├── process/                 (base, flow, transport, forcing, hydrology, contracts)
├── solver/
│   ├── base/, modflow_nwt/, modflow6/, modflow_common/
│   ├── boussinesq/          (50 fichiers, 7 niveaux d'indirection ❌)
│   │   ├── assembly/ drivers/ forcing/ jacobian/ runtimes/ methods/ engines/ formulations/
│   └── utils/
│       ├── mesh/            (cartesian_grid, gmsh_grid, zone_meshing) ❌ devrait être sous spatial/
│       └── temporal/
├── simulation/              (adapters, planning, execution, results, forcing, settings)
│   └── results/             (extracteurs — COLLISION avec hydromodpy/results/) ❌
├── results/                 (catalog DuckDB+Zarr, exporters)
├── analysis/                (calibration, comparison, batch, display, postprocess, capability_gallery)
│   └── display/             (8 850 l : 2 640 l legacy, duplication suites/posthoc ❌)
├── workflow/                (pipelines, steps, context — 3 orchestrateurs concurrents ❌)
├── runners/                 (thin shells OK ✅, mais templates/ à l'intérieur ❌)
└── annex/, cases/           (peripheral)
```

### 9.2 Arbre proposé (2 ans d'effort)

```
hydromodpy/
├── __init__.py                    (lazy, API publique minimale)
├── cli/                           ← éclater __main__.py
│   ├── __init__.py                (parser argparse, 80 l)
│   ├── commands/                  (1 fichier par verbe : run.py, config.py, init.py, new.py, list.py, display.py, export.py)
│   └── completion.py              (argcomplete)
│
├── core/                          ← RÉELLEMENT feuille, aucun import vers les couches supérieures
│   ├── config/
│   │   ├── aggregate_config.py    ← renommage de hydromodpy_config.py
│   │   ├── param_level.py, generate_toml.py, streamlit_config.py
│   │   └── pydantic_introspect.py (factorise helpers dédupliqués)
│   ├── state/ time/ units/ workspace/ whitebox/ (renommage backends/)
│   └── tools/                     (SEULEMENT infrastructure : log_manager, raster_io léger, statistics)
│
├── data/                          ← pas de legacy climatic
│   ├── common/, registry/
│   └── variables/
│       ├── common/timeseries_source.py   ← TimeseriesSourceConfig mutualisé
│       ├── dem/, geology/, hydrography/  (spécifiques, héritent d'un BaseSpatialManager)
│       ├── oceanic/, water_quality/       (spécifiques)
│       ├── hydrometry/, piezometry/, intermittency/, recharge/  (mixins sur TimeseriesSource)
│       └── {etp,humidity,runoff,soil_moisture,temperature,wind,precipitation,radiation}/  (≤10 l chacun)
│
├── spatial/
│   ├── geographic/                (UN seul pipeline, pas 3)
│   │   └── delineation.py         (ex-Geographic renommé CatchmentDelineation)
│   ├── domain/, field/
│   ├── mesh/
│   │   ├── cartesian/             ← ex solver/utils/mesh/cartesian_grid/
│   │   ├── gmsh/                  ← ex solver/utils/mesh/gmsh_grid/ + zone_meshing consolidé
│   │   └── quality.py             (mesh_quality : CCW, angle, aspect ratio)
│   └── surface.py
│
├── physics/                       ← ex process/, renommé pour éviter polysémie multiprocessing
│   ├── base/ (Protocol + dataclass)
│   ├── flow/
│   │   └── forcing/               (mutualisé, ex boundary+wells)
│   └── transport/
│
├── solver/
│   ├── base/, contracts.py
│   ├── modflow_common/            ← factorisation NWT + MF6
│   │   ├── flow_translator.py     ← ex flow_to_modflow_adapter (renommé)
│   │   ├── boundary_packages.py   (RIV, GHB, DRN avec bonne physique)
│   │   └── forcing_discretization.py
│   ├── modflow_nwt/, modflow6/
│   └── boussinesq/                ← aplati
│       ├── api.py, contracts.py
│       ├── discretization.py (space+time)
│       ├── assembly.py, jacobian.py (3 fichiers, pas 5)
│       ├── runtimes.py   (local | scipy | petsc paramétrés, pas 5 fichiers)
│       └── forcing.py    (mutualisé)
│
├── simulation/                    ← ex-simulation/ sans double 'results/'
│   ├── api.py                     ← ex project.py (classe Simulation mince)
│   ├── planning/                  (SimulationPlan, Planner)
│   ├── execution/                 (SimulationRunner)
│   ├── adapters/                  (SolverAdapter registry)
│   ├── extraction/                ← ex simulation/results/ (extracteurs + derived)
│   └── workflow/                  ← ex hydromodpy/workflow/steps/ + pipelines/
│       └── steps.py, pipelines.py
│
├── results/                       ← UNIQUE "results" (catalog + exporters)
│   ├── catalog/                   ← ex catalog.py éclaté
│   │   ├── catalog.py (150 l : lifecycle)
│   │   ├── writes.py, queries.py, geographic.py, package.py
│   ├── zarr_store.py, schema.py
│   ├── simulation.py, simulation_group.py
│   └── exporters/
│       ├── _mesh_loader.py        (factorisé)
│       ├── netcdf.py (CF-1.8 + UGRID stricts)
│       ├── geotiff.py (COG)
│       ├── gpkg.py  ← remplace shapefile.py (conservé en legacy)
│       ├── vtu.py (bug _split_cell_data corrigé)
│       └── csv.py (+ datapackage.json sidecar)
│
├── analysis/
│   ├── calibration/   (propre, exemplaire — rien à bouger)
│   ├── comparison/, batch/
│   ├── display/
│   │   ├── figures/               (primitives render/plot, SEUL endroit)
│   │   ├── common.py
│   │   ├── suites.py              (UN orchestrateur, pas 3)
│   │   └── overview.py            ← ex-sous-package report/ aplati
│   └── postprocess/
│       ├── timeseries/
│       └── netcdf/
│
└── runners/                       (thin shells, 10-30 l chacun)
```

**Changements structurels clés** :
- `solver/utils/mesh/` → `spatial/mesh/` (inversion de la dépendance interdite).
- `simulation/results/` → `simulation/extraction/` (lève la collision avec `results/`).
- `project.py` → `simulation/api.py` + classe réduite de 705 → ~150 lignes.
- `watershed/` : déprécié puis supprimé.
- Nouveau `physics/` (ex-`process/`) : évite polysémie.
- Pas de `hydromodpy/cases/` à la racine : migre sous `validation_cases/` (déjà top-level).

---

## 10. Plan d'action 3 mois — ROADMAP CHIFFRÉE

Périmètre 3 mois, ressource présumée : **1 senior dev + 1 junior + 0.5 architecte (revue)**.
Estimations en **jours-développeur** (j-dev).

### Sprint 1 — Quick wins (2 semaines, ~20 j-dev)

**Objectif** : supprimer les bugs bloquants et le code mort évident. Stabiliser la base avant de refactorer.

| # | Action | j-dev | Impact |
|---|---|:---:|---|
| 1.1 | **Corriger BC `stream→RIV`, `ocean→GHB`, `drain C=K·A/b`** (rapport 05, C1–C3). Ajouter tests de bilan de masse bassin côtier. | 3 | Bloquant levé |
| 1.2 | **Corriger confusion porosité ↔ Sy** (MT3DMS, MF6-GWT, MODPATH). Ajouter `effective_porosity` dans TransportConfig (C5). | 2 | Bloquant levé |
| 1.3 | **Ajouter moyenne harmonique K** dans `WeightedAverageFieldDiscretization` + paramètre `aggregation: Literal[...]` (C4). | 2 | Bloquant levé |
| 1.4 | **Réparer tests unit `test_boussinesq_backend.py`** : sed des anciens chemins vers `jacobian/fd`, `runtimes/local`, etc. (C cœur numérique). | 0.5 | Bloquant levé |
| 1.5 | **Fixer bug `bf.HeadFile` sur `.tif`** (C7), bug `_split_cell_data` VTU (C9), bug if/else identique `import_simulation` (C12), heuristique `n_per` (C10). | 2 | Bugs silencieux levés |
| 1.6 | **Wrapper HTTP unique** (`HTTPClient` avec Retry 429/500/502/503/504 + timeout + try JSON) migrer BRGM/IGN/Hub'Eau/SHOM/SIM2 (C17, C18). | 3 | Bloquant levé |
| 1.7 | **Supprimer code mort sûr** : `exceptions.py`, `climatic/climatic.py`, `climatic/sim2_API.py`, `folder_root.py`, `resample.py`, `rerun()`, `workflow/pipelines/process_simulation.py`, stubs display/postprocess, `smoothing.py` non branché. | 2 | ~2 500 lignes retirées |
| 1.8 | **Remplacer `cmap='jet'` 6× → `viridis`/`plasma`/`cividis`/`tab10`** dans `figures/spatial.py`, `figures/maps.py`, `suites.py`, `posthoc_orchestration.py`. | 0.5 | Qualité publication |
| 1.9 | **Supprimer `plt.style.use` / `rcParams` top-level dans `visualization_watershed.py`** et `plt.switch_backend("QtAgg")` dans `visualization_results.py`. | 0.5 | Headless CI OK |
| 1.10 | **Ajouter bornes physiques** K, Sy, Ss, n, vka via `physical_bounds.py` (C15). | 2 | Validation config robuste |
| 1.11 | **Ajouter PK manquantes** sur `timeseries`, `budgets`, `mass_balance`, `observation_points`, `provenance` (C11). Migration schema_version = 2. | 1.5 | Intégrité DuckDB |
| 1.12 | **Supprimer `hmp test` CLI + tests associés** (~300 l). Documenter pytest natif dans README. | 0.5 | Moins de fragilité |
| 1.13 | **Nettoyage config coverage** (`calibration_legacy`, `calibration2`, `pytest_ignore_collect`, `normal/`). | 0.5 | — |

**Livrable sprint 1** : 18 bugs critiques levés, ~3 000 lignes de code mort retirées, CI stable headless, validation physique active.

---

### Sprint 2 — Refactoring moyen (1 mois, ~40 j-dev)

**Objectif** : rationaliser les structures (duplication, god modules, héritages cassés). Aucun changement d'API publique.

| # | Action | j-dev | Impact |
|---|---|:---:|---|
| 2.1 | **Extraire `_BinaryHeadExtractor`** commun MF6/NWT dans `simulation/results/extractors/modflow_common.py`. Réduction ~200 l. | 2 | -200 l |
| 2.2 | **Supprimer duplication `boussinesq.py` vs `forcing/` + `runtime_summary.py`** (~700 l). Vérifier `validation_cases/` passent. | 3 | -700 l |
| 2.3 | **Factoriser `data/variables/{etp, humidity, runoff, soil_moisture, temperature, wind}`** via `TimeseriesSourceConfig` + mixin. | 3 | -400 l |
| 2.4 | **Factoriser Forcing** dans `process/base/forcing.py` avec discriminated union `ConstantForcing | CsvForcing`. Migrer `FlowBoundaryForcing*` + `FlowWellForcing*`. | 2 | -100 l |
| 2.5 | **Factoriser `clip_raster_to_polygon_normalized`** dans `geographic_io.py` (8 duplications). | 1 | -40 l, cohérence |
| 2.6 | **Éclater `__main__.py` (1 223 l) en `cli/`** avec un fichier par sous-commande. Ajouter `--version`, `argcomplete`. | 3 | CLI moderne |
| 2.7 | **Éclater `results/catalog.py` (920 l)** en `catalog.py` (150) + `writes.py` + `queries.py` + `geographic.py` + `package.py`. | 3 | Maintenabilité |
| 2.8 | **Typer les fields critiques** : `BoundaryCondition.type → Literal`, `FlowRechargeConfig.values → discriminated union`, `TransportInitialConditions.payload`. | 2 | Validation à la construction |
| 2.9 | **Factoriser registres adapters** (`simulation/adapters/registry.py` + `results/post_run._ADAPTER_REGISTRY`). | 1.5 | Une source de vérité |
| 2.10 | **`Simulation.run()` → wrapper mince sur `execute_simulation()`** (éliminer duplication store/register/persist, bypass planner). Classe réduite de 705 → ~150 lignes. | 4 | God class résolue |
| 2.11 | **Supprimer `_gmsh_driver.py`, `_geometry_cleaning.py`, `_refinement_policy.py`** (façades stériles). Fusionner `_domain_geometry.py` dans `_geometry_utils.py`. | 1.5 | -150 l, navigation simplifiée |
| 2.12 | **Migrer validation CRS** via `pyproj.CRS.from_user_input` partout, éliminer strings libres. | 2 | Typo `EPSG:2145` détecté |
| 2.13 | **Supprimer `hydromodpy/watershed/`** (façade legacy). Migrer 3 cas consommateurs. | 2 | -500 l, trois générations → deux |
| 2.14 | **Ajouter `Conventions="CF-1.8"` + `standard_name` + `grid_mapping` + `time` CF** dans `NetcdfWriter` et Zarr arrays. Corriger `units="Meter"` → `"m"`. | 3 | Interop scientifique |
| 2.15 | **Ajouter `BEGIN/COMMIT` explicite** sur écritures DuckDB critiques. `filelock` au niveau workspace. | 2 | Concurrence sûre |
| 2.16 | **Unifier convention VKA** NWT vs MF6 (rapport Kh/Kv ou valeur — choisir et documenter). | 1 | Résultats cohérents |
| 2.17 | **Ajouter tests unit dédiés `solver/boussinesq/runtimes/`** (scipy_sparse, scipy_dense, petsc_mixed, local) + Jacobien FD vs semianalytic. | 3 | Filet cœur numérique |
| 2.18 | **Vectoriser `assembly/fluxes.py` + `jacobian/operator_triplets.py`** (np.add.at). Gain ×50 sur 100k cellules. | 2 | Performance |

**Livrable sprint 2** : ~3 000 lignes supplémentaires en moins (code dédupliqué), 10 God modules réduits à 3–5, CF-1.8 respecté, classe `Simulation` propre, cœur Boussinesq testé unitairement.

---

### Sprint 3 — Changements structurels (1,5 mois, ~60 j-dev)

**Objectif** : architecture cible. Peut impliquer des breaks d'API (à documenter, release 0.4).

| # | Action | j-dev | Impact |
|---|---|:---:|---|
| 3.1 | **Déplacer `solver/utils/mesh/` → `spatial/mesh/`** (inverser la dépendance interdite). Ajuster 30+ imports. | 4 | DAG propre |
| 3.2 | **Renommer `project.py` → `simulation/api.py`**, déplacer `Simulation` dans le package existant. | 2 | Nommage cohérent |
| 3.3 | **Renommer `simulation/results/` → `simulation/extraction/`** (collision avec `results/`). | 1 | Lever ambiguïté |
| 3.4 | **Découpler `core/config/hydromodpy_config.py`** : imports lazy via fabriques. Restaurer « core feuille ». | 5 | Règle architecturale respectée |
| 3.5 | **Ajouter benchmarks Theis (1935) + Hantush (1955) + Ogata-Banks 1D** dans `validation_cases/analytical/`. | 5 | Certifiable aquifère confiné/transport |
| 3.6 | **Introduire 1 MMS** steady 1D (Laplacien avec source fabriquée) + analyse d'ordre de convergence. | 3 | Conformité scientifique |
| 3.7 | **Migrer MODPATH 6 → MODPATH 7** (ouvre DISV + MF6). | 6 | Particle tracking sur DISV |
| 3.8 | **Implémenter RIV, GHB, UZF, SFR, MAW, MVR** côté MF6 (packages manquants). | 8 | Couvre hydrologie réaliste |
| 3.9 | **Remplacer Shapefile par GeoPackage** (exporter primaire). Conserver SHP en legacy. | 2 | Interop OGC moderne |
| 3.10 | **Implémenter UGRID-1.0 strict** dans export NetCDF cell-based (`cf_role`, `topology_dimension`, `face_node_connectivity`). | 3 | Compatible xugrid/Panoply |
| 3.11 | **Implémenter `manifest.json` + zip `.hmp`** + test roundtrip export/import. Corriger bug if/else (C12). | 3 | Format d'échange réel |
| 3.12 | **Décider Zarr v2 vs v3** + `zarr_format: 2|3` dans `ResultsConfig` (défaut v2 jusqu'en 2027). | 1 | QGIS/ParaView compatibles |
| 3.13 | **Adopter `pint` + dimensional analysis** : migrer `hydraulic_conductivity`, `hydraulic_conductance`, `volumetric_flow`, `radiation` (-700 l du code unités maison). | 5 | Sûreté dimensionnelle |
| 3.14 | **Table `run_environment`** (user, host, hmp_version, git_sha, python_ver, pip_freeze). | 2 | Traçabilité FAIR |
| 3.15 | **Intégrer `ruff`** en CI (check only, pas de reformat forcé). | 1 | Qualité code standard |
| 3.16 | **Fragmenter tests unit > 1 500 lignes** (`test_model_calibration_launcher.py` 2 722 l, `test_boussinesq_backend.py` 1 642 l, `test_hydrography_full.py` 1 643 l). | 4 | Maintenabilité |
| 3.17 | **Activer `pytest-xdist -n auto --dist=loadfile`** en CI après validation `pytest_sessionfinish` en mode parallèle. | 1 | CI -30 % |
| 3.18 | **Documenter toutes les tolérances** (`validation_cases/TOLERANCES.md` + Richardson / machine epsilon). | 2 | Défendabilité |
| 3.19 | **Supprimer `watershed/`** définitivement (dépend du 2.13). | 1 | -500 l |
| 3.20 | **Aplatir Boussinesq** : 6 sous-couches (methods, engines, formulations, runtimes, drivers, assembly) → 3 (formulations, jacobian, runtimes). | 5 | Navigabilité |

**Livrable sprint 3** : architecture cible atteinte, conformité CF/UGRID/OGC stricte, benchmarks Theis/Hantush/Ogata-Banks/MMS intégrés, MODPATH 7, RIV/GHB/UZF disponibles.

---

### Récapitulatif effort 3 mois

| Sprint | Durée | j-dev | Livrable clé |
|:---:|:---:|:---:|---|
| 1 | 2 sem | 20 | Bloquants levés, code mort supprimé, validation physique |
| 2 | 4 sem | 40 | Duplication -3 000 l, God modules éclatés, CF-1.8, classe Simulation propre |
| 3 | 6 sem | 60 | Architecture cible, benchmarks certifiants, MODPATH 7, RIV/GHB/UZF, UGRID strict |
| **Total** | **3 mois** | **120 j-dev** | **Passage de 5,0/10 → 7,5/10 sur le scorecard** |

Hypothèse : 1 senior + 1 junior + 0.5 architecte = 2.5 ETP. 120 / 2.5 = ~48 jours calendaires de travail effectif (~10 semaines hors revue/tests/impondérables).

---

## 11. Conclusion

HydroModPy est un projet scientifique **au point de bascule entre prototype de recherche et produit industriel** : les choix architecturaux récents (Simulation Catalog DuckDB+Zarr, Protocol adapters, planner immutable) sont **stratégiquement justes** et le valident comme successeur des scripts MATLAB/FloPy artisanaux qui peuplent encore l'hydrogéologie française. Mais le merge `dev-refact → dev-database` a introduit 487 fichiers de code-cible sans livrer la purge du code-source équivalent, laissant **trois générations de code qui se marchent dessus** (Watershed legacy / launchers / runners+Project) et une dette de duplication visible (~800 lignes dans `data/variables/`, ~700 dans `boussinesq.py`, ~2 700 dans `climatic/`). Les bugs physiques silencieux (BC `stream/ocean → CHD`, moyenne K arithmétique, porosité = Sy) constituent **l'urgence absolue** : ils produisent des résultats *numériquement plausibles mais scientifiquement faux*, ce qui est le pire cas pour un outil d'aide à la décision — un plan d'action 3 mois ciblé suffit à les éliminer et à atteindre une note scorecard de **7,5/10**, cohérente avec une publication ESSD/HESS ou une utilisation BRGM. La trajectoire est bonne, l'exécution à consolider ; le projet mérite l'investissement qu'il demande.

---

*Fin du rapport — Audit HydroModPy, synthèse finale.*
*Auditeur : CTO / Lead Architect. Ce document engage le board à arbitrer le plan d'action.*
