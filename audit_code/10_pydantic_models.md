# Audit 10 — Modèles Pydantic de HydroModPy

**Date** : 2026-04-18
**Périmètre** : ensemble des classes héritant de `BaseModel` / `BaseVariableConfig` dans `hydromodpy/`
**Contexte** : post-merge `dev-refact → dev-database` (899 fichiers, 487 ajouts). Le merge a surtout ajouté du code solveur Boussinesq et des cas de validation ; les modèles Pydantic existants n'ont pas été réécrits massivement.
**Angle** : audit d'expert Pydantic v2 + design d'API de configuration. Regard sans complaisance sur typage, validation, héritage, duplication, defaults hydrogéologiques.

---

## 0. Synthèse exécutive

### 0.1 Scoreboard global

| Dimension | Score /10 | Constat |
|-----------|:---------:|---------|
| Adoption Pydantic v2 (syntaxe) | 9 | `field_validator`, `model_validator`, `ConfigDict` systématiques ; aucun reste de v1 |
| Validation hydrogéologique | **3** | K, Sy, Ss, n, dt, vka sans bornes physiques dans la plupart des champs critiques |
| Précision du typage | 6 | `Literal` bien employé mais `object`/`Any`/`dict[str, Any]` trop présents dans la couche process/base |
| Héritage et composition | 5 | Héritages à un seul niveau mal exploités (`FlowConfig ← ProcessSpatialConfig`, `TMeshCaseScenarioConfig ← TMeshConfigModel`) |
| Réutilisabilité / DRY | **3** | Duplication massive dans `data/variables/*/config.py` (≈1 000 lignes réutilisables) |
| Descriptions & `ParamLevel` | 9 | Presque tous les champs portent description + niveau — excellent |
| Round-trip TOML↔Pydantic | 7 | Fonctionne mais pas de `serialize_by_alias`/`populate_by_name` global ; sérialisation de `Path` hétérogène |
| Validation cross-section (agrégateur) | 4 | `HydroModPyConfig.from_toml` contient 70 lignes de parsing qui devraient être un `@model_validator(mode="before")` |
| **Note globale** | **6/10** | Pydantic v2 correctement utilisé côté syntaxe, mais duplication, types vagues et validation physique absente dégradent la robustesse. |

### 0.2 Verdicts par famille

| Famille | Nb classes | Verdict majoritaire |
|---------|:----------:|---------------------|
| `core/` (`hydromodpy_config.py`, `workspace/config.py`) | 2 | Bien pour Workspace ; à renforcer pour l'agrégateur |
| `process/base/` (IC, BC, SS, process_spatial) | 4 | **Mal typé** : `object`/`dict[str, object]` omniprésents |
| `process/flow/` | 11 | **Excellent** sur BC/SS, `FlowRechargeConfig.values: Any` est un point noir |
| `process/transport/` | 6 | Prototype acceptable ; `TransportInitialConditions.payload: dict[str,Any]` à typer |
| `solver/base`+`solver/modflow*` | 7 | Bon ; *vka* et tolérances sans bornes physiques, duplication avec dataclass `*SpecifParams` |
| `solver/utils/temporal` | 2 | `TMeshConfigModel` bien, `TMeshCaseScenarioConfig` héritage fragile |
| `solver/utils/mesh/cartesian_grid` | 4 | Excellent (sgrid_config est une référence) |
| `solver/utils/mesh/gmsh_grid/zone_meshing` | 12 | Excellent, validation multi-niveaux |
| `spatial/domain` | 6 | Bon (discriminated unions `DomainSupportConfig`, `DepthModelConfig`) |
| `spatial/field/core` | 6+ | Bon unit-handling ; **aucune borne physique sur K/Sy/Ss** |
| `spatial/geographic` | 2 | Acceptable, CRS `EPSG:2154` codé en dur dans le synthétique |
| `spatial/mesh/config.py` | 10 | Trop imbriqué, pas de racine claire |
| `data/common/base_config.py` | 1 | Bien (TOML + validation dates) |
| `data/variables/*/config.py` | ≈30 | **Duplication massive** — 12/17 fichiers à 95 % identiques |
| `data/data_managers_config.py` | 1 | Orchestrateur lourd, circular imports compensés par `model_rebuild()` |
| `analysis/calibration/*` | ≈25 | Validation physique exemplaire (meilleur sous-système de l'audit) |
| `analysis/display`, `analysis/postprocess`, `analysis/comparison`, `analysis/capability_gallery` | 15+ | Bien conçus, pragmatiques (presets, env-vars) |
| `simulation/planning/config.py` | 3 | Bien, parsing inline d'unités « 30 day » robuste |
| `results/config.py` | 5 | Simple et clair |

### 0.3 Cinq problèmes prioritaires

1. **P0 — Validation hydrogéologique physique absente** sur K (]0, 100] m/s), Sy (]0, 1[), Ss (]0, 1e-3] m⁻¹), porosité (]0, 1[), `vka`, `dt > 0`. Conséquence : un utilisateur peut créer une config numériquement invalide acceptée par Pydantic et qui part en divergence au solveur.
2. **P0 — Duplication de `data/variables/*/config.py`** : 10 fichiers (etp, humidity, runoff, soil_moisture, temperature, wind, precipitation, radiation) sont à ≈95 % identiques. ~1 000 lignes de code à factoriser derrière `TimeseriesSourceConfig`.
3. **P1 — Types vagues dans `process/base`** : `InitialCondition.value: object | None`, `BoundaryCondition.type: str` (au lieu de `Literal["Dirichlet","Neumann","Cauchy"]`), `ProcessSpatialConfig.{ic,bc,param,sinks_sources}: object | dict[str, object]`. Reporte toute validation à runtime.
4. **P1 — Héritage mal exploité** : `FlowConfig ← ProcessSpatialConfig` redéfinit 100 % des champs du parent ; `TMeshCaseScenarioConfig ← TMeshConfigModel` hérite pour exclure ensuite des champs dans `to_builder_kwargs()`. Composition serait plus propre.
5. **P1 — Agrégateur top-level `HydroModPyConfig`** sans validation cross-section, avec un `classmethod from_toml()` de 70 lignes qui normalise et dérive (run_id, DEM) — ce devrait être un `@model_validator(mode="before")`.

---

## 1. Couche `core/`

### 1.1 `HydroModPyConfig` — agrégateur top-level

- **Fichier** : `hydromodpy/core/config/hydromodpy_config.py:62`
- **Parent** : `BaseModel`
- **ConfigDict** : `arbitrary_types_allowed=True` (pour accepter `Path` etc.)
- **Champs** (tous avec `default_factory=Model()`) : `workspace`, `geographic`, `domain`, `data`, `flow`, `transport`, `solver`, `modflownwt`, `modflow6`, `display`, `postprocess`, `capability_gallery`, `overview`, `mesh_catchment`.
- **Validators** : **aucun** au niveau classe.
- **Méthodes** : `from_toml()` statique (≈70 lignes de parsing + dérivation run_id + bootstrap DEM), `from_snapshot()` avec `_deep_merge()`.

| Description | Verdict | Justification | Recommandation |
|-------------|---------|---------------|----------------|
| Agrégateur racine du schéma TOML ; compose toutes les sous-sections ; gère chargement TOML + dérivations de chemins. | **À renforcer** | Aucune validation cross-section (ex : si `[simulation]` actif, `[data.types]` doit être cohérent). `from_toml` mélange I/O (lecture TOML), logique (parsing sections), et défauts (DEM bootstrap). | Déplacer la logique de `from_toml` dans `@model_validator(mode="before")`. Ajouter `@model_validator(mode="after")` pour invariants inter-sections. Envisager `Annotated[ModflowNwtConfig | Modflow6Config, Field(discriminator="solver_engine")]` pour l'engine. |

**Point non-trivial** : pas de `ConfigDict(extra="forbid")` sur l'agrégateur — au niveau racine, **tolérer des sections inconnues est l'opposé de ce qu'on veut** (typos TOML silencieuses).

### 1.2 `WorkspaceConfig`

- **Fichier** : `hydromodpy/core/workspace/config.py:9`
- **Parent** : `BaseModel`
- **ConfigDict** : `extra="forbid"` ✓
- **Champs** : `project_root: Path` (requis), `output_root: Path | None`, `workspace_root: Path | None` (auto-découverte).
- **Validators** : `@model_validator(mode="after")` pour la découverte heuristique du `workspace_root` (scan de `projects/`, `catalog.duckdb`, `catalog.db`, `data/`).
- **Propriétés** : `_effective_output_root`, `catch_name`, `solver_scratch_folder`, `data_path`, `catalog_path`.

