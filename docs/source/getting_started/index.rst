Getting Started
===============

This section is the shortest guided entry point for HydroModPy. Use it when
you want to install the package, choose a first workflow, and run one
meaningful case without scanning the full documentation tree.

For most users, the default path is simple: choose the right first workflow,
run the data-overview case, then move to the end-to-end simulation case.

.. note::

   If you installed HydroModPy from PyPI, the package does not ship the
   repository ``examples/`` directory. Follow :doc:`../install` first, then use
   the guides below with a cloned repository or the downloaded source archive.

.. important::

   If you are unsure where to start, read :doc:`concepts_in_5_min` first,
   then :doc:`choose-your-first-workflow`, run :doc:`cli-quickstart`, and
   continue with :doc:`data-overview-walkthrough`.

Recommended entry points
------------------------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: concepts_in_5_min
      :link-type: doc

      **Concepts in 5 minutes**
      ^^^
      The five core concepts (Project, Run, Workflow, Catchment, Solver) the
      rest of the documentation assumes you have already met.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: choose-your-first-workflow
      :link-type: doc

      **Start here**
      ^^^
      Match your goal to the right first example: data-only setup, full
      simulation, comparison, or validation.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: cli-quickstart
      :link-type: doc

      **CLI quickstart**
      ^^^
      Scaffold a workspace, create a project, generate a config template,
      and run a simulation from the command line in five steps.

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

Default path
------------

1. Read :doc:`concepts_in_5_min` and :doc:`choose-your-first-workflow`.
2. Follow :doc:`cli-quickstart` to scaffold a workspace, create a project,
   and run a first simulation from the command line.
3. Run :doc:`data-overview-walkthrough` if you want to understand basin setup
   before touching any solver.
4. Continue with :doc:`simulation-walkthrough` for a complete end-to-end case.

Related sections
----------------

- :doc:`../user_guide/index` explains usage modes, workflow families,
  workspace layout, project/run concepts, comparison, calibration, meshes, and
  solver-choice routing.
- :doc:`../user_guide/data/index` explains data retrieval, public providers,
  custom files, cache inspection, lockfiles, and frozen runs.
- :doc:`read-real-basin-run` inventories what one committed real-basin run
  actually exposes through the Python API, and which outputs matter first when
  the question becomes ``EVT`` sensitivity rather than just page reading.
- :doc:`../examples/index` lists the full notebook and script inventory.
- :doc:`../capability_gallery/index` shows static, versioned result pages built
  from reproducible cases.

.. toctree::
   :hidden:
   :maxdepth: 1

   concepts_in_5_min
   choose-your-first-workflow
   cli-quickstart
   data-overview-walkthrough
   simulation-walkthrough
   read-real-basin-run
