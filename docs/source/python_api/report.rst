hmp.report
==========

Render the HTML report for a calibration session.

Signature
---------

.. code-block:: python

   hmp.report(session_id_or_prefix=None, *, workspace=None) -> Any

Reference
---------

.. autofunction:: hydromodpy.report
   :no-index:

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   # Latest session in the nearest workspace
   hmp.report()

   # Explicit session and workspace
   hmp.report("ab12cd34", workspace="~/hmp_workspace")

See Also
--------

- :func:`hydromodpy.calibrate` -- run the calibration that produces
  the session.
- :func:`hydromodpy.open` -- open the workspace catalog used to
  resolve session ids.
- :mod:`hydromodpy.calibration` -- calibration package.
