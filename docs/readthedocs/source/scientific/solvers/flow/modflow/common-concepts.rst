Common MODFLOW Concepts
=======================

Start here when the question is not yet specific to MODFLOW 6 or MODFLOW-NWT.
These pages describe the shared scientific vocabulary used by both paths.

Core Notes
----------

.. toctree::
   :maxdepth: 1

   ../../modflow-governing-equation-and-cvfd-formulation
   ../../modflow-package-semantics-and-boundary-conditions
   ../../modflow-family-methods

What Belongs Here
-----------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Topic
     - Why it is common
   * - Governing equation
     - Both MODFLOW paths solve a groundwater-flow equation through a
       cell-based finite-volume-style discretization.
   * - Package semantics
     - HydroModPy maps flow parameters, recharge, wells, and boundary
       conditions into MODFLOW package concepts before backend-specific
       assembly.
   * - Boundary-condition mapping
     - User-facing ``[flow.bc]`` declarations need to be translated into
       package-specific inputs.
   * - Method vocabulary
     - Terms such as structured grid, DISV, XT3D, storage, recharge package,
       and stress period should be understood before comparing backends.

How To Use This Group
---------------------

Use this group before reading backend-specific pages. If a difference between
``flow/modflow6`` and ``flow/modflownwt`` appears, first check whether it comes
from a common modelling choice: support geometry, vertical representation,
forcing aggregation, or boundary-condition semantics.

Related Pages
-------------

- :doc:`comparison-and-method-choice`
- :doc:`../shared-flow-numerics`
