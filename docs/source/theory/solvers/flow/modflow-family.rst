MODFLOW Flow Family
===================

This page groups the scientific notes for MODFLOW-family ``flow`` solvers.

.. figure:: /_static/theory/modflow/modflow_family_map.svg
   :alt: Reading map for the HydroModPy MODFLOW flow family
   :width: 100%

   Start from the shared MODFLOW concepts, then choose the modern MODFLOW 6
   route, the legacy MODFLOW-NWT route, or the cross-cutting comparison pages.
   This avoids mixing backend-specific details before the common groundwater
   balance and package vocabulary are clear.

Read this family as three explicit blocks:

.. list-table::
   :header-rows: 1
   :widths: 24 34 42

   * - Block
     - Main page
     - Purpose
   * - Common MODFLOW part
     - :doc:`../modflow-governing-equation-and-cvfd-formulation`
     - Shared groundwater-flow vocabulary: governing equation, package
       semantics, boundary mapping, stress periods, vertical assumptions, and
       comparison discipline.
   * - MODFLOW 6 version
     - :doc:`modflow/modflow6`
     - Modern MODFLOW 6 GWF route for ``flow/modflow6``: structured and
       runtime DISV-style supports, XT3D choices, and MODFLOW 6 GWT coupling.
   * - MODFLOW-NWT version
     - :doc:`modflow/modflownwt`
     - Legacy MODFLOW-NWT route for ``flow/modflownwt``: structured ``sgrid``
       support, continuity with historical studies, MODPATH, and MT3DMS.

In HydroModPy, the two active MODFLOW-family flow versions are:

- ``flow/modflownwt``: legacy MODFLOW-NWT route, structured ``sgrid`` support,
  and compatibility with MODPATH and MT3DMS.
- ``flow/modflow6``: modern MODFLOW 6 route, including structured grids and
  runtime DISV-style unstructured meshes where supported.

Result Examples
---------------

The MODFLOW family pages should be read with real output figures in mind. The
two examples below are useful first anchors:

.. tab-set::

   .. tab-item:: MODFLOW 6 basin state

      .. gallery-figure:: /_static/capability_gallery/simulation/headwater_100km2_outlet_2_mf6_transient_reference_flow_state_triptych.png
         :alt: MODFLOW 6 transient basin flow-state triptych
         :width: 100%

         A MODFLOW 6 basin run can be inspected through aligned maps of
         topography, hydraulic head, and water-table depth.

   .. tab-item:: MODFLOW-NWT basin response

      .. gallery-figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_hydrograph.png
         :alt: Nancon transient MODFLOW-NWT observed and simulated hydrograph
         :width: 100%

         A MODFLOW-NWT basin run can be read through outlet response and budget
         diagnostics before more specialized spatial overlays are interpreted.

Internal pages
--------------

.. toctree::
   :caption: MODFLOW pages
   :maxdepth: 1

   modflow/modflow6
   modflow/modflownwt
   modflow/comparison-and-method-choice
   modflow/worked-cases
   modflow/transport-coupling

Quick reading order
-------------------

If you do not know where to start:

1. :doc:`../modflow-governing-equation-and-cvfd-formulation` for the
   shared groundwater balance.
2. :doc:`modflow/modflow6` if you use the modern MODFLOW 6 path, or
   :doc:`modflow/modflownwt` if you use the legacy MODFLOW-NWT path.
3. :doc:`modflow/comparison-and-method-choice` and
   :doc:`modflow/transport-coupling` once the chosen backend is clear.
4. :doc:`modflow/worked-cases` to anchor everything in a concrete run.

Surface Exchange And Active-Network Reading
-------------------------------------------

For stream supports, seepage, drainage outflow, and simulated active-network
diagnostics, use the dedicated scientific section before reading backend
details:

- :doc:`../../streams_and_seepage/conceptual-model` explains the modelling
  decisions: stream boundary, seepage/drainage operator, and post-solve active
  network.
- :doc:`../../streams_and_seepage/worked-examples` lists the examples that
  connect those decisions to commands, files, and figures.
- :doc:`../../streams_and_seepage/status-and-limitations` states what is
  implemented, what is demonstrated, and what is still a non-contract.
- :doc:`../../hydrology/simulated-active-network` explains the MODFLOW 6 result
  ladder from ``outflow_drain`` to ``accumulation_flux`` and the thresholded
  active-network view.

This separation matters for MODFLOW-family comparisons. MODFLOW-NWT is the
legacy structured baseline. MODFLOW 6 is the modern path where mesh topology
and result extraction must be explicit enough to support routed active-network
diagnostics.

Backend Version Summary
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 20 28 28 24

   * - Version
     - Shared MODFLOW concepts repeated in that page
     - Version-specific emphasis
     - Downstream transport
   * - ``flow/modflow6``
     - Flow equation, recharge, wells, storage, imposed heads, drainage,
       stress periods, package semantics.
     - MODFLOW 6 package stack, structured or DISV-style support, XT3D,
       modern output and GWT compatibility.
     - ``transport/modflow6gwt``.
   * - ``flow/modflownwt``
     - Flow equation, recharge, wells, storage, imposed heads, drainage,
       stress periods, package semantics.
     - Structured-grid continuity, historical MODFLOW-NWT behavior, legacy
       package assumptions, MODPATH and MT3DMS compatibility.
     - ``transport/modpath`` and ``transport/mt3dms``.

Selection Notes
---------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Solver
     - Prefer when
     - Be careful when
   * - ``modflownwt``
     - You need continuity with legacy structured-grid workflows or downstream
       MODPATH / MT3DMS transport.
     - You need runtime Gmsh/DISV-style irregular mesh support.
   * - ``modflow6``
     - You need modern MODFLOW package semantics, irregular mesh support, or
       MODFLOW 6 GWT transport compatibility.
     - You compare against legacy studies whose numerical assumptions were
       calibrated on MODFLOW-NWT.

Related Architecture
--------------------

- :doc:`../../../architecture/solver/index`
- :doc:`../../../architecture/solver/modflow6-architecture-notes`
- :doc:`../../../architecture/solver/modflownwt-architecture-notes`
