MODFLOW 6 GWT Concentration Transport
=====================================

This page groups scientific reading for ``transport/modflow6gwt``.

Use this path when the study needs concentration transport linked to a previous
``flow/modflow6`` run.

What Is Repeated From The Common Transport Part
-----------------------------------------------

``transport/modflow6gwt`` still uses the common transport contract:

- it must be declared after a compatible ``flow`` process;
- it consumes the upstream MODFLOW 6 GWF flow model;
- concentration results depend on the upstream mesh, boundary conditions,
  recharge, storage, and stress periods;
- the transport parameter block must be interpreted together with the flow
  run that produced the velocity field.

MODFLOW 6 GWT Specifics
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Topic
     - MODFLOW 6 GWT interpretation
   * - Process pair
     - ``transport/modflow6gwt``.
   * - Required upstream flow
     - ``flow/modflow6``.
   * - Transport type
     - Concentration transport.
   * - Ecosystem
     - MODFLOW 6 GWT route aligned with a MODFLOW 6 GWF flow model.
   * - Parameter family
     - Shared concentration parameters documented in
       :doc:`common-parameters`.
   * - Outputs
     - MODFLOW 6 GWT concentration outputs ingested into the result/catalog
       layer.

Typical Plan
------------

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflow6"]

   [[simulation.process]]
   id = "transport_main"
   type = "transport"
   solvers = ["modflow6gwt"]

Typical Parameter Block
-----------------------

.. code-block:: toml

   [transport.modflow6gwt.parameters]
   spc_name = "NO3"
   sconc_init = 0.0
   sconc_input = 30.0
   disp_long = 10.0
   disp_transh = 0.1
   disp_transv = 0.01
   diffu_coeff = 0.0
   rate_decay = 0.0

Use Cases
---------

Use ``transport/modflow6gwt`` when:

- the upstream flow model is MODFLOW 6;
- the study needs the MODFLOW 6 groundwater-flow and transport ecosystem;
- MODFLOW 6 mesh or package choices should remain aligned across flow and
  concentration transport.

Be explicit when comparing against ``transport/mt3dms`` because the upstream
flow solver and package ecosystem also change.

Related Architecture
--------------------

- :doc:`../../../../architecture/solver/transport/modflow6gwt-stack`
- :doc:`../../../../architecture/solver/transport/modflow-transport-adapters`
