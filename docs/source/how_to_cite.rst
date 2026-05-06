How to cite HydroModPy
======================

If HydroModPy supports your work, please cite both the software and the
companion paper. Three formats are provided below, each with a copy
button enabled by ``sphinx-copybutton``.

A machine-readable ``CITATION.cff`` file lives at the repository root.
GitHub renders a "Cite this repository" button from it automatically.

BibTeX
------

.. code-block:: bibtex

   @software{hydromodpy_software,
     title        = {HydroModPy: a Python toolbox for deploying catchment-scale shallow groundwater models},
     author       = {Gauvain, Alexandre and Abherv{\'e}, Ronan and Coche, Antoine and
                     Le Mesnil, Martin and Roques, Cl{\'e}ment and Bouchez, Camille and
                     Mar{\c c}ais, Jean and Leray, Sarah and Marti, Eliana and
                     Figueroa, Rodrigo and Bresciani, Etienne and Vautier, Camille and
                     Boivin, Bastien and Sallou, June and Bourcier, Johann and
                     Combemale, Benoit and Longuevergne, Laurent and Aquilina, Luc and
                     de Dreuzy, Jean-Raynald},
     year         = {2025},
     url          = {https://github.com/HydroModPy/HydroModPy},
     license      = {EPL-2.0}
   }

   @article{hydromodpy_paper,
     title   = {HydroModPy: a Python toolbox for deploying catchment-scale shallow groundwater models},
     author  = {Gauvain, Alexandre and Abherv{\'e}, Ronan and Coche, Antoine and
                Le Mesnil, Martin and Roques, Cl{\'e}ment and Bouchez, Camille and
                Mar{\c c}ais, Jean and Leray, Sarah and Marti, Eliana and
                Figueroa, Rodrigo and Bresciani, Etienne and Vautier, Camille and
                Boivin, Bastien and Sallou, June and Bourcier, Johann and
                Combemale, Benoit and Longuevergne, Laurent and Aquilina, Luc and
                de Dreuzy, Jean-Raynald},
     journal = {Hydrology and Earth System Sciences},
     year    = {2025},
     note    = {In preparation}
   }

RIS
---

.. code-block:: text

   TY  - COMP
   TI  - HydroModPy: a Python toolbox for deploying catchment-scale shallow groundwater models
   AU  - Gauvain, Alexandre
   AU  - Abhervé, Ronan
   AU  - Coche, Antoine
   AU  - Le Mesnil, Martin
   AU  - Roques, Clément
   AU  - Bouchez, Camille
   AU  - Marçais, Jean
   AU  - Leray, Sarah
   AU  - Marti, Eliana
   AU  - Figueroa, Rodrigo
   AU  - Bresciani, Etienne
   AU  - Vautier, Camille
   AU  - Boivin, Bastien
   AU  - Sallou, June
   AU  - Bourcier, Johann
   AU  - Combemale, Benoit
   AU  - Longuevergne, Laurent
   AU  - Aquilina, Luc
   AU  - de Dreuzy, Jean-Raynald
   PY  - 2025
   UR  - https://github.com/HydroModPy/HydroModPy
   ER  -

Plain text
----------

.. code-block:: text

   Gauvain, A., Abhervé, R., Coche, A., Le Mesnil, M., Roques, C., Bouchez, C.,
   Marçais, J., Leray, S., Marti, E., Figueroa, R., Bresciani, E., Vautier, C.,
   Boivin, B., Sallou, J., Bourcier, J., Combemale, B., Longuevergne, L.,
   Aquilina, L., & de Dreuzy, J.-R. (2025). HydroModPy: a Python toolbox for
   deploying catchment-scale shallow groundwater models. Hydrology and Earth
   System Sciences. In preparation.

Authors and affiliations
------------------------

The companion paper lists the corresponding authors of the toolbox.
Contact details for collaboration requests are kept on the
:doc:`landing page <index>`.

A persistent DOI for the project will be issued through Zenodo at the
first tagged release. Each release will receive its own version DOI so
results can be reproduced against a specific snapshot of the codebase.

Reproducibility
---------------

Each HydroModPy run writes a ``hydromodpy.lock`` file alongside the
results. The lock pins the package version, the solver binaries, and
the resolved configuration tree, so a published result can be
reproduced from the same TOML config.

When citing a specific result, please report the package version and
the solver binary version (``hmp version``) in addition to the entries
above.
