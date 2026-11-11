MODFLOW and Boussinesq backends
===============================

How the three flow backends are put together, what they share, and the contracts the
MODFLOW family honors. The code is in ``hydromodpy/solver/``, and the page of that
package (:doc:`../packages/solver`) lists its modules. Each backend folder has a README,
which is its contract on the solver port. The mathematics of each solver is in
:doc:`/theory/solvers`. The in-house Boussinesq backend has its own diagrams in
:doc:`boussinesq-uml-diagrams`.

The backends
------------

.. list-table::
   :header-rows: 1
   :widths: 16 22 30 32

   * - Backend
     - Run pair
     - Adapter and model
     - Mesh
   * - MODFLOW 6
     - ``("flow", "modflow6")``
     - ``solver/modflow6/adapter.py`` bridges a ``ProcessRun`` to
       ``Modflow6`` (``solver/modflow6/modflow6.py``). ``build.py`` wires the
       packages, ``builders/`` holds one module per package and ``rerun.py``
       solves a solved model again for a new K or Sy.
     - The cell mesh of any engine (``[mesh] engine``). The model is always written as
       DISV, through ``to_disv_kwargs`` of ``SolverMesh``.
   * - MODFLOW-NWT
     - ``("flow", "modflow_nwt")``
     - ``solver/modflow_nwt/adapter.py`` bridges to ``ModflowNwt``
       (``solver/modflow_nwt/nwt/nwt_solver.py``). ``flow_to_modflow_adapter.py``
       turns the runtime state into package inputs.
     - The ``regular`` engine only, written as a DIS grid. A file whose ``[mesh] engine``
       is another engine is refused when it is read.
   * - Boussinesq
     - ``("flow", "boussinesq")``
     - ``solver/boussinesq/adapter.py`` bridges to ``Boussinesq``
       (``solver/boussinesq/boussinesq.py``). Its settings are the
       ``BoussinesqOptions`` of ``solver/boussinesq/options.py``.
     - Triangular cell meshes: the cell mesh of the run, or a mesh bundle read as one.

MODFLOW 6 and MODFLOW-NWT also serve transport: MODPATH, MT3DMS, GWT and PRT
adapters sit in the ``adapters/`` folder of their backend, beside the flow adapter
``adapter.py``. MODFLOW-NWT builds no LAK and no SFR package, so it serves no lake
stage and no routed reach discharge, and its adapter says so in
``declared_observables``. Use MODFLOW 6 for a lake.

What the MODFLOW family shares
------------------------------

Every flow backend reads one frozen ``Model`` (``hydromodpy/model/model.py``), built
once by ``prepare_solver`` in SI units and handed to the adapter by the runner, with
the validated options of ``[solver.<name>]`` and a ``RunSlot``. A backend does not read
the ``Flow``, the configuration or the geographic object, it does not change the
``Model``, and it never opens the Zarr store of a prior run. The contract is
``hydromodpy/solver/base/README.md``, the README of the solver port, and
``tests/unit/architecture/test_run_path.py`` holds it. The auxiliary solves of the starting head are variants of the ``Model``
(``steady_variant``, ``cycle_variant``). Each runs in a slot of its own, which has the
folder and the binaries of the run, and each backend builds them from the top.

The adapter of a flow backend has the same members in the three backends. ``build`` makes
the solver model in memory under ``slot.directory`` and writes nothing. ``run`` writes the
input files, lists them in ``SolverRun.input_files`` and solves. ``extract`` writes the
fields and tables that ``writes`` declares into the run store, and ``cleanup`` removes
the scratch files. MODFLOW 6 is the one backend with ``rerun``, so it is the one whose
``mutable`` is not empty, ``{"K", "Sy"}``. Given a solved run and a ``Model`` that differs
by K, by Sy or by both, it copies the input files of that run and writes again only NPF
and DRN (K), STO (Sy) and the properties file. The result is bit-identical to a new build.
A start from a steady or a cyclic solve, a change that turns XT3D on or off, and a change
of the drain cells still build.

Backend adapters stay thin. The shared lifecycle is in
``solver/modflow_common/flow_run.py``: ``build_flow_model`` and
``run_flow_model`` are the two halves of the build and the solve, and
``resolve_solver_run_output`` finds the folder a solver wrote in. The rest of
``solver/modflow_common/`` centralizes temporal discretization units, routing helpers,
runtime arrays, binaries and raster export for both backends, and
``solver/modflow_grid/`` describes the grid they read. The two backends do not import
each other. No gate checks that independence: the import scanner of
``tools/audit/build_graph.py`` shows that it holds today.

