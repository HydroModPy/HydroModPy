|br|

Welcome to HydroModPy
=====================

HydroModPy was initiated in 2018 to streamline the deployment of hydrological
models in catchments across the crystalline basement regions of Normandy and
Brittany, France. The platform integrates a wide range of open-source packages
(FloPy, whitebox-workflows, etc.), making them easily accessible and shareable
among scientific communities.

The development of HydroModPy was driven by two primary objectives:

#. First, it automates the extraction and discretization of watersheds from
   Digital Elevation Models (DEMs), while adding essential data available
   (e.g. piezometry, hydrography, geology) from local data to national and global
   databases. This ensures a standardized process for setting up and running
   simulation batches across different watersheds with uniform input data.
#. The second goal is to facilitate the visualization and comparison of results
   from the various modeling programs included within the platform. In addition
   to its scientific applications, HydroModPy also serves as a valuable
   educational tool, enabling students and researchers to explore hydrogeological
   modeling in a practical context.

.. dropdown:: Abstract for the congress IAH 2024

   The need for predictive models increases as the pressure of global change intensifies. Regional-scale modeling of shallow unconfined aquifers (10-100 m depth) remains challenging, especially in complex basement aquifers. Controlled both by topography and geology, groundwater flows are organized from hillslope to catchment scale. It is particularly the case in crystalline regions with low aquifer volumes and wet climates, resulting in significant subsurface-surface interactions with very few information available to constrain models.

   To address this, we present HydroModPy, an application developed in Python as a toolbox for automatic deployment of groundwater flow models. HydroModPy integrates geospatial processing (WhiteBoxTools) with groundwater flow and transport simulation tools (MODFLOW and MODPATH via FloPy). It is designed to call other groundwater flow solvers, facilitate multi-site deployment, integrate pre- and post-processing functions such as catchment extraction from a DEM and an advanced representation of head and flow results. Emphasis is placed on integrating aquifer geometry complexities and hydraulic properties heterogeneity (compartmentalization, exponential decay, implementation of a 3D geological model, etc.).

   HydroModPy's user-friendly Python interface allows for testing and exploring various aquifer models across different geomorphological contexts and recharge conditions. Ongoing improvements include methods for calibrating and estimating hydraulic properties using multiple datasets such as hydrographic network maps, streamflow, and piezometric level data. HydroModPy is developed as an open-source toolkit. It is currently being used in climate change effects on groundwater-dependent ecosystems and water resource management issues. Collaborative development should enhance the modeling capacity of near-surface aquifers, facilitate their extension to the regional scale for predictive purposes.

First visit
-----------

.. important::

   Most first-time users should follow this order:

   1. :doc:`install`
   2. :doc:`getting_started/index`
   3. :doc:`user_guide/index`
   4. :doc:`examples/index`
   5. :doc:`capability_gallery/index`

Use :doc:`getting_started/index` when you want the shortest first-run path.
Use :doc:`user_guide/index` when you need operational concepts such as usage
modes, workflow families, workspace layout, comparison, calibration, meshes, or
solver choice. Use :doc:`examples/index` when you already know that you want the full
notebook and script inventory. Use :doc:`capability_gallery/index` when you
want stable, curated result pages before running anything locally.

If you are looking for technical documentation, code-reading guides, module
diagrams, or UML pages, use :doc:`architecture/index`. If you are looking for
equations, modelling assumptions, or method notes, use
:doc:`theory/index`.

If you are specifically looking for streams, seepage, observed hydrography, or
simulation-derived active networks, use the map
:doc:`theory/streams_and_seepage/index`. It points to the scientific
semantics, the computed ``simulated_active`` views, comparison outputs,
developer diagrams, and example figures from one place. For a concrete
simulation result, open
:doc:`theory/streams_and_seepage/nancon-k-sweep-results`.

If you specifically want the quality ladder used in the repository, including
the usual commands for unit, integration, regression, validation, PETSc, and
manual benchmark runs, start with
:doc:`architecture/overview/test-families-and-quality-roles`.

