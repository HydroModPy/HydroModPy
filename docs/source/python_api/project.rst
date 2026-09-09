hmp.Project
===========

``Project`` is the object-oriented face of the Python API. Where the verbs of :doc:`index` take a config and return a
result, :class:`hydromodpy.project.Project` keeps the resolved config, the workspace, the geographic runtime, the loaded
data, the mesh and the catalog handle alive between calls. It is the setup-once, run-many surface used by notebooks,
calibration loops and custom analysis scripts.

``Project`` is a facade, not an engine. The execution engine is :class:`hydromodpy.workflow.runner.Pipeline`, which runs
ordered steps with checkpoint and resume support. Both drive the same :mod:`hydromodpy.workflow.steps` helpers;
``Project`` only offers a more interactive way to call them.

Construction
------------

Construction is cheap. ``__init__`` validates the configuration, resolves the time grid and the data plan, and builds an
empty runtime context. It performs no heavy I/O.

.. code-block:: python

   import hydromodpy as hmp

   project = hmp.Project("project.toml")

The constructor is polymorphic: it accepts a TOML path, a :class:`~hydromodpy.config.HydroModPyConfig`, a ``dict``
payload, or a JSON string, auto-detected. Keyword options are ``solver`` (auto-detected from the config otherwise),
``headless`` (disable display and postprocess runners, useful in calibration loops) and ``no_display``.

The heavy model phase builds lazily on the first :meth:`~hydromodpy.project.Project.simulate` call or on the first
accessor that needs it. Build it eagerly with :meth:`~hydromodpy.project.Project.prepare`, which returns ``self``, or
call the phase verbs one by one.

Model phase
-----------

The model phase turns a validated config into a runnable model. Each verb is callable on its own, and each one runs the
phases below it when they have not happened yet.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Method
     - Role
   * - ``setup_workspace()``
     - Bootstrap the shared runtime anchor: workspace, geographic context, domain and process objects. Opens the
       catalog as a side effect. Idempotent: calling it twice resets those objects.
   * - ``build_geographic(reuse_dem=False)``
     - Mark the geographic and domain runtime ready, record the project phase, and invalidate downstream data and mesh
       state. Runs ``setup_workspace()`` first when needed.
   * - ``rebuild_geographic(reuse_dem=False)``
     - Drop the setup products and rerun the geographic pipeline, invalidating the mesh.
   * - ``load_data(types=None)``
     - Load the external forcings declared in the ``[data]`` section. Restrict the work with ``types``.
   * - ``reload_data(types=...)``
     - Reload a named subset of data variables.
   * - ``build_mesh(**overrides)``
     - Build the mesh used by the solver. Keyword overrides patch the mesh configuration before the step runs.
   * - ``prepare()``
     - Run geographic, data and mesh in order. Returns the project.

The fields of the ``[data]`` section are defined in :doc:`/user_guide/config_reference/data`, not here.

Run phase
---------

:meth:`~hydromodpy.project.Project.simulate` runs one simulation through the configured workflow and returns its
:class:`~hydromodpy.results.run.Run`. It builds the model phase on first call, then runs the Pipeline. Flow parameter
overrides such as ``Sy``, ``K`` and ``Ss``, plus the special keys ``thickness``, ``first_clim`` and ``properties``, are
applied to the plan before the Pipeline runs. Other keywords cover the run name, ``resume`` from a workflow journal,
``from_step`` and ``until_step`` bounds, ``dry_run``, ``frozen`` input references, ``no_display`` and ``parallel``.
A dry run, and some non-simulation workflows, return ``None``.

.. code-block:: python

   run = project.simulate(name="baseline", Sy=0.05)

There is no sweep verb. A sweep is a plain Python loop over :meth:`~hydromodpy.project.Project.simulate`:

.. code-block:: python

   for value in [1e-3, 5e-3, 1e-2]:
       project.simulate(name=f"sy_{value}", Sy=value)

:meth:`~hydromodpy.project.Project.calibrate` runs a calibration campaign on the project, either from a TOML path passed
as ``config_path`` or from parameters, outputs, objective blocks and a method given in Python.

:meth:`~hydromodpy.project.Project.spinup` runs the cyclic spin-up loop, restarting the representative window each cycle
from the previous cycle's state until heads and lake stage converge. It defaults to the ``[spinup]`` section of the
project config. The returned ``SpinupResult`` carries ``restart_from``, ready to feed a production run's
:ref:`flow.restart_from <flow-restart-from>`.

