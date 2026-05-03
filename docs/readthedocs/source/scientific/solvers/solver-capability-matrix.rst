Solver Capability Matrix
========================

Purpose
-------

This page is meant to become the compact comparison sheet that answers:

"Which backend should I use for which kind of HydroModPy problem, and how well
is that path currently documented and validated?"

Current Backend Matrix
----------------------

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
     - :doc:`boussinesq-mathematical-notes` plus
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
     - :doc:`boussinesq-mathematical-notes`
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
