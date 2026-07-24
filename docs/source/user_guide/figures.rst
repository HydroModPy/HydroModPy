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

The lower-level registry stays available when you need the figure object
itself:

.. code-block:: python

   from hydromodpy.display import get, list_figures

   list_figures()
   get("piezometric_map").plot(run, save_path="head.png")

From the CLI:

.. code-block:: bash

   hmp viz list
   hmp viz show <sim_id> <figure>
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
They are the same keywords :func:`hydromodpy.figure` accepts:

.. code-block:: toml

   [display.overrides.cross_section]
   orientation = "sn"
   through = [152687.5, 6857800.0]

   [display.overrides.flux_timeseries]
   units = "mm/period"

Use ``hmp viz gallery project.toml`` to rerender all figures after a run,
``hmp viz show <sim_id> <figure>`` to rerender one figure, and
``--no-display`` during ``hmp run`` when the workflow should persist results
without rendering report figures.

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

Applicability rule
------------------

Figure names are stable entry points, but every figure depends on what the
run persisted. Each figure declares its requirements in its ``FigureSpec``
(``required_fields``, ``required_tables``, ``required_solvers``); the
display layer checks them before rendering and skips the figure with an
explicit reason when the run does not satisfy them. A configuration can
therefore list every figure it may want: a run without particle tracking
simply does not produce ``particle_tracks``.

List the names and their requirements with:

.. code-block:: bash

   hmp viz list

To inspect what a given run actually holds:

.. code-block:: bash

   hmp catalog show <sim_id> --detail

For low-level display objects, see :doc:`../api/index`.
