Reading one point
=================

A map answers "where"; a point answers "how much, here". This page covers
the two ways of getting the value of a variable at one precise location:
interrogating a finished run, and declaring the location up front so the
run samples it while it still holds its own outputs.

Both read the same mesh and give the same number. The difference is when
the work happens, and therefore how fast the answer comes back.

.. list-table::
   :header-rows: 1
   :widths: 22 39 39

   * -
     - Interrogate afterwards
     - Declare in ``[observation]``
   * - When
     - Any time after the run
     - During the run, once the fields exist
   * - Cost
     - Reads the touched Zarr chunks
     - A plain table read afterwards
   * - Use it for
     - Exploration, a location you did not anticipate
     - A piezometer you read on every run
   * - Entry point
     - ``hmp catalog point`` / ``run.probe.series()``
     - ``[observation]`` in the TOML

Interrogating a finished run
----------------------------

From the CLI
~~~~~~~~~~~~

.. code-block:: bash

   hmp catalog point @last --var head --xy 395100 6824925

The cell is named either by coordinates in the simulation CRS
(``--xy X Y``) or by its index (``--cell N``). The layer is picked with
``--layer N`` (zero-based, negative counts from the bottom) or with
``--depth METRES`` below the local model top, resolved against the mesh
layer thicknesses. The two are mutually exclusive, and so are ``--xy``
and ``--cell``.

.. code-block:: bash

   # a virtual field, one timestep, the last one
   hmp catalog point @last --var watertable_depth --cell 5000 --timestep -1

   # several variables at once
   hmp catalog point @last --var head --var watertable_depth --xy 395100 6824925

   # the same point on two runs, stacked for comparison
   hmp catalog point cheze_baseline.v2 cheze_baseline.v3 \
       --var head --cell 2550 -o probe.csv

Several references read the *same* point on each run and stack the
answers; the coordinates are resolved per run, because two runs rarely
share a mesh. ``--format`` picks ``table`` (default), ``json`` or
``csv``; ``-o FILE`` writes a ``.csv`` or ``.parquet`` file instead.

From Python
~~~~~~~~~~~

The gesture lives on ``run.probe``, next to ``run.array``, and on
``group.probe`` for a set of runs:

.. code-block:: python

   import hydromodpy as hmp

   cat = hmp.open("~/proj/cheze")
   run = cat.latest()

   frame = run.probe.series("head", x=395100.0, y=6824925.0)
   frame = run.probe.series("watertable_depth", cell=1204, timestep=-1)
   frame = run.probe.series(["head", "watertable_depth"], cell=1204, depth=12.5)

   # the same point across a RunSet
   group = cat.find(solver="modflow6")
   group.probe.series("head", x=395100.0, y=6824925.0, output="probe.parquet")

The answer is always a long-format ``pandas.DataFrame``, one row per
timestep, variable and run:

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Column
     - Meaning
   * - ``run``, ``sim_id``
     - Which run the row comes from
   * - ``variable``, ``unit``
     - Field name and its registered unit
   * - ``timestep``, ``time``
     - Step index and calendar date (``NaT`` for a steady run)
   * - ``value``
     - The number
   * - ``cell``, ``layer``
     - Cell index and the layer actually read (``<NA>`` when the stored
       array carries no layer axis)
   * - ``x``, ``y``
     - Coordinates of the point, or the cell centroid when ``cell`` was
       given

Virtual fields such as ``watertable_depth`` answer like persisted ones:
they are rebuilt at read time, with the same code a map read uses, so
the two can never disagree.

Coordinates outside the mesh raise ``PointOutsideMeshError``; an
out-of-range cell or layer index raises ``IndexError``. The
point-to-cell lookup is cached per mesh geometry, so repeated probes on
the same run pay the locator cost once.

Declaring observation points
----------------------------

For a location you already know before the run, declare it in
``[observation]``. The run samples it once its fields exist, and the
declaration is persisted with the run in
``runs/<name>/tables.parquet/observation_points.parquet``, so rebuilding
the index with ``hmp catalog reindex`` does not lose it.

.. code-block:: toml

   [observation]
   variables = ["head", "watertable_depth"]

   [[observation.points]]
   id = "piezo_amont"
   x = 395100.0
   y = 6824925.0
   depth = 12.5

   [[observation.points]]
   id = "piezo_aval"
   x = 396800.0
   y = 6823110.0
   layer = 0
   variables = ["head"]

Each point needs a unique ``id`` and its ``x`` / ``y`` in the project
CRS. ``layer`` and ``depth`` pick the vertical position exactly as on the
CLI, and remain mutually exclusive. A point may name its own
``variables``; otherwise it takes the section-level list, which itself
defaults to ``["head"]``. Virtual fields are accepted.

This is **not** ``[data.piezometry]``. That section loads *measured*
series from a data source; ``[observation]`` declares *where the model is
read*. Nothing is compared here: the declaration produces model series,
not residuals.

Reading the declared points back:

.. code-block:: python

   run.probe.declared
   # columns: run, station_id, x, y, cell_id, layer

   run.timeseries("head", station="obs:piezo_amont")

The full field list of the section is in
:doc:`config_reference/observation`.

See also
--------

- :doc:`results-and-exports` for the run directory and how each artefact
  is read.
- :doc:`cli-reference` and :doc:`/cli/catalog` for the complete
  ``hmp catalog point`` synopsis.
- :doc:`catalog` for opening a project catalog and selecting runs.
