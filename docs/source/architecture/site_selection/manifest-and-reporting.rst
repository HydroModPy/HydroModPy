Manifest and Reporting
======================

Completed site-selection runs write regular tabular and geospatial artifacts,
then assemble ``site_selection_manifest.json``. The manifest is the stable
contract for report rendering and downstream catalog consumers.

What This Page Explains
-----------------------

The output phase turns in-memory decisions into files that can be audited,
shared, rendered, or loaded by another tool. The central rule is simple:
``site_selection_manifest.json`` describes what was produced, where it is, and
what the run meant. The HTML report is a consumer of that manifest, not a second
source of truth.

The output flow is:

.. code-block:: text

   SelectionDecision rows + CriteriaComponent rows + evidence rows
          |
          v
   CSV / JSONL / GeoJSON / GeoPackage / GeoParquet artifacts
          |
          v
   site_selection_manifest.json
          |
          +-- static HTML review report
          +-- report_artifact_manifest.json
          +-- downstream catalog or frontend

If a file is useful outside the current Python process, it should be declared
in the manifest or in the report-artifact manifest. Otherwise downstream tools
have to guess filenames, and the run becomes harder to reproduce.

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

Reading the Output Directory
----------------------------

A completed run usually has three categories of files:

.. list-table::
   :header-rows: 1
   :widths: 26 38 36

   * - Category
     - Typical files
     - How to use them
   * - Audit tables
     - ``criteria_components.jsonl``,
       ``site_selection_decisions.csv``,
       ``site_selection_decisions.jsonl``.
     - Explain why each candidate passed, warned, or failed.
   * - Spatial layers
     - selected/rejected GeoJSON, GeoPackage, GeoParquet, candidate outlets,
       DEM network layers.
     - Inspect geometry, overlap, outlet locations, and map context.
   * - Report files
     - ``site_selection_manifest.json``, ``review/index.html``,
       ``review/site_selection_map.png``, ``report_artifact_manifest.json``.
     - Reconstruct the run summary and render or browse the review pages.

The CSV decision file is convenient for a quick spreadsheet review. The JSONL
files are better for code because they keep structured values and evidence
references. The geospatial files are for map inspection and frontend rendering.

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

Manifest as a Run Summary
-------------------------

The manifest is intentionally both technical and human-reviewable. It should
answer these questions without opening the source TOML:

.. code-block:: text

   What action ran?
   Which territory and strategy were used?
   Which inputs and DEM products were resolved?
   Which criteria were active?
   How many sites were selected, rejected, warned, or blocked?
   Which artifact path contains each output?
   Which map context layers were available?

This makes the manifest the best starting point for a static frontend or a
notebook that wants to inspect a completed run. The frontend can load the
manifest first, then follow artifact ids to CSV, JSONL, GeoJSON, or PNG files.

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

Validation Philosophy
---------------------

Validation is lightweight on purpose. It should catch broken contracts without
turning report rendering into a full geospatial QA pipeline:

- required artifact ids must be present when the run mode promises them;
- declared paths should exist, unless they are the report files currently being
  generated;
- JSONL and CSV files should be readable enough to detect accidental empty or
  malformed outputs;
- map context paths should resolve from the manifest output root;
- schema version must be explicit so future migrations can be handled.

Deep scientific validation belongs earlier in the workflow and in tests. The
manifest validator checks that consumers can trust the artifact list.

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

Report Detail Levels
--------------------

The four HTML entry points serve different review depths:

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Entry point
     - Intended use
     - Typical reader
   * - ``review/compact/index.html``
     - Fast summary with the smallest useful set of blocks.
     - A project lead checking whether the run looks plausible.
   * - ``review/standard/index.html``
     - Balanced review of counts, maps, selected sites, and warnings.
     - A modeler reviewing the campaign outcome.
   * - ``review/audit/index.html``
     - Detailed evidence and artifact-oriented review.
     - A developer or reviewer investigating decisions.
   * - ``review/index.html``
     - Main landing page with block selection.
     - Any reader who wants navigation to the available report views.

All of these pages should remain reproducible from the manifest and declared
artifacts. If a report block needs a new table, the output phase should write
and declare that table first.

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

Manifest Versus Report Artifact Manifest
----------------------------------------

The two manifests have different jobs:

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - File
     - Best for
     - Avoid using it for
   * - ``site_selection_manifest.json``
     - Domain semantics: action, strategy, criteria, counts, DEM settings,
       selected/rejected artifact ids.
     - A generic file browser that only needs links and producer labels.
   * - ``report_artifact_manifest.json``
     - Generic frontend integration: artifact records, producers, labels, and
       reusable file links.
     - Reconstructing selection logic or criteria semantics.

In short, the site-selection manifest explains the run. The report-artifact
manifest lists the files in a frontend-friendly way.

Common Review Questions
-----------------------

When reviewing output and reporting changes, check the following:

- Is every externally useful artifact declared with a stable output key?
- Can the HTML report be regenerated from the manifest and declared files?
- Does validation catch missing files without rejecting report files that are
  being generated?
- Are selected/rejected counts consistent between decisions, spatial layers,
  and manifest counts?
- Does the report read artifact rows instead of calling provider, DEM, or
  selection functions?
- Would a future frontend know which file to open without hard-coding a path?
