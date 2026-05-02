Solvers
=======

This category documents the scientific content of HydroModPy solvers.

It complements the software architecture pages by focusing on what the solver
represents mathematically rather than how the runtime is orchestrated.

The section should also become the main place for:

- solver-family scientific comparisons,
- mesh and discretization rationale,
- documentation of numerical method choices,
- capability limits and backend-selection guidance.

.. toctree::
   :maxdepth: 2

   boussinesq-mathematical-notes
   meshes-and-numerical-methods
   mesh-and-discretization-strategies
   field-to-cell-parameter-transfer
   vertical-representation-and-storage-assumptions
   mesh-quality-and-acceptance-criteria
   modflow-governing-equation-and-cvfd-formulation
   modflow-family-methods
   modflow6-vs-modflownwt-scientific-comparison
   modflow-package-semantics-and-boundary-conditions
   xt3d-on-irregular-disv-meshes
   solver-capability-matrix
