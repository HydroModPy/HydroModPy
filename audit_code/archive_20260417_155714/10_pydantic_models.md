# Audit critique des modèles Pydantic — HydroModPy

**Date** : 2026-04-17
**Périmètre** : tous les modèles Pydantic de `hydromodpy/` (66 fichiers `*_config.py` + 20 autres fichiers contenant des `BaseModel`)
**Approche** : exploration parallèle en 4 branches (core/spatial, process/solver, data/variables, analysis/calibration/display) + lecture directe des fichiers transverses (agrégateur, base classes, résolution de chemins).

---

## 0. Synthèse executive (verdict global)

| Axe | Note | Justification |
|---|---|---|
| Conformité Pydantic v2 | **Bonne** | `BaseModel` partout, `field_validator` + `model_validator` corrects, `ConfigDict(extra="forbid")` quasi-universel. Aucun résidu `class Config:` ni `@validator` v1 détecté. |
| Profondeur d'héritage | **À améliorer** | `FlowConfig(ProcessSpatialConfig)` + `TransportConfig(ProcessSpatialConfig)` : héritage *abusif* avec `exclude=True` sur quasiment tous les champs hérités. Le reste du code privilégie à juste titre la composition. |
| Précision des types | **Acceptable** | Bonne utilisation de `Literal` pour les énumérations courtes, mais `object`, `Any`, `dict[str, object]` parsemés dans `process/base/` et `FlowRechargeConfig`. |
| Defaults physiques | **Problématique** | Plusieurs defaults dangereux : `evt_extinction_depth=1.0 m`, `disp_long=0.0`, `recharge.units="mm/day"` (non-SI), `nwt_headtol=1e-4` (acceptable) mais `nwt_fluxtol=500.0` sans unité. |
| Validation physique | **Insuffisante** | Aucun `K > 0`, aucun `0 < Sy < 1`, aucun `0 < porosity < 1` dans `field_param_config.py` ni dans les defaults des solveurs. Les validateurs vérifient la forme, pas la physique. |
| Discriminated unions | **Partiellement utilisée** | Excellente sur `DepthModelConfig` et `DomainSupportConfig`. **Absente** sur `FlowBoundaryForcingConfig` (`constant`/`csv`), `FlowWellForcingConfig`, toutes les `*SourceConfig` data/variables. |
| Duplication | **Critique** | ~1200 lignes dupliquées dans `data/variables/*/config.py` (17 fichiers jumeaux), ~80% chevauchement entre `flow_timeseries_config` vs `transport_timeseries_config` et `flow_netcdf_config` vs `transport_netcdf_config`. |
| Round-trip TOML ⇄ Pydantic | **Incomplet** | La résolution de `Path` réécrit `Path → str` avant persistance, le chargement est asymétrique selon la provenance (`[data]` a son chemin dédié), et `from_snapshot` ne refait pas de résolution. |

**Verdict d'ensemble** : l'architecture Pydantic est **cohérente et moderne** (Pydantic v2, extra=forbid, ParamLevel via `Annotated`), mais l'exécution est **irrégulière** : certains sous-systèmes (domain/depth, zone_meshing, simulation/planning) sont d'excellente facture, alors que d'autres (process/flow, data/variables, postprocess) souffrent de duplication massive, de validateurs monstrueux (`FlowConfig` : 14 `field_validator` + 2 `model_validator`, normalisation de 100+ lignes) et de types génériques qui contournent les bénéfices du typage Pydantic.

---

## 1. Inventaire consolidé (tableau synthétique)

### 1.1 Core & configuration agrégée

| Classe | Fichier | Ligne | Parent | Champs | Config | Validators | Verdict |
|---|---|---|---|---|---|---|---|
| `HydroModPyConfig` | `core/config/hydromodpy_config.py` | 62 | `BaseModel` | 13 | `arbitrary_types_allowed=True` | `classmethod from_toml`, `from_snapshot` | **À améliorer** — manque `extra="forbid"` au niveau racine |
| `WorkspaceConfig` | `core/workspace/config.py` | 9 | `BaseModel` | 3 | `extra="forbid"` | `model_validator(after)` découverte workspace_root | **Bien conçu** |
| `StreamlitConfig` | `core/config/streamlit_config.py` | — | `BaseModel` | — | `extra="forbid"` | — | Hors périmètre audit principal |

### 1.2 Spatial (géographic, domain, mesh, field)

| Classe | Fichier | Parent | Champs | Verdict |
|---|---|---|---|---|
| `RiverNetworkConfig` | `spatial/geographic/geographic_config.py:13` | `BaseModel` | 9 | **Bien conçu** — validation croisée `threshold_mode`/`threshold_area_km2`/`threshold_cells` rigoureuse |
| `GeographicConfig` | `spatial/geographic/geographic_config.py:138` | `BaseModel` | 14 | **Bien conçu** — `VisibleWhen` + `model_validator` robuste |
| `SyntheticGridConfig` / `SyntheticTopographyConfig` / `SyntheticGeographicConfig` | `spatial/geographic/synthetic/config.py` | `BaseModel` | 8/8/3 | **Bien conçu** |
| `DomainConfig` | `spatial/domain/domain_config.py:12` | `BaseModel` | 3 | **Bien conçu** — normalisation zone_ids + `DomainSupportConfig` en union discriminée |
| `ConstantThicknessDepthModel` / `FlatSubstratumDepthModel` | `spatial/domain/depth_model_config.py` | `BaseModel` | 2 / 2 | **Exemplaire** — `DepthModelConfig = Annotated[..., Field(discriminator="type")]` |
| `DomainSupportBaseConfig` + 4 héritiers | `spatial/domain/spatial_support_config.py` | `BaseModel` + discriminator | 1→7 | **Exemplaire** — discriminator="provider" sur `generated_bands` / `generated_rings` / `catchment_zones` / `geology` |
| `MeshCatchmentConfigSchema` | `spatial/mesh/config.py` | `BaseModel` | — | Bien structuré |
| `FieldBaseSectionSchema` | `spatial/field/core/field_param_config.py:72` | `BaseModel` | 3 | **À améliorer** — `extra="allow"` contrairement au reste (legacy) |
| `FieldHomogeneousSectionSchema` | `.../field_param_config.py:131` | `BaseModel` | 1 | Acceptable mais `value: object\|None` trop générique |
| `FieldHeterogeneousSectionSchema` | `.../field_param_config.py:162` | `BaseModel` | 5 | **À améliorer** — `values_source` str + `values` dict[str, object] : redondance avec discriminator manquant |
| `FieldVerticalProfileSectionSchema` | `.../field_param_config.py:321` | `BaseModel` | 6 | **Bien conçu** — validation de monotonie des profondeurs rigoureuse |
| `FieldParamConfig` | `.../field_param_config.py:473` | `BaseModel` | 4 sous-sections | **À améliorer** — `extra="allow"` (legacy) ; rejet explicite de `[field_common]` via `model_validator(before)` |
| `ResolvedFieldParamSchema` | `.../field_param_config.py:512` | `BaseModel` | 10 | Acceptable mais duplique les champs de 3 sections précédentes. |

### 1.3 Process & solver

