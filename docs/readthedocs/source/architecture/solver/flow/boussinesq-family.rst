Boussinesq Flow Architecture
============================

This page groups architecture notes for the in-house ``flow/boussinesq``
solver family.

Architecture Reading Order
--------------------------

.. toctree::
   :maxdepth: 1

   ../boussinesq-uml-diagrams
   ../boussinesq-mathematical-notes

Code-Level Split
----------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Package area
     - Role
   * - ``hydromodpy.solver.boussinesq.adapters``
     - Process/solver adapter for ``flow/boussinesq``.
   * - ``hydromodpy.solver.boussinesq.assembly``
     - Residual, flux, boundary, and surface-interaction assembly.
   * - ``hydromodpy.solver.boussinesq.runtimes``
     - Local, SciPy, sparse, and PETSc runtime implementations.
   * - ``hydromodpy.solver.boussinesq.extractors``
     - Output ingestion into the result/catalog layer.

Related Scientific Pages
------------------------

- :doc:`../../../scientific/solvers/flow/boussinesq-family`
- :doc:`../process-solver-registry`
