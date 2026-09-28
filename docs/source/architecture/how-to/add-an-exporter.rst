Add an Exporter
===============

Exporters convert simulation results into external file formats. They live
under ``hydromodpy/results/exporters/``: CSV (series and budget), NetCDF,
GeoTIFF (fields and raster layers), GeoPackage and Shapefile (fields and
vector layers), VTU, and the portable ``.hmp`` package.

Use a new exporter when an external tool needs a format that none of those
covers. A new *data* (a field, a series, a layer) needs no new exporter: it
enters the vocabulary and takes the format of its kind.

How a request reaches an exporter
---------------------------------

A user never names an exporter. An ``[[export]]`` block, ``run.export(...)``
and ``hmp export`` all build one
:class:`~hydromodpy.core.config_kit.export_spec.ExportRequest`: what
(``variables``), when (``time``, ``period``), where (``folder``, ``file``),
and optionally ``format``.

1. ``Catalog.export(ref, request)`` (``results/catalog/reads.py``) resolves
   the run and hands the request to
   :func:`~hydromodpy.results.exporters.request.export_request`.
2. :func:`~hydromodpy.results.exporters.vocabulary.list_exportable` says what
   the run holds, and the kind of each name: field, series, vector, raster,
   table.
3. :func:`~hydromodpy.core.config_kit.export_spec.plan_outputs` names every
   file, from the kind of each name and the format (``KIND_FORMATS`` gives
   the formats a kind can be written in, the first being its natural one).
   The step 0 check of ``hmp run`` and ``hmp config check`` call the same
   function, so the plan checked before the solve is the plan written.
4. The request writer resolves the dates to stress periods
   (``run.periods.step_at``, ``run.periods.steps_for``) and calls the
   exporter of each file.

Files to touch
--------------

A new format called ``myfmt``:

- ``core/config_kit/export_spec.py``: a value of ``ExportFormat``, its
  suffix in ``_SUFFIX_TO_FORMAT`` and ``FORMAT_SUFFIX``, the kinds that can
  be written in it in ``KIND_FORMATS``, and ``SINGLE_INSTANT_FORMATS`` when a
  file holds one instant (then several dates write one file per date).
- ``results/exporters/myfmt.py``: the writer.
- ``results/exporters/request.py``: the branch of ``_Writer`` that calls it.
- ``cli/commands/export.py``: the value in ``FORMAT_CHOICES`` (a test keeps
  it equal to ``ExportFormat``).

Skeleton of a writer for a field at one step:

.. code-block:: python

   from pathlib import Path

   import numpy as np

   from hydromodpy.core.logging import get_logger
   from hydromodpy.results.exporters._fields import one_layer, read_field_step
   from hydromodpy.results.zarr_store import SimulationZarr

   logger = get_logger(__name__)


   def export_myfmt(
       zarr_path: str | Path,
       sim_id: str,
       variable: str,
       timestep: int,
       output_path: str | Path,
       *,
       layer: int | None = None,
       values: np.ndarray | None = None,
   ) -> Path:
       """Export one step of a field to a .myfmt file."""
       output_path = Path(output_path)
       output_path.parent.mkdir(parents=True, exist_ok=True)
       sz = SimulationZarr(zarr_path)
       try:
           data = values if values is not None else read_field_step(
               sz, sim_id, variable, timestep
           )
       finally:
           sz.close()
       data = one_layer(data, variable, layer, "myfmt")
       _write_myfmt(data, output_path)
       logger.info("Exported myfmt: %s", output_path)
       return output_path

``read_field_step`` reads a stored field, a static one whole, and rebuilds a
virtual one (``watertable_depth``, ``seepage_mask``) on read. ``values``
carries a field the caller computed, such as ``simulated_active_network``,
which needs the catalog and is built once per request. ``one_layer`` refuses
a field of several layers when no layer is given: a format of one layer
never picks one silently.

Choose what to read
-------------------

- **Tabular**: the ``timeseries`` and ``budgets`` tables through DuckDB. CSV
  is the reference; write naive times of the run clock
  (``timezone('UTC', time)``), never the session zone.
- **Field**: the Zarr store, through ``_fields.read_field_step``. NetCDF,
  GeoTIFF, GeoPackage, VTU follow this pattern.
- **Layer**: ``Catalog.read_geographic_feature`` for a vector layer,
  ``SimulationZarr.read_geographic_raster`` for a raster one.
- **Bundle**: the whole run. ``.hmp`` is the reference (``hmp_package.py``);
  it runs after the seal.

A file written before the seal must not trust the root attributes of the
store: the ACDD block is written by the seal. The NetCDF exporter takes it
from ``global_attrs``, which ``Catalog.export`` composes the way the seal
does.

Tests to add
------------

- **Unit** under ``tests/unit/results/`` with a tiny fixture catalog: one
  test per kind the format holds, through ``Catalog.export`` with an
  ``ExportRequest``, asserting the file name, the format and a value.
- **CLI** in ``tests/unit/cli/test_export_command.py`` when the format has a
  flag of its own.

Pitfalls flagged by the layer matrix
------------------------------------

- ``results`` may import ``core``, ``schema``, ``config``, and
  ``results``. The documented ``results -> spatial`` tolerance is
  reserved for spatial-index storage and feature names. Do not import
  ``display``, ``analysis``, ``simulation``, or ``solver`` in an exporter.
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
- :doc:`/cli/export` for ``hmp export``.
