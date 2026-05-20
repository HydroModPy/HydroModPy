hmp.overview
============

Run the overview workflow declared by a TOML file.

Signature
---------

.. code-block:: python

   hmp.overview(config, **kwargs) -> Any

Reference
---------

.. autofunction:: hydromodpy.overview
   :no-index:

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   summary = hmp.overview("overview.toml")

See Also
--------

- :func:`hydromodpy.run` -- generic workflow launcher.
- :mod:`hydromodpy.workflow` -- workflow dispatcher and pipelines.
