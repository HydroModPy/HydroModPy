MODFLOW 6 Flow
==============

This page groups scientific reading for ``flow/modflow6``.

Use this path when the study needs MODFLOW 6 package semantics, runtime
DISV-style unstructured support, XT3D method choices, or downstream
``transport/modflow6gwt`` compatibility.

What Is Repeated From The Common MODFLOW Part
---------------------------------------------

``flow/modflow6`` still uses the common MODFLOW-family contract:

- hydraulic head is the primary groundwater-flow state;
- recharge, wells, storage, imposed heads, and drainage are normalized by the
  HydroModPy ``Flow`` layer before backend assembly;
- stress periods carry the time discretization seen by the backend;
- package semantics must be documented before interpreting a result;
- comparison against another backend requires checking mesh, vertical
  representation, forcing aggregation, and boundary-condition mapping.

This repetition is intentional. The MODFLOW 6 page should be readable without
first opening the MODFLOW-NWT page.

MODFLOW 6 Specifics
-------------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Topic
     - MODFLOW 6 interpretation
   * - Process pair
     - ``flow/modflow6``.
   * - Backend family
     - MODFLOW 6 GWF.
   * - Grid support
     - Structured support and runtime DISV-style triangular support where
       enabled by the workflow.
   * - Package vocabulary
     - Modern MODFLOW 6 package stack for flow, storage, recharge, boundary
       conditions, and outputs.
   * - Irregular-mesh option
     - XT3D can matter on irregular DISV-style meshes.
   * - Active drainage outputs
     - DRN budgets are post-processed to positive ``outflow_drain`` and routed
       to ``accumulation_flux`` when the run exposes a usable solver mesh.
   * - Downstream transport
     - Preferred path for ``transport/modflow6gwt``.

Focused Reading
---------------

.. toctree::
   :maxdepth: 1

   ../../xt3d-on-irregular-disv-meshes
   ../../modflow6-vs-modflownwt-scientific-comparison
   ../../../hydrology/simulated-active-network
   ../../worked-modflow-case-dupuit-fixed-head-1d
   ../../worked-modflow-case-linearized-unconfined-recharge-periodic-1d

Typical Use Cases
-----------------

Use ``flow/modflow6`` when:

- the study needs modern MODFLOW 6 package semantics;
- the mesh may be irregular or DISV-style;
- XT3D behavior is part of the numerical-method question;
- downstream concentration transport should use MODFLOW 6 GWT;
- simulated drainage activation or active-network diagnostics should be
  inspected from persisted result fields;
- the run is part of a controlled comparison against MODFLOW-NWT or
  Boussinesq.

Be explicit when:

- reproducing a legacy MODFLOW-NWT study;
- comparing structured and irregular supports;
- changing XT3D;
- comparing raw cell outputs against collapsed profiles or observations.

Scientific Checklist
--------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Decision point
     - What to document
   * - Grid support
     - Structured grid or runtime DISV-style mesh.
   * - XT3D
     - Whether ``modflow6.runtime.mf6_enable_xt3d`` is enabled, disabled, or
       auto-resolved.
   * - Package envelope
     - Which MODFLOW 6 packages are assembled for recharge, wells, storage,
       boundary conditions, and outputs.
   * - Comparison target
     - Whether the run is compared to MODFLOW-NWT, Boussinesq, an analytical
       case, or field observations.
   * - Transport coupling
     - Whether the flow run must feed ``transport/modflow6gwt``.
   * - Active drainage diagnostics
     - Whether ``outflow_drain``, ``accumulation_flux``, and
       ``simulated_active_network`` are interpreted as local drainage, routed
       network signal, or thresholded display mask.

Minimal Plan Shape
------------------

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflow6"]

   [solver]
   solver_engine = "modflow6"

Minimal Process Interpretation
------------------------------

The short TOML shape above means:

- one ``flow`` process is requested;
- the selected solver name is ``modflow6``;
- HydroModPy resolves common ``Flow`` inputs to MODFLOW 6 packages;
- the final scientific interpretation depends on package choices, grid
  support, stress periods, and output diagnostics.

Related Architecture
--------------------

- :doc:`/architecture/solver/flow/modflow/modflow6-stack`
- :doc:`../../../../architecture/solver/modflow6-architecture-notes`
- :doc:`../../../../architecture/overview/hydrographic-network-simulated-active-inventory`
