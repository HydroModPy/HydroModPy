Criteria and Selection
======================

The evaluation layer converts delineated catchments into auditable criterion
components and final selected/rejected decisions. The central function is
``select_delineated_catchments`` in
``hydromodpy/spatial/site_selection/evaluation/selection.py``.

What This Page Explains
-----------------------

At this point, candidates already have either a delineated basin or a
delineation failure record. The selection layer does not load stations, build a
DEM, or redraw watersheds. It reads the normalized candidate and basin records,
evaluates criteria, and writes an explicit reason for each final decision.

The easiest way to understand the selector is to picture a funnel:

.. code-block:: text

   all candidates
        |
        +-- failed delineation? ------------> rejected at "delineation"
        |
        +-- blocking criterion? -----------> rejected at "criteria"
        |
        +-- compute rank score
        |
        +-- sort best candidates first
        |
        +-- spatial conflict or quota? ----> rejected at "spatial_selection"
        |
        v
   selected sites

Every arrow that rejects a candidate creates an auditable decision. Nothing is
silently dropped after the candidate list enters the selector.

Criterion Component Contract
----------------------------

Every criterion contribution is represented by ``CriteriaComponent``. A row
contains:

- ``site_id`` and ``selection_principle``;
- ``criterion_id`` and ``criterion_family``;
- ``criterion_mode`` such as ``hard_reject``, ``warning``, ``score``,
  ``stratify``, or ``report_only``;
- ``evaluation_stage`` and ``evaluation_order``;
- ``criterion_status``;
- raw value, normalized value, threshold, weight, and score contribution;
- a ``blocking`` flag;
- a human-readable reason;
- structured ``evidence_json``.

This shape is deliberately flat and JSON-friendly because it is written to
``criteria_components.jsonl`` and later summarized into decision records and
the HTML report.

Why So Many Fields?
-------------------

The component shape is intentionally more verbose than a simple boolean pass or
fail. The same row must support three audiences:

- the selection engine needs ``blocking`` and ``score_component``;
- the reviewer needs ``criterion_status``, ``reason``, ``raw_value`` and
  ``threshold``;
- downstream tools need stable identifiers such as ``criterion_id`` and
  ``criterion_family``.

For example, an area criterion can be represented as:

.. code-block:: text

   site_id              = station_J341303001
   criterion_family     = area
   criterion_id         = area_range
   criterion_mode       = hard_reject
   raw_value            = 86.4
   threshold            = 50-500
   criterion_status     = passed
   blocking             = false
   reason               = area is inside configured range

An influence criterion can use the same shape:

.. code-block:: text

   site_id              = station_X
   criterion_family     = influence
   criterion_id         = major_dam_upstream
   criterion_mode       = warning
   criterion_status     = warning
   blocking             = false
   reason               = upstream feature intersects basin
   evidence_json        = { "evidence_ref": "..." }

The selector does not need separate output code for each criterion family
because both examples share the same record contract.

Criterion Families
------------------

The current selector evaluates these families for each successfully delineated
catchment:

.. list-table::
   :header-rows: 1
   :widths: 24 30 46

   * - Family
     - Function
     - Consumes
   * - Area
     - ``evaluate_area_criterion``
     - ``DelineatedCatchment.area_km2`` and
       ``site_selection.criteria.area``.
   * - Flow station
     - ``evaluate_flow_station_criterion``
     - Normalized candidate attributes such as station id, record evidence, and
       station-to-outlet distance.
   * - Piezometer
     - ``evaluate_piezometer_criterion``
     - Piezometer evidence attached during catchment annotation.
   * - Station influence
     - ``evaluate_station_influence_criterion``
     - Station metadata normalized by the hydrometry path.
   * - Influence layers
     - ``evaluate_influence_criterion``
     - Context-layer annotations, dams, abstractions, or regulated reaches.
   * - Geology
     - ``evaluate_geology_criterion``
     - Geology intersections attached during catchment annotation.

The selection function rejects a catchment immediately when one criterion
component is blocking. Otherwise it computes a rank score from the outlet
priority plus all non-null score components.

Modes: Reject, Warn, Score, Report
----------------------------------

The same criterion family can be used in different modes depending on the
campaign. The mode controls how much authority the criterion has over the final
decision:

.. list-table::
   :header-rows: 1
   :widths: 22 30 48

   * - Mode
     - Effect on selection
     - Reviewer interpretation
   * - ``hard_reject``
     - A failed component blocks the candidate immediately.
     - The campaign has decided this condition is incompatible with selection.
   * - ``warning``
     - The candidate can still be selected, but the warning is counted and
       shown in the decision/report.
     - The site needs human review or extra caution.
   * - ``score``
     - The component adds or removes from the rank score.
     - The condition helps prefer better sites but does not directly reject.
   * - ``stratify``
     - The component contributes a class used for balancing or reporting.
     - The site belongs to a category that may matter for campaign design.
   * - ``report_only``
     - The component is written for context but has no selection effect.
     - The information is useful for review but not yet a rule.

This is why the docs and reports distinguish "rejected" from "selected with
warnings". A warning is not a failed run; it is an explicit statement that the
automated part of the workflow found something worth reviewing.

Selection Stages
----------------

Final decisions use three main stages:

``delineation``
   The candidate could not be delineated. The failure status becomes a blocking
   reason.

