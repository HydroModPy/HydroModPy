Add an exporter
===============

Exporters convert simulation results into external file formats. They live under
``hydromodpy/results/exporters/``, one writer class per format, registered in
``export_formats``. The list of formats this build serves is in the README of that
folder and in ``hmp export --help``. The formats of ``hydromodpy_annex/export/`` join
by entry point.

Use a new exporter when an external tool needs a format that none of those covers. A
new *data* (a field, a series, a layer) needs no new exporter. It enters the vocabulary
and takes the format of its kind.

How a request reaches an exporter
---------------------------------

A user never names an exporter class. An ``[[export]]`` block, ``run.export(...)`` and
``hmp export`` all build one ``ExportRequest`` (``export_spec.py``): what
(``variables``), when (``time``, ``period``), where (``folder``, ``file``), and
optionally ``format``.

1. ``Catalog.export(ref, request)`` (``results/catalog/reads.py``) resolves the run and
   hands the request to ``export_request`` in ``exporters/request.py``.
2. ``list_exportable`` (``exporters/vocabulary.py``) says what the run holds and the
   kind of each name: field, series, vector, raster, table.
3. ``plan_outputs`` (``exporters/export_spec.py``) names every file, from the kind of
   each name and the formats the declarations allow. The loader and ``hmp check`` call
   the same function through the ``refuse_an_export_that_cannot_be_written`` row of
   ``CROSS_RULES``, so the plan checked before the solve is the plan written.
4. The request resolves the dates to stress periods and hands each file to
   ``export_formats.get(fmt)().write(job, item, dest)``.

``[[export]].format`` and ``hmp export --as`` take a registered name only. An unknown
name is refused with the names this installation serves, and a format whose module
cannot be imported is refused with its entry point, its target and its reason.

Files to create
---------------

A new format called ``myfmt`` needs three edits.

- ``results/exporters/formats.py`` gets the writer class, on the model of the six file
  formats that live there.
- ``results/exporters/registry.py`` gets the registration, below.
- ``tests/ports/test_export.py`` gets a case that writes what the declarations say, on
  the copy of a sealed run.

Contract
--------

A format is a class of the ``ExportWriter`` Protocol. The tables of ``export_spec.py``
(the suffix of a format, the formats of one kind, what reprojects) are derived from the
declarations, so an in-tree format is one class and nothing else.

.. literalinclude:: /../../hydromodpy/results/exporters/port.py
   :pyobject: ExportWriter

The format decides and the job writes. ``_FileFormat.write`` looks up the kind of the
planned item and calls the method of ``ExportJob`` (``exporters/job.py``) that
``_by_kind`` names. A real format is this small.

.. literalinclude:: /../../hydromodpy/results/exporters/formats.py
   :pyobject: NetcdfFormat

The ``job`` holds what any writer reads of a run at the same place, and its
``ExportTarget`` poses the identity block of the run. A writer writes at the path it
receives and returns the paths it wrote. Every file lands under ``runs/<run>/exports/``
and is recorded in ``exports/index.json`` through ``record_derived_file`` in
``results/ledger.py``. A format must be idempotent, so a second write on the same path
overwrites cleanly.

Read the data the way the existing formats do.

- A field comes from the Zarr store through ``read_field_step`` and ``one_layer`` in
  ``exporters/fields.py``. ``one_layer`` refuses a field of several layers when no layer
  is given, so a format of one layer never picks one silently.
- A table comes from ``timeseries`` and ``budgets`` through DuckDB. CSV is the
  reference. Write naive times of the run clock (``timezone('UTC', time)``), because the
  tables carry no zone and the session zone would invent one.
- A vector layer comes from ``Catalog.read_geographic_feature``, and a raster layer from
  ``SimulationZarr.read_geographic_raster``.
- A view (``writes`` is ``(RUN_VIEW,)``) describes the whole run. The file name of a
  view is read from ``schema/generated_views.py``. RO-Crate is the model.

The mesh layers (``MESH_LAYERS`` in ``export_spec.py``) of a GeoPackage share one
file. ``exporters/mesh_layers.py`` writes them, and it is the model for a data that is
several layers of one file.

A file written before the seal must not trust the root attributes of the store, because
the seal writes the ACDD block. The NetCDF writer takes it from ``global_attrs``, which
``Catalog.export`` composes the way the seal does.

Register
--------

An in-tree format is one dotted path in ``_BUILTIN_PATHS`` of
``hydromodpy/results/exporters/registry.py``. A plugin format is the same class
published on the entry-point group ``hydromodpy.export.format``, named as its ``name``.
The mechanism is in :doc:`plug-into-a-port`. ``hydromodpy`` never imports
``hydromodpy_annex``, so the entry point carries the name and the refusal message
names only the target.

Test
----

- A unit test under ``tests/unit/results/`` with a tiny fixture catalog, one per kind
  the format holds, through ``Catalog.export`` with an ``ExportRequest``. It asserts the
  file name, the format and a value.
- ``tests/ports/test_export.py``, which the formats of the wheel and of the annex pass.
  The suite of an installed distribution runs from a clone of this repository.
- ``tests/unit/cli/test_export_command.py`` for an unknown ``--as`` name refused with the
  candidates.

Layer boundaries
----------------

``results`` never imports ``display``, ``project``, ``workflow`` or ``solver``, see
:doc:`../generated/layers`. Spatial reprojection helpers live in ``core/io/``
(``crs.py``, ``raster_io.py``, ``vector_io.py``). The VTU format builds a ``HydroMesh``
from the store and writes it with ``write_vtu`` of ``mesh/io/vtu.py``, the one VTU
writer.

See also
--------

- :doc:`../packages/results` for the catalog and the ``Run`` API.
- :doc:`add-a-figure` for matplotlib outputs.
- :doc:`/understand/reading-results` for reading a finished run and what it exported.
- :doc:`/reference/cli/export` for the ``hmp export`` command.