The shortest reading path for one flow run is the one of
:doc:`../simulation/toml-to-solver-walkthrough`, then the adapter of the backend, then
``flow_run.py``, then the model class of the table above. Configuration is
validated by ``modflow6_config.py`` (``[solver.modflow6.*]``) and ``nwt/nwt_config.py``
(``[solver.modflow_nwt.*]``). MODFLOW 6 reads the output back through
``solver/modflow6/extractors/``, and resolves HydroModPy properties into
MF6 arrays in ``solver/modflow6/support/property_mapping.py``.

MODFLOW contracts
-----------------

What HydroModPy honors before it builds the MODFLOW packages. The discretization and
the routing descent are shared by both backends; the BAS arrays belong to MODFLOW-NWT.

Discretization contract
~~~~~~~~~~~~~~~~~~~~~~~

Source: ``hydromodpy/solver/modflow_grid/discretization_temporal.py`` and
``hydromodpy/solver/modflow_grid/discretization_spatial.py``, shared by
both MODFLOW backends.

Two typed dataclasses carry the contract:

- ``TemporalDiscretizationResult``
  (``discretization_temporal.py``)
- ``SolverGridContext`` (``discretization_spatial.py``), built by
  ``build_spatial_discretization``

Temporal contract
^^^^^^^^^^^^^^^^^

Fields of ``TemporalDiscretizationResult``:

.. list-table::
   :header-rows: 1

   * - Field
     - Type
     - Role
   * - ``itmuni``
     - ``int``
     - MODFLOW time-unit code passed to DIS
   * - ``time_units``
     - ``str``
     - Same unit as canonical text, read by the MODFLOW 6 TDIS builder
   * - ``nper``
     - ``int``
     - Number of stress periods, strictly positive
   * - ``perlen``
     - 1D float ``np.ndarray``
     - Duration of each period in ``itmuni`` units
   * - ``nstp``
     - 1D int ``np.ndarray``
     - Number of time steps per period
   * - ``steady``
     - 1D bool ``np.ndarray``
     - Steady-vs-transient flag per period
   * - ``start_datetime``
     - ``object`` or ``None``
     - Optional start-date metadata

Required invariants:

- ``nper == perlen.size``
- ``nstp.size == nper``
- ``steady.size == nper``
- ``nper > 0``
- ``itmuni`` and ``time_units`` denote the same unit

Launcher runs are built in ``hydromodpy.core.time.window.SIMULATION_TIME_UNIT``, that
is SI seconds: ``ResolvedSimulationTimeGrid`` carries period lengths in
seconds, so declaring anything else would rescale every extracted flux. Both
backends take the declaration from this single field rather than restating it,
and the extractors read it back from the run's own TDIS or DIS file through
``hydromodpy.solver.modflow_common.time_units``.

Conversion to FloPy kwargs goes through
``TemporalDiscretizationResult.as_dis_kwargs()``, which exposes the keys
``itmuni``, ``nper``, ``perlen``, ``nstp``, ``steady``, ``start_datetime``.

Spatial contract
^^^^^^^^^^^^^^^^

Fields of ``SolverGridContext``:

.. list-table::
   :header-rows: 1

   * - Field
     - Type
     - Role
   * - ``grid``
     - ``GridReference``
     - Cell count, bounds, CRS, nodata, optional structured shape
   * - ``solver_mesh``
     - ``SolverMesh``
     - Prismatic mesh: ``cell_mesh`` (the ``PlanarCellMesh``), ``top``,
       ``botm``, ``idomain`` (``inactive_mask`` is derived from it)
   * - ``top_surface``
     - ``Surface``
     - Validated topographic support
   * - ``bottom_surface``
     - ``Surface``
     - Validated substratum support
   * - ``template_raster_path``
     - ``str | None``
     - Raster template used for structured exports

Derived properties: ``top_elevation`` (flat ``(n_cells,)``),
``bottom_layer`` (``botm[-1]``, flat), ``nlay``, ``n_cells``.

Required invariants:

- ``solver_mesh.botm`` and ``solver_mesh.idomain`` have shape ``(nlay, n_cells)``; ``top`` is
  a flat ``(n_cells,)`` array. ``idomain`` is an integer array: 1 is an active cell, 0 an
  inactive one and -1 a vertical pass-through cell, and every test of activity reads it as
  above 0. ``inactive_mask`` is the derived property ``idomain <= 0``.