| Description | Verdict | Justification | Recommandation |
|-------------|---------|---------------|----------------|
| Racine du workspace utilisateur ; abstraction des chemins auto-découverts. | **Bien conçu** | `extra="forbid"`, validators v2, heuristiques claires, propriétés nommées avec `_` pour celles dérivées. | Ajouter une validation que `project_root.exists()` (option, désactivable pour tests). Supprimer l'ambiguïté double catalogue (`catalog.duckdb` vs `catalog.db`) dès que la migration DuckDB est finalisée. |

### 1.3 `streamlit_config.py` et `generate_toml.py`

Ces fichiers **ne définissent aucun modèle Pydantic**. Ce sont des outils d'introspection qui lisent `model_fields`, `FieldInfo.metadata`, `get_origin()`, `get_args()` pour générer respectivement :
- un rendu Streamlit des configs (`streamlit_config.py`),
- un template TOML annoté par `ParamLevel` (`generate_toml.py`).

**Verdict** : outils Pydantic v2 conformes (`model_fields`, `model_validate`, `model_dump`). `generate_toml._placeholder()` fait ~100 lignes — candidat à découpage.

---

## 2. Couche `process/base/` — bases abstraites

### 2.1 `ProcessSpatialConfig`

- **Fichier** : `hydromodpy/process/base/process_spatial_config.py:20`
- **Parent** : `BaseModel`
- **ConfigDict** : `extra="forbid"` ✓
- **Champs clés** :
  ```python
  ic: Annotated[object | None, ...]
  bc: Annotated[dict[str, object], ...]
  param: Annotated[dict[str, object], ...]
  sinks_sources: Annotated[dict[str, object], ...]
  active_bc: list[str]
  active_sinks_sources: list[str]
  param_list: list[str]
  ```
- **Validators** : aucun.

| Verdict | Justification | Recommandation |
|---------|---------------|----------------|
| **Mal typé** | `object` et `dict[str, object]` délèguent la validation 100 % aux sous-classes. Aucun validateur de base. L'intention est *générique polymorphe* mais elle n'est documentée nulle part dans le type. | Rendre `ProcessSpatialConfig` générique : `class ProcessSpatialConfig(BaseModel, Generic[IC, BC, SS]): ic: IC | None = None; bc: dict[str, BC] = Field(default_factory=dict); ...`. Les sous-classes (`FlowConfig`) paramétreraient les TypeVars. Sinon, supprimer cette couche et dupliquer les champs dans chaque process (le gain DRY est nul quand tout est `object`). |

### 2.2 `InitialCondition` (base)

- **Fichier** : `hydromodpy/process/base/initial_conditions.py:24`
- **Champs** : `id: str`, `value: object | None`, `description: str`, `units: str`.
- **Validators** : aucun.

**Verdict** : *trop générique*. `value: object` accepte n'importe quoi. À documenter explicitement, ou à remplacer par un `TypeVar`.

### 2.3 `BoundaryCondition` (base)

- **Fichier** : `hydromodpy/process/base/boundary_conditions.py:17`
- **Champs** : `id: str` (requis), `value: float` (requis), `description: str`, `units: str`, `type: str = "Dirichlet"`, `data_value: bool`.
- **Validators** : **aucun**.

**Verdict** : *à renforcer*. `type: str` devrait être `Literal["Dirichlet", "Neumann", "Cauchy", "Robin"]`. `value` sans contrainte. Un utilisateur peut saisir `type = "dirichlet"` (casse différente) ou `type = "GHB"` et rien ne bronche. Sémantique de `data_value` confuse (docstring absente).

### 2.4 `SinkSource` (base)

Mêmes remarques que `BoundaryCondition` : `value: float` sans contrainte, `link_data: list` sans type d'élément.

### 2.5 Tableau récap `process/base/`

| Classe | Champs critiques non typés | Verdict |
|--------|---------------------------|:-------:|
| `ProcessSpatialConfig` | `ic`, `bc`, `param`, `sinks_sources` tous en `object`/`dict[str, object]` | Mal typé |
| `InitialCondition` | `value: object \| None` | Trop générique |
| `BoundaryCondition` | `type: str` (devrait être `Literal`) | À renforcer |
| `SinkSource` | `value: float` sans contrainte ; `link_data: list` sans élément | À renforcer |

---

## 3. Couche `process/flow/`

### 3.1 `FlowConfig`

- **Fichier** : `hydromodpy/process/flow/flow_config.py:51`
- **Parent** : `ProcessSpatialConfig`
- **Champs clés** : `flow_regime: Literal["steady","transient"]`, `runtime_backend: Literal[...]`, `runtime_tol_*`, `param_list`, `param`, `bc`, `ic`, `sinks_sources`, `active_*`.
- **Validators** : **14** `field_validator` + `model_validator` (param_list, param, bc, ic, sinks_sources, active_*, tolérances, cross-validation `_validate_param_consistency`).
- **Classmethod** : `from_toml_section()` (~130 lignes).

| Verdict | Justification | Recommandation |
|---------|---------------|----------------|
| **Bien structuré mais verbeux** | Typage fort (`Literal`), validation rigoureuse, cross-check `param_list ↔ param`. Mais 14 validateurs = signal de design dispersé. L'héritage de `ProcessSpatialConfig` est *en pratique* inutile : tous les champs hérités sont redéfinis ou retypés. `from_toml_section` contient 130 lignes de logique dans une `classmethod`. | (1) Remplacer l'héritage par composition : `spatial: ProcessSpatialConfig = ...`. (2) Fusionner les 4 tolerance validators en un seul. (3) Migrer `from_toml_section` dans `@model_validator(mode="before")` + un helper externe de path-resolution. |

### 3.2 `FlowInitialConditions`, `FlowBoundaryConditionConfig`, `FlowWellConfig`, `FlowRechargeConfig`

| Classe | Ligne | Verdict | Commentaire |
|--------|------:|:-------:|-------------|
| `FlowInitialConditions` | `initial_conditions.py:66` | Correct | Héritage de `InitialCondition` maladroit (le parent avait `value: object`, cette classe impose `float | None`) → préférer composition. |
| `FlowInitialCondition` | `initial_conditions.py:31` | Correct | `type: Literal["top","bottom","custom"]` ✓. `_validate_custom_value` en mode *after* ✓. |
| `FlowBoundaryForcing{Constant,Csv}Config` + `FlowBoundaryForcingConfig` | `boundary_conditions.py:78/96/130` | **Excellent** | Polymorphisme via 3 sous-classes, `as_constant()`/`as_csv()` pour extraction typée. **Mais** devrait être une `Annotated[Union[...], Field(discriminator="mode")]` au lieu de 3 classes séparées. |
| `FlowBoundaryConditionConfig` | `boundary_conditions.py:181` | **Excellent** | 4 `field_validator` + 1 `model_validator`. Gestion unités robuste (Dirichlet m, Cauchy m²/s). Enforcement `value XOR forcing`. |
| `FlowWellConfig` | `sinks_sources.py:58` | **Très bon** | 3 modes de localisation (cell / absolute_xy / relative_xy) gérés par validators. `resolve_cell(grid)` runtime. 6 field_validators. **Candidat pour discriminated union** sur le mode de localisation. |
| `FlowWellForcing{Constant,Csv}Config` + `FlowWellForcingConfig` | `sinks_sources.py:345/363/394` | Excellent mais dupliqué | Copie quasi exacte des `FlowBoundaryForcing*` — à factoriser dans `process/base/forcing.py`. |
| `FlowRechargeConfig` | `sinks_sources.py:445` | **Problématique** | `values: Any` (!) accepte float, list, dict, pandas Series, FieldRecords. `heterogeneous_source: Any`. `first_clim: str | float` (mélange Literal et numérique). Aucune validation de bornes. `negative_to_evt: bool = True` est un comportement implicite non documenté. |
| `FlowSinksSourcesConfig` | `sinks_sources.py:594` | Simple, correct | — |

### 3.3 Duplication Forcing

Le pattern Forcing (constant / csv) est implémenté **deux fois** :

| Emplacement | Classes |
|-------------|---------|
| `process/flow/boundary_conditions.py:78-180` | `FlowBoundaryForcingConstantConfig`, `FlowBoundaryForcingCsvConfig`, `FlowBoundaryForcingConfig` |
| `process/flow/sinks_sources.py:345-444` | `FlowWellForcingConstantConfig`, `FlowWellForcingCsvConfig`, `FlowWellForcingConfig` |

**Refactor proposé** dans `process/base/forcing.py` :

