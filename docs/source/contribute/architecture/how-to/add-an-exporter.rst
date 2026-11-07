Add an exporter
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
:class:`~hydromodpy.results.exporters.export_spec.ExportRequest`: what
(``variables``), when (``time``, ``period``), where (``folder``, ``file``),
and optionally ``format``.

1. ``Catalog.export(ref, request)`` (``results/catalog/reads.py``) resolves
   the run and hands the request to
   :func:`~hydromodpy.results.exporters.request.export_request`.
2. :func:`~hydromodpy.results.exporters.vocabulary.list_exportable` says what
   the run holds, and the kind of each name: field, series, vector, raster,
   table.
3. :func:`~hydromodpy.results.exporters.export_spec.plan_outputs` names every
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

- ``results/exporters/export_spec.py``: a value of ``ExportFormat``, its
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
   from hydromodpy.results.exporters.fields import one_layer, read_field_step
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

Several layers in one file
--------------------------

``plan_outputs`` gives each name its own file, with one exception: the mesh
layers (``MESH_LAYERS`` in ``results/exporters/export_spec.py``) of a GeoPackage
share one file, ``<layer>.gpkg`` for a single layer and ``<run>_mesh.gpkg`` for
several. ``results/exporters/mesh_layers.py`` writes them, one
``gdf.to_file(..., layer=name)`` per layer, and states the CRS of the ``mesh/``
group rather than the one of the run root. A run sealed before the cell-mesh
layout states none, so ``list_exportable`` does not list the layers for it and
``request.py`` gives the reason when one is asked. Follow that module for a
data that is several layers of one file.

Choose what to read
-------------------

- **Tabular**: the ``timeseries`` and ``budgets`` tables through DuckDB. CSV
  is the reference; write naive times of the run clock
  (``timezone('UTC', time)``), never the session zone.
- **Field**: the Zarr store, through ``fields.read_field_step``. NetCDF,
  GeoTIFF, GeoPackage, VTU follow this pattern.
- **Layer**: ``Catalog.read_geographic_feature`` for a vector layer,
  ``SimulationZarr.read_geographic_raster`` for a raster one.
- **Bundle**: the whole run. There is one: ``hmp publish --container tar``
  (``results/export/publish.py``), which copies the sealed run.

Every file lands under ``runs/<run>/exports/`` and carries the identity block of
the run: :class:`~hydromodpy.results.exporters.request.ExportTarget` poses it
(``gpkg_metadata`` for a GeoPackage, a ``<file>.meta.json`` sidecar otherwise)
and records the file in ``exports/index.json``. A new exporter returns the
paths it wrote and gets both for free.

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
  ``results``. The documented ``results -> mesh`` and ``results -> spatial`` tolerance is
  reserved for spatial-index storage, feature names and the cell mesh:
  ``zarr_store/mesh_layout.py`` reads the ``PlanarCellMesh`` of a run, and
  the VTU exporter builds a ``HydroMesh`` from the store and writes it with
  ``write_vtu`` of ``mesh/io/vtu.py``, the one VTU writer. Do not import
  ``display``, ``project``, ``workflow``, or ``solver`` in an exporter.
- Spatial reprojection helpers live in ``core/io/`` (``crs.py``,
  ``raster_io.py``, ``vector_io.py``); reach them from ``core``, not
  from ``spatial``.
- Exporters must remain idempotent: re-running on the same path
  must overwrite cleanly.

See also
--------

- :doc:`../packages/results` for the catalog and the ``Run`` API.
- :doc:`add-a-figure` for matplotlib outputs.
- Results and exports for the user-facing export
  inventory.
- hmp export for ``hmp export``.
