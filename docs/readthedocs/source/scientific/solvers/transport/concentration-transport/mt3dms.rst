MT3DMS Concentration Transport
==============================

This page groups scientific reading for ``transport/mt3dms``.

Use this path when the study needs concentration transport linked to a previous
``flow/modflownwt`` run.

What Is Repeated From The Common Transport Part
-----------------------------------------------

``transport/mt3dms`` still uses the common transport contract:

- it must be declared after a compatible ``flow`` process;
- it consumes the upstream MODFLOW-NWT flow model;
- concentration results depend on the upstream mesh, boundary conditions,
  recharge, storage, and stress periods;
- the transport parameter block must be interpreted together with the flow
  run that produced the velocity field.

MT3DMS Specifics
----------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Topic
     - MT3DMS interpretation
   * - Process pair
     - ``transport/mt3dms``.
   * - Required upstream flow
     - ``flow/modflownwt``.
   * - Transport type
     - Concentration transport.
   * - Ecosystem
     - Legacy MODFLOW-NWT-linked concentration route.
   * - Parameter family
     - Shared concentration parameters documented in
       :doc:`common-parameters`.
   * - Outputs
     - Concentration outputs ingested into the result/catalog layer.

Typical Plan
------------

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflownwt"]

   [[simulation.process]]
   id = "transport_main"
   type = "transport"
   solvers = ["mt3dms"]

Typical Parameter Block
-----------------------

.. code-block:: toml

   [transport.mt3dms.parameters]
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

Use ``transport/mt3dms`` when:

- the upstream flow model is MODFLOW-NWT;
- the workflow needs continuity with historical MT3DMS studies;
- concentration transport is required in the legacy structured-grid ecosystem.

Be explicit when comparing against ``transport/modflow6gwt`` because the
upstream flow solver and package ecosystem also change.

Related Architecture
--------------------

- :doc:`../../../../architecture/solver/transport/mt3dms-stack`
- :doc:`../../../../architecture/solver/transport/modflow-transport-adapters`
