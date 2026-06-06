Criteria and Selection
======================

The evaluation layer converts delineated catchments into auditable criterion
components and final selected/rejected decisions. The central function is
``select_delineated_catchments`` in
``hydromodpy/spatial/site_selection/evaluation/selection.py``.

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

DEM Target-Area Specialization
------------------------------

``dem_area_target`` overrides part of the selection configuration at runtime:

- the area criterion becomes a hard-reject window around the configured target;
- nested basins are disallowed;
- default pairwise overlap is capped when the user did not provide a cap;
- ``max_selected_sites`` is set from ``dem_area_target.n_basins``.

This keeps the user-facing target-area mode compact while still using the same
selection engine and output contract.

Developer Rule
--------------

New criteria should return ``CriteriaComponent`` rows and leave final selection
ordering to ``select_delineated_catchments``. Avoid writing one-off rejection
CSV columns or direct report-only summaries; doing so bypasses the audit
contract.