:meth:`~hydromodpy.project.Project.rerun` is a classmethod. It takes a persisted :class:`~hydromodpy.results.run.Run`,
rebuilds the configuration from its snapshot, applies an optional ``config_overrides`` deep-merge patch, and launches a
new simulation whose ``parent_sim_id`` points at the original. A run with no config snapshot raises ``ConfigMissingError``.

Overview, comparison, testbed and site selection are TOML workflows, not ``Project`` methods. They run through
:func:`hydromodpy.run` on the ``[workflow] mode`` selector, whose values are ``simulation``, ``calibration``,
``overview``, ``comparison``, ``testbed`` and ``site_selection``. Use ``Project`` for repeated simulations, calibration
and spin-up; use :func:`hydromodpy.run` for the one-shot workflows.

Lifecycle
---------

A project owns an open DuckDB catalog handle and a few cached preprocessing files.
:meth:`~hydromodpy.project.Project.close` closes the catalog and cleans the preprocessing tree. It reads the geographic
object straight from the context, so closing an unused project never triggers a lazy build. The preprocessing tree
survives when the geographic configuration asked for the intermediate rasters on disk.

Use the project as a context manager so ``close`` runs even when an exception is raised:

.. code-block:: python

   import hydromodpy as hmp

   with hmp.Project("project.toml") as project:
       project.setup_workspace()
       project.build_geographic()
       project.load_data()
       project.build_mesh()
       run = project.simulate(name="baseline", Sy=0.05)

Project state
-------------

:class:`hydromodpy.project.state.ProjectState` is the typed dataclass that owns the runtime state of a project. The
twenty-one private attributes that were once mutated directly on the ``Project`` instance live in this container.

The runtime state mixes immutable inputs (the resolved configuration, the solver name), cached preprocessing results
(the geographic context, the mesh inputs) and live counters (the run counter, the run history). Spread as
dunder-attributes on ``Project`` they made the surface noisy and resisted static typing. In one ``slots=True`` dataclass
they give mypy and pyright a single typed view and read as state rather than behaviour.

The fields group by concern:

- **Configuration**: ``config_path``, ``cfg``, ``solver``, ``time_grid``.
- **Display flags**: ``headless``, ``no_display``.
- **Mesh inputs**: ``mesh_section_data``, ``external_mesh_input``, ``mesh_constraints_mode``,
  ``spatial_support_registry``, ``requested_support_ids``, ``requested_domain_supports``.
- **Workflow runtime**: ``ctx``, the :class:`~hydromodpy.core.state.run_state.WorkflowContext`, and ``store``, the open
  :class:`~hydromodpy.results.catalog.Catalog`.
- **Bookkeeping**: ``project_name``, ``run_counter``, ``active_runs``, ``last_wall_seconds``, ``phase``,
  ``data_loaded``, ``run_history``.

``Project`` proxies private reads and writes through ``__getattr__`` and ``__setattr__``, so call sites that touch the
legacy names keep working:

.. code-block:: python

   project._cfg          # reads project._state.cfg
   project._config_path  # reads project._state.config_path
   project._run_history  # reads project._state.run_history

The mapping lives in :data:`hydromodpy.project.state.PROJECT_ATTR_TO_STATE_FIELD`. A name absent from the map falls back
to the regular attribute machinery, so ``project._runner`` and ``project._catalog`` keep living on the instance. The
public read-only view of the config is ``project.config``.

Read-only properties
--------------------

``config``, ``data``, ``runs``, ``data_loaded``, ``has_mesh``, ``geographic``, ``domain``, ``store``, ``time_grid``,
``loaded_data`` and ``workflow_context`` expose the same runtime state that TOML workflows populate through the
Pipeline. ``geographic``, ``domain``, ``store``, ``loaded_data``, ``runs`` and ``project[sim_id]`` trigger the lazy model
build; ``config``, ``has_mesh`` and ``time_grid`` do not. ``project[sim_id]`` returns the
:class:`~hydromodpy.results.run.Run` for that identifier.

Accessors
---------

Two properties return small accessor objects. They scope catalog queries and data introspection to the current project,
which keeps the facade surface small while staying explicit at the call site.

``project.data`` returns a :class:`~hydromodpy.project.accessors.ProjectDataAccessor`. It lists the input-data variables
already loaded and reports the ones the declared plan still expects.

.. code-block:: python

   import hydromodpy as hmp

   with hmp.Project("project.toml") as project:
       df = project.data.list()        # variables loaded in cache
       todo = project.data.missing()   # declared but not loaded

Use it when a workflow step complains about a missing variable, or to confirm that a manual
``project.load_data(types=...)`` covered the expected set.

``project.runs`` returns a :class:`~hydromodpy.project.accessors.ProjectRunsAccessor`. It wraps the project's
:class:`~hydromodpy.results.catalog.Catalog` and pre-filters every query by the current project name.

