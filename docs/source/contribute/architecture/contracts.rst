Contracts and design patterns
=============================

This page lists what users and integrators can rely on (the public facade, two
storage Protocols, the field registry), then the patterns the code reuses. Know
the patterns and the code is predictable: adding a backend, a data manager or a
figure follows one of them.

The public facade
-----------------

The single supported import path is ``import hydromodpy as hmp``. The package
exports a flat set of verbs from ``hydromodpy/_api.py`` and a set of config
classes, all listed in ``hydromodpy.__all__`` and documented in the generated
Python reference (:doc:`/reference/python/index`). The verbs:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Symbol
     - Role
   * - ``hmp.open(workspace, *, create=False, read_only=True)``
     - Open a project catalog. Returns a ``Catalog`` backed by
       ``.hmp/index.duckdb`` and calls ``ensure_schema()`` on its backend.
   * - ``hmp.index(db_path=None, *, read_only=True)``
     - Open the machine-wide ``GlobalIndex``, the registry of project roots. One
       row is one project; a workspace root expands into the projects it holds.
   * - ``hmp.read(sim, var, ...)``
     - Read a variable of a run. The name is resolved against the field registry, then
       the ``timeseries`` table, then the geographic features.
   * - ``hmp.run(config, **kwargs)``
     - Run the workflow a TOML file or a config object declares.
   * - ``hmp.calibrate(config, *, phase=None, ...)``
     - Drive a calibration session.
   * - ``hmp.figure(sim, name, ...)`` and ``hmp.viz.show``
     - Render one figure of a run.
   * - ``hmp.export(sim, variables, ...)``
     - Export variables of a run.
   * - ``hmp.compare_pair``, ``hmp.report``, ``hmp.spinup``, ``hmp.doctor``
     - Pairwise comparison, the HTML report of a calibration session, the
       cyclic spin-up, an environment diagnostic.

A change to the facade or to the two Protocols below is a breaking change. It
needs a migration entry under the relevant ``migrations/`` folder when it touches
a stored schema, a bump of the matching version constant, and an update of this
page and of :doc:`storage-layout`. The constants and where they live are in
:doc:`data-scopes`. The code keeps no compatibility shim, alias or re-export
outside the facade.

Storage Protocol: ``CatalogBackend``
------------------------------------

Source: ``hydromodpy/results/catalog/ports.py``. The catalog facade reaches the SQL
store only through this ``runtime_checkable`` Protocol. The in-tree adapter is
``DuckDBBackend`` (``results/catalog/adapters/duckdb.py``).

.. code-block:: python

   class CatalogBackend(Protocol):
       def ensure_schema(self) -> None: ...
       def query(self, sql, params=None) -> pandas.DataFrame: ...
       def execute(self, sql, params=None) -> None: ...
       def fetch_one(self, sql, params=None) -> tuple | None: ...
       def fetch_all(self, sql, params=None) -> list[tuple]: ...
       def insert(self, table: str, row: dict[str, Any]) -> None: ...
       def upsert(...) -> None: ...
       def transaction(self) -> AbstractContextManager[None]: ...
       def close(self) -> None: ...

Conformance is structural: there is no base class to inherit.
``tests/contract/test_catalog_backend_contract.py`` holds the contract tests of the
backend.

Storage Protocol: ``SimulationStore``
-------------------------------------

Source: ``hydromodpy/results/catalog/protocol.py``. It is the minimal write and
read surface that workflow steps, solver adapters and post-run extractors call:
``register_simulation``; the writes (``write_parameters``, ``write_timeseries``,
``write_budget``, ``write_field``, ``write_time``, ``write_crs``, ``write_mesh``,
``write_metric``, ``write_provenance``, ``write_run_environment``,
``register_tracked_files``, and more); the reads (``query_field``,
``query_timeseries``, ``list_simulations``, ``open_zarr``, ``__getitem__``); and
``finalize``, ``close`` and the context-manager protocol. The default
implementation is ``hydromodpy.results.catalog.Catalog``.

Field registry
--------------

Source: ``hydromodpy/results/field_registry.py``. ``FIELD_REGISTRY`` maps a logical
field name (``head``, ``watertable_depth``, ``accumulation_flux``, ...) to a
``FieldDescriptor``: its shape, the Zarr path inside the run store, and its CF
metadata (standard name, units, coordinates). ``get``, ``has``, ``all_names``,
``all_zarr_paths`` and ``cf_attrs`` read it. ``hmp.read``, the Zarr writers, the
exporters and the figures all read this one table, so a field is described the
same way in every layer. Adding a field is a registry entry and a writer; readers
keep working.

Design patterns
---------------

SolverAdapter: a Protocol per ``(process_type, solver_name)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``hydromodpy/solver/base/adapter_protocol.py`` defines the Protocol. An adapter
declares ``process_type``, ``solver_name`` and ``requires`` (the earlier runs it
depends on), and implements ``validate(ctx)``, ``execute(ctx)``, ``cleanup(ctx)``
and ``extract_observables(ctx, store, requests)``. Concrete adapters sit beside
their backend (``solver/modflow6/adapters/flow.py``, ``solver/boussinesq/adapters/``,
``solver/modflow_nwt/adapters/``), registered in ``solver/base/registry.py``. The
planner resolves the pair and the runner only sees the Protocol.

