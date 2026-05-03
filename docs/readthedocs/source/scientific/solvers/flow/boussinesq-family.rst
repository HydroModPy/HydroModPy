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

Reading Order
-------------

.. toctree::
   :maxdepth: 1

   ../boussinesq-mathematical-notes

Use this page together with the shared flow-numerics section when the question
is about mesh support, parameter transfer, or vertical representation.

Related Architecture
--------------------

- :doc:`../../../architecture/solver/flow/boussinesq-family`
- :doc:`../../../architecture/solver/process-solver-registry`
