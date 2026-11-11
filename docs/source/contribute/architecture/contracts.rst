Contracts and design patterns
=============================

This page says which names the contract of :doc:`/about/versions` covers: the
public import paths, the plugin ports, the two storage Protocols and the field
registry. Then it lists the patterns the code reuses. Know the patterns and the
code is predictable: adding a backend, a data variable or a figure follows one of
them.

The public facade
-----------------

A user imports ``import hydromodpy as hmp``. The package exports a short flat set:
the fifteen verbs of ``hydromodpy/project/api.py`` (``open``, ``run``, ``check``,
``calibrate``, ``spinup``, ``replay``, ``stop``, ``status``, ``trash``, ``compare``,
``show``, ``export``, ``publish``, ``example``, ``doctor``), the five objects they take
and return (``Project``, ``Run``, ``RunSet``, ``Session``, ``HydroModPyConfig``), the
categories of the exception hierarchy and ``__version__``, all listed in
``hydromodpy.__all__``. A verb takes text, numbers, paths or mappings and returns a
value with ``to_dict()``, a path or diagnostics, so a server sends it as JSON. A
command of ``hmp`` calls its verb, and nothing else at the top level reads a lower
package. ``tests/unit/architecture/test_surfaces.py`` holds this. The generated :doc:`/reference/python/index` documents every
name, so this page does not repeat them. Everything else, the config section of a
variable or a solver class, stays reachable through ``hydromodpy.<module>`` and is out of
the contract unless the list below names its module. ``hmp.open(path)`` opens what a path stands for: a ``Project``, a ``Run``, a
``Session`` or a ``Workspace``. ``project.store`` is the read-only ``Catalog``
(``hydromodpy.results.catalog.facade.Catalog``) over
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
- ``hydromodpy.core.units.types``: the quantity types of a config field.
- ``hydromodpy.core.config_kit.profile``: ``Profile``, the level of a config field.
- ``hydromodpy.core.tracking.input_file``: ``InputFile``, a file a run depends on.
- ``hydromodpy.core.contracts.observables``: what a solver answers.
- ``hydromodpy.core.state.run_state``: ``RunState``, what a transport adapter reads,
  and ``SlotRequest``, what a calibration trial asks of the slot its runs solve in.
- ``hydromodpy.schema.config_schema``: the JSON Schema export, ``export_full_schema``.
- ``hydromodpy.config.check``: ``check`` and ``phrase``, the sentence of each code a
  check gives, read from ``hydromodpy/schema/phrases.toml``.
- ``hydromodpy.catchment.terrain.port``: the terrain engine port.
- ``hydromodpy.mesh.port``: the mesh engine port.
- ``hydromodpy.data.source.port``: the data source port.
- ``hydromodpy.results.exporters.port``: the export format port.
- ``hydromodpy.data.contracts.spatial_field``: the records a gridded provider returns.
- ``hydromodpy.data.families.base_config``: the base of a data variable config.
- ``hydromodpy.data.families.grids``: the base of a gridded variable.
- ``hydromodpy.data.families.timeseries_config``: the base of a series variable.
- ``hydromodpy.model.transport.transport_config``: ``TransportConfig``, the [transport] section and its per-solver tables.
- ``hydromodpy.solver.base.adapter_protocol``: the solver port and the extractor port,
  ``SolverAdapter`` and ``OutputAdapter``.
- ``hydromodpy.solver.base.plan``: ``RunSlot``, ``SolverRun`` and ``RunContext``,
  what a solver adapter receives and returns.
- ``hydromodpy.results.storage.kept``: ``Retention``, what a run keeps of its solver
  outputs, which ``extract`` receives.
