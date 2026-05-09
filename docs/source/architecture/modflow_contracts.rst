MODFLOW-NWT Contracts
=====================

This page documents the internal contracts that HydroModPy honors before
instantiating MODFLOW-NWT packages. Two contracts are covered:

1. Spatial and temporal discretization (DIS package).
2. Boundary activation and initialization (BAS package, ``ibound`` and
   ``strt`` arrays).

1. Discretization contract
--------------------------

Source: ``hydromodpy/solver/modflow_nwt/nwt/discretization.py``.

Two typed dataclasses carry the contract:

- ``TemporalDiscretizationResult``
- ``SpatialDiscretizationResult``

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

Conversion to FloPy kwargs goes through
``TemporalDiscretizationResult.as_dis_kwargs()``, which exposes the keys
``itmuni``, ``nper``, ``perlen``, ``nstp``, ``steady``, ``start_datetime``.

1.2 Spatial contract
~~~~~~~~~~~~~~~~~~~~

Fields of ``SpatialDiscretizationResult``:

.. list-table::
   :header-rows: 1

   * - Field
     - Type
     - Role
   * - ``sgrid``
     - grid object
     - Output of ``StructuredGridBuilder``
   * - ``dem``
     - 2D float ``np.ndarray``
     - Validated topographic support
   * - ``nlay``
     - ``int``
     - Number of layers
   * - ``nrow``
     - ``int``
     - Number of rows
   * - ``ncol``
     - ``int``
     - Number of columns
   * - ``zbot``
     - 3D float ``np.ndarray``, shape ``(nlay, nrow, ncol)``
     - Bottom elevations
   * - ``bottom_layer``
     - 2D float ``np.ndarray``
     - ``zbot[-1]``, bottom of the lowest layer

Required invariants:

- ``zbot.shape == (nlay, nrow, ncol)``
- ``bottom_layer.shape == (nrow, ncol)``
- The domain provides ``surface_topo`` and ``substratum`` of type
  ``Surface``, consistent with the DEM shape.

1.3 Upstream inputs
~~~~~~~~~~~~~~~~~~~

The temporal builder consumes:

- ``tgrid_config.to_builder_kwargs()``
- ``flow_regime``
- ``default_itmuni``

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

See also
--------

- :doc:`solver/index` for the solver package architecture.
- :doc:`mesh/structured-grid-architecture` for the grid object that
  feeds the DIS contract.
- :doc:`overview/design-patterns` (item 1) for the adapter pattern that
  wraps these contracts.
