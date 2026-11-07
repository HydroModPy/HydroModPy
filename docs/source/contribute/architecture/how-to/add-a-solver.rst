Add a solver
============

A solver in HydroModPy is one ``(process_type, solver_name)`` pair
bound to a concrete backend. Today three backends ship: ``modflow6``,
``modflow_nwt``, and ``boussinesq``. This page documents how to add a
fourth flow backend or, equivalently, a new ``transport`` /
``postprocess`` solver.

The ``hydromodpy.solver`` and ``hydromodpy.solver.extractor`` ports are
experimental (:doc:`../contracts`), so they can change in any minor version.
They also have two limits today. The boundary conditions name the backends
they support in a closed list, so a backend outside the tree that writes a
boundary condition is refused when the file loads
(``model/boundaries/boundary_condition_registry.py``). The run index knows a closed
list of solver codes too, so the index leaves out a run of such a backend, and
says so (``results/catalog/index_schema.py``).

Contract
--------

A solver implements the ``SolverAdapter`` Protocol declared in
``hydromodpy/solver/base/adapter_protocol.py``:

.. code-block:: python

   class SolverAdapter(Protocol):
       process_type: ClassVar[str]   # "flow", "transport", "postprocess"
       solver_name: ClassVar[str]    # "modflow6", "modflow_nwt", "boussinesq", ...
       requires: ClassVar[tuple[tuple[str, str], ...]] = ()  # upstream (process, solver) pairs

       def validate(self, ctx: RunContext) -> None: ...
       def execute(self, ctx: RunContext) -> RunExecutionResult: ...
       def cleanup(self, ctx: RunContext) -> None: ...
       def extract_observables(
           self,
           ctx: RunContext,
           store,
           requests: "Sequence[ObservableRequest]",
           *,
           time_index=None,
       ) -> "dict[str, ObservableResult]": ...

``RunContext`` and ``RunExecutionResult`` are declared in
``hydromodpy/solver/base/plan.py``. ``RunExecutionResult`` is a frozen
dataclass with three fields:

- ``primary_model``: the model the run produced, or ``None`` for a run that
  produces none. The runner keeps it for a run that depends on this one.
- ``solver_output_dir``: the directory that holds the raw output files, or
  ``None`` for an in-memory solver.
- ``metrics``: what the run has to say about itself. The catalog keeps what
  converts to a finite float and skips the rest. Optional.

``ctx.state`` is a ``RunState``: the reduced view of the workflow runtime
an adapter is allowed to read, and not the pipeline state itself. It
carries three members and no more: ``setup`` (workspace, domain, flow,
mesh ...), ``cfg`` and ``sim_id``. Reading anything else
raises ``AttributeError``, and a static gate in
``tests/unit/architecture/`` says so before the solver ever runs. What the run
itself produced arrives beside it, as ``ctx.model`` and ``ctx.output_dir``. The
catalog handle of the enclosing run is not in there either: it arrives as
``ctx.store``, borrowed for the span of the call, and an adapter keeps no
reference to it past ``execute``.

A separate **output adapter** (the *extractor*) ingests the persisted
outputs into the catalog. It is registered on the same
``(process_type, solver_name)`` pair as the adapter and implements the
``OutputAdapter`` Protocol of
``hydromodpy/workflow/steps/run_outputs.py``:

.. code-block:: python

   class OutputAdapter(Protocol):
       def extract(self, sim_id: str, solver_output_dir: Path, store: Any) -> None: ...

Files to create
---------------

For a new flow backend called ``mysolver``:

