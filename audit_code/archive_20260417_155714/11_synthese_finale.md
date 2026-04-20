# Audit technique HydroModPy — Synthèse finale exécutive

> **Auditeur** : CTO / Lead Architect
> **Périmètre** : paquet `hydromodpy/` + `tests/` + `validation_cases/` (branche `dev-database`, commit `583f1f61`)
> **Base** : 10 rapports thématiques (`audit_code/01..10_*.md`, ~350 Ko cumulés)
> **Date** : 2026-04-17
> **Public** : Board scientifique + équipe de dev
> **Niveau de confiance** : élevé (10 rapports croisés, lecture fichier-par-fichier, références lignes précises)

---

## Résumé en une page (TL;DR)

HydroModPy est un projet scientifique **ambitieux, cohérent dans son intention, et en progression réelle**. Le choix de pile (**Pydantic v2 + Protocol-based adapters + DuckDB + Zarr + FloPy**) est moderne et pertinent. Trois pans sont déjà **au niveau industriel** : l'infrastructure de régression (golden signatures), les adaptateurs solveur typés `Protocol`, la discrétisation structurée DIS via FloPy.

Mais le projet est **aujourd'hui non livrable en release publique "1.0"** sans passage obligatoire par un bloc de corrections. Les trois raisons principales sont :

