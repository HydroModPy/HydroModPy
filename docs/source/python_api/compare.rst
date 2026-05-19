hmp.compare
===========

Run the comparison workflow declared by a TOML file.

Signature
---------

.. code-block:: python

   hmp.compare(config) -> Any

Reference
---------

.. autofunction:: hydromodpy.compare

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   summary = hmp.compare("comparison.toml")

See Also
--------

- :func:`hydromodpy.compare_pair` -- pairwise metric table between
  two persisted simulations.
- :func:`hydromodpy.run` -- generic workflow launcher.
- :mod:`hydromodpy.analysis.comparison` -- comparison package.
