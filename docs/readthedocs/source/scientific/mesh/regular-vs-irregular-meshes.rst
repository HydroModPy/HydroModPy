Regular And Irregular Mesh Cell Budgets
=======================================

Purpose
-------

This page gives a visual entry point for comparing regular and irregular mesh
families.

It answers two different questions that should not be mixed:

1. What does "same number of cells" mean when one mesh is regular and the other
   is irregular?
2. What do the currently versioned HydroModPy catchment meshes look like in
   terms of cell-count budget?

The first question is answered with a controlled synthetic figure. The second
question is answered with committed HydroModPy mesh-gallery artifacts.

Same Cell Count, Different Topology
-----------------------------------

The figure below is intentionally synthetic. It is not a HydroModPy production
mesh. Its role is to make one point visible before opening basin-specific
figures:

   equal cell count does not mean equal discretization.

.. figure:: /_static/scientific/mesh/regular_irregular_same_cell_counts.svg
   :alt: Regular and irregular meshes with identical cell counts
   :width: 100%

   Each row uses the same number of cells on the left and right. The left side
   uses structured quadrilateral cells. The right side uses triangular cells
   with irregular internal vertices. The cell budget is identical, but
   topology, edge orientation, neighbour structure, and boundary alignment are
   different.

.. list-table::
   :header-rows: 1
   :widths: 20 30 30 20

   * - Cell budget
     - Regular example
     - Irregular example
     - Main lesson
   * - 16 cells
     - 4 x 4 quadrilateral grid
     - 16 triangular cells
     - Coarse comparison; topology dominates.
   * - 64 cells
     - 8 x 8 quadrilateral grid
     - 64 triangular cells
     - Same count, different neighbour graph.
   * - 144 cells
     - 12 x 12 quadrilateral grid
     - 144 triangular cells
     - More cells do not remove support semantics.

Reading rule:

- use equal cell counts to control memory and rough solve size;
- do not use equal cell counts as a guarantee of equal accuracy;
- always report cell type, boundary alignment, field transfer, and quality
  metrics alongside cell count.

Versioned HydroModPy Mesh Budgets
---------------------------------

The next figure is not synthetic. It reads cell-count metrics from committed
capability-gallery summary JSON files.

.. figure:: /_static/scientific/mesh/real_mesh_cell_count_balance.svg
   :alt: Cell-count balance for versioned HydroModPy catchment meshes
   :width: 100%

   These are irregular catchment meshes from the mesh gallery. They should be
   read as current evidence for mesh-size budgets, not as a regular-versus-
   irregular controlled experiment.

.. list-table::
   :header-rows: 1
   :widths: 28 18 18 18 18

   * - Versioned case
     - Nodes
     - Cells
     - River edges
     - Geology interfaces
   * - 10 km2, outlet 1, geology + rivers
     - 283
     - 547
     - 65
     - 80
   * - 100 km2, outlet 27, floor 340 m / target 200 m
     - 1684
     - 3324
     - 458
     - 294
   * - 100 km2, outlet 27, floor 200 m / target 200 m
     - 1802
     - 3560
     - 458
     - 321
   * - 100 km2, outlet 27, default geology + rivers
     - 1981
     - 3922
     - 631
     - 332
   * - 1000 km2, outlet 2, geology + rivers
     - 19078
     - 38030
     - 6739
     - 1744

The important reading is not "more cells is better". The useful reading is:

- which constraints were active;
- how many cells were needed to represent them;
- how much of the cell budget is driven by rivers, geology, and basin boundary;
- whether the added cells are located where the scientific question needs
  resolution.

Controlled Size-Floor Pair
--------------------------

The 100 km2 outlet-27 pair below is useful because the two committed cases keep
the same outlet and the same river target, but change the global size floor.

.. grid:: 1 1 2 2
   :gutter: 2

   .. grid-item-card:: Floor 200 m, target 200 m

      .. figure:: /_static/capability_gallery/mesh/mesh_headwater_100km2_outlet_27_geology_rivers_buffer30_floor200_target200_overview.png
         :alt: Headwater 100 km2 outlet 27 mesh with floor 200 m and river target 200 m
         :width: 100%

      Cells: ``3560``. River edges: ``458``. Geology interfaces: ``321``.

   .. grid-item-card:: Floor 340 m, target 200 m

      .. figure:: /_static/capability_gallery/mesh/mesh_headwater_100km2_outlet_27_geology_rivers_buffer30_floor340_target200_overview.png
         :alt: Headwater 100 km2 outlet 27 mesh with floor 340 m and river target 200 m
         :width: 100%

      Cells: ``3324``. River edges: ``458``. Geology interfaces: ``294``.

This is currently the best committed example for explaining mesh-size effects:

- the river target remains ``200 m`` in both cases;
- the global floor changes;
- the realized cell count and interface count change;
- the visual difference should therefore be read as a size-floor effect before
  it is read as a physics or solver effect.

Existing Gallery Pages To Reuse
-------------------------------

The page above is a short guided view. Use the gallery pages for the complete
case records:

- :doc:`/capability_gallery/mesh`
- :doc:`/capability_gallery/cases/mesh_resolution_sensitivity_scale_ladder`
- :doc:`/capability_gallery/cases/mesh_constraint_balance_scale_ladder`
- :doc:`/capability_gallery/cases/mesh_quality_diagnostics_naizin_10km2`
- :doc:`/capability_gallery/cases/mesh_headwater_100km2_outlet_27_geology_rivers_buffer30_floor200_target200`
- :doc:`/capability_gallery/cases/mesh_headwater_100km2_outlet_27_geology_rivers_buffer30_floor340_target200`

What Is Still Missing For The Ideal Comparison
----------------------------------------------

The ideal page requested by the modelling workflow is not fully versioned yet.
It would compare, on the same basin and the same plotting extent:

- a structured regular grid;
- an irregular catchment-conformal mesh;
- several target cell budgets;
- matched or near-matched active-cell counts.

The controlled production protocol should be:

1. choose one basin support, preferably Nancon or one 100 km2 headwater case;
2. choose target budgets, for example about ``500``, ``2000``, ``8000`` cells;
3. generate regular structured grids whose active cells match those budgets as
   closely as possible;
4. generate irregular Gmsh meshes by searching the global size parameters until
   cell counts are close to the same budgets;
5. render each pair on the same extent, with the same hydrography and geology
   overlays;
6. publish a summary table with cells, nodes, river edges, geology interfaces,
   area percentiles, and quality percentiles;
7. only then use the paired supports for solver comparisons.

That future page should be a new capability-gallery case family, not only a
hand-written note. The reason is reproducibility: cell counts and figures
should be regenerated from committed mesh bundles and summary JSON, not edited
manually.
