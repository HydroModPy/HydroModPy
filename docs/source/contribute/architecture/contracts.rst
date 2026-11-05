Contracts and design patterns
=============================

This page says which names the contract of :doc:`/about/versions` covers: the
public import paths, the plugin ports, the two storage Protocols and the field
registry. Then it lists the patterns the code reuses. Know the patterns and the
code is predictable: adding a backend, a data manager or a figure follows one of
them.

The public facade
-----------------

A user imports ``import hydromodpy as hmp``. The package exports a short flat set:
the verbs of ``hydromodpy/_api.py``, ``Project``, ``Run``, ``RunSet``, ``Catalog``,
``Session``, ``Workspace``, ``HydroModPyConfig`` and the exception hierarchy, all listed
in ``hydromodpy.__all__``. The generated :doc:`/reference/python/index` documents every
name, so this page does not repeat them. Everything else, the config section of a
variable or a solver class, stays reachable through ``hydromodpy.<module>`` and is out of
the contract unless the list below names its module. ``hmp.open(path)`` opens what a path stands for: a ``Project``, a ``Run``, a
``Session`` or a ``Workspace``. ``project.store`` is the read-only ``Catalog`` over
``.hmp/index.duckdb``, the index derived from the run directories.

Public import paths
-------------------

Two lists are public. One is ``hydromodpy.__all__``. The other is the short list
of modules below, which a plugin, an extension or a test has to import from. Their
public names follow the same rules as the facade. Every other module is internal
whatever its name, and can move in any version. A module with a leading underscore
is private to its package.

``tests/unit/architecture/test_public_import_paths.py`` reads this list. It fails
when a listed module disappears, and when a page of the reference or of the how-to
guides imports a module that is neither listed nor in the facade.

.. public-modules-start

- ``hydromodpy.core.exceptions``: the exception hierarchy.
- ``hydromodpy.core.logging``: ``get_logger``.
- ``hydromodpy.core.pipeline_steps``: ``STEP_NAMES``, the frozen names of the steps.
- ``hydromodpy.core.units``: the quantity types of a config field.
- ``hydromodpy.core.config_kit.profile``: ``Profile``, the level of a config field.
- ``hydromodpy.core.tracking.input_file``: ``InputFile``, a file a run depends on.
- ``hydromodpy.core.contracts.observables``: what a solver and a forward model
  answer.
- ``hydromodpy.core.state.run_state``: ``RunState``, what a solver adapter reads.
- ``hydromodpy.schema``: the JSON Schema export and the partial validator.
- ``hydromodpy.spatial.terrain.port``: the terrain engine port.
- ``hydromodpy.spatial.mesh.port``: the mesh engine port.
- ``hydromodpy.data.source.port``: the data source port.
- ``hydromodpy.data.contracts.spatial_field``: the records a gridded provider returns.
- ``hydromodpy.data.managers.base_config``: the base of a data variable config.
- ``hydromodpy.data.managers.base_manager_field``: the base of a gridded variable.
- ``hydromodpy.data.managers.timeseries_config``: the base of a series variable.
- ``hydromodpy.physics.transport.transport``: ``Transport``, the transport process.
- ``hydromodpy.solver.base.adapter_protocol``: the solver port.
- ``hydromodpy.simulation.planning.plan``: ``RunContext`` and ``RunExecutionResult``,
  what a solver adapter receives and returns.
- ``hydromodpy.simulation.extraction.derivation.base``: the solver extractor port.
- ``hydromodpy.calibration.evaluation.port``: the trial evaluator port.
- ``hydromodpy.calibration.evaluation.forward``: the forward model port.
- ``hydromodpy.calibration.optim.optimizer``: the base of a calibration method.
- ``hydromodpy.calibration.optim.parameters``: ``ParameterSpace``.
- ``hydromodpy.display.figure``: ``BaseFigure`` and ``FigureSpec``.
- ``hydromodpy.display.figure_registry``: ``register``.
- ``hydromodpy.display.figures.scalar_face_map``: the base of a map of one value per
  face.
