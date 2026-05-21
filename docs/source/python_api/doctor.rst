hmp.doctor
==========

Lightweight environment diagnostic. Returns a dict describing Python,
HydroModPy, optional packages, and solver executables. No solver is
invoked.

Signature
---------

.. code-block:: python

   hmp.doctor() -> dict

Reference
---------

.. autofunction:: hydromodpy.doctor
   :no-index:

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   info = hmp.doctor()
   print(info["hydromodpy"])
   print(info["solvers"])

See Also
--------

- :mod:`hydromodpy.core.version` -- HydroModPy version string.
