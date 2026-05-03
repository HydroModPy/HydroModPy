Concentration Transport
=======================

Concentration transport answers questions about species movement, dispersive
spreading, input concentration, and decay after flow has been solved.

Current Solvers
---------------

.. list-table::
   :header-rows: 1
   :widths: 20 28 52

   * - Solver
     - Requires
     - Role
   * - ``mt3dms``
     - Earlier ``flow/modflownwt`` run.
     - Legacy MODFLOW-NWT-linked concentration transport route.
   * - ``modflow6gwt``
     - Earlier ``flow/modflow6`` run.
     - MODFLOW 6 GWT concentration transport route.

Typical MODFLOW-NWT + MT3DMS Plan
---------------------------------

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflownwt"]

   [[simulation.process]]
   id = "transport_main"
   type = "transport"
   solvers = ["mt3dms"]

Typical MODFLOW 6 + GWT Plan
----------------------------

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflow6"]

   [[simulation.process]]
   id = "transport_main"
   type = "transport"
   solvers = ["modflow6gwt"]

Shared Parameter Shape
----------------------

``mt3dms`` and ``modflow6gwt`` currently use the same concentration-parameter
family:

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

   [transport.modflow6gwt.parameters]
   spc_name = "NO3"
   sconc_init = 0.0
   sconc_input = 30.0
   disp_long = 10.0
   disp_transh = 0.1
   disp_transv = 0.01
   diffu_coeff = 0.0
   rate_decay = 0.0

Scientific Reading Notes
------------------------

- Treat transport outputs as dependent on upstream flow assumptions.
- Compare ``mt3dms`` and ``modflow6gwt`` only after documenting their upstream
  flow solvers, meshes, and package semantics.
- Concentration transport needs dedicated validation pages; the current matrix
  documents implementation status and dependency structure first.

Related Pages
-------------

- :doc:`../flow/modflow-family`
- :doc:`../../../architecture/solver/transport/modflow-transport-adapters`
- :doc:`../solver-capability-matrix`