- ``hydromodpy.display.report_blocks``: the static HTML blocks of a report.
- ``hydromodpy.results.run``: ``Run``.
- ``hydromodpy.results.zarr_store``: ``SimulationZarr``, the field store an exporter reads.
- ``hydromodpy.results.exporters.fields``: what every field exporter reads the same
  way.
- ``hydromodpy.results.catalog.indexer``: ``rebuild_index``.
- ``hydromodpy.results.annotations``: tags and notes of a run directory.
- ``hydromodpy.results.trash``: the trash of a run directory.
- ``hydromodpy.cli.conventions``: the shared argparse grammar.
- ``hydromodpy.cli.output``: what a command writes for a program.
- ``hydromodpy.cli.helpers``: exit codes and workspace resolution of a command.

.. public-modules-end

Plugin ports
------------

A plugin joins through an entry-point group. Each group has one Protocol.

.. list-table::
   :header-rows: 1
   :widths: 33 37 30

   * - Group
     - Protocol
     - Stability
   * - ``hydromodpy.terrain.engine``
     - ``TerrainEngine``, ``hydromodpy.spatial.terrain.port``
     - stable
   * - ``hydromodpy.mesh.engine``
     - ``MeshEngine``, ``hydromodpy.spatial.mesh.port``
     - stable
   * - ``hydromodpy.data.source``
     - ``DataSource``, ``hydromodpy.data.source.port``
     - stable
   * - ``hydromodpy.calibration.forward_model``
     - ``ForwardModel``, ``hydromodpy.calibration.evaluation.forward``
     - stable signature, experimental construction options
   * - ``hydromodpy.calibration.evaluator``
     - ``TrialEvaluator``, ``hydromodpy.calibration.evaluation.port``
     - experimental
   * - ``hydromodpy.solver``
     - ``SolverAdapter``, ``hydromodpy.solver.base.adapter_protocol``
     - experimental
   * - ``hydromodpy.solver.extractor``
     - ``OutputAdapter``, ``hydromodpy.simulation.extraction.derivation.base``
     - experimental

A stable port is frozen as the facade is: a change keeps the old form working for
two minor versions. Its types are its own, so it depends on nothing else of the
package. For ``ForwardModel`` the stable part is ``model_id`` and
``simulate(ForwardRequest) -> ForwardOutcome``. The arguments its constructor can ask
for (``cfg``, ``cfg_path``, ``space``, ``workspace``) are experimental, because
``cfg`` is the whole configuration.

An experimental port can change in any minor version. ``TrialEvaluator`` waits for
the rework of the calibration, and two of its construction options (``trial_ctx``,
``metric_fn``) are internals of the calibration. ``SolverAdapter`` hands over
``state.setup`` and ``state.cfg``, so a refactor of either reaches the adapter, and
``OutputAdapter`` writes through the 30 methods of ``SimulationStore``. The stored
result of a run is not experimental, whichever port wrote it.

``tests/contract/`` holds the conformance suites. They are not in the wheel, so run
them from a clone with your distribution installed. The suites of the terrain, mesh,
evaluator and forward model ports run on every engine the registry serves. The suite
of the data source port runs its declarations and its refusals on every source the
registry serves, as :doc:`how-to/add-a-data-source` explains. The solver ports have
no suite yet, which is one more reason why they are experimental.

Changing a contract
-------------------

A change to the facade, to a stable port or to the two Protocols below is announced.
The old name keeps working for two minor versions and warns, and this page and
:doc:`storage-layout` change with it. A renamed TOML key gets its row in
``hydromodpy/config/config_migration.py``, with ``since``. A renamed name of
``hmp.__all__`` gets its entry in ``OLD_NAMES`` of ``hydromodpy/_lazy.py``, and a renamed
``hmp`` command or flag its entry in ``OLD_CLI_FORMS`` of
``hydromodpy/cli/conventions.py``, both with ``since``. Each warns with a
``FutureWarning``, then forwards to the new form. A test fails once a row or an entry
outlives its delay. ``OLD_NAMES`` and ``OLD_CLI_FORMS`` hold, marked ``refused``, the names,
the members of the public objects, the commands and the flags that left before the first
stable version. They keep no alias: each is refused with a message that names its new
form, and leaves the table at 2.2. The members live in ``hydromodpy/core/old_members.py``,
which each object reads. After 2.0.0 a public method of the result objects is not in them:
the gate below names its removal, and the changelog says it. A change to a stored
schema needs a bump of the matching
version constant and a reader for the old version. The constants and where they live
are in :doc:`data-scopes`.

