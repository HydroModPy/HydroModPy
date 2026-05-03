MODFLOW 6 Transport Route
=========================

This page groups the transport solver attached to ``flow/modflow6``.

The route is:

.. code-block:: text

   flow/modflow6 -> transport/modflow6gwt

It is the MODFLOW 6 groundwater-flow and transport route. It should be read
separately from the MODFLOW-NWT route because the upstream flow solver,
package ecosystem, and concentration backend are different.

Available Solver
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 28 48

   * - Solver
     - Equation family
     - Role
   * - ``transport/modflow6gwt``
     - Concentration transport.
     - Species concentration fields coupled to a previous MODFLOW 6 GWF flow
       run.

Current Scope
-------------

HydroModPy currently documents concentration transport for the MODFLOW 6 route
through GWT. Particle tracking is not documented as a current MODFLOW 6
transport route in this section.

Equation Reading
----------------

``transport/modflow6gwt`` reads the solved MODFLOW 6 GWF flow model and solves
a concentration-transport balance:

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

Typical Concentration Plan
--------------------------

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflow6"]

   [[simulation.process]]
   id = "transport_concentration"
   type = "transport"
   solvers = ["modflow6gwt"]

   [transport.modflow6gwt.parameters]
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

- upstream ``flow/modflow6`` run identifier;
- grid or mesh support and stress-period setup;
- MODFLOW 6 package choices used by the upstream flow run;
- recharge, boundary-condition, and well assumptions;
- GWT concentration parameters;
- output type: concentration fields, slices, time series, or reduced metrics.

Comparison With MODFLOW-NWT Transport
-------------------------------------

Do not read ``transport/modflow6gwt`` versus ``transport/mt3dms`` as a pure
transport-solver comparison unless the upstream flow differences have also
been documented. The comparison changes both the flow backend and the transport
backend:

.. list-table::
   :header-rows: 1
   :widths: 36 32 32

   * - Question
     - MODFLOW-NWT route
     - MODFLOW 6 route
   * - Flow solver
     - ``flow/modflownwt``.
     - ``flow/modflow6``.
   * - Concentration solver
     - ``transport/mt3dms``.
     - ``transport/modflow6gwt``.
   * - Particle tracking
     - ``transport/modpath``.
     - Not documented as a current MODFLOW 6 route here.

Related Pages
-------------

- :doc:`concentration-transport/modflow6gwt`
- :doc:`../flow/modflow/modflow6`
- :doc:`../flow/modflow/transport-coupling`
- :doc:`../../../architecture/solver/transport/modflow6gwt-stack`
