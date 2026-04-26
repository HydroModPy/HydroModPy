Model Calibration - superseded
==============================

.. note::

   The ``ModelCalibrationLauncher`` architecture described on this page has
   been retired. HydroModPy's calibration now runs through the unified
   ``hmp run <calibration.toml>`` dispatcher, backed by the trial primitive
   in :mod:`hydromodpy.simulation.execution.trial` and the CLI in
   :mod:`hydromodpy.calibration.cli`.

For the current architecture, user guide, TOML reference, optimizer
catalogue, reporting commands, and Python API, see:

- ``docs/developers/calibration_guide.md`` - end-to-end user guide.
- :mod:`hydromodpy.calibration` - the calibration package (engine,
  parameters, objective, optimizer registry, diagnostics, cases).
- :mod:`hydromodpy.simulation.execution.trial` - the prepare-once /
  evaluate-many primitive used by every trial inside the ask/tell loop.

This stub page is kept so existing cross-references resolve; future doc
builds should reroute readers directly to the calibration guide.
