Meshes And Numerical Methods
============================

Purpose
-------

This page is not a solver manual yet. It is a structured perspective for how
the scientific documentation should grow beyond basic backend descriptions.

The main gap today is not only missing prose on MODFLOW. It is the absence of
one coherent map that separates:

- physical problem definition,
- mesh and discretization choices,
- backend-specific numerical methods,
- workflow-level comparison and validation evidence.

What Should Live Where
----------------------

The scientific documentation becomes much easier to maintain if it is split
into four layers.

Layer 1. Common scientific contract
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This layer should answer:

- what HydroModPy means by the groundwater problem,
- which unknown is solved for,
- which sign conventions are used,
- which families of parameters, sources, and sinks are canonical before any
  backend translation.

This belongs primarily in:

- :doc:`../foundations/groundwater-flow-problem-definition`
- :doc:`../hydrology/hydrological-forcing-chain`

Layer 2. Meshes and discretization
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This layer should answer:

- which mesh families HydroModPy supports,
- which geological or hydrographic constraints they try to honour,
- how field properties are projected onto cells,
- what the vertical representation means physically,
- what quality checks are required before solving.

This should become a dedicated documentation block, because mesh choice is one
of the strongest scientific and numerical decisions in the platform.

Layer 3. Backend methods
^^^^^^^^^^^^^^^^^^^^^^^^

This layer should answer:

- how the solver-agnostic ``[flow]`` payload becomes concrete equations,
- which package families or discrete operators are used,
- which options are enabled by default,
- why some backends are kept, preferred, or being sunset.

This belongs in:

- :doc:`modflow-family-methods`
- :doc:`boussinesq-mathematical-notes`

Layer 4. Evidence and controlled comparisons
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This layer should answer:

- where method choices are validated,
- where solver discrepancies are measured,
- which workflows are intended for comparison rather than production use.

This should point to:

- validation cases,
- comparison workflows,
- capability-gallery pages when available.

Proposed Mesh Documentation Block
---------------------------------

The mesh and discretization branch now separates the following public pages.

1. :doc:`mesh-and-discretization-strategies`
   Explain the supported mesh families: structured grids, DISV-style
   catchment-conformal meshes, and the triangular finite-volume mesh contract
   used by the in-house Boussinesq backend.
2. :doc:`field-to-cell-parameter-transfer`
   Explain how geology, hydraulic conductivity, recharge zones, and other
   fields move from geographic objects to solver-ready arrays or per-cell
   parameters.
3. :doc:`vertical-representation-and-storage-assumptions`
   Explain the physical meaning and limits of the current vertical
   representation across backends.
4. :doc:`mesh-quality-and-acceptance-criteria`
   Explain which metrics matter numerically and what failure modes they are
   meant to prevent.

Proposed MODFLOW Documentation Block
------------------------------------

The MODFLOW branch should become much more explicit than a backend overview.

It is now anchored by the following public pages and should keep expanding from
there:

1. one solver-agnostic governing equation statement and its MODFLOW
   interpretation,
2. :doc:`modflow-package-semantics-and-boundary-conditions`,
3. the mapping from HydroModPy concepts to package families such as ``NPF``,
   ``STO``, ``RCHA``, ``WEL``, ``CHD``, ``DRN``, ``EVT``, ``OC``, and ``IMS``,
4. the difference between structured ``DIS`` and unstructured ``DISV`` paths,
5. :doc:`xt3d-on-irregular-disv-meshes`,
6. why ``XT3D`` is enabled for irregular meshes and what trade-off that
   reflects,
7. :doc:`modflow6-vs-modflownwt-scientific-comparison`,
8. what remains easier or more stable in the legacy NWT path,
9. what the current vertical and unconfined assumptions do not represent.

Numerical Choices That Need Explicit Rationale
----------------------------------------------

Several choices should be documented as first-class scientific decisions, not
as code-level implementation details.

The main ones are:

- why hydraulic head is the canonical unknown at the HydroModPy level,
- how ``Sy`` and ``Ss`` are used and when both matter,
- how diffuse recharge differs from drainage, river exchange, wells, or
  evapotranspiration,
- how forcing time series are aggregated to stress periods,
- why structured and unstructured paths coexist,
- why solver comparison is handled as a separate workflow instead of being
  folded into standard simulation execution.

Where Workflow Pages Should Help
--------------------------------

Workflow pages should describe:

- what a workflow does,
- what artifacts it produces,
- when a user should choose it,
- which scientific pages explain the underlying methods.

Workflow pages should not become the main home for:

- governing equations,
- mesh-method rationale,
- package-level numerical explanations.

That material belongs in the scientific section and should be linked back from
workflow pages through short "method notes" subsections.

Recommended Immediate Additions
-------------------------------

The next highest-value additions after this perspective page are now:

1. one public mesh-walkthrough page,
2. one tighter public note on MODFLOW package subset and current project
   simplifications,
3. one public note on forcing-time aggregation to stress periods,
4. one comparison-reading page that turns these method notes into a strict
   interpretation checklist.

Current Best Anchors In The Repository
--------------------------------------

The material already exists in fragmented form. The most useful anchors are:

- :doc:`../../architecture/mesh/index`
- :doc:`../../architecture/solver/modflow6-architecture-notes`
- :doc:`../../architecture/solver/modflownwt-architecture-notes`
- ``docs/developers/gmsh_mesh_integration_note.md``
- ``docs/developers/modflow_contracts.md``
- ``docs/developers/modflow6_gmsh_disv_development_perspective.md``
- ``docs/developers/simulation_comparison_workflow.md``

The documentation effort should now consolidate those scattered rationales into
public scientific pages with a stable structure.
