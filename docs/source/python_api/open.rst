hmp.open
========

Open a project catalog backed by ``.hmp/index.duckdb``. The argument is
a **project** directory, the one holding ``project.toml`` and
``.hmp/index.duckdb``, not the workspace root above it. With the default
``create=False`` it raises ``FileNotFoundError`` when no index
exists; pass ``create=True`` to initialise an empty catalog. The default
open is read-only; pass ``read_only=False`` for a writable handle.

Signature
---------

.. code-block:: python

   hmp.open(workspace, *, create=False, read_only=True) -> Catalog

Reference
---------

.. autofunction:: hydromodpy.open
   :no-index:

Example
-------

.. code-block:: python

   import hydromodpy as hmp

   catalog = hmp.open("~/hmp_workspace/projects/naizin")
   latest = catalog.latest()

See Also
--------

- :func:`hydromodpy.read` -- read a variable from a run returned
  by the catalog.
- :mod:`hydromodpy.results` -- catalog and run result implementations.
