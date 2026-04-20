# Architecture cible — Système de configuration Pydantic v2 / TOML

**Document** : `architecture_cible/02_config_pydantic.md`
**Date** : 2026-04-18
**Auteur** : audit d'expert Pydantic v2 / Hydra / OmegaConf / dynaconf
**Périmètre** : refonte complète du système de configuration HydroModPy
**Statut attendu** : design à implémenter, pas un patch de l'existant.

> **Statut des éléments** — chaque spécification est annotée :
> `[NOUVEAU]` (n'existe pas), `[RENOMME]` (existe sous un autre nom),
> `[REFACTORE]` (existe mais doit changer), `[CONSERVE]` (existe et est bien).

---

## 0. Principes directeurs

| # | Principe | Motivation | Impact architectural |
|---|----------|------------|----------------------|
| 1 | **TOML canonique** comme format utilisateur | Lisible par un hydrogéologue, pas de quoting JSON, supporte commentaires | Tous les modèles round-trip `TOML → Pydantic → TOML` sans perte |
| 2 | **Typage strict** (`Literal`, `Annotated`, `Path`, `datetime`) | Erreurs de typo détectées à la lecture du TOML | Aucun `object`, `Any`, `dict[str, Any]` dans le schéma public |
| 3 | **Validation physique** à la construction | K négatif, Sy > 1 attrapés avant le solveur | Table `PHYSICAL_BOUNDS` centralisée ; validators par Annotated |
| 4 | **Discriminated unions** pour le polymorphisme | `depth_model.type`, `forcing.mode`, `domain_support.provider` | Plus de `if isinstance` dispersés ; erreurs claires |
| 5 | **Séparation `user` / `dev` / `expert`** via `ParamLevel` | Template TOML progressif, UI Streamlit filtrable | Métadonnée `Annotated[T, ParamLevel("user")]` sur *chaque* champ |
| 6 | **`extra="forbid"` par défaut** | Typos TOML (`[workspc]`) rejetés | Hérité d'une classe racine `HydroModelBase` |
| 7 | **Composition > héritage** | `FlowConfig ← ProcessSpatialConfig` duplique 100 % des champs | `ProcessConfig` devient générique `Generic[IC, BC, SS, Param]` |
| 8 | **Immutabilité raisonnée** | Configs validées = snapshot | `model_config = ConfigDict(frozen=False)` mais `model_copy(update=...)` pour mutations |
| 9 | **JSON Schema auto-généré** publié | Auto-complétion IDE (VSCode even-better-toml), CI schema-linting | `hmp schema export --out schema.json` dans le CLI |
| 10 | **Pas de magie** dans `from_toml` | `from_toml` = lecture TOML + parse date + merge. Tout le reste dans validators | `@model_validator(mode="before")` pour les dérivations |

### 0.1 Comparaison aux projets de référence

| Outil | Ce qu'il fait bien | Ce qu'on reprend | Ce qu'on ne reprend pas |
|-------|--------------------|------------------|--------------------------|
| **Hydra** (Facebook) | Composition `defaults:`, overrides CLI, groupes | **Oui** : groupes de configs (`solver=modflow6`, `geographic=synthetic`) | Non : pas de compositions YAML empilées — trop complexe pour un hydrogéologue |
| **OmegaConf** | Interpolations `${var}` | Non | Trop dynamique, casse la validation |
| **Dynaconf** | Profils d'environnement | **Oui** : profils `user/dev/expert` via `ParamLevel` | Pas de multi-environnement ; un seul projet = un seul TOML |
| **pydantic-settings** | Env vars typées | **Oui** : surcharge `HYDROMODPY_*` limitée aux paths et flags CI | Pas d'env vars pour la physique |
| **tomli-w + tomlkit** | Dump TOML propre | **Oui** : `tomlkit` pour conserver les commentaires au round-trip | — |
| **pint** | Unités dimensionnelles | **Oui** : via `Quantity[m/s]` sur les champs physiques (post-P1) | — |
| **FloPy** config | Attributs flat | **Non** : on expose un schéma imbriqué explicite |

---

## 1. Arbre d'héritage cible

### 1.1 Vue synoptique

```
HydroModelBase (BaseModel)                       [NOUVEAU]
  model_config = ConfigDict(
      extra="forbid",
      serialize_by_alias=True,
      populate_by_name=True,
      validate_assignment=True,
      str_strip_whitespace=True,
  )
  │
  ├── HydroModPyConfig                           [REFACTORE]  ← racine (agrégateur)
  │
  ├── WorkspaceConfig                            [CONSERVE]
  │
  ├── GeographicConfig (abstract)                [REFACTORE]
  │   ├── StandardGeographicConfig               [RENOMME] (ex: champ source_mode="standard")
  │   └── SyntheticGeographicConfig              [RENOMME] (ex: champ source_mode="synthetic")
  │   (discriminés par champ `source_mode`)
  │
  ├── DomainConfig                               [CONSERVE]
  │   └── depth_model : DepthModel                [CONSERVE] (discriminated union)
  │       ├── ConstantThicknessDepthModel        [CONSERVE]
  │       └── FlatSubstratumDepthModel           [CONSERVE]
  │   └── supports : dict[str, DomainSupport]    [CONSERVE]
  │       ├── GeneratedBandsSupport              [CONSERVE]
  │       ├── GeneratedRingsSupport              [CONSERVE]
  │       └── ExternalRasterSupport              [NOUVEAU]
  │
  ├── DataConfig                                 [RENOMME] (ex: DataManagersConfig)
  │   └── variables : dict[str, VariableConfig]  [REFACTORE] (plus flat)
  │       ├── TimeseriesVariableConfig           [NOUVEAU] (ex: 14 doublons)
  │       ├── RasterVariableConfig               [NOUVEAU] (DEM, geology)
  │       └── VectorVariableConfig               [NOUVEAU] (hydrography, geology_vector)
  │
  ├── ProcessConfig[IC, BC, SS, P] (Generic)     [REFACTORE] (ex-ProcessSpatialConfig)
  │   ├── FlowConfig = ProcessConfig[
  │   │       FlowInitialCondition,
  │   │       FlowBoundaryCondition,
  │   │       FlowSinkSource,
  │   │       FlowFieldParam]                    [REFACTORE] (plus d'héritage direct)
  │   └── TransportConfig = ProcessConfig[...]   [REFACTORE]
  │
  ├── SolverConfig                               [CONSERVE]
  │   └── engine: Literal["modflow_nwt","modflow6","boussinesq"]
  │   └── packages: ModflowNwtPackages | Modflow6Packages | BoussinesqPackages
  │       (discriminated union)                   [REFACTORE]
  │
  ├── SimulationConfig                           [CONSERVE]
  │   └── time: SimulationTimeConfig             [CONSERVE]
  │   └── process: list[SimulationProcessConfig] [CONSERVE]
  │
  ├── GridConfig                                 [NOUVEAU] (ex-SGridConfig + MeshCatchmentConfig unifiés)
  │   └── kind: Literal["cartesian", "gmsh", "external"]
  │   └── planar / vertical / …                   (discriminated)
  │
  ├── ResultsConfig                              [CONSERVE]
  │
  ├── DisplayConfig                              [CONSERVE]
  ├── PostprocessConfig                          [CONSERVE]
  ├── CalibrationConfig                          [CONSERVE]
  ├── BatchConfig                                 [CONSERVE]
  └── OverviewConfig                             [CONSERVE]
```

### 1.2 Sous-arbre `Forcing` (nouveau, factorisé)

```
Forcing = Annotated[                            [NOUVEAU]
    ConstantForcing | CsvForcing | SyntheticForcing,
    Field(discriminator="mode"),
]
  ├── ConstantForcing       mode="constant"   + value, units
  ├── CsvForcing            mode="csv"        + path, col_datetime, col_value, interp
  └── SyntheticForcing      mode="synthetic"  + amplitude, period_days, offset
```

**Utilisé par** : `FlowRechargeConfig.forcing`, `FlowWellConfig.forcing`,
`FlowBoundaryCondition.forcing`, `TimeseriesVariableConfig.forcing` — élimine
≈200 lignes dupliquées.

### 1.3 Arbre des champs critiques avec types exacts

Chaque ligne : `champ : type = default  # unité | contrainte`

```
HydroModPyConfig
├── schema_version : Literal["1.0"] = "1.0"
├── run_id         : str | None = None          # auto = toml_path.stem
├── workspace      : WorkspaceConfig            # REQUIRED
├── geographic     : GeographicConfig           # REQUIRED
├── grid           : GridConfig | None = None
├── domain         : DomainConfig = Domain()
├── data           : DataConfig = DataConfig()
├── flow           : FlowConfig = FlowConfig()
├── transport      : TransportConfig | None = None
├── simulation     : SimulationConfig = SimulationConfig()
├── solver         : SolverConfig = SolverConfig()
├── results        : ResultsConfig = ResultsConfig()
├── display        : DisplayConfig = DisplayConfig()
├── postprocess    : PostprocessConfig = PostprocessConfig()
├── calibration    : CalibrationConfig | None = None
├── batch          : BatchConfig | None = None
└── overview       : OverviewConfig | None = None
```

**Règle d'or** : les workflows secondaires (`calibration`, `batch`, `overview`,
`transport`) sont `Optional` ; leur présence = discriminant du workflow.

