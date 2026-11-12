MODFLOW and Boussinesq backends
===============================

This note says what the three flow backends share, what a MODFLOW build must honor, and the
pitfalls of the shared code. The modules of the package are on :doc:`../packages/solver`,
and each backend folder has a README that is its contract on the solver port. The
mathematics is on :doc:`/theory/solvers`, and the list of solvers is generated on
:doc:`/reference/solvers`. The Boussinesq engines have their own note,
:doc:`boussinesq-engines`.

What the backends take
----------------------

MODFLOW 6 always writes a DISV model, through ``to_disv_kwargs`` of ``SolverMesh``, so it
reads the cell mesh of any engine (``[mesh] engine``). MODFLOW-NWT writes a DIS grid and
reads the ``regular`` engine only. A file that asks for another engine is refused when it is
read. Boussinesq reads triangular cell meshes, either the cell mesh of the run or a mesh
bundle read as one.

MODFLOW 6 and MODFLOW-NWT also serve transport. The GWT and PRT adapters
are ``transport.py`` and ``prt.py`` in ``solver/modflow6/``. The MODPATH and MT3DMS adapters are
the folders ``modpath/`` and ``mt3dms/`` of ``solver/modflow_nwt/``. MODFLOW-NWT
builds no LAK and no SFR package, so it serves no lake stage and no routed reach discharge,
and its adapter says so in ``declared_observables``. Use MODFLOW 6 for a lake.

What every flow backend receives
--------------------------------

A flow backend reads one frozen ``Model`` (``hydromodpy/model/model.py``). ``prepare_solver``
builds it once in SI units, and the runner hands it to the adapter with the validated options
of ``[solver.<name>]`` and a ``RunSlot``. The backend does not read the ``Flow``, the
configuration or the geographic object. It does not change the ``Model``, and it never opens
the Zarr store of a prior run. ``hydromodpy/solver/base/README.md`` is the contract, and
``tests/unit/architecture/test_run_path.py`` holds it.

The auxiliary solves of the starting head are variants of the ``Model`` (``steady_variant``,
``cycle_variant``). Each runs in a slot of its own, with the folder and the binaries of the
run, and each backend builds them from the top.

The three adapters have the same members. ``build`` makes the solver model in memory under
``slot.directory`` and writes nothing. ``run`` writes the input files, lists them in
``SolverRun.input_files`` and solves. ``extract`` writes into the run store the fields and
tables that ``writes`` declares, and ``cleanup`` removes the scratch files.

MODFLOW 6 is the one backend with ``rerun``, so it is the one whose ``mutable`` is not empty
(``{"K", "Sy"}``). Given a solved run and a ``Model`` that differs by K, by Sy or by both,
it copies the input files of that run and writes again only NPF and DRN (K), STO (Sy) and
the properties file. The result is bit-identical to a new build. A start from a steady or a
cyclic solve, a change that turns XT3D on or off, and a change of the drain cells still
build.

The shared lifecycle of the MODFLOW family is in ``solver/modflow_common/flow_run.py``.
``build_flow_model`` and ``run_flow_model`` are the two halves of the build and the solve,
and ``resolve_solver_run_output`` finds the folder a solver wrote in. The two backends do
not import each other. No gate checks that, and the import scanner of
``tools/audit/build_graph.py`` shows that it holds today.

To read one flow run, start with :doc:`toml-to-solver`, then the adapter of the backend, then
``flow_run.py``, then the model class. Configuration is checked by ``modflow6_config.py`` and
by ``nwt/nwt_config.py``. MODFLOW 6 reads its output through ``solver/modflow6/extractors/``
and resolves the properties into arrays in ``solver/modflow6/support/property_mapping.py``.

Temporal discretization
-----------------------

``hydromodpy/solver/modflow_grid/discretization_temporal.py`` turns the time grid of the
``Model`` into the data that both backends write in TDIS or DIS.

