MODFLOW 6 Flow
==============

This page groups scientific reading for ``flow/modflow6``.

Use this path when the study needs MODFLOW 6 package semantics, runtime
DISV-style unstructured support, XT3D method choices, or downstream
``transport/modflow6gwt`` compatibility.

Focused Reading
---------------

.. toctree::
   :maxdepth: 1

   ../../xt3d-on-irregular-disv-meshes
   ../../modflow6-vs-modflownwt-scientific-comparison
   ../../worked-modflow-case-dupuit-fixed-head-1d
   ../../worked-modflow-case-linearized-unconfined-recharge-periodic-1d

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

Minimal Plan Shape
------------------

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflow6"]

   [solver]
   solver_engine = "modflow6"

Related Architecture
--------------------

- :doc:`/architecture/solver/flow/modflow/modflow6-stack`
- :doc:`../../../../architecture/solver/modflow6-architecture-notes`