- ``SolverMesh.top_active_layer()`` gives the top active layer of each column (-1 for a
  column with none) and is the one function the drains, the supports of the constant heads,
  the surface of the evapotranspiration, the computational top, the filling of the
  closed depressions, the lake footprint, the saturated thickness of the calibration and the
  location of a point read. ``closed_surface(covered_cells)`` marks the columns that no
  surface process reaches, and ``check_interfaces()`` refuses an active cell whose top is at
  or below its bottom (a pass-through cell may have no thickness). The function itself,
  ``top_active_layer`` in ``hydromodpy/core/fields/vertical_column.py``, lives in ``core`` because
  the solvers, the calibration, the results and the display all read it.
- The grid is mesh-native: ``structured_shape`` is set only when the
  planar mesh is a Cartesian grid, and is ``None`` for DISV meshes.
- The domain provides ``surface_topo`` and ``substratum`` of type
  ``Surface``.

Upstream inputs
^^^^^^^^^^^^^^^

The temporal builder consumes:

- ``time_grid``, the ``ResolvedSimulationTimeGrid`` derived from
  ``[simulation.time]``
- ``flow_regime``
- ``first_period_steady``

The spatial builder consumes:

- the ``domain`` with ``surface_topo`` and ``substratum``
- the active DEM shape
- ``vertical_config``, the ``[domain.layers]`` table that both MODFLOW backends read
  (``domain.config.layers``)

Why this contract
^^^^^^^^^^^^^^^^^

- Make the DIS payload explicit and testable.
- Prevent any shape or unit drift between runtime objects and the
  solver configuration.
- Keep the DIS conventions out of the orchestration code.

BAS contract: ``ibound`` and ``strt``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These two arrays are the most sensitive at MODFLOW startup. An
inconsistency can silently destabilize the simulation.

MODFLOW semantics honored
^^^^^^^^^^^^^^^^^^^^^^^^^^

HydroModPy follows the standard sign-based BAS contract:

- ``ibound > 0``: active cell, head is computed.
- ``ibound = 0``: inactive cell, no-flow.
- ``ibound < 0``: imposed-head cell (constant head).

``strt`` is a 3D array ``(nlay, nrow, ncol)``. For ``ibound < 0``
cells, ``strt`` provides the imposed head used by BAS.

Where the arrays are built
^^^^^^^^^^^^^^^^^^^^^^^^^^

Main source:

- ``hydromodpy/solver/modflow_nwt/nwt/flow_to_modflow_adapter.py``

  - ``FlowToModflowAdapter._build_initial_heads_and_sides``
  - ``FlowToModflowAdapter._build_ocean_chd``
  - ``FlowToModflowAdapter._validate_ibound_strt_contract``

Assembly point:

- ``hydromodpy/solver/modflow_nwt/nwt/_pre_processing.py`` calls
  ``flopy.modflow.ModflowBas(..., ibound=..., strt=...)``.

Application order
^^^^^^^^^^^^^^^^^

The ``strt`` initialization policy comes from the initial state of the ``Model``
(``inputs.initial``, built from ``[flow.ic]`` by ``initial_state_of``). A ``HeadRule``
gives it by ``kind``:

1. ``top``: initialize from the DEM.
2. ``top_offset``: initialize from the DEM, lowered by the ``value``.
3. ``bottom``: initialize from the bottom-layer elevation.
4. ``custom``: initialize from a user scalar value.

A ``SteadyStart`` or a ``CyclicStart`` starts the main model from the top, and the
auxiliary solve sets the head after that. A ``PriorState`` or a ``SolvedState`` gives
the head itself.

Then lateral Dirichlet conditions (``west``, ``east``, ``north``,
``south``) are applied:

1. face cells flipped to ``ibound = -1``,
2. matching ``strt`` values overwritten by the boundary head.

Then the no-data mask:

1. DEM cells below the sentinel threshold flip to ``ibound = 0``.

Then the optional ocean condition:

1. a scalar ocean level can flip submerged cells to ``ibound < 0`` and
   overwrite ``strt``;
2. a transient ocean forcing produces a CHD payload per stress period
   and can locally disable drainage.

Validations applied
^^^^^^^^^^^^^^^^^^^

Before assembly continues, the adapter checks:

1. ``ibound.shape == (nlay, nrow, ncol)``
2. ``strt.shape == (nlay, nrow, ncol)``
3. ``drain_array.shape == (nrow, ncol)``
4. all values are finite
5. ``drain_array`` is binary (``0`` or ``1``)

The validation enforces sign-based semantics, not just
``{-1, 0, 1}``.

Practical debugging
^^^^^^^^^^^^^^^^^^^

1. Check the assignment order (initial conditions, then lateral
   boundaries, then ocean).
2. Inspect ``ibound`` sign masks (``>0``, ``=0``, ``<0``) before
   launching the solver.
3. Plot ``strt`` slices on imposed-head faces and ocean-influenced
   areas.
