MODFLOW-NWT Transport Route
===========================

This page groups the transport solvers attached to ``flow/modflownwt``.

The route is:

.. code-block:: text

   flow/modflownwt -> transport/modpath
   flow/modflownwt -> transport/mt3dms

It is the legacy structured-grid transport route. It should be read separately
from the MODFLOW 6 route because the upstream flow solver, package ecosystem,
and transport backends are different.

Available Solvers
-----------------

.. list-table::
   :header-rows: 1
   :widths: 24 28 48

   * - Solver
     - Equation family
     - Role
   * - ``transport/modpath``
     - Particle tracking.
     - Advective pathlines, endpoints, and travel-time diagnostics.
   * - ``transport/mt3dms``
     - Concentration transport.
     - Species concentration fields with dispersion, diffusion, source
       concentration, and decay parameters.

Equation Reading
----------------

``transport/modpath`` reads the solved MODFLOW-NWT flow field and integrates
particle trajectories:

.. math::

   \frac{d x}{d t} = v(x, t)

``transport/mt3dms`` reads the same MODFLOW-NWT flow support and solves a
concentration-transport balance:

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

Typical Particle-Tracking Plan
------------------------------

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflownwt"]

   [[simulation.process]]
   id = "transport_paths"
   type = "transport"
   solvers = ["modpath"]

   [transport.modpath.parameters]
   zone_partic = "domain"
   track_dir = "forward"
   cell_div = 2

Typical Concentration Plan
--------------------------

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflownwt"]

   [[simulation.process]]
   id = "transport_concentration"
   type = "transport"
   solvers = ["mt3dms"]

   [transport.mt3dms.parameters]
   spc_name = "NO3"
   sconc_init = 0.0
   sconc_input = 30.0
   disp_long = 10.0
   disp_transh = 0.1
   disp_transv = 0.01
   diffu_coeff = 0.0
   rate_decay = 0.0

Interpretation Checklist
------------------------

Before interpreting or comparing this route, record:

- upstream ``flow/modflownwt`` run identifier;
- structured-grid support and stress-period setup;
- recharge, boundary-condition, and well package assumptions;
- selected transport solver: ``modpath`` or ``mt3dms``;
- particle injection parameters for MODPATH;
- concentration parameters for MT3DMS;
- output type: pathlines, endpoints, concentration fields, or reduced metrics.

Related Pages
-------------

- :doc:`particle-tracking/modpath`
- :doc:`concentration-transport/mt3dms`
- :doc:`../flow/modflow/modflownwt`
- :doc:`../../../architecture/solver/transport/modpath-stack`
- :doc:`../../../architecture/solver/transport/mt3dms-stack`