| Classe | Fichier | Parent | Champs | Verdict |
|---|---|---|---|---|
| `BoundaryCondition` | `process/base/boundary_conditions.py` | `BaseModel` | 6 | **À améliorer** — `type: str` au lieu de `Literal["dirichlet", "neumann", "cauchy"]` |
| `InitialCondition` | `process/base/initial_conditions.py` | `BaseModel` | 4 | **À améliorer** — `value: object\|None` |
| `SinkSource` | `process/base/sinks_sources.py` | `BaseModel` | 5 | **À améliorer** — pas de validation sur le signe |
| `ProcessSpatialConfig` | `process/base/process_spatial_config.py` | `BaseModel` | 7 | **À simplifier** — tout est `dict[str, object]` / `object \| None` |
| `FlowInitialCondition` | `process/flow/initial_conditions.py` | `BaseInitialCondition` | 3 | Bien |
| `FlowInitialConditions` | `process/flow/initial_conditions.py` | `BaseModel` | 1 | Bien (ClassVar `toml_flatten`) |
| `FlowBoundaryForcingConstantConfig` / `FlowBoundaryForcingCsvConfig` / `FlowBoundaryForcingConfig` | `process/flow/boundary_conditions.py` | `BaseModel` | 1 / 6 / 9 | **À refactorer** — union implicite `mode: Literal["constant", "csv"]` ; devrait être discriminated union |
| `FlowBoundaryConditionConfig` | `process/flow/boundary_conditions.py:181` | `BaseModel` | 9 | **À refactorer** — 16 lignes de validation croisée, `application_domain: str\|None` au lieu de `Literal` |
| `FlowWellConfig` | `process/flow/sinks_sources.py:58` | `BaseModel` | 11 | **À simplifier** — `model_validator` de 30+ lignes pour `cell` vs `location_mode` vs `x/y` vs `x_rel/y_rel`. Un pattern discriminated union serait plus clair. |
| `FlowWellForcingConfig` | `process/flow/sinks_sources.py` | `BaseModel` | 9 | Même problème que `FlowBoundaryForcingConfig` |
| `FlowRechargeConfig` | `process/flow/sinks_sources.py:445` | `BaseModel` | 7 | **Problématique** — `values: Any`, `heterogeneous_source: Any`, `units="mm/day"` (défaut non-SI) |
| `FlowSinksSourcesConfig` | `process/flow/sinks_sources.py:594` | `BaseModel` | 2 | Bien |
| `FlowConfig` | `process/flow/flow_config.py:51` | `ProcessSpatialConfig` | 14 | **À refactorer** — héritage + override multiples, 14 `field_validator` + 2 `model_validator`, `from_toml_section` de 100+ lignes |
| `ModpathParametersConfig` / `ConcentrationTransportParametersConfig` | `process/transport/transport_config.py` | `BaseModel` | 6 / 10 | Acceptable mais `disp_long=0.0`, `diffu_coeff=0.0` sont physiquement non-informatifs |
| `TransportConfig` | `process/transport/transport_config.py:133` | `ProcessSpatialConfig` | 6 (avec exclude=True) | **Design confus** — hérite puis exclut : pourquoi hériter ? |
| `SolverConfig` | `solver/base/solver_config.py:13` | `BaseModel` | 1 | **Exemplaire** — `SolverEngine` enum propre |
| `ModflowRuntimeConfig` | `solver/modflow_nwt/modflow/nwt_config.py:17` | `BaseModel` | 27 | **À améliorer** — `nwt_options="COMPLEX"` est `str` au lieu de `Literal` ; aucun validateur malgré des magic numbers (`nwt_thickfact=1e-5`, `bas_hnoflo=-9999.0`) |
| `ModflowProcessSpecificConfig` | `solver/modflow_nwt/modflow/nwt_config.py:140` | `BaseModel` | 2 | **Défaut douteux** — `exdp=1.0` m d'extinction ET |
| `Modflow6RuntimeConfig` | `solver/modflow6/modflow6_config.py:16` | `BaseModel` | 12 | **À améliorer** — `mf6_ims_complexity="COMPLEX"` est `str` au lieu de `Literal["SIMPLE","MODERATE","COMPLEX"]` |
| `Modflow6ProcessSpecificConfig` | `solver/modflow6/modflow6_config.py:81` | `BaseModel` | 2 | Même problème que NWT (`evt_extinction_depth=1.0 m`) |
| `TMeshConfigModel` | `solver/utils/temporal/tmesh_config.py:17` | `BaseModel` | 14 | **Bien conçu** — validation robuste |
| `TMeshCaseScenarioConfig` / `TMeshCasesConfig` | `solver/utils/temporal/cases/run_tmesh_config.py` | `TMeshConfigModel` / `BaseModel` | 2 / 3 | Bien |
| `VerticalGridConfig` / `PlanarGridConfig` / `SolverSGridConfig` / `SGridConfig` | `solver/utils/mesh/cartesian_grid/sgrid_config.py` | `BaseModel` | 5 / 4 / 2 / 17 | **Bien conçu** |
| `SGridConfig` (`case_config.py` GMSH) | `.../gmsh_grid/cases/*/case_config.py` | `BaseModel` | ~15 | Acceptable |
| `ZoneMeshing*` (7 classes) | `solver/utils/mesh/gmsh_grid/zone_meshing/config.py` | `BaseModel` | — | **Bien conçu** — validation croisée exhaustive (45+ lignes) |
| `ZoneMeshingDomain*Schema` (6 classes) | `.../zone_meshing/_domain_schema.py` | `BaseModel` | — | **Exemplaire** — discriminated union manuelle par `kind` (aurait pu utiliser `Field(discriminator="kind")` natif) |

### 1.4 Simulation (planning)

| Classe | Fichier | Champs | Verdict |
|---|---|---|---|
| `SimulationTimeConfig` | `simulation/planning/config.py:86` | 5 | **Bien conçu** |
| `SimulationProcessConfig` | `simulation/planning/config.py:164` | 3 | Bien — `process: list[SimulationProcessConfig]` avec contrainte d'unicité |
| `SimulationConfig` | `simulation/planning/config.py:209` | 5 | Bien |

### 1.5 Data (managers + 17 variables)

| Classe | Fichier | Parent | Verdict |
|---|---|---|---|
| `BaseVariableConfig` | `data/common/base_config.py:31` | `BaseModel` | **Bien conçu** — factorise `date_start`/`date_end` + ISO validation + `from_toml` |
| `DataManagersConfig` | `data/data_managers_config.py:51` | `BaseModel` | **À améliorer** — 20 champs optionnels typés via forward-ref `"XxxConfig \| None"`, nécessitant `_rebuild_forward_refs()` manuel. Design fragile. |
| `WindConfig` / `TemperatureConfig` / `SoilMoistureConfig` / `RunoffConfig` / `HumidityConfig` / `EtpConfig` + `*SourceConfig` | 12 fichiers | `BaseVariableConfig` / `BaseModel` | **Duplication critique** — 9 paires quasi-identiques avec `source: Literal["custom", "sim2"]` |
| `RadiationConfig` + `PrecipitationConfig` (avec `components`) | 2 fichiers | `BaseVariableConfig` | Duplication massive + un champ additionnel |
| `RechargeConfig` / `RechargeSourceConfig` | `data/variables/recharge/config.py` | `BaseVariableConfig` | Seule à avoir `source="synthetic"` avec 8 champs de forçage analytique |
| `PiezometryConfig` / `HydrometryConfig` / `WaterQualityConfig` / `IntermittencyConfig` (provider hubeau) | 4 fichiers | `BaseVariableConfig` | Duplication massive (~90%) + API-specific fields |
| `OceanicConfig` | `data/variables/oceanic/config.py` | `BaseVariableConfig` | `source: Literal["custom","shom","constant"]` — 3 providers |
| `HydrographyConfig` / `GeologyConfig` / `DemConfig` | 3 fichiers | **`BaseModel` direct, pas `BaseVariableConfig`** | **Incohérence** — pas de `date_start`/`date_end` ; pourquoi ? Si c'est parce que statiques, une `BaseStaticDataConfig` serait plus propre. |

### 1.6 Analysis (calibration, display, postprocess, comparison, results)