```python
class ConstantForcing(BaseModel):
    mode: Literal["constant"] = "constant"
    value: float
    units: str | None = None

class CsvForcing(BaseModel):
    mode: Literal["csv"] = "csv"
    path_file: Path
    col_datetime: str = "datetime"
    col_value: str = "value"
    # ...

Forcing = Annotated[ConstantForcing | CsvForcing, Field(discriminator="mode")]
```

Les deux familles deviennent `forcing: Forcing | None = None`. **≈100 lignes éliminées**.

---

## 4. Couche `process/transport/`

- **Classes** : `TransportInitialConditions` (`transport.py:28`), `ModpathParametersConfig`, `TransportModpathConfig`, `ConcentrationTransportParametersConfig`, `TransportMt3dmsConfig`, `TransportModflow6GwtConfig` (tous `transport_config.py`).
- **Hérite** : `TransportConfig ← ProcessSpatialConfig` (même problème que FlowConfig).

| Classe | Verdict | Points noirs |
|--------|:-------:|--------------|
| `TransportInitialConditions` | Trop vague | `payload: dict[str, Any]` — aucun typage. Devrait être soit `dict[str, float]` (si c'est une cartographie zone→concentration) soit une classe dédiée. |
| `ModpathParametersConfig` | Correct | `cell_div: int` avec `ge=1` ✓, `bore_depth: list[float] | None` sans validation de croissance/non-vide. |
| `ConcentrationTransportParametersConfig` | Correct | Bornes basiques mais pas de validation de cohérence unités input/IC. |
| `TransportMt3dmsConfig`, `TransportModflow6GwtConfig` | Minimaux | Peu de validation, acceptable pour prototype. |

---

## 5. Couche `solver/`

### 5.1 `SolverConfig` (base)

- **Fichier** : `hydromodpy/solver/base/solver_config.py:13`
- **Champs** : `solver_engine: Annotated[SolverEngine, ParamLevel("user")] = SolverEngine.MODFLOW_NWT`.
- **Verdict** : **Bien conçu** (minimaliste, enum externalisée).

### 5.2 `Modflow6Config`

- **Fichier** : `hydromodpy/solver/modflow6/modflow6_config.py` lignes 16, 81, 97.
- **Classes** : `Modflow6RuntimeConfig` (contient dvclose, maximum, rewet_*), `Modflow6ProcessSpecificConfig` (vka, evt_extinction_depth), `Modflow6Config` (runtime + process_specific + sgrid + tgrid), et une **dataclass frozen `Modflow6SpecifParams`** qui miroite les champs Pydantic.

| Description | Verdict | Justification | Recommandation |
|-------------|---------|---------------|----------------|
| Runtime et paramètres physiques MODFLOW 6. | **Acceptable avec réserves** | Bornes basiques (`gt=0`, `ge=1`) en place. **`vka` (anisotropie verticale) sans validation** — peut être ≤ 0 ou > 1000. `evt_extinction_depth: gt=0` mais pas de borne supérieure. La dataclass `Modflow6SpecifParams` duplique les champs Pydantic sans apporter d'immutabilité supplémentaire (le modèle Pydantic est déjà *immutable* avec `model_config = ConfigDict(frozen=True)` si nécessaire). | Ajouter `vka: Annotated[float, Gt(0), Le(100)]`. Ajouter `model_validator` de cohérence (ex : `mf6_rewet_iwetit > 0 ⇒ mf6_rewet_wetfct > 0`). Supprimer la dataclass `Modflow6SpecifParams` ou en faire une vue read-only générée par `model_dump()`. |

### 5.3 `ModflowConfig` (NWT)

- **Fichier** : `hydromodpy/solver/modflow_nwt/modflow/nwt_config.py` lignes 17, 140, 165, 207.
- **Classes** : `ModflowRuntimeConfig`, `ModflowProcessSpecificConfig`, `ModflowConfig`, `ModflowSpecifParams` (dataclass).

| Verdict | Justification |
|:-------:|---------------|
| **Partiellement validé** | `exdp` a bien un `field_validator("exdp", mode="before")` qui appelle `parse_length_to_m` et vérifie > 0 — **exemplaire**. Mais `vka` reste sans validation (copie du problème MF6). `nwt_headtol`, `nwt_fluxtol` sans borne supérieure (tolérance > 1 m n'a pas de sens hydrogéo). Même duplication dataclass `ModflowSpecifParams`. |

### 5.4 `TMeshConfigModel` et `TMeshCaseScenarioConfig`

- **Fichier** : `solver/utils/temporal/tmesh_config.py:17` et `cases/run_tmesh_config.py:16`.

| Classe | Verdict | Commentaire |
|--------|:-------:|-------------|
| `TMeshConfigModel` | **Bien conçu** | 8 `field_validator` + 1 `model_validator` (cross-field). `itmuni`, `flow_regime`, `genmtd` en `Literal`. `_compute_substeps_and_tsmult` vérifie cohérence `ntsp ≥ 1`, `tsmult ≥ 1`. |
| `TMeshCaseScenarioConfig ← TMeshConfigModel` | **Héritage fragile** | Hérite *tous* les champs temporels puis en **exclut** certains dans `to_builder_kwargs()`. Viole le principe de substitution de Liskov. `TMeshCasesConfig._validate_unique_ids` **déduplique silencieusement** les doublons au lieu de rejeter — risque de perte de scénarios. |

**Recommandation** :
```python
class TMeshCaseScenarioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str | None = None
    tmesh: TMeshConfigModel
    def to_builder_kwargs(self) -> dict: return self.tmesh.to_builder_kwargs()
```
Et dans `TMeshCasesConfig` : **lever `ValueError`** sur doublons d'`id`, pas de déduplication.

### 5.5 `SGridConfig` et consorts

- **Fichier** : `solver/utils/mesh/cartesian_grid/sgrid_config.py` lignes 48, 128, 165, 185.
- **Classes** : `VerticalGridConfig`, `PlanarGridConfig`, `SolverSGridConfig`, `SGridConfig`.

| Verdict | Justification |
|:-------:|---------------|
| **Excellent** | `Literal` pour les enums (`genmtd_lay`, `mode`, `resampling`). `lay_proportions` vérifiée sommer à 1.0 ± 1e-6 (strictement correct). `_require_existing_file()` pour paths. `_require_positive_int()` helper réutilisable. Cross-field validation (325-365) exhaustive. **Référence du projet pour la config grille.** |

**Points mineurs** : `thick` et `zbot` sans validation (`thick > 0`, `zbot` libre). `nodata = -9999.0` par défaut mais pas de commentaire sur la raison (certains rasters GDAL utilisent `-32768` ou `NaN`).

### 5.6 `ZoneMeshingSettings` et sous-schemas

- **Fichier** : `solver/utils/mesh/gmsh_grid/zone_meshing/config.py` (6 classes, lignes 27, 70, 95, 138, 180, 261) et `_domain_schema.py` (6 classes discriminées).

| Verdict | Justification |
|:-------:|---------------|
| **Excellent** | Hiérarchie imbriquée 6 niveaux, **non-diamant**. `_validate_cross_constraints` injecte des defaults intelligents (`interface_size` calculée si omise). Factory `validate_zone_meshing_domain_model` infère le `kind` si omis (user-friendly). Discriminated unions propres. |

**Points mineurs** : `global_size` sans borne supérieure (un utilisateur peut saisir `1e10` m). Le suffixe `…Schema` sur toutes les classes est un reliquat hérité de Pydantic v1 (utilisait `Schema` au lieu de `Field`) — à nettoyer par cohérence Pydantic v2.

### 5.7 `SGridFieldParamDiscretizationConfig`

- **Fichier** : `solver/utils/mesh/cartesian_grid/examples/discretization/run_demo_config.py:97`
- **Verdict** : **Couplage fort, perte de typage**. Les champs `geology`, `field_param`, `sgrid` sont typés `dict[str, Any]` alors qu'on dispose déjà de `GeologyConfigSchema`, `FieldParamConfig`, `SGridConfig`. À remplacer par les types concrets.

### 5.8 Fichiers `case_config.py` (gmsh reference cases)

Les fichiers `solver/utils/mesh/gmsh_grid/cases/reference_*/case_config.py` sont des **helpers de composition** (chargement de configs sous-jacentes + résolution de chemins). Ils **n'exposent aucune classe Pydantic**. **Verdict** : *contract manquant*. Chaque cas devrait exposer une `ReferenceXxxCaseConfig(BaseModel)` pour valider son payload TOML au lieu de manipuler des dicts.

---

## 6. Couche `spatial/`

### 6.1 `DomainConfig` et `DomainSupportConfig`

- **Fichier** : `spatial/domain/domain_config.py:12` et `spatial_support_config.py:11-231`.

| Classe | Verdict | Commentaire |
|--------|:-------:|-------------|
| `DomainConfig` | Bien conçu | `extra="forbid"`, normalisation zone_ids (lowercase + dédup), 4 field_validators. |
| `DomainSupportBaseConfig` + 4 providers + TypeAlias discriminé `DomainSupportConfig` | **Excellent** | Discriminated union propre, breaks/radii strictement croissants, `parse_length_to_m()` pour coordonnées absolues. |

**Point à surveiller** : `DomainConfig` déduplique les `zone_ids` **silencieusement** → un utilisateur qui saisit `zone_ids=["agri","Agri"]` perd une zone sans avertissement.

### 6.2 `DepthModelConfig`

- **Fichier** : `spatial/domain/depth_model_config.py:11, 46, 71`
- **Classes** : `ConstantThicknessDepthModel`, `FlatSubstratumDepthModel`, `DepthModelConfig` (TypeAlias discriminé).

**Verdict** : **Correct**. `thickness: gt=0` ✓ avec `parse_length_to_m` en mode=before. `substratum_elevation` sans validateur, mais c'est acceptable (une élévation peut être négative, ex. sous niveau marin).

### 6.3 `FieldParamConfig` et sous-schemas

- **Fichier** : `spatial/field/core/field_param_config.py:72, 131, 162, 321, 473, 512`
- **Classes** : `FieldBaseSectionSchema`, `FieldHomogeneousSectionSchema`, `FieldHeterogeneousSectionSchema`, `FieldVerticalProfileSectionSchema`, `FieldParamConfig`, `ResolvedFieldParamSchema`.

| Verdict | Justification |
|:-------:|---------------|
| **Incomplet sur la physique** | Unit normalization exhaustive (`_UNIT_ALIASES`, `normalize_m_per_s_unit`). Mais **aucune validation de bornes physiques** pour K, Sy, Ss, porosité. L'`id` est libre → on ne sait pas qu'un `id="K"` devrait avoir unit `m/s` et value ∈ ]0, 100]. |

