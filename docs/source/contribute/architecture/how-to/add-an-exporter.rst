Add an exporter
===============

Exporters convert simulation results into external file formats. They live
under ``hydromodpy/results/exporters/``: one writer class per format,
registered in ``export_formats``. The wheel ships seven, CSV (series and
budget), NetCDF, GeoTIFF (fields and raster layers), GeoPackage and
Shapefile (fields, vector layers), VTU, and the RO-Crate view of a run.
STAC and the standalone PROV view are formats too, but they live in
``hydromodpy_annex/export/`` and register by entry point.

Use a new exporter when an external tool needs a format that none of those
covers. A new *data* (a field, a series, a layer) needs no new exporter: it
enters the vocabulary and takes the format of its kind.

How a request reaches an exporter
---------------------------------

A user never names an exporter class. An ``[[export]]`` block,
``run.export(...)`` and ``hmp export`` all build one
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
   file, from the kind of each name and the formats the declarations allow
   (a kind takes the formats that declare it, the first being its natural
   one). The loader and ``hmp check`` call the same function through
   the ``refuse_an_export_that_cannot_be_written`` row of ``CROSS_RULES``
   (``config/cross_checks.py``), so the plan checked before the solve is the
   plan written. That check plans before the run has a name, so the export
   itself refuses a file an earlier block of the run already writes.
4. The request resolves the dates to stress periods
   (``run.periods.step_at``, ``run.periods.steps_for``) and hands each file
   to ``export_formats.get(fmt)().write(job, item, dest)``.

``[[export]].format`` and ``hmp export --as`` take a registered name, and
nothing else is accepted: an unknown name is refused with the names this
installation serves, and a declared format whose module cannot be imported
is refused with its entry point, its target and its reason. That is how a
format of the annex is named without the package naming it.

The port
---------

A format is a class of the
:class:`~hydromodpy.results.exporters.port.ExportWriter` Protocol:

.. code-block:: python

   class ExportWriter(Protocol):
       name: str            # the name written in [[export]].format and --as
       suffix: str          # the file suffix
       writes: ...          # the export kinds it holds, or {"run"} for a view
       natural: ...         # the kinds it is the default format of
       instants: str        # "one" or "many"
       reprojects: bool

       def write(self, job: ExportJob, item, dest: Path) -> list[Path]: ...

The vocabulary tables of ``export_spec.py`` (the suffix of a format, the
formats of one kind, what reprojects, the file name of a view) are derived
from the declarations, so an in-tree format is one class and nothing else.

The ``job`` is an :class:`~hydromodpy.results.exporters.job.ExportJob`,
which holds what any writer reads of a run at the same place, and its
``ExportTarget``. A writer writes at the path it receives, returns the
paths it wrote, and gets the identity block of the run and the entry in
``exports/index.json`` for free from the target.

Files to touch
--------------

A new format called ``myfmt``:

- ``results/exporters/formats.py``: the writer class, on the model of the
  six file formats that live there;
- ``results/exporters/registry.py``: the dotted path in ``_BUILTIN_PATHS``;
- ``tests/ports/test_export.py``: a case that writes what
  the declarations say, on the copy of a sealed run.

A plugin format, out of tree, is the same class published on the
``hydromodpy.export.format`` entry-point group, named as its ``name``.

Skeleton of the declaration of a writer for a field at one step:

.. code-block:: python

   class MyfmtWriter:
       name = "myfmt"
       suffix = ".myfmt"
       writes = {"field"}          # kinds it holds
       natural = ()                # kinds it is the default format of
       instants = "one"            # "one" or "many"
       reprojects = False

       def write(self, job, item, dest) -> list[Path]:
           ...

The item of a field carries what the plan resolved: the Zarr path of the
run, the simulation, the variable, the step, the layer, and the values when
the caller computed them. From there the body of a field writer is one
function, the model being the six file formats of ``formats.py``:

.. code-block:: python

   from hydromodpy.core.logging import get_logger
   from hydromodpy.results.exporters.fields import one_layer, read_field_step

   logger = get_logger(__name__)


   def _write_myfmt_field(zarr_path, sim_id, variable, timestep, dest,
                          *, layer=None, values=None):
       data = read_field_step(zarr_path, sim_id, variable, timestep,
                              values=values)
       data = one_layer(data, variable, layer, "myfmt")
       _write_myfmt(data, dest)
       logger.info("Exported myfmt: %s", dest)

``read_field_step`` reads a stored field, a static one whole, and rebuilds a
virtual one (``watertable_depth``, ``seepage_mask``) on read. A field the
caller computed is already carried by the item, such as
``simulated_active_network``, which needs the catalog and is built once per
request. ``one_layer`` refuses a field of several layers when no layer is
given: a format of one layer never picks one silently.

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

- Tabular: the ``timeseries`` and ``budgets`` tables through DuckDB. CSV
  is the reference; write naive times of the run clock
  (``timezone('UTC', time)``), because the tables carry no zone and the
  session zone would invent one.
- Field: the Zarr store, through ``fields.read_field_step``. NetCDF,
  GeoTIFF, GeoPackage, VTU follow this pattern.
- Layer: ``Catalog.read_geographic_feature`` for a vector layer,
  ``SimulationZarr.read_geographic_raster`` for a raster one.
- Bundle: the whole run. There is one: ``hmp publish --container tar``
  (``results/export/publish.py``), which copies the sealed run.
- View (``writes`` is ``{"run"}``): the ``ExportJob`` carries the
  ``FairExportContext`` of the sealed directory, the way RO-Crate reads it.
  The file name of a view is a fact of the stored layout, read from
  ``schema/generated_views.py``.

Every file lands under ``runs/<run>/exports/`` and carries the identity
block of the run, posed by the ``ExportTarget`` of the job
(``gpkg_metadata`` for a GeoPackage, a ``<file>.meta.json`` sidecar
otherwise), and is recorded in ``exports/index.json`` through
``record_derived_file`` in ``results/ledger.py``.

A file written before the seal must not trust the root attributes of the
store: the ACDD block is written by the seal. The NetCDF writer takes it
from ``global_attrs``, which ``Catalog.export`` composes the way the seal
does.

Tests to add
------------

- Unit: under ``tests/unit/results/`` with a tiny fixture catalog: one
  test per kind the format holds, through ``Catalog.export`` with an
  ``ExportRequest``, asserting the file name, the format and a value.
- Contract: a case in
  ``tests/ports/test_export.py`` that the formats of the
  wheel and of the annex pass, on the copy of a sealed run; the conformance
  suite of an installed distribution runs from a clone of this repository.
- CLI in ``tests/unit/cli/test_export_command.py``: a ``--as`` unknown
  name refused with the candidates.

Pitfalls flagged by the layer matrix
------------------------------------

- ``results`` may import ``core``, ``schema``, ``catchment``, ``mesh``,
  ``model`` and ``results``. The tolerance on ``mesh`` and ``catchment`` is
  reserved for spatial-index storage, feature names and the cell mesh:
  ``zarr_store/mesh_layout.py`` reads the ``PlanarCellMesh`` of a run, and
  the VTU exporter builds a ``HydroMesh`` from the store and writes it with
  ``write_vtu`` of ``mesh/io/vtu.py``, the one VTU writer. Do not import
  ``display``, ``project``, ``workflow``, or ``solver`` in an exporter.
- Spatial reprojection helpers live in ``core/io/`` (``crs.py``,
  ``raster_io.py``, ``vector_io.py``); reach them from ``core``, not
  from ``catchment``.
- Exporters must remain idempotent: re-running on the same path
  must overwrite cleanly.
- A format of the annex has no place in the wheel: ``hydromodpy`` never
  imports ``hydromodpy_annex``, the entry point carries the name, and the
  refusal message names only the target.

See also
--------

- :doc:`../packages/results` for the catalog and the ``Run`` API.
- :doc:`add-a-figure` for matplotlib outputs.
- :doc:`/understand/reading-results` for reading a finished run and what it
  exported.
- :doc:`/reference/cli/export` for the ``hmp export`` command.