.. literalinclude:: /../../hydromodpy/solver/modflow_grid/discretization_temporal.py
   :pyobject: TemporalDiscretizationResult

The invariants are ``nper > 0``, and ``perlen``, ``nstp`` and ``steady`` all have ``nper``
entries. ``itmuni`` and ``time_units`` name the same unit.

Launcher runs are built in ``SIMULATION_TIME_UNIT`` of ``hydromodpy/core/time/window.py``,
which is SI seconds. ``ResolvedSimulationTimeGrid`` carries the period lengths in seconds,
so declaring another unit would rescale every extracted flux. Both backends take the unit
from this one field, and the extractors read it back from the TDIS or DIS file of the run
through ``hydromodpy/solver/modflow_common/time_units.py``.

Spatial discretization
----------------------

``build_spatial_discretization`` in ``discretization_spatial.py`` builds the view that both
backends read.

.. literalinclude:: /../../hydromodpy/solver/modflow_grid/discretization_spatial.py
   :pyobject: SolverGridContext

The mesh is native. ``structured_shape`` is set only when the planar mesh is a Cartesian
grid, and it is ``None`` for a DISV mesh. ``solver_mesh.botm`` and ``solver_mesh.idomain``
have shape ``(nlay, n_cells)``, and ``top`` is a flat ``(n_cells,)`` array.

``idomain`` is an integer array. A value of 1 is an active cell, 0 an inactive one and -1 a
vertical pass-through cell. Every test of activity reads it as above 0, and ``inactive_mask``
is the derived property ``idomain <= 0``.

``SolverMesh.top_active_layer()`` gives the top active layer of each column, and -1 for a
column with none. The drains, the supports of the constant heads, the surface of the
evapotranspiration, the computational top, the filling of the closed depressions, the lake
footprint, the saturated thickness of the calibration and the location of a point read all
use it. The function itself, ``top_active_layer`` in
``hydromodpy/core/fields/vertical_column.py``, lives in ``core`` because the solvers, the
calibration, the results and the display read it. ``closed_surface(covered_cells)`` marks the
columns that no surface process reaches. ``check_interfaces()`` refuses an active cell whose
top is at or below its bottom, and a pass-through cell may have no thickness.

The BAS arrays of MODFLOW-NWT
-----------------------------

``ibound`` and ``strt`` are the most sensitive inputs at the start of MODFLOW-NWT. An
inconsistency can destabilize the run without any error. HydroModPy follows the sign
convention of BAS. A cell with ``ibound > 0`` is active, ``ibound = 0`` is inactive and
``ibound < 0`` has an imposed head. For the last, ``strt`` holds the imposed head.

``FlowToModflowAdapter`` in ``hydromodpy/solver/modflow_nwt/nwt/flow_to_modflow_adapter.py``
builds the arrays (``_build_initial_heads_and_sides``, ``_build_ocean_chd`` and
``_validate_ibound_strt_contract``). ``nwt/_pre_processing.py`` passes them to
``flopy.modflow.ModflowBas``.

The order of the assignments matters, because a later one overwrites an earlier one.

1. ``strt`` starts from the initial state of the ``Model`` (``inputs.initial``, built from
   ``[flow.ic]`` by ``initial_state_of``). A ``HeadRule`` gives it by ``kind``: ``top`` takes
   the DEM, ``top_offset`` takes the DEM lowered by ``value``, ``bottom`` takes the bottom
   layer and ``custom`` takes a scalar. A ``SteadyStart`` or a ``CyclicStart`` starts the
   main model from the top, and its auxiliary solve sets the head after that. A
   ``PriorState`` or a ``SolvedState`` gives the head itself.
2. The lateral Dirichlet conditions (``west``, ``east``, ``north``, ``south``) flip the face
   cells to ``ibound = -1`` and overwrite ``strt`` with the boundary head.
