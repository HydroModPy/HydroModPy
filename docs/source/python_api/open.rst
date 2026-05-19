hmp.open
========

Open a workspace catalog backed by ``catalog.duckdb``.

Signature
---------

.. code-block:: python

   hmp.open(workspace_path) -> SimulationCatalog

Reference
---------

.. autofunction:: hydromodpy.open

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   catalog = hmp.open("~/hmp_workspace")
   latest = catalog.latest()

See Also
--------

- :func:`hydromodpy.open_catalog` -- V1 catalog facade fronting
  the three DuckDB files.
- :func:`hydromodpy.read` -- read a variable from a run returned
  by the catalog.
- :mod:`hydromodpy.results` -- catalog and run result implementations.