---

## 2. Mapping TOML complet

### 2.1 Tableau maître — TOML → classe Pydantic

| Section TOML | Classe Pydantic (chemin) | Statut |
|--------------|--------------------------|--------|
| `[workspace]` | `core.workspace.WorkspaceConfig` | `[CONSERVE]` |
| `[geographic]` (mode=standard) | `spatial.geographic.StandardGeographicConfig` | `[REFACTORE]` |
| `[geographic]` (mode=synthetic) | `spatial.geographic.SyntheticGeographicConfig` | `[REFACTORE]` |
| `[geographic.river_network]` | `spatial.geographic.RiverNetworkConfig` | `[CONSERVE]` |
| `[grid]` (kind=cartesian) | `spatial.grid.CartesianGridConfig` | `[RENOMME]` (ex-SGridConfig) |
| `[grid]` (kind=gmsh) | `spatial.grid.GmshGridConfig` | `[RENOMME]` |
| `[grid.planar]` / `[grid.vertical]` | `CartesianPlanarConfig` / `CartesianVerticalConfig` | `[CONSERVE]` |
| `[domain]` | `spatial.domain.DomainConfig` | `[CONSERVE]` |
| `[domain.depth_model]` | `DepthModel` (discriminé) | `[CONSERVE]` |
| `[domain.supports.<name>]` | `DomainSupport` (discriminé) | `[CONSERVE]` |
| `[data]` | `data.DataConfig` | `[RENOMME]` |
| `[data.<variable>]` | `data.variables.<Variable>Config` | `[REFACTORE]` |
| `[[data.<variable>.sources]]` | `data.variables.SourceSpec` (discriminée) | `[NOUVEAU]` |
| `[flow]` | `process.flow.FlowConfig` | `[REFACTORE]` |
| `[flow.param.<id>]` | `process.flow.FlowFieldParam` | `[CONSERVE]` |
| `[flow.param.<id>.field_homogeneous]` | `FieldHomogeneousSection` | `[CONSERVE]` |
| `[flow.param.<id>.field_heterogeneous]` | `FieldHeterogeneousSection` | `[CONSERVE]` |
| `[flow.param.<id>.field_vertical_profile]` | `FieldVerticalProfileSection` | `[CONSERVE]` |
| `[flow.ic]` | `process.flow.FlowInitialCondition` | `[CONSERVE]` |
| `[flow.bc.<family>.<id>]` | `process.flow.FlowBoundaryCondition` | `[REFACTORE]` (famille = cauchy, dirichlet, neumann) |
| `[flow.sinks_sources.<id>]` | `FlowRechargeConfig` / `FlowWellConfig` (discriminé) | `[REFACTORE]` |
| `[transport]` | `process.transport.TransportConfig` | `[CONSERVE]` |
| `[transport.modpath]` / `[transport.mt3dms]` / `[transport.modflow6gwt]` | solveur-spécifique | `[CONSERVE]` |
| `[solver]` | `solver.base.SolverConfig` | `[CONSERVE]` |
| `[solver.packages]` (engine=modflow_nwt) | `solver.modflow_nwt.ModflowNwtPackages` | `[RENOMME]` (fusionne runtime + process_specific) |
| `[solver.packages]` (engine=modflow6) | `solver.modflow6.Modflow6Packages` | `[RENOMME]` |
| `[solver.packages]` (engine=boussinesq) | `solver.boussinesq.BoussinesqPackages` | `[NOUVEAU]` |
| `[simulation.time]` | `simulation.SimulationTimeConfig` | `[CONSERVE]` |
| `[[simulation.process]]` | `simulation.SimulationProcessConfig` | `[CONSERVE]` |
| `[results]` | `results.ResultsConfig` | `[CONSERVE]` |
| `[results.derived]`, `[results.export]` | `DerivedConfig`, `ExportConfig` | `[CONSERVE]` |
| `[display]`, `[display.flow]`, `[display.particles]`, `[display.transport]` | `DisplayConfig` + sous-classes | `[CONSERVE]` |
| `[postprocess]`, `[postprocess.flow]`, `[postprocess.transport]` | `PostprocessConfig` | `[CONSERVE]` |
| `[calibration]`, `[output]`, `[objective]` | `analysis.calibration.*` | `[CONSERVE]` |
| `[batch]` | `analysis.batch.BatchConfig` | `[CONSERVE]` |
| `[overview]` | `analysis.overview.OverviewConfig` | `[CONSERVE]` |

### 2.2 Réduction du nombre de sections racine

| Avant (16 racines plates) | Après (3 groupes logiques) |
|---------------------------|-----------------------------|
| `[workspace]`, `[geographic]`, `[domain]`, `[data]`, `[flow]`, `[transport]`, `[simulation]`, `[solver]`, `[modflownwt]`, `[modflow6]`, `[display]`, `[postprocess]`, `[capability_gallery]`, `[overview]`, `[mesh_catchment]`, `[results]` | **Inchangé** pour lisibilité humaine ; **mais** `[modflownwt]` et `[modflow6]` sont déplacés sous `[solver.packages]` avec un discriminant sur `[solver].engine`. `[mesh_catchment]` devient `[grid]` unifié. |

**Justification** : un hydrogéologue lit `[solver]` puis `[solver.packages]` plutôt que de deviner lequel de `[modflownwt]` ou `[modflow6]` est actif. Hydra/OmegaConf font exactement ça avec leurs groupes.

### 2.3 Exemple TOML cible minimaliste (profil `user`, ≤60 lignes)

