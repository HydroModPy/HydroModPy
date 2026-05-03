Solvers
=======

This category documents the scientific content of HydroModPy solver families.

The navigation is organized in two hierarchy levels:

1. **process**: ``flow``, ``transport``, or workflow-stage processes;
2. **solver type or family**: MODFLOW, Boussinesq, particle tracking,
   concentration transport, postprocess adapters, or display adapters.

This process-first layout avoids treating every backend as one flat list. A
solver name only has a precise meaning inside a process pair such as
``flow/modflow6`` or ``transport/modflow6gwt``.

Start with the taxonomy and capability matrix when choosing a path. Then open
the process section that matches the modelling question.

.. toctree::
   :maxdepth: 2

   process-solver-taxonomy
   solver-capability-matrix
   Flow <flow/index>
   Transport <transport/index>
   Workflow stages <workflow-stages/index>