.. code-block:: text

   hydromodpy/solver/mysolver/
   |-- __init__.py
   |-- mysolver.py                   # core Solver class
   |-- mysolver_config.py            # Pydantic config block
   |-- adapters/
   |   |-- __init__.py
   |   `-- flow.py                   # MysolverFlowAdapter (SolverAdapter)
   |-- extractors/
   |   |-- __init__.py
   |   `-- flow.py                   # MysolverOutputAdapter (extract())
   `-- README.md                     # short rationale and code map

If your backend shares MODFLOW-family lifecycle helpers, reuse
``solver/modflow_common/flow_adapter_helpers.py`` instead of
duplicating preprocess/postprocess flow.

Minimal adapter skeleton
------------------------

.. code-block:: python

   # hydromodpy/solver/mysolver/adapters/flow.py
   from typing import ClassVar

   from hydromodpy.solver.base.plan import RunExecutionResult


   class MysolverFlowAdapter:
       process_type: ClassVar[str] = "flow"
       solver_name: ClassVar[str] = "mysolver"
       requires: ClassVar[tuple[tuple[str, str], ...]] = ()

       def validate(self, ctx) -> None:
           # cheap pre-flight checks on ctx.run, ctx.state.setup
           ...

       def execute(self, ctx) -> RunExecutionResult:
           # build and run, under ctx.state.setup.workspace.solver_scratch_folder
           model, output_dir = ...
           return RunExecutionResult(primary_model=model, solver_output_dir=output_dir)

       def cleanup(self, ctx) -> None:
           # remove scratch files; leave persisted outputs alone
           ...

       def extract_observables(self, ctx, store, requests, *, time_index=None):
           # cheap extraction inside the calibration loop: the whole batch
           # arrives at once, so each binary file is opened once. Refuse what
           # the backend cannot produce with ObservableNotAvailableError.
           ...

Registration
------------

Two paths, depending on whether the backend ships inside the
HydroModPy repository or as an external plugin.

**In-tree backend.** Register through the two built-in path tables in
``hydromodpy/solver/base/registry.py``. Both tables are keyed on the
**same** ``(process_type, solver_name)`` tuple. The extractor table is
not keyed on the solver name alone, because one backend can carry a
different extractor per process (flow vs transport for MODFLOW 6):

.. code-block:: python

   _BUILTIN_PATHS[("flow", "mysolver")] = (
       "hydromodpy.solver.mysolver.adapters.flow:MysolverFlowAdapter"
   )
   _BUILTIN_EXTRACTOR_PATHS[("flow", "mysolver")] = (
       "hydromodpy.solver.mysolver.extractors.flow:MysolverOutputAdapter"
   )

A string key such as ``_BUILTIN_EXTRACTOR_PATHS["mysolver"]`` registers
nothing that ``get_extractor("flow", "mysolver")`` can find:
``get_extractor_instance`` then returns ``None`` and ``post_run_results``
treats it as a configuration error. The backend solves and the run is
lost on the way to the catalog.

**External plugin.** Declare the entry points in your distribution's
``pyproject.toml``. Ship both groups, for the same reason:

.. code-block:: toml

   [project.entry-points."hydromodpy.solver"]
   flow_mysolver = "mypkg.adapters:MysolverFlowAdapter"

   [project.entry-points."hydromodpy.solver.extractor"]
   flow_mysolver = "mypkg.extractors:MysolverOutputAdapter"

Entry-point names are split at the **first** underscore, so
``flow_mysolver`` yields ``("flow", "mysolver")``. Never declare an
in-tree backend through an entry point as well: ``flow_modflownwt``
would mint a second pair ``flow/modflownwt`` next to the real
``flow/modflow_nwt``, which the config accepts but which has an adapter
and no extractor.

Nothing is loaded at import time. ``registry.get(process_type,
solver_name)`` serves explicit registrations first, then lazy-imports
the ``_BUILTIN_PATHS`` entry, and only calls ``load_plugins()`` once if
the pair is still unknown. An unknown pair raises an error that lists the
known ones. The runner instantiates the adapter through
``registry.get_solver_adapter(process_type, solver_name)``.

Mesh engines
------------

A flow adapter names the mesh engines whose cells it can read, in the class
attribute ``accepted_meshes`` (``MeshReadingAdapter`` in
``adapter_protocol.py``). An adapter that declares none reads the ``regular``
engine only. A configuration that pairs the solver with another engine is
refused before any meshing. A built-in also lists its engines in
``_BUILTIN_ACCEPTED_MESHES``, so the registry answers without importing the
adapter, and a test keeps the two equal.

.. code-block:: python

   class MysolverFlowAdapter:
       accepted_meshes: ClassVar[frozenset[str]] = frozenset({"regular", "triangle"})

Capabilities (optional but recommended)
---------------------------------------

Declare the capabilities your backend exposes so the planner can
report them and tests can opt in.

.. code-block:: python

   _BUILTIN_CAPABILITIES[("flow", "mysolver")] = frozenset({
       "flow",
       "flow:heads",
       "flow:budget",
   })

Config block
------------

If the backend needs its own ``[mysolver]`` TOML section, add a
Pydantic model:

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

Then wire it into ``HydroModPyConfig`` (see
:doc:`add-a-config-field`).

Tests to add
------------

Three tiers, smallest first:

- **Unit** under ``tests/unit/solver/mysolver/`` for ``validate``,
  ``execute``, and ``cleanup`` against a small in-memory ``ctx``.
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

- ``solver`` may import ``model``, ``spatial`` and ``results``, but
  **not** ``data``, ``calibration``, ``display``, ``project``, or
  ``workflow``. If your adapter needs loaded data, take it from the
  ``ctx`` rather than importing ``data``.
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