```toml
# ======================================================================
# HydroModPy — config utilisateur (profil: user)
# schema_version = "1.0"
# ======================================================================

[workspace]
project_root = "."

[geographic]
source_mode     = "standard"
catch_def       = "from_outlet_coord"
dem_init_path   = "../../data/dem/DEM_armorican.tif"
x_outlet        = 327816.965
y_outlet        = 6777886.67
snap_dist       = "150 m"
buff_area       = "10 %"
crs_project     = "EPSG:2154"

[domain]
zone_ids = ["geology"]

[domain.depth_model]
type      = "constant_thickness"
thickness = "50 m"

[data]
types          = ["geology", "hydrography", "recharge"]
inference_mode = "warn"

[[data.geology.sources]]
source = "brgm_1m"

[[data.recharge.sources]]
source        = "synthetic"
values        = [0.9589]             # mm/day
start_date    = "2000-01-01"
freq          = "YE"
periods       = 1
runoff_ratio  = 0.0

[flow]
flow_regime          = "steady"
param_list           = ["K", "Sy", "Ss"]
active_sinks_sources = ["recharge"]
active_bc            = ["drainage"]

[flow.param.K.field]
id   = "K"
kind = "homogeneous"
unit = "m/d"

[flow.param.K.field_homogeneous]
value = 1.728

[flow.param.Sy.field]
id   = "Sy"
kind = "homogeneous"
unit = "-"
[flow.param.Sy.field_homogeneous]
value = 0.01

[flow.param.Ss.field]
id   = "Ss"
kind = "homogeneous"
unit = "m-1"
[flow.param.Ss.field_homogeneous]
value = 1e-5

[flow.ic]
type  = "top"
value = 1.0
unit  = "m"

[flow.bc.cauchy.drainage]
application_domain = "top"
value              = 0.0
unit               = "m2/s"

[flow.sinks_sources.recharge]
first_clim      = "mean"
negative_to_evt = true

[solver]
engine = "modflow_nwt"

[simulation.time]
start_datetime = "2020-01-01T00:00:00"
end_datetime   = "2020-12-31T00:00:00"
step_value     = 30
step_unit      = "day"
```

**Ce qu'on remarque** : aucune mention de `[modflownwt.runtime]` ou
`[modflownwt.process_specific]` — les defaults physiquement sensibles sont
implicites. Le profil `expert` les exposerait.

---

## 3. Squelettes de code — les 5 modèles les plus importants

### 3.1 `HydroModelBase` — racine projet `[NOUVEAU]`

**Fichier** : `hydromodpy/core/config/base.py`

```python
"""Base Pydantic pour tous les modèles HydroModPy.

Impose extra="forbid", serialize_by_alias, populate_by_name, et un
validator qui vérifie la cohérence des VisibleWhen via introspection.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from hydromodpy.core.config.param_level import VisibleWhen


class HydroModelBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",                  # typos TOML rejetées
        serialize_by_alias=True,         # dump respecte les aliases
        populate_by_name=True,           # lecture par nom interne OK
        validate_assignment=True,        # `cfg.flow.regime = "xxx"` validé
        str_strip_whitespace=True,       # "  steady  " → "steady"
        frozen=False,                    # immuabilité via model_copy(update=...)
        json_schema_extra={"$schema_version": "1.0"},
    )

    @model_validator(mode="after")
    def _check_visible_when_targets(self) -> "HydroModelBase":
        """Vérifie que chaque VisibleWhen pointe vers un champ existant."""
        own_fields = set(self.model_fields)
        for field_name, info in self.model_fields.items():
            for meta in info.metadata:
                if isinstance(meta, VisibleWhen) and meta.field not in own_fields:
                    raise ValueError(
                        f"VisibleWhen on {type(self).__name__}.{field_name} "
                        f"references unknown sibling {meta.field!r}"
                    )
        return self
```

### 3.2 `HydroModPyConfig` — agrégateur racine `[REFACTORE]`

**Fichier** : `hydromodpy/core/config/hydromodpy_config.py`

```python
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.param_level import ParamLevel
# sous-configs...

class HydroModPyConfig(HydroModelBase):
    """Racine de la configuration HydroModPy.

    Le workflow est implicitement discriminé par les sections présentes :
      - [calibration] actif      → workflow "calibration"
      - [batch] actif            → workflow "batch"
      - [overview] seul          → workflow "overview"
      - [simulation] ou [flow]   → workflow "simulation" (default)
    """

    schema_version: Annotated[
        Literal["1.0"], ParamLevel("dev"),
    ] = Field(default="1.0", description="Version du schéma Pydantic.")

    run_id: Annotated[str | None, ParamLevel("user")] = Field(
        default=None,
        description="Identifiant de run ; déduit du nom du TOML si absent.",
    )

    workspace:   WorkspaceConfig   = Field(description="Workspace.")
    geographic:  GeographicConfig  = Field(description="Définition géographique.")
    grid:        GridConfig | None = Field(default=None, description="Grille spatiale.")
    domain:      DomainConfig      = Field(default_factory=DomainConfig)
    data:        DataConfig        = Field(default_factory=DataConfig)
    flow:        FlowConfig        = Field(default_factory=FlowConfig)
    transport:   TransportConfig | None = None
    simulation:  SimulationConfig  = Field(default_factory=SimulationConfig)
    solver:      SolverConfig      = Field(default_factory=SolverConfig)
    results:     ResultsConfig     = Field(default_factory=ResultsConfig)
    display:     DisplayConfig     = Field(default_factory=DisplayConfig)
    postprocess: PostprocessConfig = Field(default_factory=PostprocessConfig)

    calibration: CalibrationConfig | None = None
    batch:       BatchConfig       | None = None
    overview:    OverviewConfig    | None = None

    # ----- classmethods d'E/S -------------------------------------------

    @classmethod
    def from_toml(cls, path: Path | str) -> "HydroModPyConfig":
        """Lit un TOML, dérive les defaults contextuels, valide."""
        from hydromodpy.core.config.toml_io import load_toml_with_includes
        path = Path(path).resolve()
        raw = load_toml_with_includes(path)
        raw.setdefault("workspace", {}).setdefault("project_root", str(path.parent))
        raw.setdefault("run_id", path.stem.removeprefix("run_") or path.stem)
        return cls.model_validate(raw, context={"toml_path": path})

    def to_toml(self, path: Path | str, *, profile: str = "user") -> None:
        """Exporte vers TOML en respectant ParamLevel(profile)."""
        from hydromodpy.core.config.toml_io import dump_toml_with_comments
        dump_toml_with_comments(self, path, profile=profile)

    # ----- cross-section validation -------------------------------------

    @model_validator(mode="after")
    def _cross_section_consistency(self) -> "HydroModPyConfig":
        # engine ↔ packages cohérence
        engine = self.solver.engine
        packages = self.solver.packages
        if engine != packages.engine:
            raise ValueError(
                f"Incohérence : solver.engine={engine!r} mais "
                f"packages.engine={packages.engine!r}"
            )
        # transport actif exige un solveur compatible
        if self.transport is not None and engine == "boussinesq":
            raise ValueError("Boussinesq solver does not support [transport]")
        # calibration sans flow → incohérent
        if self.calibration is not None and not self.flow.param_list:
            raise ValueError("[calibration] requires [flow].param_list")
        return self

    @model_validator(mode="after")
    def _derive_missing_fields(self) -> "HydroModPyConfig":
        # run_id dérivé si absent (fait en from_toml, miroir ici pour
        # instantiation programmatique)
        return self
```

**Points clés** :
- `from_toml` fait **uniquement** lecture + 2 defaults simples (project_root, run_id). Tout le reste passe par Pydantic.
- `_cross_section_consistency` attrape les erreurs **avant** le solveur.
- `to_toml(profile=…)` permet le round-trip filtré par profil.

### 3.3 `FlowConfig` — processus d'écoulement `[REFACTORE]`

**Fichier** : `hydromodpy/process/flow/flow_config.py`

Refactor majeur : `FlowConfig` n'hérite plus de `ProcessSpatialConfig`.
`ProcessSpatialConfig` devient générique ou disparaît.

