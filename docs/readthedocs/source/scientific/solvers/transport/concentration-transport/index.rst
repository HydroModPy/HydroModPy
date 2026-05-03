Concentration Transport Internals
=================================

This section structures the concentration-transport documentation inside the
``transport`` process.

Concentration transport answers questions such as:

- how a species moves after the flow field is solved;
- how longitudinal and transverse dispersivity affect spreading;
- how input concentration and decay change downstream concentrations;
- how MODFLOW-NWT-linked and MODFLOW 6-linked concentration routes differ.

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
   :caption: Common concentration part
   :maxdepth: 2

   common-parameters

.. toctree::
   :caption: Backend versions
   :maxdepth: 2

   mt3dms
   modflow6gwt

.. toctree::
   :caption: Comparison and selection
   :maxdepth: 1

   method-choice

Related Pages
-------------

- :doc:`../common-concepts`
- :doc:`../particle-tracking`
- :doc:`../../flow/modflow/transport-coupling`
- :doc:`../../../../architecture/solver/transport/index`
