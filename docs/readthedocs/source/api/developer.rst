Developer API
=============

Use this layer when you extend HydroModPy itself. These pages expose pipeline
contracts and internal objects that are useful for contributors.

Reference Groups
----------------

.. grid:: 1 1 2 3
   :gutter: 2 2 3 3

   .. grid-item-card::
      :class-card: hmp-api-card sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydromodpy-workflow-pipeline
      :link-type: doc

      **Workflow and pipeline**
      ^^^
      Simulation planning, workflow context, pipeline states, steps, and
      derived computation contracts.

   .. grid-item-card::
      :class-card: hmp-api-card sd-shadow-sm sd-rounded-3 sd-p-4
      :link: hydromodpy-tools
      :link-type: doc

      **Tools**
      ^^^
      Shared helper functions that remain documented after the package
      relocation.

   .. grid-item-card::
      :class-card: hmp-api-card sd-shadow-sm sd-rounded-3 sd-p-4
      :link: docstring-policy
      :link-type: doc

      **Docstring policy**
      ^^^
      Rules for keeping generated API pages readable without hand-maintaining
      every object page.

Stability Rule
--------------

Developer pages may expose objects that are not stable user API. If an
internal object becomes useful for users or scientific scripts, promote it to
the user or scientific layer and document the canonical import path there.

Developer API Pages
-------------------

.. toctree::
   :maxdepth: 2
   :titlesonly:

   hydromodpy-workflow-pipeline
   hydromodpy-tools
   docstring-policy
