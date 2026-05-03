Concentration Transport Internals
=================================

This section structures the concentration-transport documentation inside the
``transport`` process.

Concentration transport answers questions such as:

- how a species moves after the flow field is solved;
- how longitudinal and transverse dispersivity affect spreading;
- how input concentration and decay change downstream concentrations;
- how MODFLOW-NWT-linked and MODFLOW 6-linked concentration routes differ.

The hierarchy follows the same pattern as the ``flow`` solver pages:

1. common concentration equation and parameters;
2. MODFLOW-NWT version: MT3DMS downstream from ``flow/modflownwt``;
3. MODFLOW 6 version: GWT downstream from ``flow/modflow6``.

Current Concentration Backends
------------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 28 44

   * - Process/solver pair
     - Backend family
     - Required upstream flow
   * - ``transport/mt3dms``
     - MT3DMS.
     - Earlier ``flow/modflownwt`` run.
   * - ``transport/modflow6gwt``
     - MODFLOW 6 GWT.
     - Earlier ``flow/modflow6`` run.

.. toctree::
   :caption: Common concentration equation and parameters
   :maxdepth: 2

   ../equations-and-unknowns
   common-parameters

.. toctree::
   :caption: MODFLOW-NWT version
   :maxdepth: 2

   mt3dms

.. toctree::
   :caption: MODFLOW 6 version
   :maxdepth: 2

   modflow6gwt

.. toctree::
   :caption: Comparison and selection
   :maxdepth: 1

   method-choice

Related Pages
-------------

- :doc:`../common-concepts`
- :doc:`../modflow-nwt-transport`
- :doc:`../modflow6-transport`
- :doc:`../particle-tracking`
- :doc:`../../flow/modflow/transport-coupling`
- :doc:`../../../../architecture/solver/transport/index`
