Getting Started
===============

This section is the guided entry point for HydroModPy. Use it when you want a
recommended first workflow instead of opening the full example inventory
directly.

.. note::

   If you installed HydroModPy from PyPI, the package does not ship the
   repository ``examples/`` directory. Follow :doc:`../install` first, then use
   the guides below with a cloned repository or the downloaded source archive.

Recommended entry points
------------------------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: choose-your-first-workflow
      :link-type: doc

      **Choose a workflow**
      ^^^
      Match your goal to the right first example: data-only setup, full
      simulation, comparison, or validation.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: data-overview-walkthrough
      :link-type: doc

      **Data overview walkthrough**
      ^^^
      Start with a no-solver workflow that extracts one basin and loads the
      main geographic data layers.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: simulation-walkthrough
      :link-type: doc

      **Simulation walkthrough**
      ^^^
      Follow one end-to-end MODFLOW 6 plus Gmsh case and map the main config
      sections to the displayed outputs.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: reading-results-pages
      :link-type: doc

      **Read result pages**
      ^^^
      Learn how to interpret capability-gallery pages, solver comparisons, and
      analytical validation pages.

Suggested order
---------------

1. Read :doc:`choose-your-first-workflow`.
2. Run :doc:`data-overview-walkthrough` if you want to understand basin setup
   before touching any solver.
3. Continue with :doc:`simulation-walkthrough` for a complete end-to-end case.
4. Use :doc:`reading-results-pages` when you start comparing methods or reading
   validation metrics.

Related sections
----------------

- :doc:`../examples` lists the full notebook and script inventory.
- :doc:`../capability_gallery/index` shows static, versioned result pages built
  from reproducible cases.

.. toctree::
   :hidden:
   :maxdepth: 1

   choose-your-first-workflow
   data-overview-walkthrough
   simulation-walkthrough
   reading-results-pages
