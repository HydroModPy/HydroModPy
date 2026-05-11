Scientific Foundations
======================

.. raw:: html

   <p class="lead">
   The high-level scientific entry point: what physical system HydroModPy
   models, the assumptions shared across every workflow, and the
   solver-agnostic form of the groundwater problem before backend
   translation.
   </p>

Use this section before reading any solver-specific page. It defines the
common vocabulary that the rest of the theory documentation assumes.

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: System scope and assumptions
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: system-scope-and-assumptions
      :link-type: doc

      What HydroModPy claims to represent and what it deliberately
      leaves out: shallow unconfined aquifers, catchment scale,
      decoupling from atmospheric and subsurface processes outside
      the project scope.

   .. grid-item-card:: Groundwater flow problem definition
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: groundwater-flow-problem-definition
      :link-type: doc

      The solver-agnostic statement of the problem: state variable,
      governing equation, boundary conditions, forcing terms, and
      the regime split (steady versus transient).

See also
--------

- :doc:`/theory/notation` for the symbol table and units.
- :doc:`/theory/mesh/index` to see how the problem becomes a
  discrete one once the support is chosen.
- :doc:`/theory/solvers/index` for backend-specific interpretations
  of the equations defined here.

.. toctree::
   :hidden:
   :maxdepth: 1

   system-scope-and-assumptions
   groundwater-flow-problem-definition
