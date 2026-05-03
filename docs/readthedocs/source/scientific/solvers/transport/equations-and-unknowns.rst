Transport Equations And Unknowns
================================

This page gives the scientific entry point for the ``transport`` process.

Transport does not solve groundwater flow again. It consumes a previously
computed flow field and solves one of two downstream problems:

- particle positions and travel times;
- concentration fields for one transported species.

Flow Dependency
---------------

The upstream ``flow`` process provides hydraulic heads, cell budgets, stresses,
and mesh support. Transport then interprets those flow outputs as velocities,
advective fluxes, or package exchanges.

The dependency is therefore part of the equation definition. The same transport
parameters can produce different results when the upstream flow backend,
discretization, recharge, or boundary packages change.

Particle-Tracking Equation
--------------------------

Particle tracking follows advective trajectories through the solved flow field.
The primary unknown is the particle position ``x(t)``:

.. math::

   \frac{d x}{d t} = v(x, t)

where ``v`` is derived from the upstream flow solution and its cell-by-cell
budget information.

HydroModPy currently exposes this family through:

.. list-table::
   :header-rows: 1
   :widths: 28 28 44

   * - Transport solver
     - Required flow solver
     - Main unknown/output
   * - ``transport/modpath``
     - ``flow/modflownwt``
     - Particle pathlines, endpoints, and travel-time diagnostics.

Concentration-Transport Equation
--------------------------------

Concentration transport follows a species concentration ``C`` through advection,
dispersion, diffusion, source input, and optional decay. A compact reading of
the governing balance is:

.. math::

   \frac{\partial(\theta C)}{\partial t}
   =
   \nabla \cdot (\theta D \nabla C)
   -
   \nabla \cdot (q C)
   +
   S_C
   -
   \lambda \theta C

where:

- ``C`` is concentration;
- ``theta`` represents mobile water content or effective storage support as
  interpreted by the backend;
- ``D`` is the dispersion/diffusion tensor;
- ``q`` is the advective flux derived from the upstream flow model;
- ``S_C`` groups concentration inputs and sinks/sources;
- ``lambda`` is a decay coefficient when enabled.

HydroModPy currently exposes this family through two backend routes:

.. list-table::
   :header-rows: 1
   :widths: 28 28 44

   * - Transport solver
     - Required flow solver
     - Main unknown/output
   * - ``transport/mt3dms``
     - ``flow/modflownwt``
     - Concentration fields in the MODFLOW-NWT + MT3DMS ecosystem.
   * - ``transport/modflow6gwt``
     - ``flow/modflow6``
     - Concentration fields in the MODFLOW 6 GWF + GWT ecosystem.

Parameter Vocabulary
--------------------

The equation terms are controlled through solver-specific parameter blocks:

.. code-block:: toml

   [transport.modpath.parameters]
   zone_partic = "domain"
   track_dir = "forward"
   cell_div = 2

   [transport.mt3dms.parameters]
   spc_name = "NO3"
   sconc_init = 0.0
   sconc_input = 30.0
   disp_long = 10.0
   disp_transh = 0.1
   disp_transv = 0.01
   diffu_coeff = 0.0
   rate_decay = 0.0

   [transport.modflow6gwt.parameters]
   spc_name = "NO3"
   sconc_init = 0.0
   sconc_input = 30.0
   disp_long = 10.0
   disp_transh = 0.1
   disp_transv = 0.01
   diffu_coeff = 0.0
   rate_decay = 0.0

Reading Rule
------------

When documenting a transport simulation, record both the equation family and
the backend route:

- ``MODFLOW-NWT route``: ``flow/modflownwt`` followed by ``transport/modpath``
  and/or ``transport/mt3dms``;
- ``MODFLOW 6 route``: ``flow/modflow6`` followed by
  ``transport/modflow6gwt``.

Related Pages
-------------

- :doc:`common-concepts`
- :doc:`modflow-nwt-transport`
- :doc:`modflow6-transport`
- :doc:`concentration-transport/common-parameters`
