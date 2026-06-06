Extension Points
================

This page lists the usual extension paths and the package boundary each one
should respect.

Add a Hydrometry Provider
-------------------------

Provider code belongs in the data-manager layer, not in
``hydromodpy.spatial.site_selection``.

Expected path:

#. add or extend the provider under ``hydromodpy.data``;
#. normalize station outputs as point records with coordinates, CRS, station
   ids, labels, and relevant metadata;
#. update ``hydromodpy.workflow.site_selection_data`` only if the workflow needs
   a new loading policy;
#. keep ``build_site_selection_from_point_records`` unchanged when possible.

The spatial layer should continue receiving provider-neutral point records.

Add a Candidate Builder
-----------------------

Candidate builders belong under
``hydromodpy/spatial/site_selection/candidates``. A builder should return
``CandidateOutlet`` rows and, when useful, ``CandidateAuditEvidence`` rows.

Keep these rules:

- expose the user-facing selector through typed config first;
- do not write final selected/rejected artifacts from the candidate builder;
- attach candidate-specific diagnostics as attributes or candidate-audit rows;
- route all candidates through the normal delineation and selection phases.

If the candidate source needs DEM flow products, follow the existing
``build_dem_area_target_candidates`` and ``build_dem_network_candidates``
pattern.

Add a Snapping or Reference-Network Strategy
--------------------------------------------

Reference-network loading and scoring lives under
``hydromodpy/spatial/site_selection/candidates/reference_network.py``.
Delineation-time snapping is applied in
``hydromodpy/spatial/site_selection/hydrology/delineation.py``.

New strategies should preserve this split:

- candidate builders may score or annotate candidates;
- delineation may adjust the outlet used by the DEM extractor;
- final maps and exports should preserve both original and adjusted
  coordinates when they differ.

Add a Criterion
---------------

Criteria belong under
``hydromodpy/spatial/site_selection/evaluation/criteria``. A new criterion
should:

#. add typed config in ``config/models.py``;
#. add an evaluator that returns ``CriteriaComponent``;
#. call that evaluator from ``select_delineated_catchments``;
#. include evidence references in ``evidence_json`` rather than embedding large
   payloads;
#. add tests for hard reject, warning, score/report-only behavior, and output
   rows.

Do not add direct report logic to a criterion. The report should read the same
criterion rows that CSV and JSONL outputs read.

Add Context Evidence
--------------------

Spatial evidence such as influence, geology, or piezometers is attached before
selection by ``annotate_site_selection_catchments``. Add new context families
there when the evidence is derived from basin geometry or context layers.

The expected shape is:

- annotation code enriches ``DelineatedCatchment`` attributes or returns typed
  evidence rows;
- criterion code consumes the normalized attributes or evidence references;
- output code serializes the evidence through
  ``write_site_selection_evidence_outputs``;
- report code reads manifest-declared evidence artifacts.

Add an Output Format
--------------------

Output-format changes belong under ``spatial/site_selection/outputs``. Keep
``site_selection_manifest.json`` as the source of truth for artifact discovery.

Checklist:

- write the artifact in the core output phase or a mode-specific output phase;
- register its path in the returned ``output_paths`` mapping;
- include a stable output key;
- extend manifest validation if the format has a lightweight structural check;
- add report-artifact metadata when the artifact should appear in generic
  report consumers.

Add a Report Block
------------------

Report blocks belong in ``hydromodpy/reporting/site_selection/blocks.py``.
They should read from the manifest and already-loaded artifact rows. They should
not call selection, provider, or DEM functions.

When adding a block:

- define compact, standard, and audit behavior when the detail level matters;
- keep artifact links manifest-driven;
- prefer summary tables over re-parsing raw provider-specific files;
- add or update a focused report rendering test if the block consumes a new
  artifact.

Add a Frontend
--------------

A frontend should treat ``site_selection_manifest.json`` and
``report_artifact_manifest.json`` as the backend contracts. It should not parse
the HTML report to recover state.

Recommended frontend flow:

#. run or receive a completed selection;
#. load the manifest;
#. resolve artifact paths using the manifest output root;
#. render maps/tables from declared GeoJSON, CSV, and JSONL artifacts;
#. link back to ``review/index.html`` for the static audit report.

This keeps notebooks, static HTML, and future interactive UIs aligned on the
same output contract.