- ``hydromodpy.calibration.evaluation.port``: the trial evaluator port.
- ``hydromodpy.calibration.optim.optimizer``: the base of a calibration method.
- ``hydromodpy.calibration.optim.parameters``: ``ParameterSpace``.
- ``hydromodpy.display.figure``: ``BaseFigure`` and ``FigureSpec``.
- ``hydromodpy.display.figure_registry``: ``figures`` (the registry), ``get``,
  ``resolve``, ``names``, ``figure_option_names``.
- ``hydromodpy.display.figures.scalar_face_map``: the base of a map of one value per
  face.
- ``hydromodpy.display.report.engine``: the report engine with no domain: ``Block``,
  ``Metric``, ``Picture``, ``Table``, ``Link``, ``Prose`` and ``write_pages``.
- ``hydromodpy.results.run.view``: ``Run``.
- ``hydromodpy.results.zarr_store.simulation_zarr``: ``SimulationZarr``, the field store an exporter reads.
- ``hydromodpy.results.exporters.fields``: what every field exporter reads the same
  way.
- ``hydromodpy.results.catalog.indexer``: ``rebuild_index``.
- ``hydromodpy.results.annotations``: tags and notes of a run directory.
- ``hydromodpy.results.trash``: the trash of a run directory.
- ``hydromodpy.cli.conventions``: the shared argparse grammar.
- ``hydromodpy.cli.output``: what a command writes for a program.
- ``hydromodpy.cli.exit_codes``: the exit codes of a command and ``fail``.
- ``hydromodpy.cli.refs``: the workspace and project a command is given.
- ``hydromodpy.project.api``: the fifteen verbs, which each command of ``hmp`` calls.

.. public-modules-end

Plugin ports
------------

A plugin joins through an entry-point group. Each group has one Protocol.
The entry-point name of a plugin follows the key of its registry: a source is
declared under ``<section>_<source_id>``, an export format under its ``name``.

.. list-table::
   :header-rows: 1
   :widths: 33 37 30

   * - Group
     - Protocol
     - Stability
   * - ``hydromodpy.terrain.engine``
     - ``TerrainEngine``, ``hydromodpy.catchment.terrain.port``
     - stable
   * - ``hydromodpy.mesh.engine``
     - ``MeshEngine``, ``hydromodpy.mesh.port``
     - stable
   * - ``hydromodpy.data.source``
     - ``DataSource``, ``hydromodpy.data.source.port``
     - stable
   * - ``hydromodpy.export.format``
     - ``ExportWriter``, ``hydromodpy.results.exporters.port``
     - experimental
   * - ``hydromodpy.calibration.evaluator``
     - ``TrialEvaluator``, ``hydromodpy.calibration.evaluation.port``
     - experimental
   * - ``hydromodpy.calibration.optimizer``
     - ``Optimizer``, ``hydromodpy.calibration.optim.optimizer``
     - experimental
   * - ``hydromodpy.solver``
     - ``SolverAdapter``, ``hydromodpy.solver.base.adapter_protocol``
     - experimental
   * - ``hydromodpy.solver.extractor``
     - ``OutputAdapter``, ``hydromodpy.solver.base.adapter_protocol``
     - experimental

A stable port is frozen as the facade is: a change keeps the old form working for
two minor versions. Its types are its own, so it depends on nothing else of the

An experimental port can change in any minor version. ``TrialEvaluator`` waits for
the rework of the calibration, and two of its construction options (``trial_ctx``,
``metric_fn``) are internals of the calibration. ``SolverAdapter`` still hands a
transport adapter ``state.setup`` and ``state.cfg``, so a refactor of either reaches
it, and ``OutputAdapter`` writes through the methods of ``RunStore``. The stored
result of a run is not experimental, whichever port wrote it.

``tests/ports/`` holds the conformance suites, one file per port. They are not in the wheel, so run
them from a clone with your distribution installed. The suites of the terrain, mesh and evaluator ports run on every engine the registry serves. The suite of the data source port runs its declarations and its refusals on
every source the registry serves, as :doc:`how-to/add-a-data-source` explains,
and the suite of the export port holds every format of ``export_formats`` to
what its declarations say, as :doc:`how-to/add-an-exporter` explains. The suite of the solver port,
``tests/ports/test_solver.py``, checks the twelve attributes of every backend the
registry serves, and builds, solves and extracts every flow on every mesh engine it accepts.

