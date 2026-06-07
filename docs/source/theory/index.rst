:html_theme.sidebar_secondary.remove:

Theory
======

.. raw:: html

   <p class="lead">
   Method-focused notes that explain the scientific models implemented in
   HydroModPy: physical scope, governing equations, hydrology and recharge
   chains, mesh and discretization rationale, solver formulations, and the
   inverse problem behind calibration.
   </p>

.. admonition:: How to read this section
   :class: tip

   This is the **what** and **why** layer. For **how to drive** the
   software, open :doc:`/user_guide/workflows/index`. For **how the code is
   organized**, open :doc:`/architecture/index`. For **stable result
   figures**, open :doc:`/capability_gallery/index`.

Sections
--------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: Foundations
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: foundations/index
      :link-type: doc

      What physical system HydroModPy represents, the modelling
      assumptions shared across workflows, and the solver-agnostic
      groundwater problem.

   .. grid-item-card:: Hydrology and forcing
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: hydrology/index
      :link-type: doc

      Recharge generation, PyHELP coupling, runoff and ETP chains,
      time aggregation, plus the semantics of streams, ocean, and
      drainage at the groundwater interface.

   .. grid-item-card:: Mesh and spatial support
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: mesh/index
      :link-type: doc

      Why mesh choice is a modelling decision: structured grids,
      runtime DISV, triangular meshes, field-to-cell projection,
      quality criteria, and acceptance rules.

   .. grid-item-card:: Solvers
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: solvers/index
      :link-type: doc

      MODFLOW family (NWT and 6), shared numerical concepts, package
      semantics, XT3D, vertical representation, transport coupling,
      and worked cases.

   .. grid-item-card:: Boussinesq
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: boussinesq
      :link-type: doc

      The in-house finite-volume shallow-groundwater backend on
      triangular runtime meshes: equation, surface interaction,
      lower-obstacle drying, solver engines, and possibility map.

   .. grid-item-card:: Streams and seepage
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: streams_and_seepage/index
      :link-type: doc

      Stream support, simulated active networks, seepage and drainage
      operators, with K-sweep diagnostics and network metrics on the
      Nancon basin.

   .. grid-item-card:: Calibration
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: calibration/index
      :link-type: doc

      Inverse-problem formulation, objective construction, and the
      numerical behaviour of each calibration method shipped in
      ``hydromodpy.calibration``.

   .. grid-item-card:: Notation and references
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: notation
      :link-type: doc

      Symbol tables with SI units and cross-references, plus the
      complete bibliography that backs the theory pages.

Where to start
--------------

If you are not sure where to enter, this is a sensible reading order:

1. :doc:`foundations/index` to see what physical system the toolbox
   actually models.
2. :doc:`mesh/index` because mesh choice constrains everything downstream.
3. :doc:`solvers/index` for the MODFLOW family, then :doc:`boussinesq`
   if the in-house formulation is in scope.
4. :doc:`hydrology/index` for forcing chains and surface coupling.
5. :doc:`calibration/index` once forward simulations are clear.

.. toctree::
   :hidden:
   :maxdepth: 2

   Foundations <foundations/index>
   Hydrology <hydrology/index>
   Mesh <mesh/index>
   Solvers <solvers/index>
   Boussinesq <boussinesq>
   Streams and seepage <streams_and_seepage/index>
   Calibration <calibration/index>
   Notation <notation>
   Bibliography <bibliography>
