MODFLOW-NWT Contracts
=====================

This page documents the internal contracts that HydroModPy honors before
instantiating MODFLOW-NWT packages. Two contracts are covered, followed by
the routing descent both MODFLOW backends share:

1. Spatial and temporal discretization (DIS package).
2. Boundary activation and initialization (BAS package, ``ibound`` and
   ``strt`` arrays).
3. The routing descent D, and what routes apart from it.

1. Discretization contract
--------------------------

Source: ``hydromodpy/solver/modflow_grid/discretization_temporal.py`` and
``hydromodpy/solver/modflow_grid/discretization_spatial.py``, shared by
both MODFLOW backends.

Two typed dataclasses carry the contract:

- ``TemporalDiscretizationResult``
  (``discretization_temporal.py``)
- ``SolverGridContext`` (``grid_context.py``), built by
  ``build_spatial_discretization``

1.1 Temporal contract
~~~~~~~~~~~~~~~~~~~~~

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

Launcher runs are built in ``hydromodpy.core.time.SIMULATION_TIME_UNIT``, that
is SI seconds: ``ResolvedSimulationTimeGrid`` carries period lengths in
seconds, so declaring anything else would rescale every extracted flux. Both
backends take the declaration from this single field rather than restating it,
and the extractors read it back from the run's own TDIS or DIS file through
``hydromodpy.solver.modflow_common.time_units``.

Conversion to FloPy kwargs goes through
``TemporalDiscretizationResult.as_dis_kwargs()``, which exposes the keys
``itmuni``, ``nper``, ``perlen``, ``nstp``, ``steady``, ``start_datetime``.

1.2 Spatial contract
~~~~~~~~~~~~~~~~~~~~

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
     - Prismatic mesh: ``planar_mesh``, ``top``, ``botm``,
       ``inactive_mask``
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

- ``solver_mesh.botm`` has shape ``(nlay, n_cells)``; ``top`` and
  ``inactive_mask`` are flat ``(n_cells,)`` arrays.
- The grid is mesh-native: ``structured_shape`` is set only when the
  planar mesh is a Cartesian grid, and is ``None`` for DISV meshes.
- The domain provides ``surface_topo`` and ``substratum`` of type
  ``Surface``.

1.3 Upstream inputs
~~~~~~~~~~~~~~~~~~~

The temporal builder consumes:

- ``time_grid``, the ``ResolvedSimulationTimeGrid`` derived from
  ``[simulation.time]``
- ``flow_regime``
- ``first_period_steady``

The spatial builder consumes:

- the ``domain`` with ``surface_topo`` and ``substratum``
- the active DEM shape
- ``vertical_config``

1.4 Why this contract
~~~~~~~~~~~~~~~~~~~~~

- Make the DIS payload explicit and testable.
- Prevent any shape or unit drift between runtime objects and the
  solver configuration.
- Keep the DIS conventions out of the orchestration code.

2. BAS contract (``ibound``, ``strt``)
--------------------------------------

These two arrays are the most sensitive at MODFLOW startup. An
inconsistency can silently destabilize the simulation.

2.1 MODFLOW semantics honored
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

HydroModPy follows the standard sign-based BAS contract:

- ``ibound > 0``: active cell, head is computed.
- ``ibound = 0``: inactive cell, no-flow.
- ``ibound < 0``: imposed-head cell (constant head).

``strt`` is a 3D array ``(nlay, nrow, ncol)``. For ``ibound < 0``
cells, ``strt`` provides the imposed head used by BAS.

2.2 Where the arrays are built
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Main source:

- ``hydromodpy/solver/modflow_nwt/nwt/flow_to_modflow_adapter.py``

  - ``FlowToModflowAdapter._build_initial_heads_and_sides``
  - ``FlowToModflowAdapter._build_ocean_chd``
  - ``FlowToModflowAdapter._validate_ibound_strt_contract``

Assembly point:

