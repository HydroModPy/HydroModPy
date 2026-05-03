MODFLOW-NWT Flow
================

This page groups scientific reading for ``flow/modflownwt``.

Use this path when the study needs continuity with legacy structured-grid
MODFLOW-NWT workflows or downstream ``transport/modpath`` and
``transport/mt3dms`` compatibility.

What Is Repeated From The Common MODFLOW Part
---------------------------------------------

``flow/modflownwt`` still uses the common MODFLOW-family contract:

- hydraulic head is the primary groundwater-flow state;
- recharge, wells, storage, imposed heads, and drainage are normalized by the
  HydroModPy ``Flow`` layer before backend assembly;
- stress periods carry the time discretization seen by the backend;
- package semantics must be documented before interpreting a result;
- comparison against another backend requires checking mesh, vertical
  representation, forcing aggregation, and boundary-condition mapping.

This repetition is intentional. The MODFLOW-NWT page should be readable
without first opening the MODFLOW 6 page.

MODFLOW-NWT Specifics
---------------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Topic
     - MODFLOW-NWT interpretation
   * - Process pair
     - ``flow/modflownwt``.
   * - Backend family
     - MODFLOW-NWT.
   * - Grid support
     - Structured ``sgrid`` support.
   * - Package vocabulary
     - Legacy MODFLOW package route for flow, recharge, storage, boundary
       conditions, and outputs.
   * - Legacy continuity
     - Useful for reproducing or comparing with historical studies that were
       calibrated around MODFLOW-NWT assumptions.
   * - Downstream transport
     - Preferred path for ``transport/modpath`` and ``transport/mt3dms``.

Focused Reading
---------------

.. toctree::
   :maxdepth: 1

   ../../modflow6-vs-modflownwt-scientific-comparison
   ../../worked-modflow-case-linearized-unconfined-recharge-periodic-1d

Typical Use Cases
-----------------

Use ``flow/modflownwt`` when:

- the study is structured-grid only;
- the target is continuity with an older MODFLOW-NWT workflow;
- downstream particle tracking should use MODPATH;
- downstream concentration transport should use MT3DMS;
- a comparison needs a legacy MODFLOW-family baseline.

Be explicit when:

- the same physical case is also run with MODFLOW 6;
- MODFLOW 6 uses a different grid topology or XT3D setting;
- observations or validation profiles are compared after spatial aggregation;
- transport results depend on this upstream flow field.

Scientific Checklist
--------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Decision point
     - What to document
   * - Grid support
     - Structured ``sgrid`` support.
   * - Legacy continuity
     - Whether the run is intended to reproduce or compare with older
       MODFLOW-NWT studies.
   * - Package envelope
     - Which recharge, well, storage, and boundary-condition packages are
       assembled.
   * - Comparison target
     - Whether the run is compared to MODFLOW 6, Boussinesq, an analytical
       case, or field observations.
   * - Transport coupling
     - Whether the flow run must feed ``transport/modpath`` or
       ``transport/mt3dms``.

Minimal Plan Shape
------------------

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflownwt"]

   [solver]
   solver_engine = "modflownwt"

Minimal Process Interpretation
------------------------------

The short TOML shape above means:

- one ``flow`` process is requested;
- the selected solver name is ``modflownwt``;
- HydroModPy resolves common ``Flow`` inputs to the MODFLOW-NWT route;
- the final scientific interpretation depends on structured support, package
  choices, stress periods, and downstream legacy transport needs.

Related Architecture
--------------------

- :doc:`/architecture/solver/flow/modflow/modflownwt-stack`
- :doc:`../../../../architecture/solver/modflownwt-architecture-notes`
