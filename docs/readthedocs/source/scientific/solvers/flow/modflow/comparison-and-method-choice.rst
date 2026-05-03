MODFLOW Comparison And Method Choice
====================================

This page groups the MODFLOW-family material used when choosing between
``flow/modflow6`` and ``flow/modflownwt`` or when interpreting a comparison.

Core Comparison Notes
---------------------

.. toctree::
   :maxdepth: 1

   ../../modflow6-vs-modflownwt-scientific-comparison
   ../../xt3d-on-irregular-disv-meshes
   ../../mesh-and-discretization-strategies
   ../../vertical-representation-and-storage-assumptions

Decision Map
------------

.. list-table::
   :header-rows: 1
   :widths: 34 33 33

   * - Question
     - Prefer ``flow/modflow6``
     - Prefer ``flow/modflownwt``
   * - Do I need runtime irregular mesh support?
     - Yes.
     - No; structured ``sgrid`` only.
   * - Do I need MODFLOW 6 GWT transport?
     - Yes.
     - No.
   * - Do I need MODPATH or MT3DMS continuity?
     - Usually no.
     - Yes.
   * - Am I reproducing a legacy structured study?
     - Only if intentionally comparing.
     - Often yes.
   * - Is XT3D relevant?
     - Yes, especially on irregular DISV-style meshes.
     - No.

Comparison Discipline
---------------------

Before attributing a difference to the solver backend, document:

- grid topology and resolution,
- vertical layer assumptions,
- parameter transfer from fields to cells,
- boundary-condition semantics,
- temporal aggregation and stress-period setup,
- whether the compared outputs are raw cell values or collapsed profiles.

Related Pages
-------------

- :doc:`common-concepts`
- :doc:`modflow6`
- :doc:`modflownwt`
- :doc:`worked-cases`
