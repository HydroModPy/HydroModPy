Concentration Transport Method Choice
=====================================

This page groups the main choice between ``transport/mt3dms`` and
``transport/modflow6gwt``.

Decision Map
------------

.. list-table::
   :header-rows: 1
   :widths: 34 33 33

   * - Question
     - Prefer ``transport/mt3dms``
     - Prefer ``transport/modflow6gwt``
   * - Is the upstream flow run MODFLOW-NWT?
     - Yes.
     - No.
   * - Is the upstream flow run MODFLOW 6?
     - No.
     - Yes.
   * - Do I need continuity with older MT3DMS studies?
     - Usually yes.
     - Only for explicit comparison.
   * - Do I need MODFLOW 6 GWT alignment?
     - No.
     - Yes.
   * - Am I comparing transport methods?
     - Only after documenting the upstream MODFLOW-NWT setup.
     - Only after documenting the upstream MODFLOW 6 setup.

Comparison Discipline
---------------------

Before attributing a difference to the concentration transport solver,
document:

- upstream flow backend;
- mesh topology and resolution;
- vertical representation;
- stress periods;
- recharge and boundary semantics;
- shared concentration parameter values;
- output metric or concentration slice being compared.

Related Pages
-------------

- :doc:`common-parameters`
- :doc:`mt3dms`
- :doc:`modflow6gwt`
