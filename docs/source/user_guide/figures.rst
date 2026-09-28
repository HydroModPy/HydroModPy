Figure Catalog
==============

Figures live in ``hydromodpy.display`` and consume the persisted
:class:`hydromodpy.results.run.Run` interface. They are solver-agnostic: the
same figure name can render MODFLOW-NWT, MODFLOW 6, or Boussinesq outputs when
the required result fields exist.

Basic usage
-----------

.. code-block:: python

   import hydromodpy as hmp

   hmp.figure(run, "piezometric_map", save="figures/")
   hmp.figure(run, "cross_section", orientation="sn")
   hmp.figure(run, "seepage_map", time="2002-10-15")

The lower-level registry stays available when you need the figure object
itself:

.. code-block:: python

   from hydromodpy.display import get, list_figures

   list_figures()
   get("piezometric_map").plot(run, save_path="head.png")

From the CLI:

.. code-block:: bash

   hmp viz list
   hmp viz list --run <sim_id>
   hmp viz show <sim_id> <figure>
   hmp viz show <sim_id> <figure> --time 2002-10-15
   hmp viz gallery project.toml
   hmp run project.toml --no-display

Registered figure names
-----------------------

The catalog below is auto-generated from the
``hydromodpy.display.list_figures()`` registry. Each entry shows the figure
name, the title rendered in plots, and the result fields or tables the
figure reads at render time. Run ``python -m tools.doc_figures`` to refresh
the partial without rebuilding the rest of the documentation; the Sphinx
build also regenerates it on every run.

.. include:: figures_inventory.partial.rst

Choosing figures in TOML
------------------------

A run renders exactly the figures listed under ``[display].figures``. Every
name is validated against the registry when the configuration loads, so a
typo fails ``hmp config check`` instead of silently producing one figure
less.

.. code-block:: toml

   [display]
   figures = ["piezometric_map", "water_budget", "simulated_active_network"]
   # "warn" (default) logs a figure that fails to render and continues;
   # "raise" propagates, which is what example and CI configs want.
   on_error = "warn"

Per-figure options go under ``[display.overrides]``, keyed by figure name.
They are the same keywords :func:`hydromodpy.figure` accepts. A key the
figure does not take is refused when the configuration loads, and the
message lists the keys it takes:

.. code-block:: toml

   [display.overrides.cross_section]
   orientation = "sn"
   through = [152687.5, 6857800.0]

   [display.overrides.flux_timeseries]
   units = "mm/period"

Use ``hmp viz gallery project.toml`` to rerender all figures after a run,
``hmp viz show <sim_id> <figure>`` to rerender one figure, and
``--no-display`` during ``hmp run`` when the workflow should persist results
without rendering report figures. ``hmp viz show`` applies the ``[display]``
the run was drawn with (its ``time`` and its overrides), so it redraws the
figure of the run; ``--time`` names another instant. ``hmp.figure`` applies
only the options it is given.

Choosing the instant
--------------------

A map draws one instant. Name it by date, once for the whole gallery:

.. code-block:: toml

   [display]
   time = "2002-10-15"
   figures = ["seepage_map", "cross_section", "hydrograph"]

   [display.overrides.cross_section]
   orientation = "sn"

``time`` takes a date, ``"first"`` or ``"last"``. Each figure that draws one
instant draws the stress period that holds the date, so the same line names
October 2002 on a monthly run, on a daily run, and on the one period of the
steady stage of a calibration, with no override per grid or per phase. A
``time`` in ``[display.overrides.<figure>]`` wins over ``[display] time`` for
that figure. Figures over the whole record, a hydrograph or a budget, do not
take it.

Left unset, each figure keeps its own instant: the last period, or for the
stream-network maps the state their calibration criterion read. A date the
run does not hold, for example outside the window of a calibration phase,
skips the figure with the record the run covers. ``hmp config check`` refuses
a date outside ``[simulation.time]``.

The title and the PNG metadata name the period drawn (``time`` holds it as
an ISO interval, ``2002-10-01/2002-11-01``). A file written before this key
existed may say ``timestep = 33``: it still loads, as ``time = 33``, a period
index. Reading the file renames the key in memory only; ``hmp run --verbose``
logs the rename and ``hmp doctor --fix-config`` writes it to the file.

Console
-------