4. Any non-finite value in ``ibound`` or ``strt`` is a hard error.

Routing descent contract
~~~~~~~~~~~~~~~~~~~~~~~~

Source: ``hydromodpy/catchment/drainage/descent.py`` (the computation) and
``hydromodpy/solver/modflow_common/flow_directions.py`` (the adapter both
backends call; neither backend imports the other).
``hydromodpy/catchment/drainage/channel_tree.py`` reads the river network A.
``prepare_solver`` reads A on the mesh cells once, in ``Model.geometry.channel_exits``
(``channel_exits``). ``channel_exits_for_build`` says whether a build uses it, and the build
pins D on it with its active columns and its lakes (``pin_channel``).
``catchment_basin.py`` takes the basin of D at the outlet, and ``descent_store.py`` writes and
reads the sidecar.

Every MODFLOW 6 and MODFLOW-NWT run builds one descent D per model build and
keeps it on the model (``model.descent``), without the neighbor sets the
flood walked: after the build the consumers read the receivers, the surface,
the masks and the edge lengths only. An auxiliary model (steady
initialization, spin-up cycle) is never extracted: MODFLOW 6 builds D for it
only when an SFR network walks D, MODFLOW-NWT never, and neither leaves a
sidecar. D is a filled copy of the model top
on which every routable cell has a receiver, so water has a path to a base
level. It never returns to the solver: the channel bed, drain elevations and
reach tops keep reading the model top.

- **Seeds.** The domain rim and the constant-head cells, the same supports on
  both backends: ocean, side and river CHD, static or transient. On MODFLOW 6
  these are the ocean and river CHD support masks and the side CHD rows; on
  MODFLOW-NWT the cells with ``ibound == -1`` (static boundaries) and the CHD
  package rows (transient ones). MODFLOW-NWT writes no river CHD. Lakes
  (MODFLOW 6 only) are traversed, never seeds.
- **Constant heads pass the water on.** A constant-head cell keeps its steepest
  descent, as a rim cell does, so the per-cell discharge and the accumulated
  fluxes cross a river CHD and the outlet keeps the domain sum. The walks that
  follow water out of the model stop there (``Descent.stopping_receiver``): a
  drain chain reaching a CHD cell keeps a plain DRN, and a reach reaching one
  is the outlet reach.
- **Pins.** Where the river network was generated for the run
  (``geographic.river_network_enabled``; its full-extent rasters are in
  ``geographic.correcflow_path``), channel
  cells drain to the next cell of the channel tree. This holds
  whether or not SFR is active. Without a channel tree D has no pin.
- **Neighborhood.** Fixed by the mesh type: D8 (shared nodes) on a quad mesh,
  shared faces elsewhere. It is not a per-output option.
- **Stored with the run.** The build leaves ``<model>.descent.npz`` in the
  solver folder; the extractor writes it under ``fields.zarr/mesh/`` right after
  the mesh (see :doc:`../storage-layout`) and ``run.descent`` reads it back. A
  run sealed before D was stored gets one rebuilt from its stored top, with no
  pin, no constant-head seed and no lake.

Consumers on D: the per-cell discharge and upstream area of the calibration
observables (``catchment/drainage/routing.py``, on the graph that ``routing_graph_for_model`` of
``modflow_common/observable_extraction.py`` reads), the accumulation of
cell fluxes (``drain_accumulation_flux``, ``release_accumulation_flux``), and the
flow direction map, which also marks the cells D raised on its copy.

Declared apart, each on its own surface:

- ``modflow_common/routing_context.py`` keeps its own raster D8 pointer on the
  solver-grid DEM, conditioned by ``dem_correc_type``. Mass transfer and MT3DMS
  accumulation trace point sources down the Whitebox pointer and stay on it
  until they are migrated. The solver fills its own grid template in every run:
  a DEM declared ``state = "conditioned"`` keeps ``provided`` for the regional
  chain, and the solver grid is filled with ``fill``, because bringing a
  conditioned DEM onto a coarser grid recreates depressions.
- ``modflow_common/sink_mask.py`` answers a different question, which cells
  have no outlet in the solver's own four-face connectivity, and stays on it.
- The network criterion reads the model top T and fills its own copy on its own
  graph (see :doc:`/theory/downslope-distance`).

See also
--------

- :doc:`boussinesq-uml-diagrams` for the structure of the Boussinesq backend.
- :doc:`../mesh/mesh-pivot` for the cell mesh that feeds the discretization contract.
- :doc:`../mesh/mesh-engines` for the mesh engines.
- :doc:`../contracts` for the adapter pattern that wraps these contracts.
