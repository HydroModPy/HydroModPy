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

``base/`` holds what every backend shares, ``modflow_grid/`` and ``modflow_common/`` hold what
MODFLOW 6 and MODFLOW-NWT do the same way, and each backend has its own folder. A module that
only one MODFLOW backend reads lives in that backend. The backends are described in
:doc:`../engines/backends`.

Import rules
~~~~~~~~~~~~

``tests/unit/architecture/layer_matrix.yaml`` gives solver its layers, and
``tests/unit/architecture/solver_layout.yaml`` orders the parts inside it.

1. Backends do not import each other. ``modflow6``, ``modflow_nwt`` and ``boussinesq`` each
   import ``base``, and the two MODFLOW backends also import ``modflow_common`` and
   ``modflow_grid``. ``test_a_backend_never_imports_another_backend`` in
   ``tests/unit/architecture/test_package_layouts.py`` checks it.
2. ``base/registry.py`` names every built-in adapter and extractor by a dotted path
   (``_BUILTIN_PATHS``, ``_BUILTIN_EXTRACTOR_PATHS``) and imports it on first lookup. Loading
   ``hydromodpy.solver.base.plan`` therefore loads no backend.
3. A layer above ``solver`` calls ``solvers.get``, ``solvers.create`` and ``solvers.names`` of
   the registry. ``calibration`` reaches the solvers through ``solver.base`` only, so a
   backend can change without touching it (see :doc:`calibration`).
4. A private name read inside a backend package is declared in that package, and
   ``tests/unit/architecture/test_layers.py`` checks it.

How a run reaches a backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Choose. :toml:`solver.backend` is the name of a registered flow backend (``modflow6``,
   ``modflow_nwt``, ``boussinesq``, ``linear_reservoir`` or a plugin). A name the registry does
   not serve is refused while the file is read, with the names it serves. The settings of a
   backend are the table ``[solver.<name>]``, checked by the ``options`` class on its adapter.
   A file that uses something the backend leaves out of ``supports`` is refused by
   ``config/cross_checks.py``.
2. Plan. The planner (``base/planner.py``) reads the ``requires`` attribute of the backend
   class to bind a transport run to an earlier flow run.
3. Look up. The runner calls ``solvers.create(process_type, solver)``. The registry imports
   the built-in class, or a plugin, and returns an instance. ``slot_for`` fills the
   ``RunSlot`` and ``options_for`` reads the table of the backend.
4. Run. ``solve_one`` calls ``adapter.validate``, then ``adapter.build``, which makes the
   backend model in memory, then ``adapter.run``, which writes its files in the run folder,
   solves and returns a ``SolverRun``. A calibration trial that gives a solved run of the same
   model asks ``adapter.rerun`` first, and the adapter may decline.
5. Extract. The workflow step ``run_outputs.py`` calls ``adapter.extract``, which writes the
   fields and tables of the run into the results store through the extractor registered under
   the same key. Then ``adapter.cleanup`` removes the scratch files when the run keeps no
   solver files.
6. Observe. ``adapter.observables(solver_run, requests)`` serves a calibration trial from the
   run folder. An adapter that cannot produce a requested observable raises
   ``ObservableNotAvailableError``.

What a backend can do is declared on its adapter class, in the twelve attributes of
``base/README.md``. ``writes`` lists what it stores, ``supports`` the traits of the ``Model``
it honours and ``category`` how it resolves space.

Where to add what
~~~~~~~~~~~~~~~~~

- A solver in the tree is a package with its adapter and its extractor, one entry in each of
  ``_BUILTIN_PATHS`` and ``_BUILTIN_EXTRACTOR_PATHS``, and an ``options`` class for
  ``[solver.<name>]``. The steps are in :doc:`../how-to/add-a-solver`.
- A solver out of the tree is an adapter class on the ``hydromodpy.solver`` entry-point group
  and an extractor on ``hydromodpy.solver.extractor``. The entry-point name is
  ``<process_type>_<name>``, and the registry compares it with the joined attributes of the
  loaded class, so a name that holds an underscore stays whole.
- A MODFLOW 6 package is a module in ``modflow6/builders/`` with its build step, called from
  ``modflow6/build.py`` in the build order. A builder reads another one only along that order.
- Something both MODFLOW backends do goes in ``modflow_common/``, or in ``modflow_grid/`` when
  it is about the grid.
- A process type is described in :doc:`../how-to/add-a-process`. A callback around a run is a
  field of ``ProcessCallbacks`` and its call in ``SimulationRunner``.
- A boundary kind is added in ``boundary_condition_registry.py`` of ``model/boundaries``, then
  as a package in each backend that lists it in ``supports``.
- A backend option is a field on ``modflow6_config.py``, ``nwt/nwt_config.py`` or
  ``boussinesq/options.py``, with a profile and a description.
- An observable has its reader in the extractor of the backend or in
  ``modflow_common/observable_extraction.py``, and its state in ``base/observables.py``.
