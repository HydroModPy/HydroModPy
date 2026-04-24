# Analyse du problème `hydromodpy/calibration/benchmark.py`

Document de diagnostic pour décider si on porte ce module vers l'API
publique `run_calibration_cli()` ou si on le garde en l'état.

---

## 1. Les deux chemins de calibration qui cohabitent

### 1.1 Chemin canonique — `run_calibration_cli()`

- Fichier : `hydromodpy/calibration/cli.py` — 401 lignes.
- Schéma TOML : `[calibration]` (simple), validé par `CalibrationConfig`
  (Pydantic).
- Orchestration :
  1. Validation Pydantic,
  2. `prepare_trials()` une seule fois (setup partagé),
  3. boucle ask/tell via `CalibrationEngine`,
  4. persistence dans `calibration_iterations` (DuckDB),
  5. promotion optionnelle vers `simulations` (`save_runs="best_n"|"all"`).
- Optimiseurs : résolus par `build_optimizer()` qui pioche dans
  `hydromodpy/calibration/adapters/` (Optuna, scipy, grid, GP,
  DA-MH-GP).

### 1.2 Chemin parallèle — `benchmark.py`

- Fichier : `hydromodpy/calibration/benchmark.py` — 1794 lignes.
- Schéma TOML : `[model_calibration]` (riche), parsé *à la main* avec
  `tomllib` + dataclasses internes (`_ParameterCfg`, `_OutputCfg`,
  `_ObjectiveBlockCfg`, `_ModelCalibrationCfg`, `_LauncherCfg`).
- Orchestration :
  1. Parse TOML brut,
  2. `ModelCalibrationLauncher` instancie un `hydromodpy.Project` par
     candidat,
  3. chaque candidat est matérialisé en TOML overlay via
     `actualize_candidate()`,
  4. sorties extraites via `select_candidate_outputs()`,
  5. persistence en `iteration_history.jsonl` (pas le catalog DuckDB).
- Optimiseurs : 7 drivers écrits en dur
  (`_driver_grid_search`, `_driver_random_search`, `_driver_cma_es`,
  `_driver_simplex`, `_driver_nelder_mead`, `_driver_gp_mapping`,
  `_driver_da_mh_gp`).

### 1.3 Pourquoi deux chemins

Les validation cases scientifiques ont besoin de fonctionnalités que
`[calibration]` ne couvre pas :

- `[[model_calibration.parameter]]` avec `target` en dotted-path et
  `mode="replace"|"scale"`,
- `[[model_calibration.output]]` avec extraction déclarative et
  `observed_values` (support du twin synthétique),
- `[[model_calibration.objective_block]]` pondérés,
- candidats matérialisés en TOML overlay pour rejouer a posteriori.

Plutôt que d'enrichir `[calibration]`, un second chemin a été construit
en parallèle. Aujourd'hui il n'existe plus aucun consommateur en dehors
de `validation_cases/calibration/` et des 4 tests `test_twin_*`.

---

## 2. Duplications factuelles avec `hydromodpy/calibration/adapters/`

| Optimiseur     | `benchmark.py`          | Adapter canonique                          |
|----------------|-------------------------|--------------------------------------------|
| grid           | `_driver_grid_search`   | `adapters/grid_adapter.py`                 |
| random         | `_driver_random_search` | (via Optuna `TPESampler` / `GridSampler`)  |
| CMA-ES         | `_driver_cma_es`        | `adapters/scipy_adapter.py` (+ `cma` pkg) |
| simplex        | `_driver_simplex`       | `adapters/scipy_adapter.py` (`minimize`)   |
| Nelder-Mead    | `_driver_nelder_mead`   | `adapters/scipy_adapter.py`                |
| GP mapping     | `_driver_gp_mapping`    | `adapters/gp_mapping_adapter.py`           |
| DA-MH-GP       | `_driver_da_mh_gp`      | `adapters/da_mh_gp_adapter.py`             |

Les 7 drivers de `benchmark.py` existent déjà en version canonique.
C'est la différence de schéma TOML et de persistence qui force le
doublon, pas la différence d'algorithmes.

---

## 3. Consommateurs

