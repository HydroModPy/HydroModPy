Common Transport Concepts
=========================

Start here when the question is not yet specific to MODPATH, MT3DMS, or
MODFLOW 6 GWT.

Transport In HydroModPy
-----------------------

The ``transport`` process is downstream from ``flow``. It does not define an
independent groundwater head solve. It consumes a compatible flow field and
derives particle paths or concentration evolution from it.

The most important rule is:

.. code-block:: text

   flow process first
   transport process second

The planner checks dependencies, but it does not reorder the user's process
declaration.

Current Transport Families
--------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 28 28 20

   * - Family
     - Solvers
     - Required upstream flow
     - Output type
   * - Particle tracking
     - ``modpath``
     - ``flow/modflownwt``
     - Pathlines, endpoints, travel-time information.
   * - Concentration transport
     - ``mt3dms``
     - ``flow/modflownwt``
     - Concentration fields.
   * - Concentration transport
     - ``modflow6gwt``
     - ``flow/modflow6``
     - Concentration fields.

Transport Solver Routes
-----------------------

The practical documentation split is by MODFLOW route:

.. list-table::
   :header-rows: 1
   :widths: 28 36 36

   * - Route
     - Solvers
     - Main use
   * - :doc:`modflow-nwt-transport`
     - ``flow/modflownwt`` followed by ``transport/modpath`` or
       ``transport/mt3dms``.
     - Legacy structured-grid particle tracking and concentration transport.
   * - :doc:`modflow6-transport`
     - ``flow/modflow6`` followed by ``transport/modflow6gwt``.
     - MODFLOW 6 GWF + GWT concentration transport.

Dependency Semantics
--------------------

Transport outputs must always be interpreted together with the upstream flow
run:

- the flow solver defines the hydraulic head and budget state;
- the flow mesh defines the support on which velocities or transport packages
  are built;
- recharge, boundary conditions, storage, and stress periods from the flow run
  control the transport result;
- changing ``flow/modflownwt`` to ``flow/modflow6`` is not a neutral change for
  downstream transport.

Parameter Layout
----------------

Transport parameters live under solver-specific blocks:

.. code-block:: toml

   [transport.modpath.parameters]

   [transport.mt3dms.parameters]

   [transport.modflow6gwt.parameters]

This keeps process orchestration separate from solver-specific scientific
choices.

Common Reading Discipline
-------------------------

When documenting or comparing a transport result, record:

- upstream ``process/solver`` pair;
- flow mesh and vertical representation;
- flow stress-period setup;
- recharge, boundary, and well assumptions from the upstream run;
- transport solver name;
- transport parameter block;
- output type being compared: pathline, endpoint, concentration field, or
  reduced metric.

Related Pages
-------------

- :doc:`equations-and-unknowns`
- :doc:`modflow-nwt-transport`
- :doc:`modflow6-transport`
- :doc:`particle-tracking`
- :doc:`concentration-transport`
- :doc:`../flow/modflow/transport-coupling`
- :doc:`../../../architecture/solver/transport/index`
