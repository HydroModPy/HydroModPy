Candidate Building
==================

Candidate building answers one question: where do the outlet candidates come
from before DEM delineation and criteria evaluation? The workflow action is
resolved from ``site_selection.input.mode`` in
``hydromodpy.workflow.site_selection.run_site_selection_workflow``. Provider
loading happens before the reusable spatial package is called.

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
