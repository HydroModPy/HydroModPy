# Data Managers (Racine)

Ce dossier contient:
- les **sous-packages thematiques** (`geology/`, `hydrometry/`, etc.),
- la **couche racine d'orchestration** (activation, validation, planification des types).

L'objectif de la couche racine est de decider, de maniere deterministe, **quels types de donnees sont actifs** pour un run.

---

## Fichiers racine

- `__init__.py`  
  API publique du package racine (`DataManagersConfig`, `DataManagersPlanner`, `DataLoadPlan`, `DataManagers`, `DataManagersRuntimeLoader`).

- `data_managers_config.py`  
  Schema Pydantic du bloc `[data]`:
  - validation/normalisation de `data.types`,
  - validation des sous-sections actives (`data.geology`, `data.hydrometry`, ...),
  - resolution de chemins pour les sections typees (actuellement `geology`),
  - politique d'inference via `data.inference_mode` (`warn` ou `strict`).

- `planner.py`  
  Moteur d'inference (`DataManagersPlanner`) qui fusionne:
  - types explicites (TOML),
  - types deduits (regles runtime).

- `plan.py`  
  Contrat immuable `DataLoadPlan` (types explicites, types inferes, raisons d'inference).

- `data_managers.py`  
  Conteneur runtime leger `DataManagers` consomme par l'orchestration.

- `runtime_loader.py`  
  Chargement runtime des donnees activees, pilote par `DataLoadPlan`.
  Ce module porte la logique de dispatch par type (`oceanic`, `hydrometry`,
  `hydrography`, etc.) pour garder le launcher mince.
  Il ne met pas a jour les structures metier (domain/process): ces binders
  sont appeles ensuite par le launcher.

---

## Flux de resolution

1. Charger et valider `[data]` avec `DataManagersConfig`.
2. Construire un `DataLoadPlan` via `DataManagersPlanner`.
3. Appliquer le plan sur la config (`with_resolved_types(...)`).
4. Charger les donnees via `DataManagersRuntimeLoader`.
5. Consommer les types actifs via `DataManagers.from_config(...)` ou `DataManagers.from_plan(...)`.

---

## Regles d'inference actuelles

- `domain.zone_ids` contient `geology` -> active `geology`
- `flow.active_bc` contient `stream` -> active `hydrography`
- `flow.active_bc` contient `ocean` -> active `oceanic`

Chaque inference est tracee dans `DataLoadPlan.reasons_by_type`.

En mode `data.inference_mode = "strict"`, une inference impose la presence
explicite de `data.<type>` (sauf `geology`, qui peut etre auto-defaulte).

---

## Convention d'extension

Pour ajouter une nouvelle regle:
1. Ajouter la logique dans `DataManagersPlanner.build(...)`.
2. Ajouter une raison explicite (`"inferred from ..."`).
3. Ajouter un test unitaire dans `tests/unit/data_managers/test_data_managers_planner.py`.
4. Mettre a jour ce README.

Principe: garder des regles **pures, deterministes, testables** (pas d'effets de bord).
