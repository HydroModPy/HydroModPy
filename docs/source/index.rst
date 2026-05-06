|br|

HydroModPy
==========

.. raw:: html

   <p class="lead">
   Catchment-scale shallow groundwater modeling in Python. One TOML config drives
   MODFLOW 6, MODFLOW-NWT, Boussinesq and GR4J on the same hydrology.
   </p>

.. image:: https://img.shields.io/badge/license-EPL--2.0-blue
   :alt: License EPL-2.0
.. image:: https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue
   :alt: Python 3.11-3.13
.. image:: https://img.shields.io/badge/version-1.0.0-success
   :alt: Version 1.0.0
.. image:: https://readthedocs.org/projects/hydromodpy/badge/?version=dev
   :alt: Documentation status
.. image:: https://img.shields.io/badge/DOI-pending--Zenodo-orange
   :alt: DOI pending Zenodo

.. grid:: 1 1 3 3
   :gutter: 2 2 3 3
   :class-container: hmp-landing-cta

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 sd-text-center sd-bg-primary sd-text-white
      :link: getting_started/index
      :link-type: doc

      Get started

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 sd-text-center
      :link: capability_gallery/index
      :link-type: doc

      View gallery

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 sd-text-center
      :link: api/index
      :link-type: doc

      API reference

What HydroModPy does
--------------------

HydroModPy was initiated in 2018 to streamline the deployment of hydrological
models in catchments across the crystalline basement regions of Normandy and
Brittany, France. The platform integrates a wide range of open-source packages
(FloPy, whitebox-workflows, etc.), making them easily accessible and shareable
among scientific communities.

The development of HydroModPy was driven by two primary objectives:

#. First, it automates the extraction and discretization of watersheds from
   Digital Elevation Models (DEMs), while adding essential data available
   (e.g. piezometry, hydrography, geology) from local data to national and
   global databases. This ensures a standardized process for setting up and
   running simulation batches across different watersheds with uniform input
   data.
#. The second goal is to facilitate the visualization and comparison of
   results from the various modeling programs included within the platform. In
   addition to its scientific applications, HydroModPy also serves as a
   valuable educational tool, enabling students and researchers to explore
   hydrogeological modeling in a practical context.

.. dropdown:: Abstract for the IAH 2024 congress

   The need for predictive models increases as the pressure of global change
   intensifies. Regional-scale modeling of shallow unconfined aquifers
   (10-100 m depth) remains challenging, especially in complex basement
   aquifers. Controlled both by topography and geology, groundwater flows are
   organized from hillslope to catchment scale. It is particularly the case in
   crystalline regions with low aquifer volumes and wet climates, resulting
   in significant subsurface-surface interactions with very few information
   available to constrain models.

   To address this, we present HydroModPy, an application developed in Python
   as a toolbox for automatic deployment of groundwater flow models.
   HydroModPy integrates geospatial processing (WhiteBoxTools) with
   groundwater flow and transport simulation tools (MODFLOW and MODPATH via
   FloPy). It is designed to call other groundwater flow solvers, facilitate
   multi-site deployment, integrate pre- and post-processing functions such as
   catchment extraction from a DEM and an advanced representation of head and
   flow results.

What's new
----------

Recent changes from the public ``CHANGELOG.md``:

- **v0.3.3** (2025-12-03) lightweight conda environment option, surface
  routing consolidated under ``masstransfer``, leaner SIM2 memory use.
- **v0.3.2** (2025-11-28) reworked SIM2 with coarse clip then reproject,
  ``disk_clip`` accepts ``.shp``, ``.gpkg``, ``.geojson``.
- **v0.3.1** (2025-11-14) installation guide reorganized, dual YAML options
  for runtime versus editable installs, NumPy >= 2 baseline.

How to cite HydroModPy
----------------------

If HydroModPy supports your work, please cite the software (BibTeX below)
and the companion paper currently in preparation. Full BibTeX, RIS and
plain-text variants live on the :doc:`how_to_cite` page; ``CITATION.cff`` at
the repository root is what GitHub renders behind the "Cite this repository"
button.

.. code-block:: bibtex

   @software{hydromodpy_software,
     title  = {HydroModPy: a Python toolbox for deploying catchment-scale shallow groundwater models},
     author = {Gauvain, A. and Abherv\'e, R. and de Dreuzy, J.-R. and others},
     year   = {2025},
     url    = {https://github.com/HydroModPy/HydroModPy},
     license = {EPL-2.0}
   }

Linked publications and a registry of catchments where HydroModPy has been
deployed live on :doc:`usage_bibliography` and :doc:`applications`.

Where to go next
----------------

.. important::

   Most first-time users should follow this order:

   1. :doc:`install`
   2. :doc:`getting_started/index`
   3. :doc:`user_guide/index`
   4. :doc:`examples/index`
   5. :doc:`capability_gallery/index`

If you are looking for technical documentation, code-reading guides, module
diagrams, or UML pages, use :doc:`architecture/index`. If you are looking for
equations, modelling assumptions, or method notes, use :doc:`theory/index`.

If you are specifically looking for streams, seepage, observed hydrography,
or simulation-derived active networks, use the map
:doc:`theory/streams_and_seepage/index`. For a concrete simulation result,
open :doc:`theory/streams_and_seepage/nancon-k-sweep-results`.

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
      :link: user_guide/cookbook/index
      :link-type: doc

      **Cookbook**
      ^^^
      Ten short TOML-first recipes covering the most common HydroModPy tasks.

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
      :link: migration/index
      :link-type: doc

      **Migration**
      ^^^
      Map every removed or renamed entry point from v0 to its 1.x
      counterpart.

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