```python
from __future__ import annotations
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.process.flow.field_param import FlowFieldParam
from hydromodpy.process.flow.initial_conditions_config import FlowInitialCondition
from hydromodpy.process.flow.boundary_conditions_config import FlowBoundaryCondition
from hydromodpy.process.flow.sinks_sources_config import FlowSinkSource


FlowRegime = Literal["steady", "transient"]
RuntimeBackend = Literal["local", "scipy", "scipy_sparse", "petsc"]


class FlowRuntimeConfig(HydroModelBase):
    """Sous-section technique du solveur interne Boussinesq / partitionnement."""
    backend: Annotated[RuntimeBackend, ParamLevel("dev")] = "local"
    surface_model: Annotated[
        Literal["auto", "regularized_partition", "complementarity"],
        ParamLevel("dev"),
    ] = "auto"
    max_iterations: Annotated[int, ParamLevel("dev")] = Field(default=5000, ge=1, le=100_000)
    tol_residual_inf: Annotated[float, ParamLevel("expert")] = Field(default=1e-6, gt=0, le=1.0)
    tol_state_update_inf: Annotated[float, ParamLevel("expert")] = Field(default=1e-8, gt=0, le=1.0)


class FlowConfig(HydroModelBase):
    """Configuration du process d'écoulement."""

    flow_regime: Annotated[FlowRegime, ParamLevel("user")] = Field(
        default="transient",
        description="Régime d'écoulement (permanent ou transitoire).",
    )

    # IDs déclarés + leur payload
    param_list: Annotated[list[str], ParamLevel("user")] = Field(
        default_factory=list,
        description="Identifiants de paramètres physiques (K, Sy, Ss, ...).",
    )
    param: Annotated[dict[str, FlowFieldParam], ParamLevel("user")] = Field(
        default_factory=dict,
        description="Payload par paramètre (section [flow.param.<id>]).",
    )

    # Conditions initiales (obligatoire si transient)
    ic: Annotated[FlowInitialCondition | None, ParamLevel("user")] = None

    # Conditions aux limites par famille (cauchy/dirichlet/neumann)
    bc: Annotated[
        dict[Literal["cauchy", "dirichlet", "neumann"], dict[str, FlowBoundaryCondition]],
        ParamLevel("user"),
    ] = Field(default_factory=dict)

    # Sinks/sources discriminés par `kind` (recharge, well)
    sinks_sources: Annotated[
        dict[str, FlowSinkSource], ParamLevel("user"),
    ] = Field(default_factory=dict)

    active_bc: Annotated[list[str], ParamLevel("user")] = Field(default_factory=list)
    active_sinks_sources: Annotated[list[str], ParamLevel("user")] = Field(default_factory=list)

    runtime: Annotated[FlowRuntimeConfig, ParamLevel("dev")] = Field(
        default_factory=FlowRuntimeConfig,
    )

    # ----- validators ---------------------------------------------------

    @field_validator("param_list", mode="after")
    @classmethod
    def _normalize_param_list(cls, v: list[str]) -> list[str]:
        seen: list[str] = []
        for item in v:
            normalized = str(item).strip()
            if not normalized:
                raise ValueError("param_list contains an empty id")
            if normalized in seen:
                raise ValueError(f"param_list contains duplicate id {normalized!r}")
            seen.append(normalized)
        return seen

    @model_validator(mode="after")
    def _validate_param_payload_consistency(self) -> "FlowConfig":
        missing = [p for p in self.param_list if p not in self.param]
        if missing:
            raise ValueError(
                f"param_list declares {missing!r} but [flow.param.<id>] missing"
            )
        extras = [p for p in self.param if p not in self.param_list]
        if extras:
            raise ValueError(
                f"[flow.param.<id>] declared for {extras!r} but not in param_list"
            )
        return self

    @model_validator(mode="after")
    def _validate_ic_requirement(self) -> "FlowConfig":
        if self.flow_regime == "transient" and self.ic is None:
            raise ValueError("flow_regime=transient requires [flow.ic]")
        return self

    @model_validator(mode="after")
    def _validate_active_references(self) -> "FlowConfig":
        # `active_bc` doit référencer des familles.ids déclarées
        declared_bc = {
            f"{fam}.{id}" for fam, by_id in self.bc.items() for id in by_id
        }
        for name in self.active_bc:
            if name not in declared_bc and name not in {id for by_id in self.bc.values() for id in by_id}:
                raise ValueError(f"active_bc references unknown BC {name!r}")
        for name in self.active_sinks_sources:
            if name not in self.sinks_sources:
                raise ValueError(f"active_sinks_sources references unknown {name!r}")
        return self
```

**Différences vs l'existant** :
- Plus d'héritage de `ProcessSpatialConfig` (duplication supprimée).
- `runtime_*` regroupés sous `runtime: FlowRuntimeConfig`.
- Les 14 validators deviennent 4, plus lisibles.
- Plus de `from_toml_section` de 130 lignes — `from_toml` racine gère la lecture.

### 3.4 `TimeseriesVariableConfig` — facteur commun `[NOUVEAU]`

**Fichier** : `hydromodpy/data/variables/common/timeseries.py`

Remplace 14 fichiers quasi identiques (`etp`, `humidity`, `runoff`, …).

```python
from __future__ import annotations
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.data.common.sources import SourceSpec


class TimeseriesVariableConfig(HydroModelBase):
    """Base commune des variables point/station temporelles.

    Utilisée par : etp, humidity, runoff, soil_moisture, temperature, wind,
    precipitation, radiation, hydrometry, intermittency, piezometry, recharge.
    """

    # Dates (héritées de BaseVariableConfig actuel)
    date_start: Annotated[str | None, ParamLevel("user")] = Field(
        default=None, description="Date de début ISO-8601 (YYYY-MM-DD)."
    )
    date_end: Annotated[str | None, ParamLevel("user")] = Field(
        default=None, description="Date de fin ISO-8601 (YYYY-MM-DD)."
    )

    # Colonnes CSV standardisées (format SANDRE-like)
    col_id: Annotated[str, ParamLevel("dev")] = "id"
    col_x: Annotated[str, ParamLevel("dev")] = "x"
    col_y: Annotated[str, ParamLevel("dev")] = "y"
    col_crs: Annotated[str, ParamLevel("dev")] = "crs"
    col_datetime: Annotated[str, ParamLevel("dev")] = "datetime"
    col_value: Annotated[str, ParamLevel("dev")] = "value"
    default_crs: Annotated[str, ParamLevel("dev")] = "EPSG:4326"

    # Filtrage
    station_ids: Annotated[list[str] | None, ParamLevel("user")] = None
    extent: Annotated[
        Literal["watershed", "study_area"] | None, ParamLevel("user"),
    ] = None

    # Cache
    force_refresh: Annotated[bool, ParamLevel("dev")] = False

    # Sources discriminées
    sources: Annotated[list[SourceSpec], ParamLevel("user")] = Field(
        default_factory=list,
    )

    @field_validator("date_start", "date_end", mode="after")
    @classmethod
    def _validate_iso_date(cls, v: str | None) -> str | None:
        if v is None:
            return None
        from datetime import date
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"Date {v!r} is not valid ISO-8601") from exc
        return v

    @model_validator(mode="after")
    def _check_date_order(self) -> "TimeseriesVariableConfig":
        if self.date_start and self.date_end:
            if self.date_start > self.date_end:
                raise ValueError(
                    f"date_start ({self.date_start}) > date_end ({self.date_end})"
                )
        return self
```

**Spécialisations minimales** :

```python
# data/variables/piezometry/config.py  (10 lignes au lieu de 90)
class PiezometryConfig(TimeseriesVariableConfig):
    product: Annotated[Literal["level", "depth"], ParamLevel("user")] = "level"
    require_observations: Annotated[bool, ParamLevel("user")] = False
    sources: Annotated[list[PiezometrySourceSpec], ParamLevel("user")] = Field(
        default_factory=list,
    )

# data/variables/precipitation/config.py  (8 lignes au lieu de 65)
class PrecipitationConfig(TimeseriesVariableConfig):
    components: Annotated[
        list[Literal["liquid", "solid", "total"]], ParamLevel("user"),
    ] = Field(default_factory=lambda: ["total"])

# data/variables/etp/config.py  (3 lignes au lieu de 58)
class EtpConfig(TimeseriesVariableConfig):
    pass
```