| Consommateur                                        | Lignes | Dépendance              |
|-----------------------------------------------------|--------|-------------------------|
| `validation_cases/calibration/shared/runtime.py`    | 1073   | import ligne 15         |
| `tests/validation/calibration/test_twin_*.py` (x4)  | ~80 chacun | via le runtime ci-dessus |

Aucun autre fichier de `hydromodpy/` ne dépend de `benchmark.py`.

Fonctions publiques effectivement utilisées :

- `ModelCalibrationLauncher`
- `ModelCalibrationObjectiveEvaluator`
- `actualize_candidate`
- `select_candidate_outputs`

---

## 4. Le chemin de portage

### 4.1 Côté API publique

1. Enrichir le schéma Pydantic `CalibrationConfig` pour absorber
   `[model_calibration]` :
   - `parameters`: accepter `target` dotted-path + `mode`,
   - `outputs`: section déclarative avec `observed_values`,
   - `objective_blocks`: liste pondérée.
2. Exposer l'équivalent d'`actualize_candidate` via l'API publique
   (probablement sous `project.calibrate()` avec un flag
   `materialize_candidate=True`).
3. Router les 7 méthodes sur les adapters existants (suppression des
   7 `_driver_*`).

### 4.2 Côté validation / tests

4. Réécrire `validation_cases/calibration/shared/runtime.py` sur
   `run_calibration_cli()` ou `project.calibrate()`.
5. Recalibrer les 4 tests `test_twin_*` pour matcher les goldens
   scientifiques existants (risque principal).

### 4.3 Côté catalog

6. Migrer la persistence `iteration_history.jsonl` vers le schéma
   `calibration_iterations` du catalog DuckDB (écriture bulk déjà
   supportée par `run_calibration_cli`).

### 4.4 Nettoyage

7. Supprimer `hydromodpy/calibration/benchmark.py` (-1794 lignes).
8. Supprimer l'entrée correspondante dans `LEGACY_REMAINING.md`.

---

## 5. Risques

- **Goldens scientifiques** : les tests `test_twin_*` comparent des
  valeurs numériques contre des références. Un changement d'ordre
  d'évaluation ou d'initialisation (random state, LHS) peut faire
  diverger les goldens sans bug fonctionnel.
- **Schéma TOML** : `[model_calibration]` et `[calibration]` ont des
  conventions de nommage différentes. L'absorption doit être rétro-
  compatible ou les TOMLs existants doivent être migrés.
- **Format `iteration_history.jsonl`** : si un outil externe
  (notebook, dashboard) le lit, la migration DuckDB casse ce chemin.
- **`actualize_candidate`** : pas d'équivalent public aujourd'hui. Il
  faut concevoir l'API (où vit-elle, quel niveau d'abstraction).

---

## 6. Gain attendu

- `-1794` lignes de code dupliqué.
- Un seul chemin calibration (au lieu de deux) — le fix d'un bug
  s'applique partout.
- Les validation cases valident l'API publique au lieu d'un harnais
  parallèle — c'est le vrai test d'intégration.
- Persistence unifiée dans le catalog DuckDB — les iterations sont
  requêtables avec les mêmes outils que les simulations normales.
- Élimination d'un parse TOML en direct qui court-circuite Pydantic
  (viole `CLAUDE.md` : « Pydantic partout »).

---

## 7. Recommandation

Refactor à fort impact mais à fort risque. Hors périmètre d'une passe
de nettoyage automatisé. Trois options raisonnables :

- **Option A — laisser en l'état** : documenté dans
  `LEGACY_REMAINING.md`, coût d'entretien réel mais pas urgent.
- **Option B — portage complet** : ~2 à 5 jours de travail, exige
  une phase de recalibration des goldens avec supervision scientifique
  (et probablement pair review par un domain expert).
- **Option C — portage partiel** : enrichir `CalibrationConfig` pour
  accepter le schéma riche, router sur les adapters existants, mais
  garder l'harnais de validation tel quel pour préserver les goldens.
  Bénéfice : -50 % à -70 % des lignes tout en ne touchant pas les
  tests `test_twin_*`.

Option C est probablement le meilleur compromis risque/valeur.