``tests/unit/architecture/test_public_surfaces_are_frozen.py`` compares the public
surfaces with the snapshot files of ``tests/unit/architecture/surface/``: the names
and signatures of ``hmp.__all__``, the public methods of the result objects, the
command line with its flags, the exit codes, the TOML paths with their types and
defaults, and the process descriptions. A difference fails the test, which says what
changed. To accept it, regenerate the files and commit them with the change:

.. code-block:: bash

   python -m tools.surface_snapshot

The command refuses to drop a stable TOML key that has no row in the migration table
that rewrites it, because a form the loader only refuses is no migration. A key it drops
goes into ``removed_toml_keys.tsv``, and the test holds it there until its delay ends.
From the first stable version on, the command refuses in the same way a name of
``hmp.__all__``, a command or a flag that leaves with no entry in its table, and what
leaves goes into ``removed_names.tsv``. It also refuses a stable key marked experimental,
because the mark would free the key from its promise. Before that version a key marked
experimental stays in ``demoted_toml_keys.tsv``, and it still needs its migration to leave.

Storage
-------

Disk is the truth and the index is derived. A run directory holds everything a run
needs to be read, replayed, resumed or compared: Zarr for fields, Parquet for tables,
and its manifest and provenance. ``.hmp/index.duckdb`` is a query index over those
directories and rebuilds at any time (:doc:`storage-layout`). DuckDB is the only SQL
backend the contract promises. The catalog reaches it through a port, and the port
takes SQL in the dialect of DuckDB.

``hydromodpy.lock`` freezes the data cache of a project before a run. The launcher of
a ``[sites]`` project writes it, and ``hmp lock`` writes it by hand for a single
project. ``hmp run --frozen`` on a project TOML verifies it and refuses without one. No
other run needs it, because the manifest of a run records the inputs of that run: on the
``config.toml`` of a run, ``--frozen`` reads that record. See
:ref:`artifact-policy` for the sidecar formats that are allowed.

Storage Protocol: ``CatalogBackend``
------------------------------------

Source: ``hydromodpy/results/catalog/ports.py``. The catalog facade reaches the SQL
store only through this ``runtime_checkable`` Protocol. The in-tree adapter is
``DuckDBBackend`` (``results/catalog/adapters/duckdb.py``).

.. code-block:: python

   class CatalogBackend(Protocol):
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
the writes (``write_parameters``, ``write_timeseries``, ``write_budget``,
``write_field``, ``write_time``, ``write_crs``, ``write_mesh``, ``write_metric``,
``write_provenance``, ``write_run_environment``, ``register_tracked_files``, and
more); the reads (``query_field``, ``query_timeseries``, ``list_simulations``,
``open_zarr``, ``__getitem__``); and ``close`` with the context-manager protocol.
The writes are implemented by the run store of a run directory
(``hydromodpy.results.storage.run_store.RunStore``), which never opens an index;
the reads by ``hydromodpy.results.catalog.Catalog``, from the index.

Field registry
--------------

Source: ``hydromodpy/results/field_registry.py``. ``FIELD_REGISTRY`` maps a logical
field name (``head``, ``watertable_depth``, ``drain_accumulation_flux``, ...) to a
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
``hydromodpy/workflow/step.py``. A step is a class with a ``name`` and a
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
  ``ConfigBlockObjective``, which scores one declared or implicit block, and
  ``CompositeObjective``, their weighted sum.
- **Criterion.** ``hydromodpy/calibration/criteria/`` defines the ``Criterion``
  Protocol (``requirements()`` and ``score(simulated, observed)``). A file names a
  criterion and ``criteria/registry.py`` answers. The scoring kernels are in
  ``criteria/series.py`` (``METRICS``), and the canonical series metrics (NSE, KGE,
  RMSE, MAE, bias, correlation) in ``hydromodpy/core/scoring/metrics.py``.

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