**Gain quantifié** : ~800 lignes supprimées, ajout d'une variable = 5-10 lignes.

### 3.5 `FieldHomogeneousSection` — validation physique `[REFACTORE]`

**Fichier** : `hydromodpy/spatial/field/core/field_param_config.py`

```python
from __future__ import annotations
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.spatial.field.core.physical_bounds import (
    validate_physical_value, PHYSICAL_BOUNDS,
)


class FieldHomogeneousSection(HydroModelBase):
    """Payload `[flow.param.<id>.field_homogeneous]`.

    Valide que `value` respecte les bornes physiques du paramètre identifié
    par l'`id` du parent (K, Sy, Ss, n, vka).
    """

    value: Annotated[float | str, ParamLevel("user")] = Field(
        description="Valeur scalaire (numérique ou '<nb> <unité>').",
    )

    @field_validator("value", mode="before")
    @classmethod
    def _reject_bool(cls, v: object) -> object:
        if isinstance(v, bool):
            raise TypeError("value must be numeric, not bool")
        return v

    @model_validator(mode="after")
    def _validate_physical_bounds(self, info) -> "FieldHomogeneousSection":
        # Le parent (FieldBaseSection) injecte le `id` et l'`unit` via
        # context au moment de la construction.
        ctx = (info.context or {})
        param_id = ctx.get("param_id")
        unit = ctx.get("unit")
        if param_id and isinstance(self.value, (int, float)):
            validate_physical_value(
                param_id=param_id, unit=unit, value=float(self.value),
            )
        return self
```

Et la table centrale dans **`hydromodpy/spatial/field/core/physical_bounds.py`** :

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class PhysicalBound:
    expected_unit: str
    lo: float
    hi: float
    label: str

PHYSICAL_BOUNDS: dict[str, PhysicalBound] = {
    "k":     PhysicalBound("m/s",  1e-14, 1e2,  "hydraulic conductivity"),
    "kh":    PhysicalBound("m/s",  1e-14, 1e2,  "horizontal hydraulic conductivity"),
    "kv":    PhysicalBound("m/s",  1e-14, 1e2,  "vertical hydraulic conductivity"),
    "sy":    PhysicalBound("-",    1e-4,  0.5,  "specific yield"),
    "ss":    PhysicalBound("m-1",  1e-9,  1e-3, "specific storage"),
    "n":     PhysicalBound("-",    1e-3,  0.6,  "porosity"),
    "n_eff": PhysicalBound("-",    1e-3,  0.6,  "effective porosity"),
    "vka":   PhysicalBound("-",    1e-3,  1e2,  "vertical anisotropy K_v/K_h"),
}

def validate_physical_value(
    *, param_id: str, unit: str | None, value: float,
) -> float:
    bound = PHYSICAL_BOUNDS.get(param_id.lower())
    if bound is None:
        return value
    # (unit normalization via core.units.length / hydraulic_conductivity)
    if unit is not None and not _units_compatible(unit, bound.expected_unit):
        raise ValueError(
            f"{bound.label} (id={param_id!r}) expects unit "
            f"{bound.expected_unit!r}, got {unit!r}"
        )
    if not (bound.lo <= value <= bound.hi):
        raise ValueError(
            f"{bound.label} (id={param_id!r}) value {value} outside "
            f"[{bound.lo}, {bound.hi}]"
        )
    return value
