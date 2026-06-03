analysis
========

``hydromodpy.analysis`` groups the cross-run analytical workflows
that consume the catalog: shared-case simulation comparison and
controlled testbed variants (including the regional_lab profile).
HTML composites built on top of these features now live in
``hydromodpy.reporting``.

Sub-modules
-----------

- ``analysis/comparison/`` -- pairwise and N-way simulation
  comparison. Computes diff and stability metrics, renders maps and
  series, and feeds the ``reporting/comparison`` HTML composite.
- ``analysis/testbed/`` -- controlled-variant matrix
  (mesh / flow). Generates child overlay configs, runs them, and
  collects evidence (plan, cases, metrics CSV). Hosts the
  ``regional_lab`` profile that plans multi-site campaigns.
- ``analysis/capability_gallery.py`` -- gallery rendering helpers.
- ``analysis/catalog.py`` -- catalog-side analysis helpers.
- ``analysis/config.py`` -- ``AnalysisConfig`` Pydantic root for
  the ``[analysis]`` TOML section
  (``analysis.capability_gallery``, ``analysis.comparison``,
  ``analysis.testbed``).

Workflow placement
------------------

Each analysis subsystem is reachable through:

- The CLI: ``hmp run`` dispatches on ``[workflow].mode = "comparison"``
  or ``"testbed"`` and routes to the matching launcher under
  ``analysis/``. Regional campaigns use ``"testbed"`` with
  ``[testbed].profile = "regional_lab"``.
- The Python facade: ``hmp.run(toml)`` with ``[workflow].mode = "comparison"``
  or ``"testbed"``.
- Direct primitives under ``analysis/<subsystem>/`` for embedding
  inside another analysis loop.

Key public symbols
------------------

- ``hydromodpy.analysis.comparison.{audit, dispatch,
  child_materialization, reporting}``
- ``hydromodpy.analysis.testbed.{pipeline, profiles, regional_lab}``
- ``hydromodpy.analysis.config.AnalysisConfig``

Recommended reading path
------------------------

1. ``hydromodpy/analysis/__init__.py`` for the public surface.
2. ``hydromodpy/analysis/testbed/README.md`` for the testbed
   contract.
3. ``hydromodpy/analysis/comparison/__init__.py`` for the comparison
   pipeline.
4. ``hydromodpy/analysis/testbed/regional_lab.py`` for the regional
   lab profile.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``physics``, ``data``,
  ``results``, ``display``, ``analysis``.
- Documented tolerance: ``analysis`` -> ``reporting`` while the
  comparison launcher writes the final HTML report.
- Allowed sources: ``workflow``, ``reporting``, ``project`` and
  ``cli``.

See also
--------

- :doc:`/architecture/simulation/comparison-workflow` for the
  shared-case comparison contract.
- :doc:`/architecture/simulation/testbed-workflow-architecture` for
  the testbed pipeline.
- :doc:`/user_guide/workflows/comparison` -- user-facing hub.
- :doc:`/user_guide/workflows/regional_lab` -- regional_lab testbed profile.
- :doc:`/user_guide/workflows/testbed` -- testbed workflow page.
