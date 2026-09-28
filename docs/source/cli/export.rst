hmp export
==========

Synopsis: ``hmp export <ref> [VARIABLE ...] [--list] [--time T ...]
[--period START END] [--format F] [--folder DIR] [--file FILE] [--crs CRS]
[--resolution R] [--layer N] [-w WORKSPACE]``

Write data of a finished run to files. The verb speaks the words of an
``[[export]]`` block: the positionals say what, ``--time`` or ``--period``
when, ``--folder`` or ``--file`` where. The format follows the data unless
``--format`` or the extension of ``--file`` names one. Each written path is
printed on its own line; the count goes to the error stream.

``--list`` prints what the run can export, grouped by kind, and writes
nothing:

.. code-block:: text

   nancon_step5_export can export:
   fields:
     head
     seepage_mask
     simulated_active_network
     watertable_depth
     ...
   series:
     discharge
     discharge_obs
   vector layers:
     hydrographic_network_reference
     watershed
     ...
   raster layers:
     watershed_dem
     watershed_fill
   tables:
     budget

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Data
     - One date
     - Several dates, a period, or the whole run
   * - Field (``head``, ``watertable_depth``, ``simulated_active_network``...)
     - GeoTIFF, one file per variable
     - NetCDF, one file for every field named
   * - Series (``discharge``, ``discharge_obs``...), table ``budget``
     - CSV
     - CSV
   * - Vector layer (``watershed``, ``hydrographic_network_reference``...)
     - GeoPackage
     - GeoPackage
   * - Raster layer (``watershed_dem``, ``watershed_fill``)
     - GeoTIFF
     - GeoTIFF

- ``all`` exports everything the run holds, each data in its natural format.
  With ``--format`` it exports every data that format can hold.
- ``--time`` takes dates (``2002-10-15``), ``first`` or ``last``; a date
  takes the stress period that holds it. A format of one instant (GeoTIFF,
  Shapefile, GeoPackage, VTU) writes one file per date.
- ``--format package`` writes the portable ``.hmp`` archive of the run;
  ``stac``, ``rocrate`` and ``prov`` write its metadata views, inside the run
  directory unless ``--folder`` or ``--file`` is given. The four take ``all``.
- Files land in ``share/<run>/``. A relative ``--folder`` is read from
  ``share/``, a relative ``--file`` from the folder.
- ``--crs`` reprojects rasters and vector layers; NetCDF, VTU and CSV refuse
  it. ``--layer`` picks the layer of a field of several layers, which a
  format of one layer requires.

Examples::

   hmp export nancon_step5_export --list
   hmp export nancon_step5_export all
   hmp export nancon_step5_export head watertable_depth --time 2002-10-15
   hmp export nancon_step5_export discharge discharge_obs --period 2001-01-01 2002-12-31
   hmp export nancon_step5_export watershed hydrographic_network_reference
   hmp export nancon_step5_export simulated_active_network --time 2002-08-15 --format geopackage
   hmp export nancon_step5_export watertable_depth --time last --file depth.tif --crs EPSG:4326
   hmp export nancon_step5_export all --format package

A name the run does not hold is refused with the list of what it holds
(exit code 1); an unknown run exits with 10. Python has the same words:
``run.export(...)`` and ``hmp.export(run, ...)``; see
:doc:`/user_guide/results-and-exports`.