```

---

## 4. Validation physique — tableau de contraintes

### 4.1 Paramètres hydrogéologiques

| Paramètre | Champ TOML (path) | Borne min | Borne max | Unité canonique | Message d'erreur |
|-----------|-------------------|:---------:|:---------:|:---------------:|------------------|
| **K** (cond. hydraulique) | `flow.param.K.field_homogeneous.value` | `1e-14` | `1e2` | m/s | `hydraulic conductivity (id='K') value {v} outside [1e-14, 1e2] m/s` |
| **Kh** (horizontal) | `flow.param.Kh.*` | `1e-14` | `1e2` | m/s | idem |
| **Kv** (vertical) | `flow.param.Kv.*` | `1e-14` | `1e2` | m/s | idem |
| **Sy** (porosité efficace) | `flow.param.Sy.field_homogeneous.value` | `1e-4` | `0.5` | — (adim.) | `specific yield (id='Sy') value {v} outside ]0, 0.5]` |
| **Ss** (emmagasinement) | `flow.param.Ss.field_homogeneous.value` | `1e-9` | `1e-3` | m⁻¹ | `specific storage (id='Ss') value {v} outside [1e-9, 1e-3] m^-1` |
| **n** (porosité totale) | `flow.param.n.field_homogeneous.value` | `1e-3` | `0.6` | — | `porosity (id='n') value {v} outside ]0, 0.6]` |
| **n_eff** (porosité efficace) | idem | `1e-3` | `0.6` | — | idem |
| **vka** (anisotropie) | `solver.packages.process_specific.vka` | `1e-3` | `1e2` | — | `vertical anisotropy Kv/Kh must be in [1e-3, 1e2]` |
| **T** (transmissivité) | `solver.packages.boussinesq.T` | `1e-10` | `1e3` | m²/s | `transmissivity value outside [1e-10, 1e3] m^2/s` |
| **Recharge** constante | `flow.sinks_sources.recharge.values` | `-5000` | `+5000` | mm/jour | `recharge value {v} mm/day is unphysical` |

### 4.2 Paramètres géométriques

| Paramètre | Champ TOML | Contrainte | Message |
|-----------|-----------|-----------|---------|
| `thickness` (aquifère) | `domain.depth_model.thickness` | `> 0` | `aquifer thickness must be > 0 m` |
| `nx`, `ny` | `grid.planar.{nx,ny}` | `>= 1` | `grid dimension must be >= 1` |
| `nlay` | `grid.vertical.nlay` | `>= 1` | `nlay must be >= 1` |
| `lay_proportions` | `grid.vertical.lay_proportions` | `sum == 1 ± 1e-6`, all > 0 | `lay_proportions must sum to 1.0 ± 1e-6` |
| `dx`, `dy` (synthétique) | `geographic.synthetic.grid.*` | `dx ≈ dy ± 5 %` | `synthetic grid requires quasi-square cells` |
| `snap_dist` | `geographic.snap_dist` | `> 0`, `<= 10 km` | `snap_dist must be in ]0, 10 km]` |
| `buff_area` (numérique) | `geographic.buff_area` | `0 < x < 100 %` | `buff_area percentage must be in ]0, 100[%` |

### 4.3 Paramètres temporels

| Paramètre | Champ TOML | Contrainte | Message |
|-----------|-----------|-----------|---------|
| `step_value` | `simulation.time.step_value` | `>= 1` | `step_value must be >= 1` |
| `start_datetime` | `simulation.time.start_datetime` | ISO valide | `start_datetime not valid ISO-8601` |
| `start < end` | `simulation.time.*` | relation | `start_datetime must be before end_datetime` |
| `nwt_headtol` | `solver.packages.nwt_headtol` | `1e-8 <= x <= 1.0` | `nwt_headtol outside physical range [1e-8, 1] m` |
| `nwt_fluxtol` | `solver.packages.nwt_fluxtol` | `1e-4 <= x <= 1e5` | `nwt_fluxtol outside physical range` |
| `mf6_outer_dvclose` | `solver.packages.mf6_outer_dvclose` | `1e-10 <= x <= 1.0` | idem |

### 4.4 Paramètres de solveur numérique

| Paramètre | Champ TOML | Contrainte | Message |
|-----------|-----------|-----------|---------|
| `exdp` (MODFLOW EVT) | `solver.packages.exdp` | `> 0` | déjà présent |
| `nwt_maxiterout` | `solver.packages.nwt_maxiterout` | `1 <= x <= 1e5` | `nwt_maxiterout out of range` |
| `tol_residual_inf` | `flow.runtime.tol_residual_inf` | `> 0`, `<= 1` | idem |

### 4.5 CRS et chemins

| Paramètre | Champ TOML | Contrainte | Message |
|-----------|-----------|-----------|---------|
| `crs_project` | `geographic.crs_project` | parseable par `pyproj.CRS.from_user_input` | `crs_project {v!r} is not a valid CRS (pyproj)` |
| `dem_init_path` | `geographic.dem_init_path` | `Path.exists()` **si** mode `standard` et pas de bootstrap | `DEM file not found: {path}` |

**Mécanisme d'application** : chaque validateur est monté en `@model_validator(mode="after")` ou via un `Annotated[T, AfterValidator(check_fn)]`. Les bornes sont dans une table centrale `PHYSICAL_BOUNDS` (§3.5).

---

## 5. Système de profils `user` / `dev` / `expert`

### 5.1 Décision : **conserver `ParamLevel`** avec modifications

**Verdict de l'audit** (§1.2 de 02_core_config.md) : non-standard mais justifié. Le projet utilise le tandem `(ParamLevel, VisibleWhen)` pour :
1. Générer un template TOML commenté progressif.
2. Piloter l'UI Streamlit auto-générée.

Aucun standard (`Hydra`, `pydantic-settings`, `Dynaconf`) ne fournit ce cas d'usage sans code équivalent. **On conserve.**

### 5.2 Améliorations à apporter

| Amélioration | Justification |
|--------------|---------------|
| `ParamLevel` → `IntEnum` plutôt que `Literal` + dict | Comparaison numérique native (`level >= Profile.DEV`) |
| `VisibleWhen` validé au chargement du modèle | `_check_visible_when_targets` dans `HydroModelBase` |
| Profils comparables | `Profile.USER < Profile.DEV < Profile.EXPERT` |
| Nouvelle classe `Profile(IntEnum)` dans `core/config/profile.py` | Centralise l'ordre |

### 5.3 Squelette `[NOUVEAU]`

**Fichier** : `hydromodpy/core/config/profile.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum


class Profile(IntEnum):
    """Profils hiérarchiques de visibilité des champs."""
    USER = 1       # hydrogéologue : physique + paths
    DEV = 2        # développeur : tolérances, backends
    EXPERT = 3     # expert MODFLOW/Boussinesq : paramètres internes

    @classmethod
    def from_name(cls, name: str) -> "Profile":
        return cls[name.upper()]


@dataclass(frozen=True)
class ParamLevel:
    """Métadonnée attachée via Annotated[T, ParamLevel("user")]."""
    profile: Profile

    def __init__(self, level: str) -> None:
        object.__setattr__(self, "profile", Profile.from_name(level))

    def visible_in(self, active: Profile) -> bool:
        return active >= self.profile


@dataclass(frozen=True)
class VisibleWhen:
    """Conditional visibility : champ visible si `sibling` ∈ `values`."""
    field: str
    values: str | tuple[str, ...]

    def matches(self, actual: str) -> bool:
        return actual == self.values if isinstance(self.values, str) else actual in self.values
```

### 5.4 Trois profils — comportement cible

| Profil | Champs visibles (dans TOML généré) | Cas d'usage |
|--------|-------------------------------------|-------------|
| `user` | Paths, unités physiques, régime, Literal métier | 80 % des utilisateurs — lance une simulation standard |
| `dev` | + tolérances solveur, backends, colonnes CSV | Développeur qui teste un nouveau forçage |
| `expert` | + paramètres MODFLOW internes (NEVTOP, IPHDRY, LAYVKA, HNOFLO, ...) | Ajustement fin par un expert MODFLOW |

### 5.5 CLI cible

```bash
hmp config ./out.toml --profile user       # ~60 lignes, champs `user` seuls
hmp config ./out.toml --profile dev        # ~200 lignes, `user` + `dev`
hmp config ./out.toml --profile expert     # ~600 lignes, tout
hmp schema export --out schema.json        # JSON Schema pour IDE
```

**Génération TOML** : `generate_toml.py` utilise `model_fields[f].metadata` pour filtrer. Utilisation de **`tomlkit`** au lieu du mini-sérializer maison (préserve commentaires, formats, ordre).

---

## 6. Comparaison modèle actuel → modèle cible

### 6.1 Actions par modèle (vue synthétique)

| Modèle actuel | Modèle cible | Action | Justification |
|---------------|--------------|:------:|---------------|
| `BaseModel` (partout) | `HydroModelBase` | **NOUVEAU** | Centralise `extra="forbid"`, `serialize_by_alias`, `populate_by_name`, validator `VisibleWhen` |
| `HydroModPyConfig` | `HydroModPyConfig` | **REFACTORE** | `from_toml` → lecture minimale + `@model_validator(mode="before")`. Ajouter cross-section validator |
| `WorkspaceConfig` | `WorkspaceConfig` | **CONSERVE** | Déjà bon (extra="forbid", découverte auto) |
| `GeographicConfig` | `StandardGeographicConfig` + `SyntheticGeographicConfig` | **REFACTORE** | Split en discriminated union sur `source_mode` |
| `ProcessSpatialConfig` | `ProcessConfig[IC, BC, SS, P]` ou supprimé | **REFACTORE** | Générique OU composition dans `FlowConfig`/`TransportConfig` |
| `FlowConfig ← ProcessSpatialConfig` | `FlowConfig` (sans héritage) | **REFACTORE** | Suppression héritage redondant ; fusion runtime_* → `runtime: FlowRuntimeConfig` |
| `InitialCondition` (base) | Supprimée | **SUPPRIME** | Remplacée par `FlowInitialCondition` directement (générique inutile avec `object`) |
| `BoundaryCondition` (base) | Supprimée | **SUPPRIME** | Remplacée par `FlowBoundaryCondition` (plus de `type: str`, discriminated union) |
| `SinkSource` (base) | `FlowSinkSource` (discriminated union : recharge/well) | **REFACTORE** | `kind: Literal["recharge","well"]` |
| `FlowRechargeConfig` | `FlowRechargeConfig` | **REFACTORE** | `values: Any` → `forcing: Forcing` (discriminated). Suppression `heterogeneous_source: Any` |
| `FlowWellConfig` | `FlowWellConfig` | **REFACTORE** | 3 modes de localisation → discriminated `location: LocationSpec` |
| `FlowBoundaryForcing{Constant,Csv}Config` + `FlowWellForcing*Config` | `Forcing` (discriminated) | **REFACTORE** | Fusion en un seul module `process/base/forcing.py` |
| `Modflow6Config` | `Modflow6Packages` | **RENOMME** | Fusionne `runtime` + `process_specific` sous un parent `Modflow6Packages` |
| `ModflowConfig` (NWT) | `ModflowNwtPackages` | **RENOMME** | Idem |
| `Modflow6SpecifParams` / `ModflowSpecifParams` (dataclass) | Supprimées | **SUPPRIME** | Redondant avec `model.model_dump()` |
| `SolverConfig` | `SolverConfig` | **REFACTORE** | Ajoute `packages: ModflowNwtPackages | Modflow6Packages | BoussinesqPackages` (discriminated) |
| `TMeshConfigModel` | `TMeshConfig` | **RENOMME** | Suffixe `Model` = reliquat v1. Sinon bien. |
| `TMeshCaseScenarioConfig ← TMeshConfigModel` | `TMeshCaseScenario` (par composition) | **REFACTORE** | `tmesh: TMeshConfig` au lieu d'héritage |
| `SGridConfig` + `MeshCatchmentConfigSchema` | `GridConfig` (discriminated `kind`) | **REFACTORE** | Unification ; suffixe `Schema` retiré |
| `VerticalGridConfig`, `PlanarGridConfig` | idem, renommés `CartesianVerticalConfig`, `CartesianPlanarConfig` | **RENOMME** | Plus explicite |
| `ZoneMeshingSettings` + sous-classes | idem avec suffixes `…Schema` → `…Config` | **REFACTORE** | Nettoyage reliquat v1 |
| `DomainConfig` | `DomainConfig` | **CONSERVE** | Mais lever `ValueError` sur doublons de `zone_ids` au lieu de dédupliquer |
| `DomainSupportConfig` (discriminated) | idem | **CONSERVE** | Référence projet |
| `DepthModelConfig` (discriminated) | idem | **CONSERVE** | |
| `FieldParamConfig` + `FieldHomogeneousSectionSchema` | `FlowFieldParam` + `FieldHomogeneousSection` | **REFACTORE** | Ajout validation physique `PHYSICAL_BOUNDS`. Suppression suffixe `Schema` |
| `BaseVariableConfig` | `BaseVariableConfig` | **CONSERVE** | Centralise dates |
| `DataManagersConfig` | `DataConfig` | **RENOMME** | Plus court, plus clair. Registre `DATA_TYPE_MODELS` pour éliminer `model_rebuild()` |
| `EtpConfig`, `HumidityConfig`, `RunoffConfig`, `SoilMoistureConfig`, `TemperatureConfig`, `WindConfig` | `EtpConfig = TimeseriesVariableConfig` (+ alias) | **REFACTORE** | Factorisation → ~400 lignes supprimées |
| `PrecipitationConfig`, `RadiationConfig` | héritent `TimeseriesVariableConfig` + `components` | **REFACTORE** | ~130 lignes supprimées |
| `HydrometryConfig`, `IntermittencyConfig`, `PiezometryConfig` | héritent + `product`, etc. | **REFACTORE** | ~270 lignes supprimées |
| `RechargeConfig` | hérite + `SyntheticForcing` discriminated | **REFACTORE** | Intègre `Forcing` |
| `DemConfig`, `GeologyConfig`, `HydrographyConfig`, `OceanicConfig`, `WaterQualityConfig` | **CONSERVE** | Non-timeseries, justifiés |
| `SimulationTimeConfig` | `SimulationTimeConfig` | **CONSERVE** | Excellent |
| `ResultsConfig` + sous-classes | **CONSERVE** | |
| `DisplayConfig` + sous-classes | **CONSERVE** | |
| `PostprocessConfig` + sous-classes | **CONSERVE** | |
| `CapabilityGalleryConfig` | **CONSERVE** | |
| `MethodComparisonConfig` | **CONSERVE** | |
| `CalibrationEngineConfig` | **CONSERVE** | Référence du projet |
| `ParamLevel` | `Profile(IntEnum)` + `ParamLevel` | **REFACTORE** | Passage en IntEnum (§5.3) |
| `VisibleWhen` | **CONSERVE** + validation au chargement | `_check_visible_when_targets` |
| `toml_loader._repair_path_like_basic_strings` | Supprimé | **SUPPRIME** | Contourne un bug utilisateur ; lever une erreur claire à la place |
| 3 helpers `resolve_path` | `core/config/path_resolution.resolve_declared_path` | **REFACTORE** | Un seul module |
| `generate_toml._fmt` (mini-serializer) | `tomlkit` | **REFACTORE** | Standard externe, gère commentaires |

### 6.2 Métriques de réduction attendues

| Zone | Lignes actuelles | Lignes cibles | Gain |
|------|:---------------:|:-------------:|:----:|
| `data/variables/{etp,humidity,runoff,soil_moisture,temperature,wind}/config.py` | ~408 | ~30 | **-378** |
| `data/variables/{precipitation,radiation}/config.py` | ~130 | ~20 | **-110** |
| `data/variables/{hydrometry,intermittency,piezometry}/config.py` | ~270 | ~50 | **-220** |
| `process/flow/boundary_conditions.py` + `sinks_sources.py` (Forcing) | ~200 | ~100 | **-100** |
| `solver/modflow{6,}_config.py` (dataclasses miroir) | ~60 | 0 | **-60** |
| `FlowConfig.from_toml_section` | ~130 | ~20 | **-110** |
| `HydroModPyConfig.from_toml` | ~90 | ~20 | **-70** |
| `generate_toml._fmt`, `_placeholder` | ~200 | ~50 (via `tomlkit`) | **-150** |
| **Total** | | | **≈-1 200 lignes** |

### 6.3 Nouveaux fichiers à créer `[NOUVEAU]`

```
hydromodpy/core/config/
    base.py                     # HydroModelBase
    profile.py                  # Profile(IntEnum), ParamLevel, VisibleWhen
    toml_io.py                  # load_toml_with_includes, dump_toml_with_comments
    physical_bounds.py          # PHYSICAL_BOUNDS + validate_physical_value
    pydantic_introspect.py      # helpers mutualisés (anti-duplication §1.4 audit)

hydromodpy/data/common/
    registry.py                 # DATA_TYPE_MODELS + @register decorator
    sources.py                  # SourceSpec discriminée

hydromodpy/data/variables/common/
    timeseries.py               # TimeseriesVariableConfig

hydromodpy/process/base/
    forcing.py                  # ConstantForcing | CsvForcing | SyntheticForcing
```

### 6.4 Fichiers à supprimer

| Fichier | Raison |
|---------|--------|
| `hydromodpy/process/base/initial_conditions.py` (classe `InitialCondition`) | Classe abstraite trop générique (`object`) |
| `hydromodpy/process/base/boundary_conditions.py` (classe `BoundaryCondition`) | idem |
| `hydromodpy/process/base/sinks_sources.py` (classe `SinkSource`) | idem |
| `solver/modflow6/…` dataclass `Modflow6SpecifParams` | Redondant |
| `solver/modflow_nwt/…` dataclass `ModflowSpecifParams` | Redondant |
| `core/config/toml_loader._repair_path_like_basic_strings` | Masque un bug utilisateur |

---

## 7. Round-trip TOML → Pydantic → TOML

### 7.1 Contrat

```python
# invariant attendu
original = Path("config.toml").read_text()
cfg = HydroModPyConfig.from_toml("config.toml")
cfg.to_toml("config_rt.toml", profile="expert")
roundtrip = Path("config_rt.toml").read_text()

# pour tout champ f de profil ≤ expert :
assert extract_value(original, f) == extract_value(roundtrip, f)
```

### 7.2 Outils

| Besoin | Outil | Justification |
|--------|-------|---------------|
| Lire TOML | `tomllib` (stdlib) | Pas de dépendance |
| Écrire TOML avec commentaires | `tomlkit` | Préserve l'ordre et les commentaires lors des round-trip |
| Sérialiser `Path` en chemin relatif | `json_encoders={Path: str}` dans `ConfigDict` + helper `_relativize(base_dir)` | Round-trip portable |
| Gérer `datetime` | `datetime.isoformat()` | `tomllib` parse nativement `2020-01-01T00:00:00` |

### 7.3 Helper `[NOUVEAU]`

```python
# core/config/toml_io.py
import tomlkit
from pathlib import Path

def dump_toml_with_comments(
    model: HydroModelBase,
    path: Path | str,
    *,
    profile: str = "user",
    base_dir: Path | None = None,
) -> None:
    """Dump Pydantic → TOML avec commentaires par ParamLevel."""
    path = Path(path)
    doc = tomlkit.document()
    _render_section(doc, model, profile=Profile.from_name(profile), base_dir=base_dir)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
```

Le contenu de `_render_section` itère sur `model_fields`, filtre par
`ParamLevel`, gère les `BaseModel` imbriqués, les `Literal` (émet un commentaire
`# one of: ...`), et relativise les `Path`.

---

## 8. JSON Schema — intégration IDE

### 8.1 Export

```bash
hmp schema export --out .hydromodpy-schema.json     # JSON Schema
hmp schema export --taplo-config                    # config taplo (VSCode)
```

### 8.2 Intégration VSCode (`even-better-toml`)

Le projet fournit `.taplo.toml` :

```toml
[schema]
path = ".hydromodpy-schema.json"
enabled = true

[[rule]]
include = ["**/*.toml"]
keys    = ["workspace.*", "flow.*", "data.*", "simulation.*"]
```

Résultat : **auto-complétion TOML avec description des champs + validation en temps réel** dans l'IDE.

### 8.3 CI

Un job GitHub Actions (`.github/workflows/schema.yml`) vérifie que le JSON Schema exporté est à jour vs les modèles Pydantic. Fail si `hmp schema export` produit un diff non committé.

---

## 9. Plan d'implémentation (4 phases, ~4-5 semaines)

| Phase | Livrables | Durée | Prérequis |
|-------|-----------|:-----:|-----------|
| **P0 — Fondations** | `HydroModelBase`, `Profile(IntEnum)`, `PHYSICAL_BOUNDS`, `TimeseriesVariableConfig` | 1 sem | — |
| **P1 — Refactor critique** | Migration `FlowConfig`, `data/variables/*`, `Forcing`, `FieldHomogeneousSection` (validation physique) | 1-2 sem | P0 |
| **P2 — Renommages & structuration** | `GridConfig` unifié, `SolverConfig.packages` discriminé, suppression suffixes `Schema`, suppression dataclasses miroir | 1 sem | P1 |
| **P3 — Tooling** | `tomlkit` round-trip, JSON Schema export, integration `.taplo.toml`, migration script | 1 sem | P2 |

### 9.1 Checklist de qualité par modèle migré

- [ ] Hérite de `HydroModelBase` (`extra="forbid"` automatique)
- [ ] Chaque champ a `Annotated[T, ParamLevel("…"), Field(description=…)]`
- [ ] Validation physique via `@model_validator(mode="after")` ou `AfterValidator`
- [ ] Discriminated union plutôt que `if isinstance`
- [ ] Pas de `from_toml_section` (déplacé dans `HydroModPyConfig.from_toml`)
- [ ] Pas de `dict[str, Any]` / `object` dans le schéma public
- [ ] Test unitaire pour `model_dump(mode="json") == load(model_dump_json())`
- [ ] Test round-trip TOML (dump puis reload produit le même modèle)

---

## 10. Résumé exécutif

| Axe | État actuel | Cible |
|-----|-------------|-------|
| **Typage** | `object`, `Any`, `dict[str, object]` dans `process/base`, `FlowRechargeConfig.values` | `Literal`, `Annotated`, `Path`, `datetime` partout ; discriminated unions |
| **Validation physique** | Absente sur K/Sy/Ss/n/vka | `PHYSICAL_BOUNDS` centralisé, appliqué via `@model_validator(mode="after")` |
| **Duplication** | ~1 100 lignes dupliquées (dont ~800 en `data/variables/`) | Facteurs communs (`TimeseriesVariableConfig`, `Forcing`) → -1 200 lignes |
| **Héritage** | `FlowConfig ← ProcessSpatialConfig` (redéfinit 100 % des champs) | Composition ou générique `ProcessConfig[IC, BC, SS, P]` |
| **Profils** | `ParamLevel("user"\|"dev"\|"expert")` via dict | `Profile(IntEnum)` + `ParamLevel`, comparable numériquement |
| **Round-trip TOML** | Mini-sérializer maison, pas de commentaires préservés | `tomlkit`, support des commentaires, `serialize_by_alias` global |
| **IDE / schéma** | Non exporté | JSON Schema autogénéré + `.taplo.toml` pour auto-complétion VSCode |
| **Sections racine** | 16 plates, certaines pour éléments solveur bas-niveau | 10 sections user + `solver.packages` discriminé pour les détails solveur |
| **Agrégateur `from_toml`** | 70 lignes de logique dans un classmethod | 20 lignes de lecture + `@model_validator(mode="before")` |
| **Cohérence cross-section** | Aucune | `solver.engine ↔ solver.packages.engine`, `flow_regime=transient ⇒ ic requis`, etc. |

**Effort global estimé** : ~4-5 semaines pour un dev Pydantic v2 senior.
**Gain principal** : **config robuste physiquement + -1 200 lignes + auto-complétion IDE**.

---

## 11. Ce qu'on ne fait *pas*

Pour clarifier le périmètre :

1. **Pas de migration vers Hydra/OmegaConf** — le projet a besoin de `tomlkit` + `Pydantic v2`, pas d'une couche supplémentaire.
2. **Pas de schéma SQL séparé** — DuckDB stocke le `model_dump_json()` du `HydroModPyConfig` dans la colonne `config_snapshot`. Reproductibilité assurée.
3. **Pas de *runtime overrides* CLI** (type `hmp run cfg.toml +flow.flow_regime=transient`) en phase initiale. Utile mais non prioritaire.
4. **Pas de multi-environnement** (`env=dev/prod`) — un projet = un TOML. Les overrides ponctuels via env vars `HYDROMODPY_*` (paths + flags CI) uniquement.

---

## 12. Unités via pydantic-pint (adopté en P03)

**Décision** : pydantic-pint est **adopté comme dépendance core** et remplace `normalize_m_per_s_unit` ainsi que `units/conversions.py`.

**Motivation** :
- Remplace du code maison brittle par une librairie éprouvée (pint, ~10 ans de maturité scientifique).
- Permet l'expression d'unités physiques directement dans les types Pydantic.
- Zéro régression : tout ce que fait `normalize_m_per_s_unit` est un cas particulier de pint.
- Dépendance acceptable (pint est léger, pas de compilation native).

**Structure** :

```
hydromodpy/core/units/
├── __init__.py          Exports : HydraulicConductivity, SpecificYield, …
├── registry.py          UnitRegistry pint avec unités hydrogéologiques
│                        (m, m/s, mm/day, m3/s, m3/day, degC, Pa·s, -, etc.)
└── types.py             Types annotés Pydantic :
                            HydraulicConductivity = Annotated[PintQuantity, "m/s"]
                            SpecificYield = Annotated[float, Ge(0), Le(1)]
                            SpecificStorage, Length, FlowRate, Area, Volume, Time
```

**Exemple d'utilisation** :

```python
from typing import Annotated
from pydantic import BaseModel, Field
from hydromodpy.core.units import HydraulicConductivity, SpecificYield

class FlowProperties(BaseModel):
    k_aquifer: HydraulicConductivity = Field(
        default="1e-4 m/s",
        description="Conductivité hydraulique de l'aquifère",
        json_schema_extra={"widget_type": "input", "unit": "m/s",
                           "display_name_fr": "Conductivité hydraulique"},
    )
    specific_yield: SpecificYield = Field(
        default=0.1,
        description="Porosité efficace",
    )
```

**Format TOML accepté (rétrocompatibilité)** :

```toml
[flow.properties]
# Accepte valeur numérique sans unité (fallback sur unité canonique m/s)
k_aquifer = 1e-4

# OU expression explicite avec unité
k_aquifer = "0.0001 m/s"
k_aquifer = "0.36 m/h"       # converti automatiquement en m/s
```

**Migration** : en phase P03, on refactore `flow_config.py` d'abord (le plus critique), puis les autres modules en P04-P09.
