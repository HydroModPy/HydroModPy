Add a solver
============

A solver in HydroModPy is one ``<process_type>_<name>`` key
bound to a concrete backend class. Today four backends ship: ``modflow6``,
``modflow_nwt``, ``boussinesq`` and the global ``linear_reservoir``, which
meshes the catchment as one cell of the ``catchment`` engine and declares
``category`` ``lumped``. This page documents how to add another flow
backend or, equivalently, a new ``transport`` /
``postprocess`` solver.

The ``hydromodpy.solver`` and ``hydromodpy.solver.extractor`` ports are
experimental (:doc:`../contracts`), so they can change in any minor version.
The run index takes the solver of a run from its manifest, so the run of a
backend outside the tree is listed and filtered like the others.

Contract
--------

A solver implements the ``SolverAdapter`` Protocol declared in
``hydromodpy/solver/base/adapter_protocol.py``. It is a class that carries
twelve attributes and five methods:

.. code-block:: python

   class SolverAdapter(Protocol):
       name: ClassVar[str]                  # "modflow6", "boussinesq", ...
       process_type: ClassVar[str]          # "flow" or "transport"
       accepted_meshes: ClassVar[frozenset[str]]
       geometry: ClassVar[str]              # "cells" or "raster"
       writes: ClassVar[tuple[str, ...]]
       reads: ClassVar[tuple[str, ...]]
       supports: ClassVar[frozenset[str]]
       options: ClassVar[type[BaseModel] | None]
       category: ClassVar[str]              # "distributed", "integrated", "lumped"
       native_step: ClassVar[str | None]
       mutable: ClassVar[frozenset[str]]
       requires: ClassVar[tuple[tuple[str, str], ...]]

       def validate(self, model, options, slot: RunSlot) -> None: ...
       def build(self, model, options, slot: RunSlot, upstream=()) -> SolverRun: ...
       def run(self, solver_run: SolverRun) -> SolverRun: ...
       def cleanup(self, solver_run: SolverRun) -> None: ...
       def extract(self, solver_run: SolverRun, store, retention: Retention) -> None: ...

The attributes have no default. ``solvers.register`` refuses a class that
leaves one out and names it, and refuses a value outside its vocabulary. They
mean this:

- ``name`` and ``process_type`` make the key, ``<process_type>_<name>``.
- ``accepted_meshes`` lists the mesh engine ids whose cells the backend reads.
  A transport declares an empty set, because it reads the mesh of its flow.
- ``geometry`` is ``cells`` or ``raster``, the member of ``Model.geometry`` the
  grid is built on.
- ``writes`` lists the fields, tables and series ``extract`` stores, by
  their stored names (``head``, ``budget/drain``, ``budgets``). A ``*`` stands
  only for a part the user names, such as a species or a lake.
- ``reads`` lists the products of an earlier run it needs. A transport reads
  ``face_flow``, the name of the field registry, and a flow reads none.
- ``supports`` lists the traits of the ``Model`` it honours. The names come from
  the closed set of ``hydromodpy/model/supports.py``: the boundaries, the
  fields of ``ModelOptions``, the initial states, the sinks and sources, the
  soil reservoir, the K tensor and the layering. A trait left out is refused
  when the file is read, in the terms of :ref:`the refusal below <add-a-solver-refusal>`.
- ``options`` is the Pydantic class of the backend's own settings table,
  ``[solver.<name>]``, or ``None`` when it reads none.
- ``category`` says how the backend resolves space. The seal writes it to the
  manifest.
- ``native_step`` is a pandas frequency alias, or ``None`` when the solver
  advances at the step of ``Model.time``.
- ``mutable`` lists the calibration parameters it can change between two solves
  of one model. It is empty unless the backend carries ``rerun``.
- ``requires`` lists the ``(process_type, name)`` keys an earlier run of the
  plan must have run.

The runner calls ``validate``, then ``build``, then ``run``. ``build`` makes
the solver model in memory and writes nothing. ``run`` writes the input files
unless ``solver_run.written`` is set, solves, and returns the run with
``solved`` true. The extract step calls ``extract``, and the export step calls
``cleanup`` when the run keeps no solver files. Three members are optional and
stay out of the body of the Protocol, because the registry requires every member
of the body:

- ``rerun(previous, model, slot)`` is present if and only if ``mutable`` is not
  empty. It solves a model that differs from ``previous.model`` only by
  properties named in ``mutable``, and rewrites only the input files they touch.
  It returns ``None`` when the change needs a build. It consumes ``previous``, so
  only the ``SolverRun`` it returns serves as a parent afterwards. It has nothing
  to do with ``hmp catalog rerun``, which replays a sealed run from its
  configuration.
