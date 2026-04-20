# Audit critique — package `hydromodpy/core/`

**Date :** 2026-04-17
**Branche :** `dev-database` (tip `74b62878`, post-merge `dev-refact`)
**Périmètre :** `hydromodpy/core/` — 40 fichiers Python, ~7 380 lignes réparties en
`config/`, `state/`, `time/`, `units/`, `tools/`, `workspace/`, `backends/`.
**Auditeur :** regard d'expert Pydantic/TOML/standards scientifiques Python.

Post-merge, seuls `core/__init__.py`, `core/backends/__init__.py` et
`core/state/setup.py` ont été modifiés — le reste du package était stable
avant la fusion `dev-refact → dev-database`. L'audit porte donc sur l'état
actuel ; les points critiques ne proviennent pas du merge.

---

## 0. Synthèse exécutive

| Domaine | Verdict global | Dette |
|---|---|---|
| Pydantic v2 (usage) | Acceptable | faible |
| `ParamLevel` / profils user/dev/expert | Non-standard, justifié localement | moyenne |
| `HydroModPyConfig` (agrégateur) | À revoir | moyenne |
| `toml_loader` (base_config, repair) | Bricolage à contenir | moyenne |
| State (`WorkflowContext` + 3 scopes) | Acceptable mais anémique | moyenne |
| Units (5 modules maison) | Problématique (réinvention partielle de pint) | **forte** |
| Time (`ResolvedSimulationTimeWindow`) | Acceptable pour le cas d'usage | faible |
| Workspace | Conforme aux conventions (type cookiecutter light) | faible |
| Tools (log_manager, raster_io, geospatial, statistics, io_utils, filesystem, display, visualization, folder_root) | Mélange de code correct et de code mort / verbeux | **forte** |

**Top 5 dettes à résorber :**
1. `core/units/*` : 5 fichiers de conversion maison qui doublonnent partiellement pint (pint est déjà importé dans `length.py`). Fusionner derrière pint.
2. `core/tools/io_utils.py` et `core/tools/visualization.py` : 694 lignes orientées *examples* qui n'ont rien à faire dans un `core/` d'infrastructure.
3. `core/tools/folder_root.py` : code mort / legacy (variable d'env `HYDROMODPY_RESULTS`, appels `input()` bloquants, gros blocs commentés).
4. `core/config/toml_loader._repair_path_like_basic_strings` : parseur pseudo-TOML qui « répare » des échappements Windows. Contourne un vrai bug utilisateur plutôt que de l'exiger correct.
5. `core/state/data.py` : 17 champs `LoadResult | None` listés en dur — devrait être un `dict[str, LoadResult]` indexé par type.

---

## 1. Système Pydantic

### 1.1 Conformité à Pydantic v2

Les modèles lus (`WorkspaceConfig`, `HydroModPyConfig`, et indirectement les
sous-configs importées) utilisent les idiomes v2 **corrects** :

- `ConfigDict(...)` au lieu de la classe `Config` v1 (ex. `workspace/config.py:30`,
  `hydromodpy_config.py:73`). Conforme.
- `model_validator(mode="after")` (`workspace/config.py:56`). Conforme.
- `Annotated[T, ParamLevel(...), Field(...)]` pour exploiter la métadonnée. Conforme.
- `model_fields` (classe) et `model_dump(...)` (instance) sont utilisés dans
  `generate_toml.py` et `streamlit_config.py`. Conforme.
- `model_validate(...)` dans `streamlit_config.validate_section`. Conforme.

**Points à signaler :**

- `HydroModPyConfig.model_config = ConfigDict(arbitrary_types_allowed=True)` :
  potentiellement dangereux au niveau racine. Cela ouvre la porte à des champs
  non validés (objets arbitraires) dans l'agrégateur. Justifiable si un sous-
  modèle contient une `pd.Timestamp`, mais il faudrait **le localiser** sur ce
  sous-modèle plutôt que de l'ouvrir à la racine.
- `WorkspaceConfig.model_config = ConfigDict(extra="forbid")` : **bon choix**.
  Mais `HydroModPyConfig` n'a pas `extra="forbid"` — résultat : une faute de
  frappe de section (ex. `[workspc]`) passera silencieusement. **Incohérence**
  qu'il faut corriger (généraliser `extra="forbid"` à la racine).
- Les pré-conditions « section interdite » (`initializing`, `modflow`) sont
  gérées par des `ValueError` dans `from_toml()` (lignes 207-216), hors du
  modèle. **Acceptable** (erreurs actionnables), mais on pourrait le faire
  dans un `model_validator(mode="before")` pour rassembler toute la
  validation au même endroit.

### 1.2 Le pattern `ParamLevel` — verdict critique

```python
# core/config/param_level.py
@dataclass(frozen=True)
class ParamLevel:
    level: Literal["user", "dev", "expert"]

@dataclass(frozen=True)
class VisibleWhen:
    field: str
    values: str | tuple[str, ...]
```

**Description.** Métadonnée attachée via `Annotated[...]` qui pilote :
(a) la génération de templates TOML commentés filtrés par profil ; (b) la
visibilité de widgets dans l'UI Streamlit.

**Comparaison au standard.**

| Outil | Stratégie | Ce que fait HydroModPy |
|---|---|---|
| pydantic-settings | Variables d'env typées | Non utilisé |
| Hydra / OmegaConf | Groupes + overrides CLI | Non utilisé |
| Dynaconf | Profils d'environnement (dev/prod) | Similaire dans l'intention, pas la forme |
| FastAPI / typer | `Field(description=...)` + schéma JSON | Utilise `Field(description=...)` |
| Dataclasses + `Annotated` + métadonnée maison | — | **Exactement ce que fait HydroModPy** |

**Verdict : non-standard, mais justifié**. Le choix n'est ni Hydra, ni
Dynaconf, ni pydantic-settings — c'est une extension maison légère au-dessus
d'`Annotated`. **C'est acceptable** pour un projet scientifique qui doit :
(1) générer des templates TOML progressifs (user → expert) ; (2) piloter une
UI Streamlit auto-générée. Ni Hydra ni Dynaconf ne fournissent ce cas
d'usage sans écrire du code équivalent.

**Cependant**, le tandem `ParamLevel` + `VisibleWhen` a quelques faiblesses :

- `VisibleWhen.matches()` ne traite qu'une liste d'égalités. Pas d'opérateurs
  (`in`, `!=`, `>`, regex), donc dès qu'une règle devient complexe le code
  doit la coder en dehors. → Limitation connue, acceptable tant qu'on n'a
  pas besoin d'arithmétique.
- Profils définis comme un `dict[str, int]` ordonné (`PROFILES`) avec
  comparaison entière. Simple, mais ferait mieux avec une `IntEnum` typée.
- Aucun test ne vérifie que les `VisibleWhen("champ_inexistant", ...)` sont
  détectés. Si un refactor renomme un champ sibling, la règle devient
  silencieusement morte. **Recommandation :** ajouter un
  `model_validator(mode="after")` en classe de base qui valide la cohérence
  des `VisibleWhen` par introspection des `model_fields`.

**Sur-ingénierie ?** Non, tant que Streamlit et le générateur TOML sont
réellement utilisés. **Si** l'un des deux disparaît, `VisibleWhen` doit
disparaître avec.

### 1.3 `generate_toml.py` — qualité d'implémentation

745 lignes de génération TOML depuis les `model_fields`. Très orienté
détail :

| Aspect | Verdict | Commentaire |
|---|---|---|
| Lazy-loading du registry | Conforme | Évite cycles d'imports. |
| Couverture type-hints | Correct | `list[BaseModel]` → array-of-tables, `Optional[M]` → section commentée, `Literal[...]` → contraintes. |
| `_placeholder(field_info)` | Acceptable | Respecte `Gt`/`Ge`. Bien. |
| `toml_flatten` (ClassVar) | Non-standard | Convention maison `ClassVar` non typée pour aplatir une section. Fragile (pas de Protocol, pas de base class). |
| Duplication `_is_union_origin`, `_unwrap_optional`, `_resolve_basemodel` | **Dupliquée** entre `generate_toml.py` et `streamlit_config.py` | Factoriser dans un module `core/config/pydantic_introspect.py`. |
| Formatage TOML | Maison | `_fmt()` implémente un mini-serializer. Pourquoi pas `tomli_w` ? (tomli_w ou tomlkit produiraient des TOML syntaxiquement corrects garantis). |

**Recommandation :** isoler les helpers d'introspection Pydantic dans un
seul module, puis envisager `tomli-w` pour la serialization (bien qu'il ne
produise pas de commentaires — limite connue).

### 1.4 Code dupliqué / redondant

- `_is_union_origin` apparaît dans `generate_toml.py:335` **et**
  `streamlit_config.py:57`. Fonctions identiques au mot près.
- `_resolve_basemodel_type` (`generate_toml.py:449`) et `_resolve_basemodel`
  (`streamlit_config.py:91`) : la même logique, noms différents.
- `_resolve_list_basemodel_type` / `_resolve_list_basemodel` : idem.

**Verdict : duplication problématique.** ~80 lignes à factoriser.

### 1.5 `__main__.py` et CLI

Non lu ici, mais signalé : `core/config/__main__.py` (16 lignes) permet
probablement `python -m hydromodpy.core.config`. À vérifier que ça ne
doublonne pas la commande `hmp config`.

---

## 2. `HydroModPyConfig` — agrégateur

### 2.1 Architecture générale

Le modèle agrège 16 sous-configs :
`workspace`, `geographic`, `domain`, `data`, `flow`, `transport`,
`simulation`, `solver`, `modflownwt`, `modflow6`, `display`, `postprocess`,
`capability_gallery`, `overview` (optionnel), `mesh_catchment` (optionnel).

**Verdict : à revoir.**

**Points positifs :**

- Chaque sous-config est `default_factory=<Config>()`, donc `HydroModPyConfig()`
  sans argument donne un squelette valide (sauf `workspace` et `geographic`
  qui sont requis). Bon pour les tests.
- `from_snapshot(snapshot, **overrides)` permet de reconstruire la config
  depuis JSON stocké en DuckDB avec merge récursif. **Pattern utile** pour
  la reproductibilité scientifique.
- `from_toml(toml_path)` centralise la résolution de chemins (absolus,
  relatifs, `~`) et dérive `workspace.project_root` depuis la localisation
  du TOML (bonne convention).

**Points critiques :**

- **16 sections top-level : trop plat.** Hydra/OmegaConf regrouperaient
  `modflownwt` + `modflow6` sous `solvers.<backend>`, et `overview` +
  `mesh_catchment` + `simulation` sous `workflow.<type>`. Ici tout est au
  même niveau, ce qui complique l'évolution (ajouter un 4e solveur = nouvelle
  section racine).
