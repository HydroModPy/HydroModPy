Candidate Building
==================

Candidate building answers one question: where do the outlet candidates come
from before DEM delineation and criteria evaluation? The workflow action is
resolved from ``site_selection.input.mode`` in
``hydromodpy.workflow.site_selection.run_site_selection_workflow``. Provider
loading happens before the reusable spatial package is called.

What This Page Explains
-----------------------

Candidate building is the first spatial step, but it is not yet catchment
delineation. Its job is narrower: turn a campaign input into a list of possible
outlet points with stable ids, coordinates, priorities, and attributes. Later
steps may move these outlets slightly during snapping, delineate their basins,
reject them, or select them. The candidate builder only says "these are the
places worth trying".

The mental model is:

.. code-block:: text

   campaign input
      |
      +-- station/provider records
      +-- CSV rows
      +-- DEM target-area cells
      +-- sampled DEM network cells
      |
      v
   CandidateOutlet rows
      |
      +-- optional CandidateAuditEvidence rows
      |
      v
   normal snapping, delineation, criteria, and reporting pipeline

This separation is important because it lets very different discovery modes use
the same downstream logic. A station candidate and an ungauged DEM candidate can
both be evaluated by area, overlap, spacing, observations, and warnings once
they have been normalized into the same ``CandidateOutlet`` shape.

Candidate Record
----------------

The shared in-memory unit is ``CandidateOutlet`` from
``hydromodpy/spatial/site_selection/candidates/outlets.py``. It carries:

- a stable ``candidate_id`` used as the site id by later phases;
- projected outlet coordinates and CRS;
- a source label and source feature id;
- a priority used as the base ranking score;
- free-form attributes that criteria can consume later.

Criteria should read normalized attributes from the candidate or delineated
catchment. They should not parse raw provider payloads.

Example Record
--------------

A station-led candidate may look like this after normalization:

.. code-block:: text

   candidate_id       = station_J341303001
   source             = hydrometry
   source_feature_id  = J341303001
   x, y, crs          = projected station coordinates
   priority           = 0
   attributes         = {
       "station_label": "...",
       "provider": "hubeau",
       "flow_station_id": "J341303001"
   }

A DEM-discovery candidate uses the same contract:

.. code-block:: text

   candidate_id       = dem_target_00042
   source             = dem_area_target
   source_feature_id  = accumulation_cell_817263
   x, y, crs          = projected DEM cell coordinates
   priority           = area-match score
   attributes         = {
       "upstream_area_km2": 94.2,
       "target_area_km2": 100.0,
       "relative_area_error": 0.058
   }

Downstream code can handle both records because it sees coordinates, ids,
priority, and normalized attributes instead of provider-specific payloads.

Station-Led Candidates
----------------------

Hydrometry-led runs use the existing data-manager stack to produce normalized
``PointRecord`` objects. The spatial package receives those records through
``build_site_selection_from_point_records`` and calls
``build_station_candidate_outlets``.

The station path does the following:

- convert station records to ``CandidateOutlet`` rows;
- project station coordinates to the DEM/project CRS;
- prefer provider official projected coordinates when present;
- optionally thin candidates with
  ``site_selection.outlets.min_distance_between_outlets_km``;
- optionally load a reference network when
  ``site_selection.outlets.snap_strategy = "bdtopage_then_dem"``.

The station path deliberately does not call Hub'Eau directly. Adding a new
hydrometry provider should happen in the data-manager layer, then expose
normalized point records to this workflow.

Station Mode in Practice
------------------------

Station-led mode is the most constrained path. The candidate position comes
from an observation station, and the main uncertainty is whether the station
point lies exactly on the DEM drainage network used for delineation.

.. code-block:: text

   provider station
        |
        v
   PointRecord
        |
        v
   CandidateOutlet(original station point)
        |
        v
   optional reference-network snap
        |
        v
   DEM snap and basin delineation

Use this mode when the campaign is anchored on known measurement points. Do not
use it to discover ungauged outlets; that is what the DEM-derived modes are for.

Pre-Delineated Catalogs
-----------------------

``delineated_catchments`` starts from a CSV. This path is used for fixtures,
frozen inventories, or already-normalized provider extracts. It can represent
two cases:

- catchments are already known and the selection layer evaluates their
  attributes;
- the CSV contains outlets and ``delineate_from_outlets = true`` asks the
  workflow to rebuild catchment geometry from the DEM.

CSV inputs can also carry normalized observation columns such as
``flow_station_id``, ``flow_station_x``, or ``piezometer_id``. These columns are
converted into the same evidence records used by provider-loaded observations.

CSV Mode in Practice
--------------------

CSV mode is deliberately flexible because it supports both production imports
and regression fixtures. The important question is whether the CSV already
contains catchment geometry or only outlet information:

.. list-table::
   :header-rows: 1
   :widths: 30 34 36

   * - CSV content
     - Configuration intent
     - Downstream behavior
   * - Existing basin ids and attributes
     - Evaluate an already-known catalog.
     - Criteria can run from the provided attributes and geometries.
   * - Outlet coordinates only
     - Rebuild basins from a DEM with ``delineate_from_outlets``.
     - Rows become ``CandidateOutlet`` records before delineation.
   * - Observation columns
     - Attach known evidence to each site.
     - Evidence rows are written like provider-loaded observations.

