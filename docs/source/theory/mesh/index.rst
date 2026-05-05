Mesh And Spatial Support
========================

This section groups the theory notes for mesh and spatial support
choices in HydroModPy.

Mesh choice is not only a preprocessing detail. It controls:

- which basin, river, geology, and boundary constraints are honoured;
- how fields are projected to solver cells;
- which numerical method is appropriate;
- whether solver comparisons isolate backend behaviour or mix backend and
  support effects.

Use this section for the concepts. Use the
:doc:`capability-gallery mesh pages </capability_gallery/mesh>` for concrete,
versioned examples and figures.

Scientific Role
---------------

HydroModPy separates the modelling problem into several layers:

.. code-block:: text

   geographic domain
   -> planar support or mesh
   -> vertical representation
   -> field-to-cell transfer
   -> solver-specific discretization
   -> validation or comparison evidence

That separation matters because the same physical question can be interpreted
on different supports:

- a structured ``sgrid`` support for legacy MODFLOW-NWT-style workflows;
- a MODFLOW 6 support that may remain structured or consume a DISV-style
  irregular mesh;
- a triangular finite-volume support used by the Boussinesq backend;
- a saved mesh bundle reused by comparison and gallery workflows.

Representative gallery evidence
--------------------------------

Mesh concepts are easier to read with concrete artifacts next to the text. The
full case pages remain in :doc:`/capability_gallery/mesh`; the figures below
are the minimum evidence to keep in mind while reading this section.

.. figure:: /_static/capability_gallery/mesh/mesh_quality_diagnostics_naizin_10km2.png
   :alt: Mesh quality diagnostics on a Naizin support
   :width: 100%

   Mesh quality diagnostics are not decorative. They are the checks that decide
   whether a discretization is acceptable before solver results are trusted.

.. figure:: /_static/capability_gallery/mesh/mesh_constraint_balance_scale_ladder.png
   :alt: Mesh constraint balance across catchment scales
   :width: 100%

   Constraint-balance figures show why mesh choices should be discussed as
   modelling assumptions, especially when hydrography, geology, and basin
   boundary constraints compete.

Main Questions
--------------

.. list-table::
   :header-rows: 1
   :widths: 30 38 32

   * - Question
     - Scientific page
     - Gallery evidence
   * - Which mesh families exist and why do they matter?
     - :doc:`../solvers/mesh-and-discretization-strategies`
     - :doc:`/capability_gallery/mesh`
   * - How do regular and irregular meshes compare for the same cell budget?
     - :doc:`regular-vs-irregular-meshes`
     - :doc:`/capability_gallery/cases/mesh_resolution_sensitivity_scale_ladder`
   * - How are geology, hydraulic properties, or forcing mapped to cells?
     - :doc:`../solvers/field-to-cell-parameter-transfer`
     - :doc:`/capability_gallery/hydraulic_properties`
   * - Which mesh quality checks should be read before trusting a solve?
     - :doc:`../solvers/mesh-quality-and-acceptance-criteria`
     - :doc:`/capability_gallery/cases/mesh_quality_diagnostics_naizin_10km2`
   * - Why does MODFLOW 6 use XT3D on irregular meshes?
     - :doc:`../solvers/xt3d-on-irregular-disv-meshes`
     - :doc:`/capability_gallery/cases/modflow6_irregular_tri_xt3d_method_choice`
   * - How does vertical representation affect storage and thickness?
     - :doc:`../solvers/vertical-representation-and-storage-assumptions`
     - Validation and comparison cases that reuse the same support.

Capability Gallery Contract
---------------------------

The capability gallery should not replace this section. Its role is different:

- it shows versioned mesh bundles and static figures;
- it exposes node, cell, edge, river, geology, and quality summaries;
- it provides reproducible commands and artifact paths;
- it documents what is already available, not the full method rationale.

The scientific mesh pages should explain how to interpret those gallery
artifacts. The gallery pages should link back here when the reader needs the
conceptual background.

Recommended Reading Order
-------------------------

For a new mesh-related question, read in this order:

1. :doc:`../solvers/mesh-and-discretization-strategies`
2. :doc:`regular-vs-irregular-meshes`
3. :doc:`../solvers/field-to-cell-parameter-transfer`
4. :doc:`../solvers/mesh-quality-and-acceptance-criteria`
5. :doc:`/capability_gallery/mesh`
6. One concrete case page, such as
   :doc:`/capability_gallery/cases/mesh_quality_diagnostics_naizin_10km2`

.. toctree::
   :maxdepth: 2

   Mesh and discretization strategies <../solvers/mesh-and-discretization-strategies>
   Regular and irregular mesh cell budgets <regular-vs-irregular-meshes>
   Field-to-cell parameter transfer <../solvers/field-to-cell-parameter-transfer>
   Mesh quality and acceptance criteria <../solvers/mesh-quality-and-acceptance-criteria>
   Vertical representation and storage assumptions <../solvers/vertical-representation-and-storage-assumptions>
   XT3D on irregular DISV meshes <../solvers/xt3d-on-irregular-disv-meshes>

Related Gallery Pages
---------------------

- :doc:`/capability_gallery/mesh`
- :doc:`/capability_gallery/cases/mesh_sample_bundle`
- :doc:`/capability_gallery/cases/mesh_quality_diagnostics_naizin_10km2`
- :doc:`/capability_gallery/cases/mesh_constraint_balance_scale_ladder`
- :doc:`/capability_gallery/cases/mesh_resolution_sensitivity_scale_ladder`
