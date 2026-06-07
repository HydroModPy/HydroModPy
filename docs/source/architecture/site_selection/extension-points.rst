Extension Points
================

This page lists the usual extension paths and the package boundary each one
should respect.

What This Page Explains
-----------------------

Most site-selection changes are extensions, not rewrites. A contributor usually
wants to add a provider, a candidate source, a criterion, an evidence family, an
output, or a report block. Each one has a natural home. Putting code in the
right package keeps the workflow testable and prevents provider-specific logic
from leaking into the reusable spatial engine.

Use this decision tree first:

.. code-block:: text

   What are you adding?
        |
        +-- raw external data access -----> data-manager / workflow data layer
        |
        +-- new possible outlet source ---> candidates package
        |
        +-- outlet movement rule ---------> snapping / delineation code
        |
        +-- accept/reject/warn/score rule -> evaluation criteria
        |
        +-- basin context evidence -------> annotation and evidence outputs
        |
        +-- new file format --------------> spatial output writers + manifest
        |
        +-- report presentation ----------> reporting blocks
        |
        +-- interactive UI ---------------> manifest-consuming frontend

The extension should usually enter the normal pipeline as early as possible,
then reuse the existing downstream contracts.

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

Provider Boundary Example
-------------------------

The provider layer may know that a remote API calls a field ``code_station``.
The spatial layer should only see a normalized record with a station id,
coordinates, CRS, and attributes. That keeps the station path compatible with
CSV inputs, cached provider data, and future APIs.

.. code-block:: text

   remote API payload
        |
        v
   data-manager parser
        |
        v
   normalized PointRecord
        |
        v
   CandidateOutlet

Tests should cover provider parsing in the data layer and candidate conversion
in the spatial layer separately. A failure in the provider should not require a
DEM fixture, and a failure in candidate conversion should not require network
access.

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

Candidate Builder Checklist
---------------------------

A candidate builder is ready to integrate when it can answer:

- What stable id will the candidate use across repeated runs?
- Which CRS are the coordinates in when they enter delineation?
- Which attributes are needed later by criteria or reports?
- Which candidates were dropped, capped, or ranked before delineation?
- Which audit rows explain those pre-delineation choices?
- Which user-facing config fields activate the builder?

The builder should not decide final selection. It should produce a traceable set
of candidates and let delineation and criteria produce the final decisions.

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

Snapping Boundary Example
-------------------------

Snapping can be confusing because two coordinate pairs may be valid:

.. code-block:: text

   original outlet
        |
        +-- reference-network snap, if configured
        |
        v
   adjusted outlet used for DEM delineation
        |
        v
   basin geometry

The original point explains what the campaign asked for. The adjusted point
explains what the DEM delineator actually used. Both are useful in review maps
when a station was moved to a nearby drainage cell.

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

Criterion Design Questions
--------------------------

Before adding a criterion, decide its mode and evidence needs:

.. list-table::
   :header-rows: 1
   :widths: 28 36 36

   * - Question
     - Example answer
     - Output consequence
   * - Is the criterion blocking?
     - Area below minimum is incompatible with selection.
     - ``blocking = true`` and the decision stage becomes ``criteria``.
   * - Is it only a warning?
     - A station influence exists upstream but does not invalidate the site.
     - ``warning_flags`` records the issue but the site can still be selected.
   * - Does it contribute to ranking?
     - A preferred class adds score.
     - ``score_component`` changes the rank score.
   * - Does it need evidence?
     - A geometry intersection or observation row explains the result.
     - ``evidence_json`` references the serialized evidence artifact.

Every evaluator should return rows in the common ``CriteriaComponent`` shape so
decisions, CSV exports, JSONL exports, and report blocks stay aligned.

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

Evidence Versus Criteria
------------------------

Evidence describes what was observed. Criteria decide how that observation
affects selection.

.. code-block:: text

   basin intersects a protected area
        |
        v
   evidence row: protected-area intersection geometry and attributes
        |
        v
   criterion row: warning, hard reject, score, or report-only status

Keeping evidence separate from criterion decisions lets the same evidence be
used differently by different campaigns. One profile may reject a condition;
another may only warn or report it.

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

Output Registration Flow
------------------------

Adding a file is not finished when the file is written:

.. code-block:: text

   write file
      |
      v
   register output key in output_paths
      |
      v
   include path in site_selection_manifest.json
      |
      v
   validate lightweight structure
      |
      v
   expose through report_artifact_manifest.json when useful

This is what lets a static report, notebook, or frontend discover the file
without knowing the implementation detail that wrote it.

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

Report Block Boundary
---------------------

A report block should feel like a read-only view:

.. code-block:: text

   manifest + loaded artifact rows
             |
             v
   rendered text, table, chart, map link, or warning summary

It should not call candidate builders, criteria evaluators, provider clients,
or DEM routines. If it needs data that is not available, add a declared output
artifact first and then read that artifact from the report.

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

Testing an Extension
--------------------

Use focused tests that match the layer being changed:

.. list-table::
   :header-rows: 1
   :widths: 28 36 36

   * - Extension
     - Minimal useful test
     - Avoid
   * - Provider
     - Parse a small payload into normalized point records.
     - Requiring live network access.
   * - Candidate builder
     - Convert deterministic inputs into stable ``CandidateOutlet`` rows and
       audit evidence.
     - Running a full report just to test candidate ids.
   * - Criterion
     - Assert hard reject, warning, score, and report-only rows.
     - Testing through an unrelated provider.
   * - Output format
     - Write a tiny result and validate manifest registration.
     - Checking only that a file exists without checking the output key.
   * - Report block
     - Render from a small manifest fixture and artifact rows.
     - Calling selection logic from the report test.

A good extension test should fail near the layer that is broken. That is the
main reason the package boundaries in this page are strict.