- ``observables(solver_run, requests, *, time_index=None)`` and
  ``declared_observables(active)`` serve a calibration trial from the run folder,
  and come together or not at all. The whole batch of requests arrives at once,
  so each binary file is opened once. A backend refuses what it cannot produce with
  ``ObservableNotAvailableError``.

A flow backend also answers the ``CellLocator`` Protocol (``locate_cell`` and
``top_active_layer``). ``RERUN_MEMBERS`` and ``OPTIONAL_MEMBERS`` in
``adapter_protocol.py`` list these members, and the contract test reads them.

What an adapter receives is a frozen ``Model``, its options (an instance of
``options``, or ``None``) and a ``RunSlot``. ``RunSlot``, ``SolverRun`` and
``RunContext`` are declared in ``hydromodpy/solver/base/plan.py``. The runner fills
the slot: ``folder`` and ``name`` give the run folder ``slot.directory``,
``bin_dir`` is the folder of the solver binaries, ``stop_before_solve`` asks for
a build and no solve, and ``shared_forcing_dir`` is where a calibration trial keeps
forcing files that do not change between trials. ``SolverRun`` is the frozen
record that every call returns:

- ``model`` and ``options``: what the run was built from.
- ``slot``: where it solves.
- ``solver_model``: the object the adapter built, or ``None`` after a resume past
  the solver, for a run that produces none, and once the derive step releases it.
  The runner keeps it for a run that depends on this one.
- ``output_dir``: the directory that holds the raw output files, or ``None`` for
  an in-memory solver.
- ``input_files``, ``written``, ``solved``: the input files ``run`` wrote, relative
  to the run folder, and whether the files are on disk and the solve ran.
- ``metrics``: what the run has to say about itself. The catalog keeps what
  converts to a finite float and skips the rest. Optional.

``extract`` receives a ``Retention`` of ``hydromodpy/results/storage/kept.py``. It
says which per-cell budget terms the run keeps, whether the raw solver files
stay, and whether the flow between connected cells is kept:
``retention.face_flows``. The extractor writes the terms it names and no other.

A flow adapter reads nothing of the setup, the configuration or the store: the
``Model``, the options and the slot are all it needs, and a static gate in
``tests/unit/architecture/`` says so before the solver ever runs. ``build`` also
takes ``upstream``, the ``SolverRun`` objects the plan ran before it. A flow
backend receives none, a transport receives exactly one, the flow of the family
its ``requires`` names, and reads ``face_flow`` from the files and the solver
object of that run. A flow adapter writes ``face_flow`` and ``connection_cells``
to the store only when ``retention.face_flows`` is true, one value per connection
at each stored stamp; a flow solver that writes neither is refused when a
transport names ``face_flow`` in its ``reads``. A backend reads nothing of the
setup, the configuration or the store, and keeps no reference to the store's handle.

``extract`` calls a separate **extractor**, which ingests the persisted outputs
into the catalog. It is registered under the same ``<process_type>_<name>`` key
as the adapter, and carries the same ``extract`` signature:

.. code-block:: python

   class MysolverOutputAdapter:
       process_type: ClassVar[str] = "flow"
       solver_name: ClassVar[str] = "mysolver"

       def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None: ...

Files to create
---------------

For a new flow backend called ``mysolver``:

.. code-block:: text

   hydromodpy/solver/mysolver/
   |-- __init__.py
   |-- mysolver.py                   # core Solver class
   |-- mysolver_config.py            # Pydantic config block
   |-- adapter.py                    # MysolverFlowAdapter (SolverAdapter)
   |-- extractors/
   |   |-- __init__.py
   |   `-- flow.py                   # MysolverOutputAdapter (extract())
   `-- README.md                     # short rationale and code map

A transport adapter is filed beside its engine, in the module of
``hydromodpy/solver/<backend>/`` that holds the engine model, the way
``Modflow6GwtTransportAdapter`` is in ``modflow6/transport.py``.

If your backend shares MODFLOW-family lifecycle helpers, reuse
``solver/modflow_common/flow_adapter_helpers.py`` (``build_flow_model``,
``run_flow_model`` and ``resolve_solver_run_output``) instead of duplicating the
build and solve flow.

Minimal adapter skeleton
------------------------

