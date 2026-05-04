Cross-Cutting MODFLOW Pages
===========================

This section groups the MODFLOW pages that are not specific to only one
backend version. Read it after the common concepts and after the page for the
backend you use.

Use this section for three recurring tasks:

- choosing between ``flow/modflow6`` and ``flow/modflownwt``;
- reading executable worked cases;
- understanding how MODFLOW flow outputs feed transport solvers.

Cross-Cutting Topics
--------------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Topic
     - Role
   * - Comparison and method choice
     - Helps separate backend effects from mesh, support, vertical
       representation, package semantics, and temporal aggregation effects.
   * - Worked cases
     - Links scientific assumptions to concrete TOML inputs, assembled
       MODFLOW packages, and inspected outputs.
   * - Transport coupling
     - Explains which transport solver can consume each MODFLOW-family flow
       field.

.. toctree::
   :maxdepth: 1

   Comparison and method choice <../../../modflow6-vs-modflownwt-scientific-comparison>
   Nancon transient NWT worked case <../../../worked-modflow-case-nancon-transient-nwt-etp-evt>
   Package semantics and boundary conditions <../../../modflow-package-semantics-and-boundary-conditions>

Related Sub-Categories
----------------------

- :doc:`../common/index`
- :doc:`../modflow6-version/index`
- :doc:`../modflownwt-version/index`
