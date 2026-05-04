Boussinesq Flow Family
======================

This page groups the scientific notes for the in-house ``flow/boussinesq``
solver family.

The Boussinesq route is not a MODFLOW wrapper. It is a HydroModPy-native
finite-volume shallow-groundwater formulation on triangular runtime meshes.

Current Scope
-------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Topic
     - Current interpretation
   * - Process pair
     - ``flow/boussinesq``.
   * - Mesh support
     - Triangular runtime meshes.
   * - Regimes
     - Steady and transient paths exist.
   * - Main outputs
     - Hydraulic head and groundwater/surface-interaction terms.
   * - Maturity
     - Active validation path; use comparison and validation pages before
       making production claims.

Internal Structure
------------------

The detailed Boussinesq navigation is now organized under:

.. toctree::
   :maxdepth: 2

   boussinesq/index

Quick Reading Order
-------------------

If you do not know where to start, read the internal pages in this order:

1. :doc:`boussinesq/equation-and-unknowns`,
2. :doc:`boussinesq/boussinesq-method`,
3. :doc:`boussinesq/surface-interaction`,
4. :doc:`boussinesq/lower-obstacle-drying`,
5. :doc:`boussinesq/formulation-comparison`,
6. :doc:`boussinesq/solver-engines`,
7. :doc:`boussinesq/possibility-map`.

Current Possibilities
---------------------

.. list-table::
   :header-rows: 1
   :widths: 28 34 38

   * - Possibility
     - Main choice
     - When to use it
   * - Head-only baseline
     - ``regularized_partition`` surface closure with ``local``, ``scipy``,
       ``scipy_sparse`` or ``petsc``.
     - Validation, cross-platform studies, and comparison against historical
       Boussinesq outputs.
   * - Sparse cross-platform route
     - ``scipy_sparse`` on the head-only regularized method.
     - Larger triangular meshes when PETSc is not required.
   * - PETSc partition route
     - ``petsc`` on the head-only regularized method.
     - Linux/PETSc sparse baseline.
   * - PETSc complementarity route
     - ``petsc`` with ``complementarity`` surface closure.
     - Explicit on/off surface-threshold behavior and saturation-excess
       diagnostics, with a lower drying obstacle in the mixed PETSc runtime.
   * - Formulation comparison route
     - ``workflow = "comparison"`` with Boussinesq-only child overlays.
     - Document surface-closure and runtime sensitivity close to the
       Boussinesq method pages while keeping result production centralized.

Direct Reference Note
---------------------

.. toctree::
   :caption: Direct note links
   :maxdepth: 1

   ../boussinesq-mathematical-notes

Use this page together with the shared flow-numerics section when the question
is about mesh support, parameter transfer, or vertical representation.

Related Architecture
--------------------

- :doc:`../../../architecture/solver/index`
- :doc:`../../../architecture/solver/boussinesq-uml-diagrams`
