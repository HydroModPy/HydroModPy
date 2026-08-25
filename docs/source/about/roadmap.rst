Roadmap
=======

This page summarises the directions HydroModPy development is moving
in. It is intentionally short: the issue tracker on GitHub is the live
source of truth for items in flight.

For tagged work-in-progress items, browse the
`roadmap label <https://github.com/HydroModPy/HydroModPy/issues?q=is%3Aissue+label%3Aroadmap>`_
on the issue tracker.

Themes in progress
------------------

.. list-table::
   :header-rows: 1
   :widths: 24 60 16

   * - Theme
     - What it covers
     - Status
   * - Calibration depth
     - Bayesian methods (``gp_mapping``, ``da_mh_gp``), surrogate-driven
       MCMC, multi-station weighted objectives, MODFLOW 6 metric
       extractor.
     - Phase 4
   * - Storage evolution
     - First explicit DuckDB / Zarr schema migrations under
       ``hydromodpy/results/catalog/migrations/``, with round-trip tests and
       package-version pinning.
     - Prospective
   * - Application map
     - Interactive Leaflet variant of :doc:`../applications`,
       backed by the same catchment registry.
     - Phase 3
   * - Public examples
     - Migrated example notebooks and TOML-first walkthroughs
       rewritten on top of the current Pydantic-based API.
     - Pending
   * - Hydrographic ``simulated_active`` role
     - Persisted feature for the simulated active stream network,
       built from ``accumulation_flux`` thresholds, with comparison
       against the loaded reference.
     - Design phase
   * - Comparison workflow
     - Parallel execution of child simulations, basin-scale physics
       comparisons (drainage, network), explicit budget contrasts.
     - Iterative
   * - Transport coverage
     - Curated MODPATH and MT3DMS examples, validation pages, and
       documented transport-specific assumptions.
     - Catch-up

How to influence the roadmap
----------------------------

- Open an issue with the ``roadmap`` label describing the use case and
  the constraint it lifts.
- Send a pull request that lands a small focused step: a new data
  manager, a calibration adapter, a validation case, or a docs
  improvement (see :doc:`../contribute`).
- For collaboration on a larger feature, contact the corresponding
  authors listed on the :doc:`landing page </index>`.

What is intentionally out of scope
----------------------------------

- A single hosted web service. HydroModPy stays a Python library; the
  exposed JSON Schema and validators (see
  :doc:`../architecture/overview/frontend-hooks`) are the supported
  integration surface.
- A custom storage format beyond DuckDB, Zarr, and Parquet. Adding
  another backend requires explicit user agreement.
- Backwards-compatibility shims and alias modules. The package is
  refactored toward a single canonical name per concept.

See also
--------

- :doc:`changelog` for shipped releases.
- :doc:`../contribute` for the contributor workflow.
- :doc:`../architecture/index` for the package boundaries that any
  roadmap item must respect.