3. The no-data mask flips the DEM cells below the sentinel threshold to ``ibound = 0``.
4. The ocean condition comes last. A scalar level can flip submerged cells to ``ibound < 0``
   and overwrite ``strt``. A transient forcing gives one CHD payload per stress period and
   can disable the drainage locally.

Before it goes on, the adapter checks that ``ibound`` and ``strt`` have shape
``(nlay, nrow, ncol)``, that ``drain_array`` has shape ``(nrow, ncol)`` and holds only 0 and
1, and that every value is finite. A non-finite value is a hard error. To debug a start,
check the order above, look at the three sign masks of ``ibound``, and plot ``strt`` on the
imposed-head faces.

The routing descent
-------------------

Every MODFLOW 6 and MODFLOW-NWT run builds one descent D per model build and keeps it on the
model (``model.descent``). D is a filled copy of the model top, in which every routable cell
has a receiver, so water has a path to a base level. It never returns to the solver, because
the channel bed, the drain elevations and the reach tops keep reading the model top. The
computation is ``hydromodpy/catchment/drainage/descent.py``. The adapter that both backends
call is ``hydromodpy/solver/modflow_common/flow_directions.py``.

An auxiliary model (steady start, spin-up cycle) is never extracted. MODFLOW 6 builds D for
it only when an SFR network walks D, MODFLOW-NWT never does, and neither leaves a sidecar.

``prepare_solver`` reads the river network A on the mesh cells once, in
``Model.geometry.channel_exits``. ``channel_exits_for_build`` says whether a build uses it,
and the build pins D on it with its active columns and its lakes (``pin_channel``).

- The seeds are the domain rim and the constant-head cells, with the same supports on both
  backends: ocean, side and river CHD, static or transient. On MODFLOW 6 these are the ocean
  and river CHD support masks and the side CHD rows. On MODFLOW-NWT they are the cells with
  ``ibound == -1`` and the rows of the CHD package. MODFLOW-NWT writes no river CHD. Lakes
  are traversed and are never seeds.
- A constant-head cell keeps its steepest descent, as a rim cell does, so the discharge of
  each cell and the accumulated fluxes cross a river CHD and the outlet keeps the domain sum.
  The walks that follow water out of the model stop there (``Descent.stopping_receiver``).
  A drain chain that reaches a CHD cell keeps a plain DRN, and a reach that reaches one is
  the outlet reach.
- Channel cells drain to the next cell of the channel tree when the river network was
  generated for the run, with or without SFR. Without a channel tree, D has no pin.
- The neighborhood follows the mesh type, D8 on a quad mesh and shared faces elsewhere. It is
  not an option of the output.
- The build leaves ``<model>.descent.npz`` in the solver folder. The extractor writes it under
  ``fields.zarr/mesh/`` right after the mesh (:doc:`../storage-layout`), and ``run.descent``
  reads it back. A run sealed before D was stored gets one rebuilt from its stored top, with
  no pin, no constant-head seed and no lake.

The consumers of D are the discharge and the upstream area of each cell in the calibration
observables, the accumulation of the cell fluxes (``drain_accumulation_flux`` and
``release_accumulation_flux``), and the flow direction map.

Two modules keep their own surface and do not read D. ``modflow_common/routing_context.py``
keeps a raster D8 pointer on the solver-grid DEM, conditioned by ``dem_correc_type``, and
mass transfer and MT3DMS accumulation follow it. The solver fills its own grid template in
every run. A DEM declared ``state = "conditioned"`` keeps ``provided`` for the regional
chain, but the solver grid is filled with ``fill``, because moving a conditioned DEM onto a
coarser grid recreates depressions. ``modflow_common/sink_mask.py`` answers another question,
which cells have no outlet in the four-face connectivity of the solver. The network criterion
fills its own copy of the model top on its own graph (:doc:`/theory/downslope-distance`).

See also
--------

- :doc:`mesh-pivot` for the cell mesh that feeds the discretization.
- :doc:`mesh-engines` for the mesh engines.
- :doc:`../contracts` for the adapter pattern that wraps these contracts.