- ``hydromodpy/solver/modflow_nwt/nwt/nwt_solver.py`` calls
  ``flopy.modflow.ModflowBas(..., ibound=..., strt=...)``.

2.3 Application order
~~~~~~~~~~~~~~~~~~~~~

The ``strt`` initialization policy comes from
``flow.initial_conditions.h.type``:

1. ``top``: initialize from the DEM.
2. ``bottom``: initialize from the bottom-layer elevation.
3. ``custom``: initialize from a user scalar value.

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

2.4 Validations applied
~~~~~~~~~~~~~~~~~~~~~~~

Before assembly continues, the adapter checks:

1. ``ibound.shape == (nlay, nrow, ncol)``
2. ``strt.shape == (nlay, nrow, ncol)``
3. ``drain_array.shape == (nrow, ncol)``
4. all values are finite
5. ``drain_array`` is binary (``0`` or ``1``)

The validation enforces sign-based semantics, not just
``{-1, 0, 1}``.

2.5 Practical debugging
~~~~~~~~~~~~~~~~~~~~~~~

1. Check the assignment order (initial conditions, then lateral
   boundaries, then ocean).
2. Inspect ``ibound`` sign masks (``>0``, ``=0``, ``<0``) before
   launching the solver.
3. Plot ``strt`` slices on imposed-head faces and ocean-influenced
   areas.
4. Any non-finite value in ``ibound`` or ``strt`` is a hard error.

3. Routing descent contract
---------------------------

Source: ``hydromodpy/core/descent.py`` (the computation) and
``hydromodpy/solver/modflow_common/mesh_descent.py`` (the adapter both
backends call; neither backend imports the other).

Every MODFLOW 6 and MODFLOW-NWT run builds one descent D per model build and
keeps it on the model (``model.descent``), without the neighbour sets the
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
- **Neighbourhood.** Fixed by the mesh type: D8 (shared nodes) on a quad mesh,
  shared faces elsewhere. It is not a per-output option.
- **Stored with the run.** The build leaves ``<model>.descent.npz`` in the
  solver folder; the extractor writes it under ``fields.zarr/mesh/`` right after
  the mesh (see :doc:`../storage-layout`) and ``run.descent`` reads it back. A
  run sealed before D was stored gets one rebuilt from its stored top, with no
  pin, no constant-head seed and no lake.

Consumers on D: the per-cell discharge and upstream area of the calibration
observables (``modflow_common/discharge_routing.py``), the accumulation of
cell fluxes (``accumulation_flux``, ``release_accumulation_flux``), and the
flow direction map, which also marks the cells D raised on its copy.

Declared apart, each on its own surface:

- ``modflow_common/routing_context.py`` keeps its own raster D8 pointer on the
  solver-grid DEM, conditioned by ``dem_correc_type``. Mass transfer and MT3DMS
  accumulation trace point sources down the Whitebox pointer and stay on it
  until they are migrated.
- The Boussinesq raster path of ``derived.py`` routes on its own Whitebox D8
  raster: a Boussinesq store holds a top and no mesh connectivity, so it has no
  D.
- ``solver/modflow6/postprocess/_unstructured.py``
  (``accumulate_unstructured_cell_values``, the legacy GeoTIFF export on an
  unstructured MODFLOW 6 mesh) accumulates on its own adjacency of the DEM.
- ``modflow_common/sink_mask.py`` answers a different question, which cells
  have no outlet in the solver's own four-face connectivity, and stays on it.
- The network criterion reads the model top T and fills its own copy on its own
  graph (see :doc:`../../theory/streams_and_seepage/downslope-distance-calibration`).

See also
--------

- :doc:`index` for the solver package architecture.
- :doc:`../mesh/structured-grid-architecture` for the grid object that
  feeds the DIS contract.
- :doc:`../overview/design-patterns` (item 1) for the adapter pattern that
  wraps these contracts.
