Package: solver
===============

.. include:: ../../../../../hydromodpy/solver/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: solver

Inside the package
------------------

The parts
~~~~~~~~~

``base/`` holds what every backend shares. It has the ``SolverAdapter`` Protocol
(``adapter_protocol.py``), the registries of adapters and extractors with their entry-point
groups (``registry.py``), the twelve attributes a backend declares, ``SolverConfig``
(``solver_config.py``, the ``[solver]`` table), the ``[simulation]``, ``[simulation.results]``
and ``[observation]`` tables, the plan, the planner and the runner (``plan.py``,
``planner.py``, ``runner.py``), the rule that chooses ``rerun`` (``rerun.py``), the drain
conductance, the observable contracts (``observables.py``), the lookup of a cell by its
coordinates and the scratch cleanup.

``modflow_grid/`` is the grid description the MODFLOW family reads. ``solver_mesh.py`` is
``SolverMesh``, the cells of the planar mesh stacked in layers with their top, bottoms and
``idomain``, and the DISV arguments MODFLOW 6 takes. ``discretization_spatial.py`` builds it
from the domain, the vertical layering and the ``sgrid`` table of ``sgrid_config.py``, and
wraps it in ``SolverGridContext``, the view both backends read. ``top_sampling.py`` samples
the DEM onto the cell tops, by point or by zone, with the channel pixels kept apart from the
hillslope. ``discretization_temporal.py`` turns the time grid of the ``Model`` into stress
periods, steps and steady flags, with the first-period policy the model carries.
``active_connectivity.py`` counts the groups of active cells and warns when the grid falls
apart in pieces. MODFLOW 6 writes DISV for every grid, and MODFLOW-NWT writes DIS and only
takes a structured grid.

``modflow_common/`` is what MODFLOW 6 and MODFLOW-NWT do the same way. A module that only one
of them reads lives in that backend. The folder holds six groups of modules.

- The binaries. ``binaries.py`` finds, downloads and checks the MODFLOW executables and
  ``libmf6``, keeps the manifest of the cache, and makes a bundled binary executable.
- The run. ``flow_run.py`` is the life of a flow adapter: build the options and the solver
  from the ``Model`` of the run, write, solve, read the listing. The adapter reads
  ``ctx.state.setup.model`` and nothing it was built from. The wall time of the solve goes to
  ``SolverRun.solve_s`` and never to the metrics of the run. ``listing.py`` reads the listing
  file (``percent_discrepancies``, ``model_percent_discrepancies``,
  ``last_percent_discrepancy``, ``worst_percent_discrepancy``,
  ``simulation_listing_failure_lines`` and ``xt3d_failure_hint``). ``final_state_head`` and
  ``end_of_last_period`` shape the last head and its date for ``final_state/``.
  ``progress.py`` shows the solve while it runs, ``options.py`` holds the pre-processing, run
  and NWT post-processing options, and ``routing_context.py`` and ``raster_export.py`` write
  the solver DEM and its D8 pointer.
- The properties. ``property_mapping.py`` maps K, Kv, Sy and Ss on the solver mesh at its
  layer-center depths, through ``model.properties.property_table``. ``runtime_arrays.py``
  shapes the concentration overrides of a transport run.
- The descent of the solver mesh. ``flow_directions.py``, ``catchment_basin.py`` and
  ``descent_store.py`` give the receiver of each cell, its basin and the sidecar that stores
  them. ``flow_directions.py`` also says whether a build uses the river network A, which
  ``prepare_solver`` read once on the cells (``Model.geometry.channel_exits``), and pins D on
  it with the active columns and the lakes of the build. The rest lives in
  ``hydromodpy/catchment/drainage``, where ``channel_tree.py`` reads A and ``routing.py``
  routes a release down a graph.
- The extraction. ``time_units.py`` reads the time unit a run declared, ``period_steps.py``
  groups the saved steps by stress period, ``budget_components.py`` names the budget terms,
  ``budget_policy.py`` records what a budget extraction kept, ``field_slab.py`` bounds the
  slab of a field write, ``sink_mask.py`` marks the closed depressions and
  ``boundary_roles.py`` stores the role of each constant-head cell.
- The calibration readers. ``calibration_extractors.py`` reads heads and budgets for a trial,
  and ``observable_extraction.py`` turns them into observables, with the per-cell discharge
  routed on the graph of D. ``mt3dms_extractor_base.py`` is the concentration extractor that
  MT3DMS and MODFLOW 6 GWT share.

``modflow6/`` is MODFLOW 6 through FloPy. ``build.py`` wires the packages, and ``builders/``
has one module per package (CHD and DRN, recharge and EVT, wells, LAK, SFR, MVR, HFB and the
solver options). ``run.py`` runs the model, ``rerun.py`` solves a solved model again for a new
K or Sy, and ``api/`` runs libmf6 in process. ``adapter.py`` is the flow adapter,
``transport.py`` the GWT transport adapter and ``prt.py`` the PRT adapter. ``extractors/``
reads the files, ``support/`` holds the small helpers of the backend and
``modflow6_config.py`` is its ``[solver.modflow6]`` table.

``modflow_nwt/`` is MODFLOW-NWT through FloPy. ``nwt/`` holds the solver, the pre-processing,
the payload builders and ``nwt_config.py``. ``adapter.py`` is the flow adapter, ``modpath/``
and ``mt3dms/`` hold the two transport adapters, and ``extractors/`` reads the files.

``boussinesq/`` is the in-house solver on an unstructured mesh, and ``linear_reservoir/`` is
the global backend, where one cell takes the whole catchment. Each folder has the README of its port.