1. **Bugs silencieux** qui altèrent des données scientifiques sans avertissement (bug `_split_cell_data` qui corrompt les exports VTU, `scale_factor=NaN` dans NetCDF, `masked[masked < 0] = 0` avant moyenne, `try/except Exception: pass` dans ~40 endroits).
2. **Non-conformité aux standards scientifiques** (CF-1.9, UGRID, MODFLOW DISU, WaterML 2.0) — ce qui condamne l'interopérabilité avec QGIS, ParaView, l'écosystème xarray/rioxarray et les données publiques (ADES, Hub'Eau en sortie).
3. **Duplication massive** (~10 000 LOC récupérables, soit ~15 % du code) et **God-objects** (`Simulation` 705 L, `modflow6.py` 2 900 L, `flow_to_modflow_adapter.py` 1 392 L, `HydroModPyConfig.from_toml` ~105 L, `runtime_loader.py` 893 L) qui rendent le code fragile à la moindre évolution.

**Trajectoire** : avec 3 mois ciblés (~90 jours-dev cumulés), ce projet peut passer de **5.8/10 → 8/10** et devenir une référence open-source dans son créneau (hydrogéologie catchment-scale en Python). Sans ces 3 mois, il restera un **prototype scientifique "usable by its author"**.

---

## 1. Scorecard global

| Domaine | Note | Verdict | Justification en une ligne |
|---|---|---|---|
| **Architecture globale** | **5.5/10** | À améliorer | 12 paquets top-level (vs 6-8 chez xarray/FloPy), `core/` viole sa propre règle, triple orchestration `runners/` + `workflow/` + `simulation/execution/`, 6 niveaux d'indirection (rapport 01 §scorecard). |
| **Qualité de code (`core/` + global)** | **6.5/10** | Acceptable | Pydantic v2 propre, mais `HydroModPyConfig` sans `extra="forbid"`, `WorkflowContext` à 42 champs, ~950 LOC de dead code dans `core/tools/` (rapport 02, rapport 10). |
| **Couche données** | **4/10** | À améliorer sérieusement | 0/17 variables conforme aux standards (CF, WaterML, GeoPackage en sortie). Duplication Hydrometry/Piezometry ~900 L et SIM2 ×7 ~500 L. Cache DuckDB sans transaction ni fingerprint (rapport 03). |
| **Spatial / Mesh** | **6/10** | Acceptable | Gmsh OCC propre, sgrid propre, **mais** moyenne arithmétique non-physique pour K (viole Renard-de Marsily 1997), IDOMAIN absent, DISU non implémenté (rapport 04). |
| **Process / Solver** | **6/10** | Acceptable | Découpage sain, Jacobien semi-analytique correct, **mais** Boussinesq assembly en boucles Python (50-200× trop lent), pas de validation Jac FD vs semi-analytique, GHB/RIV absents (rapport 05). |
| **Moteur simulation** | **7/10** | Acceptable (proche du bon) | `SolverAdapter = Protocol` exemplaire (PEP 544), `SimulationPlan` `frozen=True` conforme, **mais** `Simulation` = god class 705 L, divergence chemin TOML vs chemin programmatique (rapport 06). |
| **Stockage (Catalog + Zarr)** | **5.5/10** | Acceptable mono-user, problématique pour release | Choix DuckDB+Zarr pertinent, **mais** schéma partiellement 3NF (5 PK manquantes), MIGRATIONS={} vide, chunking `(1,L,C)` catastrophique pour time-series, CF/UGRID absent du Zarr natif, `.hmp` non-standard (rapport 07). |
| **Analyse / Display** | **5/10** | À améliorer | Pattern `render_*/plot_*` matplotlib sain, **mais** 2 642 LOC de dead code, duplication `suites.py ↔ posthoc_orchestration.py` (~500 L), `scale_factor=NaN` NetCDF, mutation `rcParams` globale à l'import (rapport 08). |
| **Tests** | **7/10** | Acceptable (bonne infrastructure, pyramide inversée) | `golden_utils.py` 1 104 L de qualité industrielle, validation analytique sérieuse (Dupuit, Brutsaert), **mais** 209 fichiers `unit/` qui sont 90 % des tests d'intégration déguisés. `analysis/`, `workflow/`, `watershed/` = 0 test. Pas de test de bilan de masse (rapport 09). |
| **Pydantic / Configuration** | **7/10** | Acceptable | Conformité v2 complète, `ParamLevel` innovant, discriminated unions idiomatiques, **mais** `HydroModPyConfig` sans `extra="forbid"` (racine !), validation physique absente (K>0, Sy∈[0,1]), duplication massive `data/variables/*/config.py` ~1 200 L (rapport 10). |
| **Documentation** | **4/10** | Problématique | `CLAUDE.md` mentionne `launchers/` qui n'existe plus. Pas de `CONTRIBUTING.md` ni `CHANGELOG.md` visible. Docstrings hétérogènes (exemplaires dans `flow_to_modflow_adapter`, quasi-absentes dans `__main__.py`). Pas de modèle conceptuel scientifique publié. |
| **Interopérabilité** | **3/10** | Problématique | Formats maison (`PointRecord`, `FieldRecord`, `.hmp`, mesh maison) au lieu de `xr.DataArray`, `pd.Series(DatetimeIndex)`, UGRID. 0/5 standards OGC/CF respectés pleinement. Shapefile ESRI legacy en sortie (rapports 03, 07). |
| **Maintenabilité** | **5/10** | À améliorer | ~10 000 LOC duplication + 4 God-objects (`Simulation`, `modflow6.py`, `flow_to_modflow_adapter.py`, `WorkflowContext`) + 40+ `try/except Exception: pass` silencieux. Refactoring nécessaire avant toute évolution structurelle. |

**Moyenne pondérée** : **5.8/10** — "projet scientifique sérieux, encore en phase pré-release".

---

## 2. Top 10 forces (à préserver)

| # | Force | Verdict | Source |
|---|---|---|---|
| 1 | `SolverAdapter = typing.Protocol` (PEP 544) avec 6 adapters qui n'héritent pas — exemplaire, aligne avec xarray/scikit-learn | Conforme, exemplaire | rapport 06 §forces |
| 2 | `SimulationPlan` / `ProcessRun` en `@dataclass(frozen=True)` avec `tuple` immutables | Conforme | rapport 06 §forces |
| 3 | Conformité Pydantic v2 complète : aucun résidu v1, `ConfigDict(extra="forbid")` ~95 %, `model_validator(mode="after")` correct | Conforme | rapport 10 §forces |
| 4 | Discriminated unions exemplaires : `DepthModelConfig`, `DomainSupportConfig`, `ZoneMeshingDomain*Schema` | Conforme (idiomatique Pydantic v2) | rapport 10 §forces |
| 5 | `golden_utils.py` (1 104 L) : stats compactes `(count, mean, p50, p95, shape, sum)`, dispatch fast/extensive, xdist-aware — infrastructure de régression au niveau FloPy | Conforme (industrie) | rapport 09 §forces |
| 6 | `Annotated[Type, ParamLevel(...)]` pour lisibilité UX TOML (user/dev/expert) — innovation propre au projet, ~50 LOC, évite d'importer Hydra | Acceptable (défendable) | rapport 02 §forces |
| 7 | Intégration Gmsh OCC (pas de `.geo` files, conformal meshing edges-enforced via `gmsh.model.mesh.embed()`) | Conforme | rapport 04 §forces |
| 8 | Stockage DuckDB + Zarr + BLOSC-ZSTD clevel=3 — sweet spot de compression, séparation mesh/head/derived/budget claire | Acceptable mono-user | rapport 07 §forces |
| 9 | Double entrée API/CLI : `hmp.open()` (comme `xr.open_dataset`) + `hmp run config.toml` (comme `kubectl apply`) avec dispatch TOML élégant via `detect_workflow()` | Conforme | rapport 01 §forces |
| 10 | Lazy imports PEP 562 (`__init__.py` avec `__getattr__`) — aligne avec scikit-learn 1.3+ | Conforme | rapport 01 §forces |

---

## 3. Top 10 dettes techniques (classées impact × effort)

Échelle d'impact : **bloquant** (release impossible), **majeur** (doit être fait dans le trimestre), **mineur** (dette acceptable).
Échelle d'effort : **facile** (< 2 j), **moyen** (2-10 j), **hard** (> 10 j).

| # | Dette | Impact | Effort | Source |
|---|---|---|---|---|
| 1 | **Duplication Hydrometry/Piezometry (~900 L)** + climatique SIM2 ×7 (~500 L) + 7 managers variables SIM2 quasi-identiques | Bloquant | Moyen (factoriser via `HubeauStationManager` + `fetch_sim2_field`) | rapport 03 §duplication |
| 2 | **Cache DuckDB sans transaction, sans fingerprint SHA-256, sans TTL** — risque doublons/état incohérent, données custom remplacées non détectées | Bloquant | Moyen (2-3 j) | rapport 03 §critique |
| 3 | **God-class `Simulation` 705 LOC + God-object `WorkflowContext` 42 champs** muté en 6 endroits, 18 imports tardifs, 7 phases dans `__init__` | Majeur | Hard (refactor complet, 5-7 j) | rapports 01, 06 |
| 4 | **Moyenne arithmétique pour K dans l'upscaling** — viole physique (Wen & Gómez-Hernández 1996, Renard & de Marsily 1997) dès hétérogénéité > 1 ordre de grandeur | Bloquant (résultats incorrects) | Moyen (2 j : ajouter `harmonic`, `geometric`, `power-law`) | rapport 04 §critique |
| 5 | **IDOMAIN/IBOUND absent** + pinch-out non détecté → prismes dégénérés → MODFLOW diverge silencieusement sur géologies réelles | Majeur (bloque 3D sérieux) | Moyen (2-3 j) | rapport 04 §dettes |
| 6 | **CF-1.9 / UGRID absents du Zarr natif et des exports NetCDF** — `units="timestep index"` au lieu de `"days since 2020-01-01"`, pas de `grid_mapping`/`crs` → QGIS refuse projection, `cf-checker` rejette | Bloquant (interop) | Moyen (1-2 j + tests `cf_xarray`) | rapports 07, 08 |
| 7 | **Boussinesq assembly non-vectorisé** : boucles Python sur `range(mesh.n_edges)` dans 6+ fonctions → 50-200× trop lent | Majeur (perf) | Moyen (2-3 j) | rapport 05 §faiblesses |
| 8 | **Duplication `data/variables/*/config.py`** (17 fichiers jumeaux, ~1 200 L) — 9 pures duplications custom+sim2 | Majeur | Moyen (1-2 sem → ~200 L) | rapport 10 §duplication |
| 9 | **God-file `modflow6.py` 2 900 L** dans un seul fichier + `flow_to_modflow_adapter.py` 1 392 L | Majeur | Hard (3-4 j) | rapport 05 §faiblesses |
| 10 | **Tests : pyramide inversée** — 209 fichiers `tests/unit/` sont 90 % intégration (I/O disque, subprocess, binaires). `analysis/`, `workflow/`, `watershed/` = 0 test direct | Majeur | Hard (migration progressive 2 sem) | rapport 09 §faiblesses |

**Gain cumulé estimé si dette résolue** : -10 000 LOC (−15 %), ×50-200 perf Boussinesq, +40 points couverture effective.

---

## 4. Problèmes critiques à corriger AVANT toute release publique

Ces items produisent **des résultats silencieusement incorrects** ou **des pertes de données**. Aucun ne peut être toléré dans une version 1.0.

| # | Fichier:ligne | Problème | Conséquence | Sévérité |
|---|---|---|---|---|
| 1 | `results/exporters/vtu.py:108` `_split_cell_data` | Association valeur/cellule **fausse** si tri/quad intercalés dans connectivité | Export VTU/ParaView corrompu, visualisation scientifique fausse, publication sur mauvais résultats | Critique |
| 2 | `analysis/postprocess/netcdf/netcdf_writer.py:90-91` | `.max()/.min()` sur DataArray NaN → `scale_factor=NaN` | Fichier NetCDF corrompu, impossible à rouvrir | Critique |
| 3 | `analysis/display/figures/flow_timeseries.py:454-455` `masked[masked < 0] = 0` | Altération silencieuse avant moyenne (watertable_depth négatif artésien perdu) | Moyennes statistiques biaisées à la hausse | Critique |
| 4 | `simulation/execution/runner.py` + `Simulation._run_with_overrides` (`project.py:397-402`) | Transport silencieusement perdu si `multi-process + overrides` | Perte de résultats transport sans avertissement | Critique |
| 5 | `results/catalog.py:831-834` `import_simulation` | `if/else` identique (les deux branches produisent le même `zarr_path`) | Import `.hmp` peut charger les mauvais artefacts | Critique |
| 6 | `solver/modflow_nwt/modflow/intermittency.py:49` | Seuil `-100 m` magique peut masquer charges légitimes en montagne | Charges piézométriques légitimes → NaN silencieux | Critique |
| 7 | `data/registry/catalog_duckdb.py` `register()` l.157-204 | Pas de transaction DuckDB → doublons, état incohérent après crash | Catalogue corruptible | Critique |
| 8 | `data/variables/hydrography/apis/osm.py:27` | Swap `lat/lon` silencieux dans bbox Overpass sans commentaire | Requête OSM peut retourner zone adjacente au lieu du bassin | Critique |
| 9 | `data/variables/piezometry/discovery.py` | `buffer_deg = radius_m / 111_000` → divergence latitude | Stations piézométriques manquées hors latitudes moyennes | Majeur |
| 10 | `core/config/hydromodpy_config.py:73` | `HydroModPyConfig` **sans** `extra="forbid"` | Section TOML typotée → silencieusement ignorée | Majeur (UX + bugs) |
| 11 | `core/config/toml_loader.py:104` `_strip_empty_strings` | Un champ `str = ""` légitime → remplacé par défaut Pydantic | Masque des bugs de config | Majeur |
| 12 | `analysis/display/visualization_watershed.py:55-96` | Mutations `mpl.rcParams` globales **à l'import** | Pollue matplotlib de tout programme tiers qui importe hydromodpy | Majeur |
| 13 | `process/boussinesq/*_runtime.py:274` | Line-search accepte pas même si résidu augmente (stagnation silencieuse) | Convergence Newton non garantie | Majeur |
| 14 | `results/` CF-1.9 / UGRID absent dans Zarr natif + NetCDF export | QGIS refuse projection, `cf-checker` rejette, interop cassée | Incompatibilité écosystème (non-publiable FAIR) | Majeur |
| 15 | `simulation/adapters/post_run.py:90-105` | `try/except TypeError` pour deviner signature adapter (anti-pattern) | Écrase erreurs vraies | Majeur |
| 16 | `spatial/zone_meshing/extruded_prism_mesh.py:210-275` | Pas de détection pinch-out `top - botm[k] < tol` → prismes volume~0 | MODFLOW diverge sans diagnostic | Majeur |
| 17 | `core/config/hydromodpy_config.py:235-241` `__DEM_API_BOOTSTRAP__` | Sentinelle string injectée dans path puis réinterprétée | Anti-pattern fragile | Majeur |
| 18 | Absence totale de test de bilan de masse (`inflow - outflow - dstorage < eps`) | Vérification N°1 MODFLOW absente malgré table `mass_balance` existante | Toute régression physique passe inaperçue | Critique (process) |

**Verdict** : tant que les 18 points ci-dessus ne sont pas fermés (avec tests de non-régression dédiés), le package ne doit pas être publié en "1.0" au-delà du cercle des auteurs.

---

## 5. Code mort à supprimer

Tableau cumulé sur les 10 rapports — au total **~8 000 à 10 000 LOC** supprimables sans perte fonctionnelle.

| Chemin | LOC | Source | Action |
|---|---|---|---|
| `hydromodpy/watershed/` (shim legacy complet) | — | rapport 01 | Supprimer |
| `hydromodpy/exceptions.py` (ConfigError, SolverError, DataError, MeshError — jamais levés) | — | rapport 01 | Supprimer OU commencer à les utiliser (cohérent) |
| `hydromodpy/solver/compatibility.py` | — | rapport 01 | Vérifier usage, supprimer |
| `core/tools/folder_root.py` (`input()` + `os.system("setx ...")`) | 148 | rapport 02 | Supprimer |
| `core/tools/io_utils.py` | 379 | rapport 02 | Supprimer (exclusif à `example_00`) |
| `core/tools/visualization.py` | 315 | rapport 02 | Supprimer (exclusif à `example_00`) |
| `data/climatic/climatic.py` (avec `DeprecationWarning`) | 619 | rapport 03 | Supprimer |
| `data/climatic/sim2.py` (ancien SIM2 CSV) | 933 | rapport 03 | Supprimer |
| `data/climatic/sim2_API.py` (duplique `Sim2EDRClient`) | 283 | rapport 03 | Vérifier puis supprimer |
| `data_managers.py` (wrapper trivial `list[str]`) | 35 | rapport 03 | Inliner |
| `_gmsh_driver.py` (stub façade) | 35 | rapport 04 | Supprimer |
| `process/base/smoothing.py` complet | 170 | rapport 05 | Supprimer (imports nulle part hors fichier) |
| `process/base/scipy_runtime.py` (wrapper sans valeur) | 181 | rapport 05 | Supprimer |
| `Alias Process = ProcessSpatial` (`process_spatial.py:168`) | 1 | rapport 05 | Supprimer |
| `modflow_nwt/flow_to_modflow_adapter.py` re-export (5 L inutiles) | 5 | rapport 05 | Supprimer |
| `simulation/adapters/display/stub.py` + `postprocess/stub.py` | 72 | rapport 06 | Supprimer |
| `simulation/settings.py` classe `Settings` (jamais importée) | — | rapport 06 | Supprimer |
| `_COMPONENT_ENSURERS` + `ensure_process_context` | — | rapport 06 | Inliner |
| `launchers/process_simulation.py` re-exports `# noqa: F401` | 32 | rapport 06 | Supprimer |
| `results/exporters/resample.py` (2 stubs `NotImplementedError`) | — | rapport 07 | Supprimer |
| `Simulation.rerun()` stub | — | rapport 07 | Supprimer ou implémenter |
| `results/catalog.py record_provenance = write_provenance` alias | 1 | rapport 07 | Supprimer |
| `display/_render_stub` pour drainage_density, concentration_map, pathlines | — | rapport 07 | Supprimer |
| `catalog_schema.py MIGRATIONS = {}` squelette jamais testé | — | rapport 07 | Implémenter (critique) OU retirer |
| `display/visualization_results.py` (dead code) | 915 | rapport 08 | Archiver `hydromodpy_annex/legacy_display/` |
| `display/visualization_watershed.py` (dead + side-effects) | 469 | rapport 08 | Archiver |
| `display/export_vtuvtk.py` (dead code) | 1 258 | rapport 08 | Archiver |
| `postprocess/netcdf/netcdf.py` (wrapper vide) | 14 | rapport 08 | Supprimer |
| `postprocess/timeseries/timeseries.py` (alias legacy) | 27 | rapport 08 | Supprimer |
| `analysis/capability_gallery.py` (utilité douteuse) | 135 | rapport 08 | Supprimer ou justifier |
| `golden_utils.py` `run_legacy_example_script()` (README confirme dead) | 144 | rapport 09 | Supprimer |
| `tests/regression/reference/golden_references/normal/` (tier mort) | — | rapport 09 | Supprimer |
| `process/base/{boundary_conditions,initial_conditions,sinks_sources,process_spatial_config}.py` bases jamais utilisées comme bases | — | rapport 10 | Réduire à `Protocol` ou supprimer |
| `ResolvedFieldParamSchema` (doublonne 3 autres schémas) | — | rapport 10 | Supprimer, utiliser `@model_serializer` |

---

## 6. Inconsistances inter-modules

| # | Inconsistance | Impact | Correctif |
|---|---|---|---|
| 1 | **Triple ré-export de `WorkflowContext`** (`core/__init__.py:10-15` + `simulation/__init__.py:18-23`) | Confusion, double import | Exposer depuis un seul module |
| 2 | **3 classes homonymes `Simulation`** : `project.Simulation`, `results.simulation.Simulation`, `simulation.Simulation` + paquet `hydromodpy.simulation` | Collision, lecture difficile | Renommer (voir §8) |
| 3 | **`results/` et `simulation/results/`** : chevauchement de noms et de responsabilités | Confusion | Renommer `simulation/results/` → `simulation/extractors/` |
| 4 | **4 valeurs `nodata` mélangées** (`-9000`, `-9999`, `-99999`, `NaN`) dans spatial, results, exporters, NWT intermittency | Risque bugs silencieux | Constante unifiée `HMP_NODATA = np.nan` dans `core/constants.py` |
| 5 | **Zarr v2 vs v3 ambigu** (`zarr.codecs.BloscCodec` est v3 mais pas de `zarr_format=3` explicite) | Break compat xarray selon version | Choisir v3 officiellement, épingler |
| 6 | **Sentinelle NaN hétérogène solveurs** : NWT `isclose(..., atol=1.0)` sur `-100.0`/`-9999.0` vs MF6 `abs(values) > 1e20` | Résultats divergents selon solveur | Unifier via `core/constants.py` |
| 7 | **Double hiérarchie calibration** : `analysis/calibration/core/engine_config.py` ↔ `analysis/calibration/engine/config.py` | Refonte inachevée | Fusionner |
| 8 | **Dispatch custom/API répété dans 13 managers** au lieu d'un registry `@register_source("hubeau")` | Duplication ~200 L | Registry déclaratif |
| 9 | **`extra="forbid"` manquant** sur `HydroModPyConfig` alors que présent sur `WorkspaceConfig` | Section TOML typotée ignorée | Ajouter |
| 10 | **Convention `domain`** : HydroModPy = zonation (geology), MODFLOW/FloPy = extension spatiale. Inversion dangereuse pour utilisateurs venant de FloPy | Lecture difficile pour adoption | Renommer `domain` → `zonation` |
| 11 | **`extra="allow"` legacy** sur `FieldBaseSectionSchema` + `FieldParamConfig` alors que reste du code strict | Fuite de validation | Migrer après release dépréciation |
| 12 | **Shapefile en sortie hydrographie / GeoPackage en entrée géologie** | Incohérence formats | Standardiser GeoPackage partout |
| 13 | **Export Parquet pour LOC mais CSV pour chroniques** | Incohérence | Standardiser Parquet/GeoParquet |
| 14 | **`postprocess/flow/intermittency.py` et `matching_streams.py`** mal placés (calcul scientifique dans `analysis/postprocess/`) | Frontières modulaires floues | Déplacer dans `process/flow/diagnostics/` |
| 15 | **NetCDF dupliqué** : `analysis/postprocess/netcdf/` **et** `results/exporters/` | Lequel est canonique ? | Supprimer le premier |
| 16 | **Timeouts CI 30 min vs tests internes `timeout=7200s` (2h)** | CI flaky / impossible pour extensive | Découpler matrices |

---

## 7. Conformité aux standards

| Standard | Domaine | Statut | Impact | Commentaire |
|---|---|---|---|---|
| **PEP 8** (style) | Code global | Conforme | Bas | Respecté (PascalCase classes, snake_case modules) |
| **PEP 544** (Protocol) | Adapters | Conforme | — | `SolverAdapter` exemplaire |
| **PEP 557** (frozen dataclasses) | Plan d'exécution | Conforme | — | `SimulationPlan`, `ProcessRun` |
| **PEP 562** (lazy `__getattr__`) | `__init__.py` | Conforme | — | `_LAZY_IMPORTS` bien structuré |
| **Pydantic v2** | Configuration | Conforme (95 %) | — | `extra="forbid"` manquant à la racine (critique) |
| **CF-1.9** | NetCDF / Zarr | **Non-conforme** | Bloquant interop | `units="timestep index"` au lieu `"days since YYYY-MM-DD"`, pas de `grid_mapping`, `standard_name`, `long_name`. `cf-checker` rejette. |
| **ACDD** (Attribute Convention for Data Discovery) | NetCDF | Absent | Majeur | Pas de `title`, `institution`, `source`, `history`. Bloque catalogage FAIR. |
| **UGRID-1.0** | Mesh | Partiel | Majeur | Topologie présente dans Zarr (`vertices`, `face_node_connectivity`) mais sans `cf_role="mesh_topology"`. ParaView/VisIt ne reconnaît pas le maillage non-structuré. |
| **MODFLOW DIS** (structured) | Sgrid | Partiel (acceptable) | — | Via FloPy `StructuredGrid`, OK |
| **MODFLOW DISV** (vertex) | Mesh gmsh | Partiel | Majeur | 2D planar uniquement, `flopy_adapter.py:104` lève sur 3D |
| **MODFLOW DISU** (unstructured) | — | **Absent** | Majeur | Aucune connectivité topologique exposée |
| **OGC GeoPackage** | Formats sortie | Non-conforme | Majeur | Shapefile ESRI legacy (1998, 2 Go max, 10 char champs). OGC recommande GeoPackage depuis 2012. |
| **OGC WaterML 2.0** | Chroniques hydro | Absent | Majeur | Standard OGC pour chroniques, produit par Hub'Eau/USGS/BRGM ADES. Aucune variable ne l'émet. |
| **OGC SensorThings** | Capteurs | Absent | Mineur (spécifique IoT) | — |
| **PROV-O / RO-Crate / FAIR** | Provenance | Absent | Majeur | `provenance` table réductrice : pas de version HMP, git SHA, Python version, solveur binaire hash |
| **Pandera / GE / JSON-schema** | Validation données brutes | Absent | Majeur | Aucune validation schéma post-lecture |
| **matplotlib best practices** | Figures | À améliorer | Mineur | Violation `mpl.rcParams` globaux à l'import (anti-pattern). Usage `jet` interdit (3 endroits). |
| **pytest best practices** | Tests | À améliorer | Majeur | Pyramide Cohn 2009 inversée (90 % unit sont intégration déguisée) |
| **UDUNITS / SI** | Unités | Partiel | Moyen | `W/m2` au lieu de `W m-2` (CF), `mm/day` (non-SI) au lieu de `m/s` |
| **Zarr v3** | Stockage | Partiel | Moyen | `BloscCodec` v3 utilisé mais pas de `zarr_format=3` explicite |

**Verdict global conformité** : **3/10**. Le projet n'est conforme à aucun standard scientifique d'interopérabilité. C'est le point noir le plus visible de l'extérieur (revue par pair, FAIR data, intégration avec QGIS/ParaView).

---

## 8. Renommages nécessaires

| Nom actuel | Nom proposé | Justification | Source |
|---|---|---|---|
| `project.Simulation` | `Project` (ou `Pipeline`) | Collision 3× `Simulation`, cohérent avec `hmp new <project>` | rapport 01 |
| `results.simulation.Simulation` | `SimulationRecord` ou `StoredSimulation` | Collision | rapport 01 |
| `simulation.SimulationConfig` | `SimulationSpec` | Collision | rapport 01 |
| Paquet `hydromodpy.simulation` | `hydromodpy.engine` ou `hydromodpy.execution` | Clarifier moteur d'exécution vs concept métier | rapport 01 |
| `Modflow`, `Modpath`, `Mt3dms` | `ModflowNwt`, `Modpath7`, `Mt3dms` (versionner explicitement) | Abréviations peu lisibles, ambiguïté NWT/2005/USG | rapport 01 |
| `ModelCalibrationLauncher` | `Calibrator` | « Launcher » = Java-ism | rapport 01 |
| `RegionalLabLauncher` | `RegionalBatch` | idem | rapport 01 |
| `DataOverviewLauncher` | `WatershedIdentityCard` | idem | rapport 01 |
| `MeshCatchmentLauncher` | `MeshBuilder` | idem | rapport 01 |
| `runners/` (paquet) | `cli/` (absorber dans `__main__.py` ou `cli_dispatch/`) | Ambigu avec `simulation/execution/runner.py` | rapport 01 |
| `hydromodpy_config.py` | `config.py` | Préfixe redondant (PEP 8) | rapport 01 |
| `data_managers.py` | `managers.py` ou inliner | idem | rapport 01 |
| `simulation/results/` | `simulation/extractors/` | Chevauche `results/` | rapport 01 |
| `posthoc.py` | `replay.py` | Ambiguïté stats vs. replay | rapport 01 |
| `capability_gallery.py` | `figure_gallery_export.py` | Nom obscur | rapport 01 |
| `catch_name` | `project_name` | « catchment » incorrect en batch multi-sites | rapport 02 |
| `buff_area` | `buffer_distance` ou `buffer_percent` | "area" ≠ "distance" | rapport 10 |
| `catch_def` | `watershed_delineation_mode` | Abréviation opaque | rapport 10 |
| `dem_correc_type` | `dem_depression_handling` | Typo-gunk | rapport 10 |
| `reg_fold` | `regional_rasters_dir` | Acronyme opaque | rapport 10 |
| `genmtd`, `genmtd_lay`, `genmtd_top`, `genmtd_bot` | `generation_method`, `layer_generation_method`, etc. | Préfixes incompréhensibles | rapport 10 |
| `ntsp` | `n_timesteps` | Non-standard MODFLOW (celui-ci est `NSTP`) | rapport 10 |
| `lenper` | `period_length` | idem MODFLOW `PERLEN` | rapport 10 |
| `spc_name` | `species_name` | Abréviation inutile | rapport 10 |
| `disp_long`, `disp_transh`, `disp_transv` | `dispersivity_longitudinal`, ... | Peu clair | rapport 10 |
| `field_param` / `field_spatial` / `field_mesh` | `parameter_field.py` / `spatial_zonation.py` / `mesh_support.py` | Préfixe redondant | rapport 04 |
| préfixe `sgrid_*.py` dans `cartesian_grid/` | `generation.py`, `config.py`, `field_discretization.py` | Redondant (dossier donne déjà contexte) | rapport 04 |
| `StationLocation.crs: str` | `StationLocation.crs: pyproj.CRS` | Typage propre | rapport 03 |
| `PointRecord.data: pd.DataFrame[datetime,value]` | `pd.Series(DatetimeIndex)` ou `xr.DataArray` | Format maison → standard | rapport 03 |
| `FieldRecord.bbox/crs/date_*/frequency` | Supprimer — lire `xr.Dataset.attrs + .rio.crs` | Duplique xarray | rapport 03 |
| `DataStore.load_hydrometry/..._piezometry/...` ×13 | `DataStore.load(variable: str, config)` | Factorisation évidente | rapport 03 |
| `CatchmentDomain` (fonction) | `derive_catchment_domain_products()` | Fonction camelCase trompeuse | rapport 04 |
| `config_toml` (colonne DuckDB) | `config_snapshot` | Stocke JSON, pas TOML | rapport 07 |
| Format `.hmp` | `.hmp.zip` ou `.hmp.tar.zstd` avec `MANIFEST.json` | Actuellement répertoire avec extension trompeuse | rapport 07 |
| `section TOML [geographic]` | `[domain]` ou `[grid_spec]` | Inhabituel vs ModelMuse/FloPy | rapport 10 |

---

## 9. Réorganisation suggérée

### 9.1 Arbre actuel (12 paquets top-level)

```
hydromodpy/
├── core/           # infra (workspace, config, state, tools, units)
├── data/           # managers + cache
├── results/        # Simulation Catalog (DuckDB + Zarr)
├── spatial/        # geographic, domain, field, mesh
├── process/        # flow, transport, base/
├── solver/         # modflow_nwt, modflow6, boussinesq, base/
├── analysis/       # postprocess, display, calibration, comparison, batch
├── simulation/     # planning, execution, adapters, state
├── runners/        # CLI shells (thin)
├── workflow/       # composable pipeline steps
├── launchers/      # legacy (partiellement migré)
├── watershed/      # shim legacy (DEAD)
└── hydromodpy_annex/  # outils périphériques
```

Problèmes :
- Triple orchestration `runners/` + `workflow/` + `simulation/execution/`.
- `launchers/` mentionné dans CLAUDE.md mais absent physiquement.
- `watershed/` mort.
- `results/` vs `simulation/results/` ambigu.
- `core/` viole sa propre règle (importe `spatial/`, `data/`, `process/` via `WorkflowContext`).

### 9.2 Arbre proposé (8 paquets top-level — inspiré xarray/FloPy)

```
hydromodpy/
├── core/                    # Infra pure: workspace, config, units, time, logging
│   ├── config/              # Pydantic models (extra="forbid" racine)
│   ├── workspace/
│   ├── time/
│   ├── units/               # refactorer via pint (−800 LOC)
│   └── constants.py         # HMP_NODATA, sentinels unifiées
├── data/                    # Managers uniformisés
│   ├── base/                # BaseVariableManager + BaseFieldManager (fusionnés)
│   ├── sources/             # registry @register_source("hubeau") etc.
│   ├── variables/           # config Pydantic minimaliste (héritage BaseVariableConfig)
│   └── cache/               # DuckDB transactionnel + fingerprint + TTL
├── spatial/                 # Maillage + géographie (un seul pipeline)
│   ├── geographic/
│   ├── mesh/                # absorbe zone_meshing
│   └── field/               # zonation + upscaling (harmonic, geometric)
├── physics/                 # renommé process/ (plus explicite)
│   ├── flow/
│   ├── transport/
│   └── diagnostics/         # intermittency, matching_streams (déplacés depuis postprocess)
├── solvers/                 # renommé solver/
│   ├── modflow_nwt/
│   ├── modflow6/
│   ├── boussinesq/
│   ├── mt3dms/
│   └── modpath7/
├── engine/                  # renommé simulation/
│   ├── planning/            # SimulationPlanner
│   ├── execution/           # SimulationRunner + context
│   ├── adapters/            # Protocol-based
│   └── extractors/          # renommé simulation/results/
├── catalog/                 # renommé results/
│   ├── store.py             # SimulationCatalog (DuckDB)
│   ├── zarr_store.py        # SimulationZarr
│   ├── exporters/           # netcdf (CF-1.9), vtu (bug fix), geopackage (remplace shp), geotiff
│   └── schema/              # versioning + migrations (Alembic)
├── analysis/                # Post-processing + figures + calibration
│   ├── calibration/         # fusion core/ + engine/ (une seule hiérarchie)
│   ├── comparison/
│   ├── batch/
│   └── display/             # uniquement figures (plus de calcul scientifique ici)
└── cli/                     # remplace runners/ + fusionne workflow/
    ├── __main__.py          # dispatch
    └── pipelines/           # pipeline steps (composable)
```

Gains :
- **Sémantique claire** : `catalog/` = stockage, `engine/` = exécution, `physics/` = équations, `solvers/` = backends.
- **Convention FloPy/xarray** : `engine/`, `catalog/`, `solvers/` (pluriel pour collections).
- **Disparition dette legacy** : `watershed/`, `launchers/` supprimés. `workflow/` fusionné avec `cli/`.
- **Une seule hiérarchie calibration** au lieu de deux.
- **Frontières nettes** : `postprocess/flow/intermittency.py` migre vers `physics/flow/diagnostics/`, plus de calcul scientifique dans `analysis/display/`.

### 9.3 Migration recommandée

Réorganisation = **sprint 3 uniquement** (changement structurel, ~15 j). Nécessite un shim `from hydromodpy.process import *` qui réexporte depuis `physics/` pendant 1 release pour ne pas casser les utilisateurs externes (qui utilisent probablement `import hydromodpy as hmp` donc l'API publique est préservée).

---

## 10. Plan d'action 3 mois

Estimé en jours-développeur (jd). 1 dev sénior à temps plein = ~60 jd sur 3 mois.

### Sprint 1 — Quick wins (2 semaines, ~20 jd cumulés)

**Objectif** : supprimer les bugs silencieux critiques, fermer les fuites de données, supprimer ~3 000 LOC de code mort. Pas de refactoring structurel.

| # | Action | Effort | Gain |
|---|---|---|---|
| 1 | Fixer `_split_cell_data` (`results/exporters/vtu.py:108`) + test de non-régression | 1 jd | Export VTU correct |
| 2 | Fixer `scale_factor=NaN` → utiliser `np.nanmax/np.nanmin` (`netcdf_writer.py:90-91`) | 0.5 jd | NetCDF réouvrables |
| 3 | Supprimer `masked[masked < 0] = 0` (`flow_timeseries.py:454-455`) + option explicite | 0.5 jd | Moyennes justes |
| 4 | Fixer `if/else` identique (`catalog.py:831-834`) dans `import_simulation` | 0.5 jd | Import `.hmp` fiable |
| 5 | Transactions DuckDB autour de `register/subsume/cleanup` (rapport 03) | 2 jd | Catalogue consistant |
| 6 | Ajouter `extra="forbid"` à `HydroModPyConfig` (racine) + retirer `arbitrary_types_allowed=True` inutiles | 0.5 jd | UX + validation stricte |
| 7 | Remplacer `try/except Exception: pass` par logger (~40 occurrences, script semi-auto) | 2 jd | Bugs émergent |
| 8 | Ajouter fingerprint SHA-256 dans cache DuckDB + TTL | 2 jd | Cache correct |
| 9 | Supprimer code mort confirmé (voir §5 : `climatic.py`, `sim2.py`, `folder_root.py`, `io_utils.py`, `visualization.py`, stubs, `watershed/`) | 1.5 jd | −3 000 LOC |
| 10 | Unifier sentinelles : `core/constants.py` avec `HMP_NODATA = np.nan` + tests | 1 jd | Plus de `-9999` magique |
| 11 | Test bilan de masse (NWT, MF6) + CI fail si `\|dstorage\| > 1e-6` | 2 jd | Assurance physique |
| 12 | Retirer mutation `mpl.rcParams` à l'import (`visualization_watershed.py:55-96`) | 0.5 jd | Non-pollution tiers |
| 13 | Fixer bbox OSM lat/lon + `buffer_deg` piézométrie | 1 jd | Discovery correcte |
| 14 | Supprimer sentinelle `__DEM_API_BOOTSTRAP__` → paramètre nommé explicite | 1 jd | Fin anti-pattern |
| 15 | Ajouter `OMP_NUM_THREADS=1`/`MKL_NUM_THREADS=1` dans `conftest.py` | 0.1 jd | Reproductibilité tests |
| 16 | Documenter le status : `CHANGELOG.md` + `CONTRIBUTING.md` + lister breakings | 1.5 jd | Gouvernance |
| **Total Sprint 1** | | **~18 jd** | **Release 0.9 publiable** |

### Sprint 2 — Refactoring moyen (1 mois, ~40 jd cumulés)

**Objectif** : éliminer les duplications, introduire la conformité CF/UGRID, ajouter la validation physique, migrer les tests.

| # | Action | Effort |
|---|---|---|
| 1 | Factoriser Hydrometry/Piezometry via `HubeauStationManager` (−900 LOC) | 4 jd |
| 2 | Factoriser SIM2 ×7 via `fetch_sim2_field(variable_spec)` (−500 LOC) | 3 jd |
| 3 | Factoriser `data/variables/*/config.py` (17 fichiers jumeaux, −1 000 LOC) | 4 jd |
| 4 | Registry `@register_source("hubeau" | "sim2" | "custom")` dans `DataStore` (remplace 13 méthodes `load_*`) | 3 jd |
| 5 | Ajouter CF-1.9 dans `results/exporters/netcdf.py` (attrs `standard_name`, `long_name`, `units`, `grid_mapping`, time axis `"days since ..."`) + ACDD global | 2 jd |
| 6 | Ajouter UGRID-1.0 dans Zarr natif (`cf_role="mesh_topology"`, `topology_dimension`) + test avec `cf-checker` | 2 jd |
| 7 | Remplacer Shapefile par GeoPackage en sortie | 1 jd |
| 8 | Validation physique Pydantic : module `core/config/physical_validators.py` (K>0, 0<Sy<1, 0<φ<1, Ss>0, disp≥0) | 1.5 jd |
| 9 | Vectoriser Boussinesq assembly (boucles → numpy/scipy.sparse.COO) | 4 jd |
| 10 | Ajouter moyenne harmonique pour K + option `upscaling_method = "harmonic" | "geometric" | "arithmetic"` (defaults harmonic) | 2 jd |
| 11 | Ajouter IDOMAIN/IBOUND à `HydroMesh` + propagation adapters + détection pinch-outs | 3 jd |
| 12 | Ajouter GHB et RIV packages (MODFLOW) | 2 jd |
| 13 | Fusion `analysis/display/suites.py` ↔ `posthoc_orchestration.py` paramétré par `DataSource` (−500 LOC) | 3 jd |
| 14 | Factorisation `_write_surface_elevation` + `_find_variable` + `_watertable_elevation` (extractors+exporters) | 2 jd |
| 15 | Migration tests : créer `tests/integration/`, déplacer 50 % des `tests/unit/` qui utilisent subprocess/binaires | 3 jd |
| 16 | Premier lot de tests unitaires purs (mock-based) pour `workflow/`, `analysis/` | 3 jd |
| 17 | Schéma DuckDB : ajouter les 5 PK manquantes + contraintes CHECK | 1 jd |
| 18 | Ajouter Alembic pour migrations DuckDB (remplace `MIGRATIONS={}` vide) | 2 jd |
| **Total Sprint 2** | | **~42 jd** |

**Livrable** : release 0.95, conformité CF/UGRID partielle, duplication réduite à <5 %.

### Sprint 3 — Changements structurels (1.5 mois, ~45 jd cumulés)

**Objectif** : God-objects éliminés, réorganisation paquets, API publique nettoyée.

| # | Action | Effort |
|---|---|---|
| 1 | Découper `Simulation` (705 L) en `Project` + `SimulationOrchestrator` + extraction méthodes privées | 5 jd |
| 2 | Refactor `WorkflowContext` → dataclasses scoped immutables (pas de mutation en place) | 4 jd |
| 3 | Découper `modflow6.py` (2 900 L) en sous-modules (packaging, runtime, extractors) | 3 jd |
| 4 | Découper `flow_to_modflow_adapter.py` (1 392 L) en `FlowICToBas` + `FlowBCToBoundaryPackages` + `FlowSSToStressData` | 3 jd |
| 5 | Découper `runtime_loader.py` (893 L, `data/`) en plugins par variable | 3 jd |
| 6 | Factoriser 4 runtimes Boussinesq via `newton_loop(jacobian_builder, residual_fn, linear_solver)` générique | 2 jd |
| 7 | Réorganisation paquets : `simulation/` → `engine/`, `solver/` → `solvers/`, `results/` → `catalog/`, `process/` → `physics/`, merger `runners/` + `workflow/` → `cli/` + shim compat | 6 jd |
| 8 | Supprimer 3 classes homonymes `Simulation` (renommer `Project`, `SimulationRecord`, `SimulationSpec`) | 2 jd |
| 9 | Déplacer `postprocess/flow/intermittency.py` + `matching_streams.py` vers `physics/flow/diagnostics/` | 1 jd |
| 10 | Fusionner les 2 hiérarchies calibration (`core/engine_config.py` ↔ `engine/config.py`) | 2 jd |
| 11 | Remplacer `core/units/` (1 180 LOC) par pint full (−800 LOC) | 2 jd |
| 12 | Supprimer `LogManager` (294 LOC) → `logging.dictConfig` (−230 LOC) | 1 jd |
| 13 | Format `.hmp` : `MANIFEST.json` + `ro-crate-metadata.json` (RO-Crate) + `.hmp.zip` extension réelle | 3 jd |
| 14 | Rechunker Zarr à la finalisation : `(min(T, 24), L, min(C, 10_000))` pour équilibre carte/série | 2 jd |
| 15 | Tests unitaires purs (mock/Hypothesis) : couverture `workflow/` = 60 %, `analysis/` = 40 %, `runners/` = 50 % | 5 jd |
| 16 | Ajouter Theis (1935) + Hantush-Jacob en validation analytique transitoire | 2 jd |
| 17 | Documentation : `docs/developers/architecture.md` mis à jour + schéma composants + contrib guide | 2 jd |
| **Total Sprint 3** | | **~48 jd** |

**Livrable** : release **1.0 publique** — code propre, standards respectés, dette < 3 %.

### Récapitulatif effort

| Sprint | Durée | Effort | Livrable |
|---|---|---|---|
| 1 | 2 sem | 18 jd | 0.9 (bugs critiques fermés) |
| 2 | 1 mois | 42 jd | 0.95 (standards + duplication) |
| 3 | 1.5 mois | 48 jd | **1.0 public** (réorganisation) |
| **Total** | **3 mois** | **~108 jd** | Release 1.0 FAIR-compatible |

**Ressources** : 1 dev sénior + 1 dev junior = 6 × 20 jd/mois = 360 jd budget → confortable. Avec 1 seul sénior (60 jd × 3 = 180 jd) : livrable mais sprints 2 et 3 légèrement compressés. Inférieur à 1 FTE : report nécessaire.

---

## 11. Conclusion

HydroModPy est un projet scientifique **techniquement honnête et ambitieux**, porté par un choix de pile moderne (Pydantic v2, DuckDB, Zarr, FloPy, Gmsh OCC) et plusieurs pièces exemplaires (`Protocol`-based adapters, `SimulationPlan` immutable, `golden_utils.py`). Il vaut aujourd'hui **5.8/10**, ce qui le classe comme un **"prototype scientifique utilisable par ses auteurs"** mais **pas encore publiable en open-source 1.0** sans fermer un bloc incompressible de bugs silencieux et de non-conformités standards. La principale dette n'est pas une dette de conception (l'architecture de fond est saine) mais une **dette d'exécution** : God-objects, duplications massives (~10 000 LOC), standards CF/UGRID/OGC absents, et pyramide de tests inversée. Avec les 3 sprints proposés (~108 jd cumulés), le projet peut atteindre **8/10** et rejoindre le niveau de FloPy/MODFLOW-API. Sans ces 3 mois, il restera un outil scientifique interne — utile à ses auteurs et à leurs collaborateurs directs, mais invisible à l'écosystème xarray/rioxarray/ParaView et incompatible avec les exigences FAIR des financeurs publics.
