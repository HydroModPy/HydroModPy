Process/Solver Taxonomy
=======================

This page separates three concepts that are easy to mix:

- **process**: the physical or operational problem being executed,
- **solver**: the numerical or executable implementation for that process,
- **backend family**: the software ecosystem or mathematical lineage behind
  one or more solvers.

The taxonomy is deliberately extensible. It is intended to cover existing
``flow`` and ``transport`` processes, but also future process families such as
heat transport, reactive transport, recharge generation, metrics, or reporting.

Axes Of Classification
----------------------

.. list-table::
   :header-rows: 1
   :widths: 22 38 40

   * - Axis
     - Question answered
     - Examples
   * - Process type
     - What problem is being solved or executed?
     - ``flow``, ``transport``, ``postprocess``, ``display``.
   * - Solver name
     - Which implementation executes that process?
     - ``modflow6``, ``boussinesq``, ``modpath``, ``mt3dms``.
   * - Backend family
     - Which scientific or software family does the implementation belong to?
     - MODFLOW family, in-house Boussinesq, output-analysis adapters.
   * - Support contract
     - What mesh, domain, forcing, and upstream outputs are required?
     - Structured grid, DISV mesh, triangular mesh, earlier flow model.
   * - Output contract
     - What primary variables are produced?
     - Heads, budgets, pathlines, concentrations, figures, reports.

Process-First Taxonomy
----------------------

.. list-table::
   :header-rows: 1
   :widths: 18 22 24 36

   * - Process
     - Scientific object
     - Current solvers
     - Primary outputs
   * - ``flow``
     - Groundwater-flow state and exchanges.
     - ``modflownwt``, ``modflow6``, ``boussinesq``
     - Hydraulic head, groundwater storage, boundary exchanges, flow budgets.
   * - ``transport``
     - Particle movement or solute concentration driven by flow.
     - ``modpath``, ``mt3dms``, ``modflow6gwt``
     - Pathlines, endpoints, concentrations, species-specific derived fields.
   * - ``postprocess``
     - Derived products computed after a run.
     - ``timeseries``, ``netcdf`` stubs.
     - Time series, exports, aggregated metrics.
   * - ``display``
     - Visual representation of stored model outputs.
     - ``flow``, ``transport`` stubs.
     - Figures, maps, report-ready artifacts.

Backend-Family Taxonomy
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 24 34 42

   * - Backend family
     - Included solver names
     - Scientific interpretation
   * - MODFLOW-NWT family
     - ``flow/modflownwt``, ``transport/modpath``, ``transport/mt3dms``
     - Legacy structured-grid groundwater-flow ecosystem with linked particle
       tracking and concentration-transport tools.
   * - MODFLOW 6 family
     - ``flow/modflow6``, ``transport/modflow6gwt``
     - Modern MODFLOW groundwater-flow and transport ecosystem, including
       runtime unstructured mesh paths where supported.
   * - Boussinesq family
     - ``flow/boussinesq``
     - In-house finite-volume shallow-groundwater formulation with explicit
       Boussinesq assumptions and surface-interaction closures.
   * - Analysis and display adapters
     - ``postprocess/*``, ``display/*``
     - Executable workflow stages that consume model outputs; not themselves
       groundwater governing-equation solvers.

Dependency Taxonomy
-------------------

Some processes can run directly from domain, mesh, parameters, and forcing.
Others require earlier process outputs.

.. list-table::
   :header-rows: 1
   :widths: 28 36 36

   * - Dependency class
     - Meaning
     - Current examples
   * - Standalone numerical process
     - Can be planned without another process result, although it still needs
       project/domain/mesh/forcing inputs.
     - ``flow/modflownwt``, ``flow/modflow6``, ``flow/boussinesq``.
   * - Downstream physical process
     - Requires a previous compatible physical process output.
     - ``transport/modpath`` and ``transport/mt3dms`` require
       ``flow/modflownwt``; ``transport/modflow6gwt`` requires
       ``flow/modflow6``.
   * - Derived analysis process
     - Requires stored outputs or a completed catalog.
     - Future ``postprocess`` and ``metrics`` adapters.
   * - Presentation process
     - Requires analysis-ready outputs rather than raw forcing inputs.
     - Future concrete ``display`` or ``report`` adapters.

Generalization Rules
--------------------

When a new solver is documented, classify it on all axes:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Question
     - Required documentation answer
   * - What is the process type?
     - The public name that appears in ``[[simulation.process]].type``.
   * - What is the solver name?
     - The public name that appears in ``solvers = [...]``.
   * - What backend family does it belong to?
     - MODFLOW, Boussinesq, hydrological model, analysis adapter, display
       adapter, or another explicit family.
   * - What does it require?
     - Mesh type, domain fields, forcing, parameters, and upstream process
       outputs.
   * - What does it produce?
     - Primary variables, derived outputs, catalog entries, and raw files.
   * - What is its maturity?
     - Production path, validation path, experimental path, or stub.

This keeps the documentation stable even as new process families are added.
The navigation can grow by adding a process row and solver rows without
rewriting the whole solver section.

Related Pages
-------------

- :doc:`flow/index`
- :doc:`transport/index`
- :doc:`workflow-stages/index`
- :doc:`solver-capability-matrix`
- :doc:`../../user_guide/solver-process-map`
- :doc:`../../architecture/solver/process-solver-registry`
