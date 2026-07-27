solver
======

``hydromodpy.solver`` exposes the backend abstraction (``base/``)
plus three concrete backends: MODFLOW 6, MODFLOW-NWT, and Boussinesq.
It also hosts shared helpers (``modflow_common``, ``modflow_grid``)
that stay backend-agnostic. Time-grid primitives now live in
``hydromodpy.discretization.time``.

GR4J is not a fourth ``hydromodpy.solver`` backend in V1. It is a
calibration-side lumped catchment model under
``hydromodpy.calibration.lumped``; it runs in memory and only promoted
trials are written through the result catalog.

Sub-modules
-----------

- ``solver/base/`` -- registry, ``SolverAdapter`` Protocol,
  ``Solver`` lifecycle. Lazy-loads built-in adapters and extractors
  through ``_BUILTIN_PATHS`` and ``_BUILTIN_EXTRACTOR_PATHS``.
- ``solver/boussinesq/`` -- in-house 2D unconfined flow solver.
  Triangular runtime meshes; chained resolution
  ``flow.flow_regime`` -> ``flow.runtime_backend`` ->
  ``flow.surface_interaction_model`` -> methods / engines /
  runtime selection.
- ``solver/modflow6/`` -- FloPy-backed MODFLOW 6 wrapper. Flow
  through ``adapters/flow.py``, transport through
  ``adapters/transport.py``, output extraction through
  ``extractors/``. Advanced packages are built by dedicated builder
  modules: ``builders/lake.py`` (LAK) and ``builders/sfr.py`` (SFR)
  are mutually independent and couple only through the
  package-agnostic ``builders/mvr.py`` water-mover records that
  ``build.py`` instantiates last. The SFR builder consumes the reach
  trace delineated in ``spatial`` (a legal ``solver -> spatial``
  edge) and never imports the lake builder.
- ``solver/modflow_nwt/`` -- legacy MODFLOW-NWT wrapper plus
  Modpath / MT3DMS transport adapters.
- ``calibration/lumped/`` -- GR4J adapter and extractor. This lives
  outside ``solver/`` because it does not use the staged flow-runner
  lifecycle or solver binaries.
- ``solver/modflow_common/`` -- shared MODFLOW-family helpers
  (executables, boundary packages, flux translators, runtime arrays,
  calibration extractors).
- ``solver/modflow_grid/`` -- backend-agnostic grid primitives:
  ``SolverMesh``, ``SolverGridContext``, ``build_spatial_discretization``,
  ``build_temporal_discretization``.
- ``discretization/time/`` -- ``TimeGrid``,
  ``TmeshGenerator``, ``TMeshConfig`` for stress-period generation.

Adapter contract
----------------

Every solver implements ``SolverAdapter`` from
``solver/base/protocol.py``:

.. code-block:: python

   class SolverAdapter(Protocol):
       process_type: ClassVar[str]
       solver_name: ClassVar[str]
       requires: ClassVar[tuple[tuple[str, str], ...]] = ()

       def validate(self, ctx) -> None: ...
       def execute(self, ctx) -> RunExecutionResult: ...
       def cleanup(self, ctx) -> None: ...
       def extract_calibration_series(self, ctx, store, *, variable, ...) -> "pd.Series": ...

Output adapters implement the dual contract:

.. code-block:: python

   class SolverOutputAdapter:
       solver_name: ClassVar[str]
       def extract(self, sim_id, solver_output_dir, store) -> None: ...

Registry resolution
-------------------

``ctx.run.process.process_type`` plus
``ctx.run.process.solver_name`` resolves through the registry:

.. code-block:: text

   ("flow", "modflow6")
       -> _BUILTIN_PATHS lookup or plugin entry point
       -> Modflow6FlowAdapter (instantiated by get_solver_adapter)
       -> adapter.execute(ctx)
       -> get_extractor("modflow6") -> Modflow6OutputAdapter
       -> extractor.extract(sim_id, output_dir, store)

Built-in capabilities are declared in ``_BUILTIN_CAPABILITIES`` and
queryable through ``capabilities(process_type, solver_name)``.

Key public symbols
------------------

- ``hydromodpy.solver.base.adapter_protocol.SolverAdapter``
- ``hydromodpy.solver.base.registry.{register, get, get_solver_adapter,
  register_extractor, get_extractor, list_pairs, capabilities,
  required_bindings, load_plugins}``
- ``hydromodpy.solver.modflow_grid.{SolverMesh, SolverGridContext,
  build_spatial_discretization, build_temporal_discretization}``
- ``hydromodpy.discretization.time.{TimeGrid, TmeshGenerator, TMeshConfig,
  load_tmesh_toml, validate_tmesh_config_data}``
- ``hydromodpy.solver.modflow_common.{flow_adapter_helpers,
  calibration_extractors, flow_translator, binaries,
  boundary_packages, executables, runtime_arrays}``

Recommended reading path
------------------------

1. ``hydromodpy/solver/base/adapter_protocol.py`` and ``registry.py``.
2. ``hydromodpy/solver/modflow6/adapters/flow.py`` for a concrete
   adapter.
3. ``hydromodpy/solver/modflow_common/flow_adapter_helpers.py`` for
   the shared MODFLOW-family lifecycle.
4. ``hydromodpy/solver/modflow6/extractors/flow.py`` for the
   matching output adapter.
5. ``hydromodpy/solver/boussinesq/README.md`` for the in-house
   solver.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``physics``, ``spatial``,
  ``discretization``, ``solver``, ``simulation``.
- Allowed sources: ``config``, ``calibration``, ``workflow``,
  ``project`` and ``cli``.
- Each backend folder is independent: ``solver/modflow6/`` cannot
  import ``solver/modflow_nwt/``. Shared helpers live in
  ``solver/modflow_common/`` and ``solver/modflow_grid/``.

See also
--------

- :doc:`/architecture/how-to/add-a-solver` -- step-by-step recipe.
- :doc:`/architecture/solver/modflow-contracts` -- DIS / BAS contract.
- :doc:`/architecture/solver/index` -- per-backend deep dives
  (MODFLOW 6, MODFLOW-NWT, Boussinesq).
- :doc:`/theory/solvers/index` -- scientific solver notes.
