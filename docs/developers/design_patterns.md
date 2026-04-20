# HydroModPy — core design patterns

Every non-trivial feature in the codebase relies on one of the patterns
below. Learn these ten and most of the surface area becomes predictable.

All examples use relative paths from the repository root
(``hydromodpy/``). Line references are illustrative — check the code for
up-to-date signatures.

---

## 1. Protocol Solver

**Where**  `hydromodpy/simulation/adapters/base.py`, `solver/base/`.

A ``SolverAdapter`` is a Protocol (duck-typed interface) that binds a
``(process_type, solver_name)`` pair to a concrete solver. Each adapter
takes a domain-level process (``Flow``, ``Transport``) and drives the
underlying FloPy/Boussinesq/MODFLOW6 machinery.

```python
class SolverAdapter(Protocol):
    process_type: ClassVar[str]
    solver_name: ClassVar[str]
    def build(self, plan: ProcessRun, state: WorkflowContext) -> SolveResult: ...
```

Register new adapters in ``simulation/adapters/registry.py``. The
planner resolves the adapter at plan-build time; the runner only sees
the protocol.

**Why**  decouple the domain (Flow, Transport) from the solver specifics
(MODFLOW-NWT vs MODFLOW 6 vs Boussinesq). Adding a new solver is one
adapter class plus one registry entry.

---

## 2. Pipeline Step

**Where**  `hydromodpy/workflow/steps/`, `pipeline/`.

A pipeline step is a pure function ``(WorkflowContext) -> WorkflowContext``
(or a narrow sub-context). Each step updates exactly one scope of the
context: setup, data-loading, mesh, solve, extract, derive, export.

```python
def resolve_support_configs(ctx: SetupContext) -> SetupContext:
    ...
```

Steps live in small files named after their concern and never import
``Project`` or the runner. The pipeline composition itself is declared
elsewhere (``pipeline/``), keeping steps reusable in tests.

**Why**  testability — each step is a pure function with explicit inputs
and outputs. New workflows assemble steps without forking orchestration.

---

## 3. Figure (display suites)

**Where**  `hydromodpy/display/`.

Each named plot implements the ``Figure`` protocol:

```python
class Figure(Protocol):
    name: ClassVar[str]
    def plot(self, sim: Simulation, *, save_path: Path | None) -> None: ...
```

Figures are registered by name. End users reach them via
``sim.plot("watertable_map")`` or ``hmp.display.get("watertable_map")``.
Saving is controlled by the caller; the display module never decides
whether to show or save.

**Why**  rendering is on-demand, consistent across suites, and driven
by configuration (``DisplayConfig`` in ``[display]``) rather than global
environment variables.

---

## 4. Delineation Backend

**Where**  `hydromodpy/spatial/delineation/`.

Watershed delineation is backend-agnostic. ``WhiteboxBackend`` wraps the
standalone binary; ``WhiteboxWorkflowsBackend`` wraps the pip-installed
wheel. Both expose the same interface used by the flow-analysis steps:

```python
backend = get_whitebox_backend(preferred="wheel")
backend.breach_depressions(input_dem, output_dem)
```

**Why**  swap binaries at runtime (CI uses the wheel, production uses
the binary). Downstream code never touches the binary path.

---

## 5. Data Manager

**Where**  `hydromodpy/data/common/base_manager.py`,
`data/variables/<variable>/*.py`.

Every input variable (hydrometry, piezometry, geology, hydrography…) has
a subclass of ``BaseVariableManager``:

```python
class HydrometryManager(BaseVariableManager):
    def load(self) -> LoadResult: ...
```

``LoadResult`` wraps the fetched data and a fingerprint used for
provenance. The ``DataManagersPlanner`` resolves explicit configuration
+ inferred requirements into an immutable ``DataLoadPlan``.

**Why**  a uniform fetch/cache/verify story across heterogeneous
sources (Hubeau, BD Topage, SIM2, synthetic, custom…). Adding a new
variable is one manager class plus one entry in the registry.

---

## 6. Config via Pydantic + Annotated

**Where**  `hydromodpy/core/config/` and every `*_config.py` file.

All configuration is expressed as Pydantic models with
``ConfigDict(extra="forbid")``. Quantity-bearing fields use
``Annotated`` aliases from ``core/units/`` so users can write
``"50 m"`` or ``"0.1 km"``. ``ParamLevel`` (user/dev/expert) controls
which fields show up in generated TOML templates.

```python
class DomainConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zone_ids: list[str]
    depth_model: DepthModelConfig = Field(default_factory=...)
```

**Why**  one parser for TOML, CLI, and Python dictionaries; automatic
JSON schema export for frontend integration; units handled in one place.

---

## 7. Calibration Adapter

**Where**  `hydromodpy/calibration/adapters/`.

A calibration adapter bridges the ``Simulation`` façade and the
``CalibrationEngine``. It exposes the subset of state the engine needs
(parameters, metrics, caching key) without coupling the engine to the
runtime.

```python
class FlowCalibrationAdapter:
    def evaluate(self, params: dict) -> Metrics: ...
```

**Why**  the engine stays generic (gradient-free, mostly), and each
process type plugs in via a thin adapter.

---

## 8. Objective

**Where**  `hydromodpy/calibration/objective.py`.

An ``Objective`` aggregates one or more weighted ``Metric`` instances
into a scalar loss. Objectives are declarative (configured from TOML)
and stateless — they take a ``Metrics`` dict and return a float.

```python
class Objective:
    def __call__(self, metrics: Metrics) -> float: ...
```

**Why**  swap the calibration target (streamflow NSE, joint piezo/Q
loss, multi-site average) without touching the engine.

---

## 9. Metric

**Where**  `hydromodpy/calibration/objective.py` (metric registry),
`hydromodpy/results/metrics.py`.

A ``Metric`` is a callable that compares a simulated series against an
observation series:

```python
class Metric(Protocol):
    name: ClassVar[str]
    def __call__(self, sim, obs) -> float: ...
```

Canonical metrics: ``nse``, ``kge``, ``rmse``, ``mae``. Metrics are
persisted to the ``metrics`` table in the catalog with PK
``(sim_id, station_id, metric_name)``.

**Why**  one vocabulary for metric names across calibration, display,
exports, and the catalog.

---

## 10. Figure Protocol (frontend hook)

**Where**  `hydromodpy/schema/`, consumed by external UIs.

Any object meant to drive a UI widget (figure selector, parameter form,
metric panel) exposes a JSON-compatible contract. The
``hydromodpy/schema/`` package ships helpers to dump Pydantic models as
JSON schema (``schema export`` CLI) and to partially validate
user-edited TOML so a frontend can surface errors field-by-field
instead of aborting on the first exception.

**Why**  the codebase doubles as a backend for external frontends;
keeping the contract declarative (Pydantic + schema export) avoids
duplicating structure in the UI layer.

---

## Further reading

- ``docs/developers/simulation_catalog_architecture.md`` — storage layer.
- ``docs/developers/frontend_hooks.md`` — how external UIs integrate.
- ``docs/developers/glossary.md`` — canonical naming conventions.
- ``architecture_cible/`` — target architecture specs (reference only;
  implementation may have diverged).
