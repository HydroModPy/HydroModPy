MODFLOW Transport Coupling
==========================

MODFLOW flow results often become the upstream state for transport solvers.
This page explains where that coupling sits in the scientific documentation.

Current Couplings
-----------------

.. list-table::
   :header-rows: 1
   :widths: 28 28 44

   * - Flow pair
     - Transport pair
     - Interpretation
   * - ``flow/modflownwt``
     - ``transport/modpath``
     - Particle tracking on the MODFLOW-NWT flow field.
   * - ``flow/modflownwt``
     - ``transport/mt3dms``
     - Concentration transport on the MODFLOW-NWT flow field.
   * - ``flow/modflow6``
     - ``transport/modflow6gwt``
     - MODFLOW 6 GWT concentration transport on the MODFLOW 6 flow field.

Transport Reading Path
----------------------

.. toctree::
   :maxdepth: 1

   ../../transport/particle-tracking
   ../../transport/concentration-transport

Interpretation Rule
-------------------

Do not interpret transport outputs independently from their upstream flow
run. A change in mesh, recharge, boundary conditions, storage assumptions, or
flow solver choice changes the velocity field that transport consumes.

Related Architecture
--------------------

- :doc:`/architecture/solver/flow/modflow/transport-coupling`
- :doc:`../../../../architecture/solver/transport/modflow-transport-adapters`
