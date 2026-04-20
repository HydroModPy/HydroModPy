# 13 — Cohérence globale de l'architecture cible HydroModPy

**Auteur** : Architecte système senior (gardien de cohérence inter-phases 01→12)
**Date** : 2026-04-18
**Branche** : `dev-database` (HEAD `74b62878`)
**Portée** : Vérification et arbitrage final des interfaces, du nommage, du flux de données et des cas d'usage.

---

## 0. Résumé exécutif

Les 12 documents de phase livrent une architecture **globalement cohérente dans ses principes** (Protocols plutôt qu'ABC, registres uniques, storage UGRID+Zarr unifié, Pydantic v2 uniformisé, CLI unifiée `hmp`, parité Python↔REST). Cependant, leur production **en parallèle et par experts différents** a généré **42 incohérences concrètes** documentées plus bas, dont :

- **13 incohérences d'interface critiques** (signatures de `solve()/execute()`, types de retour `SolveResult`/`SolveReport`, ordre `(sim, obs)` vs `(obs, sim)`, méthodes d'accès `catalog.get/find/simulation/best`…),
- **7 incohérences de nommage majeur** (`Simulation` dédoublé, `DataPlanner` vs `DataManagersPlanner`, `ParamSpace` vs `ParameterSpace`…),
- **4 refontes TOML concurrentes** de la section `[data]` (phase 02 → `[observations]+[recharge]` ; phase 12 → `[data.<variable>]`),
- **3 familles CLI orphelines** (`hmp data`, `hmp api`, `hmp lock`, `hmp test goldens`) non intégrées dans l'arborescence principale de phase 10.

Ce document **tranche** chacune de ces divergences et produit **une référence unique opposable** : toute phase devra s'aligner sur les décisions ci-dessous avant implémentation.

**Verdict par phase** (détail en §11) :

| Phase | Sujet | Statut cohérence | Actions requises |
|---:|---|:-:|---|
| 01 | Structure packages | 🟢 Cohérent | Aucune (référence transversale) |
| 02 | Config Pydantic | 🟠 À clarifier | Réconcilier section `[data]` avec phase 12 |
| 03 | Contrats de données | 🟢 Cohérent | Aucune |
| 04 | Storage DuckDB+Zarr | 🟢 Cohérent | Harmoniser `write_field` signature (cf. §1.3) |
| 05 | Contrats solveurs | 🟠 À clarifier | `solve()` vs `execute()` ; `SolveResult` vs `SolveReport` |
| 06 | Pipeline exécution | 🟠 À clarifier | Aligner sur types de phase 05 |
| 07 | Calibration | 🟠 À clarifier | `(obs, sim)` vs `(sim, obs)` ; `Pipeline.default` ; `ParameterSpace` |
| 08 | Postprocess display | 🟠 À clarifier | `sim.plot()` vs `figures.get(name).plot(sim)` ; noms de champs dérivés |
| 09 | Tests idéaux | 🟢 Cohérent | `hmp test` supprimé, `hmp test goldens` conservé (non contradictoire) |
| 10 | UX CLI | 🟠 À clarifier | Intégrer `hmp data`, `hmp api`, `hmp lock` dans l'arborescence |
| 11 | Frontend-ready | 🟠 À clarifier | UUID v4 vs v5 ; `run_id` vs `sim_id` |
| 12 | Input data | 🟠 À clarifier | `DataPlanner` (vs `DataManagersPlanner`) ; TOML `[data.<var>]` vs phase 02 |

---

## 1. Cohérence des interfaces

### 1.1 Solveur (phase 05) ↔ Store (phase 04)

#### Constat

Trois signatures concurrentes ont été produites pour le retour du solveur :

| Doc | Symbole | Signature |
|---|---|---|
| 05 | `SolverRunner.solve() -> SolveResult` | `SolveResult(output_dir, converged, iterations, wall_time_s, diagnostics, residual)` |
| 06 | `SolverRunner.execute(plan, domain, store)` | encapsule `RunResult(run_id, solver_name, exit_status, solver_output_dir, primary_model_ref, logs, mass_balance)` dans un `SolveReport(runs, wall_seconds, solver_binary_sha256s)` |
| 05 vs 06 | `ResultExtractor.extract(ctx: ExtractContext)` | vs `ResultExtractor.extract(report, store)` — **incompatible** |

Idem pour l'écriture dans le Zarr : phase 05 §5.3 utilise `store.write_field(sim_id, "derived/watertable_depth", depth)` (positional) ; phase 05 §9.5 utilise `ctx.store.write_field(ctx.sim_id, "head", timestep=0, values=..., n_timesteps=1)` (keyword).

#### Décision normative

**Adopter la signature de phase 05** comme canonique (cycle de vie solveur = `setup → build → solve → cleanup`) et y aligner phase 06.

```python
# hydromodpy/solver/contracts/runner.py  [REFACTORE]
from typing import Protocol, runtime_checkable

@runtime_checkable
class SolverRunner(Protocol):
    ctx: RunContext

    def setup(self) -> None: ...
    def build(self) -> None: ...
    def solve(self) -> SolveResult: ...
    def cleanup(self) -> None: ...


@dataclass(frozen=True, slots=True)
class SolveResult:
    output_dir: Path
    converged: bool
    iterations: int | None
    wall_time_s: float
    diagnostics: dict[str, Any] = field(default_factory=dict)
    residual: float | None = None
```

**Conséquence phase 06** : `SolveReport` et `RunResult` sont des **agrégateurs** du pipeline (plusieurs `SolveResult` en séquence, ex. flow → transport → particles) et non pas du solveur individuel. Renommer :

```python
# hydromodpy/simulation/pipeline/steps/step_08_solve.py  [REFACTORE]
@dataclass(frozen=True, slots=True)
class PipelineSolveReport:                 # ex-SolveReport
    runs: tuple["PipelineRunEntry", ...]   # ex-RunResult
    wall_seconds: float
    solver_binary_sha256s: dict[str, str]

@dataclass(frozen=True, slots=True)
class PipelineRunEntry:
    run_id: str
    solver_name: str
    process_kind: ProcessKind
    exit_status: Literal["ok", "diverged", "timeout", "failed"]
    solve_result: SolveResult          # ← agrégat du retour de SolverRunner.solve()
    primary_model_ref: str
    logs: tuple[LogLine, ...]
    mass_balance: MassBalance | None
```

**Extracteur canonique** :

```python
# hydromodpy/solver/contracts/extractor.py  [CONSERVE]
@runtime_checkable
class ResultExtractor(Protocol):
    supported: frozenset[ProcessKind]

    def extract(self, ctx: ExtractContext) -> None: ...
    def derive(self, ctx: ExtractContext, flags: "DerivedFlags") -> None: ...
```

Phase 06 doit consommer `ExtractContext` (pas `(report, store)`).

#### Signature canonique unique de `SimulationCatalog.write_field`

```python
# hydromodpy/results/catalog.py  [REFACTORE]
def write_field(
    self,
    sim_id: UUID,
    name: str,              # "head", "concentration", "derived/watertable_depth", ...
    values: np.ndarray,     # shape (n_time, n_layer, n_face) ou (n_layer, n_face) steady
    *,
    timestep: slice | int | None = None,   # None = écrasement complet
    chunk_time: int = 1,
    attrs: Mapping[str, Any] | None = None,
) -> None: ...
```

Les **deux exemples divergents** de phase 05 sont ainsi unifiés : le cœur dérivé (`derived/watertable_depth`) appelle `write_field(sim_id, name, values)` avec `timestep=None` ; l'écriture incrémentale step-par-step appelle `write_field(sim_id, name, values, timestep=t)`.

### 1.2 Store (phase 04) ↔ Contrats (phase 03)

Phase 03 définit la structure UGRID-1.0 (`HydroMesh` avec `node_x`, `node_y`, `face_node`, `z_interfaces`, `topology`). Phase 04 écrit ces exacts champs dans `simulations/<uuid>.zarr/mesh/`. **Cohérent**.

Le seul ajustement : phase 04 utilise le nom de groupe `mesh/face_node_connectivity` alors que phase 03 le nomme `face_node` dans la dataclass Python. **Décision** : conserver `face_node` comme attribut Python et `face_node_connectivity` comme nom CF/UGRID dans le Zarr (mapping explicite dans `HydroMesh.to_xarray_dataset()`).

### 1.3 Figures (phase 08) ↔ Store (phase 04)

#### Constat

