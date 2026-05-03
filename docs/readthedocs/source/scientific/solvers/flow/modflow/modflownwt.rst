MODFLOW-NWT Flow
================

This page groups scientific reading for ``flow/modflownwt``.

Use this path when the study needs continuity with legacy structured-grid
MODFLOW-NWT workflows or downstream ``transport/modpath`` and
``transport/mt3dms`` compatibility.

Focused Reading
---------------

.. toctree::
   :maxdepth: 1

   ../../modflow6-vs-modflownwt-scientific-comparison
   ../../worked-modflow-case-linearized-unconfined-recharge-periodic-1d

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

Related Architecture
--------------------

- :doc:`/architecture/solver/flow/modflow/modflownwt-stack`
- :doc:`../../../../architecture/solver/modflownwt-architecture-notes`
