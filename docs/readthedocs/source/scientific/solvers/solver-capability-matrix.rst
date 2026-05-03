Solver Capability Matrix
========================

Purpose
-------

This page is the compact comparison sheet that answers:

"Which process/solver pair should I use for which kind of HydroModPy problem,
and how well is that path currently documented and validated?"

The first selection axis is now the process type. Backend-family comparisons
remain useful, but they should not hide the distinction between ``flow``,
``transport``, ``postprocess``, and ``display``.

Process-Level Matrix
--------------------

.. list-table::
   :header-rows: 1
   :widths: 16 26 26 16 16

   * - Process
     - Main question
     - Current solver names
     - Maturity
     - Main dependency
   * - ``flow``
     - What are the hydraulic heads, exchanges, and water-budget terms?
     - ``modflownwt``, ``modflow6``, ``boussinesq``
     - Active
     - Domain, mesh, flow parameters, forcing.
   * - ``transport``
     - Where do particles or concentrations move once flow has been solved?
     - ``modpath``, ``mt3dms``, ``modflow6gwt``
     - Active
     - A compatible earlier ``flow`` run.
   * - ``postprocess``
     - Which secondary products should be derived after execution?
     - ``timeseries``, ``netcdf``
     - Stub
     - Completed simulation outputs.
   * - ``display``
     - Which figures or report artifacts should be generated?
     - ``flow``, ``transport``
     - Stub
     - Catalog outputs or postprocessed products.

Flow Solver Matrix
------------------

.. list-table::
   :header-rows: 1
   :widths: 15 18 14 25 14 14

   * - Solver
     - Mesh support
     - Regimes
     - Main scientific role
     - Validation anchor
     - Current main limits
   * - ``modflownwt``
     - Structured ``sgrid``.
     - Steady and transient.
     - Legacy MODFLOW-family flow path, still important for comparison,
       MODPATH, and MT3DMS workflows.
     - ``validation_cases/README.md`` plus
       :doc:`../../architecture/solver/modflownwt-architecture-notes`.
     - No runtime Gmsh mesh path; public scientific note exists, but
       end-to-end case documentation and sunset strategy remain incomplete.
   * - ``modflow6``
     - Structured grids plus runtime DISV-style unstructured meshes.
     - Steady and transient.
     - Modern MODFLOW-family backend for flow, with irregular-mesh support and
       growing method-choice documentation.
     - XT3D method-choice assets plus
       :doc:`../../architecture/solver/modflow6-architecture-notes`.
     - Public rationale exists for package choices and backend selection, but
       worked case documentation and the maintained package envelope still
       need tightening.
   * - ``boussinesq``
     - Triangular runtime meshes.
     - Steady and transient.
     - In-house finite-volume shallow-groundwater backend with explicit
       groundwater/surface-interaction formulations.
     - :doc:`boussinesq-mathematical-notes` plus
       ``validation_cases/README.md``.
     - Still under active validation, not yet documented as a fully mature
       production envelope for all workflows.

Transport Solver Matrix
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 16 22 22 22 18

   * - Solver
     - Transport role
     - Required flow solver
     - Key parameters
     - Current main limits
   * - ``modpath``
     - Particle tracking.
     - ``flow/modflownwt``.
     - ``zone_partic``, ``track_dir``, ``cell_div``, ``zloc_div``.
     - Depends on the MODFLOW-NWT path; no MODFLOW 6 flow dependency in the
       current registry.
   * - ``mt3dms``
     - Concentration transport.
     - ``flow/modflownwt``.
     - ``spc_name``, ``sconc_init``, ``sconc_input``, ``disp_long``,
       ``rate_decay``.
     - Depends on the MODFLOW-NWT path; solver assumptions and worked examples
       need fuller user-facing documentation.
   * - ``modflow6gwt``
     - Concentration transport.
     - ``flow/modflow6``.
     - Same concentration parameter family as ``mt3dms``.
     - Modern path exists in code, but needs more curated examples and
       validation pages.

