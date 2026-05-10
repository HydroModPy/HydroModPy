Figure Catalog
==============

Figures live in ``hydromodpy.display`` and consume the persisted
:class:`hydromodpy.results.run.Run` interface. They are solver-agnostic: the
same figure name can render MODFLOW-NWT, MODFLOW 6, or Boussinesq outputs when
the required result fields exist.

Basic usage
-----------

.. code-block:: python

   from hydromodpy.display import get, list_figures

   list_figures()
   get("piezometric_map").plot(run, save_path="head.png")

From the CLI:

.. code-block:: bash

   hmp display <sim_id>
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

Simulation configurations can request report figures through the display
section. Exact options depend on the current configuration schema:

.. code-block:: toml

   [display]
   figures = ["piezometric_map", "water_budget", "simulated_active_network"]

Use ``hmp display <sim_id>`` to rerender figures after a run, and use
``--no-display`` during ``hmp run`` when the workflow should persist results
without rendering report figures.

Compatibility rule
------------------

Figure names are stable entry points, but every figure still depends on data
being present in the run store. If a figure cannot render, inspect the run first
with:

.. code-block:: bash

   hmp inspect <sim_id>
   hmp show <sim_id>

For low-level display objects, see :doc:`../api/index`.
