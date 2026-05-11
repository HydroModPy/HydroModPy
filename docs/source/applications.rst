Geographic application map
==========================

Where HydroModPy has been deployed. The map below catalogues the
catchments covered by published or in-preparation studies built on
HydroModPy. Each entry links to the corresponding gallery case when
available.

The interactive Leaflet variant of this map is on the Phase 3 roadmap.
For now the page provides a structured table and a static schematic
ordered by region.

.. mermaid::

   flowchart LR
       subgraph Brittany
           N[Nançon]
           V[Vire-Sélune]
           P[Ploémeur]
       end
       subgraph Normandy
           NB[Normandy basement]
       end
       subgraph Switzerland
           CH[Alpine knickpoint]
       end

Catchment registry
------------------

.. list-table::
   :header-rows: 1
   :widths: 18 12 12 28 30

   * - Catchment
     - Region
     - Country
     - Solver(s)
     - Reference
   * - Nançon
     - Brittany
     - France
     - MODFLOW-NWT, MODFLOW 6, Boussinesq
     - :doc:`theory/streams_and_seepage/nancon-k-sweep-results`
   * - Vire-Sélune
     - Normandy
     - France
     - MODFLOW 6
     - Abhervé et al. 2023, HESS, https://doi.org/10.5194/hess-27-3221-2023
   * - Ploémeur
     - Brittany
     - France
     - MODFLOW 6 (3D extension in preparation)
     - Abhervé et al. 2025, WRR, https://doi.org/10.1029/2025WR040083
   * - Mountain knickpoint catchment
     - Alpine
     - Switzerland
     - Boussinesq
     - Floriancic et al. 2024, GRL, https://doi.org/10.1029/2024GL111325
   * - Coastal aquifer (single piezometer)
     - Coastal Brittany
     - France
     - MODFLOW 6
     - Le Mesnil et al. 2024, J. Hydrology, https://doi.org/10.1016/j.jhydrol.2024.131859

Methodology references
----------------------

A consolidated bibliography of papers that build on HydroModPy is
seeded below. It will be promoted to a dedicated usage bibliography
page once the ``[docs] - add usage bibliography`` step lands.

- Abhervé, R., Roques, C., Gauvain, A., Longuevergne, L., Louaisil, S.,
  Aquilina, L., & de Dreuzy, J.-R. (2023). Calibration of groundwater
  seepage against the spatial distribution of the stream network.
  *Hydrology and Earth System Sciences*, 27(17), 3221-3239.
  https://doi.org/10.5194/hess-27-3221-2023
- Abhervé, R., Roques, C., de Dreuzy, J.-R., Datry, T., Brunner, P.,
  Longuevergne, L., & Aquilina, L. (2024). Improving calibration of
  groundwater flow models using headwater streamflow intermittence.
  *Hydrological Processes*, 38(6).
  https://doi.org/10.1002/hyp.15167
- Abhervé, R., Roques, C., de Dreuzy, J.-R., Van Der Veen, T., Dumaine, L.,
  Chatton, E., Brunner, P., Aquilina, L., & Servière, L. (2025). Projected
  climate change impacts on groundwater-surface water connectivity in a
  compartmentalized mountain headwater bedrock aquifer. *Water Resources
  Research*, 61(10). https://doi.org/10.1029/2025WR040083
- Floriancic, M. G., Abhervé, R., Bouchez, C., Martinez, J. J., &
  Roques, C. (2024). Evidence of Groundwater Seepage and Mixing at the
  Vicinity of a Knickpoint in a Mountain Stream. *Geophysical Research
  Letters*, 51. https://doi.org/10.1029/2024GL111325
- Le Mesnil, M., Gauvain, A., Gresselin, F., Aquilina, L., & de Dreuzy, J.
  (2024). Characterizing coastal aquifer heterogeneity from a single
  piezometer head chronicle. *Journal of Hydrology*, 131859.
  https://doi.org/10.1016/j.jhydrol.2024.131859
- Marti, E., Leray, S., & Roques, C. (2024). Catchment landforms predict
  groundwater-dependent wetland sensitivity to recharge changes.
  *Hydrology and Earth System Sciences Discussions*.
  https://doi.org/10.5194/HESS-2024-381

How to add a site
-----------------

Send a pull request that adds a row to the table above and the
matching BibTeX entry under ``docs/source/theory/references.bib``.
Include the catchment name, region, country, solver(s) used, and the
DOI when available. The interactive map will pick up the same
metadata once the Leaflet integration ships.
