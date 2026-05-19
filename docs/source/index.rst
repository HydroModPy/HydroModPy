:html_theme.sidebar_secondary.remove:

|br|

HydroModPy
==========

.. raw:: html

   <p class="lead">
   A Python toolbox for automated, reproducible, catchment-scale modeling of
   shallow groundwater. One TOML configuration drives MODFLOW 6, MODFLOW-NWT,
   Boussinesq, and GR4J on the same hydrology, from DEM to calibrated heads
   and streams.
   </p>

.. container:: hmp-badges

   .. image:: https://img.shields.io/badge/version-1.0.0-22c55e?style=flat-square
      :target: https://github.com/HydroModPy/HydroModPy/releases
      :alt: Version 1.0.0

   .. image:: https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776AB?style=flat-square&logo=python&logoColor=white
      :target: https://www.python.org/downloads/
      :alt: Python 3.11-3.13

   .. image:: https://img.shields.io/badge/license-EPL--2.0-2563eb?style=flat-square
      :target: https://github.com/HydroModPy/HydroModPy/blob/master/LICENSE
      :alt: License EPL-2.0

   .. image:: https://img.shields.io/readthedocs/hydromodpy/dev?style=flat-square&logo=readthedocs&logoColor=white&label=docs
      :target: https://hydromodpy.readthedocs.io/
      :alt: Documentation status

   .. image:: https://img.shields.io/badge/code%20style-ruff-D7FF64?style=flat-square&logo=ruff&logoColor=black
      :target: https://docs.astral.sh/ruff/
      :alt: Code style ruff

   .. image:: https://img.shields.io/badge/DOI-10.5194%2Fegusphere--2026--868-f59e0b?style=flat-square&logo=doi&logoColor=white
      :target: https://doi.org/10.5194/egusphere-2026-868
      :alt: DOI preprint EGUsphere

   .. image:: https://img.shields.io/github/stars/HydroModPy/HydroModPy?style=flat-square&logo=github&color=181717
      :target: https://github.com/HydroModPy/HydroModPy
      :alt: GitHub stars

.. grid:: 1 2 4 4
   :gutter: 2 2 3 3
   :class-container: hmp-landing-cta

   .. grid-item-card:: Install
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: install
      :link-type: doc

      ``pip install hydromodpy`` or use the conda environment, then
      check the prerequisites.

   .. grid-item-card:: Get started
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: getting_started/index
      :link-type: doc

      Concepts in five minutes, then a first end-to-end project on a
      real basin.

   .. grid-item-card:: Configuration
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: user_guide/config_reference/index
      :link-type: doc

      Every TOML section validated by ``HydroModPyConfig``, with
      fields, defaults, and types.

   .. grid-item-card:: API reference
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4 hmp-cta-card
      :link: api/index
      :link-type: doc

      Auto-generated reference for every public class, function, and
      module under ``hydromodpy``.

What HydroModPy does
--------------------

Physically based groundwater models remain expensive to deploy at the
catchment scale: data wrangling, mesh design, parameterization, calibration,
and post-processing rarely follow a uniform path from one site to the next.
HydroModPy was built to close that gap. It turns the construction,
execution, calibration, and analysis of unconfined shallow groundwater
models into a single scriptable workflow that can be replayed across many
catchments with consistent inputs and outputs.

The toolbox automates the steps that usually consume the most time:

#. **Watershed extraction** from digital elevation models, with the
   geospatial backbone provided by WhiteboxTools and the standard
   geospatial Python stack.
#. **Forcing preparation**: spatial and temporal recharge, climate inputs,
   and observation ingestion (groundwater heads, stream networks,
   intermittency patterns).
#. **Mesh and vertical discretization** suited to shallow basement
   aquifers, plus parameter assignment and steady or transient runs.
#. **Calibration and validation** that combine subsurface heads with
   surface signals (active stream networks, intermittency) to constrain
   hydraulic properties.
#. **Standard, FAIR-aligned exports** with provenance metadata, plus
   built-in visualization and notebook integration for teaching and
   reproducible analyses.