Phase 05 écrit les champs dérivés sous `derived/watertable_elevation`, `derived/watertable_depth`, `derived/seepage_areas`. Phase 08 consomme `sim.field("watertable_depth")` (sans préfixe), `sim.field("seepage_areas_m_per_day")` (avec suffixe d'unité), `sim.field("recharge_m_per_day")`. **Mismatch d'aliasing**.

Par ailleurs, phase 05 décrit `derived/seepage_areas` comme `uint8 mask`, phase 08 consomme `seepage_areas_m_per_day` (un **flux**).

#### Décision normative

**Un seul vocabulaire de champs**, exposé dans un registre central (`hydromodpy/results/field_registry.py` [NOUVEAU]) :

```python
# hydromodpy/results/field_registry.py  [NOUVEAU]
@dataclass(frozen=True, slots=True)
class FieldDescriptor:
    public_name: str         # "watertable_depth"  ← utilisé par les figures
    zarr_path: str           # "derived/watertable_depth"  ← dans le Zarr
    cf_standard_name: str    # "depth_of_water_table_below_land_surface"
    udunits: str             # "m"
    shape: Literal["(time, layer, face)", "(time, face)", "(layer, face)", "(face,)"]
    derived_by: Literal["solver", "core"]

REGISTRY: dict[str, FieldDescriptor] = {
    "head":                      FieldDescriptor("head", "head", "groundwater_head_above_reference_level", "m", "(time, layer, face)", "solver"),
    "watertable_elevation":      FieldDescriptor("watertable_elevation", "derived/watertable_elevation", "water_table_altitude", "m", "(time, face)", "core"),
    "watertable_depth":          FieldDescriptor("watertable_depth", "derived/watertable_depth", "depth_of_water_table_below_land_surface", "m", "(time, face)", "core"),
    "seepage_mask":              FieldDescriptor("seepage_mask", "derived/seepage_mask", "soil_saturation_mask", "1", "(time, face)", "core"),          # uint8
    "seepage_rate":              FieldDescriptor("seepage_rate", "derived/seepage_rate", "surface_runoff_from_groundwater", "m s-1", "(time, face)", "core"),
    "recharge":                  FieldDescriptor("recharge", "budget/recharge", "groundwater_recharge_rate", "m s-1", "(time, face)", "solver"),
    "concentration":             FieldDescriptor("concentration", "concentration", "mass_concentration_of_solute_in_groundwater", "kg m-3", "(time, layer, face, species)", "solver"),
    # ...
}
```

**Règles** :

1. Les **figures** n'utilisent que `public_name` (pas de suffixe `_m_per_day`, pas de préfixe `derived/`).
2. Les **unités** sont portées par des **attributs CF** du Zarr, pas par le nom. Les figures lisent `sim.field("recharge").attrs["units"]`.
3. `seepage_areas` est **scindé en deux** : `seepage_mask` (uint8) et `seepage_rate` (flux m/s). Le nom ambigu est abandonné.
4. `sim.field(public_name)` traduit vers `zarr_path` via le registre.

### 1.4 API Python (phase 10) ↔ API REST (phase 11)

Phase 10 expose `hmp.compare(A, B)`, `catalog.find(...)`, `catalog.best(...)`, `catalog.get(sim_id)`, `sim.field(name, timestep, layer)`, `Simulation(config).run()`. Phase 11 définit la parité :

| Python | HTTP |
|---|---|
| `catalog.find(**filters)` | `GET /simulations` |
| `catalog.get(sim_id)` | `GET /simulations/{sim_id}` |
| `sim.field(name, timestep, layer)` | `GET /simulations/{sim_id}/fields/{name}` |
| `sim.timeseries(var, station)` | `GET /simulations/{sim_id}/timeseries/{station}` |
| `sim.metrics(station)` | `GET /simulations/{sim_id}/metrics` |
| `Simulation(config).run()` | `POST /simulations/run` |
| `hmp.compare([a, b])` | `POST /simulations/compare` |

**Cohérent**, mais **3 trous** :

1. `catalog.best(...)` et `catalog.worst(...)` n'ont pas d'endpoint REST dédié. Solution : les faire passer par `GET /simulations?sort=-metrics.nse&limit=1`.
2. `sim.export(fmt)` (phase 10) ↔ `POST /simulations/{sim_id}/export` (phase 11). Mais phase 10 utilise `sim.inspect()` sans équivalent REST.
3. `sim.plot(kind, ...)` (phase 10) ↔ `POST /simulations/{sim_id}/figures/render` (phase 11). **Cohérent** à condition que phase 08 rende `sim.plot()` équivalent à `figures.get(kind).plot(sim)` (cf. §3.6).

### 1.5 Exceptions typées — catalogue transverse

Les documents introduisent plusieurs exceptions sans source canonique. **Référentiel unique** :

```python
# hydromodpy/core/exceptions.py  [REFACTORE]
class HydroModPyError(Exception):
    """Base exception."""
    code: str = "HMPY.E000"

class ConfigError(HydroModPyError):           code = "HMPY.E100"  # Pydantic validation
class ImplicitInferenceError(ConfigError):    code = "HMPY.E101"  # data inference in "strict" mode
class SchemaVersionTooNewError(ConfigError):  code = "HMPY.E102"
class UnitAliasConflict(ConfigError):         code = "HMPY.E103"

class DataError(HydroModPyError):             code = "HMPY.E200"
class MissingForcingError(DataError):         code = "HMPY.E201"
class ContractViolationError(DataError):      code = "HMPY.E202"
class DataContractViolation(ContractViolationError): pass  # alias phase 12

class MeshError(HydroModPyError):             code = "HMPY.E300"
class IncompatibleMeshError(MeshError):       code = "HMPY.E301"

class SolverError(HydroModPyError):
    sim_id: str | None = None
    run_id: str | None = None
    code = "HMPY.E400"

class SolverDivergedError(SolverError):       code = "HMPY.E401"
class SolverTimeoutError(SolverError):        code = "HMPY.E402"
class IncompatibleCapabilitiesError(SolverError): code = "HMPY.E403"
```

**Décision** : `SolverError.sim_id` et `.run_id` sont des attributs d'instance (non-frozen) renseignés par le pipeline avant propagation, ce qui résout l'incohérence de phase 07 §5.2 qui lit `e.sim_id`.

---

## 2. Grille unifiée — vérification d'usage

La grille unifiée proposée en phase 03 (§3) est **`HydroMesh` UGRID-1.0** avec les champs `node_x`, `node_y`, `face_node`, `face_x`, `face_y`, `z_interfaces`, `topology ∈ {"dis","disv","disu"}`.

### 2.1 Traversée complète des phases

| Phase | Usage | Conforme UGRID ? |
|---|---|:-:|
| 01 | `hydromodpy/spatial/mesh/hydro_mesh.py::HydroMesh` importé partout | 🟢 |
| 03 | Définition canonique §3.3 ; conversions DIS→UGRID, DISV→UGRID, DISU→UGRID explicitées | 🟢 |
| 04 | Zarr `simulations/<uuid>.zarr/mesh/{node_coordinates,face_node_connectivity,z_interfaces}` attrs `Conventions="CF-1.11 UGRID-1.0"` | 🟢 |
| 05 | `RunContext.mesh: HydroMesh` + `ExtractContext.mesh: HydroMesh` ; extracteur écrit indexé par `face_id` | 🟢 |
| 06 | `MeshedState.mesh: HydroMesh, mesh_sha256` | 🟢 |
| 07 | Indirect via `SimulationCatalog` | 🟢 |
| 08 | `sim.mesh.face_node_connectivity`, `render_ugrid_field(ax, sim, field, cmap, norm)` helper ; `sim.mesh.is_congruent_with(other.mesh)` ; coupes transversales via `shapely.LineString` | 🟢 |
| 10 | `hmp.HydroMesh` exporté top-level | 🟢 |
| 11 | `GET /simulations/{sim_id}/mesh` en UGRID-Arrow ou GeoJSON | 🟢 |
| 12 | Pas d'impact direct (inputs) | N/A |

### 2.2 Risques résiduels de code spécifique DIS vs DISV

**Trois lieux** où la bascule DIS/DISV a tendance à réapparaître :

1. **Adapters solveurs** (`hydromodpy/solver/modflow_nwt/` vs `modflow6/`) : la structure actuelle dans le code (audit 04) garde deux chemins séparés `_recarray_to_grid`. La cible phase 05 impose que **l'extracteur** (`ResultExtractor.extract(ctx)`) reçoive un `HydroMesh` UGRID déjà converti, et écrive en face-indexé. **Règle** : aucun `if mesh.topology == "dis":` dans les figures, l'analyse ou l'export. Toléré **uniquement** dans :
   - `hydromodpy/spatial/mesh/ugrid_builders/{dis_to_ugrid,disv_to_ugrid,disu_to_ugrid}.py` — conversion au moment de la création du `HydroMesh`.
   - `hydromodpy/solver/modflow_nwt/adapter.py` et `modflow6/adapter.py` — conversion UGRID → DIS/DISV au moment de l'envoi à FloPy.
2. **Export NetCDF** (`hydromodpy/results/exporters/netcdf.py`) : doit écrire en UGRID-CF (`cf_role="mesh_topology"`, `topology_dimension=2`) sans reshape `(nrow, ncol)`.
3. **Résampling** (`hydromodpy/results/resample.py`, actuellement stub) : **à écrire** avec algorithme unique basé sur triangulation Delaunay des `face_x, face_y` du mesh source, interpolation aux `face_x, face_y` du mesh cible.

**Décision** : créer un test de non-régression `tests/integration/test_no_dis_specific_code.py` qui grep récursivement le codebase pour `row\s*[,]?\s*col|nrow|ncol` hors des 3 lieux autorisés ci-dessus.

---

## 3. Nommage global — arbitrage final

### 3.1 Noms canoniques (opposables)

| Concept | Nom canonique | Aliases interdits | Module |
|---|---|---|---|
| Simulation (facade programmatique d'exécution) | `Simulation` | `Project`, `SimulationRunner`, `Launcher`, `Pipeline` | `hydromodpy.simulation.api.Simulation` |
| Simulation (vue lecture seule depuis catalog) | `SimulationView` | `Simulation` (ambigu), `SimulationResult`, `RunOutput` | `hydromodpy.results.simulation.SimulationView` |
| Catalog (sortie) | `SimulationCatalog` | `ResultsCatalog`, `Catalog`, `SimulationStore` | `hydromodpy.results.catalog.SimulationCatalog` |
| Store Zarr par simulation | `SimulationZarr` | `ZarrStore`, `SimZarr`, `ZarrHandle` | `hydromodpy.results.zarr_store.SimulationZarr` |
| Groupe de simulations | `SimulationGroup` | `SimGroup`, `Ensemble` (réservé multi-runs), `RunSet` | `hydromodpy.results.simulation_group.SimulationGroup` |
| Catalog (entrées) | `InputCatalog` | `DataCatalog`, `CacheCatalog` | `hydromodpy.data.cache.InputCatalog` |
| Planner données | `DataPlanner` | `DataManagersPlanner`, `DataLoadPlanner` | `hydromodpy.data.planner.DataPlanner` |
| Plan de données résolu | `DataLoadPlan` | `DataPlan`, `LoadPlan` | `hydromodpy.data.planner.DataLoadPlan` |
| Plan de simulation (immuable) | `SimulationPlan` | `RunPlan`, `ExecutionPlan` | `hydromodpy.simulation.planning.SimulationPlan` |
| Run processus | `ProcessRun` | `RunSpec`, `TaskSpec` | `hydromodpy.simulation.planning.ProcessRun` |
| Pipeline d'exécution | `Pipeline` | `Workflow` (réservé), `Runner`, `Driver` | `hydromodpy.simulation.pipeline.Pipeline` |
| Workflow (auto-dispatch CLI) | `SimulationWorkflow`, `OverviewWorkflow`, ... | `Mode`, `Runner` | `hydromodpy.simulation.workflows.*` |
| Résultat pipeline | `SimulationResult` | `PipelineResult`, `RunOutput` | `hydromodpy.simulation.api.SimulationResult` |
| Maillage pivot | `HydroMesh` | `Mesh`, `Grid`, `UnifiedMesh` | `hydromodpy.spatial.mesh.HydroMesh` |
| Solveur Protocol | `SolverRunner` | `SolverAdapter` (ancien), `SolverEngine` | `hydromodpy.solver.contracts.runner.SolverRunner` |
| Plugin solveur | `SolverPlugin` | `SolverBackend`, `SolverProvider` | `hydromodpy.solver.contracts.plugin.SolverPlugin` |
| Résultat solveur | `SolveResult` | `RunResult`, `StepResult`, `SolverOutput` | `hydromodpy.solver.contracts.runner.SolveResult` |
| Extracteur | `ResultExtractor` | `Extractor`, `SolverExtractor` | `hydromodpy.solver.contracts.extractor.ResultExtractor` |
| Espace de paramètres | `ParameterSpace` | `ParamSpace` | `hydromodpy.analysis.calibration.parameters.ParameterSpace` |
| Facade calibration | `CalibrationEngine` | `Calibrator`, `Optimizer` (réservé) | `hydromodpy.analysis.calibration.engine.CalibrationEngine` |
| Session calibration | `CalibrationSession` | `OptimizationRun` | `hydromodpy.analysis.calibration.engine.CalibrationSession` |
| Figure Protocol | `Figure` | `Plot`, `Graph` | `hydromodpy.analysis.display.base.Figure` |
| Figure abstraite | `BaseFigure` | `AbstractFigure` | `hydromodpy.analysis.display.base.BaseFigure` |
| Run id | `run_id` (ULID) | — | — |
| Simulation id | `sim_id` (UUID v5 déterministe) | — | — |

### 3.2 Décisions de renommage / ambiguïté tranchée

1. **`Simulation` dédoublé** (phase 10 + 11) → on garde **les deux noms** avec désambiguïsation explicite : `hydromodpy.simulation.api.Simulation` (facade mutable, `run()`) et `hydromodpy.results.simulation.SimulationView` (vue immuable depuis catalog). Le README et le type `hmp.Simulation` pointent sur la facade, tandis que `catalog.get(sim_id)` retourne un `SimulationView`.
2. **`DataPlanner` vs `DataManagersPlanner`** (phase 12 vs CLAUDE.md/audit) → **`DataPlanner`** (phase 12 est la cible, le nom existant est `[RENOMME]`).
3. **`ParamSpace` vs `ParameterSpace`** (phase 06 vs 07) → **`ParameterSpace`** (phase 07).
4. **`Objective` avec deux signatures** (phase 06 `(params) -> ObjectiveEvaluation` vs phase 07 `(observations, simulation) -> ObjectiveValue`) → **phase 07 est canonique**. L'`Objective` de phase 06 est renommé **`RawScalarObjective`** (interne au pipeline) et sert d'implémentation concrète passée à `Calibrator`, pas de Protocol public.
5. **`hmp.Modflow` / `hmp.Modflow6` / `hmp.Boussinesq`** (phase 10) → conservés, avec asymétrie historique tolérée. Ajout de `hmp.Mt3dms` et `hmp.Modpath7` pour cohérence.
6. **`SolverAdapter`** (audit, code actuel) → **`SolverRunner`** (phase 05). `SolverAdapter` est `[RENOMME]`.
7. **`ParamLevel`** enum → champ `profile: Literal["user","dev","expert"]` de `UiMeta` (phase 11). `ParamLevel` est `[SUPPRIME]`.
8. **`Watershed`** facade legacy → `[SUPPRIME]`.
9. **`Geographic`** → **`CatchmentDelineation`** (phase 01 `[RENOMME]`, nom ambigu "geographic" collide avec geopandas).
10. **`SinkSource`** → **`SourceTerm`** (convention PDE standard).
11. **`run_id` vs `sim_id`** :
    - `run_id` = **ULID** (lexicographic-sortable, 26 chars, génération à la soumission).
    - `sim_id` = **UUID v5 déterministe** `uuid5(HYDROMODPY_NAMESPACE, run_fingerprint)` où `run_fingerprint = sha256(canonical_config_json + inputs_fingerprints)`. Permet déduplication : même config + mêmes inputs → même `sim_id`.
    - **Rétropédalage phase 10** qui dit "UUID v4" : **phase 11 est canonique** (UUID v5).

### 3.3 TOML ↔ CLI ↔ REST — unification complète

| TOML section | Module Pydantic | CLI override dotted | REST body path |
|---|---|---|---|
| `[workspace]` | `WorkspaceConfig` | `--override workspace.root=...` | `config.workspace.root` |
| `[geographic]` | `GeographicConfig` | `--override geographic.buffer=...` | `config.geographic.buffer` |
| `[mesh]` | `MeshConfig` ← **ex `[mesh_catchment]`** | `--override mesh.dx=100` | `config.mesh.dx` |
| `[domain]` | `DomainConfig` | `--override domain.zone_ids=["geology"]` | `config.domain.zone_ids` |
| `[flow]` | `FlowConfig` | `--override flow.param_payload.K=5e-4` | `config.flow.param_payload.K` |
| `[transport]` | `TransportConfig` | idem | `config.transport.*` |
| `[period]` | `PeriodConfig` ← **ex `[time]`** | `--override period.start=2020-01-01` | `config.period.start` |
| `[simulation]` | `SimulationConfig` | — | `config.simulation.*` |
| `[solver]` | `SolverConfig` (discriminant `engine`) | `--override solver.engine=mf6` | `config.solver.engine` |
| `[solver.packages.modflow6]` | `Modflow6PackagesConfig` | `--override solver.packages.modflow6.ims.outer_maximum=100` | `config.solver.packages.modflow6.ims.outer_maximum` |
| `[data]` | `DataConfig` | `--override data.inference_mode=strict` | `config.data.inference_mode` |
| `[data.hydrometry]` | `HydrometryConfig` | `--override data.hydrometry.source=hubeau` | `config.data.hydrometry.source` |
| `[data.piezometry]` | `PiezometryConfig` | idem | idem |
| `[observations]` | `ObservationsConfig` | `--override observations.piezometry=path/stations.csv` | `config.observations.piezometry` |
| `[recharge]` | `RechargeConfig` | `--override recharge.source=sim2` | `config.recharge.source` |
| `[calibration]` | `CalibrationConfig` | `--override calibration.optimizer=optuna` | `config.calibration.optimizer` |
| `[batch]` | `BatchConfig` | `--override batch.regional.outlets=...` | `config.batch.regional.outlets` |
| `[comparison]` | `ComparisonConfig` | — | `config.comparison.*` |
| `[overview]` | `OverviewConfig` | — | `config.overview.*` |
| `[postprocess]` | `PostprocessConfig` | — | `config.postprocess.*` |
| `[display]` | `DisplayConfig` | — | `config.display.*` |
| `[capability_gallery]` | `CapabilityGalleryConfig` | — | `config.capability_gallery.*` |

#### Arbitrage sur la refonte `[data]` (phase 02 vs phase 12)

**Phase 02** propose `[observations]` + `[recharge]` (éclatement). **Phase 12** propose `[data.<variable>]` (imbrication).

**Décision normative** : **coexistence contrôlée**.

- `[observations]` et `[recharge]` sont des **racines sémantiques de haut niveau** (ce que l'utilisateur conceptualise : "mes chroniques observées" vs "mon forçage"). Ils restent dans `HydroModPyConfig` comme attributs de 1er niveau.
- `[data]` et ses sous-sections `[data.<variable>]` sont des **contrôles techniques du cache** (`source`, `provider`, `offline`, `frequency`, `units`, etc.). Ils fournissent une granularité par variable indépendante de leur rôle sémantique (obs vs forçage).
- Une observation de piézométrie consomme `[observations].piezometry` (chemin vers fichier ou tag) et `[data.piezometry]` (source Hub'Eau vs custom, TTL, etc.).

```python
# hydromodpy/core/config/hydromodpy_config.py  [REFACTORE]
class HydroModPyConfig(HydroModelBase):
    workspace:     WorkspaceConfig
    geographic:    GeographicConfig
    mesh:          MeshConfig
    domain:        DomainConfig
    flow:          FlowConfig
    transport:     TransportConfig | None = None
    period:        PeriodConfig
    simulation:    SimulationConfig
    solver:        SolverConfig
    data:          DataConfig                                        # cache + inférence + sources
    observations:  ObservationsConfig = ObservationsConfig()         # chroniques observées (piezo, hydro)
    recharge:      RechargeConfig = RechargeConfig()                 # forçage
    calibration:   CalibrationConfig | None = None
    batch:         BatchConfig | None = None
    comparison:    ComparisonConfig | None = None
    overview:      OverviewConfig | None = None
    postprocess:   PostprocessConfig = PostprocessConfig()
    display:       DisplayConfig = DisplayConfig()
```

---

## 4. Flux de données complet

Trace d'une donnée depuis l'entrée (CSV local OU API Hub'Eau) jusqu'à la sortie (figure PDF, DataFrame ML, endpoint REST).

### 4.1 Scénario trace : piézométrie

**Entrée utilisateur** : `config.toml` contient `[data.piezometry] source = "hubeau"` et `[observations] piezometry = ["BRGM_0123X4567", "BRGM_0234Y0001"]`.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. TOML parse (phase 02)                                                    │
│    HydroModPyConfig.from_toml("config.toml")                                 │
│    → HydroModPyConfig (Pydantic v2, extra="forbid")                          │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. DataPlanner.plan(cfg) (phase 12)                                         │
│    → list[DataRequest(variable="piezometry", provider="hubeau",             │
│                       station_ids=["BRGM_0123X4567", "BRGM_0234Y0001"],     │
│                       period=cfg.period, explicit=True)]                     │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. InputCatalog.get(cache_key) (phase 12)                                   │
│    cache_key = CacheKey(variable="piezometry", provider="hubeau",           │
│                        station_id="BRGM_0123X4567",                         │
│                        period="2018/2024",                                  │
│                        request_hash=SHA256(request_params))                 │
│    IF cache_hit:                                                            │
│       → CacheHit(artifact_id, path="data/blobs/ab/c1/ab3c1...parquet",      │
│                  sha256, fetched_at, format="parquet")                       │
│    ELSE:                                                                     │
│       HubEauPiezometrySource.fetch(extent, period, **kwargs)                │
│       HTTPClient.get(base_url + "/niveaux_nappes/chroniques", params=...)   │
│       → JSON paginé → pydantic HubEauObservation → pd.DataFrame             │
│       → validate(TimeSeriesSchema) via pandera                              │
│       → InputCatalog.put(cache_key, bytes, provenance)                      │
│          . écrit data/blobs/<2hex>/<2hex>/<rest>.parquet                    │
│          . calcule sha256                                                    │
│          . INSERT INTO artifacts, provenance, stations, coverage             │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. load() fonction pure (phase 12)                                          │
│    → LoadResult(points=[PointRecord(values=pd.Series,                       │
│                                     station=Station(shapely.Point, crs),   │
│                                     source="hubeau", unit="m", frequency=  │
│                                     "PT1H", sha256=...), ...])             │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 5. Pipeline.step_05_domain (phase 06) : projette stations → cellules mesh   │
│    observation_points[sim_id, station_id, cell_id, weight] (DuckDB)         │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 6. Pipeline.step_08_solve (phase 05)                                        │
│    SolverRunner.setup() → build() → solve() → SolveResult                   │
│    (HEAD, CBC, LST écrits dans workspace/.hmp/scratch/<sim_id>/)            │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 7. Pipeline.step_09_extract (phase 05)                                      │
│    ResultExtractor.extract(ctx) écrit :                                     │
│      - SimulationCatalog.write_field(sim_id, "head", values, timestep=…)    │
│        → simulations/<uuid>.zarr/head/ (time, layer, face)                  │
│      - SimulationCatalog.write_timeseries(sim_id, df) pour stations         │
│        → DuckDB timeseries(sim_id, station_id, variable, datetime, value)   │
│      - SimulationCatalog.write_observations(sim_id, df_obs)                 │
│        → DuckDB observations(sim_id, station_id, variable, datetime, value) │
│      - SimulationCatalog.write_provenance(sim_id, fingerprints)             │
│        → DuckDB provenance(sim_id, variable, source_kind, sha256, source_ref)│
└──────────────────────────┬──────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 8. Pipeline.step_10_derive (phase 05 + 06)                                  │
│    DerivedComputerRegistry computes watertable_depth, seepage_mask, ...     │
│    → SimulationZarr.write_field("derived/watertable_depth", depth)          │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 9. Pipeline.step_11_aggregate : calcule NSE, KGE, RMSE par station          │
│    → DuckDB metrics(sim_id, station_id, metric_name, value)                 │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 10. Sortie utilisateur (3 chemins possibles)                                │
│                                                                              │
│  10.a  FIGURE PDF (phase 08)                                                 │
│    sim = catalog.get(sim_id)                                                 │
│    display.get("piezograph").plot(sim, station="BRGM_0123X4567",            │
│                                    save_path="piezo.pdf")                    │
│    → lit sim.timeseries("head", "BRGM_0123X4567") + sim.observations(...)   │
│    → matplotlib Figure → PDF                                                 │
│                                                                              │
│  10.b  DATAFRAME ML (phase 04 + 10)                                          │
│    group = catalog.find(project="canut")                                     │
│    df = group.to_frame(params=["flow.K", "flow.Sy"],                        │
│                        metrics=["nse", "kge"])                              │
│    → DuckDB JOIN parameters + metrics → pandas DataFrame                     │
│                                                                              │
│  10.c  ENDPOINT REST (phase 11)                                              │
│    GET /simulations/{sim_id}/timeseries/BRGM_0123X4567?variable=head        │
│    → Arrow IPC ou JSON                                                       │
│    TimeseriesRouter.get() appelle sim = catalog.get(sim_id) puis             │
│    sim.timeseries("head", "BRGM_0123X4567")                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Transformations explicites

| Étape | Transformation | Module |
|---|---|---|
| 1 → 2 | TOML bytes → Pydantic → `list[DataRequest]` | `data.planner.DataPlanner.plan` |
| 2 → 3 | `DataRequest` → `CacheKey` (hash canonique des paramètres) | `data.cache.CacheKey.from_request` |
| 3 (miss) | HTTP GET → JSON → `HubEauObservation[]` → `pd.DataFrame` → pandera validate → Parquet bytes | `data.sources.hubeau.HubEauPiezometrySource.fetch` |
| 3 → 4 | Parquet bytes → `PointRecord` | `data.loader.load` |
| 4 → 5 | `PointRecord.station.point` + mesh → `cell_id, weight` | `simulation.pipeline.steps.step_05_domain` |
| 6 → 7 | `.hds` FloPy → `np.ndarray` face-indexé → Zarr `(time, layer, face)` | `solver.modflow6.extractor.Modflow6Extractor.extract` |
| 7 → 8 | `head` + `top_elevation_m_layer` → `watertable_depth` | `results.virtual_fields._DERIVED["watertable_depth"]` |
| 9 | `timeseries` (sim) + `observations` → metrics via `results.metrics` | `simulation.pipeline.steps.step_11_aggregate` |
| 10.a | `sim.timeseries()` + `sim.observations()` → matplotlib Figure | `analysis.display.figures.timeseries.Piezograph.plot` |
| 10.b | SQL JOIN `parameters` + `metrics` + `tags` → DataFrame | `results.simulation_group.SimulationGroup.to_frame` |
| 10.c | Python call → Arrow IPC bytes → HTTP response | `api.routers.timeseries.get_station_timeseries` |

---

## 5. Cas d'usage validés

### 5.1 Scénario 1 — Hydrogéologue, 1ère simulation en 5 commandes

```bash
# 1. Initialisation workspace (~/hydromodpy/ par défaut)
hmp init

# 2. Création projet avec template
hmp new canut --from demo --solver mf6

# 3. Édition config (l'utilisateur remplace bbox, dates, etc. dans ~/hydromodpy/canut/config.toml)
$EDITOR ~/hydromodpy/canut/config.toml

# 4. Vérification de la config
hmp config check ~/hydromodpy/canut/config.toml

# 5. Lancement
hmp run ~/hydromodpy/canut/config.toml
```

**Verdict** : ✅ **Faisable en 5 commandes.** L'édition manuelle du TOML est tolérable (template pré-rempli).

**Amélioration** : `hmp new canut --from demo --solver mf6 --auto` pour bypass l'édition manuelle (bbox d'exemple démo pré-rempli).

### 5.2 Scénario 2 — Data scientist, 200 simulations → DataFrame ML

```python
import hydromodpy as hmp

catalog = hmp.open("~/hydromodpy")
group = catalog.find(project="canut", status="success", nse_gt=0.5)
assert len(group) >= 200

# DataFrame "long" : 1 ligne par (sim_id, param_name)
df = group.to_frame(
    params=["flow.K", "flow.Sy", "flow.drn_cond"],
    metrics=["nse_outlet", "kge_outlet", "rmse_outlet"],
    station="outlet",
)

# Ou pivot direct
df_wide = group.pivot(index="sim_id",
                       columns="param_name",
                       values="parameter.value")

# ML-ready
X = df[["K", "Sy", "drn_cond"]].values
y = df["nse_outlet"].values
```

**Verdict** : ✅ **Faisable en 4 lignes.** Garanti par phase 04 `v_params_wide`, `v_metrics_wide` vues SQL.

**Gap identifié** : `group.to_frame(params=[...], metrics=[...], station=...)` n'est pas explicitement documenté dans phase 10 (seul `group.to_dataframe()` l'est). **Action** : aligner phase 10 sur `group.to_frame()`.

### 5.3 Scénario 3 — Développeur, nouveau solveur en 1 journée

```python
# hydromodpy/solver/hydrogeosphere/plugin.py  [EXEMPLE NOUVEAU]
from hydromodpy.solver.contracts import SolverPlugin, SolverCapabilities, ProcessKind

class HydroGeoSpherePlugin:
    name = "hgs"
    version = "0.1.0"
    capabilities = SolverCapabilities(
        process_kinds=frozenset({ProcessKind.FLOW, ProcessKind.VARIABLY_SATURATED}),
        regimes=frozenset({"steady", "transient"}),
        mesh_types=frozenset({"unstructured"}),
        requires_binary=True,
        binary_name="hgs",
        binary_env_var="HGS_BIN",
    )
    config_model = HgsConfig

    def runner(self, ctx):
        return HgsRunner(ctx)

    def extractor(self):
        return HgsExtractor()

# hydromodpy/solver/hydrogeosphere/runner.py
class HgsRunner:
    def __init__(self, ctx): self.ctx = ctx
    def setup(self): self._dir = self.ctx.scratch_dir; self._dir.mkdir(parents=True, exist_ok=True)
    def build(self): self._write_grok_file(); self._write_hgs_input()
    def solve(self):
        t0 = time.monotonic()
        ret = subprocess.run([os.environ["HGS_BIN"], self._dir / "prefix"], capture_output=True)
        return SolveResult(
            output_dir=self._dir,
            converged=(ret.returncode == 0),
            iterations=self._parse_iterations_from_log(),
            wall_time_s=time.monotonic() - t0,
            diagnostics={"returncode": ret.returncode},
        )
    def cleanup(self): ...

# hydromodpy/solver/hydrogeosphere/extractor.py
class HgsExtractor:
    supported = frozenset({ProcessKind.FLOW})
    def extract(self, ctx: ExtractContext) -> None:
        head_arr = self._read_hgs_binary(ctx.output_dir / "head.dat")  # → (n_time, n_layer, n_face)
        ctx.store.write_field(ctx.sim_id, "head", head_arr)
    def derive(self, ctx, flags): ...

# Registration
from hydromodpy.solver.registry import register
register(HydroGeoSpherePlugin())
```

**Volume** : ~250 lignes pour un plugin solveur complet + tests.
**Verdict** : ✅ **Faisable en 1 journée** si le binaire solveur existe et le format de sortie est connu.

### 5.4 Scénario 4 — Étudiant, compare NWT vs MF6 sur même domaine

```python
import hydromodpy as hmp

catalog = hmp.open("~/hydromodpy")
sim_nwt = catalog.find(project="canut", solver="mf_nwt").best("nse")
sim_mf6 = catalog.find(project="canut", solver="mf6").best("nse")

report = hmp.compare(sim_nwt, sim_mf6,
                     variables=["head", "watertable_depth"],
                     station="outlet",
                     output="comparison.pdf")
```

```bash
# Ou en CLI
hmp compare <sim_nwt_uuid> <sim_mf6_uuid> --output comparison.pdf
```

**Verdict** : ✅ **Faisable**. Garanti par phase 08 (`SideBySide`, `DifferenceMap`, `ScatterMetricMetric`, `EnsembleBand`) et phase 10 (`hmp.compare`, `hmp compare`).

**Contrainte de cohérence** : les deux simulations doivent être sur le **même mesh**. Garantie par `sim_nwt.mesh.is_congruent_with(sim_mf6.mesh)` (phase 08 §7.3). Si pas congruents : `sim_mf6.resample_to(sim_nwt.mesh)`.

### 5.5 Scénario 5 — Frontend Angular, validation config temps réel

```typescript
// Angular component
async onFieldChange(path: string, value: any) {
  const resp = await this.http.post<ValidateFieldResponse>(
    '/config/validate-field',
    { path, value, context: this.currentConfig, locale: 'fr' }
  ).toPromise();
  this.formErrors[path] = resp.valid ? null : resp.error;
  // Warnings et impact fields dépendants
  this.formWarnings = resp.warnings;
  this.affectedFields = resp.dependent_fields_affected;
}
```

**Budget latence** : 50 ms p95 (phase 11 §3.5). Architecture : FastAPI + `PartialHydroModPyConfig` + `UiMeta` enrichi via `model_json_schema()` + extensions `x-*`.

**Verdict** : ✅ **Faisable** tant que :
1. La config Pydantic respecte `ConfigDict(extra="forbid")` au top-level (actuellement manquant dans `HydroModPyConfig` — **P0** cité dans audit).
2. Le `UiMeta` dataclass est attaché via `json_schema_extra` sur **tous** les `Field()`.
3. Les validateurs croisés n'utilisent pas `@model_validator(mode="after")` coûteux (budget 25 ms).

### 5.6 Scénario 6 — Utilisateur reprend simulation de 2 ans

```python
import hydromodpy as hmp

catalog = hmp.open("~/hydromodpy")
sim = catalog.get("a7e3b5e6-...")  # UUID v5 de la sim de 2024
print(sim.created_at, sim.config_hash, sim.solver, sim.mesh.n_faces)

# Régénération figures sans rerun
fig = hmp.display.get("watertable_map").plot(sim, save_path="wt_2024.png")
```

**Cas robuste** : même si `hydromodpy` a évolué, le Zarr est **auto-descriptif** (CF-UGRID). Le champ `schema_version` dans DuckDB permet la migration.

**Verdict** : ✅ **Faisable** si `hmp open` supporte les anciennes versions de schema (migrations auto). Garanti par phase 04 `_schema_version` + migrations.

**Risque** : si l'utilisateur a supprimé les binaires solveurs, `sim.rerun()` échoue (phase 04 actuelle a ce stub NotImplementedError). **Décision** : `sim.rerun(solver_binary=None)` doit explicitement lever une exception claire si le binaire est absent.

### 5.7 Scénario 7 — Chercheur exporte ALL d'une simulation

```bash
hmp export <sim_id> --all --output /path/export/
```

Voir §7 pour l'arborescence exacte.

**Verdict** : ✅ **Faisable**. Arborescence définie en §7.

**Gap identifié** : `hmp export --all` n'est pas explicitement listé dans phase 10 (seul `--format` à un seul format est documenté). **Action** : ajouter `--all` comme flag qui exporte dans une arborescence complète (voir §7).

### 5.8 Scénario 8 — Utilisateur ajoute données piézométriques custom

```bash
# Ajoute un CSV user au cache
hmp data add ./my_piezo_network.csv \
    --type piezometry \
    --crs EPSG:2154 \
    --provider labo_rennes \
    --frequency PT1H \
    --unit m

# Utilise dans config.toml :
#   [data.piezometry]
#   source = "custom"
#   provider = "labo_rennes"
#   [observations]
#   piezometry = ["station_1", "station_2"]

hmp run canut.toml
```

**Verdict** : ✅ **Faisable** grâce à phase 12 (`hmp data add`, `CustomPiezometrySource`, `CustomTabularLoader`). Format pivot imposé : GeoParquet pour stations, Parquet+sidecar pour chronique.

**Gap identifié** : l'utilisateur peut aussi pointer directement vers un fichier CSV dans `[observations].piezometry = "path/to/file.csv"` (phase 10). Les deux chemins coexistent :
- **Via `hmp data add`** : le fichier est **ingesté dans le cache** et versionné (artifact_id, sha256, lockfile). **Recommandé** pour production.
- **Via `[observations] = "path"`** : lecture directe **ad hoc**, sans cache. **Toléré** pour prototypage.

---

## 6. Données d'entrée (phase 11) vs Store (phase 04)

### 6.1 Cohérence des systèmes

| Dimension | `data/cache.duckdb` (phase 12) | `hydromodpy.duckdb` (phase 04) |
|---|---|---|
| Classe d'accès | `InputCatalog` | `SimulationCatalog` |
| Fichier | `workspace/data/cache.duckdb` | `workspace/hydromodpy.duckdb` |
| Scope | Partagé entre **tous** les projets d'un workspace | Idem |
| Contenu | 7 tables : `artifacts`, `provenance`, `stations`, `coverage`, `failures`, `validation_reports`, `inference_audit` | 12 tables + vues + tags + observations |
| Clé primaire | `artifact_id` UUID | `sim_id` UUID v5 |
| Binaires | `workspace/data/blobs/<hash_prefix>/...` | `workspace/simulations/<uuid>.zarr/` |

**Les deux DuckDB sont distincts et ne s'intersectent pas**. Une simulation référence un ou plusieurs `artifact_id` de l'`InputCatalog` via la table `provenance` du `SimulationCatalog` :

```sql
-- hydromodpy.duckdb / provenance  (phase 04)
CREATE TABLE provenance (
    sim_id       UUID REFERENCES simulations(sim_id) ON DELETE CASCADE,
    variable     VARCHAR NOT NULL,     -- "piezometry", "hydrometry", "dem", ...
    source_kind  VARCHAR NOT NULL,     -- "http_api" | "custom_file" | "derived"
    source_ref   VARCHAR NOT NULL,     -- URL complète OU path fichier OU input_artifact_id (UUID)
    sha256       VARCHAR NOT NULL,     -- hash du blob effectivement consommé
    fetched_at   TIMESTAMP,
    size_bytes   BIGINT,
    stats        JSON,                 -- {n_rows, mean, std, min, max}
    ...
    PRIMARY KEY (sim_id, variable, source_ref)
);
```

**Règle de traçabilité** : pour tout `(sim_id, variable)`, on peut :

```python
sim = catalog.get(sim_id)
prov = sim.provenance  # pd.DataFrame
# Pour chaque ligne, si source_kind == "http_api" → source_ref = URL Hub'Eau
#                    si source_kind == "custom_file" → source_ref = "input_artifact_id:<uuid>"
#                    → peut être récupéré via ws.data.get_artifact(artifact_id).path
```

### 6.2 Clé de provenance et reproductibilité

**Triple clé** (phase 12 §6) : `(sha256, fetched_at, loader_version)`.

- `sha256` : canonique, portable entre workspaces.
- `fetched_at` : traçabilité temporelle (Hub'Eau évolue).
- `loader_version` : version de `HubEauPiezometrySource` (git sha ou semver).

**Export `.hmp` package** embarque : `sim.zarr` + dump DuckDB (simulations, parameters, timeseries, metrics, provenance, observations, geographic, calibration pour cette sim) + **les blobs inputs référencés** (copie depuis `data/blobs/`) + le `hydromodpy.lock`.

### 6.3 Gap identifié

Phase 04 `provenance` stocke `source_ref` + `sha256` mais **ne lie pas explicitement** à un `artifact_id` de l'`InputCatalog` pour les custom files. **Décision** : ajouter une colonne optionnelle `input_artifact_id UUID NULL` à la table `provenance` pour les cas `source_kind="custom_file"`, avec FK logique (pas physique, les deux DuckDB sont séparés) vers `cache.duckdb::artifacts.artifact_id`.

---

## 7. Export structure `hmp export --all`

### 7.1 Commande canonique

```bash
hmp export <sim_id> --all --output /path/to/output/
hmp export <sim_id> --format hmp --output /path/to/share/run.hmp   # package portable unique
hmp export <sim_id> --format netcdf --variable head                # un fichier NetCDF
```

### 7.2 Arborescence `--all`

```
/path/to/output/<sim_id>/
├── README.md                          # Description human-readable (généré)
├── manifest.json                       # { "sim_id", "exported_at", "hydromodpy_version", "files": [...] }
├── config/
│   ├── config.toml                     # Config complète (reconstituée depuis DuckDB config_snapshot)
│   ├── config.json                     # idem, format JSON (pour frontend)
│   └── plan.json                       # SimulationPlan sérialisé
├── metadata/
│   ├── simulation.json                 # Métadonnées de la table `simulations`
│   ├── provenance.csv                  # Fingerprints inputs
│   ├── run_env.json                    # OS, Python, solver binary SHA256
│   └── tags.json
├── parameters/
│   ├── parameters.csv                  # Table parameters (long format)
│   └── parameters_wide.csv             # Pivoté (ML-ready)
├── metrics/
│   ├── metrics.csv
│   └── metrics_wide.csv
├── timeseries/
│   ├── <station_id>_<variable>.csv     # Une série par station × variable
│   └── stations_geometry.geojson       # Localisation + métadonnées stations
├── observations/
│   └── <station_id>_<variable>_obs.csv
├── budget/
│   ├── budget.csv                      # Table budgets (long format)
│   ├── mass_balance.csv
│   └── budget_series.csv               # Agrégé par timestep pour plot
├── fields/
│   ├── head.nc                         # NetCDF CF-1.11 UGRID-1.0 (facet-indexed)
│   ├── head.tif                        # GeoTIFF COG (dernier timestep seulement si 2D)
│   ├── watertable_depth.nc
│   ├── watertable_elevation.nc
│   ├── seepage_mask.nc
│   ├── seepage_rate.nc
│   ├── recharge.nc
│   └── concentration.nc                # Si transport
├── mesh/
│   ├── mesh.ugrid.nc                   # UGRID-1.0 pure (pas de data)
│   ├── mesh.vtu                        # ParaView
│   └── mesh_faces.gpkg                 # GeoPackage polygones
├── geographic/
│   ├── watershed.geojson
│   ├── rivers.geojson
│   ├── stations.geojson
│   ├── dem.tif
│   └── geology.tif
├── figures/                            # Rendu de toutes les figures par défaut
│   ├── watertable_map.png
│   ├── watertable_depth.png
│   ├── recharge_map.png
│   ├── hydrograph_outlet.pdf
│   ├── piezograph_<station>.pdf
│   └── overview_card.pdf
├── calibration/                        # Si simulation issue d'une calibration
│   ├── session.json
│   ├── iterations.csv
│   └── convergence.png
├── paths/                              # Particle tracking (si MODPATH exécuté)
│   ├── pathlines.csv
│   └── endpoints.csv
├── validation/
│   ├── validation_reports.json         # Contrôles pandera
│   └── mass_balance_check.json
├── hydromodpy.lock                     # Lockfile reproductibilité inputs
└── export.sha256                       # SHA de chaque fichier exporté
```

### 7.3 Implémentation cible

```python
# hydromodpy/results/exporters/full.py  [NOUVEAU]
def export_all(sim: SimulationView, out_dir: Path, *, preset: Literal["full","light","research"] = "full") -> Path:
    target = out_dir / str(sim.id)
    target.mkdir(parents=True, exist_ok=True)
    _export_config(sim, target / "config")
    _export_metadata(sim, target / "metadata")
    _export_parameters(sim, target / "parameters")
    _export_metrics(sim, target / "metrics")
    _export_timeseries(sim, target / "timeseries")
    _export_observations(sim, target / "observations")
    _export_budget(sim, target / "budget")
    _export_fields(sim, target / "fields", preset=preset)
    _export_mesh(sim, target / "mesh")
    _export_geographic(sim, target / "geographic")
    _export_figures(sim, target / "figures", preset=preset)
    if sim.has_calibration:
        _export_calibration(sim, target / "calibration")
    if sim.has_pathlines:
        _export_paths(sim, target / "paths")
    _export_validation(sim, target / "validation")
    _write_lockfile(sim, target / "hydromodpy.lock")
    _write_manifest_and_hash(target)
    return target
```

---

## 8. Risques et compromis

### 8.1 Choix techniques controversés

| Choix | Alternative écartée | Raison de l'écart | Risque résiduel |
|---|---|---|---|
| **Zarr v3** | Zarr v2 (support ParaView/QGIS) | CF-UGRID + compression BLOSC-ZSTD + attrs consolidated | Support outils externes retardé (QGIS ~2027) |
| **DuckDB** | SQLite + Parquet | OLAP-first, Arrow natif, PIVOT SQL, sans serveur | Écritures concurrentes limitées (WAL mono-écrivain) — atténué par mutex applicatif |
| **UGRID-1.0 pivot unique** | Garder DIS/DISV séparés | Élimine duplication extracteurs + figures | Coût conversion DIS→UGRID à chaque sim (mesure : <100ms pour 100k cellules) |
| **UUID v5 déterministe pour `sim_id`** | UUID v4 + table dedup | Déduplication native "même config + mêmes inputs = même sim_id" | Collisions si `run_fingerprint` mal défini |
| **ULID pour `run_id`** | UUID v4 | Lexico-sortable, lisible, monotone | Dépendance à `python-ulid` |
| **FastAPI pour REST** | Flask, Starlette brut | OpenAPI auto, Pydantic natif, WebSocket natif | Adoption Python 3.13 + pytest plugins à surveiller |
| **WebSocket + SSE pour progress** | WebSocket uniquement | SSE plus simple pour clients curieux, moins de state | Double codebase progression (atténué par `ProgressBus` unique) |
| **Pydantic v2 partout** | dataclass + pandera | Validation tree, JSON Schema auto, frozen deep | Frozen nested pas natif (v2.5+ requis) |
| **`sim_id` = UUID v5 + `run_id` = ULID** | Un seul id | Différencier "identité de la simulation" de "identité d'une exécution" (rerun, retries) | Complexité mappings CLI/REST |
| **Pas de Kubernetes/Celery** | Orchestrator externe | Hors scope (scientifique pas ops) | Batch >1000 sims nécessite `joblib.Parallel` manuel |
| **`hmp test` supprimé** | CLI wrapper `pytest` | Réinvention d'un outil mature | Conservation sous-ensemble `hmp test goldens` (non-pytest) |
| **Méteo-France SIM2 cache TTL J+5** | Refetch permanent | API rate-limitée + latence +données rétroactivement | Valeurs stale si utilisateur ne relance pas `--force-refresh` |

### 8.2 Choix non tranchés (ouvertures à l'implémentation)

1. **Backend Matplotlib par défaut** : `agg` (headless) vs `auto` selon env. Phase 08 définit `BackendManager` mais la décision finale pour `pyvista` (3D) est déléguée à l'impl.
2. **Parallélisme calibration** : `multiprocessing`, `joblib`, ou `dask`. Phase 07 laisse le choix au `BatchEvaluator`. Recommandation : `joblib.Parallel(backend="loky")` pour compatibilité max.
3. **Hashing algo** : SHA-256 vs BLAKE3. SHA-256 retenu (stdlib), mais BLAKE3 2-3x plus rapide sur gros blobs. Possible migration future sans changer le schema.
4. **Compression Zarr** : BLOSC-ZSTD clevel=3 choisi. clevel=9 réduit 20-30% mais ~5x plus lent. OK pour écriture, dev peut surcharger.

### 8.3 Dettes documentées acceptées

- **Pas de migration auto DuckDB→PostgreSQL** pour workspaces >1 To. Documenté.
- **Zarr v3 cassé dans QGIS 3.34** : export `.tif` dernier-timestep fourni comme fallback.
- **UUID v5 pas stable** si l'ordre des keys dans `config.json` n'est pas canonique. Impose un `canonical_json()` (sort_keys + indent=None + séparateurs fixes) — défini dans `hydromodpy.core.io.canonical_json`.

---

## 9. Tableau de synthèse des composants

| # | Phase | Composant | Classes clés | Statut code actuel | Décision finale | Actions bloquantes |
|---:|:-:|---|---|:-:|:-:|---|
| 1 | 01 | Structure packages | `core/`, `data/`, `spatial/`, `process/` → `physics/`, `solver/`, `results/`, `simulation/`, `analysis/`, `runners/`, `api/`, `launchers/` | 🟠 REFACTORE | 🟢 **Cohérent** | Renommer `process/` → `physics/`, supprimer `watershed/` |
| 2 | 02 | Config Pydantic | `HydroModPyConfig`, `FlowConfig`, `SimulationConfig`, `DomainConfig`, `MeshConfig`, `PeriodConfig`, `DataConfig`, `ObservationsConfig`, `RechargeConfig` | 🟠 REFACTORE | 🟠 **À clarifier** | Ajouter `extra="forbid"` à `HydroModPyConfig`, réconcilier section `[data]` (§3.3) |
| 3 | 03 | Contrats données | `HydroMesh`, `FieldParam`, `PointRecord`, `FieldRecord`, `Station`, `LoadResult` | 🟠 REFACTORE | 🟢 **Cohérent** | Aucune |
| 4 | 04 | Storage | `SimulationCatalog`, `SimulationZarr`, `SimulationView`, `SimulationGroup` | 🟢 CONSERVE (renforcer) | 🟢 **Cohérent** | Signature unique `write_field` (§1.3), ajouter `input_artifact_id` à `provenance` (§6.3) |
| 5 | 05 | Solveur contracts | `SolverPlugin`, `SolverRunner`, `ResultExtractor`, `SolveResult`, `ExtractContext`, `RunContext`, `ProcessKind` | 🟠 REFACTORE | 🟠 **À clarifier** | Fixer `solve()` (pas `execute()`), fixer `extract(ctx)` (pas `(report, store)`) |
| 6 | 06 | Pipeline exécution | `Pipeline`, `PipelineStep`, 15 `StepState` dataclasses, `SimulationResult`, `PipelineSolveReport`, `PipelineRunEntry` | 🟠 REFACTORE | 🟠 **À clarifier** | Aligner sur signatures phase 05 ; renommer `SolveReport`→`PipelineSolveReport`, `RunResult`→`PipelineRunEntry` ; définir `Pipeline.default(cfg)` + `PipelineConfig.timeout_s` |
| 7 | 07 | Calibration | `CalibrationEngine`, `CalibrationSession`, `ParameterSpace`, `AskTellOptimizer`, `SimulationEvaluator`, `Objective(observations, simulation)` | 🟠 REFACTORE (largement NOUVEAU) | 🟠 **À clarifier** | Fixer ordre métriques `(obs, sim)` dans `results.metrics`, renommer `ParamSpace`→`ParameterSpace`, déprécier `optimize_with_*` au profit de `*Adapter` classes |
| 8 | 08 | Postprocess display | `Figure`, `BaseFigure`, `FigureSpec`, 25 figures concrètes, `display.get()`, `display.export_all` | 🟠 REFACTORE | 🟠 **À clarifier** | Ajouter `SimulationView.plot(kind, **opts)` = facade sur `display.get(kind).plot(sim, **opts)`, unifier noms champs via `FieldDescriptor` registry (§1.3) |
| 9 | 09 | Tests idéaux | `tests/_helpers/`, 80 unit + 18 integration + 5 e2e + validation | 🟠 REFACTORE | 🟢 **Cohérent** | Supprimer `tests/unit/validation/` duplication, supprimer marker `fast` renommé `smoke` |
| 10 | 10 | UX CLI | `hmp init/new/config/run/list/show/compare/export/import/delete/display/doctor/completion` | 🟠 REFACTORE | 🟠 **À clarifier** | Intégrer `hmp data` (phase 12), `hmp api` (phase 11), `hmp lock` (phase 12), `hmp test goldens` (phase 09) dans l'arborescence canonique |
| 11 | 11 | Frontend-ready | `hydromodpy/api/` FastAPI, 50 endpoints, WebSocket+SSE, `PartialHydroModPyConfig`, `UiMeta` | 🔴 NOUVEAU | 🟠 **À clarifier** | Fixer UUID v5 pour `sim_id` (phase 10 v4 est erroné), exposer `SimulationCatalog.get()`/`SimulationView.etag()` publiquement dans phase 10 |
| 12 | 12 | Input data | `InputCatalog`, `DataPlanner`, `LockFile`, `DataSource`, `SIM2Client`, Hub'Eau sources | 🟠 REFACTORE | 🟠 **À clarifier** | Renommer `DataManagersPlanner`→`DataPlanner`, arbitrer coexistence `[data.<var>]` + `[observations]` (§3.3) |

**Légende cohérence** :
- 🟢 **Cohérent** : aligné avec les autres phases, pas de changement majeur requis.
- 🟠 **À clarifier** : divergences internes ou inter-phases documentées dans ce doc, décisions tranchées ci-dessus.
- 🔴 **Incohérence** : nécessiterait refonte majeure (aucun ici après arbitrage).

**Légende statut code** :
- 🟢 CONSERVE : existe et est aligné avec la cible.
- 🟠 REFACTORE : existe mais nécessite retouches (renommage, signature, migration).
- 🔴 NOUVEAU : n'existe pas.

---

## 10. Liste exhaustive des incohérences arbitrées

| # | Origine | Incohérence | Décision |
|---:|:-:|---|---|
| 1 | 05 vs 06 | `SolverRunner.solve() -> SolveResult` vs `execute(plan, domain, store)` | `solve() -> SolveResult` canonique (§1.1) |
| 2 | 05 ↔ 06 | `SolveResult` vs `SolveReport`+`RunResult` | `SolveResult` = solveur, `PipelineSolveReport`+`PipelineRunEntry` = pipeline (§1.1) |
| 3 | 05 vs 06 | `ResultExtractor.extract(ctx)` vs `extract(report, store)` | `extract(ctx: ExtractContext)` canonique (§1.1) |
| 4 | 05 vs 06 | `DerivedComputerRegistry` vs `DERIVED_REGISTRY` + `register_derived` | Un seul registre : `hydromodpy.results.virtual_fields._DERIVED: dict[str, DerivedComputer]` avec `@register_derived(name)` decorator-factory |
| 5 | 06 vs 07 | `Objective.evaluate(params)` vs `(observations, simulation)` | Phase 07 canonique. `Objective` de phase 06 renommé en `RawScalarObjective` (interne pipeline) |
| 6 | 07 vs 06 | `Pipeline.default(cfg)` non défini dans 06 | Ajouter factory method `Pipeline.default(cfg: HydroModPyConfig) -> Pipeline` qui instancie les 15 steps standards |
| 7 | 07 vs 06 | `PipelineConfig(timeout_s=...)` non défini dans 06 | Ajouter `timeout_s: float | None = None` à `PipelineConfig` |
| 8 | 07 vs 05 | `SolverDivergedError.sim_id` non défini | Ajouter `sim_id`, `run_id` comme attributs de `SolverError` base (§1.5) |
| 9 | 04/07/08 | `catalog.get()` vs `catalog.simulation()` vs `catalog.find()` vs `catalog.best()` | Canonique : `get(sim_id)` (accès direct), `find(**filters)` (filtrage), `best(project, metric)` (raccourci). `simulation(sim_id)` = alias `[DEPRECATED]` |
| 10 | 04 vs 08 | `sim.plot(kind, save=...)` vs `display.get(kind).plot(sim, save_path=...)` | Les **deux** coexistent : `sim.plot(kind, **opts)` = commodité, facade thin sur `display.get(kind).plot(sim, **opts)` |
| 11 | 05 vs 08 | Noms de champs `derived/watertable_depth` vs `watertable_depth` | Registre `FieldDescriptor` central (§1.3). `zarr_path` (interne) vs `public_name` (API) |
| 12 | 05 vs 08 | `seepage_areas` uint8 mask vs flux | Scinder en `seepage_mask` (uint8) et `seepage_rate` (m/s) (§1.3) |
| 13 | 07 vs 08 | `results.metrics.nse(sim, obs)` vs `self._metric_fn(obs, sim)` | Canonique : **`(obs, sim)`** (convention hydrologique). Corriger `results.metrics.*` |
| 14 | 07 vs 08 | Deux registres métriques (`objectives/metrics.py` vs `results/metrics/efficiency.py`) | Supprimer `objectives/metrics.py`. `results/metrics/` = source unique. `ScalarObjective` importe depuis `results.metrics` |
| 15 | 06 vs 07 | `ParamSpace` vs `ParameterSpace` | `ParameterSpace` canonique |
| 16 | 06 vs 07 | `optimize_with_optuna()` fonction vs `OptunaAdapter(space, ...)` classe | Classes-adapters canoniques (phase 07). Fonctions legacy `[DEPRECATED]` |
| 17 | 07 vs 08 | `hmp.display.convergence(session_id)` vs `figures.get("convergence").plot(group)` | Registre canonique. `hmp.display.convergence()` = fonction de commodité sur `figures.get("convergence").plot()` |
| 18 | interne 06 | "11 étapes" (TOC) vs 15 effectifs | 15 étapes (numérotés 0..14), rectifier TOC |
| 19 | interne 05 | `write_field` deux signatures (positional vs keyword) | Signature unique (§1.1) |
| 20 | interne 06 | `Pipeline.from_toml(path, workspace=...)` non défini | Ajouter method factory (utile pour tests et CLI) |
| 21 | 10 vs 11 | UUID v4 (phase 10) vs v5 déterministe (phase 11) | **v5 déterministe** canonique |
| 22 | 10 vs 12 | `[data]` éclaté (10) vs `[data.<var>]` (12) | Coexistence contrôlée (§3.3) |
| 23 | 10 vs 09 | `hmp test` supprimé (10) vs `hmp test goldens update` nouveau (09) | **Pas de contradiction** : `hmp test` wrapper pytest supprimé ; `hmp test goldens` (outil spécifique golden references, pas dans pytest) conservé |
| 24 | 10 vs 12 | `hmp data` family absente de 10 | Ajouter à l'arborescence canonique (§3.3) |
| 25 | 10 vs 11 | `hmp api` family absente de 10 | Idem |
| 26 | 10 vs 12 | `hmp lock` family absente de 10 | Idem |
| 27 | 11 vs 10 | `SimulationCatalog.get()` qualifié "NOUVEAU" dans 11 alors que déjà dans 10 | Cohérent (déjà dans 10 §3.3), doc 11 doit être corrigé |
| 28 | 12 | `DataPlanner` vs `DataManagersPlanner` (CLAUDE.md) | `DataPlanner` canonique |
| 29 | 10 | `Simulation` (facade) vs `Simulation` (view) ambigu | `Simulation` = facade mutable ; `SimulationView` = vue (§3.1) |
| 30 | 11 | `ParamLevel` → `UiMeta.profile` | `ParamLevel` [SUPPRIME], `UiMeta.profile` canonique |
| 31 | CLAUDE.md | `Project` (code actuel) = dissonance `Simulation` | `Simulation` canonique (phase 10) |
| 32 | 10 | `sim.inspect()` pas d'équivalent REST | Ajouter `GET /simulations/{sim_id}/inspect` = synthèse HTML/JSON |
| 33 | 10 | `sim.export(fmt)` ambiguïté entre SimulationView et facade | `SimulationView.export()` uniquement (une sim exécutée est toujours exportée depuis catalog) |
| 34 | 04 vs 12 | `provenance.source_ref` ne lie pas à `InputCatalog.artifacts` | Ajouter `input_artifact_id UUID NULL` (§6.3) |
| 35 | 01 | `Geographic` → `CatchmentDelineation` | Renommé canonique |
| 36 | 05 | `SinkSource` → `SourceTerm` | Renommé canonique |
| 37 | audit | `Watershed` facade legacy | Supprimée |
| 38 | 01+04 | Zarr v3 vs v2 indécision | v3 canonique, export GeoTIFF fallback |
| 39 | 10 vs 12 | `hmp run --offline` / `--frozen` / `--force-refresh` absents de 10 | Ajouter à phase 10 (§3.3 TOML table déjà intégrée) |
| 40 | 12 | `provenance_hash()` (09) vs `sha256_of_file()` (12) | `sha256_of_file()` canonique dans `hydromodpy.core.io.hashing`. `provenance_hash` = alias |
| 41 | 07 vs 11 | `CalibrationSession.cancel()` absent de 07 | Ajouter à phase 07 (méthode d'interruption gracieuse) |
| 42 | 08 vs 11 | `Figure.to_png_bytes()`, `Figure.serialize_spec()` absents de 08 | Ajouter au Protocol `Figure` (§1.4) |

---

## 11. Actions bloquantes avant implémentation

### 11.1 Priorité P0 (bloquant implémentation)

1. **Fixer `HydroModPyConfig`** avec `ConfigDict(extra="forbid")` à la racine (prérequis phase 11 validation temps réel).
2. **Créer `hydromodpy/results/field_registry.py`** avec `FieldDescriptor` pour 18 champs canoniques (§1.3).
3. **Unifier signature `SimulationCatalog.write_field`** (§1.1).
4. **Déclarer les 42 exceptions typées** dans `hydromodpy/core/exceptions.py` (§1.5).
5. **Renommer sans équivoque** : `Simulation`→`SimulationView` (results), `Project`→`Simulation` (facade), `DataManagersPlanner`→`DataPlanner`, `ParamSpace`→`ParameterSpace`, `SolverAdapter`→`SolverRunner`, `seepage_areas`→`seepage_mask`+`seepage_rate`.

### 11.2 Priorité P1 (avant merge architecture)

6. **Aligner phase 06 sur signatures phase 05** (`solve()` / `extract(ctx)`).
7. **Créer `hydromodpy/core/io/canonical_json.py`** pour `sim_id` UUID v5 stable.
8. **Compléter phase 10** avec `hmp data`, `hmp api`, `hmp lock`, `hmp test goldens` dans l'arborescence unique.
9. **Arbitrer TOML `[data]`** selon §3.3.
10. **Corriger ordre métriques** `(obs, sim)` dans `results.metrics.*`.

### 11.3 Priorité P2 (avant RC)

11. Écrire test de non-régression `tests/integration/test_no_dis_specific_code.py`.
12. Ajouter `input_artifact_id` à table `provenance` (§6.3).
13. Implémenter `export_all(sim, out_dir)` (§7).
14. Définir `Pipeline.default(cfg)` + `Pipeline.from_toml(path)`.

---

## 12. Conclusion

Les 12 phases architecturales forment un **ensemble largement convergent** mais qui nécessite un **travail d'harmonisation fine** résumé par ce document.

**Trois points forts** à préserver impérativement :

1. **UGRID-1.0 comme pivot universel** : DIS/DISV/DISU disparaissent de l'API publique après conversion dans `HydroMesh`. Tout le post-traitement est topologie-agnostique.
2. **DuckDB + Zarr + parité Python/REST** : une seule source de vérité pour les sims (`hydromodpy.duckdb`), un Zarr auto-descriptif par sim, une API REST qui reflète exactement l'API Python.
3. **Plan immuable + Pipeline en steps typés** : `frozen=True`, 15 `StepState` avec transitions vérifiées, reproductibilité garantie par SHA-256 des inputs + loader version + `sim_id` UUID v5.

**Trois chantiers critiques** à livrer d'abord :

1. **Renommages** (§3.1) — effort mécanique mais transversal (~200 fichiers).
2. **Config Pydantic racine** avec `extra="forbid"` et `UiMeta` attaché partout — sinon la validation temps réel frontend ne peut pas fonctionner.
3. **`FieldDescriptor` registry** — sinon les figures et les exports écrivent des noms divergents, tous les tests bac à sable cassent.

Ce document est **opposable** : chaque phase 01→12 doit être relue et corrigée pour intégrer les décisions prises ici. Toute modification future de l'architecture doit d'abord mettre à jour `13_coherence_globale.md` avant de toucher les phases individuelles.

**Version du document** : 1.0 — 2026-04-18
**Prochaine revue** : après implémentation P0 (estimée 2026-05-15)
