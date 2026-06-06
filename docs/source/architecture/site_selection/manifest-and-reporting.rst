Manifest and Reporting
======================

Completed site-selection runs write regular tabular and geospatial artifacts,
then assemble ``site_selection_manifest.json``. The manifest is the stable
contract for report rendering and downstream catalog consumers.

Core Output Phase
-----------------

``write_core_site_selection_outputs`` coordinates the output phase. It calls
``write_selection_result`` for decision and selected/rejected artifacts, then
``write_site_selection_evidence_outputs`` for observation, influence, geology,
and normalized evidence artifacts.

The core audit outputs are:

- ``criteria_components.jsonl``;
- ``site_selection_decisions.csv``;
- ``site_selection_decisions.jsonl``;
- ``site_selection_evidence.jsonl`` when evidence records exist;
- selected/rejected CSV and GeoJSON files according to output switches;
- optional GeoPackage and GeoParquet layers.

DEM-derived modes add candidate-audit outputs such as
``candidate_audit.jsonl``. Target-area mode also writes ``diagnostics.csv``.

Manifest Contract
-----------------

``build_selection_manifest`` writes a single JSON object with these top-level
sections:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Section
     - Meaning
   * - ``schema_version``
     - Stable manifest version from
       ``hydromodpy.schema.site_selection_manifest``.
   * - ``selection_id`` and ``action``
     - Run identity and resolved workflow action.
   * - ``strategy``
     - Principle, profile, effective profile, primary axes, observation type,
       and candidate mode.
   * - ``territory``
     - Territory mode and selectors used to describe the study area.
   * - ``input``
     - Input mode, catalog paths, data roots, and resolved input paths.
   * - ``dem`` and ``flow_products``
     - DEM settings and calculated flow-product artifacts.
   * - ``outlets``
     - Candidate and snapping settings.
   * - ``criteria``
     - Full JSON dump of configured criteria.
   * - ``counts``
     - Selected, rejected, decision, criterion, warning, and blocking counts.
   * - ``outputs``
     - Artifact ids mapped to paths relative to ``output_root`` when possible.
   * - ``map_context``
     - Optional context layers used by review maps.

``write_manifest_and_optional_report`` writes the manifest before rendering the
report. If HTML reporting is enabled, it pre-declares the report HTML and map
PNG paths in the manifest so the report artifact manifest can include them.

Validation
----------

``hydromodpy.schema.site_selection_manifest`` owns manifest validation. It
checks:

- required top-level keys;
- supported schema version;
- required output artifact ids;
- existence and lightweight structure of declared artifacts;
- GeoJSON, JSONL, CSV, PNG, JSON, GeoPackage, and GeoParquet shape where
  possible;
- map-context layer paths.

Report rendering skips the report HTML and map PNG while validating because
those are the artifacts being generated from the manifest.

HTML Report
-----------

``hydromodpy.reporting.site_selection.html.render_site_selection_html_report``
loads the manifest, resolves artifact paths, reads CSV/JSONL tables, renders
``review/site_selection_map.png``, builds report blocks, and writes four HTML
entry points:

- ``review/index.html`` with per-block detail selection;
- ``review/compact/index.html``;
- ``review/standard/index.html``;
- ``review/audit/index.html``.

The report is intentionally downstream of the manifest. It should not re-run
selection logic or silently infer artifacts that are absent from
``manifest["outputs"]``.

Report Artifact Manifest
------------------------

The generic report-artifact contract is written by
``write_site_selection_report_artifact_manifest``. It transforms
manifest-declared outputs into reusable artifact records with producers such as
``site_selection.decisions``, ``site_selection.evidence``,
``site_selection.hydrology``, and ``site_selection.report``.

Downstream frontends should prefer this artifact manifest when they need a
generic list of files, and prefer ``site_selection_manifest.json`` when they
need domain semantics such as selected counts, criteria, or DEM settings.
