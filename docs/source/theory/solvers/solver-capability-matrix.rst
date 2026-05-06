Solver Capability Matrix
========================

Purpose
-------

This page is meant to become the compact comparison sheet that answers:

"Which backend should I use for which kind of HydroModPy problem, and how well
is that path currently documented and validated?"

The first selection axis is now the process type. Backend-family comparisons
remain useful, but they should not hide the distinction between ``flow``,
``transport``, ``postprocess``, and ``display``.

Axis-level capability snapshot
------------------------------

Compact matrix scanned in seconds. ``yes`` means a public path exists,
``partial`` means the code surface exists but the docs or validation
coverage is still incomplete, ``no`` means the feature is not exposed.

.. list-table::
   :header-rows: 1
   :widths: 14 9 13 11 13 8 8 8 16

   * - Backend
     - Steady
     - Transient
     - Unstructured mesh
     - Transport
     - Calibration
     - 1D
     - 2D
     - 3D
   * - ``modflownwt``
     - yes
     - yes
     - no
     - via MT3DMS
     - yes
     - yes
     - yes
     - yes
   * - ``modflow6``
     - yes
     - yes
     - yes (DISV)
     - yes (GWT)
     - yes
     - yes
     - yes
     - yes
   * - ``boussinesq``
     - yes
     - yes
     - yes (triangular)
     - no
     - partial
     - yes
     - yes
     - no
   * - ``gr4j``
     - yes
     - yes
     - n/a (lumped)
     - no
     - yes
     - n/a
     - n/a
     - n/a

The columns above are the recommended decision axes when scoping a new
study. For richer context, read each backend row in
:ref:`Process-Level Matrix <process-level-matrix>` below.

Visual Anchors
--------------

The matrix below is easier to read if each solver family is connected to a
real result artifact. These figures are representative anchors, not exhaustive
capability claims.

.. tab-set::

   .. tab-item:: MODFLOW 6 basin run

      .. figure:: /_static/capability_gallery/simulation/headwater_100km2_outlet_2_mf6_transient_reference_flow_state_triptych.png
         :alt: MODFLOW 6 transient basin flow-state triptych
         :width: 100%

         A modern MODFLOW 6 run can publish basin-scale state fields such as
         topography, hydraulic head, and water-table depth.

   .. tab-item:: MODFLOW-NWT basin run

      .. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_water_budget.png
         :alt: Water budget from the Nancon transient MODFLOW-NWT run
         :width: 100%

         The NWT path remains useful for structured legacy-style simulations
         where budgets, heads, and hydrographs can be read with established
         MODFLOW conventions.

   .. tab-item:: Boussinesq validation run

      .. figure:: /_static/capability_gallery/validation/boussinesq_hillslope_recharge_step_interception_1d__boussinesq.png
         :alt: Boussinesq hillslope recharge-step interception validation result
         :width: 100%

         The in-house Boussinesq backend is best read through controlled
         validation figures before broad production claims are made.

.. _process-level-matrix:

Process-Level Matrix
--------------------

.. list-table::
   :header-rows: 1
   :widths: 16 16 12 24 18 22

   * - Backend
     - Mesh support
     - Regimes
     - Main scientific role
     - Validation anchor
     - Current main limits
   * - ``modflownwt``
     - Structured ``sgrid``
     - Steady and transient
     - Legacy MODFLOW-family flow path, still important for comparison,
       MODPATH, and MT3DMS workflows
     - ``validation_cases/README.md`` plus
       :doc:`../../architecture/solver/modflownwt-architecture-notes`
     - No runtime Gmsh mesh path, scientific method note still missing, sunset
       strategy not yet fully reflected in user-facing docs
   * - ``modflow6``
     - Structured plus runtime DISV-style unstructured meshes
     - Steady and transient
     - Modern MODFLOW-family backend for flow, with irregular-mesh support and
       growing method-choice documentation
     - XT3D method-choice assets plus
       :doc:`../../architecture/solver/modflow6-architecture-notes`
     - Scientific note still incomplete on package choices, vertical
       assumptions, and when to prefer it over NWT
   * - ``boussinesq``
     - Triangular runtime meshes
     - Steady and transient
     - In-house finite-volume shallow-groundwater backend with explicit
       groundwater/surface-interaction formulations
     - :doc:`../boussinesq` plus
       ``validation_cases/README.md``
     - Still under active validation, not yet documented as a fully mature
       production envelope for all workflows

Documentation Maturity Matrix
-----------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 18 30 24

   * - Topic
     - Current maturity
     - Best current source
     - Main gap
   * - Project-level scientific scope
     - Low
     - :doc:`../foundations/system-scope-and-assumptions`
     - Still a scaffold, not yet a complete physical framing page
   * - Solver-agnostic groundwater problem
     - Low to medium
     - ``hydromodpy.physics.flow`` plus
       :doc:`../foundations/groundwater-flow-problem-definition`
     - Scientific contract still implicit in code
   * - Hydrological forcing chain
     - Low
     - ``hydromodpy.physics.forcing`` and ``pyhelp``
     - No canonical scientific page on recharge-generation and forcing
       semantics
   * - MODFLOW-family scientific choices
     - Medium
     - :doc:`modflow-governing-equation-and-cvfd-formulation`,
       :doc:`modflow6-vs-modflownwt-scientific-comparison`,
       XT3D note, architecture pages
     - Core rationale now exists publicly, but package-level and forcing-level
       synthesis still remains dispersed
   * - Boussinesq mathematical formulation
     - Medium to high
     - :doc:`../boussinesq`
     - Good core note, but backend envelope and comparison guidance still need
       consolidation

How This Page Should Be Used
----------------------------

This matrix should later serve three different audiences:

- contributors choosing where to add documentation next,
- users choosing a backend for a new study,
- reviewers checking whether a modelling path is both implemented and justified.

Immediate Next Additions Recommended
------------------------------------

The next high-value additions to this page would be:

1. one row-level capability breakdown for boundary conditions and forcing
   families,
2. one explicit column for mesh topology and vertical representation,
3. one column for transport compatibility,
4. one column for documentation confidence versus validation confidence.