Backend-Family Matrix
---------------------

.. list-table::
   :header-rows: 1
   :widths: 22 34 24 20

   * - Family
     - Process/solver pairs
     - Strength
     - Main caution
   * - MODFLOW-NWT ecosystem
     - ``flow/modflownwt``, ``transport/modpath``, ``transport/mt3dms``.
     - Historical continuity and linked particle/concentration tools.
     - Structured-grid path only.
   * - MODFLOW 6 ecosystem
     - ``flow/modflow6``, ``transport/modflow6gwt``.
     - Modern MODFLOW flow and transport stack, including irregular mesh paths
       where supported.
     - More package-envelope and worked-case documentation still needed.
   * - Boussinesq in-house ecosystem
     - ``flow/boussinesq``.
     - Direct access to HydroModPy-specific finite-volume formulations and
       surface-interaction choices.
     - Active validation path; use carefully for production claims.
   * - Workflow-stage adapters
     - ``postprocess/*``, ``display/*``.
     - Keeps analysis and presentation stages compatible with the same
       planner model.
     - Current entries are stubs rather than production executors.

Documentation Maturity Matrix
-----------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 18 30 24

   * - Topic
     - Current maturity
     - Best current source
     - Main gap
   * - Process/solver taxonomy
     - Medium
     - :doc:`process-solver-taxonomy`,
       :doc:`../../user_guide/solver-process-map`
     - Needs to be kept synchronized when new process families are added.
   * - Project-level scientific scope
     - Low
     - :doc:`../foundations/system-scope-and-assumptions`
     - Still a scaffold, not yet a complete physical framing page.
   * - Solver-agnostic groundwater problem
     - Low to medium
     - ``hydromodpy.physics.flow`` plus
       :doc:`../foundations/groundwater-flow-problem-definition`
     - Scientific contract still partly implicit in code.
   * - Hydrological forcing chain
     - Medium
     - :doc:`../hydrology/hydrological-forcing-chain`,
       :doc:`../hydrology/forcing-time-aggregation-and-first-clim`
     - Still needs more worked examples and fuller recharge-generation
       coverage.
   * - MODFLOW-family scientific choices
     - Medium
     - :doc:`modflow-governing-equation-and-cvfd-formulation`,
       :doc:`modflow6-vs-modflownwt-scientific-comparison`,
       :doc:`xt3d-on-irregular-disv-meshes`,
       architecture pages.
     - Core rationale exists publicly, but package-level and forcing-level
       synthesis still remains dispersed.
   * - Boussinesq mathematical formulation
     - Medium to high
     - :doc:`boussinesq-mathematical-notes`
     - Good core note, but backend envelope and comparison guidance still need
       consolidation.
   * - Transport solvers
     - Low to medium
     - :doc:`../../user_guide/solver-process-map`,
       :doc:`../../architecture/solver/process-solver-registry`
     - Needs fuller scientific pages for particle tracking, concentration
       transport, and MODFLOW 6 GWT assumptions.

How This Page Should Be Used
----------------------------

Use this matrix for three audiences:

- users choosing a process/solver pair for a new study,
- contributors deciding where a new solver or adapter belongs,
- reviewers checking whether a modelling path is both implemented and
  scientifically documented.

Process Pages
-------------

- :doc:`flow/index` groups ``flow`` solvers by MODFLOW family, Boussinesq
  family, and shared numerical support.
- :doc:`transport/index` groups ``transport`` solvers by particle tracking and
  concentration transport.
- :doc:`workflow-stages/index` groups non-numerical registry-backed stages such
  as postprocess and display adapters.

Immediate Next Additions Recommended
------------------------------------

The next high-value additions to this page would be:

1. one boundary-condition and forcing-compatibility matrix per ``flow`` solver,
2. one explicit transport-assumption page for ``modpath``, ``mt3dms``, and
   ``modflow6gwt``,
3. one mesh topology and vertical-representation column for transport solvers,
4. one documentation-confidence versus validation-confidence column.
