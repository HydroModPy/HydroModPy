Artifact Policy
===============

HydroModPy V1 uses DuckDB, Zarr and Parquet as the canonical stores.
Other formats are allowed only when their role is explicit.

Canonical scientific stores
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 28 48

   * - Category
     - Formats
     - Contract
   * - Project catalog
     - DuckDB
     - Stable source of truth for simulations, metrics, parameters,
       provenance, audit events and workflow ledger.
   * - Input cache
     - DuckDB
     - Stable cache index for downloaded and custom datasets.
   * - Field arrays
     - Zarr
     - Stable persisted field store for gridded and mesh fields.
   * - Tabular outputs
     - Parquet, GeoParquet
     - Stable persisted tables and vector layers.

Allowed non-canonical artifacts
-------------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 24 52

   * - Category
     - Formats
     - Contract
   * - User exports
     - CSV, NetCDF, GeoTIFF, VTU, Shapefile, STAC, PROV-O,
       RO-Crate, ``.hmp``
     - Documented outputs for humans and external tools. They are not
       the source of truth.
   * - Input derivatives
     - Parquet, NetCDF, JSON sidecars
     - Cache artifacts tied to data variables and provenance.
   * - Solver diagnostics
     - NPY, NPZ, JSON, CSV
     - Sidecars for debugging solver state. They are not stable user
       APIs unless a page names the schema.
   * - Validation and calibration truth packages
     - NPZ, CSV, JSON
     - Named benchmark artifacts with local schema expectations.
   * - Legacy hydrology helpers
     - HDF5
     - Localized PyHELP output. Stable only for the owning helper.
   * - Observability
     - JSONL, DuckDB
     - Experimental ``validity_frame`` sidecars.

Direct DuckDB access
--------------------

The normal path is a catalog or cache adapter. Direct ``duckdb.connect``
is allowed in these narrow cases:

- migration runners;
- backend adapters and concrete catalog/cache constructors;
- read-only diagnostics;
- portable ``.hmp`` snapshot export/import;
- tests and performance benchmarks;
- experimental ``validity_frame`` ingestion;
- developer-only CLI inspection commands.

New direct DuckDB calls in user-facing CLI commands or ``hydromodpy._api``
should be treated as a regression unless they are added to this list with
a test rationale.
