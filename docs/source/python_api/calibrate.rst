hmp.calibrate
=============

Run a calibration workflow from a TOML file or a validated config object.

Signature
---------

.. code-block:: python

   hmp.calibrate(config, **kwargs) -> Any

Reference
---------

.. autofunction:: hydromodpy.calibrate
   :no-index:

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   report = hmp.calibrate("calibration.toml")

See Also
--------

- :func:`hydromodpy.run` -- generic workflow launcher.
- :func:`hydromodpy.report` -- render the HTML report for a
  calibration session.
- :mod:`hydromodpy.calibration` -- calibration package and report types.
