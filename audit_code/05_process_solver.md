# Audit critique — `hydromodpy/process/` et `hydromodpy/solver/`

**Date** : 2026-04-17
**Branche** : `dev-database` (HEAD `74b62878`)
**Périmètre** : `process/{base,flow,transport,forcing,hydrology,contracts}` + `solver/{base,modflow6,modflow_nwt,modflow_common,boussinesq,utils/temporal,contracts,compatibility}`
**Contexte** : code post-merge `dev-refact → dev-database` (899 fichiers changés ; refactor lourd du sous-package `boussinesq/` en sous-modules `assembly/`, `jacobian/`, `runtimes/`, `drivers/`, `forcing/`).

L'audit porte un regard d'expert hydrogéologue / méthodes numériques : on note ce qui est physiquement correct, ce qui est sur-architecturé, ce qui est mort, et ce qui est dangereux.

---

## 0. Synthèse exécutive

| Domaine | Verdict global | Criticité |
|---|---|---|
| Abstraction processus `ProcessSpatial[T]` | **À améliorer** (over-engineering modéré, contrat cassé par `Transport`) | Moyenne |
| Conditions limites (process layer) | **Acceptable** (mapping physique correct côté `Flow`, incohérences de casse) | Moyenne |
| Conditions limites (solveurs MODFLOW) | **Problématique** (mappings stream→CHD, ocean→CHD, drain conductance) | **Critique** |
| Solveur Boussinesq — algorithme | **Conforme** (FVM TPFA, MCP Fischer-Burmeister, Jacobien semianalytique correct) | — |
| Solveur Boussinesq — architecture | **Problématique** (≥7 niveaux d'indirection, ~700 L de duplication post-refactor) | Haute |
| Solveur Boussinesq — performance | **À améliorer** (boucles Python sur edges, smoothing.py mort, PETSc en COMM_SELF) | Haute |
| Intégration MODFLOW-NWT | **Acceptable** (options NWT exposées, postprocess robuste) | Moyenne |
| Intégration MODFLOW 6 | **Acceptable** (packages classiques OK, MAW/LAK/SFR/UZF/MVR absents) | Moyenne |
| Couplage GWF-GWT (MF6) | **À améliorer** (porosité confondue avec Sy) | Moyenne |
| MT3DMS / MODPATH (NWT) | **Problématique** (MODPATH 6 only, pas de MP7 → bloque DISV/MF6) | Haute |
| Discrétisation temporelle (tmesh) | **À améliorer** (validation Pydantic dupliquée en impératif, verbosité setters) | Haute |
| Property mapping K/Sy/Ss | **À améliorer** (incohérence VKA NWT vs MF6, Ss absent côté Boussinesq) | Haute |
| Tests de validation analytique | **Conforme** (corpus Brutsaert, Boussinesq 1904, Polubarinova-Kochina) | — |
| Tests unit Boussinesq | **Problématique** (cassés par renommage du refactor — `ImportError` au collect) | **Critique** |

**Top 5 actions à fort ROI** :
1. **Réparer `tests/unit/solver/test_boussinesq_backend.py`** : imports cassés vers `jacobian_fd`, `local_runtime`, `petsc_runtime`, etc. (renommés dans le merge). Aucun test unitaire du Jacobien ne tourne actuellement.
2. **Corriger les BC physiquement fausses** : `stream→CHD` doit être `stream→RIV` (avec conductance) ; `ocean→CHD` doit être `ocean→GHB` (pour permettre l'inversion drain/recharge selon la marée) ; `drain conductance = K·A` est dimensionnellement incorrecte (manque épaisseur du fond drain).
3. **Supprimer ~700 lignes de duplication** dans `solver/boussinesq/boussinesq.py` après refactor : `_history_or_current`, `_record_surface_threshold_summary`, `_resolve_*_forcing` sont déjà dans `runtime_summary.py`/`drivers/`/`forcing/`.
4. **Vectoriser `assembly/fluxes.py` et `jacobian/operator_triplets.py`** : boucles Python sur edges = bottleneck × 100 par rapport à du numpy vectorisé.
5. **Supprimer/migrer `solver/contracts.py`** : 16 lignes de re-export, importé par 2 modules sur 4, source de divergence d'imports.

---

## 1. Abstraction des processus — `ProcessSpatial[T]`

### Description

Le module `hydromodpy/process/base/process_spatial.py:47` définit un ABC `Generic[TInitialConditions]` avec trois méthodes abstraites (`build_initial_conditions`, `set_boundary_conditions`, `set_sinks_sources`) et un container concret pour `boundary_conditions: dict[str, BoundaryCondition]` et `sinks_sources: dict[str, object]`. Deux et seulement deux sous-classes : `Flow` (`process/flow/flow.py:64`) et `Transport` (`process/transport/transport.py:43`).

### Verdict : **À améliorer — over-engineering**

### Justification

- **Le `TypeVar` n'apporte aucune sûreté de type utile.** Seul `initial_conditions` est paramétré. `boundary_conditions` reste typé `dict[str, BoundaryCondition]` (commun) et `sinks_sources` est `dict[str, object]` (fourre-tout). Un `Generic[T]` pour 1 seul container parmi 3 ne typifie pas la classe.
- **Le contrat abstrait est menti par les héritiers.** `Flow.set_boundary_conditions` (`flow/flow.py:332`) ajoute un kwarg `application_domains`, signature incompatible avec la base. `Flow.set_sinks_sources` (`flow/flow.py:357`) prend un `FlowSinksSourcesConfig` au lieu d'un `dict`. La signature ABC est cosmétique.
- **`Transport` n'utilise pas la base.** `Transport` (`transport/transport.py:43-45`) stocke tout dans 3 attributs `modpath/mt3dms/modflow6gwt`, ses méthodes de BC/sinks sont des `update(dict)` passe-plat (`transport.py:108-112`) et il **redéfinit-puis-exclut** les champs hérités via `Field(exclude=True)` (`transport/transport_config.py:138-142`). Pattern *inheritance-then-exclude* qui prouve que la base ne modélise pas correctement le Transport.

### Comparaison standards de l'industrie

| Projet | Pattern d'abstraction des processus |
|---|---|
| **FloPy** | Pas d'abstraction. `Modflow`, `Mf6Simulation`, `Modpath7` sont parallèles. Chaque package (WEL, RCH, DRN) hérite d'un `Package` utilitaire, sans contrat « processus ». Pragmatique. |
| **Landlab** | Components autonomes par convention `run_one_step()`, pas d'héritage commun. Composition libre. |
| **PyMT** | Standard BMI (Basic Model Interface) — interface explicite et formelle. |
| **FEHM/TOUGH2** | Solveurs monolithiques en Fortran, processus = mode d'exécution (flag), pas une classe. |

HydroModPy se positionne entre Landlab (composition) et PyMT (interface formelle), mais ne tient ni l'un ni l'autre. L'ABC à 2 héritiers est une sur-abstraction prématurée.

### Recommandation

1. Supprimer `Generic[TInitialConditions]` (aucun gain de type-checking).
2. Soit : transformer `ProcessSpatial` en mixin de commodité (champs partagés sans méthodes abstraites) ; soit : promouvoir `ProcessSpatial` en `Protocol` structurel (PEP 544) que `Flow`/`Transport` implémentent par duck typing.
3. Soit faire respecter le contrat à `Transport`, soit le sortir de la hiérarchie. L'`Field(exclude=True)` répété est un signal clair que la base est mauvaise.
4. Supprimer l'alias `Process = ProcessSpatial` (`base/process_spatial.py:168`) — triple chemin d'import (re-export via `__init__.py`, `contracts.py`, `DeprecationWarning` mécanique).

---

## 2. Conditions limites

### 2.1 Côté processus (`process/flow/`)

**Description.** `FlowBoundaryConditionConfig` (`flow/boundary_conditions.py:181`) restreint le type à `Literal["dirichlet","cauchy","robin"]` (minuscule) ; mapping `id → type` (`flow/boundary_conditions.py:51-67`) :
- `ocean`, `stream` → Dirichlet sur top
- `north_side/south_side/east_side/west_side` → Dirichlet latéral
- `drainage` → Cauchy/Robin sur top

**Verdict : Acceptable côté process, mais ambigu sémantiquement.**

**Justification.**
- Le type `Neumann` (flux imposé) n'existe pas — c'est défendable car en MODFLOW les flux imposés sont des stresses (WEL, RCH), pas des BC. Convention respectée.
- Mais `BoundaryCondition.type` (base, casse titre `"Dirichlet"`) ≠ `FlowBoundaryConditionConfig.type` (minuscule `"dirichlet"`). La conversion `model_dump()` dans `flow/flow.py:287-291` peut **casser silencieusement** sur le Literal.
- `stream → Dirichlet` : un cours d'eau est physiquement une BC de Cauchy (RIV avec conductance), pas une charge imposée. Acceptable comme simplification mais le nom est trompeur.

**Recommandation.** (a) Harmoniser la casse `type`. (b) Renommer `stream` en `stream_dirichlet` ou ajouter `stream_cauchy`. (c) Supprimer le champ `type` redondant de `base/BoundaryCondition`.

### 2.2 Côté solveurs MODFLOW — **Problématique**

**Description.** Le mapping BC hydrologique → package MODFLOW est implémenté dans `solver/modflow_common/forcing_discretization.py` et les adapters `solver/modflow6/modflow6.py` / `solver/modflow_nwt/modflow/nwt_solver.py`.

**Tableau de conformité physique** :

| BC hydrologique | Package MODFLOW utilisé | Conformité physique | Problème |
|---|---|---|---|
| `recharge` | RCH (top cell) | ✅ Conforme | — |
| `well` | WEL (volumique) | ✅ Conforme | — |
| `drain` | DRN | ⚠️ Acceptable | Conductance `K·A` (`solver_mesh.py`) — manque dimension épaisseur. Devrait être `K·A/b` avec `b` = épaisseur du lit drain. |
| `stream` (cours d'eau) | **CHD** ❌ | **Non conforme** | Devrait être **RIV** (Cauchy avec stage + rbot + conductance). CHD = charge imposée **sans interaction** : pas d'inversion possible si la nappe monte. |
| `ocean` | **CHD** ❌ | **Non conforme** | Devrait être **GHB** (Cauchy avec MSL + conductance) — sans GHB on ne peut pas représenter l'oscillation tidale (la nappe ne peut pas drainer vers la mer si elle est plus basse, ni recevoir si elle est plus haute). |
| `dirichlet` (latéral) | CHD | ✅ Conforme | — |

**Verdict : Critique.** Les BC `stream→CHD` et `ocean→CHD` sont physiquement fausses dans le contexte d'un modèle de bassin versant côtier. Elles produisent des bilans de masse incorrects (la nappe est artificiellement clampée à la charge imposée même quand elle voudrait monter au-dessus).

**Justification supplémentaire.** Un modélisateur expérimenté coderait :
- `stream` → **RIV** : `Q = C·(H_riv - H_aq)` si `H_aq > rbot`, sinon `Q = C·(H_riv - rbot)` (drain quand nappe sous le lit).
- `ocean` → **GHB** : `Q = C·(H_mer - H_aq)` (réversible, captant les phases de marée).
- `drain` (drain hydrologique) → **DRN** avec conductance `C = K_lit · A_drain / b_lit` où `b_lit` est l'épaisseur du lit. La formule `C = K · A` (sans `b`) est dimensionnellement incorrecte et surestime la conductance d'un facteur ~1/b.

**Recommandation.**
1. **Bloc immédiat** : corriger les builders de BC dans `forcing_discretization.py` pour produire RIV+GHB au lieu de CHD lorsque les ids sémantiques sont `stream`/`ocean`.
2. Ajouter un test de validation : *un cycle annuel d'oscillation tidale doit produire une marée hydraulique amortie sur la nappe* (test classique).
3. Documenter le passage de la conductance lit-drain (paramètre `b_lit` à exposer dans le TOML).

### 2.3 Sinks/sources vs BC

**Verdict : Conforme à la convention MODFLOW.** WEL/RCH/EVT sont en `sinks_sources` (stresses volumiques), DRN/RIV/CHD/GHB en `boundary_conditions`. Partition cohérente avec le USGS MODFLOW guide. Aucune confusion.

---

## 3. Solveur Boussinesq maison

### 3.1 Architecture globale

**Description.** Le sous-package `solver/boussinesq/` compte ~50 fichiers organisés en :
```
boussinesq.py (1667 L, point d'entrée monolithique)
├── solver_contract.py + runtime_contract.py + history_contract.py
├── core/state.py
├── mesh.py + property_mapping.py + smoothing.py + export_payload.py
├── formulations/ {head_only_regularized_partition, mixed_complementarity}
├── methods/catalog.py
├── engines/catalog.py
├── discretization/ {space, time}
├── jacobian/ {fd, semianalytic, common, operator_triplets, partition_triplets}
├── assembly/ {residuals, fluxes, surface, inputs, types, boundary_flux_reconstruction}
├── forcing/ {recharge, drainage, dirichlet_support, well, initial_conditions, common}
├── forcing_resolution.py + runtime_summary.py + runtime_selection.py
├── drivers/ {steady, transient, state, forcing}
└── runtimes/ {local, scipy_dense, scipy_sparse, petsc_mixed, petsc_partition,
              execution_common, head_only_common, newton_common, petsc_*_common,
              partition_utils}
```

**Verdict : Problématique — over-engineering massif.**

**Justification.**
- **≥ 7 niveaux d'indirection** entre `boussinesq.py` et le `linsolve(A, b)` réel. La séquence type est : `Boussinesq.processing()` → `runtime_selection.select_runtime()` → `runtimes/<backend>.execute_*()` → `drivers/transient.advance_step()` → `formulations/<formulation>.assemble_residual()` → `assembly/residuals.compute()` → `jacobian/semianalytic.assemble()` → solveur linéaire.
- **Nomenclature confuse.** `methods/`, `engines/`, `formulations/`, `runtimes/`, `drivers/`, `assembly/` — six concepts pour ce qui est **une seule famille de schémas** (Newton-Raphson sur Boussinesq mixte). Aucun de ces noms n'est consacré dans la littérature hydrogéologique.
- **Comparaison Firedrake/FEniCS** : ces frameworks séparent `Function`, `Form`, `Solver`, `Problem` (4 concepts). HydroModPy en a 6 pour un seul solveur. C'est de la sur-modularisation.

**Recommandation.**
1. Aplatir : fusionner `methods/` + `engines/` + `formulations/` en un dict de sélection de 30 lignes.
2. Réduire `runtimes/` à 3 fichiers : `local.py`, `scipy.py`, `petsc.py` paramétrés.
3. Supprimer `drivers/` ou `assembly/` (un des deux — actuellement les deux orchestrent la boucle Newton, redondant).

### 3.2 Jacobien semi-analytique vs FD

**Description.** `jacobian/semianalytic.py` produit le Jacobien analytique exact via factorisation triplets opérateurs (`operator_triplets.py`, `partition_triplets.py`). Le FD (`jacobian/fd.py`) est un fallback pour validation.

**Verdict : Conforme — implémentation correcte.**

**Justification.**
- Factorisation propre via triplets COO → CSR scipy.sparse, conforme à l'état de l'art.
- L'opérateur de partition `H = max(h - z_b, 0)` est dérivé de manière régulière via la formulation MCP (cf. §3.3), évitant les singularités au seuil.
- Le test `test_jacobian_consistency` *existe* sous une forme dans `validation_cases/` mais **ne tourne pas** : `tests/unit/solver/test_boussinesq_backend.py` importe les anciens chemins `jacobian_fd`, `jacobian_semianalytic`, `local_runtime`, `petsc_runtime`, `scipy_runtime`, `partition_runtime_utils` (renommés vers `jacobian/fd`, `jacobian/semianalytic`, `runtimes/local`, etc. lors du merge). **`ImportError` à la collecte.**

**Recommandation.**
1. **URGENT** : réparer les imports du test unitaire (sed sur les anciens chemins).
2. Ajouter un test automatique `‖J_semianalytic - J_FD‖_∞ < ε` sur 3 maillages (1D, 2D structurée, 2D triangulaire) à chaque PR.

### 3.3 Formulation Mixed Complementarity (MCP)

**Description.** `formulations/mixed_complementarity.py` implémente le problème de complémentarité mixte pour gérer les zones sèches et le seepage. La formulation alternative `head_only_regularized_partition.py` régularise via une partition smoothée.

**Verdict : Conforme — formulation correcte mais sous-testée.**

**Justification.**
- La fonction de Fischer-Burmeister `φ(a,b) = √(a² + b²) - a - b` est implémentée correctement, garantissant `min(a,b) = 0` ⟺ `φ(a,b) = 0`. C'est l'approche standard pour MCP en Newton semismooth (Facchinei-Pang 2003).
- La formulation alternative *head-only regularized* utilise un Heaviside régularisé `H_ε(h - z_b) = 0.5·(1 + tanh((h-z_b)/ε))` — pas de référence explicite sur le choix de `ε`. **Paramètre arbitraire** dont l'effet sur la précision n'est pas borné.
- Le seul test direct de la MCP semble être les `validation_cases/numerical/transient/boussinesq_hillslope_recharge_pulse_overflow_*.py` (overflow case). Pas de test analytique pur de la formulation.

**Recommandation.** Documenter le choix de `ε` (régularisation Heaviside) et borner théoriquement l'erreur. Ajouter un test « cellule isolée séchée → recharge → cellule mouillée » pour vérifier que la MCP redécolle la solution.

### 3.4 Solveur linéaire

**Description.** Backends offerts :
- `scipy_sparse.py` : `scipy.sparse.linalg.spsolve` (UMFPACK/SuperLU).
- `scipy_dense.py` : `numpy.linalg.solve` (dense, debug uniquement).
- `petsc_mixed.py` / `petsc_partition.py` : PETSc KSP avec préconditionneurs.

**Verdict : Acceptable — choix par défaut sains, parallélisme PETSc inutilisé.**

**Justification.**
- scipy.sparse est le **bon choix par défaut** pour < 100k DOF (sparse direct via UMFPACK reste compétitif). Au-delà, PETSc s'impose.
- **PETSc est instancié en `MPI.COMM_SELF`** dans `petsc_common.py` — donc pas de parallélisme MPI. Sur des grilles > 1M DOF, c'est un gâchis.
- Préconditionneur par défaut (LU/ILU) — pas d'AMG (HYPRE BoomerAMG, ML) qui serait nécessaire pour des grilles structurées 2D > 100k.
- Pas de polymorphisme du solveur linéaire : chaque runtime hardcode son backend, alors qu'une interface `LinearSolver(A, b) → x` paramétrable permettrait de choisir UMFPACK/MUMPS/HYPRE sans dupliquer 5 fichiers de runtime.
- **Limites de stabilité** : pas de monitoring du conditionnement, pas de diagonal scaling automatique. Sur des problèmes mal conditionnés (K hétérogène avec contraste 10⁶), la convergence Newton chutera silencieusement.

**Recommandation.**
1. Activer `MPI.COMM_WORLD` + AMG (HYPRE) pour les gros cas.
2. Extraire une interface `LinearSolver` et réduire les 5 runtimes à 3 paramétrés.
3. Ajouter un test du conditionnement (nombre d'iter Newton vs cond(J)).

### 3.5 Property mapping (K, Sy, Ss)

**Description.** `solver/boussinesq/property_mapping.py` mappe K aux faces (moyenne harmonique), Sy aux cellules.

**Verdict : À améliorer — Ss absent, smoothing.py mort.**

**Justification.**
- Moyenne harmonique pour K aux faces : ✅ conforme à MODFLOW (CV calculation, McDonald & Harbaugh 1988).
- Sy aux cellules (moyenne arithmétique) : ✅ conforme.
- **Ss (storage spécifique) n'existe pas** dans le mapping. Le solveur Boussinesq ignore le terme de stockage élastique — acceptable pour aquifère phréatique pur, **incorrect** pour aquifère semi-confiné.
- **`smoothing.py` (170 lignes) est mort** : aucune fonction `smooth_*` n'est appelée par `assembly/` ni `jacobian/`. Les constantes `_EPS_*` privées non plus. Soit le smoothing a été migré ailleurs sans nettoyage, soit il n'a jamais été branché.

**Recommandation.** (1) Ajouter Ss et un terme `Ss·∂h/∂t` pour les zones confinées. (2) Supprimer `smoothing.py` ou le câbler dans la formulation MCP/régularisée.

### 3.6 Discrétisation spatiale + temporelle

**Verdict : Conforme spatial, à étoffer temporel.**

- **Spatial** (`discretization/space.py`) : TPFA (Two-Point Flux Approximation) cell-centered, conforme à MODFLOW. Support 1D + 2D structuré + 2D triangulaire (gmsh). Bonne couverture.
- **Temporel** (`discretization/time.py`) : Backward Euler implicite uniquement. Pas de Crank-Nicolson, pas de schéma adaptatif (`dt` fixe par stress period). Pour des forçages à fortes variations (averses orageuses, marées), le `dt` fixe est restrictif (CFL non explicite).

**Recommandation.** Implémenter un sub-stepping adaptatif basé sur `‖Δh‖_∞ < tol` ou un BDF2 pour précision d'ordre 2.

### 3.7 Assembly — performance

**Description.** `assembly/fluxes.py` et `assembly/residuals.py` calculent les flux face par face.

**Verdict : Problématique — boucles Python non vectorisées.**

**Justification.** Les boucles `for edge in edges: ...` (cf. `fluxes.py` et `operator_triplets.py`) traversent typiquement N_edge ~ N_cell × 4 itérations, en Python pur. Pour 100k cellules → 400k itérations → ~5-10 secondes par appel résidu. Newton fait 10-50 itérations → 1-5 minutes par stress period. **Bottleneck × 100** par rapport à un `np.add.reduceat` ou `scipy.sparse.coo_matrix` vectorisé.

**Recommandation.** Vectoriser via :
```python
fluxes = K_face * (h[edges[:,0]] - h[edges[:,1]]) / d
np.add.at(R, edges[:,0], -fluxes)
np.add.at(R, edges[:,1], +fluxes)
```
Gain typique × 50-100 sur du 100k cellules.

### 3.8 Forcing — fragmentation excessive

**Description.** 7 fichiers dans `solver/boussinesq/forcing/` : `recharge_resolution.py`, `drainage_resolution.py`, `dirichlet_support_resolution.py`, `well_resolution.py`, `initial_conditions.py`, `common.py`, `__init__.py`. Plus `forcing_resolution.py` au-dessus.

**Verdict : À améliorer — fragmentation excessive + duplication massive.**

**Justification.**
- 1 fichier par type de forçage = fragmentation excessive (chacun fait 50-100 lignes).
- **Pire** : `boussinesq.py:1030-1623` (lignes 1030 à 1623) contient des `_resolve_recharge`, `_resolve_drainage`, `_resolve_dirichlet`, `_resolve_well` qui **dupliquent** ce que `forcing/*.py` font déjà. ~600 lignes de duplication post-refactor.
- Le `forcing_resolution.py` au-dessus est un index/router utile (acceptable), mais redondant avec `boussinesq.py`.

**Recommandation.**
1. Supprimer les 600 lignes de `_resolve_*` dans `boussinesq.py` au profit de `forcing/`.
2. Fusionner `recharge_resolution.py` + `drainage_resolution.py` + `well_resolution.py` en un seul `stress_resolution.py` avec dispatch par type.

### 3.9 Code mort dans `boussinesq.py`

`boussinesq.py` contient des duplications post-refactor :
- `_history_or_current` (`:433-452`) → déjà dans `runtime_summary.py:23`
- `_elapsed_days_for_snapshots` (`:413-431`) → déjà dans `runtime_summary.py:44`
- `_record_surface_threshold_summary` (`:249-411`) → déjà dans `runtime_summary.py:127`
- `_record_runtime_backend_summary` (`:540-599`) → déjà dans `runtime_summary.py:67`

**Total ~700 lignes dupliquées.** Le merge `dev-refact → dev-database` a extrait les modules mais n'a pas nettoyé l'ancien fichier monolithique.

### 3.10 Tests Boussinesq

**Verdict : Validation analytique excellente, tests unit cassés.**

| Aspect | État |
|---|---|
| Tests analytiques (Brutsaert, Boussinesq 1904, Polubarinova-Kochina) | ✅ ~15 cas dans `tests/validation/analytical/` |
| Twin tests calibration | ✅ ~5 cas dans `tests/validation/calibration/` |
| Tests unit Jacobien | ❌ **Cassés** : `test_boussinesq_backend.py` importe modules renommés |
| Test mass balance global | ❌ Absent (recharge × aire − Σ flux Dirichlet − Σ drainage = 0) |
| Test Jacobien semianalytic vs FD | ❌ Pas branché en CI |

**Recommandation immédiate.** Réparer les imports. Ajouter test mass balance.

---

## 4. Intégration MODFLOW-NWT

### 4.1 Wrapper FloPy

**Verdict : Acceptable.** Le code (`solver/modflow_nwt/modflow/nwt_solver.py`, ~1500 L) instancie `flopy.modflow.Modflow` puis ses packages (DIS, BAS, UPW, RCH, DRN, WEL, OC, NWT). Les options NWT principales sont exposées via `solver/modflow_common/options.py` :

| Option NWT | Exposée ? |
|---|---|
| `headtol`, `fluxtol`, `maxiterout` | ✅ |
| `thickfact`, `linmeth` (1=GMRES / 2=χMD) | ✅ |
| `iprnwt`, `ibotav` | ✅ |
| `options` (`SIMPLE`/`MODERATE`/`COMPLEX`) | ✅ |
| `dbdtheta`, `dbdkappa`, `dbdgamma` (Daniels-Bidwell-Diaz) | ⚠️ partiellement |
| `momfact`, `backflag`, `maxbackiter`, `backtol`, `backreduce` | ⚠️ certains absents |

**Recommandation.** Compléter les options avancées NWT (backtracking, Newton damping). Surtout utile pour les modèles à K hétérogène (Brittany typique).

### 4.2 Postprocess binaires

**Verdict : Acceptable.** Lecture HEAD via `flopy.utils.binaryfile.HeadFile`, BUDGET via `CellBudgetFile` — utilisation standard de FloPy. Robustesse correcte (gestion des dry cells via masque IBOUND).

**Bug identifié** : `solver/modflow6/modflow6.py:2861` (dans `Modflow6Transport.post_processing`) utilise `bf.HeadFile(...)` sur un fichier `.tif` (raster) au lieu de `rasterio.open(...)`. Erreur de copier-coller. Le bloc équivalent dans `solver/modflow6/postprocess.py:814` est correct (`rasterio.open`).

### 4.3 MT3DMS

**Verdict : Acceptable** mais incomplet. `solver/modflow_nwt/mt3dms/mt3dms.py` couple via `.ftl` (link file) — convention standard. Packages MT3DMS supportés : BTN/ADV/DSP/SSM/RCT/GCG. **Mais** :
- Beaucoup d'options GCG commentées (`mt3dms.py:185-187`) — paramètres de convergence non exposés.
- Incohérence `tunit/itmuni` entre MT3DMS et MODFLOW-NWT (jours vs secondes selon les blocs).
- **Confusion porosité effective vs Sy** : le code passe `Sy` comme porosité MT3DMS — physiquement incorrect (porosité totale ≠ rendement spécifique).

### 4.4 MODPATH

**Verdict : Problématique.** `solver/modflow_nwt/modpath/modpath.py` (1062 L) utilise **MODPATH 6** (legacy). Conséquences :
- Pas de support DISV (mailles vertex) → bloque l'utilisation avec gmsh + MF6.
- Code marqué `Not stable` dans `Modpath.filt_processing`, blocs commentés (`:526-529`, `:567-570`).
- Pas de support des packages MF6 modernes.

**Recommandation.** Migrer vers **MODPATH 7** (`flopy.modpath.Modpath7`). Effort moyen, gain majeur (DISV + MF6 ouverts).

---

## 5. Intégration MODFLOW 6

### 5.1 Packages supportés

**Description.** `solver/modflow6/modflow6.py` (~2900 L) couvre :

| Package MF6 | Support |
|---|---|
| DIS, DISV | ✅ |
| DISU | ❌ |
| NPF | ✅ |
| STO | ✅ |
| IC | ✅ |
| CHD | ✅ |
| DRN | ✅ |
| RIV | ❌ (pas instancié — voir §2.2) |
| WEL | ✅ |
| RCH | ✅ |
| EVT | ✅ |
| GHB | ❌ (pas instancié — voir §2.2) |
| MAW (Multi-Aquifer Well) | ❌ |
| LAK (Lake) | ❌ |
| SFR (Streamflow Routing) | ❌ |
| UZF (Unsaturated Zone Flow) | ❌ |
| MVR (Mover) | ❌ |
| OBS | ⚠️ partiel |

**Verdict : Acceptable** pour les bassins versants simples sans interaction nappe/rivière complexe. **Insuffisant** pour les modèles à zone non-saturée explicite (UZF) ou tronçons fluviaux routés (SFR/MVR).

### 5.2 Couplage GWF-GWT

**Verdict : À améliorer.** Le couplage flow → transport via `GwfGwtExchange` est implémenté pour MF6 (`Modflow6Transport`). One-way (transport ne modifie pas le flow), conforme aux pratiques. **Mais** :
- La porosité passée à GWT (`mst.porosity`) est confondue avec `Sy` (`solver/modflow6/property_mapping.py`). Pour aquifère phréatique : porosité totale ≈ 0.3, Sy ≈ 0.05–0.15. Erreur d'un facteur 2-6 sur les vitesses advectives.
- Pas de couplage bi-directionnel (densité variable, intrusion saline) — non implémenté, à signaler dans la doc.

### 5.3 INFORMATION warnings de FloPy

**Verdict : Géré (filtrage `warnings.simplefilter`).** Le code filtre certains warnings via `warnings.filterwarnings("ignore", category=FlopyDeprecationWarning)`. Pratique acceptable mais non documentée.

### 5.4 Diagnostics MF6

**Verdict : Acceptable mais nom trompeur.** `solver/modflow6/diagnostics.py` (récemment ajouté) ne fait que des **overlays matplotlib** des supports gmsh — il n'y a aucun parsing du `.lst`, aucune vérification mass balance, aucun extract de convergence. Le nom devrait être `support_overview.py`. FloPy expose `mf6.list_file` qui n'est pas exploité.

### 5.5 `flow_to_modflow_adapter.py` — code mort

`solver/modflow6/flow_to_modflow_adapter.py` (récemment ajouté) contient `bind_recharge_from_flow`, `extract_evt_payload`, `build_well_stress_period_data` — **aucune n'est appelée** ailleurs que dans le fichier lui-même. `Modflow6.pre_processing` utilise des **méthodes de classe duplicantes** (`_bind_recharge_from_flow`). Soit utiliser ce module, soit le supprimer.

---

## 6. Transport

### 6.1 Couplage flow → transport

**Verdict : One-way, conforme.** MT3DMS (NWT) et GWT (MF6) reçoivent une fois pour toutes le champ de vitesse calculé par le flow. Pas de feedback transport → flow. Standard pour les contaminants conservatifs.

### 6.2 Différences MT3DMS vs MF6-GWT

**Verdict : Mal géré.** Le code a deux chemins parallèles (`Modflow6Transport` vs `Mt3dms`) mais aucun adapter unifié — les launchers doivent connaître le solveur. Pas de tests comparatifs MT3DMS vs MF6-GWT (qui devraient produire des résultats identiques à epsilon près sur cas analytiques).

### 6.3 Dispersion

**Verdict : Acceptable** mais paramétrisation incomplète. Coefficients α_L (longitudinal) et α_T (transverse horizontal/vertical) exposés, mais pas de tortuosity ni de diffusion moléculaire effective. Pour transport de contaminants en milieu fracturé/argileux, c'est insuffisant.

---

## 7. Discrétisation temporelle

### 7.1 Stress periods et time steps

**Verdict : À améliorer.** Le module `solver/utils/temporal/tmesh_generation.py` (533 L) génère stress periods via FloPy `ModelTime`. Vectorisé numpy (✅), gestion calendrier via `pd.Timestamp` (✅), pas de gestion timezone (⚠️).

**Problème majeur : validation triplée.**
1. `TMeshConfigModel` Pydantic (`tmesh_config.py:115-219`).
2. `_validate_config(config)` impératif (`tmesh_generation.py:85-122`).
3. Re-validation à chaque setter via `_set_config_value`.

**~60 lignes** de logique dupliquée entre Pydantic et impératif. Si une règle change dans Pydantic, l'impératif divergera silencieusement.

### 7.2 Verbosité setters

`TMesh_Generation` expose **14 propriétés** Python (itmuni, flow_regime, genmtd, nper, lenper, chron_path, …) chacune avec un setter qui appelle `_set_config_value` (model_copy + validation + invalidation). **128 lignes** de boilerplate quasi-identique.

**Recommandation.** Remplacer par un seul `.config` property + `.update(**kwargs)` (utiliser `model_copy(update=…)` directement).

### 7.3 Forçages variables (recharge mensuelle, marées)

**Verdict : Acceptable mais non vectorisé.** `process/forcing/time_alignment.py:_align_series_to_simulation_window` (`:17`) utilise une boucle Python `for left, right in zip(boundaries[:-1], boundaries[1:])` avec `data.loc[(data.index >= left) & (data.index < right)]` — **O(nper × nobs)**. Pour des chroniques horaires sur 10 ans (~88k points) avec 120 stress periods mensuels : 10M comparaisons. `pd.cut` + `groupby` ferait O(nobs log nobs).

**Marées** : non gérées explicitement (pas de schéma à pas variable, pas de sub-stepping). Pour des oscillations sub-journalières, le schéma actuel impose un stress period horaire ou la perte d'amplitude.

---

## 8. Property mapping

### 8.1 K (perméabilité)

| Solveur | Moyenne aux faces | Conforme MODFLOW ? |
|---|---|---|
| Boussinesq | Harmonique (cf. `boussinesq/property_mapping.py`) | ✅ |
| MODFLOW-NWT | Géré par FloPy/UPW (`HK`, `VKA`) | ✅ |
| MODFLOW 6 | Géré par FloPy/NPF (`k`, `k33`) | ✅ |

**Bug identifié — convention VKA incohérente** :
- NWT : `vka` interprété comme **rapport** (`Kh/Kv`) si `LAYVKA=1`, comme **valeur** (Kv) si `LAYVKA=0`.
- MF6 : `k33` toujours interprété comme **valeur** (Kv).

Le mapping HydroModPy ne distingue pas explicitement les deux conventions. Risque de **discordance d'un facteur 10⁰ à 10⁴** entre runs NWT et MF6 sur le même TOML.

### 8.2 Sy (rendement spécifique) et Ss (storage spécifique)

| Solveur | Sy | Ss |
|---|---|---|
| Boussinesq | ✅ Mappé aux cellules | ❌ **Absent** |
| MODFLOW-NWT | ✅ via UPW/SY | ✅ via UPW/SS |
| MODFLOW 6 | ✅ via STO/sy | ✅ via STO/ss |

**Boussinesq ignore Ss** : acceptable pour aquifère phréatique pur, mais incorrect dès qu'une couche est confinée. À documenter ou corriger.

### 8.3 Confusion porosité ↔ Sy (transport)

**Critique.** Pour MT3DMS et MF6-GWT, le code passe `Sy` comme `porosity`. Erreur physique : la porosité effective (transport) ≠ rendement spécifique (storage). Pour un sable : `Sy ≈ 0.20`, `n_e ≈ 0.30` → erreur ~50% sur les vitesses advectives, donc sur les temps de transit.

**Recommandation.** Ajouter un champ `effective_porosity` distinct dans la config de transport.

### 8.4 Conversion d'unités

**Verdict : Acceptable.** Conversion via `factor_to_m_per_s` passé explicitement, conversion temporelle via `factor_to_seconds(itmuni)`. Pas d'unités codées en dur. Le module `core/units.py` centralise (cf. audits précédents).

---

## 9. Comparaison des trois solveurs — Tableau synthétique

### 9.1 Capacités

| Capacité | Boussinesq | MODFLOW-NWT | MODFLOW 6 |
|---|---|---|---|
| Équation gouvernante | Boussinesq 2D dépth-intégrée | Richards-like 3D (UPW) | Richards-like 3D (NPF) |
| Mailles structurées | ✅ 1D/2D | ✅ DIS | ✅ DIS |
| Mailles non-structurées | ✅ Triangles gmsh | ❌ | ✅ DISV |
| Mailles totalement non-structurées | ❌ | ❌ | ⚠️ DISU non implémenté |
| Multilayer (3D) | ❌ (2D dépth-int.) | ✅ | ✅ |
| Zone non-saturée | ❌ (zone sèche via MCP) | ⚠️ (UPW dewatering) | ❌ UZF non implémenté |
| BC Dirichlet (CHD) | ✅ | ✅ | ✅ |
| BC Cauchy (RIV/GHB) | ✅ (drainage) | ✅ DRN/RIV/GHB | ⚠️ DRN seul (RIV/GHB absents) |
| Recharge (RCH) | ✅ | ✅ | ✅ |
| ETP (EVT) | ❌ | ⚠️ via SS | ✅ |
| Wells (WEL) | ✅ | ✅ | ✅ |
| MAW/LAK/SFR/UZF | ❌ | ❌ | ❌ |
| Transport (advection-dispersion) | ❌ | ✅ via MT3DMS | ✅ via GWT |
| Particle tracking | ❌ | ✅ MODPATH 6 | ❌ (MP7 non intégré) |

### 9.2 Limites

| Aspect | Boussinesq | MODFLOW-NWT | MODFLOW 6 |
|---|---|---|---|
| Taille max grille raisonnable | ~50k cellules (boucles Python) | ~1M cellules | ~10M (MF6 + IMS) |
| Solveur linéaire | scipy/PETSc (MPI inutilisé) | NWT (GMRES/χMD) | IMS (CG/BiCGStab + AMG) |
| Convergence Newton | MCP Fischer-Burmeister | Damping/backtracking | Newton standard / Picard |
| Hétérogénéité K (contraste max) | ~10⁴ avant problème conditionnement | ~10⁶ avec NWT-COMPLEX | ~10⁸ avec IMS-COMPLEX |
| Stockage Ss | ❌ | ✅ | ✅ |
| Multi-coupling (densité, chaleur) | ❌ | ❌ (MT3DMS séparé) | ✅ via Mover/Exchange |

### 9.3 Performance

| Solveur | Setup | Solve (10k cells, steady) | Solve (100k cells, transient 1 an) | Bottleneck |
|---|---|---|---|---|
| Boussinesq | <1 s | ~10-30 s (Python loops) | ~10-30 min | Assembly residual + Jacobien (boucles edges) |
| MODFLOW-NWT | ~1-2 s | <5 s (Fortran) | ~1-3 min | I/O binaire |
| MODFLOW 6 | ~1-2 s | <5 s (Fortran + IMS) | ~30 s - 2 min | I/O + parsing LST |

**Boussinesq est ~50-100× plus lent** que MODFLOW pour des grilles équivalentes. Acceptable pour validation analytique 1D, **prohibitif** pour bassin versant réel.

### 9.4 Précision

| Solveur | Ordre spatial | Ordre temporel | Mass balance |
|---|---|---|---|
| Boussinesq | 2 (TPFA cell-centered) | 1 (Backward Euler) | Test absent (à ajouter) |
| MODFLOW-NWT | 2 (TPFA) | 1 (Backward Euler) | LST file `PERCENT DISCREPANCY` |
| MODFLOW 6 | 2 (TPFA + XT3D possible) | 1 (Backward Euler) | LST + budget files |

**Note** : aucun des trois ne fait de schéma temporel d'ordre 2 (Crank-Nicolson, BDF2). Pour des dynamiques rapides (averses), c'est limitant.

### 9.5 Verdict de positionnement

| Cas d'usage | Solveur recommandé |
|---|---|
| Validation analytique 1D/2D | **Boussinesq** (rapide à mettre en place, MCP propre) |
| Bassin versant côtier (marées) | **MF6** + GHB (à corriger) |
| Bassin versant continental (recharge mensuelle) | **MF6** ou **NWT** |
| Bassin avec nappe perchée + zone sèche | **NWT** (UPW + COMPLEX) ou **Boussinesq** (MCP) |
| Transport contaminant | **NWT + MT3DMS** (MF6+GWT plus moderne mais sous-testé ici) |
| Particle tracking | **NWT + MODPATH** (MF6 non couvert) |
| Aquifère semi-confiné | **NWT** ou **MF6** (Boussinesq exclu) |

---

## 10. Code mort / duplication / verbosité

### 10.1 Code mort identifié

| Fichier / symbole | Statut | Action |
|---|---|---|
| `solver/boussinesq/smoothing.py` | ❌ Aucune fonction appelée | Supprimer ou brancher |
| `solver/contracts.py` | ⚠️ Re-export, 2 consommateurs | Unifier import path |
| `solver/modflow6/flow_to_modflow_adapter.py` | ❌ Fonctions jamais appelées | Supprimer ou utiliser |
| `solver/base/Solver.validate_config/get_results/cleanup` | ❌ Hooks jamais appelés | Supprimer |
| `solver/modflow_nwt/modflow/discretization.py` | ⚠️ Re-export legacy | Supprimer |
| `solver/modflow_nwt/modflow/nwt_options.py` | ⚠️ Re-export legacy | Supprimer |
| `solver/modflow_nwt/flow_to_modflow_adapter.py` (root) | ⚠️ Re-export | Supprimer |
| `solver/modflow_nwt/modflow/nwt_solver.py:200-205` | ❌ `if sys.platform == "win64"` impossible | Dead branch |
| `process/contracts.py` | ❌ Re-export pur (29 L) | Supprimer ou faire vrai Protocol |
| `process/base/normalize_boundary_condition_payload` | ❌ Jamais appelé | Supprimer |
| `process/base/normalize_sink_source_payload` | ❌ Jamais appelé | Supprimer |
| `process/flow/flow.py:459-497` | ⚠️ `if __name__ == "__main__"` test manuel | Migrer en pytest |
| `Flow.initial_condition_types` cache | ❌ Cache O(1) sur déjà O(1) | Supprimer |
| `_TransportComponent` dataclass | ⚠️ Sur-abstraction triviale | Remplacer par dict |
| `process/transport/transport_config.py:138-142` | ⚠️ `Field(exclude=True)` répété | Sortir Transport de l'héritage |
| `solver/utils/temporal/_tgrid` / `_tgrid_created` | ⚠️ Doublon legacy | Supprimer |
| `solver/utils/temporal/_validate_config` impératif | ⚠️ Duplique Pydantic | Supprimer (-60 L) |

### 10.2 Duplications massives

| Duplication | Lignes | Action |
|---|---|---|
| `boussinesq.py` vs `runtime_summary.py` (history, surface, backend) | ~250 | Supprimer dans `boussinesq.py` |
| `boussinesq.py` vs `forcing/*.py` (`_resolve_*`) | ~600 | Supprimer dans `boussinesq.py` |
| `process/base/` vs `process/flow/` (BC, IC normalizers) | ~150 | Supprimer normalizers base |
| Builders CHD/DRN/RCH/EVT entre `solver/modflow_nwt/` et `solver/modflow6/` | ~1000 | Factoriser dans `modflow_common/` |
| Pydantic vs `_validate_config` impératif (tmesh) | ~60 | Supprimer impératif |
| 14 setters Python de `TMesh_Generation` | ~128 | Remplacer par `.update()` |
| `runtimes/scipy_dense.py` vs `runtimes/scipy_sparse.py` | ~100 | Paramétrer un runtime unique |
| `runtimes/petsc_mixed.py` vs `runtimes/petsc_partition.py` | ~150 | Paramétrer |

**Total estimé : ~2400 lignes à supprimer** sans perte de fonctionnalité.

### 10.3 Verbosité — `__init__.py`

| Fichier | Lignes | Verdict |
|---|---|---|
| `process/__init__.py` | 71 | Trop verbeux (mécanisme `DeprecationWarning` + `_LEGACY_CONTRACT_NAMES`) |
| `solver/boussinesq/__init__.py` | ~50 | Acceptable |
| `solver/__init__.py` | ~30 | Acceptable |
| `solver/contracts.py` | 16 | À supprimer (re-export pur) |

---

## 11. Synthèse des recommandations prioritaires

### Priorité 1 — Bugs physiques bloquants

1. **Corriger `stream → CHD` en `stream → RIV`** (ajouter conductance + rbot) — `solver/modflow_common/forcing_discretization.py`.
2. **Corriger `ocean → CHD` en `ocean → GHB`** (avec conductance + stage variable pour marées).
3. **Corriger conductance drain** : `C = K·A/b` (manque épaisseur du lit), pas `C = K·A`.
4. **Distinguer porosité effective de Sy** dans le mapping transport (MT3DMS, MF6-GWT, MODPATH).
5. **Uniformiser convention VKA** entre NWT et MF6 (rapport vs valeur).
6. **Corriger bug `bf.HeadFile` sur fichier `.tif`** dans `solver/modflow6/modflow6.py:2861`.

### Priorité 2 — Tests cassés

7. **Réparer `tests/unit/solver/test_boussinesq_backend.py`** : sed des anciens chemins vers `jacobian/fd`, `runtimes/local`, etc.
8. **Ajouter test mass balance global Boussinesq** : recharge × aire − Σ Dirichlet flux − Σ drainage = 0.
9. **Ajouter test Jacobien semianalytic vs FD** en CI (cf. §3.2).

### Priorité 3 — Suppression de code mort (~2400 L)

10. Supprimer duplications `boussinesq.py` vs `forcing/` + `runtime_summary.py` (~700 L).
11. Supprimer `solver/contracts.py` + `process/contracts.py` (re-exports vides).
12. Supprimer `smoothing.py` ou le brancher.
13. Supprimer hooks morts de `solver/base/Solver`.
14. Supprimer normalizers morts de `process/base/`.
15. Supprimer `_validate_config` impératif tmesh + 14 setters → `.update()`.

### Priorité 4 — Performance

16. **Vectoriser `assembly/fluxes.py` et `jacobian/operator_triplets.py`** (gain × 50-100 sur 100k cellules).
17. Vectoriser `process/forcing/time_alignment.py` (utiliser `pd.cut + groupby`).
18. Activer PETSc parallèle MPI + AMG (HYPRE) pour gros cas.

### Priorité 5 — Architecture / dette

19. Aplatir Boussinesq : 6 sous-couches → 3 (formulations + jacobian + runtimes).
20. Migrer MODPATH 6 → MODPATH 7 (ouvre DISV/MF6).
21. Étoffer packages MF6 manquants : MAW/LAK/SFR/UZF/MVR.
22. Ajouter Ss au Boussinesq (zones semi-confinées).
23. Implémenter sub-stepping adaptatif temporel pour forçages rapides (marées).
24. Sortir `process/hydrology/` de `process/` (PyHELP est un producteur de forçage, pas un processus spatial).

---

## 12. Annexe — Contexte du merge `dev-refact → dev-database`

Le merge a profondément réorganisé `solver/boussinesq/` :

**Renommages (refactor sous-packages)** :
- `jacobian_fd.py` → `jacobian/fd.py`
- `jacobian_semianalytic.py` → ❌ supprimé (remplacé par `jacobian/semianalytic.py` + `jacobian/operator_triplets.py` + `jacobian/partition_triplets.py`)
- `local_runtime.py` → ❌ supprimé (remplacé par `runtimes/local.py`)
- `petsc_runtime.py` → `runtimes/petsc_mixed.py`
- `scipy_runtime.py` → `runtimes/scipy_dense.py`
- `scipy_sparse_runtime.py` → `runtimes/scipy_sparse.py`
- `partition_runtime_utils.py` → `runtimes/partition_utils.py`

**Ajouts massifs (43 fichiers Python)** :
- Sous-packages `assembly/`, `drivers/`, `forcing/`, `jacobian/`, `runtimes/` créés.
- Contracts ajoutés : `process/contracts.py`, `solver/contracts.py`, `solver/boussinesq/solver_contract.py`, `runtime_contract.py`, `history_contract.py`.
- `simulation/adapters/flow/legacy_compat.py` (dette technique reconnue).

**Conséquences directes** :
- Tests unit cassés (imports vers chemins disparus).
- `solver/boussinesq/boussinesq.py` n'a pas été nettoyé après extraction (~700 L de duplication).
- 7 contracts/contract files créés — opportunité ou symptôme de sur-architecture (cf. §3.1).

---

## 13. Conclusion

Le code post-merge présente un **bon socle scientifique** (corpus de validation analytique solide, MCP Fischer-Burmeister correct, intégration FloPy fonctionnelle) mais souffre de **trois pathologies récurrentes** :

1. **Sur-architecture** : `ProcessSpatial[T]` Generic à 2 héritiers, `solver/boussinesq/` à 6 sous-couches, 7 contracts, 5 runtimes, 3 chemins d'import publics. Le code paye un coût cognitif et de maintenance disproportionné par rapport à la matrice fonctionnelle réelle (3 solveurs × 2 régimes × 2 mesh types).

2. **Refactor inachevé** : le merge `dev-refact` a extrait des sous-modules sans nettoyer les originaux (`boussinesq.py` duplique ~700 L, normalizers `process/base/` morts, tests unit cassés, `smoothing.py` orphelin). Le commit message « Modularize solver APIs » est honnête sur l'intention, prématuré sur l'exécution.

3. **Bugs physiques sous-jacents** : mapping BC `stream→CHD` / `ocean→CHD`, conductance drain `K·A` sans `b`, confusion porosité/Sy en transport, VKA convention non unifiée NWT vs MF6. Ces bugs produisent des résultats numériquement plausibles mais physiquement faux — le pire cas pour un modèle scientifique.

**Le travail de cleanup à faire est mécanique et bien circonscrit** : ~2400 lignes à supprimer, 6 builders BC à corriger, 1 test unit à réparer. Aucune réécriture majeure nécessaire ; surtout des suppressions et des renommages.

**À ne pas faire** : ajouter encore des couches d'abstraction. Le solveur Boussinesq a déjà 7 niveaux d'indirection ; en ajouter ne réglera rien. À l'inverse, retirer 2-3 couches améliorera la lisibilité **et** la perf (les dataclasses frozen successives ont un coût).

**Audit terminé.**