.. code-block:: python

   # hydromodpy/solver/mysolver/adapter.py
   from dataclasses import replace
   from typing import ClassVar

   from pydantic import BaseModel

   from hydromodpy.results.storage.kept import Retention
   from hydromodpy.solver.base.plan import RunSlot, SolverRun


   class MysolverFlowAdapter:
       name: ClassVar[str] = "mysolver"
       process_type: ClassVar[str] = "flow"
       accepted_meshes: ClassVar[frozenset[str]] = frozenset({"regular", "triangle"})
       geometry: ClassVar[str] = "cells"
       writes: ClassVar[tuple[str, ...]] = ("head", "budget/drain", "budgets")
       reads: ClassVar[tuple[str, ...]] = ()
       supports: ClassVar[frozenset[str]] = frozenset({"drainage", "head_rule", "steady_start"})
       options: ClassVar[type[BaseModel] | None] = MysolverConfig
       category: ClassVar[str] = "distributed"
       native_step: ClassVar[str | None] = None
       mutable: ClassVar[frozenset[str]] = frozenset()
       requires: ClassVar[tuple[tuple[str, str], ...]] = ()

       def validate(self, model, options, slot: RunSlot) -> None:
           # cheap pre-flight checks on the Model, before anything is built
           ...

       def build(self, model, options, slot: RunSlot, ctx) -> SolverRun:
           # build the solver model in memory, under slot.directory
           solver_model = ...
           return SolverRun(slot=slot, model=model, options=options, solver_model=solver_model)

       def run(self, solver_run: SolverRun) -> SolverRun:
           # write the input files unless solver_run.written, then solve
           output_dir = ...
           return replace(
               solver_run, output_dir=output_dir, written=True, solved=True
           )

       def extract(self, solver_run: SolverRun, store, retention: Retention) -> None:
           # write the fields and tables of writes, through the registered extractor
           ...

       def cleanup(self, solver_run: SolverRun) -> None:
           # remove scratch files; leave persisted outputs alone
           ...

       def observables(self, solver_run: SolverRun, requests, *, time_index=None):
           # cheap extraction inside the calibration loop: the whole batch
           # arrives at once, so each binary file is opened once. Refuse what
           # the backend cannot produce with ObservableNotAvailableError.
           ...

       def declared_observables(self, active):
           # what a run can serve, given the ids of the active conditions
           ...

Registration
------------

Two paths, depending on whether the backend ships inside the
HydroModPy repository or as an external plugin. Both end in the same
registry, ``solvers`` of ``hydromodpy/solver/base/registry.py``, an instance of
the engine every plugin surface shares. Its contract is ``register``, ``get``
and ``names``.

**In-tree backend.** Add one line to each of the two built-in path tables in
``hydromodpy/solver/base/registry.py``. Both tables use the same
``<process_type>_<name>`` key. The extractor table is not keyed on the solver
name alone, because one backend can carry a different extractor per process
(flow vs transport for MODFLOW 6):

.. code-block:: python

   _BUILTIN_PATHS["flow_mysolver"] = (
       "hydromodpy.solver.mysolver.adapter:MysolverFlowAdapter"
   )
   _BUILTIN_EXTRACTOR_PATHS["flow_mysolver"] = (
       "hydromodpy.solver.mysolver.extractors.flow:MysolverOutputAdapter"
   )

``extract`` is a required member, so a class without it is refused when it is
registered. The scenario ``tests/scenarios/test_backends_write_what_they_declare.py``
plays a small project under each in-tree backend and checks that every field and
table in the store is a name its ``writes`` declares.

**External plugin.** Declare the entry points in your distribution's
``pyproject.toml``. Ship both groups, for the same reason:

.. code-block:: toml

   [project.entry-points."hydromodpy.solver"]
   flow_mysolver = "mypkg.adapters:MysolverFlowAdapter"

   [project.entry-points."hydromodpy.solver.extractor"]
   flow_mysolver = "mypkg.extractors:MysolverOutputAdapter"

The registry never splits an entry-point name. It joins the ``process_type``
and ``name`` of the loaded class with ``_`` and compares that with the entry
point name, so ``flow_mysolver`` must equal ``flow`` and ``mysolver`` joined,
and a name that holds an underscore, such as ``modflow_nwt``, stays whole.
Never declare an in-tree backend through an entry point as well.

Nothing is loaded at import time. ``solvers.get("flow", "mysolver")`` serves
explicit registrations first, then lazy-imports the ``_BUILTIN_PATHS`` entry,
and only loads the entry-point group once if the key is still unknown. An
unknown key raises ``SolverInputError`` that lists the known ones.
``solvers.names("flow")`` lists the flow solvers by name, and
``solvers.create("flow", "mysolver")`` gives the instance the runner calls.

What the TOML says
------------------

A file chooses the backend with ``solver.backend = "mysolver"``. The value is
a plain string, checked against ``solvers.names("flow")`` while the file is
read, and a name this installation does not serve is refused with the names it
serves. The same holds for the names of ``[[simulation.process]]``
``solvers``. A plugin needs no patch in ``HydroModPy``: its entry point joins the
list.