- **Transformations cachées dans `from_toml()`** :
  - `"initializing"` → rejeté (ligne 207). Migration visible mais non testée
    dans les regressions vues.
  - `"modflow"` → rejeté.
  - `workspace.project_root` auto-dérivé de la localisation du TOML.
  - DEM placeholder `"__DEM_API_BOOTSTRAP__"` injecté quand `[overview]`
    est seul (ligne 234-241). **Très discutable** : utiliser une sentinelle
    magique comme valeur de champ `Path` casse la sémantique du type.
    Préférer un champ booléen `dem_bootstrap: bool = False` plus un
    `Optional[Path]`.
- `run_id` dérivé du nom de fichier TOML *après* validation Pydantic
  (ligne 288-289). Mutation post-création d'un modèle déclaré « frozen »
  *par convention* mais pas en Pydantic. **Pattern fragile**, à déplacer
  dans `from_toml()` avant l'instantiation : construire le dict, puis
  `cls(**dict)`.
- Aucune vérification de **cohérence inter-sections** : par exemple que
  `solver.engine` est effectivement configuré dans `[modflownwt]` ou
  `[modflow6]`. Les erreurs ne remontent qu'au runtime.

### 2.2 Mapping TOML ↔ Pydantic — transformations

**Verdict : pas du 1:1 strict.**

Transformations appliquées entre TOML brut et modèles Pydantic (dans
`toml_loader.py` et `hydromodpy_config.py`) :