| Classe | Fichier | Verdict |
|---|---|---|
| `_MethodKwargsBase` + 6 sous-classes (`GridSearchKwargs`, `RandomSearchKwargs`, `NelderMeadKwargs`, `SimplexKwargs`, `GpMappingKwargs`, `DaMhGpKwargs`) | `analysis/calibration/core/methods_config.py` | **Bien conçu** — `METHOD_KWARGS_MODELS` dict ligne 333 aurait pu être une `Annotated[Union[...], Field(discriminator="type")]` mais le pattern actuel fonctionne. |
| `CalibrationSectionSchema` / `OutputSectionSchema` / `ObjectiveSectionSchema` / `CalibrationTomlSchema` | `analysis/calibration/core/engine_config.py` | Bien |
| `ModelCalibrationParameterSchema` / `ModelCalibrationOutputSchema` / `ModelCalibrationObjectiveBlockSchema` / `ModelCalibrationObjectiveMappingSchema` / `ModelCalibrationSectionSchema` / `ModelCalibrationConfig` | `analysis/calibration/engine/config.py` | **À simplifier** — 9 classes + `arbitrary_types_allowed=True` ; chevauchement avec `core/engine_config.py` (deux hiérarchies de calibration parallèles) |
| `Groundwater1DChronicleSchema` / `BrutsaertChronicleSchema` / `ReservoirChronicleSchema` | `analysis/calibration/cases/*/case_config.py` | **Bien** pour groundwater_1d et reservoir ; **BrutsaertChronicleSchema manque la validation sur `p`** |
| `CapabilityGalleryConfig` | `analysis/capability_gallery.py` | **À améliorer** — 0 validateur, `_safe_asset_name` défini ligne 53 mais non utilisé |
| `FlowDisplayConfig` / `ParticlesDisplayConfig` / `TransportDisplayConfig` / `DisplayConfig` | `analysis/display/display_config.py` | Bien structuré, 0 validateur mais champs booléens n'en nécessitent pas |
| `OverviewPanelsConfig` / `OverviewSection` | `analysis/display/report/overview_config.py` | **À améliorer** — `date_start/date_end: str\|None` sans validation ISO (contrairement à `BaseVariableConfig`) |
| `FlowPostprocessConfig` / `TransportPostprocessConfig` / `PostprocessConfig` | `analysis/postprocess/postprocess_config.py` | Bien |
| `FlowTimeseriesPostprocessConfig` / `TransportTimeseriesPostprocessConfig` / `FlowNetcdfPostprocessConfig` / `TransportNetcdfPostprocessConfig` | `analysis/postprocess/*/` | **Duplication critique** — ~80-90% de recouvrement entre flow et transport |
| `IntermittencyPostprocessConfig` | `analysis/postprocess/flow/intermittency_config.py` | Simple — pas de validation "au moins un True" |
| `MethodComparisonVariantSchema` / `MethodComparisonObservableSchema` / `MethodComparisonSectionSchema` / `MethodComparisonFineRasterSchema` / `MethodComparisonConfig` | `analysis/comparison/config.py` | Bien — validation croisée variante/observable robuste |
| `DerivedConfig` / `ExportVariablesConfig` / `ExportConfig` / `BudgetConfig` / `ResultsConfig` | `results/config.py` | Bien |

**Total estimé** : ~150 classes Pydantic réparties sur ~66 fichiers `*_config.py` + ~20 autres fichiers.

---

## 2. Critique du design Pydantic v2

### 2.1 Ce qui est bien fait

| Pratique | Preuve | Verdict |
|---|---|---|
| Aucun résidu Pydantic v1 (`class Config:`, `@validator`, `.json()`) | Aucune occurrence détectée via `grep` | **Conforme** |
| `ConfigDict(extra="forbid")` massif | ~95% des `BaseModel` | **Bien** |
| `model_validator(mode="after"/"before")` correctement paramétré | `WorkspaceConfig._resolve_workspace_root`, `TMeshConfigModel._validate_cross_fields`, `ZoneMeshingSettings._validate_cross_constraints` | **Conforme** |
| `Annotated[Type, ParamLevel(...)]` pour métadonnées UX | Utilisation systématique dans `core`, `spatial`, `process`, `data` | **Innovation intéressante** — équivalent des `json_schema_extra` mais typé |
| `Literal` pour énumérations courtes | `catch_def: Literal["dem","txt","from_outlet_coord","from_polyg_shp"]`, `flow_regime: Literal["steady","transient"]` | **Conforme** |
| `TypeAlias` + `Annotated[..., Field(discriminator=...)]` pour unions propres | `DepthModelConfig`, `DomainSupportConfig` | **Exemplaire** — c'est *la* manière idiomatique Pydantic v2 |
| `classmethod from_toml()` + résolution de paths relatives | `BaseVariableConfig.from_toml`, `HydroModPyConfig.from_toml` | Bien |
| `ClassVar[bool] toml_flatten` pour contrôler la sérialisation | `FlowInitialConditions` | Astucieux |

### 2.2 Ce qui n'est pas idiomatique (patterns à corriger)

