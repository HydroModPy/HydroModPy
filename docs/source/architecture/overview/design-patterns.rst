Design Patterns
===============

Most non-trivial features in the codebase rest on one of the patterns
documented below. Knowing them makes the code predictable and shortens
the time-to-first-edit when extending a backend, a data manager, or a
figure family.

For complementary reading, see :doc:`mental-model-and-design-choices`
and :doc:`code-reading-guide`.

1. SolverAdapter Protocol
-------------------------

Location: ``hydromodpy/simulation/adapters/base.py``; concrete adapters
sit next to each backend under ``hydromodpy/solver/<backend>/adapters/``
(``solver/modflow_nwt/adapters/flow.py``,
``solver/modflow6/adapters/flow.py``,
``solver/boussinesq/adapters/flow.py``; shared helpers in
``solver/modflow_common/flow_adapter_helpers.py``).

A ``SolverAdapter`` is a Protocol that binds a ``(process_type,
solver_name)`` pair to a concrete solver. It accepts a domain process
(``Flow``, ``Transport``) and drives the underlying FloPy, PETSc, or
SciPy machinery.

.. code-block:: python

   class SolverAdapter(Protocol):
       process_type: ClassVar[str]
       solver_name: ClassVar[str]
       def build(self, plan: ProcessRun, state: WorkflowContext) -> SolveResult: ...

Registration lives in ``solver/base/registry.py``. The planner resolves
the adapter at plan-construction time; the runner only sees the
Protocol.

Why: decouples the domain (Flow, Transport) from solver specifics.
Adding a solver means writing one adapter class plus one line in the
registry.

2. Pipeline Step
----------------

Location: ``hydromodpy/workflow/steps/`` with the base in
``hydromodpy/workflow/internals/step.py``.

A step is a pure function ``(WorkflowContext) -> WorkflowContext`` (or
a restricted sub-context). Each step updates exactly one scope of the
context: setup, data-loading, mesh, solve, extract, derive, export.

.. code-block:: python

   def resolve_support_configs(ctx: SetupContext) -> SetupContext:
       ...

Steps live in short files named after their concern and never import
``Project`` or the runner. Pipeline composition is declared elsewhere
(``hydromodpy/workflow/pipelines/``), which keeps steps reusable in
tests.

Why: testability. Each step is a pure function with explicit inputs and
outputs. A new workflow assembles steps without forking the
orchestration layer.

3. Figure registry
------------------

Location: ``hydromodpy/display/figure.py`` with concrete figures in
``hydromodpy/display/figures/``.

Each named figure implements the ``Figure`` Protocol:

.. code-block:: python

   class Figure(Protocol):
       name: ClassVar[str]
       def plot(self, sim: Run, *, save_path: Path | None) -> None: ...

Figures are registered by name. User-facing call:
``run.plot("watertable_map")`` or ``hmp.display.get("watertable_map")``.
The caller decides between rendering and writing; the display module
does not impose a side effect.

Why: on-demand rendering, consistent across families, driven by the
``[display]`` section (``DisplayConfig`` in
``hydromodpy/display/config.py``) rather than environment variables.

4. Delineation backend
----------------------

Location: ``hydromodpy/spatial/delineation/``.

Delineation is backend-agnostic. The integrated backends are
``whitebox_workflows`` and ``synthetic``; alternative implementations
register through ``register_backend()`` and are looked up via
``get_backend()``. ``DelineationBackend`` (``base.py``) describes the
minimal contract consumed by the flow-analysis steps.

.. code-block:: python

   backend = get_backend("whitebox_workflows")
   backend.flow.breach_depressions(input_dem, output_dem)

Why: lets a runtime backend be added without exposing a public
placeholder.

5. Data Manager
---------------

Location: ``hydromodpy/data/base_manager.py`` with one subclass per
variable under ``hydromodpy/data/variables/<variable>/``.

Every input variable (hydrometry, piezometry, geology, hydrography,
climate) has a subclass of ``BaseVariableManager``:

.. code-block:: python

   class HydrometryManager(BaseVariableManager):
       def load(self) -> LoadResult: ...

``LoadResult`` wraps the fetched data plus a fingerprint used for
provenance. ``DataManagersPlanner`` (``hydromodpy/data/planner.py``)
resolves the explicit config and the inferred needs into an immutable
``DataLoadPlan``.

