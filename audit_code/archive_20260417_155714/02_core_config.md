# Audit critique — `hydromodpy/core/`

**Scope** : `core/config/`, `core/state/`, `core/time/`, `core/tools/`, `core/units/`, `core/workspace/`, `core/backends/` (référencé pour la complétude).
**Auditeur** : expert Pydantic / architecture de configuration scientifique.
**Méthode** : lecture exhaustive, comparaison aux standards (Pydantic v2, Hydra/OmegaConf, Dynaconf, pint, xarray/pandas, FloPy, MLflow, cookiecutter-data-science, hydroeval, rioxarray).

---

## 0. Synthèse exécutive

| Domaine | Verdict global | Remarque principale |
|---|---|---|
| Pydantic v2 (API) | **Acceptable** | Utilisation correcte de `ConfigDict`/`Field`/`model_validator`, mais `extra="forbid"` incohérent (présent seulement sur `WorkspaceConfig`). |
| `ParamLevel` / `VisibleWhen` | **Non-standard mais défendable** | Pattern maison. Alternatives Hydra/Typer/Dynaconf plus idiomatiques, mais la solution reste lisible et locale. |
| `HydroModPyConfig` | **À revoir** | 400 LOC, mapping TOML→Pydantic **non 1:1** (transformations cachées, placeholders magiques, strip empty string, régex de « réparation Windows »). |
| State (`WorkflowContext`) | **À revoir** | God-object déguisé : 14 champs dans `SetupContext`, typé `Any` en partie, pas d'invariant de cycle de vie. |
| `core/units` | **Problématique** | Duplication massive (5 modules quasi-identiques), pint n'est utilisé **que** dans `length.py`, année = 365.25·86400 en dur. |
| `core/time/window.py` | **Mitigé** | 625 LOC, conventions correctes mais rigide (pas d'irrégularité, pas de timezone, aliasing `step_unit` maison). |
| `core/workspace` | **Conforme** | Clair, découverte auto, petit et lisible. Inspiration MLflow/DuckDB assumée, interopérabilité acceptable. |
| `core/tools` | **À revoir** | Mélange de code de production, d'helpers d'examples morts, singleton logging, doubles boucles Python non vectorisées, dead code conséquent. |
| `core/backends` | **Conforme** | Protocol bien défini, séparation claire adapter/impl. |

---

## 1. Système Pydantic

### 1.1 Conformité à Pydantic v2

| Item | Verdict | Justification | Recommandation |
|---|---|---|---|
| `ConfigDict(extra="forbid")` sur modèles de TOML | **À améliorer** | Utilisé seulement sur `WorkspaceConfig` (config.py:30). `HydroModPyConfig` (hydromodpy_config.py:73) utilise `ConfigDict(arbitrary_types_allowed=True)` **sans** `extra="forbid"`. Conséquence : toute section TOML typo ou inconnue est silencieusement ignorée au niveau racine. | Mettre `extra="forbid"` sur **tous** les modèles de TOML + `arbitrary_types_allowed=True` là où nécessaire. Idéalement un `BaseConfigModel(BaseModel)` commun. |
| `model_validator(mode="after")` | **Conforme** | Utilisé correctement dans `WorkspaceConfig._resolve_workspace_root` (config.py:57). Pas de `validator` v1 trouvé. | Rien à changer. |
| `Field(description=..., default=..., default_factory=...)` | **Conforme** | Descriptions en anglais, consistentes. | Uniformiser la langue (actuellement mélange fr/en dans `streamlit_config.py:389` « Configuration interactive »). |
| `arbitrary_types_allowed=True` sur `HydroModPyConfig` | **Acceptable** | Permet d'inclure des types non-Pydantic si besoin, mais **aucun champ** de la classe n'en utilise. | Supprimer la directive — elle coûte une perte de sécurité sans bénéfice. |
| `from_snapshot` (hydromodpy_config.py:293) | **Conforme** | `model_validate` + deep-merge : idiomatique. | Rien à changer. |

### 1.2 Pattern `ParamLevel` / `VisibleWhen`

`core/config/param_level.py` définit deux dataclasses `Annotated`-compatibles :

```python
catch_def: Annotated[str, ParamLevel("user")] = "dem"
x_outlet: Annotated[Optional[float], ParamLevel("user"),
                    VisibleWhen("catch_def", "from_outlet_coord")] = None
```

| Aspect | Verdict | Justification |
|---|---|---|
| Lisibilité | **Conforme** | Attache la métadonnée à côté du champ, sans table externe à maintenir. |
| Sécurité typologique | **Acceptable** | `ParamLevel` est une `@dataclass(frozen=True)` propre. `Literal["user","dev","expert"]` est correctement typé. |
| Réutilisabilité | **À améliorer** | `VisibleWhen` n'est consommé **que** par `streamlit_config.py`. Le TOML generator (`generate_toml.py`) n'en tient pas compte — les champs inappropriés apparaissent donc commentés même quand ils seraient masqués en UI. Incohérence de comportement entre les deux surfaces. |
| Comparaison à l'industrie | **Non-standard** | Hydra/OmegaConf utilise des groupes de config (`_target_`, `defaults:`). Dynaconf utilise des *environments*. Typer/argparse utilisent `--level=...`. Aucun de ces outils n'a d'équivalent direct natif au couple `(ParamLevel, VisibleWhen)`, mais ils résolvent le même besoin par *overlays* de fichiers. |
| Sur-ingénierie ? | **Acceptable** | Le couple est ~50 LOC, bien isolé, et il évite d'importer Hydra pour un seul cas d'usage. Mais il duplique partiellement ce que `Field(json_schema_extra=...)` ou le nouveau `pydantic.fields.FieldInfo.metadata` peut porter. Alternative légère : utiliser `Field(json_schema_extra={"level": "user"})` et lire via `.json_schema_extra` plutôt que via `Annotated[...]`. |

**Recommandation** : garder `ParamLevel` (petit, lisible), mais retirer `VisibleWhen` **ou** l'implémenter aussi dans `generate_toml.py` pour cohérence. Sinon c'est un piège de maintenance.

### 1.3 Tableau récapitulatif de tous les modèles Pydantic de `core/`

| Modèle | Fichier | Champs principaux | Types | Verdict |
|---|---|---|---|---|
| `HydroModPyConfig` | `core/config/hydromodpy_config.py:62` | `workspace, geographic, domain, data, flow, transport, simulation, solver, modflownwt, modflow6, display, postprocess, capability_gallery, overview, mesh_catchment` (15 sections) | Tous sous-modèles Pydantic | **À revoir** : pas de `extra="forbid"`, `arbitrary_types_allowed=True` inutile, `from_toml` de 100 lignes contient de la logique métier mélangée à du parsing. |
| `WorkspaceConfig` | `core/workspace/config.py:9` | `project_root, output_root, workspace_root` + 4 `@property` dérivées | `Path`, `Path \| None` | **Bien fait** : `extra="forbid"`, validateur clair, découverte hiérarchique saine. Détail : la docstring mentionne `catalog.duckdb` mais le code cherche aussi `catalog.db` (legacy) — à nettoyer. |

*Les autres modèles Pydantic référencés par `HydroModPyConfig` vivent hors de `core/` (spatial, process, solver, analysis…). Ils seront audités dans les rapports sectoriels correspondants.*

---

## 2. `HydroModPyConfig` — mapping TOML ↔ Pydantic

### 2.1 Le mapping est-il 1:1 ?

**Non.** Plusieurs transformations cachées sont appliquées dans `from_toml` (hydromodpy_config.py:185–291) :

| Transformation | Fichier/ligne | Verdict |
|---|---|---|
| Rejet de sections legacy (`[initializing]`, `[modflow]`) | L207–216 | **Conforme** : fail-fast explicite. |
| Injection de `project_root` depuis `HYDROMODPY_PROJECT_ROOT` ou depuis le dossier du TOML | L221–227 | **Acceptable** mais masque le comportement à l'utilisateur. Préférable : documenter dans le TOML généré. |
| Placeholder magique `__DEM_API_BOOTSTRAP__` | L235–241 | **Problématique** : valeur sentinelle en string injectée dans le path, validée par Pydantic, puis réinterprétée plus tard. Anti-pattern ; préférer un champ optionnel + un flag explicite `dem_source: Literal["file", "api"]`. |
| Résolution des paths relatifs au TOML | `_resolve_section_paths` L338 | **Acceptable** pour les paths explicites, mais introspection `Path` vs `Path \| None` fragile (utilise `__args__`, ne voit pas `Optional[Path]` imbriqué dans une Union plus large). |
| `_strip_empty_strings` (toml_loader.py:104) | Parcourt récursivement le dict pour supprimer les `""` car TOML n'a pas de `null` | **Problématique** : un champ `str = ""` légitime (ex. tag, description) est silencieusement remplacé par le défaut Pydantic. C'est un contournement du pas de null TOML qui masque des bugs. Recommandation : utiliser la chaîne littérale `"~"` ou la section absente pour indiquer `None`, ou passer à des dicts vides. |
| `_repair_path_like_basic_strings` (toml_loader.py:41) | Regex qui double-échappe `\\` dans les strings TOML « qui ressemblent à un path » | **Problématique** : hack de compatibilité Windows qui modifie le contenu avant parsing. Un path Windows dans TOML doit être écrit avec `'C:\path\dir'` (literal string) ou `"C:\\path\\dir"` (escape). Le hack encourage un format invalide. Supprimer et documenter. |
| Dérivation de `run_id` depuis le stem du TOML (`run_steady_nwt.toml` → `steady_nwt`) | L52, L288 | **Acceptable** pour un fallback, mais couplage fort entre nom de fichier et sémantique — casse dès qu'on renomme le TOML. Préférer lever un warning si `simulation.run_id` manque. |
| `base_config:` (toml_loader.py:131) : héritage récursif entre TOMLs | Mécanisme maison de fusion profonde | **Non-standard** mais utile. Hydra fait la même chose via `defaults:`. Bonne implémentation (détection de cycles, fusion item-par-item pour listes de même longueur). | 

### 2.2 Defaults physiquement sensibles ?

Les defaults sont délégués aux sous-modèles (hors `core/`) ; ici on ne juge que la composition. Le choix de `default_factory` partout pour les sous-sections est bon (évite le partage d'état entre instances). **Conforme**.

### 2.3 Maintenabilité

| Aspect | Verdict | Justification |
|---|---|---|
| Longueur de `from_toml` (~105 LOC) | **À améliorer** | La classmethod mélange parsing, validation, injection d'env, logique de fallback. Extraire `_preprocess_raw(raw, toml_path)` qui rend un dict propre, puis un simple `cls(**parsed)`. |
| Dict `section_loaders` | **Acceptable** | Patttern registry lisible, mais la variance (`_load_standard_section`, `_load_flow_section`, `_load_data_section`, `_load_optional_overview_section`) montre que le pattern « standard » n'est pas universel. Chaque exception doit être justifiée en commentaire. |
| `_deep_merge` (L317) | **Acceptable** | Ré-implémente ce que `merge_toml_payloads` fait déjà (toml_loader.py:70). **Duplication** : fusionner. |
| `_is_path_field` (L328) | **Problématique** | Détecte `Path` uniquement dans une Union directe ; ne voit pas `list[Path]` ni `dict[str, Path]`. Limitation silencieuse. |

**Recommandation globale** : fractionner `HydroModPyConfig.from_toml` en :
1. `_read_and_merge_bases(toml_path) -> dict`
2. `_apply_cross_section_rules(raw, toml_path) -> dict` (placeholder DEM, project_root, rejet legacy)
3. `_resolve_paths(raw, base_dir) -> dict`
4. `cls.model_validate(raw)` simple.

---

## 3. State Management — `WorkflowContext`

### 3.1 Structure

```
WorkflowContext
├── cfg, config_path, raw_toml, data_plan, store, sim_id, parent_sim_id, postprocess_runner  (8 champs plats)
├── setup: SetupContext       (14 champs)
├── loaded_data: LoadedDataContext (17 champs)
└── execution: ExecutionRegistry   (3 champs)
```

**Total effectif : 8 + 14 + 17 + 3 = 42 champs** dans un seul graphe, tous mutables, la plupart typés `X | None` ou `Any`.

### 3.2 Comparaison aux patterns standards

| Pattern | Usage dans HydroModPy | Comparaison |
|---|---|---|
| Scikit-learn `Pipeline` | État encapsulé dans des estimateurs (`fit` → attributs trailing `_`). Pas de bag central. | HydroModPy : bag central passif. **Non-standard.** |
| Prefect/Airflow | Contexte via `contextvar`/`FlowRun`, résultats liés à des tasks identifiables. | HydroModPy : pas de task ID → registre `models_by_run_id` mais pas de traçabilité de dépendances au moment de l'écriture. |
| xarray `Dataset` | État composite mais chaque variable est typée et versionnée. | HydroModPy : `SetupContext.geographic: Any` (setup.py:30). Aucune contrainte de type. |
| Dataclass « Context » (pattern classique) | OK pour ≤ 5–7 champs. | HydroModPy a 42 champs → **God object déguisé**. |

### 3.3 Verdict par sous-scope

| Scope | Champs | Verdict | Justification |
|---|---|---|---|
| `SetupContext` (setup.py) | 14 champs dont `geographic: Any`, `time_grid: Any`, 3 niveaux de mesh (`mesh_summary`, `mesh_bundle`, `mesh_planar`, `mesh_support`) | **Problématique** | Les 4 champs mesh suggèrent une absence de hiérarchie (un seul objet `Mesh` avec `.bundle`, `.planar`, `.support` suffirait). `geographic: Any` et `time_grid: Any` contournent complètement le typage. |
| `LoadedDataContext` (data.py) | 17 managers avec `LoadResult \| None` ou types spécifiques | **Acceptable** | Liste plate mais bien typée. Pourrait être un `dict[DataType, LoadResult]` pour une itération plus propre — actuellement chaque usage doit tester les 17 attributs. |
| `ExecutionRegistry` (execution.py) | 3 champs : `simulation_plan`, `process_runs_by_id`, `models_by_run_id` | **Conforme** | Taille raisonnable, cohérent. |
| `WorkflowContext` (run_state.py) | +8 champs additionnels (store, sim_id, parent_sim_id, postprocess_runner, data_plan, cfg, config_path, raw_toml) | **À revoir** | Les lifecycle fields (`store`, `postprocess_runner`) cassent la séparation annoncée. Soit un 4ᵉ scope `ResultStoreContext`, soit promouvoir ces champs en passage explicite aux méthodes. |

### 3.4 Cycle de vie et invariants

- Aucun assert sur l'ordre `setup → loaded_data → execution`. On peut accéder à `execution.models_by_run_id` alors que `setup.domain is None`. **Problématique** : pas d'invariant codifié.
- `get_run_for_solver` (run_state.py:63) lève `ValueError` si plusieurs runs matchent → correct fail-fast.
- `get_model(run_id)` lève `KeyError` implicite → ajouter un message d'erreur utile.

**Recommandation** : remplacer le bag central par un pattern *builder* — chaque phase retourne un objet typé immuable (`SetupResult`, `DataLoadResult`, `ExecutionResult`) que la phase suivante consomme. Alternativement, garder `WorkflowContext` mais :
1. Remplacer `Any` par des types typés (même un `Protocol`).
2. Fusionner `mesh_summary/bundle/planar/support` en un seul `MeshContext`.
3. Extraire les lifecycle fields dans un 4ᵉ scope.

---

## 4. Système d'unités — `core/units/`

### 4.1 Vue d'ensemble

5 modules + `scalar.py` + `__init__.py`, **1180 LOC total**. Chaque module expose ~5 fonctions : `CANONICAL_UNITS`, `normalize_*`, `factor_to_*`, `convert_to_*`, `parse_to_*`.

| Module | LOC | Base SI | Nombre d'unités supportées |
|---|---|---|---|
| `length.py` | 282 | m | 4 (m, km, cm, mm) |
| `time.py` | 176 | seconds | 5 (s, min, h, d, y) |
| `hydraulic_conductivity.py` | 200 | m/s | 9 |
| `hydraulic_conductance.py` | 121 | m²/s | 9 |
| `volumetric_flow.py` | 117 | m³/s | 8 |
| `radiation.py` | 109 | W/m² | 6 |

### 4.2 Verdict critique

| Aspect | Verdict | Justification |
|---|---|---|
| **Duplication** | **Problématique** | Les 5 modules ont la **même structure** : un `_*_UNIT_ALIASES: dict`, un `_*_FACTORS: dict`, puis 4 fonctions copiées-collées. ~70% du code est mécanique. Un seul module générique `Quantity` paramétré par (base, aliases, factors) ferait l'affaire. |
| **Réinvention de pint** | **Problématique** | `pint` est **déjà importé** dans `length.py` (L12–15) avec fallback manuel. Mais `time.py`, `hydraulic_*.py`, `volumetric_flow.py`, `radiation.py` ne l'utilisent **jamais**. Incohérence flagrante : soit pint est OK → tout passe par pint, soit pint n'est pas OK → supprimer `length.py:_UREG`. |
| **Définition de l'année** | **Problématique** | `time.py:61` : `"years": 365.25 * 86400.0`. Commentaire honnête (« calendar-dependent ») mais **aucune garde-fou** contre l'usage silencieux. Risque d'erreurs d'unités invisibles dans des contextes mensuels/annuels. Alternative : refuser `years` dans les conversions SI, exiger `pandas.DateOffset` pour tout calcul calendaire. |
| **Support des unités CF** | **Non-standard** | `W/m2` au lieu de `W m-2` (UDUNITS/CF-conventions). Ça marche en interne mais n'interopère pas avec les NetCDF/CF-conventions qui utilisent `W m-2`. |
| **Types d'entrée** | **À améliorer** | `convert_payload_to_m` (length.py:124) gère `Mapping`/`list`/`tuple`/`Real` + duck-typing `astype`/`copy` pour numpy/pandas. C'est en fait ce que fait `pint.Quantity` nativement. |
| **Cohérence API** | **À améliorer** | `parse_scalar_and_unit` retourne `(float, str)` ; `parse_to_m` retourne `(float, str canonical)` ; `normalize_*_unit` retourne `str`. Pas de type `Quantity` unifié — chaque appelant jongle avec des tuples. |
| **Risque d'erreur silencieuse** | **Moyennement élevé** | `factor_to_m3_per_s("m3/s")` et `factor_to_m_per_s("m/s")` partagent le token `"m3/s"` vs `"m/s"` ; une confusion d'API (appeler le mauvais `factor_to_*`) ne déclenche pas d'erreur immédiate tant que la chaîne est valide. Un type `Quantity[L/T]` empêcherait ce genre de glitch. |

### 4.3 Conversions — vérification

Vérifications rapides des facteurs critiques :

| Conversion | Valeur stockée | Valeur attendue | Verdict |
|---|---|---|---|
| `cm/day → m/s` | `1e-2/86400 ≈ 1.1574e-7` | `1 cm/day = 1e-2/86400 m/s = 1.1574e-7` | **Correct** |
| `l/s → m³/s` | `1e-3` | `1 L/s = 1e-3 m³/s` | **Correct** |
| `MJ/m²/day → W/m²` | `1e6/86400 ≈ 11.574` | `11.574 W/m²` | **Correct** |
| `kWh/m²/day → W/m²` | `3.6e6/86400 = 41.667` | `41.667` | **Correct** |
| `cal/cm²/day (Langley/day) → W/m²` | `4.184e4/86400 ≈ 0.4843` | `0.4843` | **Correct** |

Les facteurs sont justes. Le risque est structurel (duplication/année), pas numérique.

### 4.4 Recommandation

**Remplacer les 5 modules par pint.** Un `UnitRegistry` unique, des alias déclarés au chargement (`ureg.define("m2/s = m**2/s")` etc.), et des helpers minces `to_si(value, dimension)`. Gain estimé : -800 LOC, moins de bugs, interop CF-conventions.

Si pint est jugé trop lourd : factoriser **un** module générique :

```python
class UnitSystem:
    def __init__(self, canonical: str, aliases: dict[str, str], factors: dict[str, float]): ...
    def normalize(self, unit: str) -> str: ...
    def factor(self, unit: str) -> float: ...
    def convert(self, value: float, unit: str) -> float: ...
    def parse(self, value, *, default_unit: str) -> tuple[float, str]: ...
```

---

## 5. Workspace — `core/workspace/`

### 5.1 Structure

```
core/workspace/
├── __init__.py         7 LOC
├── config.py         111 LOC   WorkspaceConfig (Pydantic)
├── path_registry.py   80 LOC   WorkspacePathRegistry (dataclass frozen)
└── workspace.py       58 LOC   Workspace (classe runtime)
```

### 5.2 Convention de répertoires

```
workspace_root/
├── hydromodpy.duckdb            # single source of truth
├── data/
│   └── cache.duckdb
└── projects/
    └── <project>/
        ├── config.toml
        └── simulations/<uuid>.zarr/
```

| Comparaison | Verdict |
|---|---|
| **cookiecutter-data-science** | Convention = `data/`, `notebooks/`, `models/`, `reports/`. HydroModPy n'a pas `notebooks/` ni `reports/` → **non-standard**, mais les conventions CCDS sont orientées ML/analyse, pas simulation. Acceptable. |
| **DVC** | `.dvc/`, `data.dvc`, remote storage. HydroModPy n'utilise pas DVC → versioning des inputs = provenance DuckDB seulement. **Acceptable** pour un outil de simulation, moins bon pour reproductibilité stricte. |
| **MLflow** | `mlruns/<exp_id>/<run_id>/artifacts,metrics,params,...`. HydroModPy = `simulations/<uuid>.zarr/` avec tout dans Zarr. **Proche du pattern MLflow**, simplement avec un seul artefact Zarr au lieu d'un répertoire plat. Bon compromis stockage/interrogabilité. |
| **FloPy** | Pas de convention (chaque modèle = un dossier avec des fichiers MODFLOW). HydroModPy **améliore** la situation. |

### 5.3 Critique ciblée

| Élément | Verdict | Remarque |
|---|---|---|
| `WorkspaceConfig.discover_workspace_root` (config.py:64) | **Acceptable** | Heuristique claire. Le support de `catalog.db` (legacy) peut être supprimé dès qu'une migration est actée. |
| `catch_name = project_root.name` (config.py:91) | **À améliorer** | « catch_name » est un vestige du vocabulaire « catchment ». Un projet peut ne pas être un bassin versant (batch multi-sites). Renommer `project_name`. |
| `solver_scratch_folder = .solver_scratch` (config.py:95) | **Conforme** | Préfixe `.` pour masquage UNIX, bonne pratique. |
| Duplication `WorkspaceConfig` vs `WorkspacePathRegistry` | **À améliorer** | Les propriétés `catch_name`, `solver_scratch_folder`, `data_path`, `catalog_path` sont **dupliquées** entre `config.py` et `path_registry.py`. Un seul objet devrait porter les paths — laisser Pydantic au TOML (config.py) et faire du `PathRegistry` un **proxy read-only** qui délègue, pas une copie. |
| `Workspace.__init__` (workspace.py:46) | **Acceptable** | Effets de bord : `create_folder(project_root)` + `setup_simulation_log(project_root)`. Documenté. Mais avec `Workspace` instancié, on a déjà mis un répertoire et un handler de log sur disque → côté test, impossible d'instancier sans pollution FS. |
| `_resolve_bin_path` (workspace.py:25) | **Acceptable** | Fallback explicite entre deux candidates. |

---

## 6. Time management — `core/time/window.py`

### 6.1 Capacités couvertes

- Fenêtre `[start, end]` inclusive, bornes `[start, end_exclusive)` internes.
- Pas de temps : `hour`, `day`, `month`, `year` (tokens canoniques fermés).
- Politique de couverture : `error` / `warn` / `ignore`.
- Export `lenper` (secondes) pour MODFLOW.

### 6.2 Comparaison aux standards

| Capacité | HydroModPy | pandas `DatetimeIndex` | xarray `CFTimeIndex` | Verdict |
|---|---|---|---|---|
| Timezones | **Non-supporté** (`pd.Timestamp` naif) | Supporté | Supporté | **Problématique** si l'utilisateur fournit des dates TZ-aware dans TOML. |
| Années bissextiles (month/year) | `pd.DateOffset(months=n)` | Calendaire correct | Calendaire correct (+ calendriers 360_day, noleap, julian) | **Conforme** pour les incréments ; mais `timedelta_to_seconds` sur un `DateOffset` ne fonctionne pas si le DateOffset n'a pas `.total_seconds()` → le code contourne en utilisant des Timestamps (`boundaries[i+1] - boundaries[i]` donne un `Timedelta` réel). **OK**. |
| Pas de temps irréguliers | **Non-supporté** | Supporté | Supporté | **À améliorer** : `_build_time_boundaries` rejette tout end_datetime non-aligné. Pas de `lenper` variable possible hors d'un `step_value` constant. Limitation sévère pour la calibration sur observations réelles (pas terrain ≠ pas de simulation). |
| Pandas frequency string (`2H`, `3MS`, …) | Construit manuellement (window.py:404) | Natif | Natif | **Acceptable** mais fragile : `'H'` est déprécié en pandas 2.2+ (devenu `'h'`). Vérifier. |

### 6.3 Critique ciblée

| Élément | Verdict | Remarque |
|---|---|---|
| `_inclusive_end_to_exclusive_end` (L227) | **Problématique** | Règle magique : si `step_unit == "hour"` → +1h, sinon → +1d. Cela signifie que pour un step `month`, un end `2025-12-31` devient `2026-01-01` inclusif. Pour un step `year`, idem. Le comportement n'est pas documenté clairement côté utilisateur. |
| `_parse_step_spec` + double validation (L187) | **À améliorer** | Parse la valeur, parse l'unité, puis vérifie la cohérence. Logique triplée (si `step_value="3 days"` et `step_unit="day"`, on re-normalise les deux). Une seule passe suffirait. |
| `validate_recharge_coverage` (L525) | **À améliorer** | 100 LOC de branches. À découper en (1) coercion vers `pd.Series`, (2) alignement sur périodes, (3) contrôle NaN. |
| Hardcoded aliases month (`"m", "mo", "mon"`) (L170) | **Problématique** | `"m"` est ambigu avec `"minutes"` (`TIME_UNIT_ALIASES["m"] = "minutes"`). Le `_parse_step_spec` fait une résolution préalable puis re-essaie, mais la priorité locale à `step_unit` crée un couplage fragile. Utiliser un token sans ambigüité (`mon` ou `month`). |
| `ResolvedSteadySimulationTimeGrid` avec `period_lengths_seconds=(1.0,)` par défaut (L97) | **Acceptable** | Convention « stress period unitaire » pour stationnaire. À documenter dans la docstring. |

### 6.4 Opportunité d'optimisation

`_build_time_boundaries` boucle Python (`while current < end_exclusive`). Pour des horizons longs (ex. 50 ans × 1 jour = 18250 itérations), utilisable. Pour millénaires en horaire, très lent. **Remplacer par `pd.date_range(start, end, freq=simulation_time_pandas_frequency(window))`** — test strict d'alignement via `date_range(...)[-1] == end_exclusive`. Gain : -20 LOC, 10× plus rapide sur gros pas.

---

## 7. Tools — `core/tools/`

### 7.1 Vue d'ensemble

| Fichier | LOC | Rôle | Utilisateurs | Verdict |
|---|---|---|---|---|
| `log_manager.py` | 294 | Singleton de logging | Partout dans la codebase | **À améliorer** (singleton, sur-ingénierie) |
| `raster_io.py` | 403 | I/O raster GeoTIFF/NetCDF | `hydromodpy.data.climatic.sim2`, `solver/...`, `spatial/geographic/domain_rasters` | **À améliorer** (réinvente rioxarray partiellement) |
| `geospatial.py` | 152 | Projections, masques polygone | `spatial/`, `data/` | **À améliorer** (double boucle Python pour masque) |
| `statistics.py` | 100 | RMSE/NSE/KGE/MARE | `examples_legacy/04`, tests de régression | **À améliorer** (hydroeval existe) |
| `display.py` | 85 | Style matplotlib + bannière ASCII | `analysis/display/...` | **Conforme** (petit, focalisé) |
| `filesystem.py` | 35 | `create_folder`, `load_csv`, `load_shapefile` | `core/workspace/workspace.py`, plusieurs managers | **Conforme** (petit) |
| `visualization.py` | 315 | Plots d'examples | **Un seul fichier** : `examples_legacy/00_quick_test.../example_00.py` | **Dead code / à déplacer** |
| `io_utils.py` | 379 | Helpers d'examples | **Un seul fichier** : même example_00 | **Dead code / à déplacer** |
| `folder_root.py` | 148 | `HYDROMODPY_RESULTS` env var setup interactif | 2 examples legacy + notebooks | **Dead code** (utilise `input()` + `os.system("setx ...")` — anti-pattern) |

### 7.2 `log_manager.py`

| Aspect | Verdict | Justification |
|---|---|---|
| Utilisation de la stdlib `logging` | **Conforme** | Pas de réinvention. |
| Singleton `_instance = None` | **À améliorer** | Anti-pattern en Python ; la stdlib `logging` est **déjà** globalement accessible via `logging.getLogger("hydromodpy")`. La classe `LogManager` n'ajoute qu'un mapping `mode → level` + gestion des handlers. Tout ce code (294 LOC) peut se réduire à ~30 LOC : une fonction `configure_logging(mode, log_dir=None)` et `get_logger(name)`. |
| `set_simulation_log` (L134) avec retry PID | **Acceptable** | Retry sur `PermissionError` en ajoutant le PID au filename — utile en parallèle. Bon réflexe. |
| `_suppress_library_logs` (L236) | **Conforme** | Silence `fiona`, `rasterio`, `matplotlib`, etc. à `CRITICAL` par défaut. Pratique. |
| Duplication : `setup_simulation_log` (L283) vs `LogManager.set_simulation_log` | **À améliorer** | `setup_simulation_log` délègue à `LogManager._instance`. Si `_instance` est None (pas d'init préalable), silencieux. Flakiness garantie. |

### 7.3 `raster_io.py`

| Aspect | Verdict | Justification |
|---|---|---|
| Pourquoi pas rioxarray direct ? | **À améliorer** | `load_to_xarray` utilise `xr.open_dataset` puis `ds.rio.write_crs` / `ds.rio.reproject`. 90% du code ré-implémente ce que `rioxarray.open_rasterio(path, masked=True)` fait en une ligne. |
| `_is_crs_invalid` (L246) | **Problématique** | Détection par **chaînes de caractères** (`"EngineeringCRS"`, `"UNIT[\"unknown\""`, `"LOCAL_CS"`, …) — fragile selon la version de pyproj. Utiliser `crs.is_projected` / `crs.to_epsg() is None` / `crs.is_geographic`. |
| `load_to_numpy` (L56) | **À améliorer** | 115 LOC qui mélangent vector/raster, CRS parsing, reprojection. Signature avec 5 paramètres, dont 3 optionnels. Les chemins d'erreur loggent puis **retournent None** silencieusement — mauvaise pratique. Préférer des exceptions. |
| Parsing manuel du `time.units` NetCDF (L217) | **Problématique** | Réinvente `cftime` / `xr.decode_cf`. Ne supporte que `"month(s)"`, `"day(s)"`, et les patterns date `"%Y/%m/%d"` / `"%d/%m/%Y"`. Une fois de plus, **non-CF-convention compliant**. xarray gère nativement via `decode_times=True` + `cftime`. |
| `reproject_tif` (L340) | **À améliorer** | Écrit **deux fichiers** (WGS84 intermédiaire puis UTM). Rioxarray / rasterio permet de reprojeter en mémoire en un seul passage. I/O gaspillé. |

### 7.4 `geospatial.py`

| Fonction | Verdict | Remarque |
|---|---|---|
| `select_within_polygon_points` (L125) | **Problématique (perf)** | Double boucle Python sur la grille pour tester `polygon.contains(Point(LON[i,j], LAT[i,j]))`. Pour une grille 1000×1000 : 1e6 appels Shapely. **Remplacer** par `shapely.vectorized.contains(polygon, LON, LAT)` (vectorisé). Gain attendu : 100× à 1000×. |
| `transform_coordinates` (L77) | **Problématique (perf)** | Double boucle `for row/for col` sur tous les pixels DEM. Utiliser `np.meshgrid` + `transformer.transform(X, Y)` vectorisé. |
| `reproject_coord` (L29) | **Acceptable** | Simple et isolé. |
| `convert_units(df, var_key)` (L144) | **Problématique** | Switch sur `var_key` hardcodé (précipitation ×1000, température −273.15, radiation ×1e-6). Hors structure unitaire. **Supprimer et utiliser le système d'unités**. |
| `basin_area` (L22) | **Acceptable** | Correcte si résolution en mètres, mais l'unité de sortie (km²) est hardcodée. |

### 7.5 `statistics.py`

| Aspect | Verdict | Justification |
|---|---|---|
| NSE/KGE/RMSE maison | **Acceptable** | Implémentations correctes. Masquage NaN présent. |
| Comparaison à `hydroeval` / `spotpy` | **Non-standard** mais défendable | `hydroeval` est une dépendance légère qui fournit la même chose avec plus de variantes. Remplacer = -50 LOC. |
| `hydrological_mean` (L72) | **Problématique** | Logique cryptique : calcule la fin de la dernière année complète avec une arithmétique d'index ésotérique (`- 3 <= 0`). Bug potentiel sur jours non-consécutifs. Pas de tests unitaires dédiés visibles. À documenter ou réécrire avec `pd.Grouper(freq='YE')`. |

### 7.6 `folder_root.py`

**Verdict : dead code à supprimer.** Utilise `input()` interactif, `os.system("setx HYDROMODPY_RESULTS ...")` (Windows-only) ou `export` (POSIX, mais export ne persiste pas entre shells). Zone mélangeant `#%% LIBRAIRIES` / `#%% NOTES` / code commenté (`# class simulation_time:` L113–136). **Usage** : seulement dans 2 exemples legacy + 2 notebooks. Les tests ne l'utilisent pas.

### 7.7 `io_utils.py` et `visualization.py`

**Verdict : à déplacer.** Utilisés exclusivement par `examples_legacy/00_quick_test_of_wide_hydromodpy_capabilities/example_00.py`. N'ont rien à faire dans `core/tools/` (qui est censé être l'infrastructure). Proposition : déplacer dans `examples_legacy/_helpers/` ou supprimer si l'example 00 est obsolète.

`io_utils.extract_watershed` appelle `Watershed(...)` legacy (importé depuis `hydromodpy.watershed`) — **dead code** selon CLAUDE.md qui parle de migration vers `Project`.

---

## 8. Backends — `core/backends/`

(Hors scope principal, mais noté pour complétude.)

| Aspect | Verdict | Justification |
|---|---|---|
| `WhiteboxBackend` Protocol | **Conforme** | Protocol minimal, docstring explicite, découplage clair. |
| `WhiteboxWorkflowsBackend` (913 LOC) | **Acceptable** | Concrete adapter. La taille est justifiée par la couverture de fonctionnalités WhiteboxTools. |

---

## 9. Tests et code mort

### 9.1 Candidats à suppression immédiate

| Fichier | Raison |
|---|---|
| `core/tools/folder_root.py` (148 LOC) | Dead : `input()` / `os.system`. 2 examples legacy seulement. |
| `core/tools/io_utils.py` (379 LOC) | Helpers exclusifs d'`example_00`. Hors scope `core/`. |
| `core/tools/visualization.py` (315 LOC) | Idem. Hors scope. |
| `core/tools/statistics.py:hydrological_mean` (L72) | Cryptique, non testé. |

Total supprimable : **~950 LOC** (~13% de `core/`).

### 9.2 Candidats à factorisation

| Zone | Action |
|---|---|
| `core/units/*.py` (1180 LOC) | Factoriser en un module générique ou passer à pint → **-600 à -800 LOC**. |
| `core/workspace/{config.py, path_registry.py}` | Déduplifier les 4 propriétés (`catch_name`, `solver_scratch_folder`, `data_path`, `catalog_path`) → **-20 LOC**. |
| `toml_loader._deep_merge` vs `merge_toml_payloads` | Fusionner → **-10 LOC**. |
| `core/tools/log_manager.py` (294 LOC) | Réduire à ~60 LOC (abandonner le singleton, utiliser `logging.dictConfig`). → **-230 LOC**. |

### 9.3 Tests à auditer

Les tests d'unité `tests/unit/units/test_*.py` (un par module) couvrent l'API mais **doublent l'API** (chaque module teste sa propre table d'alias). Si on unifie via pint, ces tests peuvent fusionner en un seul `test_units.py` paramétré.

---

## 10. Recommandations prioritaires (ordonnées par ROI)

1. **Supprimer** `core/tools/folder_root.py`, `io_utils.py`, `visualization.py` (dead code ou hors scope). → -950 LOC immédiates.
2. **Ajouter `extra="forbid"`** sur `HydroModPyConfig` et tous les sous-modèles. → Sécurité typos TOML.
3. **Retirer** le placeholder `__DEM_API_BOOTSTRAP__` → champ `dem_source` explicite (Literal).
4. **Supprimer** `_repair_path_like_basic_strings` (toml_loader.py) et documenter la syntaxe TOML correcte pour Windows.
5. **Remplacer** `_strip_empty_strings` par une convention claire : absence de clé = `None`. Documenter que `""` reste une chaîne vide légitime.
6. **Factoriser** `core/units/` : soit pint, soit un unique `UnitSystem` générique.
7. **Réduire** `LogManager` à 60 LOC via `logging.dictConfig`.
8. **Remplacer** les doubles boucles Python dans `geospatial.py` par `shapely.vectorized`/`np.meshgrid`.
9. **Migrer** `raster_io.load_to_xarray` vers `rioxarray.open_rasterio` + `xr.decode_cf`.
10. **Durcir** le typage de `WorkflowContext` : remplacer les `Any` par des Protocols/types concrets, fusionner les 4 champs mesh.
11. **Supprimer** `arbitrary_types_allowed=True` de `HydroModPyConfig`.
12. **Découper** `from_toml` en 4 étapes clairement nommées.

---

## 11. Bilan

`core/` de HydroModPy est globalement **fonctionnel et lisible**, avec un effort visible d'organisation (Pydantic v2 partout, scopes de state explicites, backends isolés via Protocol). Les faiblesses principales sont :

- **De la dette technique de parsing TOML** (hacks pour Windows, strip empty string, placeholders sentinelles).
- **Une réinvention partielle de pint** (5 modules d'unités quasi-identiques, incohérence pint-oui/pint-non).
- **Du dead code dans `tools/`** (~950 LOC d'helpers d'examples).
- **Un `WorkflowContext` trop gros** (42 champs) qui tend vers l'anti-pattern God object.

Aucun de ces problèmes n'est bloquant, mais ils constituent une dette significative à rembourser avant que la surface API (CLI `hmp config`, Streamlit UI, runners) ne s'y calcifie.

**Note globale core/** : **6.5/10** — fonctionnel, maintenable à court terme, à refactorer à moyen terme.
