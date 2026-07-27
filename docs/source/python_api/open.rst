hmp.open
========

Open a project catalog backed by ``.hmp/index.duckdb``. With the default
``create=False`` it raises ``FileNotFoundError`` when no index
exists; pass ``create=True`` to initialise an empty catalog.

Signature
---------

.. code-block:: python

   hmp.open(workspace_path, *, create=False) -> Catalog

Reference
---------

.. autofunction:: hydromodpy.open
   :no-index:

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   catalog = hmp.open("~/hmp_workspace")
   latest = catalog.latest()

See Also
--------

- :func:`hydromodpy.read` -- read a variable from a run returned
  by the catalog.
- :mod:`hydromodpy.results` -- catalog and run result implementations.