Originally a FloPy-driven MODFLOW-NWT toolbox, HydroModPy now ships a
multi-solver architecture, a Pydantic-validated configuration, and a
columnar storage stack (DuckDB catalog, Zarr fields, Parquet tables) that
make end-to-end runs reproducible and inspectable.

Highlights
----------

.. grid:: 1 2 3 3
   :gutter: 2 2 3 3

   .. grid-item-card:: Multi-solver core
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4

      MODFLOW 6, MODFLOW-NWT, Boussinesq, and GR4J behind a single
      adapter layer. Optional MODPATH and MT3DMS for particle tracking
      and solute transport.

   .. grid-item-card:: TOML-first interface
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: user_guide/config_reference/index
      :link-type: doc

      One ``HydroModPyConfig`` root, every field typed and validated
      by Pydantic v2. The CLI ``hmp`` runs the same config without any
      Python.

   .. grid-item-card:: Catchment automation
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: user_guide/index
      :link-type: doc

      DEM-driven watershed delineation, recharge forcing, mesh and
      vertical discretization, observation ingestion, all from one
      configuration.

   .. grid-item-card:: Calibration and validation
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: user_guide/workflows/calibration
      :link-type: doc

      Heads, stream networks, and intermittency patterns combined into
      reproducible calibration loops with provenance tracking.

   .. grid-item-card:: FAIR-aligned outputs
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: user_guide/results-and-exports
      :link-type: doc

      DuckDB catalog, Zarr field arrays, Parquet tables, and standard
      geospatial formats with metadata for interoperability.

   .. grid-item-card:: Gallery and teaching
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: capability_gallery/index
      :link-type: doc

      Validation figures, mesh illustrations, and notebook examples
      curated for documentation, training, and decision support.

What's new
----------

Recent entries from ``CHANGELOG.md``:

- **v0.3.3** (2025-12-03): lightweight conda environment option, surface
  routing consolidated under ``masstransfer``, leaner SIM2 memory use.
- **v0.3.2** (2025-11-28): SIM2 reworked with coarse-clip then reproject,
  ``disk_clip`` accepts ``.shp``, ``.gpkg``, ``.geojson``.
- **v0.3.1** (2025-11-14): installation guide reorganized, dual YAML
  options for runtime versus editable installs, NumPy >= 2 baseline.

See the full :doc:`changelog <about/changelog>` and the :doc:`roadmap
<about/roadmap>` for upcoming work.

How to cite
-----------

If HydroModPy supports your work, please cite both the software and the
companion technical note (Gauvain et al., 2026, EGUsphere,
`doi:10.5194/egusphere-2026-868
<https://doi.org/10.5194/egusphere-2026-868>`_).
The :doc:`how_to_cite` page lists BibTeX, RIS, and plain-text variants;
``CITATION.cff`` at the repository root is what GitHub renders behind the
"Cite this repository" button.

.. dropdown:: BibTeX entries
   :icon: book

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

Linked publications and a registry of catchments where HydroModPy has
been deployed live on :doc:`usage_bibliography` and :doc:`applications`.

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
      Install HydroModPy, scaffold a workspace, and run a first
      end-to-end simulation in five steps.

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
      Auto-generated reference for every public class, function, and
      module under ``hydromodpy``.

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

Authors and contact
-------------------

.. dropdown:: Authors and affiliations
   :icon: people

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

For questions or collaboration requests, contact:

- Alexandre Gauvain, ``alexandre.gauvain.ag@gmail.com``
- Ronan Abhervé, ``ronan.abherve@gmail.com``
- Bug reports and feature requests: `GitHub issues
  <https://github.com/HydroModPy/HydroModPy/issues>`_
- Discussions: `Google Group <https://groups.google.com/g/hydromodpy>`_

.. toctree::
   :hidden:
   :maxdepth: 1
   :titlesonly:

   Home <self>
   Get started <getting_started/index>
   User Guide <user_guide/index>
   Python API <python_api/index>
   CLI <cli/index>
   OO Patterns <oo/index>
   Gallery <capability_gallery/index>
   API Reference <api/index>
   Developer <architecture/index>
   About <about/index>

.. # HTML helpers
.. |br| raw:: html

   <br>
