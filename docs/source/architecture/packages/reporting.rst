reporting
=========

``hydromodpy.reporting`` is the HTML composites layer. It assembles
figures from ``display/`` and analysis features from ``analysis/``
into standalone HTML deliverables: the calibration session report
and the simulation comparison web report.
Not every HTML report lives in this package: workflow-owned reports
such as site-selection and catchment review pages may live beside their
workflow code, but should reuse ``hydromodpy.display.report_blocks``
when they are block-based static pages.

Reporting is a one-way sink: ``display`` and ``analysis`` must not
import from ``reporting``.

Every deliverable of this package lands under ``<project>/share/``,
the publication directory: reports in ``share/reports/<name>/``,
exports next to them. Nothing in ``share/`` is a source of truth; it is
regenerated from ``runs/`` and ``sessions/``.

Sub-modules
-----------

- ``reporting/calibration_report.py`` -- calibration session HTML
  report (moved from ``display/``). Reads the session descriptor and
  the trial log from ``sessions/<session_name>/``; renders six
  calibration figures through the ``display`` figure registry; emits
  ``share/reports/<session_name>/report.html`` next to a ``figures/``
  sub-directory.
- ``reporting/comparison/`` -- simulation comparison HTML web report
  (moved from ``analysis/comparison/web/``).

  - ``comparison/render.py`` -- top-level orchestration of the web
    report; main entry point.
  - ``comparison/context.py`` -- per-pair / per-N rendering context.
  - ``comparison/figures.py`` -- figure assembly delegated to
    ``display`` and ``analysis``.
  - ``comparison/html_utils.py`` -- small HTML helpers.
  - ``comparison/sections/`` -- one module per report section.
  - ``comparison/compact_network/`` -- compact network synthesis
    section (was ``compact_network_synthesis``).

Key public symbols
------------------

- ``hydromodpy.reporting.calibration_report.render_session``
- ``hydromodpy.reporting.comparison.render`` (web report orchestrator)
- ``hydromodpy.reporting.comparison.compact_network.builder.build_compact_network_synthesis``

Block-based reports
-------------------

Use ``hydromodpy.display.report_blocks`` for static HTML pages whose
content can be represented as blocks with metrics, figures, tables,
links and warnings. Keep the report producer in the package that owns
the manifest or workflow contract, then delegate HTML rendering to the
shared display renderer. This keeps ``reporting`` focused on the
cross-run composites it owns directly and avoids moving workflow logic
into a generic HTML package.

Recommended reading path
------------------------

1. ``hydromodpy/reporting/comparison/render.py`` for the comparison
   web report entry point.
2. ``hydromodpy/reporting/calibration_report.py`` for the calibration
   session report.
3. ``hydromodpy/reporting/comparison/sections/__init__.py`` for the
   per-section composition.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``config``, ``results``,
  ``display``, ``analysis``, ``reporting``.
- Allowed sources: ``workflow``, ``cli``, top-level facade.
- ``display`` cannot import ``reporting``. ``analysis`` has one
  documented tolerance to ``reporting`` for the comparison HTML report;
  that edge should not expand.

See also
--------

- :doc:`display` for the figure catalog reused by every HTML report.
- :doc:`/architecture/how-to/add-a-block-html-report` for the shared
  block-report recipe.
- :doc:`analysis` for the comparison features fed into the web
  report.
- :doc:`/architecture/calibration/calibration-guide` -- the
  calibration HTML report end to end.
