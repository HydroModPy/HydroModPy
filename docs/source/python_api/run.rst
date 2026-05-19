hmp.run
=======

Run a HydroModPy workflow from a TOML path or a validated config object.

Signature
---------

.. code-block:: python

   hmp.run(config, **kwargs) -> Any

Reference
---------

.. autofunction:: hydromodpy.run

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   result = hmp.run("run_transient_nwt.toml", name="baseline")

See Also
--------

- :func:`hydromodpy.calibrate` -- dedicated calibration launcher.
- :func:`hydromodpy.overview` -- overview workflow launcher.
- :func:`hydromodpy.compare` -- comparison workflow launcher.
- :mod:`hydromodpy.workflow` -- workflow dispatcher and pipelines.
