Add an Exporter
===============

Exporters convert simulation results into external file formats. Six
exporters ship today under ``hydromodpy/results/exporters/``: CSV,
NetCDF, GeoTIFF, VTU, Shapefile, and the portable ``.hmp`` package.

Use a new exporter when an external tool needs a format that none of
those covers.

Contract
--------

Each exporter is a function that reads from the catalog connection
plus the per-simulation Zarr / Parquet payloads and writes the
chosen format to disk:

.. code-block:: python

   from pathlib import Path

   import duckdb


   def export_<format>(
       conn: duckdb.DuckDBPyConnection,
       sim_id: str,
       output_path: str | Path,
       **kwargs,
   ) -> Path:
       """Export simulation results to <format>."""
       # 1. query the catalog for the rows you need
       # 2. open the Zarr / Parquet payloads if needed
       # 3. write the file
       # 4. log the success and return the path
       ...

Files to create
---------------

A new format called ``myfmt``:

.. code-block:: text

   hydromodpy/results/exporters/myfmt.py

Skeleton:

.. code-block:: python

   import logging
   from pathlib import Path

   import duckdb

   logger = logging.getLogger(__name__)


   def export_myfmt(
       conn: duckdb.DuckDBPyConnection,
       sim_id: str,
       output_path: str | Path,
       *,
       variable: str | None = None,
   ) -> Path:
       """Export ``timeseries`` of ``sim_id`` to a .myfmt file."""
       output_path = Path(output_path)
       output_path.parent.mkdir(parents=True, exist_ok=True)
       query = "SELECT * FROM timeseries WHERE sim_id = ?"
       params = [sim_id]
       if variable is not None:
           query += " AND variable = ?"
           params.append(variable)
       df = conn.execute(query, params).fetchdf()
       _write_myfmt(df, output_path)
       logger.info("Exported myfmt: %s", output_path)
       return output_path

Wire it through ``Catalog.export``
--------------------------------------------

The ``Catalog.export`` method dispatches on ``fmt``. Add the
new branch in ``hydromodpy/results/catalog/reads.py``:

.. code-block:: python

   if fmt == "myfmt":
       from hydromodpy.results.exporters.myfmt import export_myfmt
       return export_myfmt(self._db, sid, path, variable=variable, **kwargs)

Wire it through the CLI
-----------------------

The ``hmp export`` command (``hydromodpy/cli/commands/export.py``)
forwards ``--myfmt`` to the exporter. Add an argument and a dispatch
branch:

.. code-block:: python

   parser.add_argument("--myfmt", action="store_true",
                       help="Export to .myfmt (custom format).")

   if args.myfmt:
       export_myfmt(catalog._conn, sim_id, output_dir / f"{sim_id}.myfmt")

Choose what to read
-------------------

Most exporters fall in one of three families:

- **Tabular**: read ``timeseries`` / ``budgets`` / ``mass_balance``
  Parquet views via DuckDB. CSV is the canonical example.
- **Field**: read Zarr arrays through ``Run.field`` /
  ``Run.fields``. NetCDF, GeoTIFF, VTU follow this pattern.
- **Bundle**: read both plus the catalog rows. ``.hmp`` is the
  reference (see ``hmp_package.py``).

Reuse the connection handed by ``Catalog`` rather than
opening a new one. Reuse ``Run.field`` rather than reading raw Zarr
keys.

Tests to add
------------

- **Unit** under ``tests/unit/results/exporters/`` with a tiny
  fixture catalog (``conftest.py`` already ships ``catalog_with_data``).
  Assert the file is created and round-trips for the field's dtype
  and shape.
- **Integration** under ``tests/integration/results/`` for an
  end-to-end ``hmp export`` invocation.

Pitfalls flagged by the layer matrix
------------------------------------

- ``results`` may import ``core``, ``schema``, ``config``, and
  ``results``. The documented ``results -> spatial`` tolerance is
  reserved for spatial-index storage. Do not import ``display``,
  ``analysis``, ``simulation``, or ``solver`` in an exporter.
- Spatial reprojection helpers live in ``core/io/`` (``crs.py``,
  ``raster_io.py``, ``vector_io.py``); reach them from ``core``, not
  from ``spatial``.
- Exporters must remain idempotent: re-running on the same path
  must overwrite cleanly.

See also
--------

- :doc:`../packages/results` for the catalog and the ``Run`` API.
- :doc:`add-a-figure` for matplotlib outputs.
- :doc:`/user_guide/results-and-exports` for the user-facing export
  inventory.