Changing a contract
-------------------

A change to the facade, to a stable port or to the two Protocols below is announced.
The old name follows the rules of :doc:`/about/versions`. A name that leaves in 2.1.0
or earlier is refused with its new form. From 2.2.0 on it keeps working for two minor
versions and warns. This page and :doc:`storage-layout` change with it. A renamed TOML key gets its
``[[migration]]`` row in the register of changes, ``hydromodpy/schema/changes.toml``, with
``since``, and the row stays there after its delay for the runs already sealed. A renamed name of
``hmp.__all__`` gets its entry in ``OLD_NAMES`` of ``hydromodpy/_lazy.py``, and a renamed
``hmp`` command or flag its entry in ``OLD_CLI_FORMS`` of
``hydromodpy/cli/conventions.py``, both with ``since``. Each warns with a
``FutureWarning``, then forwards to the new form. A test fails once an entry outlives its
delay. All three read that delay from ``hydromodpy/schema/changes.py``, where it is written once. ``OLD_NAMES`` and ``OLD_CLI_FORMS`` hold, marked ``refused``, the names,
the members of the public objects, the commands and the flags that left before the first
stable version. They keep no alias: each is refused with a message that names its new
form, and leaves the table at 2.2. The members live in ``hydromodpy/core/old_members.py``,
which each object reads. After 2.0.0 a public method of the result objects is not in them:
the gate below names its removal, and the changelog says it. A change to a stored
schema needs a bump of the matching
version constant and a reader for the old version. The constants and where they live
are in :doc:`data-scopes`.

``tests/unit/architecture/test_surfaces.py`` compares the public
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

The data cache has no database and no Protocol. Each fetched file has a sidecar
``<file>.json``, and the sidecars are the cache (``hydromodpy/data/provenance/sidecars.py``,
:doc:`data-scopes`).

``hydromodpy.lock`` freezes the data cache and the files of the user of a project before a
run. The launcher of a ``[sites]`` project writes it, and ``hmp data lock`` writes it by hand
for a single project. ``hmp run --frozen`` on a project TOML verifies it and refuses without one. No
other run needs it, because the manifest of a run records the inputs of that run: ``hmp
replay <run>`` reads that record. See
:ref:`artifact-policy` for the sidecar formats that are allowed.

The index and the run store
----------------------------

The catalog facade reaches the SQL index through ``DuckDBBackend``
(``hydromodpy/results/catalog/adapters/duckdb.py``), the one backend of the
catalog, with no Protocol in front of it.
``tests/unit/results/catalog/adapters/test_duckdb.py`` holds its tests.

Workflow steps, solver adapters and post-run extractors write a run through
``hydromodpy.results.storage.run_store.RunStore``, the run store of a run
directory, which never opens an index: ``write_parameters``, ``write_timeseries``,
``write_budget``, ``write_field``, ``write_time``, ``write_crs``, ``write_mesh``,
``write_metric``, ``write_provenance``, ``write_run_environment``,
``register_tracked_files`` and more. The reads go through
``hydromodpy.results.catalog.facade.Catalog``, from the index.

Field registry
--------------

Source: ``hydromodpy/results/field_registry.py``. ``FIELD_REGISTRY`` maps a logical
field name (``head``, ``watertable_depth``, ``drain_accumulation_flux``, ...) to a
``FieldDescriptor``: its shape, the Zarr path inside the run store, and its CF
metadata (standard name, units, coordinates). ``get``, ``has``, ``all_names``,
``all_zarr_paths`` and ``cf_attrs`` read it. ``Run.read``, the Zarr writers, the
exporters and the figures all read this one table, so a field is described the
same way in every layer. Adding a field is a registry entry and a writer; readers
keep working.