This path is useful when a team needs repeatable runs from a frozen input file.
It is also the simplest path for testing criterion behavior because the input
can be made small and deterministic.

DEM Target-Area Candidates
--------------------------

``dem_area_target`` is the high-level ungauged discovery mode. It searches DEM
accumulation cells for upstream areas close to
``site_selection.dem_area_target.target_area_km2``. The path is implemented by
``build_site_selection_from_dem_area_target`` and
``build_dem_area_target_candidates``.

The build sequence is:

#. resolve or build DEM flow products;
#. ensure a raw accumulation-cell table exists;
#. rank candidate cells against the target area;
#. cap the candidate list before expensive delineation;
#. delineate candidates with the normal DEM pipeline;
#. apply area and spatial criteria with stricter defaults for nested basins.

This mode is intended for practical area-driven campaigns. It hides most
low-level network sampling controls from users.

Target-Area Mode in Practice
----------------------------

Target-area mode starts from a hydrological design question: "find basins whose
upstream area is close to this size". It uses the DEM accumulation grid as a
search space, then keeps only a manageable number of cells before delineation.

.. code-block:: text

   DEM accumulation cells
        |
        v
   cells inside search geometry
        |
        v
   score by distance to target_area_km2
        |
        v
   keep best candidate cells
        |
        v
   CandidateOutlet rows
        |
        v
   normal delineation and selection

This mode should stay opinionated. It is meant for campaigns where the area
objective is more important than exposing every network-sampling knob. The
candidate audit file is the place to explain which cells were considered and
why only some were carried forward.

DEM Network Sampling Candidates
-------------------------------

``dem_network_sampling`` exposes the lower-level DEM stream-network sampling
path. It is useful when a contributor needs explicit control over network
candidate construction: accumulation thresholds, spacing, candidate caps, and
optional reference-network scoring.

The path is implemented by ``build_site_selection_from_dem_network_sampling``
and ``build_dem_network_candidates``. It writes extra candidate-audit artifacts
such as ``candidate_audit.jsonl``, ``candidate_outlets.geojson``, and
``dem_network.geojson`` when the relevant output switches are enabled.

Network-Sampling Mode in Practice
---------------------------------

Network sampling is the contributor-facing low-level mode. It exposes more
controls because the user is effectively saying "sample this drainage network
with these rules, then let the normal selection engine decide".

Use it when you need to tune:

- minimum accumulation before a DEM cell is considered part of the network;
- outlet spacing before delineation;
- maximum number of network candidates;
- optional reference-network score or distance attributes;
- candidate-audit output for debugging.

This mode can generate many plausible outlets. It should therefore produce
diagnostics that explain why candidates were kept, thinned, or skipped before
the expensive delineation step.

Search Geometry
---------------

DEM-derived modes can constrain sampling to the configured territory through
``site_selection_search_geometry``. The function supports French administrative
departments and regions, polygon files, and bounding boxes. It returns a
geometry in the project CRS so candidate builders avoid sampling outside the
study territory, especially along coastal DEM extents.

Reference-Network Scoring
-------------------------

Reference networks have two roles:

- in ``bdtopage_then_dem`` snapping, they move an outlet to the nearest valid
  reference line before DEM snapping;
- in DEM-network mode with ``dem_accumulation`` and a configured reference
  network path, they can score candidates without changing the snapping
  strategy.

Candidate builders should attach reference-network distances and status to
candidate attributes. The final selection phase then remains provider-neutral.

Choosing the Right Candidate Mode
---------------------------------

.. list-table::
   :header-rows: 1
   :widths: 26 37 37

   * - Mode
     - Best fit
     - Main review question
   * - ``hydrometry``
     - Known gauging or observation stations.
     - Did snapping preserve the intended station outlet?
   * - ``delineated_catchments``
     - Frozen catalogs, fixtures, or already-prepared basins.
     - Are the imported ids, geometry, and attributes trustworthy?
   * - ``dem_area_target``
     - Ungauged discovery around a target upstream area.
     - Did the ranking and cap keep the right area candidates?
   * - ``dem_network_sampling``
     - Low-level DEM network exploration.
     - Did accumulation, spacing, and candidate caps sample the network well?

If a new input mode cannot be explained in this table, it probably needs a
clearer boundary before it is added. The builder should produce candidate
records, not final decisions.

Common Review Questions
-----------------------

When reviewing candidate-building changes, check the following:

- Are candidate ids stable across repeated runs with the same input?
- Are coordinates projected into the CRS expected by delineation?
- Is provider-specific data normalized before entering the spatial package?
- Are candidate attributes small, serializable, and meaningful to criteria?
- Does the builder write audit evidence when it drops or ranks candidates?
- Does the mode reuse the normal snapping, delineation, criteria, and manifest
  pipeline instead of writing a separate output path?
