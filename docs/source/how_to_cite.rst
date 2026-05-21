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
     title   = {HydroModPy: a Python toolbox for deploying catchment-scale shallow groundwater models},
     author  = {Gauvain, A. and Abherv{\'e}, R. and Boivin, B. and Roques, C. and
                Le Mesnil, M. and Coche, A. and Babey, T. and Mar{\c c}ais, J. and
                Bouchez, C. and Leray, S. and Marti, E. and Bresciani, E. and
                Figueroa, R. and P{\'e}lissier, M. and Guillaumot, L. and
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
     author  = {Gauvain, A. and Abherv{\'e}, R. and Boivin, B. and Roques, C. and
                Le Mesnil, M. and Coche, A. and Babey, T. and Mar{\c c}ais, J. and
                Bouchez, C. and Leray, S. and Marti, E. and Bresciani, E. and
                Figueroa, R. and P{\'e}lissier, M. and Guillaumot, L. and
                Touzeau, T. and Issolah, I. and Maugan, E. and Bagagnan, R. S. and
                Vautier, C. and Sallou, J. and Bourcier, J. and Combemale, B. and
                Brunner, P. and Longuevergne, L. and Aquilina, L. and
                de Dreuzy, J.-R.},
     journal = {EGUsphere},
     volume  = {2026},
     year    = {2026},
     pages   = {1--31},
     doi     = {10.5194/egusphere-2026-868},
     url     = {https://egusphere.copernicus.org/preprints/2026/egusphere-2026-868/}
   }

RIS
---

.. code-block:: text

   TY  - JOUR
   TI  - Technical note: HydroModPy – a Python toolbox for deploying catchment-scale shallow groundwater models
   AU  - Gauvain, Alexandre
   AU  - Abhervé, Ronan
   AU  - Boivin, Bastien
   AU  - Roques, Clément
   AU  - Le Mesnil, Martin
   AU  - Coche, Alexandre
   AU  - Babey, Tristan
   AU  - Marçais, Jean
   AU  - Bouchez, Camille
   AU  - Leray, Sarah
   AU  - Marti, Etienne
   AU  - Bresciani, Etienne
   AU  - Figueroa, Ronny
   AU  - Pélissier, Mathias
   AU  - Guillaumot, Luca
   AU  - Touzeau, Théa
   AU  - Issolah, Imene
   AU  - Maugan, Enzo
   AU  - Bagagnan, Rock S.
   AU  - Vautier, Camille
   AU  - Sallou, June
   AU  - Bourcier, Johan
   AU  - Combemale, Benoit
   AU  - Brunner, Philip
   AU  - Longuevergne, Laurent
   AU  - Aquilina, Luc
   AU  - de Dreuzy, Jean-Raynald
   JO  - EGUsphere
   PY  - 2026
   VL  - 2026
   SP  - 1
   EP  - 31
   DO  - 10.5194/egusphere-2026-868
   UR  - https://egusphere.copernicus.org/preprints/2026/egusphere-2026-868/
   ER  -

Plain text
----------

.. code-block:: text

   Gauvain, A., Abhervé, R., Boivin, B., Roques, C., Le Mesnil, M., Coche, A.,
   Babey, T., Marçais, J., Bouchez, C., Leray, S., Marti, E., Bresciani, E.,
   Figueroa, R., Pélissier, M., Guillaumot, L., Touzeau, T., Issolah, I.,
   Maugan, E., Bagagnan, R. S., Vautier, C., Sallou, J., Bourcier, J.,
   Combemale, B., Brunner, P., Longuevergne, L., Aquilina, L., & de Dreuzy, J.-R.
   (2026). Technical note: HydroModPy – a Python toolbox for deploying
   catchment-scale shallow groundwater models. EGUsphere [preprint], 1–31.
   https://doi.org/10.5194/egusphere-2026-868

Authors and affiliations
------------------------

The companion paper lists 27 co-authors across Geosciences Rennes
(Université de Rennes, CNRS), CHYN Neuchâtel, INRAE, LMD Sorbonne, BRGM,
Pontificia Universidad Católica de Chile, Universidad de O'Higgins,
Wageningen University & Research, Université de Pau et des Pays de
l'Adour, and Inria/IRISA. The complete author list with ORCIDs and
affiliations is maintained in ``CITATION.cff`` at the repository root.

Contact details for collaboration requests are kept on the
:doc:`landing page <index>`.

A persistent DOI for the project will be issued through Zenodo at the
first tagged release. Each release will receive its own version DOI so
results can be reproduced against a specific snapshot of the codebase.

Reproducibility
---------------

HydroModPy writes ``hydromodpy.lock`` on a best-effort basis when input
fingerprints and cache metadata are available. Frozen replay treats the
lock as mandatory; normal runs without enough cache evidence emit a
reproducibility warning instead of failing.

When citing a specific result, please report the package version and
the solver binary version (``hmp version``) in addition to the entries
above.
