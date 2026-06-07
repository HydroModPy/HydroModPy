Mesh Quality And Acceptance Criteria
====================================

Purpose
-------

This page explains what HydroModPy users should check before interpreting a
solve on one support as a scientific result.

The main idea is simple:

- mesh or grid quality is not one cosmetic score,
- and one failed support can dominate the error budget before backend choice,
  storage law, or forcing details matter.

Two Different QA Families
-------------------------

HydroModPy uses two broad support families that fail in different ways.

Structured grids
^^^^^^^^^^^^^^^^

Typical risks are:

- stair-stepped boundaries,
- poor alignment with rivers or geology interfaces,
- overly coarse representation of narrow features,
- strong mixing of several materials inside the same cell.

Irregular planar meshes
^^^^^^^^^^^^^^^^^^^^^^^

Typical risks are:

- sliver elements,
- abrupt resolution jumps,
- poor angle quality,
- non-orthogonality effects that increase sensitivity to flux discretization,
- overly distorted cells near key boundaries.

This is why HydroModPy should not collapse all QA into one universal threshold.

Minimum Checks Before Solving
-----------------------------

Regardless of backend, the support should pass at least these questions:

- Is the domain thickness physically valid everywhere on active cells?
- Does the support honour the intended outer boundary?
- Are the main hydrographic or geological constraints represented explicitly?
- Is the resolution appropriate where observables or strong gradients are
  expected?
- Are there visibly pathological cells or resolution jumps?
- Is the support identical across runs if the goal is solver comparison?

For comparison workflows, the last question is often the most important one.

Structured Grid Acceptance Questions
------------------------------------

A structured grid is usually acceptable when:

- its resolution is fine enough that stair-stepping is not the dominant source
  of discrepancy,
- key interfaces are not systematically smeared across a few cells,
- the grid is reused consistently across the runs that are being compared,
- raster-to-grid transfer does not introduce obvious geometric contradictions.

The main point is not perfection. It is knowing whether the grid is faithful
enough for the scientific question being asked.

Irregular Mesh Acceptance Questions
-----------------------------------

An irregular mesh is usually acceptable when:

- element shapes stay within a reasonable quality envelope,
- there are no obvious slivers controlling the solution locally,
- refinement transitions remain progressive,
- the mesh follows the constraints it was meant to honour,
- method choices such as XT3D are reported when they are needed because of
  geometry.

On that kind of support, geometry and numerical method become tightly coupled.

Why Comparison Workflows Need Extra Care
----------------------------------------

In HydroModPy, comparison workflows are strongest when support equality is
controlled explicitly.

If two runs use:

- the same saved support,
- the same observables,
- and the same physical payload,

then the remaining differences are much easier to attribute to backend or
method choices.

If the support changes between candidates, the workflow may still be useful,
but the interpretation shifts from "backend comparison" toward "combined
discretization and backend comparison".

Evidence Already Available In The Repository
--------------------------------------------

One useful public anchor is the capability-gallery case:

- :doc:`../../capability_gallery/cases/mesh_quality_diagnostics_naizin_10km2`

That page is valuable because it shows how HydroModPy can expose:

- triangle-shape diagnostics,
- percentile-style summaries,
- compact figures that can be reused in documentation without re-running the
  full mesh pipeline.

What Should Be Reported
-----------------------

When a study depends on mesh choice, the report should state:

- which support family is used,
- how the support was generated or loaded,
- whether support equality was preserved across compared runs,
- which quality diagnostics were checked,
- and whether the main remaining risk is geometric fidelity or backend method.

Related Pages
-------------

- :doc:`mesh-and-discretization-strategies`
- :doc:`field-to-cell-parameter-transfer`
- :doc:`xt3d-on-irregular-disv-meshes`
- :doc:`../../user_guide/concepts/comparison-workflow`

Current Limitation
------------------

HydroModPy still lacks one canonical public threshold table for all support
families. For now, the safer scientific position is to document the diagnostics
used and the failure modes ruled out, rather than pretending one scalar
"quality score" is enough.