- ``list()`` returns a DataFrame summary of every persisted run for the project.
- ``find(**filters)`` filters by metadata such as ``solver``, ``status`` or run name.
- ``latest()`` returns the most recent run, or ``None`` when the project has none yet.
- ``best(metric)`` returns the run ranking first on a metric stored in the catalog, highest value first.
- ``delete(sim_id, remove_storage=True)`` removes a simulation from the catalog and, by default, its artefacts.

.. code-block:: python

   with hmp.Project("project.toml") as project:
       project.simulate(Sy=0.05, name="probe-1")
       project.simulate(Sy=0.08, name="probe-2")

       last = project.runs.latest()
       probes = project.runs.find(name="probe-1")
       best = project.runs.best("nse")

The accessor yields full :class:`~hydromodpy.results.run.Run` objects, not identifiers, so the caller can chain into
``run.field(...)``, ``run.timeseries(...)`` or ``hmp.read(run, "head")``.

The catalog without a project
-----------------------------

A project handle is convenient for the run loop but unnecessary when the caller only wants to read previously persisted
runs. :func:`hydromodpy.open` returns a :class:`~hydromodpy.results.catalog.Catalog` rooted at one project. It is the
read-side complement of :meth:`~hydromodpy.project.Project.simulate` and mirrors the ``xarray.open_dataset`` intent: one
call, a ready-to-query object.

The argument is a **project** directory, the one holding ``project.toml`` and ``.hmp/index.duckdb``. A workspace root
such as ``~/hydromodpy`` is not a project and owns no index: pass ``~/hydromodpy/projects/<name>`` instead. With the
default ``create=False`` the call raises ``FileNotFoundError`` when no index exists; pass ``create=True`` to initialise
an empty catalog.

.. code-block:: python

   import hydromodpy as hmp

   cat = hmp.open("~/hmp_workspace/projects/naizin")
   last = cat.latest()
   da = hmp.read(last, "head")

``cat`` is scoped to that one project: it sees every run persisted under the project root and nothing from its
neighbours. Federation across projects is the job of :func:`hydromodpy.index`, which registers one row per project root
and expands a workspace root into the project roots it holds.

The catalog is the single door for queries. ``cat.find`` is the one filtered entry point and returns a ``RunSet``; an
unknown filter key raises ``ValueError`` listing the valid filters. ``cat.frame`` returns the full DataFrame. Schema
discovery and selectors live on the same object: ``cat.describe``, ``cat.tables``, ``cat.columns``, ``cat.variables``,
``cat.metrics``, ``cat.stations``, then ``cat.latest``, ``cat.best``, ``cat.worst``, ``cat.rank``, ``cat[ref]``,
``cat.resolve``, ``cat.sql`` and ``cat.read`` for the by-id read path. Input data is reached through
:class:`hydromodpy.catalog.InputsNamespace` or the ``hmp data`` CLI.

.. code-block:: python

   import hydromodpy as hmp

   cat = hmp.open("~/proj/naizin")
   sims = cat.find(solver="modflow6")
   frame = cat.frame
   projects = hmp.index()

Catalog and reader compose naturally inside a notebook session:

.. code-block:: python

   import hydromodpy as hmp

   cat = hmp.open("~/hmp_workspace/projects/naizin")
   run = cat.latest()

   head_t0 = hmp.read(run, "head", time=0)
   head_all = hmp.read(run, "head")
   q_out = hmp.read(run, "discharge", sel={"station": "outlet"})

:func:`hydromodpy.read` auto-dispatches the variable name through the field registry (Zarr), the timeseries table
(DuckDB) and the geographic features table (GeoParquet), so a single call handles the three storage kinds.

When to prefer TOML and the CLI
-------------------------------

Use TOML plus ``hmp run`` for reproducible research, teaching material and CI. Use ``Project`` when a notebook, a
calibration method, a custom analysis loop or an application needs to orchestrate the same steps directly. The two
surfaces execute the same workflow steps, so a script and its TOML equivalent produce the same run.

Reference
---------

.. autoclass:: hydromodpy.project.Project
   :members:
   :no-index:

See Also
--------

- :doc:`/user_guide/config_reference/index` -- the TOML side of every option named on this page.
- :doc:`/cli/index` -- the command-line equivalents of these verbs.
- :doc:`open` -- the catalog verb documented on its own page.
- :doc:`run` -- the one-shot workflow launcher.
- :class:`hydromodpy.results.run.Run` -- per-simulation result view.
- :mod:`hydromodpy.project.phases` -- model-phase functions that mutate the state in place.
- :doc:`/api/index` -- autosummary reference for every module.