Design patterns
---------------

SolverAdapter: a Protocol and twelve attributes per backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``hydromodpy/solver/base/adapter_protocol.py`` defines the Protocol. An adapter
class carries twelve attributes (``name``, ``process_type``, ``accepted_meshes``,
``geometry``, ``writes``, ``reads``, ``supports``, ``options``, ``category``,
``native_step``, ``mutable`` and ``requires``) and five members the runner calls:
``validate(model, options, slot)``, ``build(model, options, slot, ctx)``,
``run(solver_run)``, ``cleanup(solver_run)`` and ``extract(solver_run, store, retention)``.
Three members are optional. ``rerun(previous, model, slot)`` is present if and only if
``mutable`` is not empty, and ``observables`` and ``declared_observables`` serve a
calibration trial. Every call that makes or changes a run returns a ``SolverRun``, the
frozen record of the ``Model``, the options, the ``RunSlot`` the run solves in, the solver
model, the output folder, the input files written and whether the run is written and
solved. Concrete adapters sit beside their backend (``solver/modflow6/adapter.py``,
``solver/boussinesq/adapter.py``, ``solver/modflow_nwt/adapter.py``, and the transports
in ``solver/modflow6/adapters/`` and ``solver/modflow_nwt/adapters/``), registered in
``solver/base/registry.py``, which keys a backend on ``<process_type>_<name>``. The
planner resolves the key and the runner only sees the Protocol. ``extract`` hands the
run to the extractor registered under the same key, a class that answers
``OutputAdapter``, which a plugin publishes in the ``hydromodpy.solver.extractor`` group.

*Why:* the domain objects (``Flow``, ``Transport``) stay independent of solver
details. A solver is one adapter class with its attributes and a line in each registry table
(:doc:`how-to/add-a-solver`).

A backend gets no hook into the runner. The runner fills the ``RunSlot`` (the run folder,
the run name, the folder of the binaries, the early stop of a trial) and reads the
``options`` table, so a flow adapter reads nothing of the setup, the configuration or the
store. ``rerun`` is a shortcut between two solves of a calibration. It rewrites only the
input files that a changed K or Sy touches, and it is bit-identical to a new build. It has
nothing to do with ``hmp catalog rerun``, which replays a sealed run from its configuration.

The TOML meets this port in three places, and none of them names a backend.
``solver.backend`` is a string checked against the registry while the file is read, and an
unknown name is refused with the names the installation serves. The table
``[solver.<name>]`` is validated by the ``options`` class of the adapter. And
``hydromodpy/config/cross_checks.py`` refuses a key the chosen backend leaves out of
``supports``: the message gives the key the file wrote, the backend, and the backends that honor
it, and the error is ``IncompatibleCapabilitiesError``. A transport solver whose ``requires``
does not name the flow of the run is refused in the same way. Two pairs of keys spoil
each other whatever the solver, a lake with a ``spinup_cyclic`` start for one, and they are rows
of ``CONTAMINATIONS``. A run sealed before a refusal existed is read back with a warning.
The one refusal that waits for the solve is a transport behind a steady start whose heads
did not converge, because convergence is only known then.

Pipeline step
~~~~~~~~~~~~~

``hydromodpy/workflow/steps/``, with the protocol in
``hydromodpy/workflow/step.py``. A step is a class with a ``name`` and a
``run(state: PipelineState) -> PipelineState``. It declares the payload keys it
reads and writes (``reads``, ``writes``), checked in both directions by
``test_run_path.py``, and optionally the TOML subtrees it consumes
(``config_sections``), which is how a calibration finds the first step that must
run again. A persistent step adds ``artifacts`` and ``rebuild_state`` so a resume
does not repeat it. Pipelines are assembled by ``standard_steps`` in ``workflow/steps/sequence.py``.

