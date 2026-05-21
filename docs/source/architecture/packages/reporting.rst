reporting
=========

``hydromodpy.reporting`` is the HTML composites layer. It assembles
figures from ``display/`` and analysis features from ``analysis/``
into standalone HTML deliverables: the calibration session report,
the simulation comparison web report, and the streamlit configurator.

Reporting is a one-way sink: ``display`` and ``analysis`` must not
import from ``reporting``.

Sub-modules
-----------

- ``reporting/calibration_report.py`` -- calibration session HTML
  report (moved from ``display/``). Reads sessions, iterations, and
  promoted runs from the catalog; renders six calibration figures
  through the ``display`` catalog; emits a standalone HTML file.
- ``reporting/streamlit_config.py`` -- streamlit configurator UI
  (moved from ``display/``). Exposes the JSON Schema export to a live
  TOML editor.
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

- ``hydromodpy.reporting.calibration_report.render_report``
- ``hydromodpy.reporting.streamlit_config`` (CLI script entry point)
- ``hydromodpy.reporting.comparison.render`` (web report orchestrator)
- ``hydromodpy.reporting.comparison.compact_network.builder.build_compact_network_synthesis``

Recommended reading path
------------------------

1. ``hydromodpy/reporting/comparison/render.py`` for the comparison
   web report entry point.
2. ``hydromodpy/reporting/calibration_report.py`` for the calibration
   session report.
3. ``hydromodpy/reporting/comparison/sections/__init__.py`` for the
   per-section composition.
4. ``hydromodpy/reporting/streamlit_config.py`` for the configurator
   UI.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``config``, ``results``,
  ``display``, ``analysis``, ``reporting``.
- Allowed sources: ``workflow``, ``cli``, top-level facade.
- ``display`` and ``analysis`` cannot import ``reporting``; the edge
  is one-way (``tests/unit/architecture/test_layer_matrix.py``
  enforces it).

See also
--------

- :doc:`display` for the figure catalog reused by every HTML report.
- :doc:`analysis` for the comparison features fed into the web
  report.
- :doc:`/architecture/calibration/calibration-guide` -- the
  calibration HTML report end to end.
