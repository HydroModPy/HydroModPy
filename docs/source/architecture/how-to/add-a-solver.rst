Add a Solver
============

A solver in HydroModPy is one ``(process_type, solver_name)`` pair
bound to a concrete backend. Today three backends ship: ``modflow6``,
``modflow_nwt``, and ``boussinesq``. This page documents how to add a
fourth flow backend or, equivalently, a new ``transport`` /
``postprocess`` solver.

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
       def extract_calibration_series(
           self,
           ctx: RunContext,
           store,
           *,
           variable: str,
           station_cells,
           time_index,
       ) -> "pandas.Series": ...

``RunExecutionResult`` is a small dataclass exposing
``success: bool`` and ``outputs: dict | None``.

A separate **output adapter** (the *extractor*) ingests the persisted
outputs into the catalog. It is registered on the same
``(process_type, solver_name)`` pair as the adapter and implements:

.. code-block:: python

   class SolverOutputAdapter:
       def extract(self, sim_id: str, solver_output_dir: Path, store) -> None: ...
       def derive(self, sim_id: str, store, ...) -> None: ...

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

   from hydromodpy.solver.base.adapter_protocol import RunExecutionResult


   class MysolverFlowAdapter:
       process_type: ClassVar[str] = "flow"
       solver_name: ClassVar[str] = "mysolver"
       requires: ClassVar[tuple[tuple[str, str], ...]] = ()

       def validate(self, ctx) -> None:
           # cheap pre-flight checks on ctx.run, ctx.state.setup
           ...

       def execute(self, ctx) -> RunExecutionResult:
           # build, run, persist
           outputs = {...}
           return RunExecutionResult(success=True, outputs=outputs)

       def cleanup(self, ctx) -> None:
           # remove scratch files; leave persisted outputs alone
           ...

       def extract_calibration_series(
           self, ctx, store, *, variable, station_cells, time_index
       ):
           # cheap series extraction used inside the calibration loop
           ...

Registration
------------

Two paths, depending on whether the backend ships inside the
HydroModPy repository or as an external plugin.

**In-tree backend.** Register through the two built-in path tables in
``hydromodpy/solver/base/registry.py``. Both tables are keyed on the
**same ``(process_type, solver_name)`` tuple** — the extractor table is
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
the pair is still unknown. Launchers may also call
``SolverConfig.validate_registry()`` to force that scan up front and
fail early on an unknown backend name. The runner instantiates the
adapter through ``registry.get_solver_adapter(process_type,
solver_name)``.

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

- ``solver`` may import ``physics``, ``spatial``, ``simulation``, but
  **not** ``data``, ``calibration``, ``results``, ``display``,
  ``analysis``, or ``workflow``. If your adapter needs results, hand
  the data through the ``ctx`` rather than importing ``results``.
- Do **not** cross-import another backend (``solver/modflow6/`` cannot
  import ``solver/modflow_nwt/`` and vice versa). Shared helpers go
  in ``solver/modflow_common/`` or ``solver/modflow_grid/``.
- Underscored modules of another package (``data/_*``,
  ``simulation/_*``) are off-limits.

See also
--------

- :doc:`../packages/solver` for the solver package map.
- :doc:`add-a-process` if you also need a new ``ProcessSpatial`` for
  the runtime payload your adapter consumes.
- :doc:`add-a-calibration-method` if your backend changes how the
  ask/tell loop should observe outputs.
- :doc:`../layered-architecture` for the layer matrix that constrains
  the imports above.