*Why:* testability and resume. A new workflow assembles steps without forking the
orchestration layer.

Figure registry
~~~~~~~~~~~~~~~

``hydromodpy/display/figure.py`` defines ``BaseFigure``, ``FigureSpec`` (static
metadata: the fields and tables the figure reads). ``BaseFigure`` is the one figure type.
A subclass implements ``render(sim, ax)``; the base builds the matplotlib
figure, applies the style and saves, and takes the name of the figure from its
``spec``. Concrete figures live in ``display/figures/`` and are listed by the
generated table ``display/figure_table.py`` (``python -m tools.figure_table``),
which ``display/figure_registry.py`` reads to answer a name, so resolving a
name imports no figure module. ``run.figure("watertable_map")`` and the
``[display]`` section call them by name. A figure reads a ``Run`` and never a
solver file.

*Why:* on-demand rendering, consistent across families (:doc:`how-to/add-a-figure`).

Plugin registry
~~~~~~~~~~~~~~~

One engine, ``hydromodpy/core/plugin_registry.py``, holds every plugin
surface of the package. Each surface is one instance with the attributes that
key its members: the solver backends and the terrain, mesh and evaluator
engines on their entry-point groups, the data sources on
``hydromodpy.data.source`` keyed by the section and the name of the class, the
export formats on ``hydromodpy.export.format`` keyed by their name. The
figures are the exception on purpose: they have no group, and their registry
reads a table generated from the tree (``python -m tools.figure_table``), so a
name is answered without importing a module. Every registry names the members
it ships and the members the installation resolves, so a config field
validated against it (:doc:`data-scopes`) refuses an unknown name with the
names it serves.

An entry point that cannot be imported is kept by the engine with its target
and its reason: the name is refused with both when a user asks for it, and no
package is named that the registry does not read. Two entry points of the same
name and target, from two distributions, count as one.

*Why:* one lookup story for every plugin (:doc:`how-to/add-a-solver`,
:doc:`how-to/add-a-data-source`, :doc:`how-to/add-an-exporter`), and no list
of names written beside a registry.

Terrain engine
~~~~~~~~~~~~~~

``hydromodpy/catchment/terrain/port.py``. ``TerrainEngine`` has five members
(``condition_dem``, ``drainage_directions``, ``flow_accumulation``, ``stream_network`` and
``delineate``), the strings ``engine_id`` and ``engine_version``, and ``engine_digest()``.
Each member writes where the caller says and returns a product that declares its units,
transform, pointer convention and CRS. The conditioning method is ``fill``, ``breach``, a
``CappedBreach`` or ``provided``. ``ConditionedDem.provided(path)`` wraps a DEM that another
tool conditioned, and ``condition_dem`` refuses ``provided`` with ``TerrainRequestError``.
The checks both engines share are ``require_conditioning``, ``require_accumulation``,
``require_stream`` and ``require_delineable``. An engine is found through ``terrain_engines`` in
``catchment/terrain/registry.py``.

*Why:* the flow-routing library behind the port can change without a caller noticing.

Delineation backend
~~~~~~~~~~~~~~~~~~~

``hydromodpy/catchment/delineation/__init__.py``. The one backend is
``whitebox_workflows``. ``get_whitebox_backend()`` builds the Whitebox facade on the first
call and returns the same object after that. A function that wants another backend takes it
as an argument, and ``resolve_delineation_backend(backend)`` returns it. There is no registry.
A third party reaches the routing through the terrain engine port.

*Why:* one process holds one Whitebox environment, and a registry with one entry only added
a name to remember.

Data variable
~~~~~~~~~~~~~

``hydromodpy/data/families/stations.py`` holds
``StationVariable``, with one subclass per variable under
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
  ``hydromodpy/calibration/optim/adapters/`` declared with its ``name`` and ``options``
  models and reached through ``PluginRegistry`` or entry points, with ``ask`` and ``tell``
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