``criteria``
   A normal criterion produced a blocking component.

``spatial_selection``
   The candidate passed normal criteria but failed a spatial rule such as max
   selected count, basin overlap, outlet spacing, or spatial quota.

``selection``
   The candidate passed all active blocking rules and was selected.

The resulting ``SelectionDecision`` stores blocking flags, warning flags, rank
score, and a compact status summary for every criterion id.

Decision Records
----------------

``SelectionDecision`` is the final one-row summary for a candidate. It does not
replace the detailed criterion rows; it points back to them through flags and
summary status. A typical selected decision looks like this:

.. code-block:: text

   site_id          = station_A
   selected         = true
   decision_stage   = selection
   decision_reason  = selected
   blocking_flags   = []
   warning_flags    = ["station_influence"]
   rank_score       = 12.5

A rejected decision keeps the same shape:

.. code-block:: text

   site_id          = station_B
   selected         = false
   decision_stage   = criteria
   decision_reason  = area is below configured minimum
   blocking_flags   = ["area_range"]
   warning_flags    = []
   rank_score       = null

This makes CSV summaries easy to scan while preserving detailed JSONL evidence
for audit and report pages.

Spatial Selection Rules
-----------------------

Candidates that pass normal criteria are sorted by:

#. descending rank score;
#. ascending number of warnings;
#. stable ``site_id`` tie-break.

They are then admitted one by one while enforcing spatial constraints:

- ``max_selected_sites`` creates a ``target_count`` component;
- ``max_pairwise_basin_overlap_fraction`` creates a ``basin_overlap``
  component when geometries are available;
- ``min_outlet_distance_km`` creates an ``outlet_spacing`` component;
- ``spatial_quota_mode = "grid"`` creates a ``spatial_quota`` component.

These spatial rules are also written as ``CriteriaComponent`` rows. They are
not hidden post-processing filters.

The spatial phase is sequential. Once a candidate is accepted, it becomes part
of the already-selected set that later candidates are compared against:

.. code-block:: text

   scored candidates sorted best first
       |
       v
   candidate 1 -> no selected neighbor yet -> selected
       |
       v
   candidate 2 -> overlap with candidate 1? outlet too close? quota full?
       |
       +-- no  -> selected
       +-- yes -> rejected at spatial_selection
       |
       v
   candidate 3 -> compared with all previously selected candidates

This is why ranking matters before spatial rules. If two overlapping basins are
both otherwise valid, the higher-ranked one is considered first and can occupy
the spatial slot. The lower-ranked one may then be rejected because it conflicts
with an already selected basin.

The rank score is deliberately simple:

.. code-block:: text

   rank_score = candidate_priority + sum(score_component for active criteria)

Warnings are not directly subtracted from the score. Instead, the sort order
uses the warning count as a tie-break after score. A high-scoring site with a
warning can still outrank a low-scoring clean site, but ties prefer fewer
warnings.

Overlap and Distance
--------------------

Two spatial checks often need careful interpretation:

.. list-table::
   :header-rows: 1
   :widths: 28 36 36

   * - Rule
     - What it prevents
     - What to inspect when it fires
   * - ``basin_overlap``
     - Selecting nearly the same upstream area twice.
     - Basin polygons, overlap reference, and maximum allowed fraction.
   * - ``outlet_spacing``
     - Selecting outlets that are too close to each other.
     - Final snapped outlet coordinates, not only original station points.

The overlap rule requires basin geometries. If geometry loading fails, the
selector does not invent an overlap value. The site can still be selected or
rejected by other criteria, and the absence of geometry should be diagnosed in
the delineation outputs.

DEM Target-Area Specialization
------------------------------

``dem_area_target`` overrides part of the selection configuration at runtime:

- the area criterion becomes a hard-reject window around the configured target;
- nested basins are disallowed;
- default pairwise overlap is capped when the user did not provide a cap;
- ``max_selected_sites`` is set from ``dem_area_target.n_basins``.

This keeps the user-facing target-area mode compact while still using the same
selection engine and output contract.

In plain terms, target-area mode says: "find me a limited number of basins near
this drainage area, avoid nested duplicates, and keep the best candidates after
DEM delineation." It is still the same selector, but the workflow supplies a
more opinionated area criterion and spatial selection policy because that is
what this mode is meant to do.

How to Read a Selection Report
------------------------------

When reviewing the HTML report or CSV/JSONL outputs, read decisions in this
order:

#. Start with counts: how many candidates were selected, rejected, and warned.
#. Open rejected decisions grouped by ``decision_stage``. Duplicated failures
   at the delineation stage point to DEM or CRS problems; failures at the
   criteria stage point to campaign rules.
#. For selected sites with warnings, inspect ``warning_flags`` before trusting
   the catalog blindly.
#. For spatial rejections, compare the candidate against the selected site
   named in ``evidence_json`` when available.
#. If a decision looks surprising, go back from ``SelectionDecision`` to the
   detailed ``CriteriaComponent`` rows for the same ``site_id``.

This reading order avoids a common trap: looking only at selected sites and
missing a systematic reason why many candidates were rejected.

Developer Rule
--------------

New criteria should return ``CriteriaComponent`` rows and leave final selection
ordering to ``select_delineated_catchments``. Avoid writing one-off rejection
CSV columns or direct report-only summaries; doing so bypasses the audit
contract.
