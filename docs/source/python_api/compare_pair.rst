hmp.compare_pair
================

Compare two simulations by id or result object.

Signature
---------

.. code-block:: python

   hmp.compare_pair(sim_a, sim_b, *, workspace=None) -> pandas.DataFrame

Reference
---------

.. autofunction:: hydromodpy.compare_pair
   :no-index:

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   table = hmp.compare_pair("ab12cd34", "ef56gh78", workspace="~/hmp_workspace")

See Also
--------

- :func:`hydromodpy.compare` -- comparison workflow driven by a TOML config.
- :func:`hydromodpy.open` -- open a workspace to resolve simulation ids.
- :mod:`hydromodpy.analysis.comparison` -- comparison package.