A run prints one line for its figures: how many were drawn and where. A
figure that does not apply to the run by nature, a calibration figure on a
plain run for instance, is counted there and named with its reason at
``--verbose``. The line is a warning only when you can act on a skipped
figure: a ``[simulation.results]`` option would have kept the field it needs,
or it failed while drawing.

Overlays
--------

Spatial figures accept an ``overlays`` list, so a composite map is a
configuration choice rather than a bespoke script:

.. code-block:: toml

   [display.overrides.watertable_depth_map]
   overlays = ["watershed", "seepage", "particles", "wells", "outlet"]

Available overlays: ``watershed`` (catchment outline), ``seepage``
(outcropping cells), ``particles`` (pathlines), ``network`` (reference
hydrographic network), ``wells`` (pumping and injection cells read from the
well budget) and ``outlet``. An overlay whose data the run does not carry is
logged and skipped, so the same declaration works across projects.

Map frame
---------

The seepage and stream maps (``seepage_map``, ``flow_persistence_map``,
``flow_intermittence_map``, ``seepage_network_confusion_map`` and their
siblings) open on the delineated catchment, in the project coordinates in
metres. The part of the frame outside the catchment outline stays visible
under a white veil, and the key counts the cells inside the outline.
``extent = "mesh"`` keeps the whole modelled domain and counts every cell:

.. code-block:: toml

   [display.overrides.flow_intermittence_map]
   extent = "mesh"

``seepage_map`` draws two classes, seepage and no seepage, with their cell
counts: the field is a yes or no per cell. The maps state the network
criterion in words under the map: "a cell counts as seepage above 0.01 % of
its recharge" is ``tau_specific_ratio = 1e-4``.

Calibration progress
--------------------

``calibration_progress`` ("How the search converged") draws a calibration
search on one 16:9 slide, run after run, for any method. It is drawn on a run
the calibration promoted and reads the session of that run's own phase:

- the value tried at each run, on a log axis for a log-transformed parameter,
  each marker coloured by the cost of its run (darker is better), the best run
  starred, and the range of runs within tolerance of the best as a band. A
  bisection also shades the bracket that closes on ``J = 0``;
- the cost of each run and the best so far, a staircase that only goes down.
  The axis names the metric and its unit, ``|D_so - D_os| (m)`` for
  ``distance_gap`` or ``1 - NSElog (-)`` for ``nse_log``, and a dashed line
  marks the run from which the search stays within tolerance of its best;
- what the search improves: for a network output, the cells the simulated
  seepage network finds, adds and misses against the mapped streams, with the
  size of the map as a dashed line; for a hydrograph, the efficiency itself
  (NSElog, NSE, KGE) rising toward its best;
- with two parameters, the runs in the parameter plane coloured by run order,
  each new best joined in order: a simplex walks downhill, a sampler explores
  then concentrates.

The tolerance is the calibration's own: ``[calibration.uncertainty]`` when it
writes one, else one mesh cell on a search scored on network distances in
metres, else five per cent of the best cost. A sentence under the panels says
what "better" means for the phase. ``session_id`` picks one session when the
run belongs to several, and ``output`` names the network output to count.

.. code-block:: bash

   hmp viz show <promoted_run> calibration_progress --output progress.png

Applicability rule
------------------

Figure names are stable entry points, but every figure depends on what the
run persisted. Each figure declares its requirements in its ``FigureSpec``
(``required_fields``, ``required_tables``, ``required_solvers``), and checks
what ``FigureSpec`` cannot say (a network, a DEM raster, hydrochemistry, the
series of a stream reach, a lake or a piezometer) itself. The display layer
asks before rendering: ``[display].figures`` skips the figure with an explicit
reason, and ``hmp viz show`` and ``hmp.figure`` refuse it with the same
sentence. A configuration can therefore list every figure it may want: a run
without particle tracking simply does not produce ``particle_tracks``.

``difference_map`` and ``side_by_side`` compare two runs. They are drawn from
Python, ``hmp.figure(run, "difference_map", reference=other_run)``, and say so
when ``reference`` is missing.

List the names and their requirements with:

.. code-block:: bash

   hmp viz list

Ask what one run supports, and why not the other figures, with:

.. code-block:: bash

   hmp viz list --run <sim_id>

To inspect what a given run actually holds:

.. code-block:: bash

   hmp catalog show <sim_id> --detail

For low-level display objects, see :doc:`../api/index`.
