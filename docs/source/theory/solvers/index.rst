Solvers
=======

.. raw:: html

   <p class="lead">
   Scientific content behind the HydroModPy solver layer. Focuses on what
   each solver represents mathematically and which numerical choices are
   active, not on the runtime orchestration.
   </p>

.. admonition:: Operational pages live elsewhere
   :class: tip

   For backend selection and TOML snippets, see
   :doc:`/user_guide/solvers`. For the package layout and runtime
   handoff, see :doc:`/architecture/solver/index`. The in-house
   Boussinesq theory is in :doc:`/theory/boussinesq`.

MODFLOW family
--------------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: MODFLOW flow family overview
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: flow/modflow-family
      :link-type: doc

      Reading map for MODFLOW 6 and MODFLOW-NWT in HydroModPy:
      common contract, backend split, comparison discipline, and
      version-specific emphasis.

   .. grid-item-card:: Governing equation and CVFD formulation
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: modflow-governing-equation-and-cvfd-formulation
      :link-type: doc

      Cell-by-cell groundwater balance, control-volume finite
      difference statement, sign conventions, and the relationship
      to the solver-agnostic problem.

   .. grid-item-card:: Package semantics and boundary conditions
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: modflow-package-semantics-and-boundary-conditions
      :link-type: doc

      How HydroModPy maps the ``[flow]`` payload to NPF, STO, RCHA,
      WEL, CHD, DRN, and EVT packages, with version differences
      flagged explicitly.

   .. grid-item-card:: MODFLOW 6 vs MODFLOW-NWT
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: modflow6-vs-modflownwt-scientific-comparison
      :link-type: doc

      Scientific contrast of the two MODFLOW backends: support,
      solver settings, package coverage, transport coupling, and
      reasons to keep both alive.

   .. grid-item-card:: XT3D on irregular DISV meshes
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: xt3d-on-irregular-disv-meshes
      :link-type: doc

      Why XT3D matters when a DISV-style mesh leaves the
      strictly-orthogonal regime, with the method-choice evidence
      published in the gallery.

   .. grid-item-card:: MODFLOW 6 flow page
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: flow/modflow/modflow6
      :link-type: doc

      MODFLOW 6-specific notes for ``flow/modflow6``: structured and
      runtime DISV support, XT3D policy, and the GWT downstream
      route.

   .. grid-item-card:: MODFLOW-NWT flow page
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: flow/modflow/modflownwt
      :link-type: doc

      MODFLOW-NWT-specific notes for ``flow/modflownwt``: legacy
      structured ``sgrid`` continuity, MODPATH and MT3DMS
      compatibility.

   .. grid-item-card:: Comparison and method choice
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: flow/modflow/comparison-and-method-choice
      :link-type: doc

      Checklist to follow before attributing a difference between
      ``flow/modflow6`` and ``flow/modflownwt`` to the numerical
      backend.

Mesh and discretization
-----------------------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: Mesh and discretization strategies
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: mesh-and-discretization-strategies
      :link-type: doc

      The separation between physical problem, planar support,
      vertical layering, and solver-specific cell interpretation.

   .. grid-item-card:: Field-to-cell parameter transfer
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: field-to-cell-parameter-transfer
      :link-type: doc

      How heterogeneous fields (geology, hydraulic conductivity,
      forcing) are projected to solver cells across mesh families.

   .. grid-item-card:: Vertical representation and storage
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: vertical-representation-and-storage-assumptions
      :link-type: doc

      How vertical layering and saturated thickness assumptions
      shape storage, transmissivity, and the unconfined response.

   .. grid-item-card:: Mesh quality and acceptance
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: mesh-quality-and-acceptance-criteria
      :link-type: doc

      Quality diagnostics that decide whether a discretization is
      acceptable before solver results are trusted.

Worked cases and reference matrix
---------------------------------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: Worked MODFLOW cases
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: flow/modflow/worked-cases
      :link-type: doc

      Executable MODFLOW-family examples that link assumptions to
      TOML inputs, package assembly, and inspected outputs.

   .. grid-item-card:: Dupuit fixed-head 1D
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: worked-modflow-case-dupuit-fixed-head-1d
      :link-type: doc

      The simplest analytical-style benchmark: Dupuit unconfined
      flow against fixed-head boundaries in a 1D strip.

   .. grid-item-card:: Linearized unconfined periodic 1D
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: worked-modflow-case-linearized-unconfined-recharge-periodic-1d
      :link-type: doc

      Linearized unconfined response to a periodic recharge signal,
      with explicit comparison against the analytical solution.

   .. grid-item-card:: Nancon transient NWT
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: worked-modflow-case-nancon-transient-nwt-etp-evt
      :link-type: doc

      The Nancon basin transient MODFLOW-NWT case with ETP routed
      through the EVT package, the canonical real-basin teaching
      reference.

   .. grid-item-card:: Transport coupling
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: flow/modflow/transport-coupling
      :link-type: doc

      Which downstream transport solver consumes each MODFLOW-family
      flow field: MODFLOW 6 GWT, MODPATH, or MT3DMS.

   .. grid-item-card:: Solver capability matrix
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: solver-capability-matrix
      :link-type: doc

      Compact inventory of what each solver can represent today and
      where the active development edges sit.

.. toctree::
   :hidden:
   :maxdepth: 2

   flow/index
   mesh-and-discretization-strategies
   field-to-cell-parameter-transfer
   vertical-representation-and-storage-assumptions
   mesh-quality-and-acceptance-criteria
   modflow-governing-equation-and-cvfd-formulation
   modflow6-vs-modflownwt-scientific-comparison
   modflow-package-semantics-and-boundary-conditions
   xt3d-on-irregular-disv-meshes
   worked-modflow-case-dupuit-fixed-head-1d
   worked-modflow-case-linearized-unconfined-recharge-periodic-1d
   worked-modflow-case-nancon-transient-nwt-etp-evt
   solver-capability-matrix