| Anti-pattern | Fichier | Correctif |
|---|---|---|
| **`type: str` au lieu de `Literal`** | `process/base/boundary_conditions.py:BoundaryCondition.type`, `ModpathParametersConfig.zone_partic`, `ModflowRuntimeConfig.nwt_options`, `Modflow6RuntimeConfig.mf6_ims_complexity`, `FieldBaseSectionSchema.kind` | Remplacer par `Literal["..."]` ou enum |
| **`object` / `Any` / `dict[str, object]`** | `ProcessSpatialConfig.param` (dict[str, object]), `FlowRechargeConfig.values: Any`, `FlowInitialCondition.value: object\|None`, `InitialCondition.value: object\|None`, `FieldHomogeneousSectionSchema.value: object\|None` | Typer précisément (`float \| str` si unité optionnelle, ou discriminated union) |
| **`dict[str, XxxConfig]` pour entités nommées** | `DomainConfig.supports`, `FlowSinksSourcesConfig.wells`, `FlowConfig.bc`, `FlowConfig.param` | Acceptable pour `supports` (clé utilisateur) ; pour `bc`/`param` ce serait plus propre de typer `dict[str, FlowBoundaryConditionConfig]` (c'est le cas pour `supports` mais pas pour `bc`) |
| **`extra="allow"` pour la rétrocompatibilité** | `FieldBaseSectionSchema` (ligne 82), `FieldParamConfig` (ligne 482) | Migrer vers `extra="forbid"` après une release de dépréciation |
| **Union implicite sans discriminator** | `FlowBoundaryForcingConfig` (mode=constant/csv avec tous les champs présents), `FlowWellForcingConfig`, toutes les `*SourceConfig` de `data/variables/` | Introduire `Annotated[Union[...], Field(discriminator="source"/"mode")]` |
| **`str` pour dates au lieu de `datetime`/`date`** | `BaseVariableConfig.date_start/date_end`, `OverviewSection.date_start/date_end`, `Groundwater1DChronicleSchema.start_year` | Pydantic valide nativement `datetime.date`/`datetime.datetime`. Le code actuel fait `datetime.fromisoformat(v)` à la main dans un validator. |
| **`str` pour chemins après résolution** | `_resolve_section_paths` dans `hydromodpy_config.py:349` et `data_managers_config.py:431` écrit `data[field_name] = str(p)` après résolution | Conserver `Path` après résolution ; le serializer TOML sait sérialiser `Path` en str |
| **`arbitrary_types_allowed=True` sans nécessité claire** | `HydroModPyConfig` (pour quoi exactement ?), `ModelCalibrationConfig`, `MethodComparisonConfig` | Restreindre à l'endroit où un type non-Pydantic est réellement utilisé |
| **Absence de `extra="forbid"` sur `HydroModPyConfig`** | `core/config/hydromodpy_config.py:73` | Ajouter — c'est le point d'entrée, les fautes de frappe au niveau racine sont silencieusement ignorées |
| **`model_validator(mode="before")` avec `dict` brut** | `FieldParamConfig._reject_field_common` | Acceptable mais casse l'assistance IDE ; préférer `extra="forbid"` plus un rejet explicite via validator |

### 2.3 Pydantic v2 idiomatique *ignoré* par le code

- **`Field(discriminator=...)`** : utilisé correctement pour `DepthModelConfig` et `DomainSupportConfig`, mais *absent* de toutes les unions mode/source pourtant parfaitement adaptées.
- **`StringConstraints` / `conint` / `confloat`** : le code utilise `ge`/`gt`/`le`/`lt` dans `Field(...)` directement, ce qui est correct, mais certains validators font du `if value <= 0: raise` à la main là où `Field(gt=0)` suffirait (ex : `TMeshConfigModel._validate_nper`).
- **`@computed_field`** : jamais utilisé. Des propriétés comme `WorkspaceConfig.catch_name`, `workspace.data_path`, `workspace.catalog_path` sont de simples `@property` non exposées dans le schéma JSON ni la sérialisation. Si ces champs doivent être persistés (ce qui semble être le cas pour `catch_name` dans le provenance tracking), `@computed_field` serait plus propre.
- **`model_serializer` / `field_serializer`** : jamais utilisé. Pourtant utile pour sérialiser `Path` en chaîne sans passer par `_resolve_section_paths`.

---

## 3. Arbre d'héritage

### 3.1 Vue d'ensemble

```
BaseModel (Pydantic)
├── HydroModPyConfig                           (agrégateur racine)
├── WorkspaceConfig
├── GeographicConfig
├── SyntheticGeographicConfig
│   ├── SyntheticGridConfig (composition)
│   └── SyntheticTopographyConfig (composition)
├── RiverNetworkConfig
├── DomainConfig
├── DomainSupportBaseConfig                    (union discriminée "provider")
│   ├── GeneratedBandsSupportConfig
│   ├── GeneratedRingsSupportConfig
│   ├── CatchmentZonesSupportConfig
│   └── GeologySupportConfig
├── ConstantThicknessDepthModel                (union discriminée "type")
├── FlatSubstratumDepthModel                   (union discriminée "type")
├── MeshCatchmentConfigSchema
├── FieldBaseSectionSchema / FieldHomogeneousSectionSchema / FieldHeterogeneousSectionSchema / FieldVerticalProfileSectionSchema / FieldParamConfig / ResolvedFieldParamSchema
├── DataManagersConfig
├── BaseVariableConfig                         (base factorisée)
│   ├── WindConfig / TemperatureConfig / ... (14 héritiers)
│   └── RechargeConfig, OceanicConfig, ...
├── DemConfig / GeologyConfig / HydrographyConfig  ← héritent direct de BaseModel (incohérence)
├── ProcessSpatialConfig                       (base trop permissive)
│   ├── FlowConfig (14 champs, 6 overrides)
│   └── TransportConfig (6 champs, 4 overrides avec exclude=True)
├── BoundaryCondition / InitialCondition / SinkSource (base)
│   └── FlowInitialCondition, FlowBoundaryConditionConfig (héritage partiel + composition)
├── SolverConfig / ModflowConfig / Modflow6Config
│   └── Runtime et ProcessSpecific sous-configs (composition)
├── TMeshConfigModel
│   └── TMeshCaseScenarioConfig (héritage propre)
├── ZoneMeshing* (multiples classes, composition)
├── _MethodKwargsBase                          (base calibration)
│   └── GridSearchKwargs, RandomSearchKwargs, NelderMeadKwargs, SimplexKwargs, GpMappingKwargs, DaMhGpKwargs
└── Display*/Postprocess*/Results*/Comparison* (pure composition)
```

### 3.2 Verdicts par branche

| Branche d'héritage | Profondeur | Verdict |
|---|---|---|
| `DomainSupportBaseConfig → {GeneratedBands, GeneratedRings, CatchmentZones, Geology}SupportConfig` avec `Field(discriminator="provider")` | 2 | **Exemplaire** |
| `ConstantThicknessDepthModel` + `FlatSubstratumDepthModel` en `TypeAlias = Annotated[..., Field(discriminator="type")]` | 1 | **Exemplaire** |
| `BaseVariableConfig → 14 VariableConfig(+ SourceConfig)` | 2 | **Correct** mais incohérent (3 variables manquantes) |
| `_MethodKwargsBase → 6 kwargs classes` | 2 | **Bien** |
| `ProcessSpatialConfig → FlowConfig` | 2 | **Problématique** — `FlowConfig` override `param_list`, `param`, `bc`, `ic`, `sinks_sources`, `active_sinks_sources`, `active_bc` avec des types différents de la base. C'est de l'**héritage fantoche** : la base ne contraint rien. |
| `ProcessSpatialConfig → TransportConfig` | 2 | **Encore pire** — hérite puis exclut 4/6 champs avec `exclude=True`. Un *héritage par pure politesse* qui devrait être remplacé par composition ou par un `Protocol`. |
| `BoundaryCondition → FlowBoundaryConditionConfig` | 1 (partiel) | **Acceptable** mais `FlowBoundaryConditionConfig` n'hérite pas vraiment de `BoundaryCondition` — ce sont deux classes parallèles avec des champs similaires. |
| `TMeshConfigModel → TMeshCaseScenarioConfig` | 2 | **Exemplaire** |

### 3.3 Pas d'héritage diamant détecté.

**Recommandation** :
- **À supprimer** : `ProcessSpatialConfig` comme parent de `FlowConfig` et `TransportConfig`. Remplacer par une classe commune *vraiment* minimale (ou supprimer complètement et dupliquer les rares champs communs).
- **À factoriser** : `DemConfig`, `GeologyConfig`, `HydrographyConfig` devraient soit hériter de `BaseVariableConfig` (avec `date_start`/`date_end` = `None`), soit hériter d'une nouvelle `BaseStaticDataConfig` pour documenter clairement leur nature non-temporelle.

---

## 4. Valeurs par défaut — analyse hydrogéologique

### 4.1 Defaults hydrauliques (K, Sy, Ss, porosité)

**Fait saillant** : dans tout le code, il n'existe **aucun default typé pour K, Sy, Ss, porosité** au niveau Pydantic. Ces paramètres passent par le système `FieldParamConfig` (dict de zones → valeurs), donc leur default est défini *à l'utilisation* dans les TOMLs utilisateur.

| Paramètre | Default Pydantic | Verdict |
|---|---|---|
| `K` (conductivité hydraulique) | Aucun default — requis dans `[flow.param.K]` | **Acceptable** (pas de default misleading) |
| `Sy` (coefficient emmagasinement libre) | Aucun default | **Acceptable** |
| `Ss` (specific storage) | Aucun default | **Acceptable** |
| porosité | Aucun default | **Acceptable** |
| `thickness` (épaisseur aquifère constante) | **50.0 m** (`ConstantThicknessDepthModel.thickness`) | **Raisonnable** pour un aquifère de socle cristallin altéré breton ; trop épais pour un aquifère alluvial. Le `gt=0` suffit pour éviter les aberrations. |
| `substratum_elevation` | **0.0 m** | Défaut dangereux — si l'utilisateur oublie de le changer, il implique substrat au niveau de la mer. Pas d'autre choix cependant sans référence géographique. |

### 4.2 Defaults solveurs

| Paramètre | Default | Verdict hydrogéologique |
|---|---|---|
| `ModflowRuntimeConfig.nwt_headtol` | `1e-4` m (0,1 mm) | **Conforme** — tolérance standard MODFLOW-NWT |
| `ModflowRuntimeConfig.nwt_fluxtol` | `500.0` | **Opaque** — unités ? selon manuel MODFLOW-NWT, c'est L³/T en unités MODFLOW. Sans contexte `itmuni`, 500 peut être 500 m³/j ou 500 m³/s. |
| `ModflowRuntimeConfig.nwt_maxiterout` | `5000` | Élevé mais sûr |
| `ModflowRuntimeConfig.nwt_thickfact` | `1e-5` | "Magic number" MODFLOW-NWT — acceptable |
| `Modflow6RuntimeConfig.mf6_outer_dvclose` | `1e-4` m | Cohérent avec NWT |
| `Modflow6RuntimeConfig.mf6_outer_maximum` | `500` | Raisonnable |
| `ModflowProcessSpecificConfig.vka` | `1.0` | **Conforme** (ratio aniso vertical/horizontal, 1 = isotrope) |
| `ModflowProcessSpecificConfig.exdp` | `1.0` m | **Problématique** — profondeur d'extinction ET. Pour un bassin français avec couvert végétal, les valeurs courantes sont 1-3 m en climat humide et 3-5 m en zone semi-aride. 1 m est un choix conservateur mais **non documenté**. |
| `Modflow6ProcessSpecificConfig.evt_extinction_depth` | `1.0` m | Même remarque |

### 4.3 Defaults recharge / forçages

| Paramètre | Default | Verdict |
|---|---|---|
| `FlowRechargeConfig.units` | `"mm/day"` | **Problématique** — unité non-SI. Le reste du code utilise le SI (mètres, secondes). Un default SI `"m/s"` serait plus cohérent même s'il est moins lisible pour l'utilisateur final. **Alternative** : documenter explicitement que les recharges sont en mm/jour par convention hydrologique, et ne jamais normaliser. |
| `FlowRechargeConfig.values` | `0.0` | Neutre, acceptable |
| `FlowRechargeConfig.first_clim` | `"mean"` | Défaut correct pour le spin-up |
| `FlowRechargeConfig.negative_to_evt` | `True` | Cohérent avec les workflows MODFLOW-NWT/6 |
| `FlowRechargeConfig.spatial_mode` | `"auto"` | Acceptable |

### 4.4 Defaults transport

| Paramètre | Default | Verdict |
|---|---|---|
| `ConcentrationTransportParametersConfig.spc_name` | `"NO3"` | **Orienté** — défaut nitrate (probablement pertinent pour l'équipe française, mais biaisé pour un outil générique) |
| `sconc_init` / `sconc_input` | `0.0` | Neutre |
| `disp_long` | `0.0` m | **Physiquement non-informatif** — dispersivité longitudinale nulle = transport purement advectif. Accepté par MT3DMS/MODFLOW6-GWT mais silencieux. Un warning serait opportun. |
| `diffu_coeff` | `0.0` | Idem — diffusion moléculaire nulle acceptable mais à documenter |
| `react_order` | `None` | Bien (optionnel) |
| `rate_decay` | `0.0` | Neutre |

### 4.5 Defaults spatialization / mesh

| Paramètre | Default | Verdict |
|---|---|---|
| `ZoneMeshingSettings.algorithm` | `"delaunay"` | Bien |
| `ZoneMeshingSettings.global_size` | `250.0` m | Raisonnable pour bassin régional (1-1000 km²) |
| `VerticalGridConfig.nlay` | `1` | Conservateur — 1 couche active |
| `cell_samples_per_axis` (`DomainSupportConfig`) | `8` | Défaut d'échantillonnage suffisant |

**Verdict global sur les defaults** : **acceptable** pour les solveurs, **à nuancer** pour les valeurs physiques (les défauts physiquement nuls comme `disp_long=0` ou `diffu_coeff=0` devraient générer un warning, pas une acceptation silencieuse). Le choix `units="mm/day"` dans `FlowRechargeConfig` rompt la cohérence SI du reste de la codebase.

---

## 5. Validation : contraintes physiques vérifiées ou manquantes

### 5.1 Ce qui est validé

| Contrainte | Lieu | Conformité |
|---|---|---|
| `thickness > 0` | `ConstantThicknessDepthModel.thickness` (`gt=0.0`) | Bien |
| `cell_size > 0` | `GeographicConfig._normalize_cell_size` | Bien |
| `snap_dist > 0` | `GeographicConfig._normalize_snap_dist` | Bien |
| `buff_area > 0` | `GeographicConfig._normalize_buff_area` | Bien |
| `min_stream_length_m >= 0` | `RiverNetworkConfig._normalize_min_stream_length` | Bien |
| `threshold_area_km2 > 0` | `RiverNetworkConfig._validate_threshold_payload` | Bien |
| `lay_proportions` somme à 1.0 | `VerticalGridConfig` (isclose avec abs_tol=1e-6) | **Excellent** |
| `dvclose > 0`, `maxiterout >= 1` | `Modflow6RuntimeConfig` (`gt=0.0`, `ge=1`) | Bien |
| `exdp > 0` | `ModflowProcessSpecificConfig` (via `parse_length_to_m`) | Bien |
| `ntsp > 0`, `lenper > 0`, `tsmult > 0` | `TMeshConfigModel` | Bien |
| ISO date format + ordering `date_start < date_end` | `BaseVariableConfig` | **Excellent** |

### 5.2 Ce qui *manque* sur le plan physique

| Contrainte manquante | Lieu où elle devrait exister | Risque |
|---|---|---|
| **`K > 0`** | `ResolvedFieldParamSchema` / `FieldHomogeneousSectionSchema.value` (accepte `object`) | `K <= 0` accepté silencieusement → solveur diverge sans message clair |
| **`0 < Sy < 1`** | idem | `Sy > 1` ou négatif accepté |
| **`Ss > 0`** | idem | idem |
| **`0 < porosité < 1`** | idem | idem |
| **`disp_long >= 0`** | `ConcentrationTransportParametersConfig` | dispersivité négative accepée |
| **`diffu_coeff >= 0`** | idem | idem |
| **Cohérence unités K vs Ss** | Pas de validation inter-paramètres | unité `m/s` pour K puis `m-1` pour Ss sans vérification |
| **`vka > 0`** | `ModflowProcessSpecificConfig.vka` | défaut 1.0 accepté mais `0.0` aussi |
| **`runoff_coeff in [0, 1]`** | ✓ vérifié dans `Groundwater1DChronicleSchema` et `ReservoirChronicleSchema`, absent ailleurs |
| **Brutsaert `p > 0`** (paramètre `p` Brutsaert) | `BrutsaertChronicleSchema.p` défaut 0.346 sans validateur | accepte `p=-1` ou `p=10` |
| **Bornes de `nlay`, `nx`, `ny`** | Partielles (`ge=1` posé) | pas de borne supérieure → `nx=10_000_000` accepté |
| **Cohérence `start_datetime < end_datetime`** | ✓ dans `TMeshConfigModel` et `SimulationTimeConfig`, manquant dans `OverviewSection` |
| **Validité du CRS** | `GeographicConfig.crs_project: str` sans validation | "EPSG:9999" accepté → erreur tardive à l'exécution |
| **Existence des fichiers** | Quelques validateurs (SGridConfig), mais `dem_init_path`, `polyg_shp_path`, `bot_path`, `top_path`, `path_file` CSV pour BC : **pas de `path.exists()` systématique** | L'erreur surgit à l'exécution et non à la validation de config |

**Recommandation** : créer un module `hydromodpy/core/config/physical_validators.py` qui expose :

```python
from typing import Annotated
from pydantic import Field

PositiveFloat = Annotated[float, Field(gt=0.0)]
ProbabilityFloat = Annotated[float, Field(ge=0.0, le=1.0)]           # Sy, porosity
StrictProbabilityFloat = Annotated[float, Field(gt=0.0, lt=1.0)]     # porosité stricte
HydraulicConductivity = Annotated[float, Field(gt=0.0, le=1e-2)]     # K en m/s, borne haute physiquement plausible
Dispersivity = Annotated[float, Field(ge=0.0)]
```

et les utiliser partout où des paramètres physiques passent par Pydantic (notamment dans `ResolvedFieldParamSchema.value`).

### 5.3 Erreurs silencieuses potentielles

| Scénario | Conséquence |
|---|---|
| `FieldHomogeneousSectionSchema.value = "-5 m/s"` (K négatif avec unité) | Parsing réussit, solveur plante au runtime |
| `FlowRechargeConfig.values = "invalid"` (champ `Any`) | Acceptation, crash plus tard |
| `disp_long = -1.0` | Accepté, MT3DMS peut produire des oscillations |
| `nlay = 10000` avec `nx * ny = 10000` | Accepté, OOM à l'exécution |
| `dem_init_path` pointant vers un fichier inexistant mais résolu comme chemin absolu | Passe validation Pydantic, échoue au chargement raster |

---

## 6. Round-trip TOML ⇄ Pydantic ⇄ TOML

### 6.1 Trajet `TOML → Pydantic` (chargement)

Le chargement est **asymétrique selon la provenance** :

1. **`[data]`** : passe par `DataManagersConfig.from_toml_section()` qui :
   - normalise `types` (trim, lowercase, dedup),
   - résout les `Path` relatifs via `_resolve_section_paths` (réécrit `Path → str(Path)`),
   - instancie les sous-configs typées (`GeologyConfig`, `OceanicConfig`, `HydrometryConfig`, ...).

2. **`[flow]`** : passe par `FlowConfig.from_toml_section()` avec une pipeline de ~100 lignes (normalisation `param_list`, `param`, `bc`, `ic`, `sinks_sources`, `active_*`).

3. **Autres sections** : passent par `_load_standard_section()` dans `hydromodpy_config.py:352`, qui fait un simple `model_cls(**payload)` après résolution des paths.

**Verdict** : **fragile** — trois pipelines différents pour charger du TOML. Une seule pipeline unifiée avec enregistrement de "chargeurs spécialisés" par section serait plus maintenable.

### 6.2 Trajet `Pydantic → TOML` (persistance)

**Aucun trajet retour Pydantic → TOML documenté.** Le projet écrit les configs en tant que snapshot JSON dans DuckDB (`simulations.config_toml`, cf. `HydroModPyConfig.from_snapshot`). La sérialisation se fait via `model_dump(mode="python", exclude_none=True)` ou `model_dump(mode="json")`.

**Round-trip effectif** :

```python
cfg = HydroModPyConfig.from_toml("run.toml")
snapshot = cfg.model_dump(mode="json")           # persistance DuckDB
cfg_restored = HydroModPyConfig.from_snapshot(snapshot)   # rechargement
```

**Problèmes identifiés** :

| Problème | Impact | Correctif |
|---|---|---|
| `Path → str` avant instanciation (`_resolve_section_paths` écrit `str(p)`) | Le snapshot contient des chemins absolus de la machine d'origine. Un partage de snapshot entre machines **casse** les chemins. | Conserver `Path`, sérialiser via `field_serializer` au dernier moment |
| `from_snapshot` ne repasse pas par `from_toml` | Les champs qui ont un parsing custom (unités, dates ISO) peuvent être rejoués une 2e fois si le snapshot contient les valeurs non-normalisées | Utiliser `model_validate` sur un snapshot *déjà* normalisé (c'est le cas) |
| Champs avec `exclude=True` (`TransportConfig.param_list`, etc.) | Disparaissent du snapshot — problème si le workflow les réutilise | Revoir l'utilité de `exclude=True` |
| `extra="allow"` sur `FieldBaseSectionSchema` et `FieldParamConfig` | Les champs inconnus persistent dans le snapshot mais ne sont pas rejoués en validation | Migrer vers `extra="forbid"` |
| Champs optionnels `None` vs absents | `exclude_none=True` dans le dump supprime les `None`, mais au rechargement le default est appliqué. Si ce default change entre deux versions, le snapshot "équivaut" à une autre config. | Versionner le schema (déjà présent dans DuckDB `_schema_version`) mais pas dans Pydantic |

**Verdict** : **incomplet**. Le round-trip fonctionne pour un usage local mais **n'est pas portable** entre machines (chemins absolus sérialisés) et ne survivra pas à une évolution silencieuse des defaults Pydantic.

### 6.3 Sérialisation des `Path`

Le code convertit systématiquement `Path → str(absolute_path)` avant validation. Conséquences :
- Le snapshot contient `"/home/bb/.../dem.tif"`, pas `"dem.tif"`.
- Partage impossible entre machines sans rewriting manuel.
- Pas de support de chemin relatif dans les snapshots JSON.

**Recommandation** : utiliser `field_serializer` Pydantic v2 pour convertir `Path` en string *lors du dump* (pas avant), et conserver un champ `_base_dir` séparé dans le snapshot pour permettre la re-résolution sur une autre machine.

---

## 7. Mapping TOML ↔ Pydantic : nommage et ergonomie hydrogéologue

### 7.1 Noms TOML adaptés au métier

| Section TOML | Conformité hydrogéologie | Commentaire |
|---|---|---|
| `[workspace]` | Standard | OK |
| `[geographic]` | **Inhabituel** | Le terme consacré est `[domain]` (ModelMuse) ou `[grid_spec]` (FloPy). `geographic` est correct mais peu utilisé dans la communauté. |
| `[domain]` | **Confus** | Dans HydroModPy, `domain` = zonation (geology, zones), alors que dans MODFLOW/FloPy, `domain` = extension spatiale + grille. La convention est inversée. |
| `[data]` | Bien | OK |
| `[flow]`, `[transport]` | Bien | Cohérent avec MODFLOW 6 (`GWF`, `GWT`) |
| `[solver]` | Bien | OK |
| `[modflownwt]`, `[modflow6]` | Bien | Explicite |
| `[simulation]` | Bien | Cohérent MODFLOW 6 |
| `[overview]` | Original | Concept maison ("carte d'identité bassin") |
| `[mesh_catchment]` | Original | Pourrait être `[mesh]` plus sobrement |

### 7.2 Noms de champs problématiques

| Nom actuel | Fichier | Meilleur nom | Raison |
|---|---|---|---|
| `buff_area` | `GeographicConfig` | `buffer_distance` ou `buffer_percent` | "area" ≠ "distance" ; confusion dimensionnelle |
| `catch_def` | `GeographicConfig` | `watershed_delineation_mode` | abréviation peu lisible pour un nouvel utilisateur |
| `dem_correc_type` | `GeographicConfig` | `dem_depression_handling` | "correc" = typo-gunk |
| `reg_fold` | `GeographicConfig` | `regional_rasters_dir` | acronyme opaque |
| `catch_name` | `WorkspaceConfig` | `catchment_name` ou `project_name` | abréviation |
| `genmtd`, `genmtd_lay`, `genmtd_top`, `genmtd_bot` | `TMeshConfigModel`, `SGridConfig` | `generation_method`, `layer_generation_method`, ... | préfixe `genmtd` incompréhensible |
| `ntsp` | `TMeshConfigModel` | `n_timesteps` | ✓ conforme MODFLOW (`NSTP`) mais en interne on a `ntsp` ≠ `NSTP` |
| `lenper` | `TMeshConfigModel` | `period_length` | ✓ conforme MODFLOW (`PERLEN`) mais graphie différente |
| `nwt_headtol`, `nwt_fluxtol`, `nwt_thickfact`, `nwt_iprnwt`, `nwt_ibotav`, `nwt_backflag`, `nwt_stoptol` | `ModflowRuntimeConfig` | conserver tel quel | **exception** — ces noms sont issus de la documentation MODFLOW-NWT et doivent rester identiques pour les experts |
| `upw_iphdry`, `upw_hdry`, `upw_layvka`, `evt_nevtop`, `evt_ievt`, `evt_ipakcb` | `ModflowRuntimeConfig` | conserver tel quel | idem |
| `spc_name` | `ConcentrationTransportParametersConfig` | `species_name` | abréviation |
| `disp_long`, `disp_transh`, `disp_transv` | idem | `dispersivity_longitudinal`, `dispersivity_transverse_horizontal`, `dispersivity_transverse_vertical` | abréviations peu claires |
| `col_id`, `col_x`, `col_y`, `col_crs`, `col_datetime`, `col_value` | toutes les `*SourceConfig` | acceptable | nomenclature "column_*" abrégée en "col_*" — cohérent |

**Verdict** : les noms techniques MODFLOW (`nwt_*`, `upw_*`, `evt_*`) sont **justifiés** (communauté experte). Les abréviations génériques (`buff_area`, `catch_def`, `reg_fold`, `genmtd`, `spc_name`) nuisent à la lisibilité **sans raison historique**.

### 7.3 Mapping 1:1 ou transformations ?

- **1:1 la plupart du temps** : `[workspace]` → `WorkspaceConfig`, `[geographic]` → `GeographicConfig`, etc.
- **Transformations silencieuses** :
  - `[data.types]` liste → normalisation trim+lowercase+dedup.
  - `catch_def = "DEM"` (majuscules) → `"dem"` (normalisation).
  - Path relatifs → absolus (irreversible).
  - `"0.5 km"` → `500.0` via `parse_length_to_m`.
  - `"buff_area = '500 m'"` → `"500.0"` (str !) pour préserver le contrat `catchment_domain`.
- **Transformations dangereuses** :
  - `buff_area` chaîne → chaîne (!!) mais chaîne avec contenu numérique. Re-parsing requis plus tard.
  - Injection de `__DEM_API_BOOTSTRAP__` comme sentinel dans `dem_init_path` pour l'overview workflow (`hydromodpy_config.py:240`) — **anti-pattern**, devrait être un `Optional[Path]` avec un flag séparé.

---

## 8. Duplication, verbosité, dead code

### 8.1 Duplication massive — `data/variables/*/config.py`

Les 17 variables (`wind`, `temperature`, `soil_moisture`, `runoff`, `humidity`, `etp`, `radiation`, `precipitation`, `recharge`, `piezometry`, `hydrometry`, `water_quality`, `intermittency`, `oceanic`, `dem`, `geology`, `hydrography`) ont chacun leur `config.py` de 60-90 lignes.

**9 variables partagent un schéma quasi-identique** (`custom` + `sim2` providers, champs `col_id`, `col_x`, `col_y`, `col_crs`, `col_datetime`, `col_value`, `default_crs`, `mask_path`, `station_ids`, `extent`, `force_refresh`, `path`, `source_unit`) :

| Variable | Lignes communes | Lignes spécifiques |
|---|---|---|
| wind, temperature, soil_moisture, runoff, humidity, etp | ~65 | 0 (pure duplication) |
| radiation, precipitation | ~65 | 1 (`components` field) |
| piezometry, hydrometry, water_quality, intermittency | ~65 | 3-5 (API hubeau : `product`, `site_type`, `code_departement`, `require_observations`, `fallback_search_radius_km`) |

**Total : ~1200 lignes récupérables par factorisation**.

**Correctif proposé** :

```python
# data/common/base_config.py

class BaseTimeSeriesSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str                                 # overridden by subclass with Literal
    path: Path | None = None
    source_unit: str | None = None
    col_id: str = "id"
    col_x: str = "x"
    col_y: str = "y"
    col_crs: str = "crs"
    col_datetime: str = "datetime"
    col_value: str = "value"
    default_crs: str = "EPSG:4326"
    mask_path: Path | None = None
    station_ids: list[str] | None = None
    extent: Literal["watershed", "study_area"] | None = None
    force_refresh: bool = False

    @model_validator(mode="after")
    def _check_custom_path(self):
        if self.source == "custom" and self.path is None:
            raise ValueError(f"source='custom' requires 'path'")
        return self

class BaseHubeauSourceConfig(BaseTimeSeriesSourceConfig):
    nearest: bool = False
    fallback_search_radius_km: float | None = None
    require_observations: bool = True
```

Puis chaque variable devient :

```python
class WindSourceConfig(BaseTimeSeriesSourceConfig):
    source: Literal["custom", "sim2"]

class WindConfig(BaseVariableConfig):
    _TOML_SECTION = "wind"
    sources: list[WindSourceConfig] = Field(..., min_length=1)
```

→ **réduction de ~1200 lignes à ~200 lignes**.

### 8.2 Duplication `flow_timeseries_config` ↔ `transport_timeseries_config`

**`analysis/postprocess/timeseries/flow_timeseries_config.py` et `transport_timeseries_config.py`** ont 80-90% de champs en commun (`enabled`, `datetime_format`, `subbasin_results`). Seul diffère :
- `flow` : `subbasin_results`
- `transport` : `suffix_name="s1"` (legacy), `residence_times`, `concentration_seepage`, `mass_accumulated`

**Correctif** : base commune `TimeseriesPostprocessBase` dans `analysis/postprocess/timeseries/base_config.py`.

### 8.3 Duplication `flow_netcdf_config` ↔ `transport_netcdf_config`

Idem, ~90% de chevauchement (`enabled`, `datetime_format` vs `enabled`, `datetime_format`, `residence_times`, `concentration_seepage`, `mass_accumulated`).

### 8.4 Duplication des validateurs `_check_source_requirements`

Cette fonction existe **17 fois** dans `data/variables/*/config.py` avec variations mineures. À factoriser dans la base.

### 8.5 Duplication `core/engine_config.py` vs `engine/config.py` (calibration)

Le module calibration a **deux hiérarchies Pydantic parallèles** :
- `analysis/calibration/core/engine_config.py` : `CalibrationSectionSchema`, `CalibrationTomlSchema`, `OutputSectionSchema`, `ObjectiveSectionSchema`
- `analysis/calibration/engine/config.py` : `ModelCalibrationConfig`, `ModelCalibrationSectionSchema`, etc.

Verdict : **refonte inachevée**. Les deux hiérarchies décrivent à peu près le même domaine. **À fusionner**.

### 8.6 Verbosité : classes à méthode unique, wrappers

| Classe | Fichier | Valeur ajoutée |
|---|---|---|
| `SolverConfig` | `solver/base/solver_config.py` | 1 champ (`solver_engine`) — équivaut à un champ direct dans `HydroModPyConfig` ; **acceptable** car gardé comme point d'extension futur |
| `BudgetConfig` | `results/config.py` | 1 champ (`spatial_fields: bool`) — **marginale** |
| `TransportMt3dmsConfig`, `TransportModflow6GwtConfig`, `TransportModpathConfig` | `transport_config.py` | containers d'un seul sous-block parametersConfig — **verbeux**, pourraient être remplacés par un `dict[Literal[...], ParametersConfig]` |
| `FlowInitialConditions` | `initial_conditions.py` | 1 champ (`h: FlowInitialCondition`) — **marginale** |
| `SolverSGridConfig` | `sgrid_config.py` | 2 champs (planar, vertical) — acceptable |

### 8.7 Code mort / abstractions inutiles

- `process/base/{boundary_conditions.py, initial_conditions.py, sinks_sources.py, process_spatial_config.py}` : ces classes sont héritées par `FlowConfig` et `TransportConfig` mais les héritiers **surchargent tous les champs**. Les bases n'apportent rien. **À supprimer** ou à réduire à un `Protocol`.
- `ResolvedFieldParamSchema` (`field_param_config.py:512`) **duplique** `FieldBaseSectionSchema` + `FieldHomogeneousSectionSchema` + `FieldHeterogeneousSectionSchema` + `FieldVerticalProfileSectionSchema`. C'est le résultat "aplati" d'une étape de résolution. Son existence doublonne le schéma d'entrée.
- `_rebuild_forward_refs()` dans `data_managers_config.py:353` : hack nécessaire car tous les types `XxxConfig` sont importés en lazy-string. **À revoir** : structurer `DataManagersConfig` différemment (peut-être via un `dict[str, Union[...]]` avec discriminator).
- `capability_gallery._safe_asset_name()` (ligne 53) : défini mais **non utilisé** comme validateur alors qu'il devrait l'être.

---

## 9. Formats de données — interopérabilité

| Dimension | Format actuel | Standard applicable | Verdict |
|---|---|---|---|
| Coordonnées | EPSG string (`"EPSG:2154"`) | OGC/EPSG | **Conforme** mais **pas validé** côté Pydantic — validation déléguée à pyproj |
| DEM | GeoTIFF (`.tif`) | OGC / GDAL | **Standard** |
| Polygones | Shapefile (`.shp`) | OGC / OGR | **Standard** (mais shapefile est obsolète pour les gros volumes — GeoPackage serait plus moderne) |
| Chroniques | CSV | Maison (pas CF-compliant) | **Acceptable** mais peu interopérable |
| Maillage structuré | MODFLOW DIS (top/bot par cellule) | MODFLOW — standard de facto | **Conforme** |
| Maillage non-structuré | MODFLOW DISV (vertex-based, implémenté dans `sgrid_config.py`) + gmsh pour le raffinement | MODFLOW / UGRID | **Partiellement conforme** — UGRID serait le standard mais non utilisé |
| Sortie Zarr | Custom layout avec `head/`, `derived/`, `budget/`, `pathlines/` | Pas CF-conventions, pas UGRID | **Maison** — décisions raisonnables mais limite l'interop xarray/Dask |
| Sortie NetCDF (via `*NetcdfPostprocessConfig`) | Format non précisé | CF-conventions attendues pour l'hydrogéologie | **Non documenté** dans la config Pydantic |

**Verdict** : l'outil respecte les standards OGC (EPSG, GeoTIFF, shapefile) mais **ignore CF-conventions et UGRID** pour les sorties. Ce n'est pas un bug, mais ça limite l'interopérabilité avec les outils climatiques (xarray), QGIS (UGRID), et les viewers scientifiques.

---

## 10. Grilles régulières vs irrégulières — conformité MODFLOW DIS/DISV

| Cas | Implémentation | Verdict |
|---|---|---|
| Grille structurée (DIS) | `SGridConfig` + `sgrid_from_config.py` | **Conforme MODFLOW-2005/NWT/6 DIS** |
| Grille non-structurée vertex (DISV) | `sgrid_config.py` avec `zone_meshing/config.py` via gmsh | **Conforme MODFLOW 6 DISV** |
| Grille quadtree/DISU | Non implémenté | hors périmètre |

Les conventions MODFLOW (indexation 0-based vs 1-based, `layer, row, col` vs `cell_id`) sont respectées via `FlowWellConfig.cell: tuple[int, int, int]` (0-based selon commentaire ligne 65 de `sinks_sources.py`).

**Verdict** : le projet gère **correctement** les deux types de grilles.

---

## 11. Optimisation et performances Pydantic

| Symptôme | Impact | Recommandation |
|---|---|---|
| `FlowConfig` avec 16 validators déclenchés à chaque instanciation | Latence au chargement TOML sur les fichiers avec beaucoup de `[flow.param.XXX]` | Regrouper les normalisations dans un unique `model_validator(mode="before")` |
| `DataManagersConfig._rebuild_forward_refs()` appelé à l'import | Coût d'import constant | Utiliser `model_rebuild(force=True)` ou restructurer en union discriminée |
| `_resolve_section_paths` parcourt tous les champs d'un modèle à chaque appel | Négligeable sauf sur les listes imbriquées (`sources`) | OK |
| Validation ISO datetime via `datetime.fromisoformat(v)` dans un `field_validator` | Python-pur, moins rapide que `Pydantic.AwareDatetime`/`NaiveDatetime` natifs | Préférer typage `date`/`datetime` Pydantic natif |
| Aucun usage de `model_config["validate_assignment"] = True` | Les mutations post-validation ne sont pas vérifiées | À discuter selon le besoin (coût non négligeable) |
| `arbitrary_types_allowed=True` dans 3 configs | Désactive les checks Pydantic sur les types non-Pydantic. Peut cacher des bugs de typage. | Restreindre |

**Verdict global** : pas de problème de perf Pydantic critique, sauf `FlowConfig` qui est un **point chaud** à 16 validators enchaînés.

---

## 12. Tests et couverture Pydantic

### 12.1 Pratiques observées

- Tests unitaires Pydantic dans `tests/unit/` (présence observée via le périmètre d'audit mais non explorés ici).
- Tests de validation TOML via round-trips `from_toml → model_dump`.

### 12.2 Signalements critiques

Sans avoir exploré `tests/`, je signale les **zones à risque non couvertes par Pydantic seul** :

- Les champs `Any`/`object` dans `FlowRechargeConfig.values`, `FlowRechargeConfig.heterogeneous_source`, `ProcessSpatialConfig.param`, `FieldHomogeneousSectionSchema.value`, `InitialCondition.value` **contournent la validation Pydantic**. Les tests doivent donc vérifier que les cas aberrants (négatifs, nuls, NaN) sont bien rejetés par d'autres couches.
- Les validateurs `model_validator(mode="after")` de 30+ lignes (`FlowWellConfig._validate_location_payload`, `FlowBoundaryConditionConfig._validate_runtime_payload`, `ZoneMeshingSettings._validate_cross_constraints`) devraient être testés exhaustivement par combinaison — hors portée du présent audit.

---

## 13. Recommandations priorisées

### P0 — critique (action immédiate)

1. **Ajouter `extra="forbid"` à `HydroModPyConfig`** (`core/config/hydromodpy_config.py:73`). Le point d'entrée racine accepte silencieusement des sections inconnues.
2. **Factoriser les 17 `*SourceConfig` dans `data/variables/*/config.py`** via une classe `BaseTimeSeriesSourceConfig` et une variante `BaseHubeauSourceConfig`. Gain estimé : ~1000 lignes.
3. **Ajouter un validateur `p > 0`** dans `BrutsaertChronicleSchema.p` (`recession_brutsaert/case_config.py`). Défaut `0.346` sans borne.
4. **Remplacer `FlowRechargeConfig.values: Any` et `heterogeneous_source: Any`** par des types précis (`float | list[float]` ou `Literal`-based union).
5. **Ajouter une validation `K > 0`, `Ss > 0`, `0 ≤ Sy ≤ 1`** dans `ResolvedFieldParamSchema.value` et `FieldHomogeneousSectionSchema.value`.

### P1 — important (prochaine itération)

6. **Supprimer l'héritage `FlowConfig(ProcessSpatialConfig)` et `TransportConfig(ProcessSpatialConfig)`**. Remplacer par composition. Les bases n'apportent aucune contrainte et sont systématiquement overridées.
7. **Remplacer `mode`/`source` par `Field(discriminator=...)`** dans `FlowBoundaryForcingConfig`, `FlowWellForcingConfig`, et toutes les `*SourceConfig`. C'est le pattern natif Pydantic v2, et rend le code plus type-safe.
8. **Fusionner `analysis/calibration/core/engine_config.py` et `analysis/calibration/engine/config.py`**. Deux hiérarchies parallèles pour le même domaine.
9. **Factoriser `flow_timeseries_config` / `transport_timeseries_config` et `flow_netcdf_config` / `transport_netcdf_config`** via bases communes.
10. **Typer les dates en `datetime.date` / `datetime.datetime`** dans `BaseVariableConfig` et `OverviewSection` (Pydantic valide nativement l'ISO format).
11. **Réviser les defaults physiques non-SI** : `FlowRechargeConfig.units = "mm/day"` → documenter explicitement la convention ou migrer en SI.

### P2 — souhaitable (si le temps le permet)

12. **Valider `CRS`** via pyproj dans le validator `GeographicConfig.crs_project` et `DataManagersConfig.project_crs`.
13. **Valider l'existence de fichiers** (`dem_init_path`, `polyg_shp_path`, `bot_path`, `top_path`, `path_file` CSV) dans les validators `model_validator(mode="after")`.
14. **Renommer les champs à abréviations opaques** : `buff_area`, `catch_def`, `reg_fold`, `genmtd*`, `spc_name`, `disp_*`. Conserver `nwt_*`, `upw_*`, `evt_*` (standards MODFLOW).
15. **Supprimer le sentinel `__DEM_API_BOOTSTRAP__`** dans `HydroModPyConfig.from_toml` (ligne 240) au profit d'un flag booléen ou d'un `Optional[Path]`.
16. **Migrer `extra="allow"` → `extra="forbid"`** sur `FieldBaseSectionSchema` et `FieldParamConfig` après une release de dépréciation.
17. **Supprimer `ResolvedFieldParamSchema`** (doublonne `FieldParamConfig` aplati) ou exposer la transformation via `@model_serializer`.
18. **Documenter avec un test de round-trip** : TOML → Pydantic → TOML identique (ou différence limitée aux normalisations documentées).

### P3 — cosmétique

19. **Remplacer `@property catch_name, data_path, catalog_path` par `@computed_field`** dans `WorkspaceConfig` pour qu'ils apparaissent dans le schéma JSON et la sérialisation.
20. **Documenter tous les "magic numbers" MODFLOW** (`nwt_thickfact=1e-5`, `bas_hnoflo=-9999.0`, `upw_hdry=-100.0`) avec un commentaire renvoyant à la doc USGS.

---

## 14. Conclusion

HydroModPy présente une architecture Pydantic **globalement moderne et cohérente** : Pydantic v2, `extra="forbid"`, `Annotated[Type, ParamLevel(...)]` pour l'UX, usage correct des validateurs de niveau champ et modèle. Certaines sous-parties (`DomainSupportConfig`, `DepthModelConfig`, `ZoneMeshing*`, `TMeshConfigModel`) sont même **exemplaires** dans leur usage des discriminated unions et des validations croisées.

Cependant, trois problèmes systémiques **pénalisent l'ensemble** :

1. **Duplication massive** dans `data/variables/*/config.py` (17 fichiers quasi-jumeaux, ~1200 lignes redondantes) et dans `analysis/postprocess/` (flow/transport timeseries et NetCDF).
2. **Héritage fantoche** autour de `ProcessSpatialConfig` / `FlowConfig` / `TransportConfig` : 16 validateurs cumulés sur `FlowConfig`, une méthode `from_toml_section` de 100+ lignes, et des héritages systématiquement overridés ou exclus. Le code appelle un refactor vers de la pure composition.
3. **Validation physique insuffisante** : `K`, `Sy`, `Ss`, porosité, dispersivités passent par des champs typés `object`/`Any`/`float sans borne`. Les contraintes hydrogéologiques élémentaires (`K > 0`, `0 ≤ Sy ≤ 1`) ne sont vérifiées nulle part au niveau Pydantic. Les erreurs apparaissent tardivement, au solveur.

Les deux premiers problèmes sont des **refactors mécaniques** (1-2 semaines de travail), le troisième est un **module neuf à écrire** (`core/config/physical_validators.py`, ~100 lignes). Aucun de ces chantiers n'est bloquant, mais leur résolution transformerait le ressenti qualité du projet, particulièrement pour les utilisateurs non-experts qui dépendent des validateurs pour se protéger des configurations aberrantes.

**Note finale** : la conformité Pydantic v2 est **excellente** — aucun résidu v1, aucun anti-pattern majeur — mais l'uniformité du style est **moyenne**, avec de la très haute qualité (`depth_model_config.py`, `spatial_support_config.py`) côtoyant de la duplication grossière (`data/variables/*/config.py`). Unifier le niveau par une passe de factorisation ferait passer cette codebase de "bon projet Python scientifique" à "référence pédagogique Pydantic".
