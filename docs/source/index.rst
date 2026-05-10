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

.. grid:: 1 2 4 4
   :gutter: 2 2 3 3
   :class-container: hmp-landing-cta

   .. grid-item-card:: Get started
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: getting_started/index
      :link-type: doc

      Install HydroModPy and run a first project end to end.

   .. grid-item-card:: Configuration
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: user_guide/config_reference/index
      :link-type: doc

      Every TOML section validated by ``HydroModPyConfig``,
      with fields, defaults and types.

   .. grid-item-card:: Case studies
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: capability_gallery/index
      :link-type: doc

      Validation figures, mesh illustrations and watershed
      diagnostics.

   .. grid-item-card:: API reference
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: api/index
      :link-type: doc

      Auto-generated reference for every public class,
      function and module.

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

If HydroModPy supports your work, please cite both the software and the
companion preprint (Gauvain et al., 2026, EGUsphere,
`doi:10.5194/egusphere-2026-868
<https://doi.org/10.5194/egusphere-2026-868>`_). Full BibTeX, RIS and
plain-text variants live on the :doc:`how_to_cite` page; ``CITATION.cff``
at the repository root is what GitHub renders behind the "Cite this
repository" button.

.. code-block:: bibtex

   @software{hydromodpy_software,
     title   = {HydroModPy: a Python toolbox for deploying catchment-scale shallow groundwater models},
     author  = {Gauvain, A. and Abherv\'e, R. and Boivin, B. and Roques, C. and
                Le Mesnil, M. and Coche, A. and Babey, T. and Mar\c{c}ais, J. and
                Bouchez, C. and Leray, S. and Marti, E. and Bresciani, E. and
                Figueroa, R. and P\'elissier, M. and Guillaumot, L. and
                Touzeau, T. and Issolah, I. and Maugan, E. and Bagagnan, R. S. and
                Vautier, C. and Sallou, J. and Bourcier, J. and Combemale, B. and
                Brunner, P. and Longuevergne, L. and Aquilina, L. and
                de Dreuzy, J.-R.},
     year    = {2026},
     url     = {https://github.com/HydroModPy/HydroModPy},
     license = {EPL-2.0}
   }

   @article{egusphere-2026-868,
     title   = {Technical note: HydroModPy -- a Python toolbox for deploying catchment-scale shallow groundwater models},
     author  = {Gauvain, A. and Abherv\'e, R. and Boivin, B. and Roques, C. and
                Le Mesnil, M. and Coche, A. and Babey, T. and Mar\c{c}ais, J. and
                Bouchez, C. and Leray, S. and Marti, E. and Bresciani, E. and
                Figueroa, R. and P\'elissier, M. and Guillaumot, L. and
                Touzeau, T. and Issolah, I. and Maugan, E. and Bagagnan, R. S. and
                Vautier, C. and Sallou, J. and Bourcier, J. and Combemale, B. and
                Brunner, P. and Longuevergne, L. and Aquilina, L. and
                de Dreuzy, J.-R.},
     journal = {EGUsphere},
     year    = {2026},
     volume  = {2026},
     pages   = {1--31},
     doi     = {10.5194/egusphere-2026-868}
   }

Linked publications and a registry of catchments where HydroModPy has been
deployed live on :doc:`usage_bibliography` and :doc:`applications`.

Where to go next
----------------

.. important::

   Most first-time users should follow this order:

   1. :doc:`getting_started/index` (install + first run)
   2. :doc:`user_guide/index` (workflows, configuration, theory)
   3. :doc:`capability_gallery/index` (validated case studies)

If you are looking for technical documentation, code-reading guides, module
diagrams, or UML pages, use :doc:`architecture/index`. If you are looking for
equations, modelling assumptions, or method notes, use
:doc:`user_guide/index` and follow the Theory section.

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

.. grid:: 1 2 3 3
   :gutter: 2 2 3 3

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: getting_started/index
      :link-type: doc

      **Get started**
      ^^^
      Install HydroModPy, scaffold a workspace, and run a first end-to-end
      simulation in five steps.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: user_guide/index
      :link-type: doc

      **User Guide**
      ^^^
      Usage modes, workflow families, cookbook, and the theory backing
      each solver.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: user_guide/config_reference/index
      :link-type: doc

      **Configuration**
      ^^^
      Every TOML section validated by ``HydroModPyConfig``: fields,
      defaults, types, plus the JSON Schema explorer.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: capability_gallery/index
      :link-type: doc

      **Gallery**
      ^^^
      Static mesh illustrations, validation figures, and watershed
      diagnostics curated for documentation and teaching.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: api/index
      :link-type: doc

      **API Reference**
      ^^^
      Auto-generated reference for every public class, function, and module
      under ``hydromodpy``.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: architecture/index
      :link-type: doc

      **Developer**
      ^^^
      Architecture, code-reading maps, component and class diagrams,
      developer notes, and contributing guidelines.

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: about/index
      :link-type: doc

      **About**
      ^^^
      How to cite HydroModPy, papers using the toolbox, and field
      applications across catchments.

Install
-------

.. code-block:: bash

   pip install hydromodpy

For detailed instructions see the :doc:`installation guide <install>`.
If you plan to add new features, check the :doc:`contributor setup <contribute>`.

Authors and affiliations
------------------------

A. Gauvain\ :sup:`1,2`, R. Abhervé\ :sup:`1,3,4`, B. Boivin\ :sup:`1`,
C. Roques\ :sup:`3`, M. Le Mesnil\ :sup:`1`, A. Coche\ :sup:`1`,
T. Babey\ :sup:`1`, J. Marçais\ :sup:`5`, C. Bouchez\ :sup:`1`,
S. Leray\ :sup:`6`, E. Marti\ :sup:`6`, E. Bresciani\ :sup:`7`,
R. Figueroa\ :sup:`3`, M. Pélissier\ :sup:`3`, L. Guillaumot\ :sup:`8`,
T. Touzeau\ :sup:`1`, I. Issolah\ :sup:`11`, E. Maugan\ :sup:`1`,
R. S. Bagagnan\ :sup:`1`, C. Vautier\ :sup:`1`, J. Sallou\ :sup:`9`,
J. Bourcier\ :sup:`10`, B. Combemale\ :sup:`11`, P. Brunner\ :sup:`3`,
L. Longuevergne\ :sup:`1`, L. Aquilina\ :sup:`1`,
J.-R. de Dreuzy\ :sup:`1`.

- :sup:`1` Geosciences Rennes - UMR 6118, CNRS, Université de Rennes, Rennes, France
- :sup:`2` Laboratoire de Météorologie Dynamique (LMD), CNRS, Sorbonne Université, Paris, France
- :sup:`3` Centre for Hydrogeology and Geothermics (CHYN), Université de Neuchâtel, Neuchâtel, Switzerland
- :sup:`4` UMR SAS 1069, INRAE, Centre Bretagne-Normandie, Rennes, France
- :sup:`5` UR RiverLy, INRAE, Centre Lyon-Grenoble Auvergne-Rhône-Alpes, Villeurbanne, France
- :sup:`6` Pontificia Universidad Católica de Chile, Santiago, Chile
- :sup:`7` Instituto de Ciencias de la Ingeniería, Universidad de O'Higgins, Rancagua, Chile
- :sup:`8` BRGM, F-45060 Orléans, France
- :sup:`9` INF, Wageningen University & Research, Wageningen, Netherlands
- :sup:`10` ISA/LIUPPA, Université de Pau et des Pays de l'Adour, Pau, France
- :sup:`11` Inria, IRISA, CNRS, Université de Rennes, Rennes, France

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
   Get started <getting_started/index>
   User Guide <user_guide/index>
   Gallery <capability_gallery/index>
   API Reference <api/index>
   Developer <architecture/index>
   About <about/index>

.. # HTML helpers
.. |br| raw:: html

   <br>