| Transformation | Fichier:ligne | Verdict |
|---|---|---|
| `base_config = "…"` → merge hiérarchique récursif | `toml_loader.py:131` | Utile (DRY sur TOML), non-standard. |
| Valeurs `""` → supprimées → `None` par défaut | `toml_loader.py:104` | **Contournement** du manque de `null` en TOML. Acceptable, mais piège subtil (une clé `label = ""` devient `None`). |
| Chemins Windows cassés → échappement auto des `\` | `toml_loader.py:41` | **Bricolage**. Le TOML de spec interdit les single-backslash dans les basic strings — la vraie solution est `'C:\path'` (littéral) ou `"C:\\path"`. Ce « repair » masque des bugs utilisateur. |
| Résolution `~` et chemins relatifs | `path_resolution.py:15` | Conforme. |
| Auto-dérivation de `workspace.project_root` | `hydromodpy_config.py:220` | Conforme. |
| DEM `__DEM_API_BOOTSTRAP__` sentinel | `hydromodpy_config.py:234` | **Problématique**. |
| `run_id` dérivé du nom du TOML si vide | `hydromodpy_config.py:52` | Acceptable. |
| `initializing` / `modflow` → erreur | `hydromodpy_config.py:207` | Bon (migration explicite). |
| `data` et `flow` utilisent un loader dédié (`from_toml_section`) | `hydromodpy_config.py:372, 377` | Pattern hybride. La cohérence demanderait soit tous les modèles via `from_toml_section`, soit aucun. |

### 2.3 Defaults — sensibilité physique

Non évaluable ici sans descendre dans chaque sous-config (hors périmètre
`core/`). Mais un signal d'alarme de la part de `_placeholder()` dans
`generate_toml.py:344-420` : quand le défaut est `None`, le générateur
invente un placeholder (`0`, `0.0`, `""`, ou la première option d'un
`Literal`). **Risque** : un utilisateur copie-colle un TOML généré et ne
touche pas ce `0.0` silencieux. Le contrat actuel est un champ `user`
`REQUIRED` est émis *non commenté* avec un placeholder — il faudrait au
moins un marqueur visuel (`<<CHANGE_ME>>` ou `0.0  # TODO`).

---

## 3. State management — `WorkflowContext` et scopes

### 3.1 Description

```python
@dataclass
class WorkflowContext:
    cfg: HydroModPyConfig
    config_path: Path
    raw_toml: dict[str, Any]
    data_plan: DataLoadPlan | None = None
    setup: SetupContext = field(default_factory=SetupContext)
    loaded_data: LoadedDataContext = field(default_factory=LoadedDataContext)
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)
    store: Any = field(default=None, repr=False)
    sim_id: str | None = None
    parent_sim_id: str | None = None
    postprocess_runner: Any = field(default=None, repr=False)
```

### 3.2 Verdict : acceptable mais anémique

**Comparaison aux références :**

| Pattern | Comparaison avec HydroModPy |
|---|---|
| scikit-learn `Pipeline` | Pas comparable — sklearn n'a pas de contexte partagé. |
| Prefect / Dagster `Context` | Plus riche : loggers, retries, metadata. Ici uniquement conteneur de données. |
| Xarray / FloPy `ModelInterface` | Plus orienté domaine — HydroModPy agrège plusieurs modèles. |
| Airflow `TaskInstanceContext` | Similaire en intention — conteneur plat pour les étapes. |

**Ce qui est bien fait :**
- La séparation `setup` (structural) / `loaded_data` (externes) / `execution`
  (outputs) est **une bonne idée** — lisible, chaque étape sait dans quel
  scope écrire. C'est mieux qu'un seul dataclass à 30 champs.
- Les types forward-référencés (`TYPE_CHECKING`) évitent les cycles d'imports.
  Conforme.
- `WorkflowContext.get_model(run_id)` / `get_run_for_solver(solver_name)` /
  `get_model_for_solver(solver_name)` : trois helpers qui **évitent**
  d'inlinent le dict `execution.models_by_run_id` partout. Bon.

**Ce qui est problématique :**

1. **God Object masqué.** `SetupContext` a 13 champs, `LoadedDataContext`
   a 17 champs (tous `None` par défaut). Ajouter un nouveau type de
   données = ajouter une ligne ici + toutes les étapes qui la lisent.
   C'est un *registre*, pas un contexte typé. **Recommandation :**
   remplacer `LoadedDataContext` par un `dict[str, LoadResult]` indexé
   par le nom du variable-manager. On perd l'auto-complétion, on gagne
   en extensibilité. `SetupContext` fait la même chose à plus petite
   échelle.

2. **`store: Any`, `postprocess_runner: Any`.** Typage dégénéré.
   `WorkflowContext` dépend du simulation-catalog, et pourtant ces champs
   sont typés `Any`. Un `TYPE_CHECKING` import suffirait pour les rendre
   `SimulationZarr | None` et `PostprocessRunner | None`.

3. **Le code lifecycle (`store`, `sim_id`, `parent_sim_id`,
   `postprocess_runner`) est hors des 3 scopes.** Le docstring dit
   « result-store lifecycle formerly in WorkflowContext only » — on sent
   un refactor inachevé. À déplacer dans un 4e scope `RunLifecycleContext`
   ou à fusionner dans `execution`.

4. **Mutabilité totale.** Aucun champ n'est `frozen=True` dans les trois
   scopes. Ça complique le raisonnement sur les étapes parallèles. En
   Prefect / Dagster, les contextes sont conçus pour être *threadsafe*.
   Ici, on doit le vérifier à chaque étape.

### 3.3 `ExecutionRegistry` — structure

`process_runs_by_id: dict[str, ProcessRun]` + `models_by_run_id: dict[str, Any]`.
La liaison est **implicite** (les clés doivent correspondre). Un
`dict[str, tuple[ProcessRun, Any]]` serait plus sûr. Mais vu la taille
(18 lignes), le risque est contenu.

---

## 4. Système d'unités

### 4.1 Inventaire

| Fichier | Lignes | Domaine SI | Nb unités supportées |
|---|---|---|---|
| `units/scalar.py` | 80 | parse `"12.3 m"` | — |
| `units/length.py` | 282 | longueurs (m, km, cm, mm) | 20 aliases |
| `units/time.py` | 176 | temps (s, min, h, d, y) | 24 aliases + ITMUNI |
| `units/hydraulic_conductivity.py` | 200 | K (m/s) | 9 formes × ~7 alias |
| `units/hydraulic_conductance.py` | 121 | T (m²/s) | 9 formes × ~5 alias |
| `units/volumetric_flow.py` | 117 | Q (m³/s) | 8 formes × ~3 alias |
| `units/radiation.py` | 109 | W/m² | 6 formes × ~8 alias |

**Total : ~1 085 lignes de conversion maison.**

### 4.2 Verdict : problématique — réinvention partielle de pint

**Élément fondamental qui fait mal :** `length.py` **importe déjà pint** :

```python
# core/units/length.py:13
try:
    from pint import UnitRegistry
except Exception:
    UnitRegistry = None
```