Documentation map
-----------------

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: install
      :link-type: doc

      **Installation**
      ^^^
      Pip, conda, and offline installation paths plus verification steps.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: getting_started/index
      :link-type: doc

      **Quickstart**
      ^^^
      Short path from installation to a first project, a data overview, and one
      end-to-end simulation.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: user_guide/index
      :link-type: doc

      **User guide**
      ^^^
      Usage modes, workflow families, workspace layout, project/run concepts,
      comparison, calibration, meshes, and solver-choice routing.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: examples/index
      :link-type: doc

      **Examples**
      ^^^
      Coming soon: TOML-first walkthroughs and migrated example notebooks.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: capability_gallery/index
      :link-type: doc

      **Case studies**
      ^^^
      Static mesh illustrations, validation figures, and watershed diagnostics
      curated for documentation and teaching.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: theory/index
      :link-type: doc

      **Theory**
      ^^^
      Method notes, solver equations, and modelling assumptions separated from
      the software architecture.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: theory/streams_and_seepage/index
      :link-type: doc

      **Streams and seepage**
      ^^^
      One map for observed stream networks, seepage, drainage outflow,
      simulated active networks, figures, metrics, and developer diagrams.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: architecture/index
      :link-type: doc

      **Developer guide**
      ^^^
      Technical documentation, code-reading maps, component diagrams, class
      diagrams, activity diagrams, and runtime handoff views.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: api/index
      :link-type: doc

      **API reference**
      ^^^
      Auto-generated reference for every public class, function, and module
      under ``hydromodpy``.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: contribute
      :link-type: doc

      **Contributors**
      ^^^
      Development guidelines, testing expectations, and release process.

Install
-------

.. code-block:: bash

   pip install hydromodpy

For detailed instructions see the :doc:`installation guide <install>`.
If you plan to add new features, check the :doc:`contributor setup <contribute>`.

Research use and citation
-------------------------

.. raw:: html

   <style>
   /* allow line wrapping in code blocks (applies to this page only) */
   .highlight pre,
   pre.literal-block,
   .code,
   code {
     white-space: pre-wrap !important;
     word-wrap: break-word !important;
     overflow-wrap: anywhere !important;
   }
   </style>

If HydroModPy supports your work, please cite:

.. code-block:: text

   Gauvain, A., Abhervé, R., Coche, A., Le Mesnil, M., Roques, C., Bouchez, C., Marçais, J., Leray, S., Marti, E., Figueroa, R., Bresciani, E., Vautier, C., Boivin, B., Sallou, J., Bourcier, J., Combemale, B., Longuevergne, L., Aquilina, L., & de Dreuzy, J.-R. (2025). HydroModPy - a Python toolbox for deploying catchment-scale shallow groundwater models. Hydrology and Earth System Sciences. In preparation.

Linked publications
-------------------

- Abhervé, R., Roques, C., de Dreuzy, J.-R., Van Der Veen, T., Dumaine, L., Chatton, E., Brunner, P., Aquilina, L., & Servière, L. (2025). *Projected climate change impacts on groundwater-surface water connectivity in a compartmentalized mountain headwater bedrock aquifer*. Water Resources Research, 61(10). https://doi.org/10.1029/2025WR040083
- Marti, E., Leray, S., & Roques, C. (2024). *Catchment landforms predict groundwater-dependent wetland sensitivity to recharge changes*. Hydrology and Earth System Sciences Discussions. https://doi.org/10.5194/HESS-2024-381
- Floriancic, M. G., Abhervé, R., Bouchez, C., Martinez, J. J., & Roques, C. (2024). *Evidence of Groundwater Seepage and Mixing at the Vicinity of a Knickpoint in a Mountain Stream*. Geophysical Research Letters, 51. https://doi.org/10.1029/2024GL111325
- Le Mesnil, M., Gauvain, A., Gresselin, F., Aquilina, L., & de Dreuzy, J. (2024). *Characterizing coastal aquifer heterogeneity from a single piezometer head chronicle*. Journal of Hydrology, 131859. https://doi.org/10.1016/j.jhydrol.2024.131859
- Abhervé, R., Roques, C., de Dreuzy, J.-R., Datry, T., Brunner, P., Longuevergne, L., & Aquilina, L. (2024). *Improving calibration of groundwater flow models using headwater streamflow intermittence*. Hydrological Processes, 38(6). https://doi.org/10.1002/hyp.15167
- Abhervé, R., Roques, C., Gauvain, A., Longuevergne, L., Louaisil, S., Aquilina, L., & de Dreuzy, J.-R. (2023). *Calibration of groundwater seepage against the spatial distribution of the stream network to assess catchment-scale hydraulic properties*. Hydrology and Earth System Sciences, 27(17), 3221-3239. https://doi.org/10.5194/hess-27-3221-2023

Corresponding authors
---------------------

For any question or collaboration request, contact:

- Alexandre Gauvain - ``alexandre.gauvain.ag@gmail.com``
- Ronan Abhervé - ``ronan.abherve@gmail.com``

.. toctree::
   :hidden:
   :maxdepth: 1
   :titlesonly:

   Home <self>
   install
   Quickstart <getting_started/index>
   user_guide/index
   examples/index
   Case Studies <capability_gallery/index>
   Theory <theory/index>
   Architecture <architecture/index>
   Developer Notes <developer/index>
   API Reference <api/index>
   How to cite <how_to_cite>
   Papers using HydroModPy <usage_bibliography>
   Applications <applications>
   Migration <migration/index>
   contribute

.. # HTML helpers
.. |br| raw:: html

   <br>