Why: a uniform fetch / cache / verify story for heterogeneous sources
(Hub'Eau, BD Topage, SIM2, synthetic, custom). Adding a variable means
writing one manager and registering it.

6. Pydantic config with Annotated units
---------------------------------------

Location: ``hydromodpy/config/`` and every ``*_config.py``.

The full configuration is expressed as Pydantic models with
``ConfigDict(extra="forbid")``. Fields carrying physical quantities use
``Annotated`` aliases from ``hydromodpy/core/units/``: ``Length``,
``Time``, ``FlowRate``, ``HydraulicConductivity``, ``SpecificStorage``,
``SpecificYield``, ``Area``, ``Volume``, ``Dimensionless``. Users can
write ``"50 m"`` or ``"0.1 km"``.

``Profile`` (``hydromodpy.core.config_kit.profile.Profile``, an
``IntEnum``) controls field visibility in generated TOML files.

.. code-block:: python

   class DomainConfig(BaseModel):
       model_config = ConfigDict(extra="forbid")
       zone_ids: list[str]
       depth_model: DepthModelConfig = Field(default_factory=...)

Why: a single parser for TOML, CLI, and Python dictionaries; automatic
JSON Schema export for frontends; units handled in one place.

7. Calibration adapters
-----------------------

Location: ``hydromodpy/calibration/adapters/``.

A calibration adapter plugs a concrete optimizer into the engine. The
available adapters:

- ``scipy_adapter.py``: SciPy routines (Nelder-Mead, differential
  evolution).
- ``optuna_adapter.py``: Optuna's Bayesian engine.
- ``grid_adapter.py``: grid sweep.
- ``gp_mapping_adapter.py``: GP surrogate plus parameter mapping.
- ``da_mh_gp_adapter.py``: data-assimilation Metropolis-Hastings on a
  GP surrogate.

Each adapter exposes a common interface to the engine so that
parameters, metrics, and cache keys flow without coupling the engine
to runtime details.

Why: the engine stays generic. Each optimization strategy plugs in
through a thin adapter.

8. Objective
------------

Location: ``hydromodpy/calibration/objective.py``.

An ``Objective`` aggregates one or more weighted ``Metric`` values into
a scalar loss. Objectives are declarative (configured from TOML) and
stateless: they accept a ``Metrics`` dict and return a float.

.. code-block:: python

   class Objective:
       def __call__(self, metrics: Metrics) -> float: ...

Why: lets the calibration target swap (NSE on discharge, joint
piezo-discharge loss, multi-site mean) without touching the engine.

9. Metric
---------

Locations: ``hydromodpy/core/metrics/`` (canonical: NSE, KGE, RMSE,
MAE, log-NSE, bias, pbias, correlation) and
``hydromodpy/calibration/metrics.py`` (trial-side extractor
``build_metric_extractor``).

A ``Metric`` is a callable that compares a simulated series to an
observed series:

.. code-block:: python

   class Metric(Protocol):
       name: ClassVar[str]
       def __call__(self, sim, obs) -> float: ...

Canonical metrics: ``nse``, ``kge``, ``rmse``, ``mae``. Persisted in
the catalog ``metrics`` table with the primary key
``(sim_id, station_id, metric_name)``.

Why: a single naming vocabulary for calibration, display, export, and
catalog.

10. Frontend hooks via Pydantic plus JSON Schema
------------------------------------------------

Location: ``hydromodpy/schema/``.

Anything that drives a UI widget (figure picker, parameter form,
metrics panel) exposes a JSON-compatible contract. The ``schema``
package exposes helpers that dump Pydantic models as JSON Schema
(``hmp schema export``) and validate a partially edited TOML, so a
frontend can flag errors field by field without raising on the first
invalid value.

Why: the codebase also serves as the backend for external frontends.
Keeping the contract declarative (Pydantic plus exported schema) avoids
duplicating the structure on the UI side.

See also
--------

- :doc:`mental-model-and-design-choices` for the layer responsibilities
  behind these patterns.
- :doc:`code-reading-guide` for a package-by-package reading order.
- :doc:`two-databases` for the persistence layer that several of these
  patterns talk to.