**Recommandation clé** : table de contraintes par paramètre.

```python
_PHYSICAL_BOUNDS: dict[str, tuple[str, float, float]] = {
    "k":  ("m/s",  1e-12, 1e0),
    "sy": ("-",    1e-3,  0.5),
    "ss": ("1/m",  1e-8,  1e-3),
    "n":  ("-",    0.01,  0.6),  # porosité
}

@model_validator(mode="after")
def _validate_physical_bounds(self) -> "FieldHomogeneousSectionSchema":
    entry = _PHYSICAL_BOUNDS.get(self.id.lower())
    if entry is None: return self
    expected_unit, lo, hi = entry
    if self.unit not in _equivalent_units(expected_unit):
        raise ValueError(f"Field id={self.id!r} expects unit {expected_unit}, got {self.unit!r}")
    val = self.value
    if isinstance(val, float) and not (lo < val < hi):
        raise ValueError(f"Field id={self.id!r} value {val} outside physical bounds ]{lo}, {hi}[")
    return self
```

### 6.4 `GeographicConfig`, `RiverNetworkConfig`, `SyntheticGridConfig`

| Classe | Verdict | Commentaire |
|--------|:-------:|-------------|
| `RiverNetworkConfig` (`geographic_config.py:13`) | Acceptable | `threshold_mode` en `Literal` mais **pas de cross-field** qu'un des deux seuils (area_km2 / cells) soit défini. |
| `SyntheticGridConfig` (`spatial/geographic/synthetic/config.py:16`) | Bon | `model_validator` check dx≈dy. **CRS `EPSG:2154` codé en dur** → acceptable pour un projet français mais à paramétrer si le projet vise l'international. |

### 6.5 `spatial/mesh/config.py`

Ce fichier contient ~10 classes `MeshCatchment*ConfigSchema` (lignes 48, 121, 159, 197, 231, 293, 434, 469, 686, 741).

**Verdict** : **complexe et fragmenté**. Pas de classe mère unique structurant l'intention (`MeshCatchmentConfig` n'a pas de parent). Le suffixe `…ConfigSchema` partout est redondant (`Config` + `Schema`). **Duplication conceptuelle** avec `sgrid_config.py` sur la partie grille cartésienne.

**Recommandation** : unifier sgrid / mesh en un seul schéma racine (`GridConfig` discriminé sur `kind: Literal["cartesian", "gmsh", "external"]`).

---

## 7. Couche `data/` — c'est ici que se concentre la dette

### 7.1 `BaseVariableConfig`

- **Fichier** : `data/common/base_config.py:31`
- **Champs** : `date_start: str | None`, `date_end: str | None`.
- **Validator** : `@field_validator("date_start", "date_end", mode="after")` → parse ISO + ordre chronologique.
- **Méthodes** : `from_toml()` classmethod avec fallback `tomllib` / `tomli`.

**Verdict** : **Bien conçu**. Centralise la logique date+TOML pour tous les variables.

**Point à améliorer** : `ValueError` levée sans contexte — un utilisateur voit juste `Invalid isoformat string: '2020/01/01'`, pas quel champ de quelle section TOML. À wrapper avec le nom du champ.

### 7.2 Les 17 fichiers `data/variables/*/config.py` — **duplication massive**

Chaque fichier suit le pattern `{Var}SourceConfig` + `{Var}Config`. Le tableau ci-dessous résume :

| Variable | Fichier.py | Lignes | Hérite `BaseVariableConfig` | Champs spécifiques | Similarité moy. avec le "noyau" |
|----------|:----------:|:------:|:--:|---|:--:|
| dem | `dem/config.py` | 89 | Non | `path, mask_path, extent` | Cas spécial (pas de dates) |
| etp | `etp/config.py` | 58 | Oui | `source_unit`, cols génériques | **~95 %** |
| geology | `geology/config.py` | 392 | Oui | raster+vector dual + 2 schemas supplémentaires | Justifié (complexité réelle) |
| humidity | `humidity/config.py` | 68 | Oui | Idem ETP | **~95 %** |
| hydrography | `hydrography/config.py` | 79 | Non | vecteur (WFS/OSM) | Spécifique (OK) |
| hydrometry | `hydrometry/config.py` | 89 | Oui | `product`, Hub'Eau | ~75 % |
| intermittency | `intermittency/config.py` | 86 | Oui | `code_departement`, ONDE | ~75 % |
| oceanic | `oceanic/config.py` | 89 | Oui | `value` constante, SHOM | Spécifique (OK) |
| piezometry | `piezometry/config.py` | 90 | Oui | `product: Literal["level","depth"]` | ~75 % |
| precipitation | `precipitation/config.py` | 65 | Oui | `components: liquid/solid/total` | ~85 % |
| radiation | `radiation/config.py` | 65 | Oui | `components: atmospheric/visible` | ~85 % |
| recharge | `recharge/config.py` | 97 | Oui | `values`, synthétique (amplitude, period_days) | ~65 % |
| runoff | `runoff/config.py` | 68 | Oui | Idem ETP | **~95 %** |
| soil_moisture | `soil_moisture/config.py` | 68 | Oui | Idem ETP | **~95 %** |
| temperature | `temperature/config.py` | 68 | Oui | Idem ETP | **~95 %** |
| water_quality | `water_quality/config.py` | 92 | Oui | `site_type`, `parameters` | Spécifique (OK) |
| wind | `wind/config.py` | 68 | Oui | Idem ETP | **~95 %** |

**Noyau commun identifié** (14 champs communs à 13 fichiers sur 17) :

```python
source: Literal[...]
path: Path | None
source_unit: str | None
col_id: str = "id"
col_x: str = "x"
col_y: str = "y"
col_crs: str = "crs"
default_crs: str = "EPSG:4326"
col_datetime: str = "datetime"
col_value: str = "value"
mask_path: Path | None = None
station_ids: list[str] | None = None
extent: Literal["watershed", "study_area"] | None = None
force_refresh: bool = False

@model_validator(mode="after")
def _check_source_requirements(self): ...
```

**Quantification de la dette** :
- Fichiers ≥ 95 % identiques (etp, humidity, runoff, soil_moisture, temperature, wind) : **6 × 68 lignes = 408 lignes dupliquées**.
- Fichiers ~85 % identiques (precipitation, radiation) : **2 × 65 lignes = 130 lignes**.
- Fichiers ~75 % identiques (hydrometry, intermittency, piezometry) : **3 × ~90 lignes = 270 lignes**.
- **Total refactorisable : ~800 lignes**, soit environ 50 % du code cumulé de `data/variables/`.

