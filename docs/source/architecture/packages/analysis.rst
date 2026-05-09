analysis
========

``hydromodpy.analysis`` groups the cross-run analytical workflows
that consume the catalog: regional batches over many sites,
shared-case simulation comparison, controlled testbed variants, and
stream-network metrics.

Sub-modules
-----------

- ``analysis/batch/`` -- regional lab. Plans multi-site campaigns
  (``RegionalLabSiteRecord``), executes them, ingests outputs,
  reports site-level metrics.
- ``analysis/comparison/`` -- pairwise and N-way simulation
  comparison. Computes diff and stability metrics, renders maps and
  series, emits the comparison HTML report.
- ``analysis/testbed/`` -- controlled-variant matrix
  (mesh / flow). Generates child overlay configs, runs them, and
  collects evidence (plan, cases, metrics CSV).
- ``analysis/stream_networks/`` -- planar bidirectional distance
  metrics, simulated-vs-reference overlap, and active-network
  metrics consumed by the comparison and the ``Run`` facade.
- ``analysis/config.py`` -- ``AnalysisConfig`` Pydantic root for
  the ``[analysis]`` TOML section
  (``analysis.batch``, ``analysis.capability_gallery``,
  ``analysis.comparison``).

Workflow placement
------------------

Each analysis subsystem is reachable through:

- The CLI: ``hmp run`` dispatches on ``[workflow].mode = "batch"``
  or ``"comparison"`` or ``"testbed"`` and routes to the matching
  launcher under ``analysis/``.
- The Python facade:
  ``Project.batch()`` / ``Project.compare()`` /
  ``Project.testbed()``.
- Direct primitives under ``analysis/<subsystem>/`` for embedding
  inside another analysis loop.

Key public symbols
------------------

- ``hydromodpy.analysis.batch.{RegionalLabSiteRecord, batch_planning,
  batch_execution, batch_catalog, batch_reporting}``
- ``hydromodpy.analysis.comparison.{audit, dispatch,
  child_materialization, web_report}``
- ``hydromodpy.analysis.testbed.{plan, cases, metrics}``
- ``hydromodpy.analysis.stream_networks`` (overlap and distance
  metrics).
- ``hydromodpy.analysis.config.AnalysisConfig``

Recommended reading path
------------------------

1. ``hydromodpy/analysis/__init__.py`` for the public surface.
2. ``hydromodpy/analysis/testbed/README.md`` for the testbed
   contract.
3. ``hydromodpy/analysis/comparison/__init__.py`` for the comparison
   pipeline.
4. ``hydromodpy/analysis/batch/__init__.py`` for the regional lab.
5. ``hydromodpy/analysis/stream_networks/__init__.py`` for the
   geometric metrics.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``data``, ``results``,
  ``analysis``.
- Documented tolerances: ``analysis`` -> ``physics`` (history
  contract), ``analysis`` -> ``display`` (comparison exports
  reuse plot mesh loading), ``analysis`` -> ``solver``
  (comparison runtime resolves solver families).
- Allowed sources: ``results`` (``Run`` exposes stream-network
  diagnostics, documented tolerance), ``workflow``, ``cli``.

See also
--------

- :doc:`/architecture/simulation/comparison-workflow` for the
  shared-case comparison contract.
- :doc:`/architecture/overview/testbed-workflow-architecture` for
  the testbed pipeline.
- :doc:`/user_guide/comparison` -- user-facing hub.
- :doc:`/user_guide/workflows/batch` -- batch workflow page.
- :doc:`/user_guide/workflows/testbed` -- testbed workflow page.
