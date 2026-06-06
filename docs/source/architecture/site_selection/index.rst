:html_theme.sidebar_secondary.remove:

.. _architecture-site-selection:

Site Selection Internals
========================

``site_selection`` is the upstream catalog-building workflow. It turns station
records, pre-delineated catchments, or DEM-derived outlet candidates into a
reviewed set of selected and rejected catchments. The public user page stays in
:doc:`/user_guide/workflows/site_selection`; this section documents the code
contracts behind that page for contributors.

The main design choice is a strict boundary between provider loading and
spatial selection. Provider access lives in the workflow and data-manager
layers. The reusable selection engine lives under
``hydromodpy/spatial/site_selection`` and receives normalized candidates,
flow products, observations, and output paths.

Runtime Shape
-------------

.. code-block:: text

   hmp run config.toml
        |
        +-- hydromodpy.workflow.site_selection.run_site_selection_workflow
              |
              +-- load and validate [site_selection]
              +-- resolve action from site_selection.input.mode
              +-- load provider data when needed
              +-- call spatial build primitives
              +-- write manifest and optional review report

The workflow supports five actions:

.. list-table::
   :header-rows: 1
   :widths: 22 36 42

   * - Action
     - Candidate source
     - Main implementation path
   * - ``plan``
     - No candidate loading; validation and plan manifest only.
     - ``plan_site_selection`` in ``hydromodpy.workflow.site_selection``.
   * - ``delineated_catchments``
     - A CSV of already-known catchments or outlets.
     - ``select_delineated_catchments_from_csv`` in the workflow layer,
       then the shared evaluation and output writers.
   * - ``hydrometry``
     - Normalized hydrometry ``PointRecord`` objects.
     - ``build_site_selection_from_point_records`` in
       ``spatial/site_selection/pipelines/build.py``.
   * - ``dem_area_target``
     - DEM cells whose upstream area is close to a target area.
     - ``build_site_selection_from_dem_area_target`` in
       ``spatial/site_selection/pipelines/build.py``.
   * - ``dem_network_sampling``
     - Sampled DEM stream-network cells.
     - ``build_site_selection_from_dem_network_sampling`` in
       ``spatial/site_selection/pipelines/build.py``.

Subsystem Map
-------------

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: Candidate building
      :link: candidate-building
      :link-type: doc

      How station, CSV, target-area, and DEM-network candidates enter the
      spatial build.

   .. grid-item-card:: Delineation and snapping
      :link: delineation-and-snapping
      :link-type: doc

      DEM flow products, outlet snapping, reference-network constraints, and
      failure records.

   .. grid-item-card:: Criteria and selection
      :link: criteria-and-selection
      :link-type: doc

      Criterion components, blocking decisions, warnings, ranking, overlap,
      outlet spacing, and quotas.

   .. grid-item-card:: Manifest and reporting
      :link: manifest-and-reporting
      :link-type: doc

      Output writers, ``site_selection_manifest.json``, report artifact
      manifests, and the HTML review page.

   .. grid-item-card:: Extension points
      :link: extension-points
      :link-type: doc

      Where to add providers, candidate builders, criteria, report blocks, and
      output formats without crossing package boundaries.

Package Boundaries
------------------

.. list-table::
   :header-rows: 1
   :widths: 27 38 35

   * - Package
     - Owns
     - Must not own
   * - ``hydromodpy.workflow.site_selection``
     - TOML loading, action dispatch, provider-data resolution, progress
       messages, and report-renderer injection.
     - Low-level spatial criteria or provider-independent output schemas.
   * - ``hydromodpy.workflow.site_selection_data``
     - DEM and hydrometry data-manager calls used by this workflow.
     - Selection decisions or report layout.
   * - ``hydromodpy.spatial.site_selection``
     - Candidate records, DEM-selection phases, delineation adapters,
       criteria, decisions, evidence, outputs, and manifests.
     - Hub'Eau or Geoplateforme API details.
   * - ``hydromodpy.reporting.site_selection``
     - Static map, reusable report blocks, and HTML page rendering from
       manifest-declared artifacts.
     - Running selection, reading provider APIs, or writing the official
       selection manifest.
   * - ``hydromodpy.schema.site_selection_manifest``
     - Manifest constants, path resolution, artifact validation, and stable
       JSON IO helpers.
     - Workflow dispatch or domain-specific ranking rules.

Design Invariants
-----------------

- The spatial build functions receive resolved file paths and normalized
  records; they do not fetch provider data themselves.
- DEM access is configured through ``[data.dem]`` or an explicitly resolved DEM
  path. The DEM is not hidden inside a selection criterion.
- Every final decision is represented by auditable ``CriteriaComponent`` rows
  and a ``SelectionDecision`` row.
- ``site_selection_manifest.json`` is the hand-off contract for reports and
  downstream catalog consumers.
- HTML reporting is derived from the manifest and its declared artifacts. A
  report should be reproducible from the manifest alone.

.. toctree::
   :hidden:
   :maxdepth: 1

   candidate-building
   delineation-and-snapping
   criteria-and-selection
   manifest-and-reporting
   extension-points
