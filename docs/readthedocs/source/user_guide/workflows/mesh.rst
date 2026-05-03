Mesh Workflow
=============

``workflow = "mesh"`` builds a catchment mesh as a first-class artifact. It
uses the geographic context and the ``[mesh_catchment]`` contract, but it does
not run a groundwater solver.

Use it when the question is:
"Is this discretization acceptable before I use it in simulations?"

Functional Role
---------------

The mesh workflow is designed to make discretization visible and reusable:

- delineate or load the catchment;
- choose an effective support domain;
- decide which constraints must be honored;
- generate a Gmsh mesh;
- export mesh files, summary JSON, figures, and optional exchange bundles;
- optionally loop over several outlets through ``[mesh_catchment_batch]``.

It is appropriate for:

- QA of river-conformal or geology-conformal meshes;
- preparing a reusable mesh before several solver runs;
- producing mesh figures for reports;
- testing mesh-size and refinement parameters without solver cost.

Typical Command
---------------

.. code-block:: bash

   hmp run path/to/mesh_workflow.toml

Current public examples mostly show ``[mesh_catchment]`` embedded in
``simulation`` TOMLs, for example:

- ``examples/projects/06_vire_selune/run_vire_mf6_irregular.toml``
- ``examples/projects/06_vire_selune/run_selune_mf6_irregular.toml``
- ``examples/projects/09_comparison_workflow/base_nancon_transient_seasonal.toml``

The dedicated ``workflow = "mesh"`` launcher uses the same
``[mesh_catchment]`` contract.

Representative Results
----------------------

.. figure:: /_static/capability_gallery/mesh/mesh_s3_10km2_outlet_3_geology_rivers_buffer30_overview.png
   :alt: Mesh overview result for a geology-plus-rivers catchment mesh
   :width: 100%

   The overview figure is the first QA view: it shows whether the watershed
   envelope and the enforced constraints are spatially coherent.

.. figure:: /_static/capability_gallery/mesh/mesh_s3_10km2_outlet_3_geology_rivers_buffer30_regional.png
   :alt: Regional mesh context result for a geology-plus-rivers catchment mesh
   :width: 100%

   The regional panel is useful when a locally plausible mesh still looks
   suspicious in its broader hydrographic or geological context.

Minimal Shape
-------------

.. code-block:: toml

   workflow = "mesh"

   [workspace]
   project_root = "outputs/mesh_demo"

   [geographic]
   catch_def = "from_outlet_coord"
   dem_init_path = "../../data/dem/DEM_armorican_massif.tif"
   x_outlet = 400866.1983
   y_outlet = 6923974.693
   buff_area = "20%"
   crs_project = "EPSG:2154"

   [mesh_catchment]
   constraints_mode = "rivers_only"
   output_layout = "flat"
   figures_enabled = true

   [mesh_catchment.zone_meshing]
   global_size = 2500.0
   min_size = 1200.0
   max_size = 4000.0

Important Parameters
--------------------

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Section / field
     - Role
     - Practical guidance
   * - ``workflow``
     - Selects the mesh-only launcher.
     - Use ``"mesh"`` when the mesh itself is the output.
   * - ``[geographic]``
     - Provides catchment geometry and DEM-derived context.
     - The mesh can only be trusted if outlet, CRS, DEM, and buffer are
       correct.
   * - ``[mesh_catchment].constraints_mode``
     - Selects enforced geometric constraints.
     - Use ``rivers_only`` for hydrographic alignment, ``geology_only`` for
       lithological interfaces, or ``geology_rivers`` for both.
   * - ``output_layout``
     - Controls where final artifacts are written.
     - ``flat`` is convenient for examples; ``standard`` keeps artifacts under
       the canonical project tree.
   * - ``figures_enabled``
     - Enables overview PNG outputs.
     - Keep enabled during QA; disable in headless or large batch runs.
   * - ``export_exchange_bundle``
     - Writes solver-exchange metadata.
     - Keep enabled when the mesh will feed MODFLOW 6 or Boussinesq.
   * - ``[mesh_catchment.rivers]``
     - Chooses river constraints.
     - Default ``source = "domain_geographic"`` reuses the in-memory river
       trace from geographic preprocessing.
   * - ``[mesh_catchment.geology]``
     - Provides geology polygons when geology constraints are active.
     - Required for ``geology_only`` and ``geology_rivers``.
   * - ``[mesh_catchment.watershed_boundary]``
     - Controls boundary conformity and refinement.
     - Enable it when the watershed boundary itself must be honored by mesh
       edges.
   * - ``[mesh_catchment.zone_meshing]``
     - Controls cell sizes and refinement.
     - Tune ``global_size``, ``min_size``, ``max_size``, interface size, and
       refinement policy.

Constraint Modes
----------------

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Mode
     - What it constrains
     - When to use it
   * - ``rivers_only``
     - River traces and optional watershed boundary.
     - Solver runs where stream-aquifer exchange geometry matters most.
   * - ``geology_only``
     - Lithological interfaces.
     - Conductivity zonation or geology-transfer experiments.
   * - ``geology_rivers``
     - Both geology and river constraints.
     - Final production meshes where both hydrography and heterogeneity must
       be represented.

Batch Mesh Variant
------------------

``[mesh_catchment_batch]`` repeats the same mesh recipe over an outlet table.
It is useful for preparing many catchment meshes with consistent settings.

.. code-block:: toml

   [mesh_catchment_batch]
   enabled = true
   outlets_table_path = "outlets.csv"
   outlet_id_column = "outlet_id"
   x_column = "x_outlet_m"
   y_column = "y_outlet_m"
   selection_mode = "selected"
   selected_outlet_ids = ["outlet_01", "outlet_02"]
   catch_name_pattern = "mesh_{outlet_id}"
   continue_on_error = false

Outputs To Inspect
------------------

Inspect mesh outputs before using the mesh in a simulation:

1. overview figure;
2. regional overview figure;
3. mesh summary JSON;
4. cell-size distribution and constraint diagnostics;
5. exchange bundle if a solver will consume the mesh.

Next Pages
----------

- :doc:`../mesh`
- :doc:`../../capability_gallery/mesh`
- :doc:`../../scientific/solvers/meshes-and-numerical-methods`
- :doc:`../../architecture/mesh/index`
