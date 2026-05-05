Calibration
===========

This section documents the scientific side of HydroModPy calibration.

It complements the architecture pages by answering different questions:

- what inverse problem is being solved,
- how objective values are constructed,
- what each built-in calibration method actually does numerically,
- how to interpret a best-fit result versus a distribution of models.

The scope here is the calibration stack implemented in
``hydromodpy.calibration``, exposed through the ``hmp run
<calibration.toml>`` CLI workflow.

.. toctree::
   :maxdepth: 2

   inverse-problem-formulation
   calibration-methods
