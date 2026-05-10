Simulation Comparison Workflow
==============================

Use this page when you want to understand why the comparison workflow is
kept separate from standard simulation and validation, and which scientific
notes matter before interpreting outputs.

For the operational steps (TOML structure, command, parameters, outputs to
inspect, stability checker), see :doc:`../workflows/comparison`. For a
strict artefact-by-artefact reading order once a comparison has been
materialized, see :doc:`comparison-output-reading-order`.

What This Workflow Is
---------------------

The comparison workflow is an external orchestration layer declared
through ``[workflow].mode = "comparison"``. It does not replace the
standard ``simulation`` workflow. Instead, it:

1. reads one comparison TOML,
2. reads one shared base simulation TOML,
3. generates child simulation TOMLs,
4. runs those children through the public HydroModPy entry point,
5. extracts observables from persisted results,
6. computes metrics, audits, and figures.

Execution Map
-------------

.. uml:: diagrams/comparison_workflow_execution.wsd

The workflow does not bypass standard simulations. It builds ordinary
child simulation configs, runs them through the public entry point, then
compares persisted outputs.

Why It Exists As A Separate Workflow
------------------------------------

Keeping comparison separate from standard simulation is a deliberate
scientific and architectural choice.

It means:

- each child run remains a real HydroModPy simulation,
- solver-to-solver comparison stays explicit instead of becoming a hidden
  side effect inside ``simulation``,
- comparison outputs are clearly post-hoc evidence products rather than
  raw simulation artifacts.

This also prevents one important confusion: a comparison workflow is not
a validation workflow.

Comparison asks:
"How different are these runs on the same declared case?"

Validation asks:
"Does this run match an analytical or trusted reference within stated
tolerances?"

Method Notes Before You Interpret Results
-----------------------------------------

The comparison workflow keeps one physical case as constant as possible,
but it does not remove the need to interpret method choices explicitly.

Before reading the output figures as "solver differences", confirm at
least the following:

- whether the child runs use the exact same support,
- whether the comparison is backend-only or also changes mesh family,
- whether XT3D is active for irregular MODFLOW 6 cases,
- whether the comparison mixes a layered MODFLOW representation with a
  reduced shallow-flow Boussinesq representation,
- whether heterogeneous properties are being transferred to cells in the
  same way for both runs.

The key scientific notes are:

- :doc:`../../theory/solvers/modflow6-vs-modflownwt-scientific-comparison`
- :doc:`../../theory/solvers/modflow-governing-equation-and-cvfd-formulation`
- :doc:`../../theory/solvers/modflow-package-semantics-and-boundary-conditions`
- :doc:`../../theory/solvers/field-to-cell-parameter-transfer`
- :doc:`../../theory/solvers/vertical-representation-and-storage-assumptions`
- :doc:`../../theory/solvers/mesh-quality-and-acceptance-criteria`
- :doc:`../../theory/solvers/xt3d-on-irregular-disv-meshes`
- :doc:`../../theory/boussinesq`
- :doc:`../../theory/hydrology/forcing-time-aggregation-and-first-clim`

Related Reading
---------------

- :doc:`../workflows/comparison` for the operational TOML structure,
  examples, outputs, and stability checker.
- :doc:`comparison-output-reading-order` for the strict reading order
  once a comparison output folder is available.
- :doc:`reading-results-pages` for the difference between gallery,
  comparison, and validation pages.
- :doc:`../../theory/solvers/meshes-and-numerical-methods` for the
  numerical-method context behind discretization choices.