**Refactorisation proposée** — créer `data/variables/common/timeseries_source.py` :

```python
class TimeseriesSourceConfig(BaseModel):
    """Source générique pour variables temporelles de type point/station."""
    model_config = ConfigDict(extra="forbid")

    source: Literal["custom", "sim2", "hubeau"]
    path: Path | None = None
    source_unit: str | None = None

    # Colonnes CSV standardisées (SANDRE-ish)
    col_id: str = "id"
    col_x: str = "x"
    col_y: str = "y"
    col_crs: str = "crs"
    default_crs: str = "EPSG:4326"
    col_datetime: str = "datetime"
    col_value: str = "value"

    mask_path: Path | None = None
    station_ids: list[str] | None = None
    extent: Literal["watershed", "study_area"] | None = None
    force_refresh: bool = False

    @model_validator(mode="after")
    def _check_source_requirements(self) -> "TimeseriesSourceConfig":
        if self.source == "custom" and self.path is None:
            raise ValueError("Custom source requires 'path'")
        return self
```

Puis par variable :

```python
# precipitation/config.py
class PrecipitationSourceConfig(TimeseriesSourceConfig):
    components: list[Literal["liquid","solid","total"]] = ["total"]

# piezometry/config.py
class PiezometrySourceConfig(TimeseriesSourceConfig):
    source: Literal["custom", "hubeau"]   # override pour restreindre
    product: Literal["level", "depth"]
    require_observations: bool = False

# etp/config.py (+ humidity, runoff, soil_moisture, temperature, wind)
PrecipitationSourceConfig → EtpSourceConfig: simple alias si rien de spécifique
```

**Bénéfice attendu** : ~800 lignes supprimées, validation centralisée, ajout d'une nouvelle variable = 5-10 lignes au lieu de 70.

### 7.3 `DataManagersConfig`

- **Fichier** : `data/data_managers_config.py:51`
- **Taille** : 440 lignes.
- **Verdict** : **Orchestrateur lourd mais fonctionnel**. Les circular imports sont compensés par `model_rebuild()` en fin de module — pattern fragile.

| Problème | Détail |
|----------|--------|
| Triple enregistrement des types | `SUPPORTED_DATA_MANAGER_TYPES` (tuple), `_TYPED_SECTIONS` (dict), champs Annotated. Un type ajouté demande 3 modifications. |
| Circular imports | 17 imports statiques + `model_rebuild()`. Reconfiguration fragile lors d'un refactor. |
| Résolution de paths générique | `_resolve_section_paths` parcourt récursivement les champs, sans schema explicite de quels champs sont des paths. |

**Recommandation** : centraliser dans un module de registre neutre :

```python
# data/common/registry.py
DATA_TYPE_MODELS: dict[str, type[BaseModel]] = {}
def register(name: str):
    def _decorator(cls):
        DATA_TYPE_MODELS[name] = cls
        return cls
    return _decorator
```

Et dans chaque `*/config.py` : `@register("etp")` sur la classe `EtpConfig`.

---

## 8. Couche `analysis/` — la plus soignée

### 8.1 Calibration engine

- **Fichiers** : `analysis/calibration/core/engine_config.py` (391 lignes) et `methods_config.py` (~300 lignes).
- **Classes** : `CalibrationSectionSchema`, `OutputSectionSchema`, `ObjectiveSectionSchema`, `CalibrationTomlSchema`, `_MethodKwargsBase`, `GridSearchKwargs`, `RandomSearchKwargs`, `CmaEsKwargs`, `SimplexKwargs`, `GpMappingKwargs`, `DaMhGpKwargs`.

| Verdict | Justification |
|:-------:|---------------|
| **Excellent** | Validation `bounds: (low < high)` rigoureuse. `transform_params` restreint aux clés autorisées par transformer (`log` → `epsilon`, `box_cox` → `lambda_param`). Auto-désactivation de la surface objective en 3D+ (avec `warnings.warn`). Validation ISO des dates. Cross-section consistency entre `parameter_names` et `bounds` dans `ModelCalibrationConfig._validate_cross_section_consistency`. **Le sous-système le mieux validé du projet.** |

### 8.2 Cas de calibration (`groundwater_1d`, `recession_brutsaert`, `reservoir`)

**Verdict** : **Exemplaire pour la validation physique**.

Exemple `Groundwater1DChronicleSchema` (`cases/groundwater_1d/case_config.py:24`) :

```python
@model_validator(mode="after")
def _validate_domain_consistency(self):
    if not (0.0 < self.xi_true_m < self.L_m):
        raise ValueError("xi_true_m must satisfy 0 < xi_true_m < L_m")
    if any((x < 0.0 or x > self.L_m) for x in self.obs_x_m):
        raise ValueError("obs_x_m values must satisfy 0 <= x <= L_m")
```

Validation de bornes hydrauliques (K_am > 0, Sy_am ∈ ]0,1[), mois ∈ [1,12], `recharge_mode` dans `SUPPORTED_RECHARGE_MODES`. **C'est le pattern à généraliser au reste du projet.**

### 8.3 Comparaison (`MethodComparisonConfig`)

- **Fichier** : `analysis/comparison/config.py:287` (~460 lignes au total).
- **Classes** : `MethodComparisonVariantSchema`, `MethodComparisonObservableSchema`, `MethodComparisonSectionSchema`, `MethodComparisonFineRasterSchema`, `MethodComparisonConfig`.

**Verdict** : **Excellent**. Validation croisée, Literal partout, sections imbriquées bien structurées.

### 8.4 Display (`DisplayConfig`)

- **Fichier** : `analysis/display/display_config.py:24-189`.
- **Classes** : `FlowDisplayConfig`, `ParticlesDisplayConfig`, `TransportDisplayConfig`, `DisplayConfig`.

**Point remarquable** : `to_runtime_options()` honore les variables d'environnement `HYDROMODPY_NO_DISPLAY` / `HYDROMODPY_NO_SAVE` pour l'exécution headless (CI). **Pragmatique et correctement encapsulé.**

### 8.5 Postprocess (`PostprocessConfig`)

- **Fichier** : `analysis/postprocess/postprocess_config.py:40-116`.
- **Validator remarquable** : `@model_validator(mode="after") _apply_profile_preset` applique un preset `solver_only` qui désactive tous les exports — utile pour benchmarks.

**Verdict** : **Très bon** (presets bien intégrés).

### 8.6 `CapabilityGalleryConfig`

