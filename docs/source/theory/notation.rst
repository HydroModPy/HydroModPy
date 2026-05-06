Unified notation
================

One reference list for every symbol used in the HydroModPy theory
pages. SI units are the default. Per-page math notes link back here
via the labels at the end of each row, so the same variable is never
defined twice.

Hydraulic state and forcing
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 12 18 14 56

   * - Symbol
     - Description
     - SI unit
     - Notes / cross-refs
   * - ``h``
     - Hydraulic head measured from a fixed datum
     - m
     - Field variable solved by every flow backend; see
       :doc:`solvers/modflow-governing-equation-and-cvfd-formulation`.
   * - ``z_top``
     - Land surface elevation
     - m
     - Used in the Boussinesq surface-interaction closures.
   * - ``z_bot``
     - Aquifer bottom elevation
     - m
     - Domain depth declared via ``[domain.depth_model]``.
   * - ``b = h - z_bot``
     - Saturated thickness
     - m
     - Drives transmissivity in unconfined regimes.
   * - ``q_x``, ``q_y``, ``q_z``
     - Specific discharge along axis
     - m s\ :sup:`-1`
     - Darcy flux per unit area; see :doc:`/architecture/solver/index`.
   * - ``Q``
     - Volumetric discharge
     - m\ :sup:`3` s\ :sup:`-1`
     - Streamflow, well rate, drainage outflow.
   * - ``R``
     - Recharge rate (positive into the aquifer)
     - m s\ :sup:`-1`
     - Forced via ``[flow.bc]`` recharge entries.
   * - ``q_ex``
     - Surface-interaction exchange flux
     - m s\ :sup:`-1`
     - Boussinesq closure between aquifer and ground surface.

Hydraulic parameters
--------------------

.. list-table::
   :header-rows: 1
   :widths: 12 18 14 56

   * - Symbol
     - Description
     - SI unit
     - Notes / cross-refs
   * - ``K``
     - Saturated hydraulic conductivity
     - m s\ :sup:`-1`
     - Field declared in ``[flow.param.K]``; supports homogeneous,
       heterogeneous, anisotropic.
   * - ``T = K * b``
     - Transmissivity
     - m\ :sup:`2` s\ :sup:`-1`
     - Used in linearized Boussinesq variants.
   * - ``S_s``
     - Specific storage
     - m\ :sup:`-1`
     - Storage per unit volume.
   * - ``S_y``
     - Specific yield
     - dimensionless
     - Drainable porosity in unconfined regimes.
   * - ``n``
     - Porosity
     - dimensionless
     - Required for transport formulations.
   * - ``alpha_L``, ``alpha_T``
     - Longitudinal and transverse dispersivities
     - m
     - Transport package input (MODFLOW 6 GWT, MT3DMS).

Geometry and discretisation
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 12 18 14 56

   * - Symbol
     - Description
     - SI unit
     - Notes / cross-refs
   * - ``L``
     - Domain characteristic length (1D, 2D)
     - m
     - Used in analytical validation cases.
   * - ``A``
     - Catchment surface area
     - m\ :sup:`2`
     - Reported per project; gallery shows ``area_km2``.
   * - ``dx``, ``dy``
     - Cell size on a structured grid
     - m
     - Set via ``[<solver>.sgrid.planar]``.
   * - ``nlay``
     - Number of vertical layers
     - dimensionless
     - Set via ``[<solver>.sgrid.vertical]``.
   * - ``dt``
     - Solver internal timestep
     - s
     - Adaptive in PETSc backend; fixed in MODFLOW.
   * - ``Pe``
     - Mesh Peclet number for transport
     - dimensionless
     - Used to assess oscillations on coarse meshes.

Time and calibration
--------------------

.. list-table::
   :header-rows: 1
   :widths: 12 18 14 56

   * - Symbol
     - Description
     - SI unit
     - Notes / cross-refs
   * - ``t``
     - Simulation time
     - s
     - Reported in catalog as ISO date when calendar metadata exists.
   * - ``T_sim``
     - Total simulated horizon
     - s
     - Set via ``[simulation.time]``.
   * - ``RMSE``
     - Root-mean-square error of an observable
     - same as observable
     - Default calibration objective.
   * - ``NSE``
     - Nash-Sutcliffe efficiency
     - dimensionless
     - Available via ``[calibration.objective]``.
   * - ``KGE``
     - Kling-Gupta efficiency
     - dimensionless
     - Optional alternative to NSE.

Conventions
-----------

- All times in TOML accept SI units (``"3600 s"``, ``"1 h"``,
  ``"0.5 d"``). The Pydantic Pint integration normalises them.
- Lengths default to metres; declarations may override with explicit
  units (``"500 m"``, ``"2 km"``).
- Vector quantities follow the right-hand rule with z pointing up.
- Sign convention: ``Q > 0`` and ``R > 0`` represent flux into the
  aquifer.

This page replaces what would have been a tools-comparison page. Per
the v1 documentation refactor plan, comparing HydroModPy with other
toolboxes (FloPy, ParFlow, PFLOTRAN) was deliberately dropped; the
solver capability matrix at
:doc:`solvers/solver-capability-matrix` documents the in-scope
backends instead.