Mais :
- Seul `parse_length_to_m` l'utilise (fallback maison sinon).
- Les 6 autres modules (`time`, `hydraulic_conductivity`, `hydraulic_conductance`,
  `volumetric_flow`, `radiation`, `scalar`) **n'utilisent pas pint**.
- Chaque module réimplémente :
  - Un dict `_<DOMAIN>_UNIT_ALIASES` (mapping des variantes).
  - Un dict `_<DOMAIN>_FACTORS` (facteur vers SI).
  - `normalize_<domain>_unit()`.
  - `factor_to_<domain>()`.
  - `convert_to_<domain>()`.
  - `parse_to_<domain>()` (qui réutilise `parse_scalar_and_unit` — bon).
  - Pour 2 modules, une variante `convert_payload_to_<domain>` qui traite
    récursivement `dict | list | tuple | np.ndarray` (pattern dupliqué
    entre `length.py:124` et `hydraulic_conductivity.py:134`).

**Comparaison aux standards :**

| Bibliothèque | Approche | Ce qu'elle fournit gratuitement |
|---|---|---|
| [pint](https://pint.readthedocs.io) | UnitRegistry + `Quantity` | Tout l'inventaire, dimensional checking, propagation. |
| [unyt](https://unyt.readthedocs.io) | `unyt_quantity` arrays | Numpy-friendly, rapide. |
| [cf-units](https://cf-units.readthedocs.io) | UDUNITS2 (standard NOAA) | **Standard métier** hydro/climat. |
| [pydantic + pint](https://pint.readthedocs.io/en/stable/advanced/pint-pydantic.html) | Types `Quantity[m/s]` | Validation **à la construction**. |

**Ce que le code fait bien :**
- SI comme base canonique pour chaque domaine. Conforme.
- Factorisation commune via `parse_scalar_and_unit` (`scalar.py`). Bon.
- Conversion ITMUNI MODFLOW ↔ unité humaine (`time.py:73`). Utile pour
  l'interop FloPy.

**Ce qui est problématique :**

1. **Pas de *dimensional analysis***. Si un utilisateur écrit dans son TOML
   `K = "10 m/day"` pour un champ typé « length », le code va tenter de le
   parser comme longueur, échouer sur `normalize_length_unit`, et renvoyer
   une `ValueError`. Bien. Mais si l'erreur vient de l'appel Python où
   une valeur en `m/day` est passée à `convert_to_m` au lieu de
   `convert_to_m_per_s`, **aucune protection** : la conversion appliquera
   un facteur de 1.0 à la valeur numérique, et la simulation avancera avec
   la mauvaise physique. **C'est le risque d'erreur silencieuse principal**
   que pint aurait détecté.

2. **Années = 365.25 jours.** `time.py:61` utilise une année sidérale. Pour
   des simulations hydro pluriannuelles avec `[simulation.time]` en pas
   mensuels / annuels, c'est **conventionnel** mais incohérent avec pandas
   (qui utilise `DateOffset(years=1)` = calendar-aware, donc 365 ou 366
   jours selon bissextile). **Risque** : si un utilisateur dit
   `step_unit = "year"`, `_time_step_offset()` utilise `pd.DateOffset` (bien),
   mais `timedelta_to_seconds()` d'un tel delta dépendra de l'année. Le
   code gère ce cas dans `time/window.py:278-291` (`_period_lengths_in_seconds_from_boundaries`)
   qui calcule les deltas réels — donc **OK en pratique**, mais le
   `_SECONDS_PER_UNIT["years"] = 365.25 * 86400` est un piège pour
   quiconque le lit directement.

3. **Duplication massive.** Chaque module pèse ~100-300 lignes de
   boilerplate quasi-identique. Un `@dataclass` générique
   `UnitDomain(canonical: str, aliases: dict, factors: dict)` + un helper
   `build_conversion_functions(domain: UnitDomain)` réduirait le code par
   un facteur ~5.

4. **Couverture incomplète.** Pas de surfaces (m², km², ha), pas de
   volumes (m³, L, Mm³), pas de densité (kg/m³), pas de recharge
   (mm/jour — variable clé hydro). L'inventaire actuel est ad hoc.

5. **`convert_payload_to_m_per_s` gère numpy via `hasattr(value, "astype")`
   mais aussi `hasattr(value, "copy") and hasattr(value, "__mul__")`**
   (`hydraulic_conductivity.py:166-175`) : duck-typing fragile. pint
   supporte nativement les arrays.

**Recommandation claire :**

- **Phase 1 (court terme) :** migrer `hydraulic_conductivity`, `hydraulic_conductance`,
  `volumetric_flow` et `radiation` sur pint. `length.py` l'utilise déjà
  partiellement. `time.py` et `scalar.py` peuvent être conservés tels
  quels (interop MODFLOW ITMUNI).
- **Phase 2 :** introduire `Quantity[m/s]` via
  [pydantic-pint](https://pydantic-pint.readthedocs.io/) sur les champs
  typés `K_value`, `transmissivity`, etc. — validation dimensionnelle à
  la construction du modèle. C'est un vrai gain de sûreté.
- **Phase 3 :** envisager `cf-units` pour les exports NetCDF (standard
  CF-conventions attendu par xarray + CDO). HydroModPy génère déjà du
  NetCDF et le tag `"Meter"` dans `raster_io.py:308` — cf-units aiderait.

---

## 5. Workspace

### 5.1 Structure

```
workspace_root/
  hydromodpy.duckdb
  data/
    cache.duckdb
  projects/
    <project>/            <- project_root
      config.toml
      simulations/<uuid>.zarr/
```

### 5.2 Verdict : conforme, proche de cookiecutter-data-science

**Comparaison :**

| Convention | HydroModPy | Standard |
|---|---|---|
| cookiecutter-data-science | `data/`, `models/`, `reports/`, `notebooks/` | Proche : `data/`, `simulations/` (= `models/`), `configs/`, `figures/`. |
| DVC | `.dvc/`, `dvc.yaml` | Non : HydroModPy met tout dans DuckDB + Zarr. |
| MLflow | `mlruns/<exp>/<run>/` | HydroModPy fait `simulations/<uuid>.zarr/` avec metadata en DuckDB. Choix différent mais défendable. |
| Kedro | `conf/`, `data/01_raw/`, etc. | HydroModPy a `data/` et `configs/` mais pas le versioning raw/intermediate/primary. |

**Ce qui est bien :**
- Auto-discovery du `workspace_root` par walk-up (`workspace/config.py:64`).
  Pattern classique (git, pyproject.toml). Bon.
- `output_root` séparable de `project_root` — permet de rediriger les gros
  outputs (Zarr) vers un autre disque. **Très bon** pour les vrais
  workflows scientifiques où `/home` est petit et `/scratch` est large.
- `_effective_output_root` property bien factorisée.
- `.solver_scratch/_preprocessing/` est un « staging » explicite. Nom
  peut-être trop MODFLOW-centric (`_preprocessing` serait plus neutre).

**Ce qui est discutable :**
- `discover_workspace_root` cherche `catalog.duckdb` **ou** `catalog.db`
  **ou** un dossier `data/` (`workspace/config.py:76`). Le premier nom
  (`catalog.duckdb`) ne correspond pas à celui réellement utilisé
  (`hydromodpy.duckdb` dans la racine). **Bug silencieux** : la détection
  d'un workspace ne s'appuiera que sur `data/`, jamais sur `hydromodpy.duckdb`.
  → À aligner.
- `LEGACY_STABLE_DIR = ".solver_scratch/_preprocessing"` (constante
  globale) : nom « LEGACY » mais c'est le *chemin courant*. Confusing.
- `WorkspacePathRegistry` est `frozen=True` mais stocke un `Path`
  mutable — OK en pratique car Path n'expose pas de muter. Bon.
- `_resolve_bin_path()` (`workspace.py:25`) scanne `<repo>/bin` et
  `<repo>/hydromodpy/bin`. Fait des assomptions sur le layout post-install
  via pip (qui casse `parents[3]`). Jamais utilisé (il faut vérifier si
  `self.bin_path` est lu ailleurs). **Suspect de code mort.**

### 5.3 `catch_name` — naming

Le property `catch_name` vient de `project_root.name`. Relique sémantique
« catchment » dans une classe généraliste. À renommer `project_name` ou
garder un alias si trop invasif.

---

## 6. Time management

### 6.1 Gestion des fuseaux horaires

**Verdict : naïf (timezone-agnostique).**

- `pd.Timestamp(value)` est utilisé sans imposer de tz (`window.py:117`).
- Les strings TOML sont interprétés en local time implicite.
- Aucun test ne couvre les transitions DST.

**Comparaison :**
- pandas `DatetimeIndex` supporte `tz`. HydroModPy n'en tire pas parti.
- xarray `CFTimeIndex` supporte les calendriers non-grégoriens (360-day,
  noleap) — crucial pour les couplages climat. HydroModPy n'en a pas
  besoin *si* les données forcées sont déjà en temps standard.

**Ce qui est géré :**

| Cas | Statut |
|---|---|
| Années bissextiles | Indirectement OK (via `pd.DateOffset`). |
| Pas de temps irréguliers | **Non** — `_build_time_boundaries` rejette les windows non-alignés. |
| Mois de durée variable | OK (via `DateOffset(months=…)`). |
| Timezone | **Non géré** — pas de `tz`. |
| Calendriers non-grégoriens | **Non géré** — pas de CFTime. |
| DST / transitions d'heure | **Non géré**. |

**Recommandation :**
- Pour un outil groundwater local (ex. bassin versant en France), la
  tz-agnostic approche est **acceptable** : les données SIM2, BD-HUBEAU
  sont en temps local français. Documenter explicitement.
- Pour éviter les pièges futurs, typer les timestamps comme
  `pd.Timestamp` *et* imposer `tz=None` explicitement dans `_as_timestamp`
  (pour rejeter un input tz-aware — sinon arithmetique mixte qui échoue).

### 6.2 `ResolvedSimulationTimeWindow` — qualité du design

**Verdict : bon.**

- Frozen dataclass (**immutable**, cohérent avec l'intention
  « canonical »).
- Séparation inclusive (user-facing) / exclusive (compute) clairement
  documentée (lignes 8-14).
- Période = `(step_value, step_unit)` + calendriers pandas — cohérent.
- `simulation_time_pandas_frequency(window, anchor="start|end")` — bon
  helper avec option.

**Ce qui cloche :**

- `_build_time_boundaries` : **boucle Python** sur l'avancée (ligne 263).
  Pour 30 000 pas de 1 jour (30 000 / 365 ≈ 82 ans), ça passe. Au-delà,
  vectoriser avec `pd.date_range(start, end, freq=…)` serait ~100× plus
  rapide. Non-critique pour le cas d'usage, mais à signaler.
- `_inclusive_end_to_exclusive_end` : le choix « +1 jour pour tout unit
  >= jour » est arbitraire. Pour un user qui met `step_unit = "hour"` et
  `end = "2024-01-01 12:00:00"`, le code fait `+1h`. Pour un user en
  monthly step et `end = "2024-12-31"`, il fait `+1d`. **OK en semantics**
  mais pas obvious — meilleur commentaire requis.
- `resolve_simulation_time_grid(cfg)` prend `cfg: Any` (duck-typing). Alors
  que `cfg` est très probablement un `HydroModPyConfig`. Typer correctement
  (import conditionnel `TYPE_CHECKING`) améliorerait l'IDE.

### 6.3 `validate_recharge_coverage` — hors périmètre ?

Cette fonction (ligne 525-626, ~100 lignes) vérifie que les séries de
recharge couvrent la fenêtre. **Elle n'a rien à faire dans
`core/time/window.py`** : c'est une validation *data* qui dépend d'une
`pd.Series` de recharge. À déplacer dans `data/variables/recharge/` ou
dans un `data/contracts/coverage.py`.

---

## 7. Tools — audit détaillé

### 7.1 `log_manager.py` — verdict : correct mais réinventé

**Description.** Classe `LogManager` singleton avec 3 modes console
(dev/verbose/quiet), un log utilisateur optionnel, et un log de simulation
dans le dossier de watershed.

**Verdict : acceptable, légèrement sur-ingénieré.**

**Comparaison au standard :**
- Le module stdlib `logging` seul (+ un `dictConfig`) suffirait.
- [structlog](https://www.structlog.org) aurait apporté le JSON et le
  contexte.
- [loguru](https://loguru.readthedocs.io) aurait remplacé les 294 lignes
  par ~20.

**Ce qui est bien :**
- Utilise `logging.getLogger("hydromodpy")` comme racine. Conforme PEP 282.
- `_suppress_library_logs` à `CRITICAL` pour fiona/rasterio/matplotlib/…
  est **exactement la bonne chose à faire** pour un outil scientifique
  (ces libs sont bavardes).

**Ce qui est problématique :**
- **Singleton (`_instance`)** : anti-pattern en Python (on peut simplement
  `getLogger("hydromodpy")`). La classe introduit un état global
  implicite qui complique les tests. `pytest --forked` et workers
  `xdist` auront des surprises.
- `setup_simulation_log(watershed_folder)` est un wrapper de 12 lignes
  autour de `LogManager._instance.set_simulation_log(...)` — si l'instance
  est None (tests unitaires), ça ne fait rien silencieusement. **Piège**.
- Le fallback `candidate_paths` pour le FileHandler (lignes 170-179) est
  fragile (permissions, concurrence). Un `tempfile`/UUID serait plus sûr.
- Mode `"dev"` vs `"verbose"` vs `"quiet"` : 3 modes pour DEBUG/INFO/WARN
  — logging propose déjà ces 5 niveaux. Couche d'abstraction inutile.

### 7.2 `raster_io.py` — verdict : à revoir, pas rioxarray natif

**Description.** 403 lignes qui orchestrent `rasterio`, `geopandas`,
`pyproj`, `xarray`, `rasterio.features`, `rasterio.warp` pour :
`clip_tif`, `load_to_numpy`, `load_to_xarray`, `export_tif`,
`reproject_tif`.

**Verdict : à revoir.**

**Pourquoi pas rioxarray directement ?**
- rioxarray unifie déjà rasterio + xarray (`.rio.reproject()`,
  `.rio.clip()`). La classe expose un API que `load_to_xarray` bricole
  à la main (lignes 264-299, `ds = ds.rio.reproject(...)` + détection CRS
  invalide).
- **Dette :** `load_to_numpy` fait le même travail avec un flux différent
  (ligne 56-169). Il existe deux chemins : numpy ou xarray, et les bugs
  divergent.
- La détection « CRS invalide » via patterns string
  (`"EngineeringCRS"`, `'UNIT["unknown"'`, ...) est un **hack**
  (ligne 252-261). pyproj fournit `crs.is_derived` / `crs.to_epsg()` pour
  détecter ça proprement.

**Ce qui est bien :**
- La fonction `reproject_tif` utilise `query_utm_crs_info` de pyproj
  pour trouver la zone UTM locale à partir d'un centroïde WGS-84. **Bon
  pattern** (mieux que hardcoder un EPSG).
- `mask_by_dem` vectorise via `np.ma.masked_*`. Bon.

**Ce qui est problématique :**
- Le décodage NetCDF manuel des dates (lignes 217-239) : parse
  `units = "days since YYYY-MM-DD"` avec une regex et des
  `strptime`. **C'est exactement ce que fait `xarray.decode_cf()`** via
  cftime. Ce code réinvente (mal) le décodage CF. Si le NetCDF vient de
  SIM2 / SAFRAN, `decode_cf=True` (défaut xarray) fonctionnerait.
- `load_to_numpy` attrape `Exception` et renvoie `None` (ligne 92-95,
  135-139, etc.) — *silent failure*. Aucune trace pour l'utilisateur.
  Catastrophique pour du debug.

### 7.3 `io_utils.py` — verdict : hors périmètre core/

**Description.** 379 lignes de helpers orientés **examples / notebooks** :
`setup_paths`, `load_raster`, `load_vector`, `load_csv`,
`load_simulation_results`, `make_timeseries_data`, `save_results`,
`extract_watershed`.

**Verdict : ne devrait pas être dans `core/`.**

**Raisons :**
- `setup_paths` cherche `examples_legacy/<example_name>` — **hardcode un
  layout d'examples** qui n'existe plus ou qui est spécifique à
  certaines démos. Le path `examples_legacy/` n'est pas mentionné dans
  `CLAUDE.md` et suggère du code mort.
- `load_simulation_results` assume une structure `<model>/_postprocess/_rasters/watertable_elevation_t(0).tif` —
  c'est l'ancien layout pré-Simulation-Catalog. **Ancien format, post-merge
  l'output est Zarr**.
- `extract_watershed` délègue à `hydromodpy.watershed.Watershed` avec un
  *deprecated shim*. Le module `watershed/` est marqué legacy par
  `CLAUDE.md`. Cette fonction est donc un wrapper legacy → legacy.
- `save_results(format=...)` avec 3 branches `if/elif` → signe de
  sur-généralisation. Préférer 3 helpers nommés.

**Recommandation :** déplacer ce module en `examples/shared/io_utils.py`
ou le supprimer purement si les examples ont migré vers le nouveau layout.

### 7.4 `visualization.py` — verdict : hors périmètre core/

**Description.** 315 lignes de matplotlib dédié à des plots d'example :
`create_watershed_plot`, `create_map_plot`, `create_crosssection_plot`,
`create_timeseries_plot`.

**Verdict : hors périmètre core/**, à déplacer.

**Raisons :**
- `core/tools/` est supposé être de l'infrastructure. Ces fonctions font
  des choix éditoriaux (cmap `jet`, fond bleu ciel, `2017-01`… `2018-01`
  en dur ligne 295) qui sont des *exemples*.
- Aucun autre module de `core/` n'importe ce fichier (à vérifier au runtime :
  `grep` sur le code montrera que seuls les notebooks / examples
  l'utilisent).
- Duplication potentielle avec `analysis/display/figures/*.py`.

### 7.5 `statistics.py` — verdict : correct mais nommage à revoir

**Description.** ~100 lignes : `rmse_manual`, `nse_manual`,
`mare_manual`, `kge_manual`, `efficiency_criteria`, `date_range`,
`select_period`, `hydrological_mean`.

**Verdict : correct, suffixe `_manual` problématique.**

- Suffixe `_manual` suggère que des versions non-manuelles existent. Rien
  de tel dans le code. **Mauvais nommage**. À renommer `rmse`, `nse`,
  `kge` (et gérer les collisions avec le scope d'import).
- `hydrological_mean` est obscur — un doc plus précis serait bienvenu
  (définition hydrologique : moyenne sur l'année hydrologique ?). L'algo
  actuel (lignes 86-100) calcule l'indice du « dernier jour le plus proche
  du premier » — logique complexe pour un docstring d'une ligne.
- Formules NSE/KGE correctes. Bon.
- `efficiency_criteria` retourne un tuple `(rmse, nrmse, nse, nselog, bal, mare, kge)`
  **sans noms**. Préférer un `NamedTuple` ou un dataclass.

### 7.6 `filesystem.py` — verdict : correct et minimaliste

36 lignes, 3 fonctions : `create_folder`, `load_csv`, `load_shapefile`.
Chacune attrape `Exception` et renvoie un empty-dataframe / `None` en
log.

**Problématique :** « silent-fail fallback » (renvoyer `pd.DataFrame()`
vide quand le CSV est illisible) masque des bugs. Préférer laisser
l'exception remonter.

Par ailleurs `load_csv` existe *aussi* dans `io_utils.py` (ligne 144).
**Duplication directe.** À fusionner.

### 7.7 `geospatial.py` — verdict : correct mais tiroir à utilitaires

152 lignes, 8 fonctions hétérogènes :
- `basin_area` : compte de cellules masquées → aire. OK.
- `reproject_coord`, `reproject_shp` : conversions CRS. OK.
- `get_centroid_coordinates` : fige `EPSG:2056` (Suisse MN95) en
  intermédiaire. **Valeur hardcodée** — si le point est hors Europe, c'est
  faux. Préférer `gdf.to_crs(gdf.estimate_utm_crs())`.
- `transform_coordinates` : **boucle Python sur tous les pixels** d'un DEM
  (ligne 87-92). Pour un DEM 1000×1000, c'est ~1M d'appels
  `Transformer.transform`. À vectoriser (transform sur array numpy
  directement via `transformer.transform(x_arr, y_arr)`). Gain ~100×.
- `select_within_polygon_points` : idem, `for i in range(...)` sur une
  grille 2-D (ligne 134-137). À remplacer par `shapely.vectorized.contains`
  ou `rioxarray.rio.clip`.
- `convert_units(df, var_key)` : hardcode 3 conversions
  (precipitation ×1000, temp -273.15, radiation ×1e-6). **Exactement ce
  que ferait pint ou cf-units** — et en plus *sans* connaissance des
  unités source/cible. À supprimer une fois le système d'unités unifié.

### 7.8 `display.py` — verdict : correct (matplotlib styling)

85 lignes, 2 fonctions : `plot_params` et `print_hydromodpy` (ASCII
banner).

- Style matplotlib cohérent. Bon.
- `_banner_printed` singleton flag pour éviter la répétition. Acceptable.
- `plot_params(small, interm, medium, large)` : 4 paramètres positionnels
  dont `interm` mal nommé — préférer `small, intermediate, medium, large`
  ou des kwargs explicites.

### 7.9 `folder_root.py` — verdict : **code mort / legacy**

149 lignes dont :
- ~50 lignes commentées (lignes 98-148).
- `root_folder_results()` utilise `input()` bloquant (ligne 60) → cassera
  n'importe quelle exécution non-interactive (CI).
- `os.system("setx ...")` ou `os.system("export ...")` (lignes 67, 70) —
  l'`export` ne persiste pas dans la session utilisateur (c'est un
  sous-shell). Le `setx` Windows persiste mais ne reflète pas dans la
  session en cours. **Commentaire ligne 34 avoue le bug.**
- Variable d'env `HYDROMODPY_RESULTS` : **n'apparaît pas** dans `CLAUDE.md`
  qui documente `HYDROMODPY_*`. Probablement plus utilisée.

**Recommandation : supprimer ce fichier.** Ou au pire, le déplacer sous
`legacy/` avec un `DeprecationWarning`.

---

## 8. Tableau récapitulatif des modèles Pydantic

| Nom | Fichier | Champs principaux | Config | Verdict |
|---|---|---|---|---|
| `HydroModPyConfig` | `config/hydromodpy_config.py` | 16 sections (workspace, geographic, domain, data, flow, transport, simulation, solver, modflownwt, modflow6, display, postprocess, capability_gallery, overview, mesh_catchment) | `arbitrary_types_allowed=True`, **pas** d'`extra="forbid"` | **À revoir** — trop plat, `extra` ouvert, mutations post-validation (`run_id`). |
| `WorkspaceConfig` | `workspace/config.py` | `project_root`, `output_root`, `workspace_root` | `extra="forbid"`, `model_validator(mode="after")` pour discovery | Bien fait. |
| `ParamLevel` | `config/param_level.py` | `level: Literal["user","dev","expert"]` | `@dataclass(frozen=True)` (pas Pydantic) | Non-standard mais justifié. |
| `VisibleWhen` | `config/param_level.py` | `field`, `values` | `@dataclass(frozen=True)` | Acceptable. Validation incomplète. |
| `ResolvedSimulationTimeWindow` | `time/window.py` | `start`, `end`, `step_value`, `step_unit`, `coverage_policy` | `@dataclass(frozen=True)` (pas Pydantic) | Bien fait. |
| `ResolvedSimulationTimeGrid` | `time/window.py` | `window`, `boundaries`, `period_lengths_seconds`, `nstp_per_period` | `@dataclass(frozen=True)` | Bien fait. |
| `ResolvedSteadySimulationTimeGrid` | `time/window.py` | `period_lengths_seconds`, `boundaries`, `window=None` | `@dataclass(frozen=True)` | **À revoir** — sentinelle `window=None` via annotation `None`. Deux classes + union type auraient été plus propres. |
| `SetupContext` | `state/setup.py` | 13 champs `Any`/`None` (workspace, geographic, domain, flow, transport, 4 mesh, run_id, time_grid) | `@dataclass` (mutable) | **À revoir** — anémique, `run_id` est une string par défaut `"default"` (magic). |
| `LoadedDataContext` | `state/data.py` | **17 champs optionnels** typés `LoadResult | None` | `@dataclass` | **À revoir** — dict-indexed préférable. |
| `ExecutionRegistry` | `state/execution.py` | `simulation_plan`, `process_runs_by_id`, `models_by_run_id` | `@dataclass` avec `field(default_factory=dict)` | Acceptable. |
| `WorkflowContext` | `state/run_state.py` | 3 scopes + 4 lifecycle fields | `@dataclass` | Acceptable mais lifecycle devrait être dans un scope. |
| `WorkspacePathRegistry` | `workspace/path_registry.py` | `project_root`, `output_root`, `workspace_root` | `@dataclass(frozen=True)` | Bien fait. |

---

## 9. Dette de code concrète à résoudre

### 9.1 Duplications

| Fichier:ligne | Duplication avec | Action |
|---|---|---|
| `generate_toml.py:335` `_is_union_origin` | `streamlit_config.py:57` | Factoriser. |
| `generate_toml.py:449` `_resolve_basemodel_type` | `streamlit_config.py:91` `_resolve_basemodel` | Factoriser. |
| `generate_toml.py:423` `_resolve_list_basemodel_type` | `streamlit_config.py:108` `_resolve_list_basemodel` | Factoriser. |
| `length.py:124-166` `convert_payload_to_m` | `hydraulic_conductivity.py:134-176` `convert_payload_to_m_per_s` | Factoriser. |
| 5× `units/*.py` normalise/factor/convert/parse | — | Factoriser via un `UnitDomain` générique. |
| `filesystem.py:20` `load_csv` | `io_utils.py:144` `load_csv` | Supprimer l'un ou l'autre. |
| `filesystem.py:29` `load_shapefile` | `io_utils.py:121` `load_vector` | Idem (noms différents, même fonction). |

### 9.2 Code mort / legacy

| Fichier | Raison | Action |
|---|---|---|
| `core/tools/folder_root.py` | `input()` bloquant, `HYDROMODPY_RESULTS` non-documenté | **Supprimer**. |
| `core/tools/io_utils.setup_paths` (lignes 28-69) | `examples_legacy/` hardcodé | Déplacer ou supprimer. |
| `core/tools/io_utils.extract_watershed` (lignes 312-376) | Legacy `hydromodpy.watershed.Watershed` | Supprimer (ou `DeprecationWarning`). |
| `core/tools/io_utils.load_simulation_results` | Format pré-Simulation-Catalog | Supprimer — remplacé par `SimulationCatalog.find(...)`. |
| `core/tools/visualization.py` | Hors périmètre core, orienté examples | Déplacer. |
| `core/workspace/workspace._resolve_bin_path` (ligne 25) | Scan de path `parents[3]/bin` jamais utilisé en pratique | Vérifier + supprimer. |
| `core/workspace/config.py:76` `catalog.db`/`catalog.duckdb` | Nom obsolète (vraie DB = `hydromodpy.duckdb`) | Aligner. |

### 9.3 Anti-patterns notables

| Localisation | Problème | Recommandation |
|---|---|---|
| `hydromodpy_config.py:239-241` | `"__DEM_API_BOOTSTRAP__"` sentinelle dans un `Path` | `Optional[Path]` + flag booléen. |
| `hydromodpy_config.py:288-289` | Mutation post-validation de `cfg.simulation.run_id` | Déplacer dans le dict avant `cls(**…)`. |
| `toml_loader.py:41` `_repair_path_like_basic_strings` | Masque un bug TOML utilisateur | Remplacer par une erreur plus pédagogique ; exiger TOML valide. |
| `log_manager.py:14-43` Singleton | Anti-pattern, état global | Simplifier via `logging.getLogger("hydromodpy")` + `dictConfig`. |
| `raster_io.py:246-261` | Détection CRS invalide par pattern matching | Utiliser pyproj (`crs.to_epsg()` fallback). |
| `raster_io.py:217-239` | Décodage CF NetCDF manuel | Confier à xarray (`decode_cf=True`). |
| `geospatial.py:67` | EPSG:2056 hardcodé pour centroid | `gdf.estimate_utm_crs()`. |
| `geospatial.py:87-92` | Boucle Python sur pixels d'un DEM | Vectoriser avec `Transformer.transform(x_arr, y_arr)`. |
| `geospatial.py:134-137` | Double boucle Python sur grille lon/lat | `shapely.vectorized.contains`. |
| `statistics.py:15-41` | Suffixe `_manual` | Renommer. |
| `units/time.py:61` | `years = 365.25 * 86400` | Documenter le piège ou retirer l'entrée. |

### 9.4 Optimisation

| Localisation | Amélioration | Gain estimé |
|---|---|---|
| `time/window.py:261-267` | `_build_time_boundaries` Python-loop | ~100× via `pd.date_range`. |
| `tools/geospatial.transform_coordinates` | Double loop 1M pixels | ~100× via vectorisation. |
| `tools/geospatial.select_within_polygon_points` | Double loop grille | ~100× via `shapely.vectorized`. |

---

## 10. Conclusion

Le package `core/` remplit son rôle d'infrastructure — les configurations
se chargent, les workspaces se résolvent, les temps se valident — mais il
porte une dette technique visible :

1. **Le système d'unités (1 085 lignes) est la plus grosse dette
   technique.** Il duplique partiellement pint et introduit un risque
   d'erreur dimensionnelle silencieuse incompatible avec des simulations
   physiques. **Action prioritaire.**

2. **Le package `core/tools/` est un tiroir fourre-tout.** Il contient
   du code mort (`folder_root.py`), du code orienté-examples
   (`io_utils.py`, `visualization.py`), du code correct mais mal placé
   (`statistics.py`) et du code réinventé (`raster_io.py` vs rioxarray
   natif, `log_manager.py` vs logging stdlib). **Nettoyer = ~1 000 lignes
   supprimées ou déplacées.**

3. **Le pattern `ParamLevel`/`VisibleWhen` est défendable** pour un projet
   qui expose à la fois une génération TOML et une UI Streamlit
   auto-générée — mais il faut factoriser les helpers d'introspection
   Pydantic actuellement dupliqués.

4. **`HydroModPyConfig`** devrait (a) activer `extra="forbid"` à la
   racine, (b) regrouper les 16 sections en sous-groupes
   (`solvers.modflow6`, `solvers.modflownwt`), (c) éviter la sentinelle
   magique `"__DEM_API_BOOTSTRAP__"`.

5. **Le pattern `WorkflowContext` + 3 scopes est correct en intention**
   mais `LoadedDataContext` (17 champs `None`) et `SetupContext`
   (13 champs `None`) sont anémiques et fragiles à l'évolution. Un
   `dict[str, T]` + helper typé serait plus souple.

6. **Time management** est bon pour le cas d'usage local (bassin
   versant France) mais naïf sur la timezone : documenter ou typer
   explicitement.

7. **Workspace** est une des parties les plus saines du package —
   conforme aux conventions cookiecutter-data-science, `output_root`
   séparable propre. Un bug mineur (`catalog.duckdb` vs
   `hydromodpy.duckdb`) à corriger.

**Volumétrie de nettoyage estimée :**
- Suppressible net : ~400 lignes (`folder_root.py`, parties legacy
  d'`io_utils.py`).
- Déplaçable : ~700 lignes (`visualization.py`, `io_utils.py`).
- Factorisable : ~500 lignes (unités, introspection Pydantic dupliquée).
- Soit **~1 600 lignes (22 % du package)** qui pourraient disparaître ou
  migrer.

---

*Fin de l'audit `core/`.*