*Why:* the domain objects (``Flow``, ``Transport``) stay independent of solver
details. A solver is one adapter class and a few registry lines
(:doc:`how-to/add-a-solver`).

Pipeline step
~~~~~~~~~~~~~

``hydromodpy/workflow/steps/``, with the protocol in
``hydromodpy/workflow/internals/step.py``. A step is a class with a ``name`` and a
``run(state: PipelineState) -> PipelineState``. It declares the payload keys it
reads and writes (``reads``, ``writes``), checked in both directions by
``test_step_payload_keys.py``, and optionally the TOML subtrees it consumes
(``config_sections``), which is how a calibration finds the first step that must
run again. A persistent step adds ``artifacts`` and ``rebuild_state`` so a resume
does not repeat it. Pipelines are assembled in ``workflow/pipelines/``.

*Why:* testability and resume. A new workflow assembles steps without forking the
orchestration layer.

Figure registry
~~~~~~~~~~~~~~~

``hydromodpy/display/figure.py`` defines ``BaseFigure``, ``FigureSpec`` (static
metadata: the fields and tables the figure reads, the solvers it fits) and the
``Figure`` Protocol. A subclass implements ``render(sim, ax)``; the base builds
the matplotlib figure, applies the style and saves. Concrete figures live in
``display/figures/`` and register by name in ``display/figure_registry.py``.
``hmp.figure(run, "watertable_map")`` and the ``[display]`` section call them by
name. A figure reads a ``Run`` and never a solver file.

*Why:* on-demand rendering, consistent across families (:doc:`how-to/add-a-figure`).

Delineation backend
~~~~~~~~~~~~~~~~~~~

``hydromodpy/spatial/delineation/registry.py``. The integrated backend is
``whitebox_workflows``. A backend registers with ``register_backend(name, loader)``
and is looked up with ``get_backend(name)``. The loader imports lazily.

*Why:* a runtime backend can be added without a public placeholder.

Data manager
~~~~~~~~~~~~

``hydromodpy/data/managers/base_manager_variable.py`` holds
``BaseVariableManager``, with one subclass per variable under
``hydromodpy/data/variables/<variable>/``. A subclass sets ``VARIABLE_NAME``,
``INTERNAL_UNIT`` and ``SOURCES`` and ``load()`` returns a ``LoadResult``.
``DataPlanner`` (``data/loading/planner.py``) turns the explicit config and the
needs it infers into an immutable ``DataLoadPlan``.

*Why:* one fetch, cache and verify story for sources as different as Hub'Eau, BD
Topage, SIM2 and a synthetic series (:doc:`how-to/add-a-data-variable`).

Pydantic config with unit types
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The whole configuration is Pydantic models that inherit ``HydroModelBase`` and
forbid extra keys. A field with a physical quantity uses a unit type from
``hydromodpy/core/units/`` (``Length``, ``Time``, ``FlowRate``,
``HydraulicConductivity``, ...), so the file can write ``"50 m"``. ``Profile``
sets whether a field shows by default or behind the developer and expert buttons.

*Why:* one parser for TOML, CLI and Python, an exported JSON Schema for frontends,
and units handled in one place (:doc:`how-to/add-a-config-field`).

Calibration adapters, objectives and criteria
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Adapter.** A search method is one module of
  ``hydromodpy/calibration/optim/adapters/`` registered with
  ``@register_optimizer("name")``, with ``ask`` and ``tell``
  (:doc:`how-to/add-a-calibration-method`).
- **Objective.** ``hydromodpy/calibration/optim/objective.py`` defines the
  ``Objective`` Protocol (``name`` and ``evaluate(sim)``) and its implementations,
  among them ``ScalarObjective``, ``CompositeObjective`` and
  ``ConfigBlockObjective``, which scores the declared blocks.
- **Criterion.** ``hydromodpy/calibration/criteria/`` defines the ``Criterion``
  Protocol (``requirements()`` and ``score(simulated, observed)``). A file names a
  criterion and ``criteria/registry.py`` answers. The scoring kernels are in
  ``criteria/series.py`` (``METRICS``), and the canonical series metrics (NSE, KGE,
  RMSE, MAE, bias, correlation) in ``hydromodpy/core/metrics.py``.

*Why:* the engine stays generic. A new strategy, a new objective or a new score
plugs in without touching it.

Frontend hooks
~~~~~~~~~~~~~~

``hydromodpy/schema/`` exports the Pydantic models as JSON Schema and validates one
field at a time, so a UI follows the models without copying their structure
(:doc:`how-to/build-a-frontend`).

See also
--------

- :doc:`mental-model` for the layer responsibilities behind these patterns.
- :doc:`storage-layout` for the on-disk layout these Protocols cover.
- :doc:`data-scopes` for the migration policy and the version constants.
- :doc:`packages/results` for the Python surface.