Extractors sit beside the adapters of each backend, in ``extractors/``. An extractor carries
``process_type``, ``solver_name`` and an ``extract(solver_run, store, retention)`` method,
which the ``extract`` of the adapter calls. Its category is read on the adapter.

Import rules
~~~~~~~~~~~~

``tests/unit/architecture/layer_matrix.yaml`` gives solver ``core``, ``schema``,
``catchment``, ``mesh``, ``model``, ``results`` and itself. No ``solver_layout.yaml`` orders
the parts, so the shape below holds by habit and by the import scanner of
``tools/audit/build_graph.py``.

1. Backends do not import each other. ``modflow6``, ``modflow_nwt`` and ``boussinesq`` each
   import ``base``, and the first two also import ``modflow_common`` and ``modflow_grid``. No
   gate checks the independence.
2. ``modflow_common`` and ``modflow_grid`` import ``base`` and each other, never a backend.
3. ``base/registry.py`` names every built-in adapter and extractor by a dotted path in
   ``_BUILTIN_PATHS`` and ``_BUILTIN_EXTRACTOR_PATHS`` and imports it on first lookup, through
   the engine of ``core/plugin_registry.py``. Loading ``hydromodpy.solver.base.plan``
   therefore loads no backend.
4. A private name read inside a backend package is declared in that package, and
   ``tests/unit/architecture/test_layers.py`` checks it.
5. A layer above ``solver`` imports the registry from ``solver/base/registry.py`` and calls
   ``solvers.get``, ``solvers.create`` and ``solvers.names``. The runner in ``base/runner.py``
   imports no backend, and ``calibration`` reaches the solvers through ``solver.base`` only
   (see :doc:`calibration`).

How a run reaches a backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Choose. :toml:`solver.backend` is the name of a registered flow backend (``modflow6``,
   ``modflow_nwt``, ``boussinesq``, ``linear_reservoir`` or a plugin). A name the registry does
   not serve is refused while the file is read, with the names it serves. The settings of a
   backend are the table ``[solver.<name>]``, checked by the ``options`` class on its adapter.
   A file that uses something the backend leaves out of ``supports`` is refused as well, by
   ``config/cross_checks.py``.
2. Plan. The planner (``base/planner.py``) reads the ``requires`` attribute of the backend
   class, ``solvers.get(process_type, solver).requires``, to bind a transport run to an
   earlier flow run.
3. Look up. The runner calls ``solvers.create(process_type, solver)``. The registry imports
   the built-in class, or a plugin, and returns an instance. ``slot_for`` fills the
   ``RunSlot`` and ``options_for`` reads the table of the backend.
4. Run. ``solve_one`` calls ``adapter.validate(model, options, slot)``, then
   ``adapter.build(model, options, slot, upstream)``, which makes the backend model in memory,
   then ``adapter.run(solver_run)``, which writes its files in the run folder, solves and
   returns a ``SolverRun``. A calibration trial that gives a solved run of the same model asks
   ``adapter.rerun`` first, and the adapter may decline.
5. Extract. The workflow step ``run_outputs.py`` calls
   ``adapter.extract(solver_run, store, retention)``, which writes the fields and tables of the
   run into the results store through the extractor registered under the same key. After
   extraction, ``adapter.cleanup(solver_run)`` removes the scratch files when the run keeps no
   solver files.
6. Observe. ``adapter.observables(solver_run, requests)`` serves a calibration trial from the
   run folder. An adapter that cannot produce a requested observable raises
   ``ObservableNotAvailableError``.

What a backend can do is declared on its adapter class, in the twelve attributes of
``base/README.md``. ``writes`` lists what it stores, ``supports`` the traits of the ``Model``
it honours and ``category`` how it resolves space. One copy of the category remains, and a
contract test holds it equal to the adapters. It is the category table of
``results/catalog/constants.py``, which the index reads when a manifest has none.

Where to add what
~~~~~~~~~~~~~~~~~

- A solver in the tree is a package with its adapter (``adapter.py``) and its extractor. The
  adapter class carries the twelve attributes and the five members of the contract, and it
  has one entry in each of ``_BUILTIN_PATHS`` and ``_BUILTIN_EXTRACTOR_PATHS``. An ``options``
  class on the adapter holds the settings that a file writes under ``[solver.<name>]``. The
  steps are in :doc:`../how-to/add-a-solver`.
- A solver out of the tree is an adapter class on the ``hydromodpy.solver`` entry-point group
  and an extractor on ``hydromodpy.solver.extractor``. The entry-point name is
  ``<process_type>_<name>``, and the registry compares it with the joined attributes of the
  loaded class, so a name that holds an underscore stays whole.
- A MODFLOW 6 package is a module in ``modflow6/builders/`` with its build step, called from
  ``modflow6/build.py`` in the build order. A builder reads another one only along that order.
- A process type is described in :doc:`../how-to/add-a-process`.
- A callback around a run is a field of ``ProcessCallbacks`` and its call in
  ``SimulationRunner``.
- Something both MODFLOW backends do goes in ``modflow_common/``, or in ``modflow_grid/`` when
  it is about the grid.
- A boundary kind is added in ``boundary_condition_registry.py`` of ``model/boundaries``, then
  as a package in each backend that lists it in ``supports``.
- A backend option is a field on ``modflow6_config.py``, ``nwt/nwt_config.py`` or
  ``boussinesq/options.py``, with a profile and a description. A file writes it under
  ``[solver.<name>]``.
- An observable a backend can serve has its reader in the extractor of the backend or in
  ``modflow_common/observable_extraction.py``, and its state in ``base/observables.py``.