The settings of the backend are the table ``[solver.mysolver]``. ``SolverConfig``
validates it with the class the adapter gives as ``options``, so a key the class
does not know is refused at its own path, and a backend whose ``options`` is
``None`` refuses the table. A table of a backend that does not run is read and
checked too, because a recipe of ``[sites]`` can change the backend of a shared
base file. The runner reads the table with ``cfg.solver.options_of(name)`` and
hands it to ``build`` as ``options``.

.. _add-a-solver-refusal:

``config/cross_checks.py`` crosses the file with ``supports``. It lists the
traits the file uses, and each one the chosen backend leaves out raises
``IncompatibleCapabilitiesError``. The message gives the key the file wrote,
the backend chosen and the backends of the installation that honour the trait::

   solver.backend = 'mysolver' does not honor solver.sink_fill: it would be ignored
   without a word. Remove it, or run a flow solver that honors it (modflow6, modflow_nwt).

A transport solver is checked against its ``requires`` in the same way. The
check never names a backend, so a new backend needs no line in ``config/``.
A sealed run, read back from disk, only warns.

Mesh engines
------------

A flow adapter names the mesh engines whose cells it can read in the
``accepted_meshes`` attribute. A configuration that pairs the solver with
another engine is refused before any meshing. The registry reads the class
attribute, so there is no second table to keep equal.

Config block
------------

If the backend needs settings, add a Pydantic model for its table
``[solver.mysolver]``:

.. code-block:: python

   # hydromodpy/solver/mysolver/mysolver_config.py
   from pydantic import BaseModel, ConfigDict, Field

   from hydromodpy.core.config_kit.profile import Profile
   from typing import Annotated


   class MysolverConfig(BaseModel):
       model_config = ConfigDict(extra="forbid")

       max_iter: Annotated[int, Profile.USER] = Field(
           default=200, description="Newton-iteration ceiling."
       )

Then set it as the ``options`` attribute of the adapter. The model is not wired
into ``HydroModPyConfig``: ``SolverConfig`` finds it through the registry. The
generic readers of the configuration (the schema, the template, the parameter
pages and ``--set solver.mysolver.max_iter=100``) read the tables of the
shipped backends through ``SolverConfig.named_tables``. A field that every
backend reads belongs to ``[solver]``, as ``sink_fill`` does (see
:doc:`add-a-config-field`).

The ``description`` of each field is also the sentence that a check gives for
the key. ``check(document)`` resolves ``[solver.mysolver]`` through the registry,
so a plugin writes no phrase in ``schema/phrases.toml``. A wrong value at
``solver.mysolver.max_iter`` is reported at that path, with the description of
the field as its ``help``, and a key the class does not know is reported at its
own path. Write the description for a person who reads it next to the error.

Tests to add
------------

Three tiers, smallest first:

- **Unit** under ``tests/unit/solver/mysolver/`` for ``validate``,
  ``build``, ``run`` and ``cleanup`` against a small in-memory ``Model`` and a
  ``RunSlot`` in a temporary folder. The contract test
  ``tests/contract/test_solver_backend_contract.py`` runs over ``solvers.names()``,
  so a registered backend is checked for its members, and for ``rerun`` if and only
  if its ``mutable`` is not empty. A backend that carries ``rerun`` adds a test
  that compares a rerun with a new build of the same ``Model``, file by file.
  The same file checks, for each backend that has ``options``, that ``check``
  points at a key of its table by its exact path and gives the description of that
  field as the ``help``.
- **Integration** under ``tests/integration/solver/`` for one
  end-to-end ``hmp run`` on a tiny case.
- **Validation** under ``tests/validation/`` (analytical or numerical)
  with a ``tolerances.toml`` companion if a scientific reference
  exists.

If the backend wraps a binary, mark the validation test
``@pytest.mark.solver_sanity`` so it can be selected separately.

See :doc:`add-a-test` for the full ladder.

Pitfalls flagged by the layer matrix
------------------------------------

- ``solver`` may import ``model``, ``catchment`` and ``results``, but
  **not** ``data``, ``calibration``, ``display``, ``project``, or
  ``workflow``. If your adapter needs loaded data, take it from the
  ``Model`` rather than importing ``data``.
- Do **not** cross-import another backend (``solver/modflow6/`` cannot
  import ``solver/modflow_nwt/`` and vice versa). Shared helpers go
  in ``solver/modflow_common/`` or ``solver/modflow_grid/``.
- Underscored modules of another package (``data/_*``,
  ``model/_*``) are off-limits.

See also
--------

- :doc:`../packages/solver` for the solver package map.
- :doc:`add-a-process` if you also need a new ``ProcessSpatial`` for
  the runtime payload your adapter consumes.
- :doc:`add-a-calibration-method` if your backend changes how the
  ask/tell loop should observe outputs.
- :doc:`../layered-architecture` for the layer matrix that constrains
  the imports above.