- **Fichier** : `analysis/capability_gallery.py:24`.
- **Verdict** : **Très bon utilitaire** (validation paths + sanitization noms d'assets).

---

## 9. Couche `simulation/` et `results/`

### 9.1 `SimulationConfig` et sous-classes

- **Fichier** : `simulation/planning/config.py:86, 164, 209`.
- **Classes** : `SimulationTimeConfig`, `SimulationProcessConfig`, `SimulationConfig`.

**Point remarquable** : parsing inline d'unités de temps — l'utilisateur peut saisir `step_value = "30 day"` OU `step_value = 30, step_unit = "day"`. Géré par `parse_scalar_and_unit`. Validation chronologique `end_datetime >= start_datetime`. `coverage_policy: Literal["error", "warn", "ignore"]`.

**Verdict** : **Excellent**.

### 9.2 `ResultsConfig` et sous-classes

- **Fichier** : `results/config.py:13-117`.
- **Classes** : `DerivedConfig`, `ExportVariablesConfig`, `ExportConfig`, `BudgetConfig`, `ResultsConfig`.
- **Méthode utile** : `ExportVariablesConfig.active_names() -> list[str]`.

**Verdict** : **Bien organisé, lisible**.

---

## 10. Arbre d'héritage global

```
BaseModel (pydantic)
├── HydroModPyConfig [agrégateur racine]
├── WorkspaceConfig
├── ProcessSpatialConfig [abstrait]
│   ├── FlowConfig
│   └── TransportConfig
├── InitialCondition [abstrait]
│   └── FlowInitialCondition
├── BoundaryCondition [abstrait]
├── SinkSource [abstrait]
├── SolverConfig
├── Modflow6Config, ModflowConfig (NWT)
├── TMeshConfigModel
│   └── TMeshCaseScenarioConfig  ⚠ héritage mal utilisé
├── SGridConfig, ZoneMeshingSettings, DomainConfig, FieldParamConfig, ...
├── BaseVariableConfig
│   ├── EtpConfig, HumidityConfig, ...  [16 sous-classes, majoritairement dupliquées]
└── ... (≈100 classes plates)
```

**Observations** :
- **Aucun héritage diamant** détecté.
- Profondeur maximale : 2 (sauf `TMeshCaseScenarioConfig ← TMeshConfigModel ← BaseModel` → niveau 3 mais anti-pattern).
- **Les héritages existants sont tous à un niveau et certains n'apportent rien** (`FlowConfig` redéfinit 100 % des champs de `ProcessSpatialConfig` ; `FlowInitialCondition` retype `value` à `float | None` alors que le parent a `object`).

**Recommandation** : remplacer `FlowConfig ← ProcessSpatialConfig` par composition. `ProcessSpatialConfig` devrait être `Generic[IC, BC, SS]` ou supprimé.

---

## 11. Valeurs par défaut — évaluation hydrogéologique

### 11.1 Defaults présents

| Champ | Fichier | Default | Évaluation |
|-------|---------|---------|-----------|
| `FlowRechargeConfig.values` | `process/flow/sinks_sources.py:445` | `0.0` | OK (zéro recharge) |
| `FlowRechargeConfig.units` | idem | `"mm/day"` | OK (hydro standard) |
| `FlowRechargeConfig.first_clim` | idem | `"mean"` | OK |
| `FlowRechargeConfig.negative_to_evt` | idem | `True` | Comportement implicite **à documenter explicitement** |
| `BoundaryCondition.type` | `process/base/boundary_conditions.py:17` | `"Dirichlet"` | OK mais devrait être `Literal` |
| `FlowInitialCondition.type` | `process/flow/initial_conditions.py:31` | `"custom"` | Force `value` à être fourni → OK |
| `Modflow6ProcessSpecificConfig.vka` | `solver/modflow6/modflow6_config.py:81` | `1.0` | Isotrope ✓ mais **sans borne** |
| `ConstantThicknessDepthModel.thickness` | `spatial/domain/depth_model_config.py:11` | `50` (m) | OK (aquifère moyen) |
| `SyntheticGridConfig.length_x / ny` | `spatial/geographic/synthetic/config.py:16` | `(100, 1)` nx/ny par défaut | **Non équilibré** — devrait être `(10, 10)` par défaut |
| `SyntheticGridConfig.crs` | idem | `"EPSG:2154"` | **Codé en dur France** |
| `BaseVariableConfig.default_crs` | `data/common/base_config.py:31` | `"EPSG:4326"` | OK (WGS84 global, reprojection au load) |
| `ModflowRuntimeConfig.nwt_headtol` | `solver/modflow_nwt/modflow/nwt_config.py:17` | `1e-4` | OK pour MODFLOW-NWT |
| `ModflowRuntimeConfig.nwt_maxiterout` | idem | `5000` | OK |
| `Modflow6RuntimeConfig.mf6_outer_dvclose` | `solver/modflow6/modflow6_config.py:16` | typiquement `1e-3`-`1e-6` | OK si conforme |

### 11.2 Defaults manquants (problématiques)

| Champ | Impact | Recommandation |
|-------|--------|----------------|
| K, Ss, Sy dans `FieldHomogeneousSectionSchema` | Aucun default → utilisateur doit tout spécifier | **Ne PAS ajouter de default** — laisser obligatoire. Mais valider les bornes physiques. |
| `dt` dans `SimulationTimeConfig.step_value` | Pas de default, obligatoire | OK laisser obligatoire |
| `runoff_coeff`, `losses_mm_day` (mentionnés dans calibration) | Pas de default | OK laisser obligatoire |

### 11.3 Résumé

Les defaults présents sont **globalement hydrogéologiquement raisonnables**. Les champs critiques (K, Sy, Ss) n'ont **à juste titre** pas de default — ils doivent être explicites. **Le problème n'est pas les defaults mais l'absence de bornes de validation** sur ces champs.

---

## 12. Validation — matrice des contraintes physiques

| Contrainte physique | Champ concerné | Fichier | Status |
|---------------------|----------------|---------|:------:|
| K > 0 | Tout `id="k"` dans FieldParamConfig | `spatial/field/core/field_param_config.py` | ❌ |
| 0 < K ≤ 100 m/s | idem | idem | ❌ |
| 0 < Sy < 1 | `id="sy"` | idem | ❌ |
| 0 < Ss ≤ 1e-3 m⁻¹ | `id="ss"` | idem | ❌ |
| 0 < n < 1 (porosité) | `id="n"` / `porosity` | idem | ❌ |
| `dt > 0` | `TMeshConfigModel.lenper` | `solver/utils/temporal/tmesh_config.py` | Partielle (`gt=0` mais pas de min physique ≥ 1 s) |
| `dz > 0` | `VerticalGridConfig.thick` | `solver/utils/mesh/cartesian_grid/sgrid_config.py` | ❌ |
| `nlay ≥ 1` | `VerticalGridConfig.nlay` | idem | ✓ |
| `lay_proportions.sum() == 1` | idem | idem | ✓ |
| `nx, ny ≥ 1` | `PlanarGridConfig`, `SyntheticGridConfig` | idem | ✓ |
| `vka > 0` | `Modflow{6,NWT}ProcessSpecificConfig.vka` | solver configs | ❌ |
| `exdp > 0` | `ModflowProcessSpecificConfig.exdp` | NWT config | ✓ (exemplaire) |
| `mf6_outer_dvclose > 0` | `Modflow6RuntimeConfig` | MF6 config | ✓ (`gt=0`) |
| `start < end` (dates) | `SimulationTimeConfig`, `BaseVariableConfig` | divers | ✓ |
| `xmax > xmin` | `ZoneMeshingDomainBBoxSchema` | gmsh config | ✓ |
| `0 < xi < L` (1D) | `Groundwater1DChronicleSchema` | calibration case | ✓ |
| CRS valide | `DataManagersConfig.project_crs`, `SyntheticGridConfig.crs` | divers | ❌ (chaîne libre) |
| `value XOR forcing` sur BC/wells | `FlowBoundaryConditionConfig`, `FlowWellConfig` | process/flow | ✓ |

**Score** : 9 validations conformes / 17 points critiques = **53 %**. Les contraintes hydrogéologiques centrales (K, Sy, Ss, n, vka) sont toutes absentes.

**Recommandation** : créer `hydromodpy/spatial/field/core/physical_bounds.py` :

```python
_HYDRAULIC_BOUNDS = {
    "k":        ("m/s",  1e-14, 1e2,  "hydraulic conductivity"),
    "kh":       ("m/s",  1e-14, 1e2,  "horizontal hydraulic conductivity"),
    "kv":       ("m/s",  1e-14, 1e2,  "vertical hydraulic conductivity"),
    "sy":       ("-",    1e-4,  0.5,  "specific yield"),
    "ss":       ("1/m",  1e-9,  1e-3, "specific storage"),
    "n":        ("-",    1e-3,  0.6,  "porosity"),
    "n_eff":    ("-",    1e-3,  0.6,  "effective porosity"),
    "vka":      ("-",    1e-3,  1e2,  "vertical anisotropy K_v/K_h"),
}

def validate_hydraulic_value(id: str, unit: str, value: float) -> float:
    entry = _HYDRAULIC_BOUNDS.get(id.lower())
    if entry is None:
        return value
    expected_unit, lo, hi, label = entry
    if not _units_compatible(unit, expected_unit):
        raise ValueError(f"{label} (id={id!r}) expects unit {expected_unit!r}, got {unit!r}")
    if not (lo <= value <= hi):
        raise ValueError(f"{label} (id={id!r}) value {value} outside [{lo}, {hi}]")
    return value
```

À appliquer dans `FieldHomogeneousSectionSchema` et équivalents.

---

## 13. Sérialisation et round-trip TOML

### 13.1 État actuel

Pattern observé dans `*Config.from_toml_section()` / `from_toml()` :
1. `tomllib.load(open(path, "rb"))`
2. Résolution de chemins (`_resolve_section_paths`) **avant** `model_validate` — dépend de connaître la structure.
3. `Model.model_validate(payload)`.
4. Pour l'export : `model.model_dump(mode="python")`.

### 13.2 Problèmes identifiés

| Problème | Impact | Criticité |
|----------|--------|:---------:|
| Pas de `serialize_by_alias=True` global | Si on ajoute un `alias=` pour un champ TOML user-friendly, le dump ne respectera pas l'alias | Moyenne |
| Pas de `populate_by_name=True` global | Les alias ne peuvent pas être lus sous leur nom interne | Moyenne |
| `Path` sérialisé en string absolu par `model_dump(mode="json")` mais en `PosixPath` en mode `python` | Round-trip TOML donne un path absolu, qui peut casser si le TOML est déplacé | Haute |
| Sections vides omises dans `model_dump` | Un user qui sauvegarde et recharge voit ses valeurs par défaut disparaître du TOML | Faible |
| `datetime` sérialisé en str par `tomllib` mais en `datetime.datetime` par Pydantic | Asymétrie sur `SimulationTimeConfig.start_datetime` | Moyenne |

### 13.3 Recommandations

Appliquer dans tous les modèles :

```python
model_config = ConfigDict(
    extra="forbid",
    serialize_by_alias=True,
    populate_by_name=True,
    json_encoders={Path: str},
)
```

Créer un helper `config_to_toml_string(model, base_dir=None) -> str` qui :
- relativise les `Path` par rapport à `base_dir`,
- omet les champs valeur par défaut si demandé (`model_dump(exclude_defaults=True)`).

---

## 14. Mapping TOML ↔ Pydantic

### 14.1 Qualité des noms TOML

Noms TOML analysés sur un échantillon représentatif (`flow`, `domain`, `data.*`, `simulation.time`, `solver`) :

| Section | Noms TOML typiques | Qualité pour un hydrogéologue |
|---------|--------------------|-------------------------------|
| `[flow]` | `flow_regime`, `runtime_backend`, `runtime_tol_abs` | OK |
| `[flow.param]` | `K`, `Sy`, `Ss` (par id, user libre) | OK |
| `[domain]` | `zone_ids`, `supports` | OK |
| `[data]` | `types`, `project_crs`, `inference_mode` | OK |
| `[data.dem]` / `[data.dem.sources]` | `source`, `path`, `mask_path`, `extent` | OK |
| `[solver]` | `solver_engine` | OK |
| `[modflow6.runtime]` | `mf6_outer_dvclose`, `mf6_inner_maximum` | OK (préfixe mf6_ cohérent) |
| `[modflownwt.runtime]` | `nwt_headtol`, `nwt_fluxtol`, `dis_itmuni`, `bas_hnoflo` | **Trop technique** — `dis_itmuni` est un nom de package MODFLOW, pas un terme hydrogéo |
| `[simulation.time]` | `start_datetime`, `step_value`, `substeps_per_period`, `coverage_policy` | OK |
| `[spatial.field_param.k]` | `id`, `kind`, `unit`, `value`, `values_source` | OK |

**Verdict** : majoritairement conformes aux conventions hydrogéo/MODFLOW. Seul bémol : certains champs NWT (`dis_itmuni`, `bas_hnoflo`) exposent le jargon MODFLOW brut — à documenter ou renommer.

### 14.2 Transformations TOML → Pydantic

| Transformation | Emplacement | Verdict |
|----------------|-------------|:-------:|
| Normalisation dates ISO | `BaseVariableConfig._validate_iso_date` | ✓ |
| Résolution chemins relatifs | `_resolve_section_paths` dans `DataManagersConfig.from_toml` | Fragile (générique, sans schéma) |
| Parse d'unités (`"30 day"`, `"10 m"`) | `parse_length_to_m`, `parse_scalar_and_unit` | ✓ (robuste) |
| Normalisation enums `flat_substratum`/`constant_thickness` | `DepthModelConfig` discriminator | ✓ |
| `zone_ids` lowercase + dédup | `DomainConfig._normalize_zone_ids` | ⚠ (dédup silencieuse) |
| Infer `kind` si omis dans zone_meshing_domain | `validate_zone_meshing_domain_model` | ✓ (user-friendly) |

---

## 15. Duplication de code — inventaire exhaustif

| # | Emplacement A | Emplacement B | Nature | Lignes refactorisables |
|---|---------------|----------------|--------|-----------------------:|
| 1 | `data/variables/etp/config.py` | `data/variables/{humidity,runoff,soil_moisture,temperature,wind}/config.py` | 95 % copie | ~400 |
| 2 | idem | `data/variables/{precipitation,radiation}/config.py` (+ `components`) | 85 % copie | ~130 |
| 3 | idem | `data/variables/{hydrometry,intermittency,piezometry}/config.py` (+ `product`) | 75 % copie | ~270 |
| 4 | `process/flow/boundary_conditions.py:78-180` (FlowBoundaryForcing*) | `process/flow/sinks_sources.py:345-444` (FlowWellForcing*) | 90 % copie | ~100 |
| 5 | `solver/modflow6/modflow6_config.py` (`Modflow6SpecifParams`) | `solver/modflow_nwt/modflow/nwt_config.py` (`ModflowSpecifParams`) | Dataclasses miroir des Pydantic Configs | ~30 chacun = ~60 |
| 6 | `solver/utils/mesh/cartesian_grid/sgrid_config.py` (SGridConfig) | `spatial/mesh/config.py` (MeshCatchmentConfig) | Duplication conceptuelle grille cartésienne | Non quantifié, ≥ 100 |
| 7 | `{solver,analysis,...}/*_config.py` — pattern `from_toml` / `from_mapping` | Presque tous les fichiers | 3 variantes de resolve_path (`_resolve_path`, `resolve_path`, `resolve_declared_path`) | ~50 |

**Total refactorisable** : **~1 100 lignes**.

---

## 16. Code mort, abstractions inutiles, verbosité

| Élément | Localisation | Verdict |
|---------|--------------|:-------:|
| `FlowRechargeConfig.heterogeneous_source: Any` | `process/flow/sinks_sources.py:445` | À vérifier : jamais lu dans les consommateurs ? Suppression probable. |
| Dataclasses `Modflow{6,}SpecifParams` | `solver/modflow*/` | Redondant — remplacer par `model.model_dump()` ou `model.model_copy(update=...)`. |
| Suffixe `…Schema` | `solver/utils/mesh/gmsh_grid/zone_meshing/*`, `spatial/mesh/config.py`, `spatial/field/core/field_param_config.py` | Reliquat Pydantic v1 (où `Schema()` remplaçait `Field()`). Aujourd'hui purement décoratif. Renommer en `…Config`. |
| `TransportInitialConditions.payload: dict[str, Any]` | `process/transport/transport.py:28` | Typage à définir ou classe à supprimer si `TransportConfig.ic` n'est jamais consommé. |
| `generate_toml._placeholder()` ~100 lignes | `core/config/generate_toml.py` | À découper en fonctions spécialisées par type. |
| `FlowConfig.from_toml_section` 130 lignes | `process/flow/flow_config.py` | À migrer dans `@model_validator(mode="before")` + helpers. |
| Fichiers `case_config.py` (gmsh, mesh, temporal) sans classe Pydantic | Divers | Soit supprimer les helpers dict-based, soit leur adjoindre une Pydantic de validation. |
| `ReservoirChronicleSchema`, `BrutsaertChronicleSchema`, `Groundwater1DChronicleSchema` | `analysis/calibration/cases/*` | OK, pas de duplication réelle, mais **aucune factorisation** des champs de chronologie commune (`n_days`, `dt_days`, `obs_noise_std_m`). |

---

## 17. Tableau récapitulatif final par fichier

| Fichier | Classes Pydantic | Verdict | Priorité action |
|---------|:----------------:|:-------:|:---------------:|
| `core/config/hydromodpy_config.py` | `HydroModPyConfig` | À renforcer (pas de cross-section) | P1 |
| `core/workspace/config.py` | `WorkspaceConfig` | Bien | — |
| `core/config/streamlit_config.py` / `generate_toml.py` | aucune | Outils OK | — |
| `process/base/process_spatial_config.py` | `ProcessSpatialConfig` | Mal typé | P1 |
| `process/base/initial_conditions.py` | `InitialCondition` | Trop générique | P2 |
| `process/base/boundary_conditions.py` | `BoundaryCondition` | À renforcer (Literal, value) | P2 |
| `process/base/sinks_sources.py` | `SinkSource` | À renforcer | P2 |
| `process/flow/flow_config.py` | `FlowConfig` | Bien mais verbeux ; héritage inutile | P2 |
| `process/flow/initial_conditions.py` | `FlowInitialCondition`, `FlowInitialConditions` | Correct | — |
| `process/flow/boundary_conditions.py` | `FlowBoundaryForcing*` + `FlowBoundaryConditionConfig` | Excellent ; à discrétiser (Union[…, discriminator]) | P3 |
| `process/flow/sinks_sources.py` | `FlowWell*`, `FlowRecharge*`, `FlowSinksSourcesConfig` | FlowRecharge problématique (`values: Any`) | P1 |
| `process/transport/transport_config.py` + `transport.py` | 6 classes | Acceptable prototype | P3 |
| `solver/base/solver_config.py` | `SolverConfig` | Bien | — |
| `solver/modflow6/modflow6_config.py` | 3 classes + dataclass | vka sans borne ; dataclass redondante | P2 |
| `solver/modflow_nwt/modflow/nwt_config.py` | 3 classes + dataclass | Partiellement validé | P2 |
| `solver/utils/temporal/tmesh_config.py` | `TMeshConfigModel` | Bien | — |
| `solver/utils/temporal/cases/run_tmesh_config.py` | `TMeshCaseScenarioConfig`, `TMeshCasesConfig` | Héritage fragile, dédup silencieuse | P2 |
| `solver/utils/mesh/cartesian_grid/sgrid_config.py` | 4 classes | **Excellent** (référence) | — |
| `solver/utils/mesh/cartesian_grid/examples/discretization/run_demo_config.py` | `SGridFieldParamDiscretizationConfig` | Couplage faible (`dict[str, Any]`) | P2 |
| `solver/utils/mesh/gmsh_grid/zone_meshing/config.py` | 6 classes | **Excellent** | — |
| `solver/utils/mesh/gmsh_grid/zone_meshing/_domain_schema.py` | 6 classes (discriminated) | Bien | — |
| `solver/utils/mesh/gmsh_grid/cases/reference_*/case_config.py` | aucune | Contrats manquants | P3 |
| `spatial/domain/domain_config.py` | `DomainConfig` | Bien (dédup silencieuse à surveiller) | P3 |
| `spatial/domain/spatial_support_config.py` | 5 classes | **Excellent** | — |
| `spatial/domain/depth_model_config.py` | 2 classes + alias | Correct | — |
| `spatial/field/core/field_param_config.py` | 6 classes | Incomplet (physique) | **P0** |
| `spatial/geographic/geographic_config.py` | `RiverNetworkConfig`, `GeographicConfig` | Acceptable | P3 |
| `spatial/geographic/synthetic/config.py` | 3 classes | Bien mais CRS codé en dur | P3 |
| `spatial/mesh/config.py` | ≈10 classes | Trop imbriqué | P2 |
| `data/common/base_config.py` | `BaseVariableConfig` | Bien | — |
| `data/data_managers_config.py` | `DataManagersConfig` | Orchestrateur fragile (circular imports) | P2 |
| `data/variables/dem/config.py` | `DemSourceConfig`, `DemConfig` | Hors pattern (pas de dates) | P3 |
| `data/variables/geology/config.py` | 5 classes | Justifié (dual use) | — |
| `data/variables/{etp,humidity,runoff,soil_moisture,temperature,wind}/config.py` | 6×2 classes quasi identiques | **Dupliqué** | **P0** |
| `data/variables/{precipitation,radiation}/config.py` | 2×2 classes | **Dupliqué + components** | P1 |
| `data/variables/{hydrometry,intermittency,piezometry}/config.py` | 3×2 classes | **Dupliqué + product** | P1 |
| `data/variables/{oceanic,water_quality,hydrography}/config.py` | 3×2 classes | Spécifique, OK | — |
| `data/variables/recharge/config.py` | 2 classes | Dupliqué + synthétique | P1 |
| `analysis/calibration/core/engine_config.py` | 4 classes | **Excellent** | — |
| `analysis/calibration/core/methods_config.py` | ~6 classes | **Excellent** | — |
| `analysis/calibration/engine/config.py` | 6 classes | **Excellent** | — |
| `analysis/calibration/cases/*/case_config.py` | 3×1 classes | **Exemplaire** | — |
| `analysis/comparison/config.py` | 5 classes | Excellent | — |
| `analysis/display/display_config.py` | 4 classes | Très bon | — |
| `analysis/display/report/overview_config.py` | 2 classes | Bon | — |
| `analysis/postprocess/*` (6 fichiers) | 6 classes | Bon (presets) | — |
| `analysis/capability_gallery.py` | `CapabilityGalleryConfig` | Bon | — |
| `simulation/planning/config.py` | 3 classes | **Excellent** (parsing inline) | — |
| `results/config.py` | 5 classes | Bien | — |

---

## 18. Plan d'action consolidé

### Phase P0 (urgent, impact correctness)

1. **Validateurs hydrogéologiques** — créer `hydromodpy/spatial/field/core/physical_bounds.py` avec la table `_HYDRAULIC_BOUNDS` (K, Sy, Ss, n, vka, kh, kv). Appliquer via `@model_validator(mode="after")` dans `FieldHomogeneousSectionSchema` et `FieldHeterogeneousSectionSchema`. Appliquer `vka` dans `Modflow{6,}ProcessSpecificConfig`. Tests unitaires dédiés.
2. **Refactor `data/variables/`** — créer `data/variables/common/timeseries_source.py:TimeseriesSourceConfig`. Migrer les 6 fichiers quasi-identiques (etp, humidity, runoff, soil_moisture, temperature, wind). **Gain : ~400 lignes supprimées**.

### Phase P1 (structure et typage)

3. Typer `FlowRechargeConfig.values` en discriminated union (constant/list/dict/csv-ref) au lieu d'`Any`. Supprimer `heterogeneous_source` si code mort.
4. Typer `BoundaryCondition.type` et `SinkSource.type` en `Literal`.
5. Typer `TransportInitialConditions.payload` ou supprimer la classe.
6. Migrer `ProcessSpatialConfig` vers `Generic[IC, BC, SS]` ou le supprimer.
7. **Agrégateur** : migrer `HydroModPyConfig.from_toml` vers `@model_validator(mode="before")` ; ajouter `@model_validator(mode="after")` de cohérence cross-section.

### Phase P2 (réduction duplication + robustesse)

8. Refactor Forcing → `process/base/forcing.py` avec discriminated union.
9. Refactor `data/variables/{precipitation,radiation,hydrometry,intermittency,piezometry,recharge}` sur `TimeseriesSourceConfig` + mixins. **Gain : ~400 lignes supplémentaires**.
10. Remplacer `TMeshCaseScenarioConfig ← TMeshConfigModel` par composition.
11. Décentraliser `DataManagersConfig` via registre `DATA_TYPE_MODELS` pour éliminer `model_rebuild()`.
12. Supprimer les dataclass `Modflow{6,}SpecifParams` au profit de `model_dump(mode="python")`.
13. Dédup des `zone_ids` / scenario `id` : lever `ValueError` au lieu de dédupliquer silencieusement.
14. Unifier les 3 helpers `resolve_path` en un seul module `core/config/path_resolution.py`.

### Phase P3 (polish et finalisation)

15. Renommer suffixes `…Schema` en `…Config` (reliquat v1).
16. Ajouter `serialize_by_alias=True, populate_by_name=True` globalement (hérité d'un `BaseConfig` projet).
17. Unifier `sgrid_config.py` et `spatial/mesh/config.py` en une racine discriminée.
18. Ajouter contrats Pydantic pour les `case_config.py` qui n'en ont pas (gmsh reference cases).
19. Ajouter `schema_version` et script de migration sur les configs racine stables.

---

## 19. Conclusion

HydroModPy utilise **correctement Pydantic v2** au niveau syntaxe (validators v2, `ConfigDict(extra="forbid")`, `Annotated`/`ParamLevel`, discriminated unions là où c'est utile). **Aucun reste de Pydantic v1** n'a été détecté.

Les deux points noirs sont :

1. **L'absence de validation hydrogéologique physique** sur les paramètres centraux (K, Sy, Ss, n, vka). C'est étonnant compte tenu de la qualité exemplaire de la validation dans `analysis/calibration/cases/` — le savoir-faire existe mais n'a pas été propagé aux champs centraux. Un utilisateur peut actuellement configurer K = -1 m/s et le code validera.

2. **La duplication massive dans `data/variables/`** : ~50 % du code de cette couche est du copier-coller. Une factorisation simple (`TimeseriesSourceConfig` + mixins) supprimerait ≈800 lignes et rendrait l'ajout d'une nouvelle variable de 70 lignes à 5-10 lignes.

Les forces principales sont la couche `analysis/calibration/` (validation exemplaire), les modèles `SGridConfig` et `ZoneMeshingSettings` (références du projet), et l'excellente intégration de `ParamLevel` pour la traçabilité utilisateur/dev/expert.

**Verdict final : 6/10** — Base saine mais incomplète. Les corrections P0 suffisent à passer à 7.5/10, les corrections P1+P2 à 8.5/10. Aucun des points identifiés n'exige de réécriture profonde : ce sont des interventions ciblées à effort modéré.
